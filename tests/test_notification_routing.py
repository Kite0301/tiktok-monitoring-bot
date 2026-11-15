"""Collect-only accounts (notify=false).

The line: what the account posted is silenced, whether the bot still works
is not. A silent account must not be able to stop collecting unnoticed.
"""

import pytest

from conftest import StubClient, analytics_result, pending_job, video
from config import Account
from tiktok_client import TikTokClientError

SILENT = Account("@quiet", notify=False)
LOUD = Account("@loud", notify=True)


def test_a_silent_account_still_collects_everything(write_account, run_cycle):
    write_account("@quiet", known=["v1"])
    result = run_cycle(
        StubClient(videos=[video("v2", hours_ago=1), video("v1")]),
        accounts=[SILENT],
    )

    assert "v2" in result.account("@quiet")["known_video_ids"]
    assert len(result.account("@quiet")["pending_analytics"]) == 1
    assert len(result.commits) == 1


def test_a_silent_account_sends_no_new_post_message(write_account, run_cycle):
    write_account("@quiet", known=["v1"])
    result = run_cycle(
        StubClient(videos=[video("v2", hours_ago=1), video("v1")]),
        accounts=[SILENT],
    )

    assert result.notifier.calls == []


def test_a_silent_account_sends_no_analytics_message(write_account, run_cycle):
    write_account(
        "@quiet",
        known=["v1"],
        pending=[pending_job("v1", username="@quiet", posted_hours_ago=24)],
    )
    result = run_cycle(
        StubClient(videos=[video("v1")], analytics=analytics_result()),
        accounts=[SILENT],
    )

    assert result.notifier.calls == []
    assert len(result.account("@quiet")["completed_analytics"]) == 1


def test_a_silent_account_still_reports_repeated_failures(
    write_account, run_cycle
):
    """Otherwise a collect-only account could stop collecting silently."""
    write_account("@quiet", known=["v1"])
    for _ in range(3):
        result = run_cycle(
            StubClient(videos=TikTokClientError("boom")),
            accounts=[SILENT],
            failure_alert_threshold=3,
        )

    assert result.notifier.only("failure")["username"] == "@quiet"


def test_a_silent_account_still_reports_recovery(write_account, run_cycle):
    write_account("@quiet", known=["v1"])
    for _ in range(3):
        run_cycle(
            StubClient(videos=TikTokClientError("boom")),
            accounts=[SILENT],
            failure_alert_threshold=3,
        )

    result = run_cycle(
        StubClient(videos=[video("v1")]),
        accounts=[SILENT],
        failure_alert_threshold=3,
    )

    assert result.notifier.only("recovery")["username"] == "@quiet"


def test_a_silent_account_does_not_report_a_lost_video(write_account, run_cycle):
    """A deleted video is content, not a health problem."""
    write_account(
        "@quiet",
        known=["v1"],
        pending=[
            pending_job("v1", username="@quiet", posted_hours_ago=24, retry_count=2)
        ],
    )
    result = run_cycle(
        StubClient(videos=[video("v1")], analytics=TikTokClientError("gone")),
        accounts=[SILENT],
        max_analytics_retries=3,
    )

    assert result.notifier.calls == []
    assert result.account("@quiet")["completed_analytics"][0]["view_count"] is None


def test_silence_applies_per_account(write_account, run_cycle):
    write_account("@quiet", known=["a1"])
    write_account("@loud", known=["b1"])
    client = StubClient(
        videos={
            "@quiet": [video("a2", hours_ago=1), video("a1")],
            "@loud": [video("b2", hours_ago=1), video("b1")],
        }
    )
    result = run_cycle(client, accounts=[SILENT, LOUD])

    assert result.notifier.only("new_post")["username"] == "@loud"
    assert "a2" in result.account("@quiet")["known_video_ids"]


class TestAccountConfig:
    def test_a_plain_string_still_means_a_notifying_account(self):
        from config import _parse_account

        assert _parse_account("@a") == Account("@a", notify=True)

    def test_notify_defaults_to_true_for_an_object(self):
        from config import _parse_account

        assert _parse_account({"username": "@a"}).notify is True

    def test_notify_can_be_turned_off(self):
        from config import _parse_account

        assert _parse_account({"username": "@a", "notify": False}).notify is False

    @pytest.mark.parametrize("entry", [{}, {"notify": True}, 42, None])
    def test_malformed_entries_are_rejected(self, entry):
        from config import _parse_account

        with pytest.raises(ValueError):
            _parse_account(entry)

    def test_the_shipped_config_parses(self):
        """config/accounts.json must stay loadable as the format evolves."""
        import json
        from pathlib import Path

        from config import _parse_account

        repo = Path(__file__).resolve().parent.parent
        data = json.loads(
            (repo / "config" / "accounts.json").read_text(encoding="utf-8")
        )
        accounts = [_parse_account(e) for e in data["accounts"]]

        assert accounts
        assert len({a.username for a in accounts}) == len(accounts)
