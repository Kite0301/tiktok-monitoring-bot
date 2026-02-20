"""Manage reading and writing of data/state.json."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Type alias for the state dict
State = dict[str, Any]


def _default_state() -> State:
    """Return a fresh empty state."""
    return {
        "version": 1,
        "last_updated": None,
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

    Updates last_updated timestamp and prunes completed_analytics if over the
    max_completed limit.
    """
    state["last_updated"] = datetime.now(timezone.utc).isoformat()

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
