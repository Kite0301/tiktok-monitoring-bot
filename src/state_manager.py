"""Manage reading and writing of data/state.json (persistent state).

Persistent state only contains data that changes meaningfully:
- known_video_ids per account
- pending_analytics jobs
- completed_analytics history

Timestamps and failure counters live in ephemeral state (cache_manager.py).
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Type alias for the state dict
State = dict[str, Any]


def _default_state() -> State:
    """Return a fresh empty state."""
    return {
        "version": 1,
        "accounts": {},
        "pending_analytics": [],
        "completed_analytics": [],
    }


def load_state(path: str) -> State:
    """Load state from JSON file.

    If the file doesn't exist, is empty, or is corrupt, return a fresh default
    state and log a warning.
    """
    try:
        p = Path(path)
        if not p.exists():
            logger.info("State file not found; starting with empty state")
            return _default_state()

        text = p.read_text(encoding="utf-8").strip()
        if not text:
            logger.warning("State file is empty; starting with empty state")
            return _default_state()

        state = json.loads(text)

        # Ensure required top-level keys exist
        for key in ("accounts", "pending_analytics", "completed_analytics"):
            if key not in state:
                state[key] = {} if key == "accounts" else []

        return state

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"State file is corrupt ({e}); starting with empty state")
        return _default_state()


def save_state(state: State, path: str, max_completed: int = 200) -> None:
    """Write state to JSON file.

    Prunes completed_analytics if over the max_completed limit.
    Does NOT include timestamps (those belong in ephemeral state).
    """
    # Prune old completed analytics
    completed = state.get("completed_analytics", [])
    if len(completed) > max_completed:
        state["completed_analytics"] = completed[-max_completed:]

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info(f"State saved to {path}")


def serialize_state(state: State) -> str:
    """Deterministic JSON serialization for change detection."""
    return json.dumps(state, sort_keys=True, ensure_ascii=False)


def has_meaningful_change(old_snapshot: str, new_snapshot: str) -> bool:
    """Compare two state snapshots to determine if a git commit is needed.

    Returns True if the persistent state has meaningfully changed, i.e.:
    - known_video_ids changed (new posts detected)
    - pending_analytics changed (new jobs added or jobs moved/removed)
    - completed_analytics changed (analytics collected or retries exhausted)
    """
    return old_snapshot != new_snapshot
