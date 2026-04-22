"""Attribution schema — decomposes performance into four buckets.

Each bucket forces Gemini to state a specific claim, cite evidence, and
declare a confidence level. This is the Phase 2 mechanism that makes the
analysis falsifiable: 'borrowed equity high' becomes checkable against
the tags (pop_culture_quote, smash_cut_to_reference, has_meme_audio_clip)
and against retention (borrowed-equity hits often produce early-video
spikes where the reference lands).

`evidence` should cite concrete things: retention curve moments
('retention jumps at 40%'), the avg_view_percentage number, tag IDs
applied in the tags object, or explicitly say 'no direct evidence' rather
than making something up.
"""

from __future__ import annotations

from google.genai import types  # type: ignore


_CONFIDENCE = ["low", "medium", "high"]


def _bucket(purpose: str, evidence_hint: str) -> types.Schema:
    return types.Schema(
        type="OBJECT",
        properties={
            "claim": types.Schema(
                type="STRING",
                description=f"{purpose} — be specific; 1-3 sentences.",
            ),
            "evidence": types.Schema(
                type="STRING",
                description=(
                    f"Concrete evidence for the claim. {evidence_hint} "
                    "If no direct evidence supports this bucket, say so."
                ),
            ),
            "confidence": types.Schema(
                type="STRING",
                enum=_CONFIDENCE,
                description=(
                    "low = speculation, medium = plausible with some "
                    "evidence, high = clearly supported by retention/tags."
                ),
            ),
        },
        required=["claim", "evidence", "confidence"],
    )


ATTRIBUTION_SCHEMA = types.Schema(
    type="OBJECT",
    description=(
        "Decompose the video's performance into four buckets. Each claim "
        "must cite concrete evidence (retention moments, tags, "
        "avg_view_percentage) or explicitly decline."
    ),
    properties={
        "replicable_craft": _bucket(
            "Craft you could deliberately repeat on a future short",
            "Cite the tags or retention shape that support replicability.",
        ),
        "borrowed_equity": _bucket(
            "Pop-culture references, meme audio, franchise recognition carrying weight",
            "Cite pop_culture_quote / smash_cut_to_reference / has_meme_audio_clip "
            "tags if applied, and retention spikes at the reference beat.",
        ),
        "channel_specific_equity": _bucket(
            "Factors only this channel's existing audience would value",
            "Cite evidence the subscriber base drove this rather than broad "
            "appeal — e.g. running joke, character familiarity, prior-video callback.",
        ),
        "probable_external_tailwind": _bucket(
            "External cultural moment plausibly boosting this video",
            "Trending game release, viral meme in the air, news cycle. "
            "Flag as speculation when evidence is indirect.",
        ),
    },
    required=[
        "replicable_craft",
        "borrowed_equity",
        "channel_specific_equity",
        "probable_external_tailwind",
    ],
)
