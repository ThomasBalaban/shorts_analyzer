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
    MODEL_PRO,
    THINKING_ANALYSIS,
    get_gemini_client,
    get_safety_settings,
)
from config import get_youtube_api_key


# ─── Response schema ──────────────────────────────────────────────────────────
# Forcing structured JSON output means no more splitting "TITLE EFFECTIVENESS:"
# out of a prose blob and no more stray "****" / "**\n" markdown artifacts
# bleeding into the saved fields. Gemini returns exactly these keys.

_ANALYSIS_SCHEMA = types.Schema(
    type="OBJECT",
    properties={
        "title": types.Schema(
            type="OBJECT",
            properties={
                "text": types.Schema(
                    type="STRING",
                    description="The exact title of the short, copied verbatim.",
                ),
                "why_it_worked": types.Schema(
                    type="STRING",
                    description=(
                        "Detailed analysis of why this specific title was effective. "
                        "Cover the concrete mechanics: curiosity gap, pop-culture "
                        "reference, promise/payoff structure, emotional hook, "
                        "specificity, POV, question vs statement, length, "
                        "word choice. Explain how it pairs with the video's "
                        "content. 4-6 sentences."
                    ),
                ),
            },
            required=["text", "why_it_worked"],
        ),
        "hook": types.Schema(
            type="OBJECT",
            properties={
                "description": types.Schema(
                    type="STRING",
                    description=(
                        "A precise description of the hook portion of the video "
                        "— you decide where the hook ends based on the video's "
                        "structure. Describe exactly what the viewer sees and "
                        "hears: first frame composition, on-screen text, audio, "
                        "tone, what question or tension it plants."
                    ),
                ),
                "why_it_worked": types.Schema(
                    type="STRING",
                    description=(
                        "Why this hook stops the scroll. Discuss pattern "
                        "interrupts, curiosity, visual contrast, audio cues, "
                        "and how it sets up the payoff. 3-5 sentences."
                    ),
                ),
            },
            required=["description", "why_it_worked"],
        ),
        "video_description": types.Schema(
            type="STRING",
            description=(
                "A detailed beat-by-beat walkthrough of the entire short. "
                "Describe every cut and edit, what's on screen, on-screen text "
                "overlays, audio choices (meme audio vs original VO vs music vs "
                "silence), pacing and rhythm, timing of the punchline, visual "
                "effects, and how the edit builds to its payoff. Be specific "
                "and concrete — cite approximate timestamps where helpful. "
                "This should read like an editor's breakdown, not a summary."
            ),
        ),
        "why_the_video_worked": types.Schema(
            type="STRING",
            description=(
                "Why this video earned the views it did. Analyze the content "
                "itself: setup/payoff structure, comedic or emotional timing, "
                "audio-visual synchronization, relatability, rewatchability, "
                "how the edit amplifies the core idea. Distinct from the title "
                "analysis — this is about the content, not the packaging. "
                "4-6 sentences."
            ),
        ),
        "what_could_have_been_better": types.Schema(
            type="STRING",
            description=(
                "Concrete, specific suggestions for what could have made this "
                "short perform even better. Think like an experienced editor "
                "giving notes: pacing changes, tighter cuts, different audio, "
                "a stronger first frame, better on-screen text, a sharper "
                "title variant, etc. Avoid generic advice — every suggestion "
                "should be tied to something specific in THIS video. "
                "3-5 sentences."
            ),
        ),
    },
    required=[
        "title",
        "hook",
        "video_description",
        "why_the_video_worked",
        "what_could_have_been_better",
    ],
)


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
        """Analyze video with Gemini, returning a structured dict.

        Uses Gemini's response schema feature so the model returns strict
        JSON — no prose parsing, no stripping of stray markdown.
        """
        prompt = f"""You are a senior short-form video editor and strategist analyzing a YouTube Short to understand, in concrete detail, why the TITLE and the HOOK worked (or didn't).

Video Title: "{title}"
Views: {views:,}

Watch the video carefully and think like an editor doing a postmortem. Pay close attention to:
  - The exact moment the viewer's scroll is interrupted (the hook)
  - Every cut, edit, and transition
  - On-screen text and overlays
  - Audio choices — meme audio, original voiceover, music, silence, sound design
  - Pacing, rhythm, and the timing of the punchline or payoff
  - Visual effects, framing, and composition
  - How the title pairs with what actually happens in the video

You decide where the "hook" ends based on the video's own structure — it might be the first 1.5 seconds, it might be the full setup before a reveal. Explain it precisely.

Be specific and concrete. Cite timestamps where helpful. Avoid generic observations. Every claim should be tied to something that actually happens in THIS video. The "what could have been better" field should give real editor's notes — specific changes someone could actually make — not vague encouragement.

Respond strictly in the required JSON schema. Do not wrap your response in code fences or markdown."""

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
                model=MODEL_PRO,
                contents=[file_part, prompt],
                config=types.GenerateContentConfig(
                    safety_settings=self.gemini_safety,
                    thinking_config=types.ThinkingConfig(
                        thinking_level=THINKING_ANALYSIS,
                    ),
                    response_mime_type="application/json",
                    response_schema=_ANALYSIS_SCHEMA,
                ),
            )

            return self._parse_structured_response(response, title)

        except Exception as e:
            self._log(f"Error analyzing with Gemini: {e}")
            raise
        finally:
            if video_file is not None:
                try:
                    self.gemini_client.files.delete(name=video_file.name)
                except Exception:
                    pass

    def _parse_structured_response(self, response, fallback_title: str) -> dict:
        """Turn a Gemini structured-JSON response into a clean dict.

        Prefer `response.parsed` when the SDK gives it to us; fall back to
        parsing `response.text` (which is guaranteed JSON because we set
        `response_mime_type='application/json'` + a schema). If Gemini ever
        slips and wraps it in ```json fences we strip those too.
        """
        # Path 1: SDK-parsed object
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, dict) and parsed:
            return self._ensure_title_text(parsed, fallback_title)

        # Path 2: JSON in response.text
        raw = (response.text or "").strip()
        if raw.startswith("```"):
            # Strip ```json ... ``` fences if present
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return self._ensure_title_text(data, fallback_title)
        except json.JSONDecodeError as e:
            self._log(f"  ⚠️  Failed to parse structured JSON: {e}")
            self._log(f"  Raw response (first 500 chars): {raw[:500]}")

        # Path 3: give up gracefully — return a shell that preserves the
        # raw text so the run doesn't die and you can still inspect it.
        return {
            "title": {"text": fallback_title, "why_it_worked": ""},
            "hook": {"description": "", "why_it_worked": ""},
            "video_description": "",
            "why_the_video_worked": "",
            "what_could_have_been_better": "",
            "_parse_error": True,
            "_raw_response": raw,
        }

    @staticmethod
    def _ensure_title_text(data: dict, fallback_title: str) -> dict:
        """Make sure title.text is populated — it's the exact title from YouTube
        and we already know it, so overwrite anything weird Gemini put there."""
        if not isinstance(data.get("title"), dict):
            data["title"] = {"text": fallback_title, "why_it_worked": ""}
        else:
            data["title"]["text"] = fallback_title
        return data

    def load_existing_results(self) -> dict:
        # Treat an empty or corrupt file the same as "no previous results".
        # Can happen if a previous run crashed before writing anything.
        if os.path.exists(self.output_file) and os.path.getsize(self.output_file) > 0:
            try:
                with open(self.output_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                self._log(
                    f"⚠️  Existing results file is not valid JSON "
                    f"({e}). Starting fresh."
                )

        return {
            "metadata": {
                "channel_url": self.channel_url,
                "date_analyzed": datetime.now().strftime("%Y-%m-%d"),
                "total_shorts_analyzed": 0,
                "gemini_model": MODEL_PRO,
                "schema_version": 2,
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