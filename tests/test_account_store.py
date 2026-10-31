"""Per-account file storage and the one-time migration off state.json."""

import json

import pytest

from account_store import (
    account_path,
    has_meaningful_change,
    load_account,
    migrate_legacy_state,
    save_account,
    serialize,
)

ACCOUNT = "@acct"


def test_filename_drops_the_at_sign(tmp_path):
    assert account_path(str(tmp_path), "@kt.umaimon").endswith("kt.umaimon.json")


@pytest.mark.parametrize(
    "username",
    ["@../escape", "@a/b", "@", "@.hidden", "@name with space", "@naughty;rm"],
)
def test_unsafe_usernames_are_rejected(tmp_path, username):
    """A username becomes a file path, so it must not be able to escape."""
    with pytest.raises(ValueError):
        account_path(str(tmp_path), username)


def test_missing_file_yields_a_fresh_state(tmp_path):
    state = load_account(str(tmp_path / "nope.json"), ACCOUNT)

    assert state["username"] == ACCOUNT
    assert state["known_video_ids"] == []
    assert state["completed_analytics"] == []


@pytest.mark.parametrize(
    "content", ["", "   \n", "{not json", "42", '"a string"'],
    ids=["empty", "whitespace", "corrupt", "scalar", "string"],
)
def test_unusable_files_yield_a_fresh_state(tmp_path, content):
    path = tmp_path / "acct.json"
    path.write_text(content, encoding="utf-8")

    assert load_account(str(path), ACCOUNT)["known_video_ids"] == []


def test_wrong_types_are_replaced_rather_than_crashing_the_run(tmp_path):
    path = tmp_path / "acct.json"
    path.write_text(
        json.dumps(
            {
                "username": ACCOUNT,
                "known_video_ids": {},
                "pending_analytics": "nope",
                "completed_analytics": 5,
            }
        ),
        encoding="utf-8",
    )

    state = load_account(str(path), ACCOUNT)
    assert state["known_video_ids"] == []
    assert state["pending_analytics"] == []
    assert state["completed_analytics"] == []


def test_failure_tracking_survives_a_round_trip(tmp_path):
    path = str(tmp_path / "acct.json")
    save_account(
        {
            "username": ACCOUNT,
            "known_video_ids": ["v1"],
            "pending_analytics": [],
            "completed_analytics": [],
            "consecutive_failures": 2,
            "failure_notified": True,
        },
        path,
    )

    state = load_account(path, ACCOUNT)
    assert state["consecutive_failures"] == 2
    assert state["failure_notified"] is True


def test_save_creates_missing_directories(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "acct.json")
    save_account({"username": ACCOUNT, "known_video_ids": []}, path)

    assert load_account(path, ACCOUNT)["username"] == ACCOUNT


def test_save_prunes_history_to_the_limit(tmp_path):
    path = str(tmp_path / "acct.json")
    entries = [{"video_id": f"v{i}"} for i in range(10)]
    save_account(
        {"username": ACCOUNT, "completed_analytics": entries}, path, max_completed=4
    )

    kept = load_account(path, ACCOUNT)["completed_analytics"]
    assert [e["video_id"] for e in kept] == ["v6", "v7", "v8", "v9"]


def test_round_trip_preserves_japanese_text(tmp_path):
    path = str(tmp_path / "acct.json")
    save_account(
        {
            "username": ACCOUNT,
            "completed_analytics": [{"title": "日本語タイトル"}],
        },
        path,
    )

    stored = load_account(path, ACCOUNT)["completed_analytics"][0]
    assert stored["title"] == "日本語タイトル"


def test_change_detection_ignores_key_order():
    a = serialize({"username": ACCOUNT, "known_video_ids": []})
    b = serialize({"known_video_ids": [], "username": ACCOUNT})

    assert not has_meaningful_change(a, b)


def test_change_detection_notices_new_data():
    a = serialize({"known_video_ids": []})
    b = serialize({"known_video_ids": ["v1"]})

    assert has_meaningful_change(a, b)


