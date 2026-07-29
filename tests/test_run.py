"""The unified entry point (#9).

The point of running both phases in one process is that state.json has
exactly one writer, so the phases cannot lose each other's changes.
"""

import subprocess

from conftest import StubClient, analytics_result, pending_job, video


def test_both_phases_run_and_the_state_is_written_once(
    write_state, run_cycle, state_path
):
    write_state(
        accounts={"@acct": {"known_video_ids": ["v1"]}},
        pending=[pending_job("v0", posted_hours_ago=24)],
    )
    client = StubClient(
        videos=[video("v2", hours_ago=1), video("v1")],
        analytics=analytics_result(),
    )
    result = run_cycle(client)

    assert result.exit_code == 0
    assert result.notifier.kinds == ["new_post", "analytics"]
    assert "v2" in result.account()["known_video_ids"]
    assert len(result.completed) == 1
    assert len(result.commits) == 1


def test_commit_message_describes_what_the_run_did(write_state, run_cycle):
    write_state(
        accounts={"@acct": {"known_video_ids": ["v1"]}},
        pending=[pending_job("v0", posted_hours_ago=24)],
    )
    result = run_cycle(
        StubClient(
            videos=[video("v2", hours_ago=1), video("v1")],
            analytics=analytics_result(),
        )
    )

    assert result.commits == ["Update state: 1 new post(s), 1 analytics"]


def test_nothing_to_do_means_no_write_and_no_commit(write_state, run_cycle):
    write_state(accounts={"@acct": {"known_video_ids": ["v1"]}})
    result = run_cycle(StubClient(videos=[video("v1")]))

    assert result.exit_code == 0
    assert result.commits == []
    assert result.notifier.calls == []


def test_a_crashing_phase_does_not_discard_the_other_phase(
    write_state, run_cycle, monkeypatch
):
    """Detection blows up outside its per-account handler; analytics lands."""
    import monitor

    write_state(
        accounts={"@acct": {"known_video_ids": ["v1"]}},
        pending=[pending_job("v0", posted_hours_ago=24)],
    )

    def boom(*args, **kwargs):
        raise RuntimeError("detection phase exploded")

    monkeypatch.setattr(monitor, "_get_account_state", boom)
    result = run_cycle(StubClient(analytics=analytics_result()))

    assert result.exit_code == 1
    assert len(result.completed) == 1
    assert result.notifier.kinds == ["analytics"]
    assert len(result.commits) == 1


def test_a_crashing_analytics_phase_keeps_the_detections(
    write_state, run_cycle, monkeypatch
):
    import analytics

    write_state(
        accounts={"@acct": {"known_video_ids": ["v1"]}},
        pending=[pending_job("v0", posted_hours_ago=24)],
    )

    def boom(*args, **kwargs):
        raise RuntimeError("analytics phase exploded")

    monkeypatch.setattr(analytics, "_completed_entry", boom)
    result = run_cycle(
        StubClient(
            videos=[video("v2", hours_ago=1), video("v1")],
            analytics=analytics_result(),
        )
    )

    assert result.exit_code == 1
    assert "v2" in result.account()["known_video_ids"]
    assert result.notifier.kinds == ["new_post"]
    assert len(result.commits) == 1


def test_push_failure_is_reported_as_a_failed_run(write_state, run_cycle):
    """Previously this was logged and the run still reported success."""
    write_state(accounts={"@acct": {"known_video_ids": ["v1"]}})
    result = run_cycle(
        StubClient(videos=[video("v2", hours_ago=1), video("v1")]),
        push_error=subprocess.CalledProcessError(1, ["git", "push"]),
    )

    assert result.exit_code == 1
    assert result.commits == []


def test_configuration_error_exits_nonzero(monkeypatch, state_path):
    import run as run_module

    def bad_config():
        raise ValueError("SLACK_WEBHOOK_URL is not set")

    monkeypatch.setattr(run_module, "load_config", bad_config)
    assert run_module.main() == 1
