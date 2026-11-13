"""Read and write one JSON file per monitored account.

Each account owns data/accounts/<username>.json holding everything about
it: which videos we have seen, its analytics queue and history, and its
failure tracking. One writer per file means adding an account, or a busy
account, cannot disturb any other account's data.

Replaces the single data/state.json, which is migrated away on first run.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AccountState = dict[str, Any]

# TikTok usernames are letters, digits, underscore and period. Anything else
# has no business being turned into a file path.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._]+$")


def _slug(username: str) -> str:
    """Filename stem for an account, e.g. "@kt.umaimon" -> "kt.umaimon"."""
    stem = username.lstrip("@")
    if not stem or not _SAFE_NAME.match(stem) or stem.startswith("."):
        raise ValueError(f"Unsupported account username: {username!r}")
    return stem


def account_path(data_dir: str, username: str) -> str:
    return str(Path(data_dir) / f"{_slug(username)}.json")


def default_account_state(username: str) -> AccountState:
    return {
        "version": 1,
        "username": username,
        "known_video_ids": [],
        "pending_analytics": [],
        "completed_analytics": [],
    }


def load_account(path: str, username: str) -> AccountState:
    """Load one account's file, or return a fresh state.

    A missing, empty, corrupt or wrongly-shaped file yields a fresh state
    with a warning rather than an exception: losing one account's history is
    bad, but taking the whole run down with it is worse.
    """
    state = default_account_state(username)

    p = Path(path)
    if not p.exists():
        logger.info(f"No stored data for {username}; starting fresh")
        return state

    try:
        text = p.read_text(encoding="utf-8").strip()
        if not text:
            logger.warning(f"Data file for {username} is empty; starting fresh")
            return state
        stored = json.loads(text)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Data file for {username} is unreadable ({e}); starting fresh")
        return state

    if not isinstance(stored, dict):
        logger.warning(
            f"Data file for {username} is not a JSON object; starting fresh"
        )
        return state

    for key, expected in (
        ("known_video_ids", list),
        ("pending_analytics", list),
        ("completed_analytics", list),
    ):
        value = stored.get(key)
        if isinstance(value, expected):
            state[key] = value
        elif key in stored:
            logger.warning(
                f"{username}: key {key!r} has unexpected type "
                f"{type(value).__name__}; resetting it"
            )

    # Failure tracking is only present while an account is failing.
    for key in ("consecutive_failures", "failure_notified"):
        if key in stored:
            state[key] = stored[key]

    return state


def save_account(state: AccountState, path: str, max_completed: int = 200) -> None:
    """Write one account's file, pruning its analytics history to the limit."""
    completed = state.get("completed_analytics", [])
    if len(completed) > max_completed:
        state["completed_analytics"] = completed[-max_completed:]

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info(f"Saved {state.get('username')} to {path}")


def serialize(state: AccountState) -> str:
    """Deterministic serialization, for detecting real changes."""
    return json.dumps(state, sort_keys=True, ensure_ascii=False)


def has_meaningful_change(before: str, after: str) -> bool:
    return before != after


def migrate_legacy_state(legacy_path: str, data_dir: str) -> list[str]:
    """Split a pre-existing data/state.json into per-account files.

    Runs once: the legacy file is deleted afterwards. Accounts found in the
    legacy file are all migrated, including ones no longer configured, so
    that removing an account from the config never destroys its history.

    Returns the paths written (empty if there was nothing to migrate).
    """
    legacy = Path(legacy_path)
    if not legacy.exists():
        return []

    try:
        stored = json.loads(legacy.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"Legacy state file is unreadable ({e}); leaving it in place")
        return []

    if not isinstance(stored, dict):
        logger.error("Legacy state file is not a JSON object; leaving it in place")
        return []

    accounts = stored.get("accounts")
    accounts = accounts if isinstance(accounts, dict) else {}
    pending = stored.get("pending_analytics")
    pending = pending if isinstance(pending, list) else []
    completed = stored.get("completed_analytics")
    completed = completed if isinstance(completed, list) else []

    usernames = set(accounts)
    usernames.update(
        job["username"] for job in pending + completed
        if isinstance(job, dict) and job.get("username")
    )

    written: list[str] = []
    for username in sorted(usernames):
        try:
            path = account_path(data_dir, username)
        except ValueError as e:
            logger.error(f"Cannot migrate {username!r}: {e}")
            continue

        if Path(path).exists():
            logger.warning(f"{path} already exists; not overwriting it")
            continue

        legacy_account = accounts.get(username) or {}
        state = default_account_state(username)
        known = legacy_account.get("known_video_ids")
        if isinstance(known, list):
            state["known_video_ids"] = known
        for key in ("consecutive_failures", "failure_notified"):
            if key in legacy_account:
                state[key] = legacy_account[key]
        state["pending_analytics"] = [
            job for job in pending
            if isinstance(job, dict) and job.get("username") == username
        ]
        state["completed_analytics"] = [
            entry for entry in completed
            if isinstance(entry, dict) and entry.get("username") == username
        ]

        # Migration must not silently drop history, so no pruning here.
        save_account(state, path, max_completed=len(state["completed_analytics"]))
        written.append(path)

    legacy.unlink()
    logger.info(
        f"Migrated {len(written)} account(s) out of {legacy_path} and removed it"
    )
    return written
