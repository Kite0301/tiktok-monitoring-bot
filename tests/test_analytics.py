"""24-hour analytics collection."""

from conftest import StubClient, analytics_result, pending_job
from tiktok_client import TikTokClientError


def test_due_job_is_collected_and_notified(write_state, run_cycle):
    write_state(pending=[pending_job("v1", posted_hours_ago=24)])
    result = run_cycle(StubClient(analytics=analytics_result()))

    assert result.pending == []
    assert len(result.completed) == 1
    entry = result.completed[0]
    assert entry["view_count"] == 1000
    assert result.notifier.only("analytics")["view_count"] == 1000
    assert result.commits == ["Update state: 1 analytics"]


def test_job_that_is_not_due_yet_is_left_alone(write_state, run_cycle):
    write_state(
        accounts={"@acct": {"known_video_ids": ["v1"]}},
        pending=[pending_job("v1", due_hours_ago=-5)],
    )
    result = run_cycle()

    assert len(result.pending) == 1
    assert result.completed == []
    assert result.commits == []
    assert result.notifier.calls == []


def test_elapsed_time_is_recorded_from_the_post_time(write_state, run_cycle):
    write_state(
        pending=[pending_job("v1", posted_hours_ago=26, detected_hours_ago=2)]
    )
    result = run_cycle(StubClient(analytics=analytics_result()))

    entry = result.completed[0]
    assert 25.9 < entry["elapsed_hours"] < 26.1
    assert entry["posted_at"] is not None

    note = result.notifier.only("analytics")
    assert 25.9 < note["elapsed_hours"] < 26.1
    assert note["posted_at_is_exact"] is True


def test_job_without_post_time_falls_back_to_detection(write_state, run_cycle):
    """Jobs registered before post-time anchoring carry no posted_at."""
    write_state(pending=[pending_job("v1", detected_hours_ago=24)])
    result = run_cycle(StubClient(analytics=analytics_result()))

    entry = result.completed[0]
    assert entry["posted_at"] is None
    assert 23.9 < entry["elapsed_hours"] < 24.1
    assert result.notifier.only("analytics")["posted_at_is_exact"] is False


def test_failed_collection_is_retried_not_dropped(write_state, run_cycle):
    write_state(pending=[pending_job("v1", posted_hours_ago=24)])
    result = run_cycle(StubClient(analytics=TikTokClientError("unavailable")))

    assert result.exit_code == 0
    assert len(result.pending) == 1
    assert result.pending[0]["retry_count"] == 1
    assert result.completed == []
    assert result.notifier.calls == []


def test_exhausted_retries_record_nulls_and_alert(write_state, run_cycle):
    write_state(
        pending=[pending_job("v1", posted_hours_ago=24, retry_count=2)]
    )
    result = run_cycle(
        StubClient(analytics=TikTokClientError("video removed")),
        max_analytics_retries=3,
    )

    assert result.pending == []
    entry = result.completed[0]
    assert entry["view_count"] is None
    assert entry["elapsed_hours"] is not None
    assert "v1" in result.notifier.only("error")["message"]


def test_slack_failure_does_not_lose_collected_metrics(write_state, run_cycle):
    from conftest import RecordingNotifier

    write_state(pending=[pending_job("v1", posted_hours_ago=24)])
    result = run_cycle(
        StubClient(analytics=analytics_result()),
        notifier=RecordingNotifier(fail_on={"analytics"}),
    )

    assert result.exit_code == 0
    assert len(result.completed) == 1


def test_multiple_due_jobs_are_all_collected(write_state, run_cycle):
    write_state(
        pending=[
            pending_job("v1", posted_hours_ago=24),
            pending_job("v2", posted_hours_ago=25),
            pending_job("v3", due_hours_ago=-10),
        ]
    )
    result = run_cycle(StubClient(analytics=analytics_result()))

    assert len(result.completed) == 2
    assert [job["video_id"] for job in result.pending] == ["v3"]
    assert result.commits == ["Update state: 2 analytics"]
