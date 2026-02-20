"""Manage reading and writing of data/ephemeral.json (Actions cache state).

Ephemeral state contains data that changes frequently but is not worth
committing to git:
- last_checked timestamps per account
- last_check_success flags
- consecutive_failures counters

This file is persisted between workflow runs via GitHub Actions cache
(actions/cache@v4) but is NOT committed to git. If the cache expires
(7 days without access), the ephemeral state resets to empty — this is
safe because only consecutive_failures resets to 0, which has no
functional impact.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Type alias for ephemeral state
Ephemeral = dict[str, Any]


def _default_ephemeral() -> Ephemeral:
    """Return a fresh empty ephemeral state."""
    return {
        "accounts": {},
    }


def load_ephemeral(path: str) -> Ephemeral:
    """Load ephemeral state from JSON file.

    Returns a default empty state if the file doesn't exist or is corrupt.
    This is expected on first run or when the Actions cache has expired.
    """
    try:
        p = Path(path)
        if not p.exists():
            logger.info("Ephemeral file not found; starting fresh")
            return _default_ephemeral()

        text = p.read_text(encoding="utf-8").strip()
        if not text:
            logger.info("Ephemeral file is empty; starting fresh")
            return _default_ephemeral()

        ephemeral = json.loads(text)

        # Ensure required keys exist
        if "accounts" not in ephemeral:
            ephemeral["accounts"] = {}

        return ephemeral

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Ephemeral file is corrupt ({e}); starting fresh")
        return _default_ephemeral()


def save_ephemeral(ephemeral: Ephemeral, path: str) -> None:
    """Write ephemeral state to JSON file.

    This file is NOT committed to git — it is managed by Actions cache.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(ephemeral, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info(f"Ephemeral state saved to {path}")


def get_account_ephemeral(ephemeral: Ephemeral, username: str) -> dict[str, Any]:
    """Get or initialize ephemeral data for a specific account."""
    if username not in ephemeral["accounts"]:
        ephemeral["accounts"][username] = {
            "last_checked": None,
            "last_check_success": False,
            "consecutive_failures": 0,
        }
    return ephemeral["accounts"][username]
