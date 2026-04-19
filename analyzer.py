"""
YouTube Shorts Analyzer (standalone)

Fetches a channel's top shorts, downloads them, runs Gemini analysis, and
saves the result to JSON. Extracted from SimpleAutoSubs as a standalone
tool with its own config and API.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

try:
    from googleapiclient.discovery import build  # type: ignore
    from googleapiclient.errors import HttpError  # type: ignore
    import yt_dlp  # type: ignore
except ImportError as e:
    raise ImportError(
        f"Missing required package: {e}. "
        "Install with: pip install -r requirements.txt"
    )

from google.genai import types  # type: ignore

from models import (
    MODEL_FLASH,
    get_gemini_client,
    get_safety_settings,
)
from config import get_youtube_api_key


class YouTubeShortAnalyzer:
    """Handles fetching, downloading, and analyzing YouTube shorts."""

    def __init__(
        self,
        channel_url: str,
        output_file: str = "shorts_analysis.json",
        max_shorts: int = 100,
        temp_dir: Optional[str] = None,
        log_func: Optional[Callable[[str], None]] = None,
        stop_flag: Optional[Callable[[], bool]] = None,
    ):
        self.channel_url = channel_url
        self.output_file = output_file
        self.max_shorts = max_shorts
        self.log_func = log_func or print
        self.stop_flag = stop_flag or (lambda: False)

        if temp_dir:
            self.temp_dir = Path(temp_dir)
        else:
            self.temp_dir = Path(__file__).parent / "temp_downloads"
        self.temp_dir.mkdir(exist_ok=True, parents=True)

        # YouTube Data API
        self.youtube_api_key = get_youtube_api_key()
        self.youtube = build(
            "youtube", "v3", developerKey=self.youtube_api_key)

        # Gemini client
        self.gemini_client = get_gemini_client()
        self.gemini_safety = get_safety_settings()

        self.channel_handle = self._extract_channel_handle(channel_url)

    def _log(self, msg: str) -> None:
        self.log_func(msg)

    def _check_stop(self) -> None:
        if self.stop_flag():
            raise InterruptedError("Analysis stopped by user")

    def _extract_channel_handle(self, url: str) -> str:
        parts = url.rstrip("/").split("/")
        for part in parts:
            if part.startswith("@"):
                return part
        raise ValueError(
            f"Could not extract channel handle from URL: {url}")

    def fetch_top_shorts(self):
        """Fetch top shorts from the channel sorted by view count."""
        self._log(f"Fetching shorts from channel: {self.channel_handle}")

        try:
            channel_response = self.youtube.channels().list(
                part="id,contentDetails",
                forHandle=self.channel_handle.lstrip("@"),
                maxResults=1,
            ).execute()

            if not channel_response.get("items"):
                raise ValueError(f"Channel not found: {self.channel_handle}")

            channel_id = channel_response["items"][0]["id"]
            self._log(f"Found channel ID: {channel_id}")

            self._log("Fetching all videos from channel...")
            all_videos = []
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

            self._log(f"Total videos found: {len(all_videos)}")

            self._log("Filtering for shorts and getting view counts...")
            shorts = []

            for i in range(0, len(all_videos), 50):
                self._check_stop()
                batch = all_videos[i:i + 50]

                videos_response = self.youtube.videos().list(
                    part="snippet,statistics,contentDetails",
                    id=",".join(batch),
                ).execute()

                for video in videos_response.get("items", []):
                    duration = video["contentDetails"]["duration"]
                    if self._is_short_duration(duration):
                        shorts.append({
                            "video_id": video["id"],
                            "title": video["snippet"]["title"],
                            "views": int(
                                video["statistics"].get("viewCount", 0)),
                            "published_date": (
                                video["snippet"]["publishedAt"].split("T")[0]
                            ),
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

            self._log(f"\nTotal shorts found: {len(shorts)}")

            shorts.sort(key=lambda x: x["views"], reverse=True)
            top_shorts = shorts[:self.max_shorts]

            self._log(f"Selected top {len(top_shorts)} shorts by view count")
            if top_shorts:
                self._log(f"  Highest views: {top_shorts[0]['views']:,}")
                self._log(f"  Lowest views: {top_shorts[-1]['views']:,}")

            return top_shorts

        except HttpError as e:
            self._log(f"YouTube API error: {e}")
            raise

    def _is_short_duration(self, duration_str: str) -> bool:
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

    def download_video(self, video_url: str, video_id: str) -> Path:
        output_path = self.temp_dir / f"{video_id}.mp4"
        ydl_opts = {
            "format": "best[ext=mp4]",
            "outtmpl": str(output_path),
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            return output_path
        except Exception as e:
            self._log(f"Error downloading video {video_id}: {e}")
            raise

    def analyze_with_gemini(self, video_path: Path, title: str, views: int):
        """Analyze video with Gemini via the new SDK."""
        prompt = f"""You are analyzing a YouTube Short to understand why its title was effective.

Video Title: "{title}"
Views: {views:,}

Please provide:
1. A detailed description of what happens in this video (2-3 sentences)
2. An analysis of why this title was effective for this content (3-4 sentences covering specific techniques used)

