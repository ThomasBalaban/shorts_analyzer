"""Top-level analysis schema — composes the prose fields, retention
interpretation, attribution, and tag object into a single Schema.

The prose fields are kept from the original v2 schema (title, hook,
video_description, why_the_video_worked, what_could_have_been_better)
because the game plan explicitly says Phase 2 adds alongside, doesn't
replace. Downstream human readers still get the editor's-breakdown prose;
downstream AIs get retention + attribution + tags.
"""

from __future__ import annotations

from google.genai import types  # type: ignore

from analyzer.gemini.schema.attribution import ATTRIBUTION_SCHEMA
from analyzer.gemini.schema.retention import RETENTION_SCHEMA
from analyzer.gemini.schema.tags import TAGS_SCHEMA


_TITLE = types.Schema(
    type="OBJECT",
    properties={
        "text": types.Schema(
            type="STRING",
            description="Exact title of the short, copied verbatim.",
        ),
        "why_it_worked": types.Schema(
            type="STRING",
            description=(
                "Why this title earned clicks. Concrete mechanics: curiosity "
                "gap, pop-culture reference, promise/payoff, POV, "
                "specificity, word choice. Explain how it pairs with the "
                "video content. 4-6 sentences."
            ),
        ),
    },
    required=["text", "why_it_worked"],
)


_HOOK = types.Schema(
    type="OBJECT",
    properties={
        "description": types.Schema(
            type="STRING",
            description=(
                "Precise description of the hook — you decide where it ends "
                "based on the video's structure. First-frame composition, "
                "on-screen text, audio, tone, the tension it plants."
            ),
        ),
        "why_it_worked": types.Schema(
            type="STRING",
            description=(
                "Why this hook stops the scroll. Pattern interrupts, "
                "curiosity, visual contrast, audio cues, how it sets up the "
                "payoff. 3-5 sentences. If retention data shows a steep "
                "opening drop, the prose MUST reconcile that — don't claim "
                "a strong hook when the curve disagrees."
            ),
        ),
    },
    required=["description", "why_it_worked"],
)


ANALYSIS_SCHEMA = types.Schema(
    type="OBJECT",
    properties={
        "title": _TITLE,
        "hook": _HOOK,
        "video_description": types.Schema(
            type="STRING",
            description=(
                "Beat-by-beat walkthrough of the entire short. Every cut, "
                "on-screen text overlay, audio choice, visual effect, "
                "pacing, timing of the punchline. Cite timestamps. Reads "
                "like an editor's breakdown, not a summary."
            ),
        ),
        "why_the_video_worked": types.Schema(
            type="STRING",
            description=(
                "Why this video earned its views — content analysis, not "
                "packaging. Setup/payoff, timing, rewatchability, how the "
                "edit amplifies the core idea. If retention plateaus (viewers "
                "stayed) vs. cliffs (they left), the prose must reflect that. "
                "4-6 sentences."
            ),
        ),
        "what_could_have_been_better": types.Schema(
            type="STRING",
            description=(
                "Concrete editor's notes tied to THIS video. Pacing changes, "
                "tighter cuts, audio swaps, stronger first frame, sharper "
                "title variant. If retention shows a specific drop moment, "
                "the suggestion should address that moment. 3-5 sentences."
            ),
        ),
        "retention_interpretation": RETENTION_SCHEMA,
        "attribution": ATTRIBUTION_SCHEMA,
        "tags": TAGS_SCHEMA,
    },
    required=[
        "title",
        "hook",
        "video_description",
        "why_the_video_worked",
        "what_could_have_been_better",
        "retention_interpretation",
        "attribution",
        "tags",
    ],
)
