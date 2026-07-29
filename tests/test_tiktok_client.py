"""Error classification for yt-dlp failures.

Which exception a failure maps to decides what cause the Slack alert
reports, so the mapping is worth pinning down against real yt-dlp output.
The REAL_* strings below were captured from yt-dlp, not invented.
"""

import pytest
import yt_dlp

from tiktok_client import (
    AccountNotFoundError,
    RateLimitError,
    TikTokClientError,
    _classify_error,
)

REAL_MISSING_ACCOUNT = (
    "ERROR: [tiktok:user] someone: Unable to extract secondary user ID. "
    "If you are able to get the channel_id from a video posted by this "
    'user, try using "tiktokuser:channel_id" as the input URL'
)
REAL_MISSING_VIDEO = (
    "ERROR: [TikTok] 0000000000000000000: Video not available, "
    "status code 100002; please report this issue on ..."
)


def classify(message):
    return _classify_error(yt_dlp.utils.DownloadError(message))


@pytest.mark.parametrize(
    "message",
    [
        "HTTP Error 404: Not Found",
        "This account does not exist",
        "Video unavailable",
    ],
)
def test_missing_account_messages_map_to_account_not_found(message):
    assert isinstance(classify(message), AccountNotFoundError)


@pytest.mark.parametrize(
    "message",
    [
        "HTTP Error 429: Too Many Requests",
        "You have been rate limited",
        "ERROR: too many requests, slow down",
    ],
)
def test_throttling_messages_map_to_rate_limit(message):
    assert isinstance(classify(message), RateLimitError)


def test_unrecognised_messages_stay_generic():
    assert type(classify("something odd happened")) is TikTokClientError


@pytest.mark.parametrize(
    "message",
    [REAL_MISSING_ACCOUNT, REAL_MISSING_VIDEO, "429", "unknown"],
)
def test_every_classification_is_catchable_as_the_base_error(message):
    """monitor catches TikTokClientError; subclasses must not escape it."""
    assert isinstance(classify(message), TikTokClientError)


def test_the_original_message_is_preserved():
    assert "404" in str(classify("HTTP Error 404"))


def test_a_deleted_video_is_retryable_rather_than_fatal():
    """analytics retries TikTokClientError, which is right for a lost video."""
    assert type(classify(REAL_MISSING_VIDEO)) is TikTokClientError


@pytest.mark.xfail(
    strict=True,
    reason="issue #15: yt-dlp reports a missing account as 'Unable to extract "
    "secondary user ID', which matches none of the keywords, so a deleted "
    "account is diagnosed as a rate limit or a broken extractor",
)
def test_real_missing_account_message_is_recognised():
    assert isinstance(classify(REAL_MISSING_ACCOUNT), AccountNotFoundError)
