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
from analyzer.core.meta import (
    backfill_analysis_meta,
    build_meta,
    prompt_source_hash,
)
from analyzer.core.models import MODEL_PRO
from analyzer.gemini.client import GeminiVideoAnalyzer
from analyzer.gemini.prompts import build_analysis_prompt
from analyzer.tags import format_vocabulary
from analyzer.youtube.data_api import YouTubeDataClient, duration_to_seconds
from analyzer.youtube.downloader import ShortDownloader


# Bump when the Gemini schema changes shape in a way that makes old
# records incompatible with new consumers. This is stamped into each
# record's `gemini_analysis._meta.schema_version` so reruns can be
# scoped to just the stale records — we no longer nuke the whole file
# on mismatch; the operator decides when to rerun.
SCHEMA_VERSION = 3


def current_analysis_prompt_hash() -> str:
    """Hash of the Phase 2 prompt + tag vocabulary. Stamped on new records
    and used by `/rerun/analysis?filter=prompt_mismatch` to find records
    produced under an older prompt."""
    return prompt_source_hash(build_analysis_prompt, format_vocabulary())


def build_analysis_meta(ran_at: Optional[str] = None) -> dict:
    return build_meta(
        model=MODEL_PRO,
        schema_version=SCHEMA_VERSION,
        prompt_hash=current_analysis_prompt_hash(),
        ran_at=ran_at,
    )


