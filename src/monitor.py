"""New post detection entry point.

Checks each configured TikTok account for new posts, sends Slack
notifications, and registers 24-hour analytics follow-up jobs.

Uses 2-layer storage:
- Persistent state (data/state.json, git): known_video_ids, pending/completed analytics
- Ephemeral state (data/ephemeral.json, Actions cache): timestamps, failure counters

Exit codes:
    0 = Success
    1 = Unrecoverable error
"""

import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add src/ to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cache_manager import get_account_ephemeral, load_ephemeral, save_ephemeral
from config import load_config
from slack_notifier import SlackNotifier
from state_manager import (
    has_meaningful_change,
    load_state,
    save_state,
    serialize_state,
)
from tiktok_client import AccountNotFoundError, TikTokClient, TikTokClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def git_commit_and_push(message: str) -> None:
    """Commit the state file and push to origin.

    Configures git user as github-actions[bot] for clean attribution.
    """
    subprocess.run(
        ["git", "config", "user.name", "github-actions[bot]"], check=True
    )
    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        ],
        check=True,
    )
    subprocess.run(["git", "add", "data/state.json"], check=True)

    # Check if there are actually staged changes
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], capture_output=True
    )
    if result.returncode == 0:
        logger.info("No staged changes; skipping commit")
        return

    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "push"], check=True)


def main() -> int:
    """Main monitor logic."""
    try:
        config = load_config()
    except (ValueError, FileNotFoundError) as e:
        logger.error(f"Configuration error: {e}")
        return 1

    state = load_state(config.state_file_path)
    original_snapshot = serialize_state(state)
    ephemeral = load_ephemeral(config.ephemeral_file_path)
    notifier = SlackNotifier(config.slack_webhook_url)
    client = TikTokClient()
    now = datetime.now(timezone.utc)

    for username in config.accounts:
        # Initialize persistent account state if first time
        if username not in state["accounts"]:
            state["accounts"][username] = {
                "known_video_ids": [],
            }

        account = state["accounts"][username]
        acct_ephemeral = get_account_ephemeral(ephemeral, username)

        try:
            videos = client.list_recent_videos(username)
            known_ids = set(account["known_video_ids"])
            new_videos = [v for v in videos if v.video_id not in known_ids]

            # On first run, record existing videos silently (no notifications)
            is_first_run = len(known_ids) == 0

            if is_first_run:
                logger.info(
                    f"First run for {username}: recording {len(videos)} "
                    f"existing videos without notification"
                )
                account["known_video_ids"] = [v.video_id for v in videos]
            else:
                for video in new_videos:
                    logger.info(
                        f"New post detected: {username} - {video.video_id}"
                    )
                    account["known_video_ids"].append(video.video_id)

                    analytics_due = now + timedelta(
                        hours=config.analytics_delay_hours
                    )
                    state["pending_analytics"].append(
                        {
                            "video_id": video.video_id,
                            "username": username,
                            "video_url": video.url,
                            "detected_at": now.isoformat(),
                            "analytics_due_at": analytics_due.isoformat(),
                            "title": video.title,
                            "retry_count": 0,
                        }
                    )

                    try:
                        notifier.notify_new_post(
                            username=username,
                            video_id=video.video_id,
                            video_url=video.url,
                            title=video.title,
                            detected_at=now.strftime("%Y-%m-%d %H:%M UTC"),
                        )
                    except Exception as e:
                        logger.error(f"Slack notification failed: {e}")

            # Update ephemeral state (timestamps, success tracking)
            acct_ephemeral["last_checked"] = now.isoformat()
            acct_ephemeral["last_check_success"] = True
            acct_ephemeral["consecutive_failures"] = 0

        except AccountNotFoundError as e:
            logger.warning(f"Account not found: {username}: {e}")
            acct_ephemeral["consecutive_failures"] = (
                acct_ephemeral.get("consecutive_failures", 0) + 1
            )
            acct_ephemeral["last_checked"] = now.isoformat()
            acct_ephemeral["last_check_success"] = False
            if acct_ephemeral["consecutive_failures"] >= 5:
                try:
                    notifier.notify_error(
                        f"アカウント {username} が5回連続で取得失敗。"
                        f"アカウントが存在しないか、非公開の可能性があります。"
                    )
                except Exception:
                    pass

        except TikTokClientError as e:
            logger.warning(f"TikTok extraction failed for {username}: {e}")
            acct_ephemeral["consecutive_failures"] = (
                acct_ephemeral.get("consecutive_failures", 0) + 1
            )
            acct_ephemeral["last_checked"] = now.isoformat()
            acct_ephemeral["last_check_success"] = False

        except Exception as e:
            logger.error(
                f"Unexpected error for {username}: {e}", exc_info=True
            )
            acct_ephemeral["consecutive_failures"] = (
                acct_ephemeral.get("consecutive_failures", 0) + 1
            )
            acct_ephemeral["last_checked"] = now.isoformat()
            acct_ephemeral["last_check_success"] = False

    # Always save ephemeral state (timestamps etc.) — NOT committed to git
    save_ephemeral(ephemeral, config.ephemeral_file_path)

    # Only save and commit persistent state if meaningfully changed
    new_snapshot = serialize_state(state)
    if has_meaningful_change(original_snapshot, new_snapshot):
        save_state(state, config.state_file_path, config.max_completed_history)
        try:
            git_commit_and_push("Update state: monitor check")
        except subprocess.CalledProcessError as e:
            logger.error(f"Git commit/push failed: {e}")
    else:
        logger.info("No state changes; skipping commit")

    return 0


if __name__ == "__main__":
    sys.exit(main())