Format your response as:
VIDEO DESCRIPTION:
[Your description here]

TITLE EFFECTIVENESS:
[Your analysis here]"""

        video_file = None
        try:
            ext = Path(video_path).suffix.lower()
            mime_map = {
                ".mp4": "video/mp4",
                ".mov": "video/quicktime",
                ".mkv": "video/x-matroska",
                ".webm": "video/webm",
                ".avi": "video/x-msvideo",
            }
            mime_type = mime_map.get(ext, "video/mp4")

            video_file = self.gemini_client.files.upload(
                file=str(video_path),
                config={"mime_type": mime_type},
            )

            self._log("  Waiting for video processing...")
            poll_start = time.time()
            while True:
                state = video_file.state.name
                if state == "ACTIVE":
                    break
                if state == "FAILED":
                    raise ValueError("Video processing failed")
                if time.time() - poll_start > 300:
                    raise TimeoutError(
                        f"File did not become ACTIVE within 5 min "
                        f"(last state: {state})"
                    )
                time.sleep(2)
                video_file = self.gemini_client.files.get(
                    name=video_file.name)

            file_part = types.Part.from_uri(
                file_uri=video_file.uri,
                mime_type=video_file.mime_type or mime_type,
            )

            response = self.gemini_client.models.generate_content(
                model=MODEL_FLASH,
                contents=[file_part, prompt],
                config=types.GenerateContentConfig(
                    safety_settings=self.gemini_safety,
                ),
            )

            response_text = response.text
            parts = response_text.split("TITLE EFFECTIVENESS:")

            if len(parts) == 2:
                description = parts[0].replace(
                    "VIDEO DESCRIPTION:", "").strip()
                effectiveness = parts[1].strip()
            else:
                description = response_text[:len(response_text) // 2].strip()
                effectiveness = response_text[len(response_text) // 2:].strip()

            return {
                "video_description": description,
                "title_effectiveness_analysis": effectiveness,
            }

        except Exception as e:
            self._log(f"Error analyzing with Gemini: {e}")
            raise
        finally:
            if video_file is not None:
                try:
                    self.gemini_client.files.delete(name=video_file.name)
                except Exception:
                    pass

    def load_existing_results(self) -> dict:
        if os.path.exists(self.output_file):
            with open(self.output_file, "r", encoding="utf-8") as f:
                return json.load(f)

        return {
            "metadata": {
                "channel_url": self.channel_url,
                "date_analyzed": datetime.now().strftime("%Y-%m-%d"),
                "total_shorts_analyzed": 0,
                "gemini_model": MODEL_FLASH,
            },
            "shorts": [],
        }

    def save_results(self, results: dict) -> None:
        results["metadata"]["total_shorts_analyzed"] = len(results["shorts"])
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    def process_shorts(self) -> dict:
        self._log("=" * 60)
        self._log("YouTube Shorts Analyzer")
        self._log("=" * 60)

        results = self.load_existing_results()
        analyzed_video_ids = {
            short["video_id"] for short in results["shorts"]
        }

        self._log(f"Already analyzed: {len(analyzed_video_ids)} shorts")
        top_shorts = self.fetch_top_shorts()

        for rank, short in enumerate(top_shorts, start=1):
            self._check_stop()
            video_id = short["video_id"]
            if video_id in analyzed_video_ids:
                self._log(
                    f"[{rank}/{len(top_shorts)}] Skipping {video_id} "
                    f"(already analyzed)"
                )
                continue

            self._log(
                f"\n[{rank}/{len(top_shorts)}] Processing: {short['title']}")
            self._log(f"  Views: {short['views']:,}")
            self._log(f"  URL: {short['url']}")

            try:
                self._log("  Downloading...")
                video_path = self.download_video(short["url"], video_id)

                self._log("  Analyzing with Gemini...")
                analysis = self.analyze_with_gemini(
                    video_path, short["title"], short["views"])

                duration_seconds = self._duration_to_seconds(short["duration"])

                result_entry = {
                    "rank": rank,
                    "video_id": video_id,
                    "url": short["url"],
                    "title": short["title"],
                    "views": short["views"],
                    "published_date": short["published_date"],
                    "duration_seconds": duration_seconds,
                    "gemini_analysis": analysis,
                    "analysis_timestamp": datetime.now().isoformat(),
                }

                results["shorts"].append(result_entry)
                self.save_results(results)
                self._log(f"  ✓ Saved to {self.output_file}")

                video_path.unlink()

            except InterruptedError:
                raise
            except Exception as e:
                self._log(f"  ✗ Error processing {video_id}: {e}")
                continue

        self._log("\n" + "=" * 60)
        self._log(f"Analysis complete! Results saved to {self.output_file}")
        self._log(f"Total shorts analyzed: {len(results['shorts'])}")
        self._log("=" * 60)

        return results

    def _duration_to_seconds(self, duration_str: str) -> int:
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

    def cleanup(self) -> None:
        if self.temp_dir.exists():
            for file in self.temp_dir.glob("*"):
                try:
                    file.unlink()
                except Exception:
                    pass