"""Shared fixtures and stubs.

Every test runs against stubbed TikTok, Slack and git, so the suite never
reaches the network and never touches the real data/state.json.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

import run as run_module
from config import Config
from tiktok_client import VideoAnalytics, VideoSummary

UTC = timezone.utc


class RecordingNotifier:
    """Slack stub that records calls instead of sending them.

    Pass `fail_on` to simulate Slack being unavailable for those calls.
    """

    def __init__(self, webhook_url=None, fail_on=()):
        self.calls: list[tuple[str, dict]] = []
        self.fail_on = set(fail_on)

    def _record(self, kind: str, payload: dict) -> None:
        if kind in self.fail_on:
            raise RuntimeError(f"slack is unavailable ({kind})")
        self.calls.append((kind, payload))

    def notify_new_post(self, **kw):
        self._record("new_post", kw)

    def notify_analytics(self, **kw):
        self._record("analytics", kw)

    def notify_error(self, message):
        self._record("error", {"message": message})

    def notify_account_failure(self, **kw):
        self._record("failure", kw)

    def notify_account_recovery(self, username):
        self._record("recovery", {"username": username})

    @property
    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.calls]

    def payloads(self, kind: str) -> list[dict]:
        return [payload for k, payload in self.calls if k == kind]

    def only(self, kind: str) -> dict:
        """The single payload of `kind`; fails if there is not exactly one."""
        found = self.payloads(kind)
        assert len(found) == 1, f"expected 1 {kind!r} call, got {len(found)}"
        return found[0]


class StubClient:
    """TikTok stub.

    `videos` is a list, a {username: list} mapping, or an exception to raise.
    `analytics` is a VideoAnalytics or an exception to raise.
    """

    def __init__(self, videos=(), analytics=None):
        self._videos = videos
        self._analytics = analytics

    def list_recent_videos(self, username):
        result = self._videos
        if isinstance(result, dict):
            result = result.get(username, [])
        if isinstance(result, BaseException):
            raise result
        return list(result)

    def get_video_analytics(self, video_url):
        if self._analytics is None:
            raise AssertionError("unexpected analytics call in this test")
        if isinstance(self._analytics, BaseException):
            raise self._analytics
        return self._analytics


def video(video_id: str, *, hours_ago=None, title=None) -> VideoSummary:
    """Build a VideoSummary posted `hours_ago` hours ago.

    hours_ago=None means yt-dlp gave us no timestamp for this entry.
    """
    timestamp = None
    if hours_ago is not None:
        posted = datetime.now(UTC) - timedelta(hours=hours_ago)
        timestamp = int(posted.timestamp())
    return VideoSummary(
        video_id=video_id,
        url=f"https://tiktok.test/video/{video_id}",
        title=title or f"動画 {video_id}",
        timestamp=timestamp,
    )


def analytics_result(**overrides) -> VideoAnalytics:
    values = {
        "video_id": "v1",
        "url": "https://tiktok.test/video/v1",
        "title": "動画 v1",
        "view_count": 1000,
        "like_count": 10,
        "comment_count": 2,
        "repost_count": 3,
        "save_count": 4,
    }
    values.update(overrides)
    return VideoAnalytics(**values)


def pending_job(video_id="v1", *, username="@acct", posted_hours_ago=None,
                detected_hours_ago=24, due_hours_ago=0, retry_count=0):
    """Build a pending_analytics job.

    posted_hours_ago=None omits posted_at, matching jobs registered before
    post-time anchoring existed.
    """
    now = datetime.now(UTC)
    job = {
        "video_id": video_id,
        "username": username,
        "video_url": f"https://tiktok.test/video/{video_id}",
        "detected_at": (now - timedelta(hours=detected_hours_ago)).isoformat(),
        "analytics_due_at": (now - timedelta(hours=due_hours_ago)).isoformat(),
        "title": f"動画 {video_id}",
        "retry_count": retry_count,
    }
    if posted_hours_ago is not None:
        job["posted_at"] = (
            now - timedelta(hours=posted_hours_ago)
        ).isoformat()
    return job


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "state.json"


@pytest.fixture
def write_state(state_path):
    """Write a state file for the run under test."""

    def _write(*, accounts=None, pending=(), completed=()):
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "accounts": {} if accounts is None else accounts,
                    "pending_analytics": list(pending),
                    "completed_analytics": list(completed),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    return _write


@dataclass
class CycleResult:
    """What one run of the bot did."""

    exit_code: int
    state: dict
    notifier: RecordingNotifier
    commits: list[str]

    def account(self, username="@acct") -> dict:
        return self.state["accounts"][username]

    @property
    def pending(self) -> list[dict]:
        return self.state["pending_analytics"]

    @property
    def completed(self) -> list[dict]:
        return self.state["completed_analytics"]


@pytest.fixture
def run_cycle(monkeypatch, state_path):
    """Run one full run.main() cycle with every external dependency stubbed."""

    def _run(client=None, *, notifier=None, push_error=None, **config_kwargs):
        notifier = notifier if notifier is not None else RecordingNotifier()
        client = client if client is not None else StubClient()
        commits: list[str] = []

        def fake_commit(message):
            if push_error is not None:
                raise push_error
            commits.append(message)

        config = Config(
            accounts=config_kwargs.pop("accounts", ["@acct"]),
            slack_webhook_url="https://slack.test/hook",
            state_file_path=str(state_path),
            **config_kwargs,
        )

        monkeypatch.setattr(run_module, "load_config", lambda: config)
        monkeypatch.setattr(run_module, "TikTokClient", lambda: client)
        monkeypatch.setattr(run_module, "SlackNotifier", lambda url: notifier)
        monkeypatch.setattr(run_module, "commit_and_push", fake_commit)

        exit_code = run_module.main()

        state = {}
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
        return CycleResult(exit_code, state, notifier, commits)

    return _run
