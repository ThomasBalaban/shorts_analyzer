"""
Gemini video-analysis client.

Handles the mechanics of:
  - Uploading a video file to the Gemini File API
  - Polling until the file is ACTIVE
  - Calling generate_content with our schema + prompt
  - Parsing the structured response back into a dict
  - Cleaning up the uploaded file after

Separated from the orchestrator so the I/O dance (upload / poll / delete)
doesn't pollute the main analyzer flow.
"""

import json
import time
from pathlib import Path
from typing import Callable, Optional

from google.genai import types  # type: ignore

from analyzer.core.models import (
    MODEL_PRO,
    THINKING_ANALYSIS,
    get_gemini_client,
    get_safety_settings,
)
from analyzer.gemini.prompts import build_analysis_prompt
from analyzer.gemini.schema import ANALYSIS_SCHEMA


_MIME_MAP = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
}


class GeminiVideoAnalyzer:
    def __init__(
        self,
        log_func: Optional[Callable[[str], None]] = None,
    ):
        self.client = get_gemini_client()
        self.safety = get_safety_settings()
        self.log_func = log_func or print

    def _log(self, msg: str) -> None:
        self.log_func(msg)

    def analyze(
        self,
        video_path: Path,
        title: str,
        views: int,
        analytics: Optional[dict] = None,
    ) -> dict:
        """Analyze a single video, return structured dict matching ANALYSIS_SCHEMA.

        analytics: optional enrichment dict from ChannelBaseline —
            {avg_view_percentage, estimated_minutes_watched, retention_curve,
             breakout_score}. When provided, the prompt embeds the retention
            curve so Gemini must reconcile its prose with actual viewer
            behavior.
        """
        prompt = build_analysis_prompt(title, views, analytics)

        video_file = None
        try:
            ext = Path(video_path).suffix.lower()
            mime_type = _MIME_MAP.get(ext, "video/mp4")

            video_file = self.client.files.upload(
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
                video_file = self.client.files.get(name=video_file.name)

            file_part = types.Part.from_uri(
                file_uri=video_file.uri,
                mime_type=video_file.mime_type or mime_type,
            )

            response = self.client.models.generate_content(
                model=MODEL_PRO,
                contents=[file_part, prompt],
                config=types.GenerateContentConfig(
                    safety_settings=self.safety,
                    thinking_config=types.ThinkingConfig(
                        thinking_level=THINKING_ANALYSIS,
                    ),
                    response_mime_type="application/json",
                    response_schema=ANALYSIS_SCHEMA,
                ),
            )

            return self._parse_response(response, title)

        except Exception as e:
            self._log(f"Error analyzing with Gemini: {e}")
            raise
        finally:
            if video_file is not None:
                try:
                    self.client.files.delete(name=video_file.name)
                except Exception:
                    pass

    def _parse_response(self, response, fallback_title: str) -> dict:
        """Turn a Gemini structured-JSON response into a clean dict.

        Prefer `response.parsed` when the SDK gives it to us; fall back to
        parsing `response.text` (guaranteed JSON because we set
        `response_mime_type='application/json'` + a schema). Strip stray
        code fences if Gemini ever slips and adds them.
        """
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, dict) and parsed:
            return self._ensure_title_text(parsed, fallback_title)

        raw = (response.text or "").strip()
        if raw.startswith("```"):
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

        # Graceful shell so a single parse failure doesn't kill the run
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
        """Force title.text to be the real YouTube title — we already know it
        exactly, so don't let Gemini paraphrase it."""
        if not isinstance(data.get("title"), dict):
            data["title"] = {"text": fallback_title, "why_it_worked": ""}
        else:
            data["title"]["text"] = fallback_title
        return data
