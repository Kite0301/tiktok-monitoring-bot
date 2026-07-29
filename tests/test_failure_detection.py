"""Repeated-extraction-failure alerting (#8).

The counter lives in state.json precisely because it has to survive across
runs; these tests drive several consecutive runs to prove that it does.
"""

import pytest

from conftest import RecordingNotifier, StubClient, video
from tiktok_client import AccountNotFoundError, TikTokClientError

THRESHOLD = 3


def failing_client(error):
    return StubClient(videos=error)


def healthy_client():
    return StubClient(videos=[video("v1")])


def run_failures(run_cycle, times, error=None, notifier=None):
    """Run `times` consecutive failing cycles, returning the last result."""
    error = error or AccountNotFoundError("Unable to find user")
    result = None
    for _ in range(times):
        result = run_cycle(
            failing_client(error),
            notifier=notifier,
            failure_alert_threshold=THRESHOLD,
        )
    return result


def test_no_alert_before_the_threshold(write_state, run_cycle):
    write_state(accounts={"@acct": {"known_video_ids": ["v1"]}})
    result = run_failures(run_cycle, THRESHOLD - 1)

    assert result.account()["consecutive_failures"] == THRESHOLD - 1
    assert result.notifier.calls == []


def test_alert_fires_once_the_threshold_is_reached(write_state, run_cycle):
    write_state(accounts={"@acct": {"known_video_ids": ["v1"]}})
    result = run_failures(run_cycle, THRESHOLD)

    alert = result.notifier.only("failure")
    assert alert["username"] == "@acct"
    assert alert["consecutive_failures"] == THRESHOLD
    assert result.account()["failure_notified"] is True


def test_ongoing_outage_neither_realerts_nor_commits(write_state, run_cycle):
    write_state(accounts={"@acct": {"known_video_ids": ["v1"]}})
    run_failures(run_cycle, THRESHOLD)

    for _ in range(3):
        result = run_failures(run_cycle, 1)
        assert result.notifier.calls == []
        assert result.commits == []
        # Capped, so the state stops changing and stops producing commits.
        assert result.account()["consecutive_failures"] == THRESHOLD


def test_recovery_notifies_and_clears_the_tracking(write_state, run_cycle):
    write_state(accounts={"@acct": {"known_video_ids": ["v1"]}})
    run_failures(run_cycle, THRESHOLD)

    result = run_cycle(healthy_client(), failure_alert_threshold=THRESHOLD)

    assert result.notifier.only("recovery")["username"] == "@acct"
    account = result.account()
    assert "consecutive_failures" not in account
    assert "failure_notified" not in account
    assert account["known_video_ids"] == ["v1"]


def test_healthy_runs_leave_no_tracking_in_the_state(write_state, run_cycle):
    write_state(accounts={"@acct": {"known_video_ids": ["v1"]}})
    result = run_cycle(healthy_client(), failure_alert_threshold=THRESHOLD)

    assert set(result.account()) == {"known_video_ids"}
    assert result.commits == []
    assert result.notifier.calls == []


@pytest.mark.parametrize(
    "error",
    [
        AccountNotFoundError("Unable to find user"),
        TikTokClientError("HTTP Error 429: Too Many Requests"),
        ValueError("something entirely unexpected"),
    ],
    ids=["account_not_found", "extraction_failed", "unexpected"],
)
def test_every_failure_kind_counts_towards_the_alert(
    write_state, run_cycle, error
):
    """The old implementation only ever noticed AccountNotFoundError."""
    write_state(accounts={"@acct": {"known_video_ids": ["v1"]}})
    result = run_failures(run_cycle, THRESHOLD, error=error)

    assert result.notifier.only("failure")["summary"]


def test_alert_is_retried_when_slack_is_down(write_state, run_cycle):
    write_state(accounts={"@acct": {"known_video_ids": ["v1"]}})
    broken = RecordingNotifier(fail_on={"failure"})
    result = run_failures(run_cycle, THRESHOLD, notifier=broken)

    # Not marked as notified, so the next run tries again.
    assert "failure_notified" not in result.account()

    result = run_failures(run_cycle, 1)
    assert result.notifier.only("failure")
    assert result.account()["failure_notified"] is True


def test_state_without_the_tracking_fields_still_works(write_state, run_cycle):
    """State written before this feature existed needs no migration."""
    write_state(accounts={"@acct": {"known_video_ids": ["v1"]}})
    result = run_cycle(healthy_client())

    assert result.exit_code == 0
    assert result.commits == []
