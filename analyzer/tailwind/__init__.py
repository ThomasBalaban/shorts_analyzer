"""Cultural tailwind analysis — Phase 5.

Deliberately last. By the time this runs we already know:
  - Which videos really broke out (baseline-normalized, from Phase 1)
  - What retention explains (from Phase 2's retention_interpretation)
  - What's already credited as craft / borrowed equity / channel equity
    (from Phase 2's attribution block)

So this layer tackles the *residual* variance: for the performance that
Analytics + craft + equity can't account for, what dated cultural
moment was plausibly in play? A text-only Gemini call per candidate
short produces dated hypotheses with confidence levels and search
terms that a human (or the optional Trends validator) can check.

Downstream apps MUST treat tailwind claims as hypotheses, not facts —
the schema enforces that with a `confidence` field and a
`trends_signal` field (when `--use-trends` is enabled).

Output: `output/<handle>.tailwind.json`. A separate file, not an edit
to the main analysis, so the tailwind layer can be re-run, iterated
on, or discarded independently of the expensive Phase 2 analysis.

See game_plan.md → Layer 5.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from analyzer.core.meta import build_meta, prompt_source_hash
from analyzer.core.models import MODEL_PRO
from analyzer.tailwind.gemini import analyze_tailwind
from analyzer.tailwind.prompts import build_tailwind_prompt
from analyzer.tailwind.residual import (
    DEFAULT_MIN_BREAKOUT,
    DEFAULT_MIN_RESIDUAL_RATIO,
    compute_residual,
    corpus_median_avg_view_pct,
)


TAILWIND_SCHEMA_VERSION = 1


def current_tailwind_prompt_hash() -> str:
    return prompt_source_hash(build_tailwind_prompt)


def build_tailwind_meta(ran_at: Optional[str] = None) -> dict:
    return build_meta(
        model=MODEL_PRO,
        schema_version=TAILWIND_SCHEMA_VERSION,
        prompt_hash=current_tailwind_prompt_hash(),
        ran_at=ran_at,
    )


def _derive_output_path(analysis_file: Path) -> Path:
    """`output/foo.json` → `output/foo.tailwind.json`."""
    return analysis_file.with_name(analysis_file.stem + ".tailwind.json")


def _load_analysis(analysis_file: Path) -> dict:
    if not analysis_file.exists():
        raise FileNotFoundError(f"Analysis file not found: {analysis_file}")
    with open(analysis_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "shorts" not in data or not isinstance(data["shorts"], list):
        raise ValueError(
            f"{analysis_file} does not look like an analyzer output "
            "file (no `shorts` array)."
        )
    return data


def _pick_candidates(
    shorts: list[dict],
    corpus_median_avp: Optional[float],
    min_breakout: float,
    min_residual_ratio: float,
    include_all: bool,
    only_video_ids: Optional[Iterable[str]] = None,
) -> list[tuple[dict, dict]]:
    """Return [(short, residual)] pairs that warrant a Gemini tailwind call.

    Skip shorts where tailwind speculation is noise:
      - no breakout_score (can't normalize)
      - breakout below `min_breakout` (median-or-worse performers)
      - residual_ratio below `min_residual_ratio` (retention already
        explains the breakout)

    `include_all=True` bypasses both cutoffs — useful when the user
    wants tailwind annotation on every short regardless of residual.

    `only_video_ids`: when given (rerun path), bypass cutoffs entirely
    and restrict to those video_ids. The operator picked them already;
    they don't need to pass the residual filter again.
    """
    allowlist = set(only_video_ids) if only_video_ids is not None else None

    picked: list[tuple[dict, dict]] = []
    for short in shorts:
        if allowlist is not None:
            if short.get("video_id") not in allowlist:
                continue
            picked.append((short, compute_residual(short, corpus_median_avp)))
            continue

        residual = compute_residual(short, corpus_median_avp)
        if include_all:
            picked.append((short, residual))
            continue

        breakout = residual.get("breakout_score")
        if not isinstance(breakout, (int, float)):
            continue
        if breakout < min_breakout:
            continue

        ratio = residual.get("residual_ratio")
        # Allow through when retention baseline is unknown — ratio will
        # be the raw breakout_score, already gated by min_breakout
        if ratio is not None and ratio < min_residual_ratio:
            continue
        picked.append((short, residual))
    return picked


def _load_existing_tailwind(output_path: Path) -> dict:
    """Read the current tailwind.json if present, so rerun-on-subset can
    merge into it instead of clobbering the unselected entries."""
    if not output_path.exists():
        return {}
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if isinstance(existing.get("videos"), dict):
            return existing["videos"]
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def run_tailwind_analysis(
    analysis_file: str | os.PathLike,
    output_file: str | os.PathLike | None = None,
    min_breakout: float = DEFAULT_MIN_BREAKOUT,
    min_residual_ratio: float = DEFAULT_MIN_RESIDUAL_RATIO,
    include_all: bool = False,
    use_trends: bool = False,
    video_ids: Optional[Iterable[str]] = None,
    log_func: Optional[Callable[[str], None]] = None,
) -> dict:
    """Build `<handle>.tailwind.json` from an analyzer output file.

    min_breakout / min_residual_ratio: candidate cutoffs (see
        residual.py). Ignored when include_all=True or when video_ids
        is given.
    use_trends: attach Google Trends interest-over-time to each
        hypothesis. Requires `pip install pytrends`; if missing, a
        warning is logged and the run proceeds without Trends data.
    video_ids: when given (rerun path), process only those video IDs
        and merge into the existing tailwind file — entries for
        unselected videos are preserved.
    """
    log = log_func or print

    analysis_path = Path(analysis_file)
    output_path = Path(output_file) if output_file else _derive_output_path(
        analysis_path)

    log("=" * 60)
    log("Channel tailwind analysis (Phase 5)")
    log("=" * 60)
    log(f"Reading: {analysis_path}")

    analysis = _load_analysis(analysis_path)
    shorts = analysis["shorts"]
    log(f"Corpus: {len(shorts)} analyzed shorts")

    corpus_median_avp = corpus_median_avg_view_pct(shorts)
    if corpus_median_avp is None:
        log(
            "⚠️  No avg_view_percentage in the corpus — residual "
            "estimation will fall back to raw breakout_score."
        )
    else:
        log(
            f"Corpus median avg_view_percentage: "
            f"{corpus_median_avp:.1f}% (used to normalize retention)"
        )

    candidates = _pick_candidates(
        shorts,
        corpus_median_avp,
        min_breakout=min_breakout,
        min_residual_ratio=min_residual_ratio,
        include_all=include_all,
        only_video_ids=video_ids,
    )
    if video_ids is not None:
        log(
            f"Candidates for tailwind analysis: {len(candidates)} "
            "(restricted to explicit video_ids — cutoffs bypassed)"
        )
    else:
        log(
            f"Candidates for tailwind analysis: {len(candidates)}"
            + (" (all shorts — include_all=True)" if include_all else "")
        )
    if not candidates:
        log(
            "No shorts crossed the residual cutoffs. Re-run with "
            "--all to force tailwind analysis on every record."
        )

    # Start from whatever's already on disk so a rerun on a subset
    # merges instead of clobbering. For a full run this is a no-op;
    # every candidate gets re-written anyway.
    preserved_videos = (
        _load_existing_tailwind(output_path) if video_ids is not None else {}
    )

    # Optional Trends wiring — resolved once up front so we can warn
    # loudly if requested-but-unavailable, instead of silently skipping
    # on each hypothesis.
    trends_enricher = None
    if use_trends:
        from analyzer.tailwind.trends import trends_available, enrich_hypotheses
        if not trends_available():
            log(
                "⚠️  --use-trends was set but pytrends is not installed. "
                "Install with `pip install pytrends` to enable. "
                "Continuing without Trends."
            )
        else:
            trends_enricher = enrich_hypotheses

    videos: dict[str, dict] = {}
    for i, (short, residual) in enumerate(candidates, 1):
        vid = short["video_id"]
        title = short.get("title", "")
        log(
            f"\n[{i}/{len(candidates)}] {vid} — "
            f"breakout={residual.get('breakout_score')}, "
            f"residual_ratio={residual.get('residual_ratio')}"
        )
        log(f"  Title: {title}")

        try:
            tailwind = analyze_tailwind(short, residual, log_func=log)
        except Exception as e:
            log(f"  ✗ Tailwind analysis failed: {e}")
            tailwind = {
                "residual_summary": "",
                "hypotheses": [],
                "overall_confidence": "low",
                "_error": str(e),
            }

        if trends_enricher is not None and tailwind.get("hypotheses"):
            try:
                trends_enricher(tailwind["hypotheses"], log_func=log)
            except Exception as e:
                log(f"  Trends enrichment failed: {e}")

        tailwind["_meta"] = build_tailwind_meta()
        videos[vid] = {
            "title": title,
            "published_date": short.get("published_date"),
            "breakout_score": short.get("breakout_score"),
            "residual": residual,
            "tailwind": tailwind,
        }

    # Merge: preserved entries first, freshly-processed ones win on conflict.
    merged_videos = {**preserved_videos, **videos}

    result = {
        "metadata": {
            "source_file": str(analysis_path),
            "source_channel_url": analysis.get("metadata", {}).get(
                "channel_url"),
            "generated_at": datetime.now().isoformat(),
            "gemini_model": MODEL_PRO,
            "tailwind_schema_version": TAILWIND_SCHEMA_VERSION,
            "source_schema_version": analysis.get("metadata", {}).get(
                "schema_version"),
            "total_shorts_in_corpus": len(shorts),
            "total_candidates_analyzed": len(candidates),
            "cutoffs": {
                "min_breakout": None if include_all else min_breakout,
                "min_residual_ratio": (
                    None if include_all else min_residual_ratio),
                "include_all": include_all,
            },
            "corpus_median_avg_view_pct": corpus_median_avp,
            "trends_enriched": trends_enricher is not None,
            "restricted_to_video_ids": (
                list(video_ids) if video_ids is not None else None),
        },
        "videos": merged_videos,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    log("=" * 60)
    log(f"Tailwind analysis complete → {output_path}")
    log("=" * 60)
    return result


__all__ = [
    "run_tailwind_analysis",
    "TAILWIND_SCHEMA_VERSION",
    "current_tailwind_prompt_hash",
    "build_tailwind_meta",
]
