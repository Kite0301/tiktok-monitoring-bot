"""Single entry point for the monitoring bot.

Runs both phases against one in-memory state, then persists and commits
it exactly once:

1. New post detection          (monitor.check_new_posts)
2. 24-hour analytics collection (analytics.collect_due_analytics)

Running both in one process means only one writer ever touches
data/state.json, so the phases cannot lose each other's changes to a
racing git push.

Exit codes:
    0 = Success
    1 = Configuration error, or a phase or the push failed
"""

import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src/ to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from analytics import collect_due_analytics
from config import load_config
from git_sync import commit_and_push
from monitor import check_new_posts
from slack_notifier import SlackNotifier
from state_manager import (
    has_meaningful_change,
    load_state,
    save_state,
    serialize_state,
)
from tiktok_client import TikTokClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _commit_message(new_posts: int, collected: int) -> str:
    """Describe in the commit subject what this run actually did."""
    parts = []
    if new_posts:
        parts.append(f"{new_posts} new post(s)")
    if collected:
        parts.append(f"{collected} analytics")
    if not parts:
        # Failure counters or analytics retry counts changed.
        return "Update state: bookkeeping"
    return "Update state: " + ", ".join(parts)


def main() -> int:
    """Run both phases and persist the result once."""
    try:
        config = load_config()
    except (ValueError, FileNotFoundError) as e:
        logger.error(f"Configuration error: {e}")
        return 1

    state = load_state(config.state_file_path)
    original_snapshot = serialize_state(state)
    notifier = SlackNotifier(config.slack_webhook_url)
    client = TikTokClient()
    now = datetime.now(timezone.utc)

    failed = False
    new_posts = 0
    collected = 0

    # The phases are isolated from each other: whatever one has already
    # written into `state` is still persisted below if the other blows up.
    try:
        new_posts = check_new_posts(state, config, notifier, client, now)
    except Exception as e:
        logger.error(f"New post detection failed: {e}", exc_info=True)
        failed = True

    try:
        collected = collect_due_analytics(state, config, notifier, client, now)
    except Exception as e:
        logger.error(f"Analytics collection failed: {e}", exc_info=True)
        failed = True

    if has_meaningful_change(original_snapshot, serialize_state(state)):
        save_state(state, config.state_file_path, config.max_completed_history)
        try:
            commit_and_push(_commit_message(new_posts, collected))
        except subprocess.CalledProcessError as e:
            # Surface this as a failed run: the state changes made by this
            # run are lost when the runner is discarded.
            logger.error(f"Git commit/push failed: {e}")
            failed = True
    else:
        logger.info("No state changes; skipping commit")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
