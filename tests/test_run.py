"""The unified entry point.

Both phases run in one process against per-account files, so accounts
cannot disturb each other and the phases cannot lose each other's changes.
"""

import subprocess

from conftest import StubClient, analytics_result, pending_job, video


def test_both_phases_run_and_commit_once(write_account, run_cycle):
    write_account(known=["v1"], pending=[pending_job("v0", posted_hours_ago=24)])
    client = StubClient(
        videos=[video("v2", hours_ago=1), video("v1")],
        analytics=analytics_result(),
    )
    result = run_cycle(client)

    assert result.exit_code == 0
    assert result.notifier.kinds == ["new_post", "analytics"]
    assert "v2" in result.known
    assert len(result.completed) == 1
    assert len(result.commits) == 1


def test_commit_message_describes_what_the_run_did(write_account, run_cycle):
    write_account(known=["v1"], pending=[pending_job("v0", posted_hours_ago=24)])
    result = run_cycle(
        StubClient(
            videos=[video("v2", hours_ago=1), video("v1")],
            analytics=analytics_result(),
        )
    )

    assert result.commits == ["Update state: 1 new post(s), 1 analytics"]


def test_nothing_to_do_means_no_write_and_no_commit(write_account, run_cycle):
    write_account(known=["v1"])
    result = run_cycle(StubClient(videos=[video("v1")]))

    assert result.exit_code == 0
    assert result.commits == []
    assert result.notifier.calls == []


def test_a_crashing_phase_does_not_discard_the_other_phase(
    write_account, run_cycle, monkeypatch
):
    """Detection blows up outside its per-account handler; analytics lands."""
    import run as run_module

    write_account(known=["v1"], pending=[pending_job("v0", posted_hours_ago=24)])

    def boom(*args, **kwargs):
        raise RuntimeError("detection phase exploded")

    monkeypatch.setattr(run_module, "check_account", boom)
    result = run_cycle(StubClient(analytics=analytics_result()))

    assert result.exit_code == 1
    assert len(result.completed) == 1
    assert result.notifier.kinds == ["analytics"]
    assert len(result.commits) == 1


def test_a_crashing_analytics_phase_keeps_the_detections(
    write_account, run_cycle, monkeypatch
):
    import analytics

    write_account(known=["v1"], pending=[pending_job("v0", posted_hours_ago=24)])

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
    assert "v2" in result.known
    assert result.notifier.kinds == ["new_post"]
    assert len(result.commits) == 1


def test_push_failure_is_reported_as_a_failed_run(write_account, run_cycle):
    """Previously this was logged and the run still reported success."""
    write_account(known=["v1"])
    result = run_cycle(
        StubClient(videos=[video("v2", hours_ago=1), video("v1")]),
        push_error=subprocess.CalledProcessError(1, ["git", "push"]),
    )

    assert result.exit_code == 1
    assert result.commits == []


def test_configuration_error_exits_nonzero(monkeypatch):
    import run as run_module

    def bad_config():
        raise ValueError("SLACK_WEBHOOK_URL is not set")

    monkeypatch.setattr(run_module, "load_config", bad_config)
    assert run_module.main() == 1


class TestLegacyMigrationOnStartup:
    """The split happens on the first real run, with no manual step."""

    def write_legacy(self, path):
        import json

        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "accounts": {"@acct": {"known_video_ids": ["v1"]}},
                    "pending_analytics": [],
                    "completed_analytics": [
                        {"video_id": "v1", "username": "@acct", "view_count": 7}
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_the_run_splits_the_legacy_file_and_commits_it(
        self, run_cycle, legacy_state_path
    ):
        self.write_legacy(legacy_state_path)
        result = run_cycle(StubClient(videos=[video("v1")]))

        assert result.exit_code == 0
        assert result.known == ["v1"]
        assert result.completed[0]["view_count"] == 7
        assert not legacy_state_path.exists()
        assert "split 1 account(s)" in result.commits[0]

    def test_migrated_history_is_not_re_notified(
        self, run_cycle, legacy_state_path
    ):
        self.write_legacy(legacy_state_path)
        result = run_cycle(StubClient(videos=[video("v1")]))

        assert result.notifier.calls == []

    def test_the_next_run_has_nothing_left_to_migrate(
        self, run_cycle, legacy_state_path
    ):
        self.write_legacy(legacy_state_path)
        run_cycle(StubClient(videos=[video("v1")]))
        result = run_cycle(StubClient(videos=[video("v1")]))

        assert result.commits == []
        assert result.known == ["v1"]


class TestPerAccountIsolation:
    """Each account owns its own file."""

    def test_each_account_gets_its_own_file(self, write_account, run_cycle, data_dir):
        write_account("@one", known=["a1"])
        write_account("@two", known=["b1"])
        client = StubClient(
            videos={
                "@one": [video("a2", hours_ago=1), video("a1")],
                "@two": [video("b1")],
            }
        )
        result = run_cycle(client, accounts=["@one", "@two"])

        assert sorted(p.name for p in data_dir.glob("*.json")) == [
            "one.json",
            "two.json",
        ]
        assert "a2" in result.account("@one")["known_video_ids"]
        assert result.account("@two")["known_video_ids"] == ["b1"]

    def test_an_account_only_stores_its_own_analytics(
        self, write_account, run_cycle
    ):
        write_account("@one", known=["a1"], pending=[
            pending_job("a1", username="@one", posted_hours_ago=24)
        ])
        write_account("@two", known=["b1"])
        client = StubClient(
            videos={"@one": [video("a1")], "@two": [video("b1")]},
            analytics=analytics_result(),
        )
        result = run_cycle(client, accounts=["@one", "@two"])

        assert len(result.account("@one")["completed_analytics"]) == 1
        assert result.account("@two")["completed_analytics"] == []

    def test_history_limit_applies_per_account(self, write_account, run_cycle):
        """A prolific account must not crowd the others out of the dataset."""
        old = [{"video_id": f"x{i}", "username": "@acct"} for i in range(10)]
        write_account(
            known=["v1"],
            completed=old,
            pending=[pending_job("v1", posted_hours_ago=24)],
        )
        result = run_cycle(
            StubClient(videos=[video("v1")], analytics=analytics_result()),
            max_completed_history=5,
        )

        assert len(result.completed) == 5
        assert result.completed[-1]["video_id"] == "v1"
