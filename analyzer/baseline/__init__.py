"""
Channel baseline + context — [Phase 1, not yet implemented]

Responsibilities when built:
  - Build `channel_context.json`: per-month channel medians, so any single
    video can be scored against its own era rather than against today.
  - Compute per-video "breakout score" = views ÷ channel median at publish.
  - Stitch together Data API stats + Analytics retention/traffic data into
    a single per-video enrichment dict the prompt can consume.

Output feeds into:
  - analyzer.gemini.prompts (Phase 2) — so analysis is evidence-grounded
  - analyzer.synthesis (Phase 4) — for quintile splits

See game_plan.md → Layer 1.
"""
