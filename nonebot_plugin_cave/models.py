from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any


class CaveState(IntEnum):
    APPROVED = 0
    PENDING = 1
    REJECTED = 2
    DELETED = 3


@dataclass(frozen=True)
class CaveEntry:
    cave_id: int
    message: list[dict[str, Any]]
    contributor_id: str
    state: CaveState
    created_at: datetime


@dataclass(frozen=True)
class Activity:
    activity_id: int
    cave_id: int
    state: CaveState
    contributor_id: str
    created_at: datetime


class CaveError(Exception):
    pass


class CaveNotFound(CaveError):
    pass


class InvalidState(CaveError):
    pass


class CooldownActive(CaveError):
    def __init__(self, remaining_seconds: float) -> None:
        self.remaining_seconds = max(0.0, remaining_seconds)
        super().__init__(f"cooldown active for {self.remaining_seconds:.0f} seconds")
