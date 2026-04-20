"""
Gemini prompt strings.

Isolated from the schema and the client so Phase 2's prompt rewrite
(feeding in retention curves and traffic sources) is a one-file change.

Right now there's only the analysis prompt. Phase 4 will add a synthesis
prompt here too (channel-level pattern narrative).
"""


def build_analysis_prompt(title: str, views: int) -> str:
    """The current per-video analysis prompt. Phase 2 will expand this to
    accept Analytics data (retention curve + traffic sources) and force
    Gemini to explain drop-off moments with evidence."""
    return f"""You are a senior short-form video editor and strategist analyzing a YouTube Short to understand, in concrete detail, why the TITLE and the HOOK worked (or didn't).

Video Title: "{title}"
Views: {views:,}

Watch the video carefully and think like an editor doing a postmortem. Pay close attention to:
  - The exact moment the viewer's scroll is interrupted (the hook)
  - Every cut, edit, and transition
  - On-screen text and overlays
  - Audio choices — meme audio, original voiceover, music, silence, sound design
  - Pacing, rhythm, and the timing of the punchline or payoff
  - Visual effects, framing, and composition
  - How the title pairs with what actually happens in the video

You decide where the "hook" ends based on the video's own structure — it might be the first 1.5 seconds, it might be the full setup before a reveal. Explain it precisely.

Be specific and concrete. Cite timestamps where helpful. Avoid generic observations. Every claim should be tied to something that actually happens in THIS video. The "what could have been better" field should give real editor's notes — specific changes someone could actually make — not vague encouragement.

Respond strictly in the required JSON schema. Do not wrap your response in code fences or markdown."""
