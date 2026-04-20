"""
Gemini structured-output schema.

Kept in its own file because:
  - Phase 2 will add an `attribution` object (replicable craft / borrowed
    equity / channel-specific / tailwind) with per-claim evidence refs.
  - Phase 3 will add controlled-vocabulary tag fields (title_mechanics,
    hook_type, pivot_technique, audio_strategy) baked into enum values
    so Gemini literally cannot produce off-vocabulary tags.

Changing the schema here does not require touching the prompt or the
orchestrator.
"""

from google.genai import types  # type: ignore


ANALYSIS_SCHEMA = types.Schema(
    type="OBJECT",
    properties={
        "title": types.Schema(
            type="OBJECT",
            properties={
                "text": types.Schema(
                    type="STRING",
                    description="The exact title of the short, copied verbatim.",
                ),
                "why_it_worked": types.Schema(
                    type="STRING",
                    description=(
                        "Detailed analysis of why this specific title was effective. "
                        "Cover the concrete mechanics: curiosity gap, pop-culture "
                        "reference, promise/payoff structure, emotional hook, "
                        "specificity, POV, question vs statement, length, "
                        "word choice. Explain how it pairs with the video's "
                        "content. 4-6 sentences."
                    ),
                ),
            },
            required=["text", "why_it_worked"],
        ),
        "hook": types.Schema(
            type="OBJECT",
            properties={
                "description": types.Schema(
                    type="STRING",
                    description=(
                        "A precise description of the hook portion of the video "
                        "— you decide where the hook ends based on the video's "
                        "structure. Describe exactly what the viewer sees and "
                        "hears: first frame composition, on-screen text, audio, "
                        "tone, what question or tension it plants."
                    ),
                ),
                "why_it_worked": types.Schema(
                    type="STRING",
                    description=(
                        "Why this hook stops the scroll. Discuss pattern "
                        "interrupts, curiosity, visual contrast, audio cues, "
                        "and how it sets up the payoff. 3-5 sentences."
                    ),
                ),
            },
            required=["description", "why_it_worked"],
        ),
        "video_description": types.Schema(
            type="STRING",
            description=(
                "A detailed beat-by-beat walkthrough of the entire short. "
                "Describe every cut and edit, what's on screen, on-screen text "
                "overlays, audio choices (meme audio vs original VO vs music vs "
                "silence), pacing and rhythm, timing of the punchline, visual "
                "effects, and how the edit builds to its payoff. Be specific "
                "and concrete — cite approximate timestamps where helpful. "
                "This should read like an editor's breakdown, not a summary."
            ),
        ),
        "why_the_video_worked": types.Schema(
            type="STRING",
            description=(
                "Why this video earned the views it did. Analyze the content "
                "itself: setup/payoff structure, comedic or emotional timing, "
                "audio-visual synchronization, relatability, rewatchability, "
                "how the edit amplifies the core idea. Distinct from the title "
                "analysis — this is about the content, not the packaging. "
                "4-6 sentences."
            ),
        ),
        "what_could_have_been_better": types.Schema(
            type="STRING",
            description=(
                "Concrete, specific suggestions for what could have made this "
                "short perform even better. Think like an experienced editor "
                "giving notes: pacing changes, tighter cuts, different audio, "
                "a stronger first frame, better on-screen text, a sharper "
                "title variant, etc. Avoid generic advice — every suggestion "
                "should be tied to something specific in THIS video. "
                "3-5 sentences."
            ),
        ),
    },
    required=[
        "title",
        "hook",
        "video_description",
        "why_the_video_worked",
        "what_could_have_been_better",
    ],
)
