"""State file loading, saving and change detection."""

import json

from state_manager import (
    has_meaningful_change,
    load_state,
    save_state,
    serialize_state,
)

EXPECTED_KEYS = {"version", "accounts", "pending_analytics", "completed_analytics"}


def test_missing_file_yields_an_empty_state(tmp_path):
    state = load_state(str(tmp_path / "nope.json"))

    assert state["accounts"] == {}
    assert state["pending_analytics"] == []


def test_empty_file_yields_an_empty_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("   \n", encoding="utf-8")

    assert load_state(str(path))["accounts"] == {}


def test_corrupt_json_yields_an_empty_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")

    assert load_state(str(path))["accounts"] == {}


def test_missing_top_level_keys_are_filled_in(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"version": 1}), encoding="utf-8")

    state = load_state(str(path))
    assert state["accounts"] == {}
    assert state["pending_analytics"] == []
    assert state["completed_analytics"] == []


def test_wrong_types_are_replaced_rather_than_crashing_the_run(tmp_path):
    """A list where a dict belongs used to blow up mid-run."""
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "accounts": [],
                "pending_analytics": {},
                "completed_analytics": "nope",
            }
        ),
        encoding="utf-8",
    )

    state = load_state(str(path))
    assert state["accounts"] == {}
    assert state["pending_analytics"] == []
    assert state["completed_analytics"] == []


def test_a_json_scalar_yields_an_empty_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("42", encoding="utf-8")

    assert load_state(str(path))["accounts"] == {}


def test_save_creates_missing_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "state.json"
    save_state({"version": 1, "accounts": {}}, str(path))

    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_save_prunes_completed_history_to_the_limit(tmp_path):
    path = tmp_path / "state.json"
    entries = [{"video_id": f"v{i}"} for i in range(10)]
    save_state(
        {"version": 1, "accounts": {}, "completed_analytics": entries},
        str(path),
        max_completed=4,
    )

    kept = json.loads(path.read_text(encoding="utf-8"))["completed_analytics"]
    assert [e["video_id"] for e in kept] == ["v6", "v7", "v8", "v9"]


def test_round_trip_preserves_japanese_text(tmp_path):
    path = tmp_path / "state.json"
    save_state(
        {"version": 1, "accounts": {"@a": {"title": "日本語タイトル"}}},
        str(path),
    )

    assert load_state(str(path))["accounts"]["@a"]["title"] == "日本語タイトル"


def test_change_detection_ignores_key_order():
    a = serialize_state({"accounts": {}, "version": 1})
    b = serialize_state({"version": 1, "accounts": {}})

    assert not has_meaningful_change(a, b)


def test_change_detection_notices_new_data():
    a = serialize_state({"version": 1, "accounts": {}})
    b = serialize_state({"version": 1, "accounts": {"@a": {}}})

    assert has_meaningful_change(a, b)
