"""
YouTube Shorts Analyzer — orchestrator.

Composes three pieces:
  - analyzer.youtube.data_api  (which shorts, sorted by views)
  - analyzer.youtube.downloader (mp4 on disk)
  - analyzer.gemini.client      (structured analysis)

Handles the outer loop: fetch → download → analyze → save → repeat,
with resumability (skip video_ids already in the output JSON).
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from analyzer.baseline import ChannelBaseline
from analyzer.core.config import (
    analytics_available,
    get_analytics_client_secrets,
    get_analytics_token_path,
)
from analyzer.core.models import MODEL_PRO
from analyzer.gemini.client import GeminiVideoAnalyzer
from analyzer.youtube.data_api import YouTubeDataClient, duration_to_seconds
from analyzer.youtube.downloader import ShortDownloader


# Bump when the Gemini schema changes shape in a way that makes old
# records incompatible with new consumers. On mismatch, existing output
# files are ignored and everything re-analyzes.
SCHEMA_VERSION = 3


class YouTubeShortAnalyzer:
    """Orchestrator: fetch top shorts, download each, analyze with Gemini, save."""

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

        project_root = Path(__file__).resolve().parents[2]
        temp_path = Path(temp_dir) if temp_dir else project_root / "temp_downloads"

        self.data_client = YouTubeDataClient(
            log_func=self._log, stop_flag=stop_flag)
        self.downloader = ShortDownloader(
            temp_dir=temp_path, log_func=self._log)
        self.gemini = GeminiVideoAnalyzer(log_func=self._log)

        self.baseline = ChannelBaseline(
            context_dir=project_root / "data" / "channel_context",
            cache_dir=project_root / "data" / "analytics_cache",
            log_func=self._log,
        )

        self.analytics = None
        if analytics_available():
            from analyzer.youtube.analytics import YouTubeAnalyticsClient
            self.analytics = YouTubeAnalyticsClient(
                client_secrets_path=get_analytics_client_secrets(),
                token_path=get_analytics_token_path(),
                log_func=self._log,
            )

    def _log(self, msg: str) -> None:
        self.log_func(msg)

    def _check_stop(self) -> None:
        if self.stop_flag():
            raise InterruptedError("Analysis stopped by user")

    # ─── Persistence ─────────────────────────────────────────────────────────

    def load_existing_results(self) -> dict:
        """Resume from an existing JSON file, or start fresh if empty/corrupt
        or if the schema version is older than the current one (old records
        are missing required fields, so rebuilding is the right move)."""
        if (os.path.exists(self.output_file)
                and os.path.getsize(self.output_file) > 0):
            try:
                with open(self.output_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                file_version = loaded.get("metadata", {}).get("schema_version")
                if file_version == SCHEMA_VERSION:
                    return loaded
                self._log(
                    f"⚠️  Existing results use schema v{file_version}; "
                    f"current is v{SCHEMA_VERSION}. Starting fresh — "
                    f"old records will be re-analyzed."
                )
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
                "schema_version": SCHEMA_VERSION,
            },
            "shorts": [],
        }

    def save_results(self, results: dict) -> None:
        results["metadata"]["total_shorts_analyzed"] = len(results["shorts"])
        # Make sure the output directory exists
        os.makedirs(os.path.dirname(os.path.abspath(self.output_file)) or ".",
                    exist_ok=True)
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    # ─── Main loop ───────────────────────────────────────────────────────────

    def process_shorts(self) -> dict:
        self._log("=" * 60)
        self._log("YouTube Shorts Analyzer")
        self._log("=" * 60)

        results = self.load_existing_results()
        analyzed_video_ids = {
            short["video_id"] for short in results["shorts"]
        }

        self._log(f"Already analyzed: {len(analyzed_video_ids)} shorts")
        top_shorts = self.data_client.fetch_shorts(
            self.channel_url, max_shorts=self.max_shorts)

        # ── Phase 1: build channel context + analytics enrichment ────────────
        channel_context = self.baseline.load()
        if self.analytics is not None:
            self._log("\nBuilding channel context with Analytics data...")
            channel_context = self.baseline.build(
                top_shorts, analytics_client=self.analytics)
        elif channel_context is None:
            # No OAuth — still build medians from Data API view counts alone
            self._log(
                "\nAnalytics not configured (no client_secrets.json). "
                "Building baseline from Data API view counts only."
            )
            channel_context = self.baseline.build(top_shorts)

        # Re-sort: primary = breakout_score desc, secondary = views desc
        def _sort_key(s: dict):
            score = self.baseline.get_breakout_score(s["video_id"])
            return (score or 0.0, s["views"])

        top_shorts.sort(key=_sort_key, reverse=True)
        self._log(
            f"Sorted {len(top_shorts)} shorts by breakout score "
            "(views ÷ channel median at publish month)"
        )

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
                video_path = self.downloader.download(
                    short["url"], video_id)

                enrichment = self.baseline.get_video_enrichment(video_id)

                self._log("  Analyzing with Gemini...")
                analysis = self.gemini.analyze(
                    video_path,
                    short["title"],
                    short["views"],
                    analytics=enrichment,
                )
                result_entry = {
                    "rank": rank,
                    "video_id": video_id,
                    "url": short["url"],
                    "title": short["title"],
                    "views": short["views"],
                    "published_date": short["published_date"],
                    "duration_seconds": duration_to_seconds(
                        short["duration"]),
                    "breakout_score": (
                        enrichment.get("breakout_score") if enrichment
                        else self.baseline.get_breakout_score(video_id)
                    ),
                    "analytics": enrichment,
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

    def cleanup(self) -> None:
        self.downloader.cleanup()
