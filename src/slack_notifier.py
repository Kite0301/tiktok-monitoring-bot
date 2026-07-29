"""Send notifications to Slack via incoming webhook."""

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# Slack rejects a section text longer than 3000 chars; yt-dlp errors can be
# far longer than that.
_MAX_DETAIL_CHARS = 800


def _truncate(text: str) -> str:
    if len(text) <= _MAX_DETAIL_CHARS:
        return text
    return text[:_MAX_DETAIL_CHARS] + " …(以下省略)"


class SlackNotificationError(Exception):
    """Raised when a Slack notification fails."""


class SlackNotifier:
    """Slack incoming webhook client."""

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    def _send(self, payload: dict) -> None:
        """Send a JSON payload to the Slack webhook.

        Uses urllib (stdlib) to avoid adding requests as a dependency.
        """
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._webhook_url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status != 200:
                    raise SlackNotificationError(
                        f"Slack returned status {resp.status}"
                    )
        except urllib.error.URLError as e:
            raise SlackNotificationError(f"Failed to send: {e}") from e

    def notify_new_post(
        self,
        username: str,
        video_id: str,
        video_url: str,
        title: str,
        detected_at: str,
        analytics_due_at: Optional[str] = None,
    ) -> None:
        """Send a new post detection notification in Japanese.

        analytics_due_at is the scheduled measurement time, or None when the
        post was seen too late to be measured at the 24h mark.
        """
        if analytics_due_at:
            analytics_note = f"分析データは {analytics_due_at} に取得します"
        else:
            analytics_note = (
                "投稿から時間が経過しているため、分析データは取得しません"
            )
        payload = {
            "text": f"\u65b0\u898f\u6295\u7a3f\u3092\u691c\u51fa: {username} - {title}",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "\U0001f4f1 \u65b0\u898fTikTok\u6295\u7a3f\u3092\u691c\u51fa",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*\u30a2\u30ab\u30a6\u30f3\u30c8:*\n{username}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*\u691c\u51fa\u6642\u523b:*\n{detected_at}",
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*\u30bf\u30a4\u30c8\u30eb:*\n{title}",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*\u30ea\u30f3\u30af:*\n<{video_url}|\u52d5\u753b\u3092\u898b\u308b>",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": analytics_note,
                        }
                    ],
                },
            ],
        }
        self._send(payload)

    def notify_analytics(
        self,
        username: str,
        video_url: str,
        title: str,
        posted_at: str,
        elapsed_hours: float,
        view_count: Optional[int],
        like_count: Optional[int],
        comment_count: Optional[int],
        repost_count: Optional[int],
        save_count: Optional[int],
        posted_at_is_exact: bool = True,
    ) -> None:
        """Send a 24h analytics notification in Japanese.

        elapsed_hours is how long after posting the metrics were actually
        read; it can exceed 24 when a scheduled run lands late. Showing it
        keeps the number interpretable instead of silently mislabelled.
        """
        # Without a real post time the elapsed window is counted from
        # detection, so say so rather than implying more accuracy than we have.
        time_label = "投稿時刻" if posted_at_is_exact else "検出時刻（投稿時刻は不明）"
        elapsed_from = "投稿" if posted_at_is_exact else "検出"

        def fmt(n: Optional[int]) -> str:
            if n is None:
                return "\u53d6\u5f97\u4e0d\u53ef"
            return f"{n:,}"

        payload = {
            "text": f"24\u6642\u9593\u5206\u6790: {username} - {title}",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "\U0001f4ca 24\u6642\u9593\u5f8c\u306e\u5206\u6790\u30c7\u30fc\u30bf",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*\u30a2\u30ab\u30a6\u30f3\u30c8:*\n{username}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*{time_label}:*\n{posted_at}",
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*\u30bf\u30a4\u30c8\u30eb:*\n{title}",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*\U0001f440 \u518d\u751f\u56de\u6570:*\n{fmt(view_count)}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*\u2764\ufe0f \u3044\u3044\u306d\u6570:*\n{fmt(like_count)}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*\U0001f4ac \u30b3\u30e1\u30f3\u30c8\u6570:*\n{fmt(comment_count)}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*\U0001f504 \u30b7\u30a7\u30a2\u6570:*\n{fmt(repost_count)}",
                        },
                    ],
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*\U0001f516 \u4fdd\u5b58\u6570:*\n{fmt(save_count)}",
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"<{video_url}|\u52d5\u753b\u3092\u898b\u308b>",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"{elapsed_from}\u304b\u3089 {elapsed_hours:.1f} \u6642\u9593\u5f8c\u306e\u6570\u5024\u3067\u3059",
                        }
                    ],
                },
            ],
        }
        self._send(payload)

    def notify_weekly_report(self, accounts: list[str]) -> None:
        """Send a weekly operational status report in Japanese."""
        account_list = "\n".join(f"• {a}" for a in accounts)
        payload = {
            "text": "週次レポート: TikTokモニタリングBot 稼働状況",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "📋 TikTokモニタリングBot 週次レポート",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "このBotは、登録されているTikTokアカウントの投稿を検知し、"
                            "投稿時にSlackへ通知を行います。"
                        ),
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "投稿から24時間経過後に、その動画のパフォーマンス"
                            "（再生回数・いいね数・コメント数・シェア数・保存数）を"
                            "再度通知します。"
                        ),
                    },
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "*現在登録されているアカウントはこちらです:*\n"
                            f"{account_list}"
                        ),
                    },
                },
            ],
        }
        self._send(payload)

    def notify_account_failure(
        self,
        username: str,
        summary: str,
        detail: str,
        consecutive_failures: int,
    ) -> None:
        """Alert that an account has failed extraction repeatedly."""
        payload = {
            "text": f"⚠️ 取得エラーが継続: {username} - {summary}",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "⚠️ 投稿の取得に失敗し続けています",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*アカウント:*\n{username}"},
                        {
                            "type": "mrkdwn",
                            "text": f"*連続失敗回数:*\n{consecutive_failures} 回",
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*考えられる原因:*\n{summary}"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"```{_truncate(detail)}```"},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "この通知は復旧するまで再送しません。復旧時にあらためて通知します。",
                        }
                    ],
                },
            ],
        }
        self._send(payload)

    def notify_account_recovery(self, username: str) -> None:
        """Notify that a previously failing account is working again."""
        payload = {
            "text": f"✅ 取得が復旧: {username}",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ 投稿の取得が復旧しました",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*アカウント:*\n{username}"},
                },
            ],
        }
        self._send(payload)

    def notify_error(self, message: str) -> None:
        """Send an error alert to Slack."""
        payload = {
            "text": f"\u26a0\ufe0f TikTok\u30e2\u30cb\u30bf\u30ea\u30f3\u30b0\u30a8\u30e9\u30fc: {message}",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "\u26a0\ufe0f \u30e2\u30cb\u30bf\u30ea\u30f3\u30b0\u30a8\u30e9\u30fc",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"```{message}```",
                    },
                },
            ],
        }
        self._send(payload)
