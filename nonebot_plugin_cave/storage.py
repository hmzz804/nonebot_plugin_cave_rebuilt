import json
import random
import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Activity, CaveEntry, CaveNotFound, CaveState, CooldownActive, InvalidState

_UNIT_SECONDS = {"sec": 1, "min": 60, "hour": 3600}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CaveRepository:
    """Transactional storage and domain rules for the global cave pool."""

    def __init__(
        self,
        data_dir: Path,
        initial_reviewers: Iterable[str] = (),
        default_cooldown: int = 1,
        default_unit: str = "sec",
    ) -> None:
        if default_unit not in _UNIT_SECONDS or not 0 < default_cooldown < 500:
            raise ValueError("invalid default cooldown")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.image_dir = self.data_dir / "pictures"
        self.image_dir.mkdir(exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.data_dir / "cave.db", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._default_cooldown = default_cooldown
        self._default_unit = default_unit
        self._create_schema()
        with self._db:
            self._db.executemany(
                "INSERT OR IGNORE INTO reviewers(user_id) VALUES (?)",
                ((str(user_id),) for user_id in initial_reviewers),
            )
        self._migrate_legacy_json()

    def close(self) -> None:
        self._db.close()

    def _create_schema(self) -> None:
        self._db.executescript(
            """
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS caves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_json TEXT NOT NULL,
                contributor_id TEXT NOT NULL,
                state INTEGER NOT NULL CHECK (state BETWEEN 0 AND 3),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS groups (
                group_id TEXT PRIMARY KEY,
                cooldown_value INTEGER NOT NULL,
                cooldown_unit TEXT NOT NULL,
                last_draw_at TEXT
            );
            CREATE TABLE IF NOT EXISTS group_admins (
                group_id TEXT NOT NULL REFERENCES groups(group_id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                PRIMARY KEY (group_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS reviewers (user_id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cave_id INTEGER NOT NULL,
                state INTEGER NOT NULL,
                contributor_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS activity_reads (
                group_id TEXT PRIMARY KEY REFERENCES groups(group_id) ON DELETE CASCADE,
                last_activity_id INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )

    def ensure_group(self, group_id: str) -> None:
        group_id = str(group_id)
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO groups VALUES (?, ?, ?, NULL)",
                (group_id, self._default_cooldown, self._default_unit),
            )
            self._db.execute(
                "INSERT OR IGNORE INTO activity_reads(group_id) VALUES (?)", (group_id,)
            )

    def add(self, message: list[dict[str, Any]], contributor_id: str) -> CaveEntry:
        if not message:
            raise ValueError("message cannot be empty")
        created_at = _now()
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT INTO caves(message_json, contributor_id, state, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    payload,
                    str(contributor_id),
                    CaveState.PENDING,
                    created_at.isoformat(),
                    created_at.isoformat(),
                ),
            )
            cave_id = int(cursor.lastrowid)
            self._record_activity(cave_id, CaveState.PENDING, str(contributor_id), created_at)
        return CaveEntry(cave_id, message, str(contributor_id), CaveState.PENDING, created_at)

    def get(self, cave_id: int, include_inactive: bool = True) -> CaveEntry:
        query = "SELECT * FROM caves WHERE id = ?"
        params: tuple[Any, ...] = (cave_id,)
        if not include_inactive:
            query += " AND state = ?"
            params += (CaveState.APPROVED,)
        row = self._db.execute(query, params).fetchone()
        if row is None:
            raise CaveNotFound(f"cave {cave_id} does not exist")
        return self._entry(row)

    def draw(self, group_id: str, bypass_cooldown: bool = False) -> CaveEntry:
        self.ensure_group(group_id)
        with self._lock, self._db:
            rows = self._db.execute(
                "SELECT * FROM caves WHERE state = ?", (CaveState.APPROVED,)
            ).fetchall()
            if not rows:
                raise CaveNotFound("no approved caves")
            if not bypass_cooldown:
                group = self._db.execute(
                    "SELECT * FROM groups WHERE group_id = ?", (str(group_id),)
                ).fetchone()
                if group["last_draw_at"]:
                    elapsed = (
                        _now() - datetime.fromisoformat(group["last_draw_at"])
                    ).total_seconds()
                    cooldown = group["cooldown_value"] * _UNIT_SECONDS[group["cooldown_unit"]]
                    if elapsed < cooldown:
                        raise CooldownActive(cooldown - elapsed)
                self._db.execute(
                    "UPDATE groups SET last_draw_at = ? WHERE group_id = ?",
                    (_now().isoformat(), str(group_id)),
                )
            return self._entry(random.choice(rows))

    def moderate(self, cave_id: int, approved: bool) -> CaveEntry:
        target = CaveState.APPROVED if approved else CaveState.REJECTED
        with self._lock, self._db:
            entry = self.get(cave_id)
            if entry.state is not CaveState.PENDING:
                raise InvalidState(f"cave {cave_id} has already been processed")
            changed_at = _now()
            self._db.execute(
                "UPDATE caves SET state = ?, updated_at = ? WHERE id = ?",
                (target, changed_at.isoformat(), cave_id),
            )
            self._record_activity(cave_id, target, entry.contributor_id, changed_at)
        return CaveEntry(
            entry.cave_id, entry.message, entry.contributor_id, target, entry.created_at
        )

    def moderate_all(self, approved: bool) -> int:
        ids = [entry.cave_id for entry in self.pending()]
        for cave_id in ids:
            self.moderate(cave_id, approved)
        return len(ids)

    def delete(self, cave_id: int) -> CaveEntry:
        with self._lock, self._db:
            entry = self.get(cave_id)
            if entry.state is CaveState.DELETED:
                raise CaveNotFound(f"cave {cave_id} does not exist")
            changed_at = _now()
            self._db.execute(
                "UPDATE caves SET state = ?, updated_at = ? WHERE id = ?",
                (CaveState.DELETED, changed_at.isoformat(), cave_id),
            )
            self._record_activity(cave_id, CaveState.DELETED, entry.contributor_id, changed_at)
        return entry

    def pending(self) -> list[CaveEntry]:
        rows = self._db.execute(
            "SELECT * FROM caves WHERE state = ? ORDER BY id", (CaveState.PENDING,)
        ).fetchall()
        return [self._entry(row) for row in rows]

    def set_cooldown(self, group_id: str, value: int, unit: str) -> None:
        if unit not in _UNIT_SECONDS or not 0 < value < 500:
            raise ValueError("cooldown must be 1..499 and use sec, min, or hour")
        self.ensure_group(group_id)
        with self._db:
            self._db.execute(
                "UPDATE groups SET cooldown_value = ?, cooldown_unit = ?, last_draw_at = NULL "
                "WHERE group_id = ?",
                (value, unit, str(group_id)),
            )

    def is_group_admin(self, group_id: str, user_id: str) -> bool:
        self.ensure_group(group_id)
        return (
            self._db.execute(
                "SELECT 1 FROM group_admins WHERE group_id = ? AND user_id = ?",
                (str(group_id), str(user_id)),
            ).fetchone()
            is not None
        )

    def group_admins(self, group_id: str) -> list[str]:
        self.ensure_group(group_id)
        return [
            row[0]
            for row in self._db.execute(
                "SELECT user_id FROM group_admins WHERE group_id = ? ORDER BY user_id",
                (str(group_id),),
            )
        ]

    def set_group_admin(self, group_id: str, user_id: str, enabled: bool) -> bool:
        self.ensure_group(group_id)
        with self._db:
            if enabled:
                cursor = self._db.execute(
                    "INSERT OR IGNORE INTO group_admins VALUES (?, ?)",
                    (str(group_id), str(user_id)),
                )
            else:
                cursor = self._db.execute(
                    "DELETE FROM group_admins WHERE group_id = ? AND user_id = ?",
                    (str(group_id), str(user_id)),
                )
        return cursor.rowcount > 0

    def is_reviewer(self, user_id: str) -> bool:
        return (
            self._db.execute(
                "SELECT 1 FROM reviewers WHERE user_id = ?", (str(user_id),)
            ).fetchone()
            is not None
        )

    def reviewers(self) -> list[str]:
        return [
            row[0] for row in self._db.execute("SELECT user_id FROM reviewers ORDER BY user_id")
        ]

    def set_reviewer(self, user_id: str, enabled: bool) -> bool:
        with self._db:
            if enabled:
                cursor = self._db.execute(
                    "INSERT OR IGNORE INTO reviewers VALUES (?)", (str(user_id),)
                )
            else:
                cursor = self._db.execute(
                    "DELETE FROM reviewers WHERE user_id = ?", (str(user_id),)
                )
        return cursor.rowcount > 0

    def unread_activities(self, group_id: str) -> list[Activity]:
        self.ensure_group(group_id)
        with self._lock, self._db:
            last_id = self._db.execute(
                "SELECT last_activity_id FROM activity_reads WHERE group_id = ?", (str(group_id),)
            ).fetchone()[0]
            rows = self._db.execute(
                "SELECT * FROM activities WHERE id > ? ORDER BY id", (last_id,)
            ).fetchall()
            if rows:
                self._db.execute(
                    "UPDATE activity_reads SET last_activity_id = ? WHERE group_id = ?",
                    (rows[-1]["id"], str(group_id)),
                )
        return [
            Activity(
                row["id"],
                row["cave_id"],
                CaveState(row["state"]),
                row["contributor_id"],
                datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def _record_activity(
        self, cave_id: int, state: CaveState, contributor_id: str, at: datetime
    ) -> None:
        self._db.execute(
            "INSERT INTO activities(cave_id, state, contributor_id, created_at) VALUES (?, ?, ?, ?)",
            (cave_id, state, contributor_id, at.isoformat()),
        )

    @staticmethod
    def _entry(row: sqlite3.Row) -> CaveEntry:
        return CaveEntry(
            row["id"],
            json.loads(row["message_json"]),
            row["contributor_id"],
            CaveState(row["state"]),
            datetime.fromisoformat(row["created_at"]),
        )

    def _migrate_legacy_json(self) -> None:
        data_path, caves_path = self.data_dir / "data.json", self.data_dir / "cave.json"
        done = self._db.execute(
            "SELECT 1 FROM metadata WHERE key = 'legacy_json_migrated'"
        ).fetchone()
        if done or not (data_path.is_file() and caves_path.is_file()):
            return
        data = json.loads(data_path.read_text(encoding="utf-8"))
        caves = json.loads(caves_path.read_text(encoding="utf-8"))
        with self._lock, self._db:
            for group_id, group in data.get("groups_dict", {}).items():
                self.ensure_group(str(group_id))
                self.set_cooldown(
                    str(group_id), int(group.get("cd_num", 1)), group.get("cd_unit", "sec")
                )
                for user_id in group.get("white_A", []):
                    self.set_group_admin(str(group_id), str(user_id), True)
            for user_id in data.get("white_B", []):
                self.set_reviewer(str(user_id), True)
            for item in caves:
                created = _now().isoformat()
                self._db.execute(
                    "INSERT OR IGNORE INTO caves(id, message_json, contributor_id, state, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        item["cave_id"],
                        json.dumps(item["message"], ensure_ascii=False),
                        str(item["contributor_id"]),
                        int(item["state"]),
                        created,
                        created,
                    ),
                )
            self._db.execute(
                "INSERT INTO metadata VALUES ('legacy_json_migrated', ?)", (_now().isoformat(),)
            )
