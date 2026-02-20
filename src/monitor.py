"""New post detection entry point.

Checks each configured TikTok account for new posts, sends Slack
notifications, and registers 24-hour analytics follow-up jobs.

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

from config import load_config
from slack_notifier import SlackNotifier
from state_manager import load_state, save_state, serialize_state
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
    notifier = SlackNotifier(config.slack_webhook_url)
    client = TikTokClient()
    now = datetime.now(timezone.utc)

    for username in config.accounts:
        # Initialize account state if first time
        if username not in state["accounts"]:
            state["accounts"][username] = {
                "last_checked": None,
                "last_check_success": False,
                "consecutive_failures": 0,
                "known_video_ids": [],
            }

        account = state["accounts"][username]

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

            account["last_checked"] = now.isoformat()
            account["last_check_success"] = True
            account["consecutive_failures"] = 0

        except AccountNotFoundError as e:
            logger.warning(f"Account not found: {username}: {e}")
            account["consecutive_failures"] = (
                account.get("consecutive_failures", 0) + 1
            )
            account["last_checked"] = now.isoformat()
            account["last_check_success"] = False
            if account["consecutive_failures"] >= 5:
                try:
                    notifier.notify_error(
                        f"\u30a2\u30ab\u30a6\u30f3\u30c8 {username} \u304c5\u56de\u9023\u7d9a\u3067\u53d6\u5f97\u5931\u6557\u3002"
                        f"\u30a2\u30ab\u30a6\u30f3\u30c8\u304c\u5b58\u5728\u3057\u306a\u3044\u304b\u3001\u975e\u516c\u958b\u306e\u53ef\u80fd\u6027\u304c\u3042\u308a\u307e\u3059\u3002"
                    )
                except Exception:
                    pass

        except TikTokClientError as e:
            logger.warning(f"TikTok extraction failed for {username}: {e}")
            account["consecutive_failures"] = (
                account.get("consecutive_failures", 0) + 1
            )
            account["last_checked"] = now.isoformat()
            account["last_check_success"] = False

        except Exception as e:
            logger.error(
                f"Unexpected error for {username}: {e}", exc_info=True
            )
            account["consecutive_failures"] = (
                account.get("consecutive_failures", 0) + 1
            )
            account["last_checked"] = now.isoformat()
            account["last_check_success"] = False

    # Only save and commit if state actually changed
    new_snapshot = serialize_state(state)
    if new_snapshot != original_snapshot:
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
