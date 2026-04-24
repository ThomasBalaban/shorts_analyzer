"""Prompt builder for the tailwind Gemini call.

This is a text-only call — by the time we run Phase 5 the video has
already been watched once in Phase 2, and the prose description +
retention curve + attribution block are captured in the analysis file.
Re-uploading the video would roughly double the API cost of the whole
pipeline for a layer explicitly flagged as the most speculative.

What we send instead:
  - video title + publish date (load-bearing: date is the axis tailwind
    turns on)
  - the breakout_score and residual-variance estimate (tells Gemini how
    much unexplained performance there is to explain)
  - a condensed retention summary (shape, not all 20 points)
  - the existing attribution block (so Gemini can see what's already
    been credited to craft/equity and not double-count)
  - the prior prose description + why_the_video_worked (gives content
    handle for tying to cultural moments)

Everything is framed as: "here is the residual — what external context
plausibly caused it, and how sure are you?"
"""

from __future__ import annotations

import json
from typing import Optional


def _retention_summary(analytics: Optional[dict]) -> str:
    """Collapse the full retention curve into a handful of landmark points.

    Gemini doesn't need 20 values to reason about tailwind — it needs
    the shape. We surface the 5%, 25%, 50%, 75%, and 95% marks plus
    the avg_view_percentage, which is plenty to pair with the breakout
    score.
    """
    if not analytics:
        return "- No retention data available."
    avp = analytics.get("avg_view_percentage")
    curve = analytics.get("retention_curve") or []

    lines = []
    if avp is not None:
        lines.append(f"- Average view percentage: {avp:.1f}%")
    if curve:
        wanted = [5, 25, 50, 75, 95]
        picks = []
        for target in wanted:
            best = min(curve, key=lambda p: abs(p["pct"] - target))
            picks.append(f"{best['pct']}%→{best['watch_ratio']:.2f}")
        lines.append("- Retention landmarks: " + ", ".join(picks))
    return "\n".join(lines) if lines else "- No retention data available."


def _attribution_summary(gemini_analysis: dict) -> str:
    """Compact view of the existing 4-bucket attribution block.

    We hand Gemini the prior verdict so Phase 5 doesn't re-invent work
    already done in Phase 2. The goal is for tailwind to cover what the
    other three buckets don't — Gemini needs to see the full picture
    to know what's already been credited.
    """
    attribution = gemini_analysis.get("attribution") or {}
    if not attribution:
        return "- No prior attribution on file."
    buckets = [
        ("replicable_craft", "Craft"),
        ("borrowed_equity", "Borrowed equity"),
        ("channel_specific_equity", "Channel-specific equity"),
        ("probable_external_tailwind", "Prior tailwind guess"),
    ]
    lines = []
    for key, label in buckets:
        bucket = attribution.get(key) or {}
        claim = (bucket.get("claim") or "").strip()
        conf = bucket.get("confidence") or "?"
        if claim:
            lines.append(f"- {label} ({conf}): {claim}")
        else:
            lines.append(f"- {label}: [no claim on file]")
    return "\n".join(lines)


def build_tailwind_prompt(
    short: dict,
    residual: dict,
) -> str:
    """Build the text prompt for a single video's tailwind analysis.

    short: a record from the analyzer output `shorts` array.
    residual: the dict returned by residual.compute_residual().
    """
    title = short.get("title", "")
    video_id = short.get("video_id", "")
    published = short.get("published_date", "unknown")
    breakout = short.get("breakout_score")
    views = short.get("views")

    analytics = short.get("analytics") or {}
    gemini_prior = short.get("gemini_analysis") or {}

    retention_block = _retention_summary(analytics)
    attribution_block = _attribution_summary(gemini_prior)

    description = (gemini_prior.get("video_description") or "").strip()
    why_worked = (gemini_prior.get("why_the_video_worked") or "").strip()

    residual_block = json.dumps({
        "breakout_score": residual.get("breakout_score"),
        "residual_ratio": residual.get("residual_ratio"),
        "retention_quality_vs_channel": residual.get("retention_quality"),
        "interpretation": residual.get("explanation"),
    }, indent=2)

    return f"""You are refining the tailwind attribution for a single YouTube Short. Your job is narrow and honest: identify dated cultural moments that plausibly boosted this video's performance beyond what retention alone would predict. Everything you produce will be consumed downstream as HYPOTHESES, not facts.

## The video
- Title: "{title}"
- Video ID: {video_id}
- Published: {published}
- Views: {views:,} (breakout score: {breakout}x the channel median for that month)

## Performance shape
{retention_block}

## Residual variance estimate
{residual_block}

`residual_ratio` is breakout_score divided by a clamped retention-quality factor. Values near 1.0 mean retention already explains the breakout and tailwind speculation adds little. Values above ~1.3 mean views outran retention — something external plausibly pushed impressions up. Use this number as the size of the slice you are trying to explain.

## Prior attribution (Phase 2) — already on file
{attribution_block}

These buckets are already credited. Your job is to cover what they miss. Do NOT re-describe craft or evergreen franchise recognition already captured above — those belong to other buckets. Tailwind is specifically time-bound cultural moments: a game launching, a news cycle, a meme peaking, a franchise beat (trailer, finale, reveal, tournament), a platform trend that had a moment.

## Prior content description (for grounding)
{description[:1500]}

## Prior reasoning on why the video worked
{why_worked[:800]}

## What to produce

1. `residual_summary`: how much of this video's breakout is plausibly tailwind vs. already accounted for upstream. Reference the residual_ratio and any load-bearing content details. If tailwind is NOT the leading explanation, say so. 2-4 sentences.

2. `hypotheses`: 0-3 dated tailwind hypotheses, most-likely first. Each must commit to a window (YYYY-MM-DD start and end) that brackets when the cultural moment was live, list 2-5 search_terms a human could validate against Google Trends or a news archive, and declare confidence honestly. Empty array is correct when there is no plausible external moment — do not invent one to fill the slot.

3. `overall_confidence`: low / medium / high. Low when tailwind is thin or when craft/equity already explains the breakout. High requires that the video content explicitly references the cultural moment AND the publish date lands inside the window.

Rules:
- Only propose a tailwind hypothesis if it is specifically dated. Evergreen franchise recognition (e.g. "Star Wars is always popular") belongs in borrowed_equity, which is already on file — not here.
- Publish date is {published}. Windows that don't overlap the publish date should not appear.
- If `residual_ratio` is below 1.1, default to an empty hypotheses array and low overall_confidence unless you have a specific content-linked moment to cite.
- Respond strictly in the required JSON schema. No markdown fences.
"""
