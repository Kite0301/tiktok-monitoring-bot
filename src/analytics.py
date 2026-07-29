"""24-hour analytics collection.

Checks pending_analytics for due items, collects metrics via yt-dlp, and
sends Slack notifications with the results.

Mutates the state dict in place. Loading, saving and committing the state
is run.py's responsibility, so that a single run writes it exactly once.
"""

import logging
from datetime import datetime, timedelta, timezone

from config import Config
from slack_notifier import SlackNotifier
from state_manager import State
from tiktok_client import TikTokClient, TikTokClientError

JST = timezone(timedelta(hours=9))

logger = logging.getLogger(__name__)


def _format_jst(iso_str: str) -> str:
    """Convert an ISO 8601 UTC timestamp to JST display string."""
    dt = datetime.fromisoformat(iso_str)
    return dt.astimezone(JST).strftime("%Y-%m-%d %H:%M JST")


def _anchor_iso(job: dict) -> str:
    """The timestamp the measurement window is counted from.

    Jobs registered before posted_at existed, and jobs whose post time
    yt-dlp did not expose, fall back to the detection time.
    """
    return job.get("posted_at") or job["detected_at"]


def _completed_entry(job: dict, now: datetime, **metrics) -> dict:
    """Build a completed_analytics record for a job.

    Records how long after posting the metrics were actually read, so that
    a late run produces an honest number rather than a mislabelled one.
    """
    anchor = datetime.fromisoformat(_anchor_iso(job))
    return {
        "video_id": job["video_id"],
        "username": job["username"],
        "video_url": job["video_url"],
        "title": job["title"],
        "posted_at": job.get("posted_at"),
        "detected_at": job["detected_at"],
        "analytics_collected_at": now.isoformat(),
        "elapsed_hours": round((now - anchor).total_seconds() / 3600, 2),
        **metrics,
    }


def collect_due_analytics(
    state: State,
    config: Config,
    notifier: SlackNotifier,
    client: TikTokClient,
    now: datetime,
) -> int:
    """Collect metrics for every pending job whose 24h window has elapsed.

    Returns the number of jobs whose metrics were successfully collected.
    Jobs that fail are retried on later runs until max_analytics_retries,
    after which they are recorded with null metrics.
    """
    collected_count = 0
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

            entry = _completed_entry(
                job,
                now,
                view_count=analytics.view_count,
                like_count=analytics.like_count,
                comment_count=analytics.comment_count,
                repost_count=analytics.repost_count,
                save_count=analytics.save_count,
            )
            state["completed_analytics"].append(entry)
            collected_count += 1

            try:
                notifier.notify_analytics(
                    username=job["username"],
                    video_url=job["video_url"],
                    title=job["title"],
                    posted_at=_format_jst(_anchor_iso(job)),
                    posted_at_is_exact=bool(job.get("posted_at")),
                    elapsed_hours=entry["elapsed_hours"],
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
                    _completed_entry(
                        job,
                        now,
                        view_count=None,
                        like_count=None,
                        comment_count=None,
                        repost_count=None,
                        save_count=None,
                    )
                )
                try:
                    notifier.notify_error(
                        f"動画 {job['video_id']} ({job['username']}) の分析データ取得に"
                        f"失敗しました（{config.max_analytics_retries}回リトライ済み）。"
                        f"動画が削除された可能性があります。"
                    )
                except Exception as e:
                    logger.error(f"Slack error notification failed: {e}")
            else:
                # Keep in pending for next attempt
                still_pending.append(job)

    state["pending_analytics"] = still_pending
    return collected_count
