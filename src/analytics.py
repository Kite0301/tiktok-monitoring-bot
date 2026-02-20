"""24-hour analytics collection entry point.

Checks pending_analytics for due items, collects metrics via yt-dlp,
and sends Slack notifications with the results.

Uses 2-layer storage:
- Persistent state (data/state.json, git): pending/completed analytics
- Ephemeral state (data/ephemeral.json, Actions cache): timestamps only

Exit codes:
    0 = Success
    1 = Unrecoverable error
"""

import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src/ to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cache_manager import load_ephemeral, save_ephemeral
from config import load_config
from slack_notifier import SlackNotifier
from state_manager import (
    has_meaningful_change,
    load_state,
    save_state,
    serialize_state,
)
from tiktok_client import TikTokClient, TikTokClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def git_commit_and_push(message: str) -> None:
    """Commit the state file and push to origin."""
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

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], capture_output=True
    )
    if result.returncode == 0:
        logger.info("No staged changes; skipping commit")
        return

    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "push"], check=True)


def main() -> int:
    """Main analytics collection logic."""
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

    still_pending: list[dict] = []

    for job in state["pending_analytics"]:
        due_at = datetime.fromisoformat(job["analytics_due_at"])

        if due_at > now:
            still_pending.append(job)
            continue

        logger.info(
            f"Collecting analytics for {job['video_id']} ({job['username']})"
        )

        try:
            analytics = client.get_video_analytics(job["video_url"])

            state["completed_analytics"].append(
                {
                    "video_id": job["video_id"],
                    "username": job["username"],
                    "video_url": job["video_url"],
                    "title": job["title"],
                    "detected_at": job["detected_at"],
                    "analytics_collected_at": now.isoformat(),
                    "view_count": analytics.view_count,
                    "like_count": analytics.like_count,
                    "comment_count": analytics.comment_count,
                    "repost_count": analytics.repost_count,
                    "save_count": analytics.save_count,
                }
            )

            try:
                notifier.notify_analytics(
                    username=job["username"],
                    video_url=job["video_url"],
                    title=job["title"],
                    detected_at=job["detected_at"],
                    view_count=analytics.view_count,
                    like_count=analytics.like_count,
                    comment_count=analytics.comment_count,
                    repost_count=analytics.repost_count,
                    save_count=analytics.save_count,
                )
            except Exception as e:
                logger.error(f"Slack analytics notification failed: {e}")

        except TikTokClientError as e:
            logger.warning(
                f"Analytics extraction failed for {job['video_id']}: {e}"
            )
            job["retry_count"] = job.get("retry_count", 0) + 1

            if job["retry_count"] >= config.max_analytics_retries:
                logger.error(
                    f"Max retries reached for {job['video_id']}; "
                    f"recording with null values"
                )
                state["completed_analytics"].append(
                    {
                        "video_id": job["video_id"],
                        "username": job["username"],
                        "video_url": job["video_url"],
                        "title": job["title"],
                        "detected_at": job["detected_at"],
                        "analytics_collected_at": now.isoformat(),
                        "view_count": None,
                        "like_count": None,
                        "comment_count": None,
                        "repost_count": None,
                        "save_count": None,
                    }
                )
                try:
                    notifier.notify_error(
                        f"動画 {job['video_id']} ({job['username']}) の分析データ取得に"
                        f"失敗しました（{config.max_analytics_retries}回リトライ済み）。"
                        f"動画が削除された可能性があります。"
                    )
                except Exception:
                    pass
            else:
                # Keep in pending for next attempt
                still_pending.append(job)

    state["pending_analytics"] = still_pending

    # Prune completed history
    completed = state.get("completed_analytics", [])
    if len(completed) > config.max_completed_history:
        state["completed_analytics"] = completed[-config.max_completed_history:]

    # Always save ephemeral state — NOT committed to git
    save_ephemeral(ephemeral, config.ephemeral_file_path)

    # Only save and commit persistent state if meaningfully changed
    new_snapshot = serialize_state(state)
    if has_meaningful_change(original_snapshot, new_snapshot):
        save_state(state, config.state_file_path, config.max_completed_history)
        try:
            git_commit_and_push("Update state: analytics collected")
        except subprocess.CalledProcessError as e:
            logger.error(f"Git commit/push failed: {e}")
    else:
        logger.info("No pending analytics due; skipping commit")

    return 0


if __name__ == "__main__":
    sys.exit(main())
