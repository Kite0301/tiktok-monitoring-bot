"""Single entry point for the monitoring bot.

Walks the configured accounts, running both phases against each account's
own file, then commits whatever changed in one go:

1. New post detection           (monitor.check_account)
2. 24-hour analytics collection (analytics.collect_due_analytics)

Each account owns data/accounts/<username>.json, so accounts cannot
disturb each other's data, and one process owns the whole run, so the two
phases cannot lose each other's changes to a racing git push.

Exit codes:
    0 = Success
    1 = Configuration error, or an account, a phase or the push failed
"""

import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src/ to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from account_store import (
    account_path,
    has_meaningful_change,
    load_account,
    migrate_legacy_state,
    save_account,
    serialize,
)
from analytics import collect_due_analytics
from config import load_config
from git_sync import commit_and_push
from monitor import check_account
from slack_notifier import AccountNotifier, SlackNotifier
from tiktok_client import TikTokClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _commit_message(new_posts: int, collected: int, migrated: int) -> str:
    """Describe in the commit subject what this run actually did."""
    parts = []
    if migrated:
        parts.append(f"split {migrated} account(s) out of state.json")
    if new_posts:
        parts.append(f"{new_posts} new post(s)")
    if collected:
        parts.append(f"{collected} analytics")
    if not parts:
        # Failure counters or analytics retry counts changed.
        return "Update state: bookkeeping"
    return "Update state: " + ", ".join(parts)


def main() -> int:
    """Run both phases for every account and persist the result once."""
    try:
        config = load_config()
    except (ValueError, FileNotFoundError) as e:
        logger.error(f"Configuration error: {e}")
        return 1

    notifier = SlackNotifier(config.slack_webhook_url)
    client = TikTokClient()
    now = datetime.now(timezone.utc)

    failed = False
    new_posts = 0
    collected = 0
    changed = 0

    # One-time split of the pre-existing single state file.
    try:
        migrated = len(
            migrate_legacy_state(config.legacy_state_file_path, config.data_dir)
        )
        changed += migrated
    except Exception as e:
        logger.error(f"Legacy state migration failed: {e}", exc_info=True)
        migrated = 0
        failed = True

    for account in config.accounts:
        # An account that blows up must not take the other accounts with it.
        try:
            path = account_path(config.data_dir, account.username)
            state = load_account(path, account.username)
            before = serialize(state)
            account_notifier = AccountNotifier(notifier, account.notify)

            # The phases are isolated from each other too: whatever one has
            # already written into `state` is still persisted below.
            try:
                new_posts += check_account(
                    account, state, config, account_notifier, client, now
                )
            except Exception as e:
                logger.error(
                    f"New post detection failed for {account.username}: {e}",
                    exc_info=True,
                )
                failed = True

            try:
                collected += collect_due_analytics(
                    account, state, config, account_notifier, client, now
                )
            except Exception as e:
                logger.error(
                    f"Analytics collection failed for {account.username}: {e}",
                    exc_info=True,
                )
                failed = True

            if has_meaningful_change(before, serialize(state)):
                save_account(state, path, config.max_completed_history)
                changed += 1

        except Exception as e:
            logger.error(
                f"Could not process {account.username}: {e}", exc_info=True
            )
            failed = True

    if changed:
        try:
            commit_and_push(_commit_message(new_posts, collected, migrated))
        except subprocess.CalledProcessError as e:
            # Surface this as a failed run: the changes made by this run are
            # lost when the runner is discarded.
            logger.error(f"Git commit/push failed: {e}")
            failed = True
    else:
        logger.info("No changes; skipping commit")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
