"""
Cultural tailwind analysis — [Phase 5, not yet implemented]

Deliberately last. By the time this is built we already know:
  - Which videos really broke out (baseline-normalized, from Phase 1)
  - What Analytics can explain (traffic sources, from Phase 1/2)

So this layer tackles the *residual* variance: for the performance that
Analytics can't account for, what external cultural context was plausibly
at play? Gemini speculates with an explicit confidence level + reasoning.
Optionally wire Google Trends for high-value terms Gemini identifies.

Downstream apps MUST treat tailwind claims as hypotheses, not facts — the
schema enforces that with a confidence field.

See game_plan.md → Layer 5.
"""