class TestLegacyMigration:
    """The single data/state.json is split once, then removed."""

    def legacy(self, path):
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "accounts": {
                        "@one": {"known_video_ids": ["a1", "a2"]},
                        "@two": {
                            "known_video_ids": ["b1"],
                            "consecutive_failures": 2,
                            "failure_notified": True,
                        },
                    },
                    "pending_analytics": [
                        {"video_id": "a3", "username": "@one"},
                    ],
                    "completed_analytics": [
                        {"video_id": "a1", "username": "@one", "view_count": 1},
                        {"video_id": "b1", "username": "@two", "view_count": 2},
                        {"video_id": "a2", "username": "@one", "view_count": 3},
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_nothing_to_do_when_there_is_no_legacy_file(self, tmp_path):
        assert migrate_legacy_state(str(tmp_path / "absent.json"), str(tmp_path)) == []

    def test_each_account_is_split_into_its_own_file(self, tmp_path):
        legacy_path = tmp_path / "state.json"
        data_dir = tmp_path / "accounts"
        self.legacy(legacy_path)

        written = migrate_legacy_state(str(legacy_path), str(data_dir))

        assert len(written) == 2
        one = load_account(account_path(str(data_dir), "@one"), "@one")
        two = load_account(account_path(str(data_dir), "@two"), "@two")
        assert one["known_video_ids"] == ["a1", "a2"]
        assert [e["video_id"] for e in one["completed_analytics"]] == ["a1", "a2"]
        assert [j["video_id"] for j in one["pending_analytics"]] == ["a3"]
        assert two["completed_analytics"][0]["video_id"] == "b1"
        assert two["pending_analytics"] == []

    def test_failure_tracking_is_carried_over(self, tmp_path):
        legacy_path = tmp_path / "state.json"
        data_dir = tmp_path / "accounts"
        self.legacy(legacy_path)

        migrate_legacy_state(str(legacy_path), str(data_dir))

        two = load_account(account_path(str(data_dir), "@two"), "@two")
        assert two["consecutive_failures"] == 2
        assert two["failure_notified"] is True

    def test_the_legacy_file_is_removed_so_it_runs_once(self, tmp_path):
        legacy_path = tmp_path / "state.json"
        data_dir = tmp_path / "accounts"
        self.legacy(legacy_path)

        migrate_legacy_state(str(legacy_path), str(data_dir))
        assert not legacy_path.exists()
        assert migrate_legacy_state(str(legacy_path), str(data_dir)) == []

    def test_history_is_not_pruned_during_migration(self, tmp_path):
        """Migration must never be the thing that loses data."""
        legacy_path = tmp_path / "state.json"
        data_dir = tmp_path / "accounts"
        legacy_path.write_text(
            json.dumps(
                {
                    "accounts": {"@one": {"known_video_ids": []}},
                    "pending_analytics": [],
                    "completed_analytics": [
                        {"video_id": f"v{i}", "username": "@one"}
                        for i in range(500)
                    ],
                }
            ),
            encoding="utf-8",
        )

        migrate_legacy_state(str(legacy_path), str(data_dir))

        one = load_account(account_path(str(data_dir), "@one"), "@one")
        assert len(one["completed_analytics"]) == 500

    def test_accounts_only_present_in_history_are_kept(self, tmp_path):
        """An account dropped from the config must not lose its history."""
        legacy_path = tmp_path / "state.json"
        data_dir = tmp_path / "accounts"
        legacy_path.write_text(
            json.dumps(
                {
                    "accounts": {},
                    "pending_analytics": [],
                    "completed_analytics": [
                        {"video_id": "v1", "username": "@retired"}
                    ],
                }
            ),
            encoding="utf-8",
        )

        migrate_legacy_state(str(legacy_path), str(data_dir))

        retired = load_account(account_path(str(data_dir), "@retired"), "@retired")
        assert len(retired["completed_analytics"]) == 1

    def test_an_existing_account_file_is_never_overwritten(self, tmp_path):
        legacy_path = tmp_path / "state.json"
        data_dir = tmp_path / "accounts"
        self.legacy(legacy_path)
        data_dir.mkdir()
        save_account(
            {"username": "@one", "known_video_ids": ["keep"]},
            account_path(str(data_dir), "@one"),
        )

        migrate_legacy_state(str(legacy_path), str(data_dir))

        one = load_account(account_path(str(data_dir), "@one"), "@one")
        assert one["known_video_ids"] == ["keep"]

    def test_a_corrupt_legacy_file_is_left_in_place(self, tmp_path):
        legacy_path = tmp_path / "state.json"
        legacy_path.write_text("{not json", encoding="utf-8")

        assert migrate_legacy_state(str(legacy_path), str(tmp_path / "a")) == []
        assert legacy_path.exists()
