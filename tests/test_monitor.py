"""New post detection, including post-time anchoring (#13)."""

from datetime import datetime, timedelta, timezone

import pytest

from conftest import RecordingNotifier, StubClient, analytics_result, video

UTC = timezone.utc


def test_first_run_records_existing_videos_without_notifying(run_cycle):
    result = run_cycle(StubClient(videos=[video("v1"), video("v2")]))

    assert result.known == ["v1", "v2"]
    assert result.notifier.calls == []
    assert result.pending == []


def test_new_post_is_notified_and_scheduled(write_account, run_cycle):
    write_account(known=["v1"])
    result = run_cycle(StubClient(videos=[video("v2", hours_ago=1), video("v1")]))

    assert "v2" in result.known
    posted = result.notifier.only("new_post")
    assert posted["video_id"] == "v2"
    assert posted["analytics_due_at"] is not None
    assert len(result.pending) == 1
    assert result.commits == ["Update state: 1 new post(s)"]


@pytest.mark.xfail(
    strict=True,
    reason="issue #16: an account with no videos stays in first-run mode, so "
    "its first ever post is recorded silently instead of notified",
)
def test_first_post_from_a_previously_empty_account_is_notified(
    write_account, run_cycle
):
    """Monitoring starts before the account has posted anything."""
    write_account(known=[])
    result = run_cycle(StubClient(videos=[video("v1", hours_ago=1)]))

    assert result.notifier.only("new_post")["video_id"] == "v1"


def test_known_videos_are_not_renotified(write_account, run_cycle):
    write_account(known=["v1", "v2"])
    result = run_cycle(StubClient(videos=[video("v2"), video("v1")]))

    assert result.notifier.calls == []
    assert result.commits == []


def test_slack_failure_does_not_lose_the_detection(write_account, run_cycle):
    """A dropped notification must not cost us the recorded video id."""
    write_account(known=["v1"])
    result = run_cycle(
        StubClient(videos=[video("v2", hours_ago=1), video("v1")]),
        notifier=RecordingNotifier(fail_on={"new_post"}),
    )

    assert result.exit_code == 0
    assert "v2" in result.known
    assert len(result.pending) == 1


def test_one_account_failing_does_not_stop_the_others(write_account, run_cycle):
    from tiktok_client import TikTokClientError

    write_account("@ok", known=["v1"])
    write_account("@broken", known=["v9"])
    client = StubClient(
        videos={
            "@ok": [video("v2", hours_ago=1), video("v1")],
            "@broken": TikTokClientError("boom"),
        }
    )
    result = run_cycle(client, accounts=["@broken", "@ok"])

    assert "v2" in result.account("@ok")["known_video_ids"]
    assert result.notifier.only("new_post")["video_id"] == "v2"
    assert result.account("@broken")["consecutive_failures"] == 1


class TestPostTimeAnchoring:
    """The 24h window is counted from the post time, not from detection."""

    def test_due_time_is_measured_from_the_post_time(
        self, write_account, run_cycle
    ):
        write_account(known=["v1"])
        result = run_cycle(
            StubClient(videos=[video("v2", hours_ago=2), video("v1")])
        )

        job = result.pending[0]
        posted = datetime.fromisoformat(job["posted_at"])
        due = datetime.fromisoformat(job["analytics_due_at"])
        assert abs((due - posted).total_seconds() - 24 * 3600) < 2

        # ...which is ~2h earlier than anchoring on detection would give.
        detection_based = datetime.now(UTC) + timedelta(hours=24)
        drift_hours = (detection_based - due).total_seconds() / 3600
        assert 1.9 < drift_hours < 2.1

    def test_missing_timestamp_falls_back_to_detection_time(
        self, write_account, run_cycle
    ):
        write_account(known=["v1"])
        result = run_cycle(
            StubClient(videos=[video("v2", hours_ago=None), video("v1")])
        )

        job = result.pending[0]
        assert job["posted_at"] is None
        due = datetime.fromisoformat(job["analytics_due_at"])
        expected = datetime.now(UTC) + timedelta(hours=24)
        assert abs((due - expected).total_seconds()) < 5

    def test_post_seen_too_late_gets_no_analytics_job(
        self, write_account, run_cycle
    ):
        """A 31h-old post would yield a 31h number; keep it out entirely."""
        write_account(known=["v1"])
        result = run_cycle(
            StubClient(videos=[video("v2", hours_ago=31), video("v1")])
        )

        assert result.pending == []
        assert "v2" in result.known
        assert result.notifier.only("new_post")["analytics_due_at"] is None

    def test_late_but_acceptable_post_is_measured_immediately(
        self, write_account, run_cycle
    ):
        """29h is inside the 24h+6h window, so it is due the moment we see it."""
        write_account(known=["v1"])
        result = run_cycle(
            StubClient(
                videos=[video("v2", hours_ago=29), video("v1")],
                analytics=analytics_result(),
            )
        )

        assert result.pending == []
        assert len(result.completed) == 1
        assert 28.9 < result.completed[0]["elapsed_hours"] < 29.1
        assert result.notifier.kinds == ["new_post", "analytics"]

    def test_lateness_allowance_is_configurable(self, write_account, run_cycle):
        write_account(known=["v1"])
        result = run_cycle(
            StubClient(
                videos=[video("v2", hours_ago=31), video("v1")],
                analytics=analytics_result(),
            ),
            analytics_max_lateness_hours=12,
        )

        assert len(result.completed) == 1
