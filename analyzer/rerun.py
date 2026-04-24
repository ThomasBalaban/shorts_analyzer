"""Per-phase rerun operations.

Every rerun is an explicit, manual action — nothing in this module ever
fires from a schedule or startup hook. The operator picks a phase and
either (a) names the video_ids to rerun, or (b) picks a predicate filter
(`missing`, `schema_mismatch`, `model_mismatch`, `prompt_mismatch`,
`all`) that's resolved against the current `_meta` state of each
record.

Phases:
  - analytics  — refetch YouTube Analytics retention/engagement
  - analysis   — Phase 2 Gemini call (video upload + full analysis)
  - synthesis  — Phase 4 corpus-wide synthesis (always full-corpus)
  - tailwind   — Phase 5 dated-hypothesis Gemini call

Cost tiers, so the caller knows what they're asking for:
  - analytics  cheap, API-rate-limited
  - analysis   EXPENSIVE — video upload + Pro + thinking=high per video
  - synthesis  one text-only Gemini call, no per-video fan-out
  - tailwind   one text-only Gemini call per candidate, ~seconds each

The module is stateless — each function reads the file, does its work,
writes back. No caching between calls. The expensive Gemini client and
baseline are built fresh per invocation.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from analyzer.baseline import ChannelBaseline
from analyzer.core.analyzer import (
    SCHEMA_VERSION,
    build_analysis_meta,
    current_analysis_prompt_hash,
)
from analyzer.core.config import (
    analytics_available,
    get_analytics_client_secrets,
    get_analytics_token_path,
)
from analyzer.core.meta import (
    backfill_analysis_meta,
    backfill_tailwind_meta,
)
from analyzer.core.models import MODEL_PRO
from analyzer.gemini.client import GeminiVideoAnalyzer
from analyzer.synthesis import run_synthesis
from analyzer.tailwind import (
    TAILWIND_SCHEMA_VERSION,
    current_tailwind_prompt_hash,
    run_tailwind_analysis,
)
from analyzer.youtube.downloader import ShortDownloader


FILTERS = {
    "all",
    "missing",
    "schema_mismatch",
    "model_mismatch",
    "prompt_mismatch",
}


# ─── File discovery ────────────────────────────────────────────────────────

def _analysis_path(output_file: str | os.PathLike) -> Path:
    return Path(output_file)


def _tailwind_path(output_file: str | os.PathLike) -> Path:
    p = Path(output_file)
    return p.with_name(p.stem + ".tailwind.json")


def _synthesis_path(output_file: str | os.PathLike) -> Path:
    p = Path(output_file)
    return p.with_name(p.stem + ".synthesis.json")


def _context_path(output_file: str | os.PathLike) -> Path:
    p = Path(output_file)
    return p.with_name(p.stem + ".context.json")


def _load_analysis(output_file: str | os.PathLike) -> dict:
    """Load the analyzer output and backfill `_meta` for legacy records.

    Persists the backfill so subsequent reads see a stamped file and
    the change is visible to the operator (not hidden in memory).
    """
    path = _analysis_path(output_file)
    if not path.exists():
        raise FileNotFoundError(f"Analysis file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "shorts" not in data or not isinstance(data["shorts"], list):
        raise ValueError(
            f"{path} is not a valid analyzer output file (no `shorts`).")

    file_schema = (
        data.get("metadata", {}).get("schema_version") or SCHEMA_VERSION)
    if backfill_analysis_meta(data, file_schema):
        _save_analysis(output_file, data)
    return data


def _save_analysis(output_file: str | os.PathLike, data: dict) -> None:
    data["metadata"]["total_shorts_analyzed"] = len(data["shorts"])
    path = _analysis_path(output_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_tailwind(output_file: str | os.PathLike) -> Optional[dict]:
    """Load tailwind.json and backfill `_meta` on legacy entries.

    Persists the backfill so the file converges to the current shape.
    """
    path = _tailwind_path(output_file)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    if backfill_tailwind_meta(data, TAILWIND_SCHEMA_VERSION):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError:
            pass
    return data


# ─── Predicate resolution ──────────────────────────────────────────────────

def _meta_mismatch_reasons(
    meta: Optional[dict],
    *,
    current_model: Optional[str],
    current_schema: int,
    current_prompt_hash: Optional[str],
) -> list[str]:
    """List of reasons this record would be flagged stale by predicates.

    `missing` applies when no `_meta` exists at all. Otherwise we check
    each field against current values. Legacy records that were
    backfilled with `model=null` / `prompt_hash=null` DO match
    `model_mismatch` / `prompt_mismatch` — "unknown" is not "current,"
    and the whole point of these predicates is to help the operator
    find records that would benefit from a rerun against today's model
    and prompt.
    """
    if not isinstance(meta, dict):
        return ["missing"]
    reasons = []
    if (current_schema is not None
            and meta.get("schema_version") != current_schema):
        reasons.append("schema_mismatch")
    if (current_model is not None
            and meta.get("model") != current_model):
        reasons.append("model_mismatch")
    if (current_prompt_hash is not None
            and meta.get("prompt_hash") != current_prompt_hash):
        reasons.append("prompt_mismatch")
    return reasons


def _resolve_targets(
    data: dict,
    video_ids: Optional[Iterable[str]],
    filter_: Optional[str],
    *,
    phase: str,
    tailwind_data: Optional[dict] = None,
) -> list[str]:
    """Turn (video_ids, filter) into a concrete list of video_ids to process.

    Explicit `video_ids` wins: we trust the caller. When only `filter`
    is given, compute the set against current `_meta` for the phase.
    """
    if video_ids is not None:
        picked = list(video_ids)
        known = {s["video_id"] for s in data["shorts"]}
        unknown = [v for v in picked if v not in known]
        if unknown:
            raise ValueError(
                f"Unknown video_id(s) not in corpus: {unknown}")
        return picked

    if filter_ is None:
        raise ValueError(
            "Either video_ids or filter must be specified.")
    if filter_ not in FILTERS:
        raise ValueError(
            f"Unknown filter '{filter_}'. Allowed: {sorted(FILTERS)}")

    if filter_ == "all":
        return [s["video_id"] for s in data["shorts"]]

    # Phase-specific _meta lookups
    if phase == "analytics":
        # Analytics has no _meta — "missing" = no analytics block. Other
        # predicates don't apply cleanly, so we raise rather than silently
        # returning []
        if filter_ != "missing":
            raise ValueError(
                f"filter='{filter_}' is not supported for analytics; "
                "use filter='missing' or explicit video_ids.")
        return [
            s["video_id"] for s in data["shorts"]
            if not isinstance(s.get("analytics"), dict)
            or s["analytics"].get("retention_curve") is None
        ]

    if phase == "analysis":
        current_hash = current_analysis_prompt_hash()
        picked = []
        for s in data["shorts"]:
            meta = (s.get("gemini_analysis") or {}).get("_meta")
            if filter_ == "missing":
                if not isinstance(meta, dict):
                    picked.append(s["video_id"])
                continue
            reasons = _meta_mismatch_reasons(
                meta,
                current_model=MODEL_PRO,
                current_schema=SCHEMA_VERSION,
                current_prompt_hash=current_hash,
            )
            if filter_ in reasons:
                picked.append(s["video_id"])
        return picked

    if phase == "tailwind":
        current_hash = current_tailwind_prompt_hash()
        tw_videos = (tailwind_data or {}).get("videos") or {}
        picked = []
        for s in data["shorts"]:
            vid = s["video_id"]
            entry = tw_videos.get(vid) or {}
            tw = entry.get("tailwind") or {}
            meta = tw.get("_meta") if tw else None
            if filter_ == "missing":
                if vid not in tw_videos:
                    picked.append(vid)
                continue
            reasons = _meta_mismatch_reasons(
                meta,
                current_model=MODEL_PRO,
                current_schema=TAILWIND_SCHEMA_VERSION,
                current_prompt_hash=current_hash,
            )
            if filter_ in reasons:
                picked.append(vid)
        return picked

    raise ValueError(f"Unknown phase '{phase}'")


# ─── Listing ───────────────────────────────────────────────────────────────

def list_videos(output_file: str | os.PathLike) -> dict:
    """Return a structured view of each video's per-phase state.

    Response is stable and safe to serve over HTTP: no file paths leak,
    no secrets. `stale_reasons` is the authoritative list of predicate
    labels that would select this video for rerun.
    """
    data = _load_analysis(output_file)
    tailwind = _load_tailwind(output_file)
    tw_videos = (tailwind or {}).get("videos") or {}

    analysis_hash = current_analysis_prompt_hash()
    tailwind_hash = current_tailwind_prompt_hash()

    result = {
        "analysis_file": str(_analysis_path(output_file)),
        "tailwind_file": str(_tailwind_path(output_file))
        if tailwind else None,
        "synthesis_file": str(_synthesis_path(output_file))
        if _synthesis_path(output_file).exists() else None,
        "channel_url": data.get("metadata", {}).get("channel_url"),
        "corpus_schema_version": data.get(
            "metadata", {}).get("schema_version"),
        "current": {
            "analysis": {
                "model": MODEL_PRO,
                "schema_version": SCHEMA_VERSION,
                "prompt_hash": analysis_hash,
            },
            "tailwind": {
                "model": MODEL_PRO,
                "schema_version": TAILWIND_SCHEMA_VERSION,
                "prompt_hash": tailwind_hash,
            },
        },
        "videos": [],
    }

    for s in data["shorts"]:
        vid = s["video_id"]
        gemini = s.get("gemini_analysis") or {}
        analysis_meta = gemini.get("_meta")
        analysis_reasons = _meta_mismatch_reasons(
            analysis_meta,
            current_model=MODEL_PRO,
            current_schema=SCHEMA_VERSION,
            current_prompt_hash=analysis_hash,
        )

        tw_entry = tw_videos.get(vid) or {}
        tw_block = tw_entry.get("tailwind") or {}
        tw_meta = tw_block.get("_meta") if tw_block else None
        tw_reasons = (
            ["missing"] if vid not in tw_videos
            else _meta_mismatch_reasons(
                tw_meta,
                current_model=MODEL_PRO,
                current_schema=TAILWIND_SCHEMA_VERSION,
                current_prompt_hash=tailwind_hash,
            )
        )

        analytics = s.get("analytics") or {}
        has_retention = isinstance(analytics, dict) and (
            analytics.get("retention_curve") is not None)

        result["videos"].append({
            "video_id": vid,
            "title": s.get("title"),
            "views": s.get("views"),
            "published_date": s.get("published_date"),
            "breakout_score": s.get("breakout_score"),
            "phases": {
                "analytics": {
                    "present": has_retention,
                    "avg_view_percentage": analytics.get(
                        "avg_view_percentage"),
                    "fetched_at": analytics.get("analytics_fetched_at"),
                    "stale_reasons":
                        [] if has_retention else ["missing"],
                },
                "analysis": {
                    "present": isinstance(analysis_meta, dict)
                    or bool(gemini),
                    "meta": analysis_meta,
                    "ran_at": s.get("analysis_timestamp"),
                    "stale_reasons": analysis_reasons,
                },
                "tailwind": {
                    "present": vid in tw_videos and bool(tw_block),
                    "meta": tw_meta,
                    "stale_reasons": tw_reasons,
                },
            },
        })
    return result


# ─── Shared dependency builder ─────────────────────────────────────────────

def _build_baseline(
    output_file: str | os.PathLike,
    log_func: Callable[[str], None],
) -> ChannelBaseline:
    project_root = Path(__file__).resolve().parents[1]
    baseline = ChannelBaseline(
        context_file=_context_path(output_file),
        cache_dir=project_root / "data" / "analytics_cache",
        log_func=log_func,
    )
    baseline.load()
    return baseline


def _build_analytics_client(log_func: Callable[[str], None]):
    if not analytics_available():
        return None
    from analyzer.youtube.analytics import YouTubeAnalyticsClient
    return YouTubeAnalyticsClient(
        client_secrets_path=get_analytics_client_secrets(),
        token_path=get_analytics_token_path(),
        log_func=log_func,
    )


# ─── Rerun: analytics ──────────────────────────────────────────────────────

def rerun_analytics(
    output_file: str | os.PathLike,
    *,
    video_ids: Optional[Iterable[str]] = None,
    filter: Optional[str] = None,
    log_func: Optional[Callable[[str], None]] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
) -> dict:
    """Refresh Phase 1 analytics for selected videos.

    Rebuilds the channel baseline from the full corpus (so monthly
    medians stay accurate), then updates the `analytics` block +
    `breakout_score` on each targeted record.

    Returns a summary dict: `{targets, updated, errors}`.
    """
    log = log_func or print
    stop = stop_flag or (lambda: False)

    data = _load_analysis(output_file)
    targets = _resolve_targets(
        data, video_ids, filter, phase="analytics")
    log(f"rerun_analytics: {len(targets)} target(s)")

    if not targets:
        return {"targets": 0, "updated": 0, "errors": []}

    analytics_client = _build_analytics_client(log)
    if analytics_client is None:
        raise RuntimeError(
            "Analytics client not configured (missing client_secrets.json)")

    baseline = _build_baseline(output_file, log)

    # Invalidate cache entries for targets so baseline.build refetches them.
    project_root = Path(__file__).resolve().parents[1]
    cache_dir = project_root / "data" / "analytics_cache"
    for vid in targets:
        cache_file = cache_dir / f"{vid}.json"
        if cache_file.exists():
            try:
                cache_file.unlink()
            except OSError as e:
                log(f"  Could not clear cache for {vid}: {e}")

    # Rebuild baseline from the full corpus (baseline.build re-fetches
    # analytics for any video whose cache is gone). The baseline needs
    # the full population to compute medians correctly.
    all_shorts = [
        {"video_id": s["video_id"], "views": s["views"],
         "published_date": s["published_date"]}
        for s in data["shorts"]
    ]
    baseline.build(all_shorts, analytics_client=analytics_client)

    updated = 0
    errors: list[dict] = []
    for vid in targets:
        if stop():
            log("  Stop requested; aborting.")
            break
        enrichment = baseline.get_video_enrichment(vid)
        if enrichment is None:
            errors.append({"video_id": vid, "error": "no enrichment returned"})
            continue
        for entry in data["shorts"]:
            if entry.get("video_id") != vid:
                continue
            entry["analytics"] = enrichment
            entry["breakout_score"] = enrichment.get("breakout_score")
            updated += 1
            break

    _save_analysis(output_file, data)
    log(f"rerun_analytics complete: updated={updated}, errors={len(errors)}")
    return {"targets": len(targets), "updated": updated, "errors": errors}


# ─── Rerun: analysis (Phase 2) ─────────────────────────────────────────────

def rerun_analysis(
    output_file: str | os.PathLike,
    *,
    video_ids: Optional[Iterable[str]] = None,
    filter: Optional[str] = None,
    log_func: Optional[Callable[[str], None]] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
) -> dict:
    """Rerun Phase 2 Gemini analysis for selected videos.

    EXPENSIVE: each target = one video download + one Gemini Pro
    generate_content with thinking_level=high. The caller is on the
    hook for knowing what they're asking for — this function does not
    self-gate.

    Each targeted record has its `gemini_analysis`, `analytics`,
    `breakout_score`, and `analysis_timestamp` replaced. Untargeted
    records are untouched.

    Returns `{targets, updated, errors}`.
    """
    log = log_func or print
    stop = stop_flag or (lambda: False)

    data = _load_analysis(output_file)
    targets = _resolve_targets(
        data, video_ids, filter, phase="analysis")
    log(f"rerun_analysis: {len(targets)} target(s)")

    if not targets:
        return {"targets": 0, "updated": 0, "errors": []}

    project_root = Path(__file__).resolve().parents[1]
    temp_dir = project_root / "temp_downloads"
    downloader = ShortDownloader(temp_dir=temp_dir, log_func=log)
    gemini = GeminiVideoAnalyzer(log_func=log)
    baseline = _build_baseline(output_file, log)

    updated = 0
    errors: list[dict] = []

    targets_set = set(targets)
    try:
        for entry in data["shorts"]:
            if stop():
                log("  Stop requested; aborting.")
                break
            vid = entry.get("video_id")
            if vid not in targets_set:
                continue
            log(f"\n[rerun] {vid} — {entry.get('title', '')[:60]}")
            try:
                video_path = downloader.download(entry["url"], vid)
                enrichment = baseline.get_video_enrichment(vid)
                log("  Analyzing with Gemini...")
                analysis = gemini.analyze(
                    video_path,
                    entry["title"],
                    entry["views"],
                    analytics=enrichment,
                )
                ran_at = datetime.now().isoformat()
                analysis["_meta"] = build_analysis_meta(ran_at=ran_at)

                entry["gemini_analysis"] = analysis
                entry["analysis_timestamp"] = ran_at
                if enrichment is not None:
                    entry["analytics"] = enrichment
                    entry["breakout_score"] = enrichment.get("breakout_score")

                _save_analysis(output_file, data)
                log(f"  ✓ Updated {vid}")
                updated += 1

                try:
                    video_path.unlink()
                except OSError:
                    pass

            except Exception as e:
                log(f"  ✗ Rerun failed for {vid}: {e}")
                errors.append({"video_id": vid, "error": str(e)})
                continue
    finally:
        try:
            downloader.cleanup()
        except Exception:
            pass

    log(f"rerun_analysis complete: updated={updated}, errors={len(errors)}")
    return {"targets": len(targets), "updated": updated, "errors": errors}


# ─── Rerun: synthesis (Phase 4) ────────────────────────────────────────────

def rerun_synthesis(
    output_file: str | os.PathLike,
    *,
    skip_narrative: bool = False,
    log_func: Optional[Callable[[str], None]] = None,
) -> dict:
    """Rerun Phase 4 synthesis. Always corpus-wide (no per-video filter)."""
    log = log_func or print
    run_synthesis(
        analysis_file=_analysis_path(output_file),
        skip_narrative=skip_narrative,
        log_func=log,
    )
    return {"ok": True}


# ─── Rerun: tailwind (Phase 5) ─────────────────────────────────────────────

def rerun_tailwind(
    output_file: str | os.PathLike,
    *,
    video_ids: Optional[Iterable[str]] = None,
    filter: Optional[str] = None,
    include_all: bool = False,
    use_trends: bool = False,
    log_func: Optional[Callable[[str], None]] = None,
) -> dict:
    """Rerun Phase 5 tailwind for selected videos.

    If `video_ids` or `filter` is given, entries for unselected videos
    are preserved (merge). If neither is given, falls back to the normal
    full tailwind run with default residual cutoffs.
    """
    log = log_func or print
    data = _load_analysis(output_file)

    if video_ids is not None or filter is not None:
        tailwind_data = _load_tailwind(output_file)
        targets = _resolve_targets(
            data, video_ids, filter,
            phase="tailwind", tailwind_data=tailwind_data,
        )
        log(f"rerun_tailwind: {len(targets)} target(s)")
        if not targets:
            return {"targets": 0, "updated": 0}
        run_tailwind_analysis(
            analysis_file=_analysis_path(output_file),
            video_ids=targets,
            use_trends=use_trends,
            log_func=log,
        )
        return {"targets": len(targets), "updated": len(targets)}

    # No filter → fresh full run (caller wants default behavior)
    run_tailwind_analysis(
        analysis_file=_analysis_path(output_file),
        include_all=include_all,
        use_trends=use_trends,
        log_func=log,
    )
    return {"targets": None, "updated": None}


__all__ = [
    "FILTERS",
    "list_videos",
    "rerun_analytics",
    "rerun_analysis",
    "rerun_synthesis",
    "rerun_tailwind",
]
