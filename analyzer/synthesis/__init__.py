"""Channel-level pattern synthesis — Phase 4.

Reads the per-video output JSON (e.g. `output/<handle>.json`), computes
tag-frequency tables split by performance quintile, surfaces "unique to
breakouts" / "absent from breakouts" / shared-baseline / conditional
patterns, and layers a Gemini-written narrative on top of the numbers.

Writes `output/<handle>.synthesis.json` — the file downstream
title/edit-advice apps load FIRST for strategy before drilling into
individual records for examples.

Usage:
    from analyzer.synthesis import run_synthesis
    run_synthesis("output/PeepingOtter.json")

Or via the CLI at project root:
    python synthesize.py --analysis output/PeepingOtter.json

See game_plan.md → Layer 4.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from analyzer.core.models import MODEL_PRO
from analyzer.synthesis.narrative import write_narrative
from analyzer.synthesis.stats import compute_stats


# Below this corpus size, quintile splits are just the identity function
# (1 video per quintile). Phase 4 still produces a file so downstream
# consumers can inspect it, but the narrative is told to flag the low
# confidence and the metadata carries a warning flag.
MIN_CORPUS_FOR_CONFIDENT_SYNTHESIS = 20

SYNTHESIS_SCHEMA_VERSION = 1


def _derive_output_path(analysis_file: Path) -> Path:
    """`output/foo.json` → `output/foo.synthesis.json`."""
    return analysis_file.with_name(analysis_file.stem + ".synthesis.json")


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


def run_synthesis(
    analysis_file: str | os.PathLike,
    output_file: str | os.PathLike | None = None,
    skip_narrative: bool = False,
    log_func: Optional[Callable[[str], None]] = None,
) -> dict:
    """Build `<handle>.synthesis.json` from an analyzer output file.

    skip_narrative: compute stats only, skip the Gemini call. Useful
        for iterating on the stat math without burning API calls.
    """
    log = log_func or print

    analysis_path = Path(analysis_file)
    output_path = Path(output_file) if output_file else _derive_output_path(
        analysis_path)

    log("=" * 60)
    log("Channel synthesis (Phase 4)")
    log("=" * 60)
    log(f"Reading: {analysis_path}")

    analysis = _load_analysis(analysis_path)
    shorts = analysis["shorts"]
    log(f"Corpus: {len(shorts)} analyzed shorts")

    small_corpus = len(shorts) < MIN_CORPUS_FOR_CONFIDENT_SYNTHESIS
    if small_corpus:
        log(
            f"⚠️  Corpus is below {MIN_CORPUS_FOR_CONFIDENT_SYNTHESIS} "
            "— quintile splits will be noisy. Generating anyway; "
            "narrative will flag low confidence."
        )

    log("Computing statistics...")
    stats = compute_stats(shorts)
    log(
        f"  Quintiles: top n={stats['quintiles']['n_top']} "
        f"(≥{stats['quintiles']['top_threshold']}x), "
        f"bottom n={stats['quintiles']['n_bottom']} "
        f"(≤{stats['quintiles']['bottom_threshold']}x)"
    )
    log(
        f"  Unique-to-breakout tags: "
        f"{len(stats['unique_to_breakouts'])}"
    )
    log(
        f"  Conditional patterns: "
        f"{len(stats['conditional_patterns'])}"
    )

    narrative: dict
    if skip_narrative:
        log("Skipping narrative synthesis (skip_narrative=True)")
        narrative = {"_skipped": True}
    else:
        narrative = write_narrative(stats, log_func=log)

    result = {
        "metadata": {
            "source_file": str(analysis_path),
            "source_channel_url": analysis.get("metadata", {}).get(
                "channel_url"),
            "generated_at": datetime.now().isoformat(),
            "gemini_model": MODEL_PRO,
            "synthesis_schema_version": SYNTHESIS_SCHEMA_VERSION,
            "source_schema_version": analysis.get("metadata", {}).get(
                "schema_version"),
            "total_shorts": len(shorts),
            "small_corpus_warning": small_corpus,
            "min_corpus_threshold": MIN_CORPUS_FOR_CONFIDENT_SYNTHESIS,
        },
        "narrative": narrative,
        **stats,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    log("=" * 60)
    log(f"Synthesis complete → {output_path}")
    log("=" * 60)
    return result


__all__ = ["run_synthesis", "SYNTHESIS_SCHEMA_VERSION"]
