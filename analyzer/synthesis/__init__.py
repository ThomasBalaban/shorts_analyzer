"""
Channel-level pattern synthesis — [Phase 4, not yet implemented]

Responsibilities when built:
  - Aggregate tag frequencies across the whole corpus (once Phase 3 has
    populated tags on every record).
  - Quintile splits by breakout score: what tags appear in top 20% vs
    bottom 20% vs channel-average.
  - "Unique to breakouts" extraction — tags significantly overrepresented
    in the top quintile.
  - Conditional pattern detection — when tag A is present, does tag B
    correlate with higher breakout score?
  - Gemini-written narrative layer that reads the stats and explains the
    patterns in prose for downstream-app consumption.

Writes `data/synthesis/channel_synthesis.json` — the file that downstream
title/edit-advice apps load FIRST for strategy before drilling into
individual records for examples.

See game_plan.md → Layer 4.
"""
