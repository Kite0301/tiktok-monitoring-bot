"""Send notifications to Slack via incoming webhook."""

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)


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
    ) -> None:
        """Send a new post detection notification in Japanese."""
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
                            "text": "24\u6642\u9593\u5f8c\u306b\u5206\u6790\u30c7\u30fc\u30bf\u3092\u53d6\u5f97\u3057\u307e\u3059",
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
        detected_at: str,
        view_count: Optional[int],
        like_count: Optional[int],
        comment_count: Optional[int],
        repost_count: Optional[int],
        save_count: Optional[int],
    ) -> None:
        """Send a 24h analytics notification in Japanese."""

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
                            "text": f"*\u6295\u7a3f\u691c\u51fa\u6642\u523b:*\n{detected_at}",
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
