"""Residual-variance heuristic.

Phase 5 is scoped to the *residual*: the slice of a short's breakout that
Analytics can't account for through retention + average view percentage.
This module makes that slice explicit — numeric, auditable, cheap — so
the tailwind Gemini call can be given a concrete target to explain, and
so low-residual shorts can be skipped entirely (they don't need tailwind
speculation when craft already accounts for the breakout).

The heuristic is deliberately simple and transparent:

    retention_quality = avg_view_percentage / corpus_median_avg_view_pct
    retention_explained = clamp(retention_quality, 0.5, 3.0)
    residual_ratio = breakout_score / retention_explained

Interpretation:
  - residual_ratio near 1.0: breakout is fully explained by retention
    being above channel-typical. Tailwind speculation adds little.
  - residual_ratio >> 1.0: video outperformed what retention predicts.
    Something pushed impressions up — algorithm boost, external share,
    cultural moment. Tailwind worth investigating.
  - residual_ratio < 1.0: strong retention but middling views. Under-
    served by the algorithm; tailwind probably wasn't a factor.

This isn't a statistical model. It's a floor that filters obvious
non-candidates and gives Gemini a number to reconcile against.
"""

from __future__ import annotations

import statistics
from typing import Optional


RESIDUAL_RATIO_MIN = 0.5
RESIDUAL_RATIO_MAX = 3.0

# Default cutoff used by the orchestrator when picking which shorts to
# send to Gemini. Shorts below this breakout_score or residual_ratio are
# skipped — there's nothing tailwind-shaped to explain.
DEFAULT_MIN_BREAKOUT = 1.5
DEFAULT_MIN_RESIDUAL_RATIO = 1.25


def corpus_median_avg_view_pct(shorts: list[dict]) -> Optional[float]:
    """Median avg_view_percentage across the corpus.

    Used as the channel-typical baseline when normalizing a single
    video's retention quality. Returns None if the corpus has no usable
    data — caller should fall back to treating retention as neutral.
    """
    values = [
        s["analytics"]["avg_view_percentage"]
        for s in shorts
        if isinstance(s.get("analytics"), dict)
        and isinstance(s["analytics"].get("avg_view_percentage"), (int, float))
    ]
    if not values:
        return None
    return statistics.median(values)


def compute_residual(
    short: dict,
    corpus_median_avp: Optional[float],
) -> dict:
    """Estimate how much of a short's breakout isn't explained by retention.

    Returns a dict shaped for direct inclusion in the tailwind output
    file. All numeric fields are None when the underlying data is
    missing so downstream readers can distinguish "no data" from "zero."
    """
    breakout = short.get("breakout_score")
    analytics = short.get("analytics") or {}
    avp = analytics.get("avg_view_percentage")

    result: dict = {
        "breakout_score": breakout,
        "avg_view_percentage": avp,
        "corpus_median_avg_view_pct": corpus_median_avp,
        "retention_quality": None,
        "residual_ratio": None,
        "explanation": None,
    }

    if not isinstance(breakout, (int, float)):
        result["explanation"] = "no breakout_score — cannot estimate residual"
        return result

    if (avp is None or corpus_median_avp is None or corpus_median_avp <= 0):
        result["explanation"] = (
            "no retention baseline available — treating retention as neutral"
        )
        result["residual_ratio"] = round(breakout, 3)
        return result

    retention_quality = avp / corpus_median_avp
    retention_explained = max(
        RESIDUAL_RATIO_MIN,
        min(RESIDUAL_RATIO_MAX, retention_quality),
    )
    residual_ratio = breakout / retention_explained

    result["retention_quality"] = round(retention_quality, 3)
    result["residual_ratio"] = round(residual_ratio, 3)

    if residual_ratio >= 1.5:
        result["explanation"] = (
            "breakout outpaces retention — algorithm boost or external pull "
            "likely in play"
        )
    elif residual_ratio >= 1.0:
        result["explanation"] = (
            "retention partly explains breakout; modest residual for "
            "tailwind to cover"
        )
    else:
        result["explanation"] = (
            "retention stronger than views — tailwind unlikely to be "
            "load-bearing"
        )
    return result
