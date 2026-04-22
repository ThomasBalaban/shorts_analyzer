"""Gemini prompt strings.

Phase 2/3 rewrite: the analysis prompt now receives retention data and the
full tag vocabulary. The prose fields still exist (kept alongside, not
replaced) but must reconcile with the retention curve. The structured-
output schema enforces the tag enum; the prompt explains what each tag
means so Gemini applies them consistently.

The synthesis prompt (Phase 4 — channel-level pattern narrative) will live
in this file too when that phase lands.
"""

from __future__ import annotations

from typing import Optional

from analyzer.tags import format_vocabulary


def _format_retention(analytics: Optional[dict]) -> str:
    """Render the retention curve and engagement stats as a block Gemini
    can reason about. Returns a 'no data' stub when analytics is missing so
    the prompt structure stays consistent run-to-run."""
    if not analytics:
        return (
            "## Analytics data\n"
            "No retention data available for this video. "
            "Write 'no retention data available' in each retention_interpretation "
            "field and set attribution confidence levels to 'low' where the "
            "bucket would have depended on retention evidence."
        )

    avg = analytics.get("avg_view_percentage")
    mins_watched = analytics.get("estimated_minutes_watched")
    curve = analytics.get("retention_curve") or []
    breakout = analytics.get("breakout_score")

    lines = ["## Analytics data"]
    if breakout is not None:
        lines.append(
            f"- Breakout score: {breakout:.2f}x the channel median for the "
            "publish month. >1 = above median, <1 = below."
        )
    if avg is not None:
        lines.append(
            f"- Average view percentage: {avg:.1f}% "
            "(>100% means viewers looped / rewatched)."
        )
    if mins_watched is not None:
        lines.append(f"- Estimated minutes watched: {mins_watched:,.0f}.")

    if curve:
        lines.append("")
        lines.append(
            "Retention curve — `watch_ratio` is the fraction of starting "
            "viewers still watching at each point of video length. "
            "Values >1.0 indicate rewatches:"
        )
        for point in curve:
            lines.append(
                f"  - {point['pct']:>3}% through: "
                f"watch_ratio = {point['watch_ratio']:.3f}"
            )
    else:
        lines.append("- No retention curve available.")

    return "\n".join(lines)


def build_analysis_prompt(
    title: str,
    views: int,
    analytics: Optional[dict] = None,
) -> str:
    """Per-video analysis prompt.

    analytics: optional dict with keys `avg_view_percentage`,
        `estimated_minutes_watched`, `retention_curve`, `breakout_score`.
        Shape matches what ChannelBaseline.get_video_enrichment returns.
    """
    retention_block = _format_retention(analytics)
    vocab_block = format_vocabulary()

    return f"""You are a senior short-form video editor and strategist analyzing a YouTube Short. Your analysis will be consumed by another AI that writes titles and guides edits, so it must be concrete, evidence-grounded, and structured.

Video Title: "{title}"
Views: {views:,}

{retention_block}

## What to do

Watch the video carefully. Then produce a structured analysis with three layers:

1. **Prose fields** (title, hook, video_description, why_the_video_worked, what_could_have_been_better): editor's-breakdown prose. Every claim must be tied to something that happens in THIS specific video — no generic observations. Cite timestamps where helpful.

2. **Retention interpretation**: explain what the retention curve actually shows. If you claim the hook is strong but retention drops 40% in the first second, you must reconcile that contradiction in the prose. If no retention data was provided, write 'no retention data available' in each retention field.

3. **Attribution** (replicable_craft, borrowed_equity, channel_specific_equity, probable_external_tailwind): decompose performance into these four buckets. For each bucket, state a specific claim, cite concrete evidence (retention moments, applied tags, avg_view_percentage), and declare a confidence level. If a bucket has no evidence, say so rather than speculating.

4. **Tags**: apply every tag that legitimately fits across all 14 axes. Overlapping tags are expected and desired — the same concept often appears as presence in one axis and role in another (e.g. `zoom_punch` in visual_effects is "was zoom used anywhere", `zoom_punch_in_payoff` in payoff_technique is "was zoom the load-bearing beat"). Use ONLY the tag IDs listed below — other values will be rejected.

## Observation notes
- You decide where the hook ends based on the video's own structure.
- The "what could have been better" field should give real editor's notes — specific changes someone could actually make — not vague encouragement. If retention shows a drop moment, the suggestion should address it.
- Be specific about audio: meme audio vs. original VO vs. music vs. silence, and whether SFX stingers punctuate beats.

## Tag vocabulary

Apply tags from this controlled vocabulary. Multi-tag axes are arrays; single-tag axes are strings. Use tag IDs exactly as written.

{vocab_block}

## Output

Respond strictly in the required JSON schema. Do not wrap your response in code fences or markdown."""
