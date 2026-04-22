"""
Channel baseline + context.

Builds channel_context.json: per-month view medians so any video can be
scored against the channel's performance at the time it was published, not
against today's much larger baseline.

Breakout score = views / channel_median_for_publish_month

Monthly medians are computed from the view counts returned by the Data API
(current totals). This is an approximation: older videos have had more time
to accumulate views. Phase 2 will refine this using time-windowed Analytics
data once we have more history.

Months with fewer than MIN_VIDEOS_FOR_MEDIAN videos fall back to the
overall median so one outlier month doesn't skew the score.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from analyzer.youtube.analytics import YouTubeAnalyticsClient


MIN_VIDEOS_FOR_MEDIAN = 3
CACHE_TTL_DAYS = 7  # re-fetch Analytics data older than this


class ChannelBaseline:
    def __init__(
        self,
        context_dir: Path,
        cache_dir: Path,
        log_func: Optional[Callable[[str], None]] = None,
    ):
        self.context_file = Path(context_dir) / "channel_context.json"
        self.cache_dir = Path(cache_dir)
        self.log_func = log_func or print
        self._context: Optional[dict] = None

    def _log(self, msg: str) -> None:
        self.log_func(msg)

    # ─── Cache I/O ────────────────────────────────────────────────────────────

    def _cache_path(self, video_id: str) -> Path:
        return self.cache_dir / f"{video_id}.json"

    def _load_cached(self, video_id: str) -> Optional[dict]:
        path = self._cache_path(video_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        fetched_at = datetime.fromisoformat(data.get("fetched_at", "2000-01-01"))
        if (datetime.now() - fetched_at).days > CACHE_TTL_DAYS:
            return None
        return data

    def _save_cached(self, video_id: str, data: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(video_id).write_text(json.dumps(data, indent=2))

    # ─── Context file ─────────────────────────────────────────────────────────

    def load(self) -> Optional[dict]:
        """Load an existing channel_context.json, or return None if absent."""
        if not self.context_file.exists():
            return None
        self._context = json.loads(self.context_file.read_text())
        return self._context

    def _save_context(self, context: dict) -> None:
        self.context_file.parent.mkdir(parents=True, exist_ok=True)
        self.context_file.write_text(json.dumps(context, indent=2))

    # ─── Building ─────────────────────────────────────────────────────────────

    def build(
        self,
        shorts: list[dict],
        analytics_client: Optional["YouTubeAnalyticsClient"] = None,
    ) -> dict:
        """
        Build (or refresh) channel_context.json from a list of shorts dicts:
            [{video_id, views, published_date, ...}, ...]

        If analytics_client is provided, enriches each video with retention
        curves and basic engagement stats (with caching).

        Returns the full context dict and saves it to disk.
        """
        self._log(f"Building channel context for {len(shorts)} shorts...")

        # ── Monthly medians (from Data API view counts) ─────────────────────
        by_month: dict[str, list[int]] = {}
        for s in shorts:
            month = s["published_date"][:7]  # YYYY-MM
            by_month.setdefault(month, []).append(s["views"])

        monthly_medians: dict[str, float] = {}
        for month, views_list in by_month.items():
            if len(views_list) >= MIN_VIDEOS_FOR_MEDIAN:
                monthly_medians[month] = statistics.median(views_list)

        all_views = [s["views"] for s in shorts]
        overall_median = statistics.median(all_views) if all_views else 0

        # ── Per-video analytics enrichment ──────────────────────────────────
        videos: dict[str, dict] = {}
        for i, s in enumerate(shorts, 1):
            vid = s["video_id"]
            month = s["published_date"][:7]
            median = monthly_medians.get(month, overall_median)
            breakout_score = (
                round(s["views"] / median, 2) if median else None)

            entry: dict = {
                "views": s["views"],
                "published_date": s["published_date"],
                "breakout_score": breakout_score,
            }

            if analytics_client is not None:
                cached = self._load_cached(vid)
                if cached:
                    analytics = cached
                else:
                    self._log(
                        f"  [{i}/{len(shorts)}] Fetching analytics: {vid}")
                    try:
                        analytics = analytics_client.get_video_analytics(
                            vid, s["published_date"])
                        # Only cache if at least one metric came back
                        if any(analytics.get(k) is not None for k in (
                                "views", "retention_curve",
                                "avg_view_percentage")):
                            self._save_cached(vid, analytics)
                    except Exception as e:
                        self._log(
                            f"  Analytics fetch failed for {vid}: {e}")
                        analytics = {"video_id": vid, "error": str(e)}

                entry["avg_view_percentage"] = analytics.get(
                    "avg_view_percentage")
                entry["estimated_minutes_watched"] = analytics.get(
                    "estimated_minutes_watched")
                entry["retention_curve"] = analytics.get("retention_curve")
                entry["analytics_fetched_at"] = analytics.get("fetched_at")

            videos[vid] = entry

        context = {
            "built_at": datetime.now().isoformat(),
            "overall_median": overall_median,
            "monthly_medians": monthly_medians,
            "videos": videos,
        }
        self._save_context(context)
        self._context = context
        self._log(
            f"Channel context saved → {self.context_file} "
            f"({len(videos)} videos, overall median: "
            f"{overall_median:,.0f} views)"
        )
        return context

    # ─── Accessors ────────────────────────────────────────────────────────────

    def get_breakout_score(self, video_id: str) -> Optional[float]:
        if not self._context:
            return None
        return self._context["videos"].get(video_id, {}).get("breakout_score")

    def get_video_enrichment(self, video_id: str) -> Optional[dict]:
        """Return the analytics fields for a single video (None if unavailable)."""
        if not self._context:
            return None
        entry = self._context["videos"].get(video_id)
        if not entry:
            return None
        keys = [
            "breakout_score",
            "avg_view_percentage",
            "estimated_minutes_watched",
            "retention_curve",
        ]
        return {k: entry.get(k) for k in keys}