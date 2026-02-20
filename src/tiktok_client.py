"""Wrapper around yt-dlp for TikTok data extraction."""

import logging
from dataclasses import dataclass
from typing import Optional

import yt_dlp

logger = logging.getLogger(__name__)


class TikTokClientError(Exception):
    """Base exception for TikTok client errors."""


class AccountNotFoundError(TikTokClientError):
    """Raised when a TikTok account does not exist or is private."""


class RateLimitError(TikTokClientError):
    """Raised when TikTok rate-limits the request."""


@dataclass
class VideoSummary:
    """Minimal video info from flat-playlist listing."""

    video_id: str
    url: str
    title: str
    timestamp: Optional[int] = None


@dataclass
class VideoAnalytics:
    """Full video analytics from individual video extraction."""

    video_id: str
    url: str
    title: str
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    repost_count: Optional[int] = None
    save_count: Optional[int] = None
    upload_date: Optional[str] = None


def _classify_error(error: yt_dlp.utils.DownloadError) -> TikTokClientError:
    """Classify a yt-dlp DownloadError into a more specific exception."""
    msg = str(error).lower()
    if any(kw in msg for kw in ("not found", "404", "does not exist", "unavailable")):
        return AccountNotFoundError(str(error))
    if any(kw in msg for kw in ("429", "rate limit", "too many requests")):
        return RateLimitError(str(error))
    return TikTokClientError(str(error))


class TikTokClient:
    """yt-dlp based TikTok data client."""

    def __init__(self) -> None:
        self._base_opts: dict = {
            "quiet": True,
            "no_warnings": True,
            "no_color": True,
            "logger": logger,
        }

    def list_recent_videos(self, username: str) -> list[VideoSummary]:
        """List recent videos for a TikTok user using flat-playlist mode.

        Uses extract_flat=True for speed -- does NOT fetch per-video pages.
        Returns approximately the 22 most recent videos visible on the profile.

        Args:
            username: TikTok username with @ prefix, e.g. "@username".

        Returns:
            List of VideoSummary objects, newest first.

        Raises:
            AccountNotFoundError: If the account doesn't exist or is private.
            RateLimitError: If TikTok rate-limits the request.
            TikTokClientError: For other extraction failures.
        """
        opts = {
            **self._base_opts,
            "extract_flat": True,
            "playlist_items": "1-30",
        }
        url = f"https://www.tiktok.com/{username}"

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                result = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise _classify_error(e) from e

        if result is None:
            raise TikTokClientError(f"No data returned for {username}")

        entries = result.get("entries") or []
        videos = []
        for entry in entries:
            if entry is None:
                continue
            video_id = str(entry.get("id", ""))
            if not video_id:
                continue
            videos.append(
                VideoSummary(
                    video_id=video_id,
                    url=entry.get("url", f"https://www.tiktok.com/{username}/video/{video_id}"),
                    title=entry.get("title", ""),
                    timestamp=entry.get("timestamp"),
                )
            )

        logger.info(f"Found {len(videos)} videos for {username}")
        return videos

    def get_video_analytics(self, video_url: str) -> VideoAnalytics:
        """Get full analytics for a single TikTok video.

        Uses full extraction (NOT flat) to get all metadata fields including
        view_count, like_count, comment_count, repost_count, save_count.

        Args:
            video_url: Full TikTok video URL.

        Returns:
            VideoAnalytics object with all available metrics.

        Raises:
            TikTokClientError: If extraction fails (video deleted, private, etc.)
        """
        opts = {
            **self._base_opts,
            "skip_download": True,
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise _classify_error(e) from e

        if info is None:
            raise TikTokClientError(f"No data returned for {video_url}")

        return VideoAnalytics(
            video_id=str(info.get("id", "")),
            url=video_url,
            title=info.get("title", ""),
            view_count=info.get("view_count"),
            like_count=info.get("like_count"),
            comment_count=info.get("comment_count"),
            repost_count=info.get("repost_count"),
            save_count=info.get("save_count"),
            upload_date=info.get("upload_date"),
        )
