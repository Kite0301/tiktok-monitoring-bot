"""Send test notifications to Slack to verify webhook configuration.

Usage:
    python src/test_slack.py

Requires SLACK_WEBHOOK_URL environment variable.
"""

import os
import sys
from datetime import datetime, timezone, timedelta

from slack_notifier import SlackNotifier

JST = timezone(timedelta(hours=9))


def main() -> None:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        print("ERROR: SLACK_WEBHOOK_URL is not set", file=sys.stderr)
        sys.exit(1)

    notifier = SlackNotifier(webhook_url)
    now_jst = datetime.now(JST)
    detected_at = now_jst.strftime("%Y-%m-%d %H:%M JST")

    # --- Test 1: New post detection notification ---
    print("Sending test notification: new post detection...")
    notifier.notify_new_post(
        username="@test_account",
        video_id="0000000000000000000",
        video_url="https://www.tiktok.com/@test_account/video/0000000000000000000",
        title="[テスト] Slack Webhook 通知テスト",
        detected_at=detected_at,
    )
    print("OK: new post detection notification sent.")

    # --- Test 2: 24h analytics notification ---
    print("Sending test notification: 24h analytics...")
    notifier.notify_analytics(
        username="@test_account",
        video_url="https://www.tiktok.com/@test_account/video/0000000000000000000",
        title="[テスト] Slack Webhook 通知テスト",
        detected_at=detected_at,
        view_count=12345,
        like_count=678,
        comment_count=90,
        repost_count=12,
        save_count=34,
    )
    print("OK: 24h analytics notification sent.")

    print("All test notifications sent successfully.")


if __name__ == "__main__":
    main()
