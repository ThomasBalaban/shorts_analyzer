"""Tailwind response schema — Phase 5.

A tailwind block is a set of *hypotheses* about what external cultural
context plausibly boosted this short beyond what Analytics can explain.
Every claim carries an explicit confidence level and a dated window so
downstream apps can reason about staleness (a 2022 meme is not a 2026
meme) and so a human can sanity-check against actual calendar events.

The schema is deliberately shaped to refuse vagueness:
  - each hypothesis must commit to a dated window
  - each hypothesis must list searchable terms that could be checked
  - `confidence = low` is the honest default; `high` requires evidence
  - an overall `residual_summary` forces Gemini to explain WHY tailwind
    is the leading explanation vs. craft/equity already tagged upstream

Downstream apps are instructed to treat these as hypotheses, never as
facts — and the schema enforces that by shape, not by trust.
"""

from __future__ import annotations

from google.genai import types  # type: ignore


_CONFIDENCE = ["low", "medium", "high"]


_HYPOTHESIS = types.Schema(
    type="OBJECT",
    properties={
        "claim": types.Schema(
            type="STRING",
            description=(
                "One-sentence hypothesis naming a specific cultural moment "
                "(game release, news cycle, viral meme, franchise beat, "
                "platform trend). Must be concrete — 'Star Wars is popular' "
                "is not a tailwind claim; 'Obi-Wan Kenobi finale aired two "
                "weeks before publish' is."
            ),
        ),
        "window_start": types.Schema(
            type="STRING",
            description=(
                "YYYY-MM-DD — earliest plausible date the tailwind was "
                "active. Use the best guess available; evergreen franchises "
                "without a specific beat belong in borrowed_equity, not here."
            ),
        ),
        "window_end": types.Schema(
            type="STRING",
            description=(
                "YYYY-MM-DD — latest plausible date the tailwind was "
                "active. For open-ended trends, estimate conservatively."
            ),
        ),
        "search_terms": types.Schema(
            type="ARRAY",
            description=(
                "2-5 search queries that would validate this claim against "
                "Google Trends, news archives, or Reddit. Pick terms a "
                "person could type into a search bar, not category labels."
            ),
            items=types.Schema(type="STRING"),
        ),
        "reasoning": types.Schema(
            type="STRING",
            description=(
                "Why you believe this tailwind was at play for THIS video: "
                "link the video's content/date/retention shape to the "
                "cultural moment. 2-4 sentences. If the link is indirect, "
                "say so rather than dressing it up."
            ),
        ),
        "confidence": types.Schema(
            type="STRING",
            enum=_CONFIDENCE,
            description=(
                "low = pure speculation, one plausible connection. "
                "medium = timing + content both point to this tailwind. "
                "high = video content explicitly references the moment AND "
                "publish date lands inside the cultural window."
            ),
        ),
    },
    required=[
        "claim",
        "window_start",
        "window_end",
        "search_terms",
        "reasoning",
        "confidence",
    ],
)


TAILWIND_SCHEMA = types.Schema(
    type="OBJECT",
    description=(
        "Dated cultural-tailwind hypotheses explaining residual performance "
        "Analytics can't account for. Treat every claim as a hypothesis "
        "to be validated downstream — never as fact."
    ),
    properties={
        "residual_summary": types.Schema(
            type="STRING",
            description=(
                "How much of this video's breakout is plausibly tailwind "
                "vs. already accounted for by craft/borrowed equity in the "
                "upstream attribution block. Reference the breakout_score, "
                "retention shape, and any load-bearing tags. 2-4 sentences. "
                "If tailwind is NOT the leading explanation, say so."
            ),
        ),
        "hypotheses": types.Schema(
            type="ARRAY",
            description=(
                "0-3 dated tailwind hypotheses. Empty array is correct when "
                "there is no plausible external moment — do not invent one "
                "just to fill the slot. Sort most-likely first."
            ),
            items=_HYPOTHESIS,
        ),
        "overall_confidence": types.Schema(
            type="STRING",
            enum=_CONFIDENCE,
            description=(
                "Your confidence that tailwind is meaningfully load-bearing "
                "for this video's performance. `low` when the evidence is "
                "thin or when craft/equity already explains the breakout."
            ),
        ),
    },
    required=["residual_summary", "hypotheses", "overall_confidence"],
)
