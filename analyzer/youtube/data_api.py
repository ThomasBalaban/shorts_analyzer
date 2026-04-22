"""
YouTube Data API v3 wrapper.

Responsible for:
  - Resolving a channel handle (@...) to a channel ID
  - Listing every video on the channel
  - Fetching statistics/contentDetails for those videos
  - Filtering down to Shorts (≤60s, already published) and returning
    them sorted by views

This module is pure fetching. It does not download videos and it does not
call Gemini — those live in `downloader.py` and `analyzer.gemini` respectively.
"""

from datetime import datetime
from typing import Callable, List, Optional

from googleapiclient.discovery import build  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore

from analyzer.core.config import get_youtube_api_key


def extract_channel_handle(url: str) -> str:
    """Pull the @handle out of a channel URL."""
    parts = url.rstrip("/").split("/")
    for part in parts:
        if part.startswith("@"):
            return part
    raise ValueError(f"Could not extract channel handle from URL: {url}")


def _is_short_duration(duration_str: str) -> bool:
    """Return True if an ISO-8601 PT duration string is ≤60s."""
    duration = duration_str.replace("PT", "")
    if "H" in duration:
        return False

    minutes = 0
    seconds = 0
    if "M" in duration:
        parts = duration.split("M")
        minutes = int(parts[0])
        if len(parts) > 1 and "S" in parts[1]:
            seconds = int(parts[1].replace("S", ""))
    elif "S" in duration:
        seconds = int(duration.replace("S", ""))

    return (minutes * 60 + seconds) <= 60


def duration_to_seconds(duration_str: str) -> int:
    """Convert an ISO-8601 PT duration into total seconds."""
    duration = duration_str.replace("PT", "")
    minutes = 0
    seconds = 0
    if "M" in duration:
        parts = duration.split("M")
        minutes = int(parts[0])
        if len(parts) > 1 and "S" in parts[1]:
            seconds = int(parts[1].replace("S", ""))
    elif "S" in duration:
        seconds = int(duration.replace("S", ""))
    return minutes * 60 + seconds


class YouTubeDataClient:
    """Thin wrapper around the YouTube Data API v3."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        log_func: Optional[Callable[[str], None]] = None,
        stop_flag: Optional[Callable[[], bool]] = None,
    ):
        self.api_key = api_key or get_youtube_api_key()
        self.log_func = log_func or print
        self.stop_flag = stop_flag or (lambda: False)
        self.youtube = build("youtube", "v3", developerKey=self.api_key)

    def _log(self, msg: str) -> None:
        self.log_func(msg)

    def _check_stop(self) -> None:
        if self.stop_flag():
            raise InterruptedError("Analysis stopped by user")

    def resolve_channel_id(self, handle: str) -> str:
        """Turn '@handle' (or 'handle') into a channel ID."""
        response = self.youtube.channels().list(
            part="id,contentDetails",
            forHandle=handle.lstrip("@"),
            maxResults=1,
        ).execute()

        if not response.get("items"):
            raise ValueError(f"Channel not found: {handle}")

        return response["items"][0]["id"]

    def list_all_video_ids(self, channel_id: str) -> List[str]:
        """Paginate through every video on a channel (newest first)."""
        all_videos: List[str] = []
        next_page_token = None
        page_count = 0

        while True:
            self._check_stop()
            page_count += 1
            search_response = self.youtube.search().list(
                part="id",
                channelId=channel_id,
                type="video",
                maxResults=50,
                pageToken=next_page_token,
                order="date",
            ).execute()

            video_ids = [
                item["id"]["videoId"]
                for item in search_response.get("items", [])
            ]
            if not video_ids:
                break

            all_videos.extend(video_ids)
            self._log(
                f"  Page {page_count}: Found {len(video_ids)} videos "
                f"(total: {len(all_videos)})"
            )

            next_page_token = search_response.get("nextPageToken")
            if not next_page_token:
                break

        return all_videos

    def fetch_shorts(
        self,
        channel_url: str,
        max_shorts: int = 100,
    ) -> List[dict]:
        """High-level helper: channel URL → list of top shorts sorted by views.

        Only returns videos that are already live (published_date <= today).
        Scheduled or upcoming videos are excluded entirely.

        Returns a list of dicts:
            {video_id, title, views, published_date, duration, url}
        """
        handle = extract_channel_handle(channel_url)
        self._log(f"Fetching shorts from channel: {handle}")

        # Used to filter out scheduled/upcoming videos
        today = datetime.now().strftime("%Y-%m-%d")

        try:
            channel_id = self.resolve_channel_id(handle)
            self._log(f"Found channel ID: {channel_id}")

            self._log("Fetching all videos from channel...")
            all_videos = self.list_all_video_ids(channel_id)
            self._log(f"Total videos found: {len(all_videos)}")

            self._log("Filtering for shorts and getting view counts...")
            shorts: List[dict] = []
            skipped_future = 0

            for i in range(0, len(all_videos), 50):
                self._check_stop()
                batch = all_videos[i:i + 50]

                videos_response = self.youtube.videos().list(
                    part="snippet,statistics,contentDetails",
                    id=",".join(batch),
                ).execute()

                for video in videos_response.get("items", []):
                    published_date = (
                        video["snippet"]["publishedAt"].split("T")[0]
                    )

                    # Skip videos that haven't gone live yet — they have no
                    # real view counts and Analytics will reject date queries
                    # for them with a 412.
                    if published_date > today:
                        skipped_future += 1
                        continue

                    duration = video["contentDetails"]["duration"]
                    if _is_short_duration(duration):
                        shorts.append({
                            "video_id": video["id"],
                            "title": video["snippet"]["title"],
                            "views": int(
                                video["statistics"].get("viewCount", 0)),
                            "published_date": published_date,
                            "duration": duration,
                            "url": (
                                f"https://www.youtube.com/shorts/"
                                f"{video['id']}"
                            ),
                        })

                self._log(
                    f"  Processed {min(i+50, len(all_videos))}/"
                    f"{len(all_videos)} videos, "
                    f"found {len(shorts)} shorts so far"
                )

            if skipped_future:
                self._log(
                    f"Skipped {skipped_future} scheduled/upcoming video(s) "
                    f"(publish date is in the future)"
                )

            self._log(f"\nTotal shorts found: {len(shorts)}")

            shorts.sort(key=lambda x: x["views"], reverse=True)
            top_shorts = shorts[:max_shorts]

            self._log(f"Selected top {len(top_shorts)} shorts by view count")
            if top_shorts:
                self._log(f"  Highest views: {top_shorts[0]['views']:,}")
                self._log(f"  Lowest views: {top_shorts[-1]['views']:,}")

            return top_shorts

        except HttpError as e:
            self._log(f"YouTube API error: {e}")
            raise