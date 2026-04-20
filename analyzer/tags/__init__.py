"""
Controlled-vocabulary tag system — [Phase 3, not yet implemented]

Responsibilities when built:
  - Define the controlled vocabularies (title mechanics, hook types,
    pivot/payoff techniques, audio strategies). These live as Python enums
    / literal string tuples and get baked into the Gemini schema so the
    model cannot freelance tags.
  - Retro-tagger: walk existing analyzed shorts and add tag fields in a
    single batch pass, so the corpus is uniform.
  - Query helpers: find-by-tag, tag-frequency, tag-cooccurrence counts.

Vocabulary design happens BEFORE code — per game_plan.md, enumerate the
vocabulary by hand from ~20 already-analyzed shorts first.

See game_plan.md → Layer 3.
"""
