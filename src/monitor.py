"""New post detection.

Checks one account for new posts, sends Slack notifications, and registers
24-hour analytics follow-up jobs. An account that keeps failing extraction
is alerted on, once, until it recovers.

Mutates the account's state dict in place. Loading, saving and committing
it is run.py's responsibility.
"""

import logging
from datetime import datetime, timedelta, timezone

from account_store import AccountState
from config import Account, Config
from tiktok_client import (
    AccountNotFoundError,
    TikTokClient,
    TikTokClientError,
)

JST = timezone(timedelta(hours=9))

logger = logging.getLogger(__name__)


def _posted_at(video, fallback: datetime) -> tuple[datetime, bool]:
    """Return the video's post time, falling back to the detection time.

    yt-dlp exposes the real upload time for TikTok even in flat-playlist
    mode, but it is not guaranteed to be present on every entry.

    Returns (anchor, is_real_post_time).
    """
    if video.timestamp:
        return datetime.fromtimestamp(video.timestamp, timezone.utc), True
    return fallback, False


def _record_failure(
    state: AccountState,
    username: str,
    summary: str,
    detail: str,
    notifier,
    threshold: int,
) -> None:
    """Count an extraction failure and alert Slack once the threshold is hit.

    The counter stops at the threshold so that an ongoing outage stops
    changing the state, which in turn stops producing git commits.
    """
    failures = state.get("consecutive_failures", 0)
    if failures < threshold:
        failures += 1
        state["consecutive_failures"] = failures

    if failures < threshold or state.get("failure_notified"):
        return

    try:
        notifier.notify_account_failure(
            username=username,
            summary=summary,
            detail=detail,
            consecutive_failures=failures,
        )
    except Exception as e:
        # Leave failure_notified unset so the next run retries the alert.
        logger.error(f"Slack failure alert failed for {username}: {e}")
        return

    state["failure_notified"] = True


def _record_success(state: AccountState, username: str, notifier) -> None:
    """Clear failure tracking, notifying Slack if we had alerted about it."""
    if not state.get("consecutive_failures") and not state.get("failure_notified"):
        return

    was_notified = state.pop("failure_notified", False)
    state.pop("consecutive_failures", None)

    if not was_notified:
        return

    try:
        notifier.notify_account_recovery(username)
    except Exception as e:
        logger.error(f"Slack recovery notification failed for {username}: {e}")


def check_account(
    account: Account,
    state: AccountState,
    config: Config,
    notifier,
    client: TikTokClient,
    now: datetime,
) -> int:
    """Check one account for new posts.

    Returns the number of new posts detected. Extraction failures are
    recorded and alerted on rather than raised, so that the caller can carry
    on with the remaining accounts.
    """
    username = account.username
    new_post_count = 0

    try:
        videos = client.list_recent_videos(username)
        known_ids = set(state["known_video_ids"])
        new_videos = [v for v in videos if v.video_id not in known_ids]

        # On first run, record existing videos silently (no notifications)
        if len(known_ids) == 0:
            logger.info(
                f"First run for {username}: recording {len(videos)} "
                f"existing videos without notification"
            )
            state["known_video_ids"] = [v.video_id for v in videos]
        else:
            for video in new_videos:
                logger.info(f"New post detected: {username} - {video.video_id}")
                state["known_video_ids"].append(video.video_id)
                new_post_count += 1

                # Measure 24h from when the video was posted, not from when
                # we happened to notice it.
                anchor, has_post_time = _posted_at(video, now)
                due = anchor + timedelta(hours=config.analytics_delay_hours)
                deadline = due + timedelta(
                    hours=config.analytics_max_lateness_hours
                )

                if now <= deadline:
                    state["pending_analytics"].append(
                        {
                            "video_id": video.video_id,
                            "username": username,
                            "video_url": video.url,
                            "posted_at": (
                                anchor.isoformat() if has_post_time else None
                            ),
                            "detected_at": now.isoformat(),
                            "analytics_due_at": due.isoformat(),
                            "title": video.title,
                            "retry_count": 0,
                        }
                    )
                    due_label = due.astimezone(JST).strftime("%Y-%m-%d %H:%M JST")
                else:
                    # Seen too late for the number to mean "24h performance"
                    # -- keep it out of the dataset.
                    age_hours = (now - anchor).total_seconds() / 3600
                    logger.info(
                        f"Skipping analytics for {video.video_id}: "
                        f"posted {age_hours:.1f}h ago, past the "
                        f"{config.analytics_delay_hours}h window"
                    )
                    due_label = None

                try:
                    notifier.notify_new_post(
                        username=username,
                        video_id=video.video_id,
                        video_url=video.url,
                        title=video.title,
                        detected_at=now.astimezone(JST).strftime("%Y-%m-%d %H:%M JST"),
                        analytics_due_at=due_label,
                    )
                except Exception as e:
                    logger.error(f"Slack notification failed: {e}")

        _record_success(state, username, notifier)

    except AccountNotFoundError as e:
        logger.warning(f"Account not found: {username}: {e}")
        _record_failure(
            state,
            username,
            "アカウントが存在しないか、非公開・改名・削除された可能性があります。",
            str(e),
            notifier,
            config.failure_alert_threshold,
        )

    except TikTokClientError as e:
        logger.warning(f"TikTok extraction failed for {username}: {e}")
        _record_failure(
            state,
            username,
            "TikTok からのデータ取得に失敗しました。"
            "レート制限、または yt-dlp の TikTok 対応が壊れている可能性があります。",
            str(e),
            notifier,
            config.failure_alert_threshold,
        )

    except Exception as e:
        logger.error(f"Unexpected error for {username}: {e}", exc_info=True)
        _record_failure(
            state,
            username,
            "予期しないエラーが発生しました。",
            f"{type(e).__name__}: {e}",
            notifier,
            config.failure_alert_threshold,
        )

    return new_post_count