class YouTubeShortAnalyzer:
    """Orchestrator: fetch top shorts, download each, analyze with Gemini, save."""

    def __init__(
        self,
        channel_url: str,
        output_file: str = "shorts_analysis.json",
        max_shorts: int = 100,
        recent_n: int = 30,
        temp_dir: Optional[str] = None,
        log_func: Optional[Callable[[str], None]] = None,
        stop_flag: Optional[Callable[[], bool]] = None,
    ):
        self.channel_url = channel_url
        self.output_file = output_file
        # max_shorts is split evenly between the top-by-views and
        # bottom-by-views cohorts. Recent is its own cohort.
        self.top_n = max_shorts // 2
        self.bottom_n = max_shorts - self.top_n
        self.recent_n = recent_n
        self.log_func = log_func or print
        self.stop_flag = stop_flag or (lambda: False)

        project_root = Path(__file__).resolve().parents[2]
        temp_path = Path(temp_dir) if temp_dir else project_root / "temp_downloads"

        self.data_client = YouTubeDataClient(
            log_func=self._log, stop_flag=stop_flag)
        self.downloader = ShortDownloader(
            temp_dir=temp_path, log_func=self._log)
        self.gemini = GeminiVideoAnalyzer(log_func=self._log)

        # Context file sits next to the analysis file in output/ so every
        # downstream-consumable product lives in one directory.
        # analytics_cache/ stays under data/ — it's 99+ internal cache
        # files, not something meant to be browsed.
        output_path = Path(self.output_file)
        context_file = output_path.with_name(
            output_path.stem + ".context.json")
        # Videos that fall out of all current cohorts are parked here so
        # nothing is lost — if they re-enter a cohort on a later run we
        # promote them back into the main file.
        self.historical_file = str(output_path.with_name(
            output_path.stem + ".historical.json"))

        self.baseline = ChannelBaseline(
            context_file=context_file,
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
        """Resume from an existing JSON file, or start fresh if empty/corrupt.

        Schema mismatches are NOT auto-handled: we log a warning and leave
        the old records alone. The operator decides when to rerun via
        `/rerun/analysis?filter=schema_mismatch` — we never silently
        destroy work.

        Any record missing a `gemini_analysis._meta` block gets one
        backfilled from `analysis_timestamp` so downstream predicates
        have something to compare against. Backfilled records are
        marked `model=null, prompt_hash=null` so they're distinguishable
        from freshly-stamped ones.
        """
        if (os.path.exists(self.output_file)
                and os.path.getsize(self.output_file) > 0):
            try:
                with open(self.output_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                file_version = loaded.get("metadata", {}).get("schema_version")
                if file_version != SCHEMA_VERSION:
                    self._log(
                        f"ℹ️  Existing results use schema v{file_version}; "
                        f"current is v{SCHEMA_VERSION}. Keeping records "
                        "as-is — use /rerun/analysis?filter=schema_mismatch "
                        "to refresh them."
                    )
                self._backfill_analysis_meta(loaded)
                return loaded
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

    def _backfill_analysis_meta(self, results: dict) -> None:
        """Stamp a best-guess `_meta` block onto records that lack one.

        Delegates to the shared helper so `list_videos` and the rerun
        pipeline see the same shape.
        """
        schema = (
            results.get("metadata", {}).get("schema_version")
            or SCHEMA_VERSION
        )
        if backfill_analysis_meta(results, schema):
            self._log(
                "Backfilled gemini_analysis._meta on legacy record(s); "
                "saving."
            )
            self.save_results(results)

    def save_results(self, results: dict) -> None:
        results["metadata"]["total_shorts_analyzed"] = len(results["shorts"])
        # Make sure the output directory exists
        os.makedirs(os.path.dirname(os.path.abspath(self.output_file)) or ".",
                    exist_ok=True)
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    # ─── Cohorts + historical ────────────────────────────────────────────────

    def _build_cohorts(self, all_shorts: list) -> dict:
        """Compute the three cohorts and which one(s) each video belongs to.

        Returns:
            {
              "selected": [short, ...],          # dedup'd union
              "memberships": {video_id: [labels]},
              "stats": {top_n_actual, bottom_n_actual, recent_n_actual},
            }

        Top and bottom are de-overlapped: a video in top_50 is never also
        in bottom_50. Recent can overlap with either.
        """
        by_views_desc = sorted(
            all_shorts, key=lambda s: s["views"], reverse=True)

        top = by_views_desc[:self.top_n]
        top_ids = {s["video_id"] for s in top}

        # Bottom = lowest-view shorts excluding anything already in top.
        bottom_pool = [s for s in by_views_desc if s["video_id"] not in top_ids]
        bottom = (sorted(bottom_pool, key=lambda s: s["views"])
                  [:self.bottom_n])

        def _recency_key(s: dict) -> str:
            # Fall back to published_date if published_at is missing on
            # records fetched by an older client (shouldn't happen for new
            # fetches, but harmless).
            return s.get("published_at") or s.get("published_date") or ""

        by_recent = sorted(all_shorts, key=_recency_key, reverse=True)
        recent = by_recent[:self.recent_n]

        memberships: dict[str, list[str]] = {}
        for s in top:
            memberships.setdefault(s["video_id"], []).append("top_50")
        for s in bottom:
            memberships.setdefault(s["video_id"], []).append("bottom_50")
        for s in recent:
            memberships.setdefault(s["video_id"], []).append("recent_30")

        seen: set[str] = set()
        selected: list[dict] = []
        for source in (top, bottom, recent):
            for s in source:
                if s["video_id"] in seen:
                    continue
                seen.add(s["video_id"])
                selected.append(s)

        return {
            "selected": selected,
            "memberships": memberships,
            "stats": {
                "top_n_actual": len(top),
                "bottom_n_actual": len(bottom),
                "recent_n_actual": len(recent),
            },
        }

    def _load_historical(self) -> dict:
        if (os.path.exists(self.historical_file)
                and os.path.getsize(self.historical_file) > 0):
            try:
                with open(self.historical_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                self._log(
                    f"⚠️  Historical file at {self.historical_file} is "
                    "not valid JSON — starting a fresh historical record."
                )
        return {
            "metadata": {
                "channel_url": self.channel_url,
                "schema_version": SCHEMA_VERSION,
                "note": (
                    "Records of shorts that were once in a cohort but no "
                    "longer are. Promoted back into the main file if they "
                    "re-enter on a later run."
                ),
            },
            "shorts": [],
        }

    def _save_historical(self, historical: dict) -> None:
        os.makedirs(
            os.path.dirname(os.path.abspath(self.historical_file)) or ".",
            exist_ok=True,
        )
        with open(self.historical_file, "w", encoding="utf-8") as f:
            json.dump(historical, f, indent=2, ensure_ascii=False)

    def _reconcile_with_cohorts(
        self, results: dict, current_ids: set[str]
    ) -> None:
        """Move ejected records out, promote returning records back in.

        Runs once per `process_shorts` call, before the main loop. After
        this returns, `results['shorts']` only contains records whose
        video_id is in `current_ids` (the union of all current cohorts).
        """
        historical = self._load_historical()

        # Pull anything from historical that's back in a cohort.
        promoted: list[dict] = []
        kept_historical: list[dict] = []
        for entry in historical.get("shorts", []):
            if entry.get("video_id") in current_ids:
                promoted.append(entry)
            else:
                kept_historical.append(entry)

        # Move anything from main results that's no longer in a cohort.
        kept_main: list[dict] = []
        ejected: list[dict] = []
        for entry in results["shorts"]:
            if entry.get("video_id") in current_ids:
                kept_main.append(entry)
            else:
                ejected.append(entry)

        # Dedupe historical by video_id (newer ejection wins).
        by_id = {e["video_id"]: e for e in kept_historical}
        for e in ejected:
            by_id[e["video_id"]] = e
        kept_historical = list(by_id.values())

        results["shorts"] = kept_main + promoted

        if promoted:
            self._log(
                f"Promoted {len(promoted)} record(s) back from historical "
                "(re-entered a cohort)."
            )
        if ejected:
            self._log(
                f"Ejected {len(ejected)} record(s) to historical "
                "(no longer in any cohort)."
            )

        if promoted or ejected:
            self.save_results(results)
            historical["shorts"] = kept_historical
            historical["metadata"]["last_updated"] = (
                datetime.now().isoformat())
            self._save_historical(historical)

    def _refresh_existing_enrichment(self, results: dict) -> None:
        """Re-stamp breakout_score and analytics on already-analyzed records.

        Gemini analysis is expensive and should never re-run on resume, but
        the cheap enrichment fields go stale whenever the baseline is
        rebuilt (e.g. new shorts published, or a corrected baseline scope).
        Without this, a resumed record keeps whatever breakout_score was
        computed at its original analysis time — which is often wrong.
        """
        refreshed = 0
        for entry in results["shorts"]:
            vid = entry.get("video_id")
            if not vid:
                continue
            enrichment = self.baseline.get_video_enrichment(vid)
            if enrichment is None:
                continue
            new_bs = enrichment.get("breakout_score")
            if new_bs != entry.get("breakout_score"):
                refreshed += 1
            entry["breakout_score"] = new_bs
            entry["analytics"] = enrichment
        if refreshed:
            self._log(
                f"Refreshed breakout_score on {refreshed} existing record(s) "
                "against rebuilt baseline"
            )
            self.save_results(results)

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

        # Baseline needs the full channel population for medians to be
        # meaningful — if we passed only the top-N slice, the "median"
        # would be the median of the top-N, and a 100x-breakout short
        # would score 1.0 against itself. Fetch all, build baseline from
        # all, then slice to top-N for analysis.
        all_shorts = self.data_client.fetch_shorts(
            self.channel_url, max_shorts=None)

        # ── Phase 1: build channel context + analytics enrichment ────────────
        channel_context = self.baseline.load()
        if self.analytics is not None:
            self._log("\nBuilding channel context with Analytics data...")
            channel_context = self.baseline.build(
                all_shorts, analytics_client=self.analytics)
        elif channel_context is None:
            # No OAuth — still build medians from Data API view counts alone
            self._log(
                "\nAnalytics not configured (no client_secrets.json). "
                "Building baseline from Data API view counts only."
            )
            channel_context = self.baseline.build(all_shorts)

        # ── Cohort selection ─────────────────────────────────────────────────
        cohorts = self._build_cohorts(all_shorts)
        selected = cohorts["selected"]
        memberships = cohorts["memberships"]
        stats = cohorts["stats"]
        current_ids = {s["video_id"] for s in selected}

        self._log(
            f"\nCohorts (from {len(all_shorts)} shorts): "
            f"top_50={stats['top_n_actual']}, "
            f"bottom_50={stats['bottom_n_actual']}, "
            f"recent_30={stats['recent_n_actual']} "
            f"→ {len(selected)} unique to analyze"
        )

        # Move records that fell out of every cohort to historical, and
        # pull back any historical records that re-entered.
        self._reconcile_with_cohorts(results, current_ids)
        analyzed_video_ids = {s["video_id"] for s in results["shorts"]}

        # Tag every record (both freshly-analyzed and previously-analyzed)
        # with its current cohort membership so downstream consumers can
        # filter by cohort without recomputing. Also backfill
        # `published_at` from the fresh fetch onto records originally
        # written before that field existed.
        fresh_by_id = {s["video_id"]: s for s in selected}
        for entry in results["shorts"]:
            vid = entry["video_id"]
            entry["cohorts"] = memberships.get(vid, [])
            if not entry.get("published_at") and vid in fresh_by_id:
                fresh_pub = fresh_by_id[vid].get("published_at")
                if fresh_pub:
                    entry["published_at"] = fresh_pub

        # Resumed records were saved against a possibly-stale baseline —
        # their breakout_score and analytics blob need refreshing before
        # we skip them in the main loop.
        self._refresh_existing_enrichment(results)
        self.save_results(results)

        for rank, short in enumerate(selected, start=1):
            self._check_stop()
            video_id = short["video_id"]
            if video_id in analyzed_video_ids:
                self._log(
                    f"[{rank}/{len(selected)}] Skipping {video_id} "
                    f"(already analyzed)"
                )
                continue

            self._log(
                f"\n[{rank}/{len(selected)}] Processing: {short['title']}")
            self._log(f"  Views: {short['views']:,}")
            self._log(f"  Cohorts: {', '.join(memberships[video_id])}")
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
                ran_at = datetime.now().isoformat()
                analysis["_meta"] = build_analysis_meta(ran_at=ran_at)
                result_entry = {
                    "rank": rank,
                    "video_id": video_id,
                    "url": short["url"],
                    "title": short["title"],
                    "views": short["views"],
                    "published_date": short["published_date"],
                    "published_at": short.get("published_at"),
                    "duration_seconds": duration_to_seconds(
                        short["duration"]),
                    "breakout_score": (
                        enrichment.get("breakout_score") if enrichment
                        else self.baseline.get_breakout_score(video_id)
                    ),
                    "analytics": enrichment,
                    "cohorts": memberships.get(video_id, []),
                    "gemini_analysis": analysis,
                    "analysis_timestamp": ran_at,
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
