import json
from pathlib import Path

import pytest

from nonebot_plugin_cave.models import CaveNotFound, CaveState, CooldownActive, InvalidState
from nonebot_plugin_cave.storage import CaveRepository


@pytest.fixture
def repository(tmp_path: Path):
    repo = CaveRepository(tmp_path, ["10001"])
    yield repo
    repo.close()


def test_submission_moderation_and_draw(repository: CaveRepository) -> None:
    entry = repository.add([{"type": "text", "data": {"text": "hello"}}], "42")
    assert entry.state is CaveState.PENDING
    with pytest.raises(CaveNotFound):
        repository.draw("123")
    approved = repository.moderate(entry.cave_id, True)
    assert repository.draw("123") == approved
    with pytest.raises(CooldownActive):
        repository.draw("123")
    assert repository.draw("123", bypass_cooldown=True) == approved
    with pytest.raises(InvalidState):
        repository.moderate(entry.cave_id, False)


def test_rejection_remains_queryable(repository: CaveRepository) -> None:
    entry = repository.add([{"type": "text", "data": {"text": "no"}}], "42")
    repository.moderate(entry.cave_id, False)
    assert repository.get(entry.cave_id).state is CaveState.REJECTED


def test_whitelists_are_scoped(repository: CaveRepository) -> None:
    assert repository.reviewers() == ["10001"]
    assert repository.set_reviewer("10002", True)
    assert repository.set_group_admin("1", "20001", True)
    assert repository.is_group_admin("1", "20001")
    assert not repository.is_group_admin("2", "20001")


def test_activity_feed_has_per_group_cursor(repository: CaveRepository) -> None:
    repository.ensure_group("1")
    repository.ensure_group("2")
    entry = repository.add([{"type": "text", "data": {"text": "news"}}], "42")
    repository.moderate(entry.cave_id, True)
    assert len(repository.unread_activities("1")) == 2
    assert repository.unread_activities("1") == []
    assert len(repository.unread_activities("2")) == 2


def test_legacy_json_migration(tmp_path: Path) -> None:
    (tmp_path / "data.json").write_text(json.dumps({
        "groups_dict": {"9": {"cd_num": 3, "cd_unit": "min", "white_A": ["7"]}},
        "white_B": ["8"],
    }), encoding="utf-8")
    (tmp_path / "cave.json").write_text(json.dumps([{
        "cave_id": 12, "message": [{"type": "text", "text": "old"}],
        "contributor_id": "6", "state": 0,
    }]), encoding="utf-8")
    repo = CaveRepository(tmp_path)
    assert repo.get(12).message[0]["text"] == "old"
    assert repo.is_group_admin("9", "7")
    assert repo.is_reviewer("8")
    repo.close()
