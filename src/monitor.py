"""New post detection.

Checks each configured TikTok account for new posts, sends Slack
notifications, and registers 24-hour analytics follow-up jobs. Accounts
that keep failing extraction are alerted on, once, until they recover.

Mutates the state dict in place. Loading, saving and committing the state
is run.py's responsibility, so that a single run writes it exactly once.
"""

import logging
from datetime import datetime, timedelta, timezone

from config import Config
from slack_notifier import SlackNotifier
from state_manager import State
from tiktok_client import (
    AccountNotFoundError,
    TikTokClient,
    TikTokClientError,
)

JST = timezone(timedelta(hours=9))

logger = logging.getLogger(__name__)


def _get_account_state(state: State, username: str) -> dict:
    """Get or initialize persistent state for one account."""
    account = state["accounts"].setdefault(username, {})
    account.setdefault("known_video_ids", [])
    return account


def _record_failure(
    account: dict,
    username: str,
    summary: str,
    detail: str,
    notifier: SlackNotifier,
    threshold: int,
) -> None:
    """Count an extraction failure and alert Slack once the threshold is hit.

    The counter stops at the threshold so that an ongoing outage stops
    changing the state, which in turn stops producing git commits.
    """
    failures = account.get("consecutive_failures", 0)
    if failures < threshold:
        failures += 1
        account["consecutive_failures"] = failures

    if failures < threshold or account.get("failure_notified"):
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

    account["failure_notified"] = True


def _record_success(
    account: dict, username: str, notifier: SlackNotifier
) -> None:
    """Clear failure tracking, notifying Slack if we had alerted about it."""
    if not account.get("consecutive_failures") and not account.get(
        "failure_notified"
    ):
        return

    was_notified = account.pop("failure_notified", False)
    account.pop("consecutive_failures", None)

    if not was_notified:
        return

    try:
        notifier.notify_account_recovery(username)
    except Exception as e:
        logger.error(f"Slack recovery notification failed for {username}: {e}")


def check_new_posts(
    state: State,
    config: Config,
    notifier: SlackNotifier,
    client: TikTokClient,
    now: datetime,
) -> int:
    """Check every configured account for new posts.

    Returns the number of new posts detected. A failure on one account is
    logged and counted, but never stops the remaining accounts.
    """
    new_post_count = 0

    for username in config.accounts:
        account = _get_account_state(state, username)

        try:
            videos = client.list_recent_videos(username)
            known_ids = set(account["known_video_ids"])
            new_videos = [v for v in videos if v.video_id not in known_ids]

            # On first run, record existing videos silently (no notifications)
            if len(known_ids) == 0:
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
                    new_post_count += 1

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
                            detected_at=now.astimezone(JST).strftime("%Y-%m-%d %H:%M JST"),
                        )
                    except Exception as e:
                        logger.error(f"Slack notification failed: {e}")

            _record_success(account, username, notifier)

        except AccountNotFoundError as e:
            logger.warning(f"Account not found: {username}: {e}")
            _record_failure(
                account,
                username,
                "アカウントが存在しないか、非公開・改名・削除された可能性があります。",
                str(e),
                notifier,
                config.failure_alert_threshold,
            )

        except TikTokClientError as e:
            logger.warning(f"TikTok extraction failed for {username}: {e}")
            _record_failure(
                account,
                username,
                "TikTok からのデータ取得に失敗しました。"
                "レート制限、または yt-dlp の TikTok 対応が壊れている可能性があります。",
                str(e),
                notifier,
                config.failure_alert_threshold,
            )

        except Exception as e:
            logger.error(
                f"Unexpected error for {username}: {e}", exc_info=True
            )
            _record_failure(
                account,
                username,
                "予期しないエラーが発生しました。",
                f"{type(e).__name__}: {e}",
                notifier,
                config.failure_alert_threshold,
            )

    return new_post_count
