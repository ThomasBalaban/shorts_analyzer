"""
YouTube Analytics API wrapper — [Phase 1, not yet implemented]

This module will handle the OAuth'd half of the YouTube API, which gives us
private performance data for the channel owner. Data API (other module)
works with an API key; Analytics API needs OAuth because the data is private.

Planned responsibilities:
  - OAuth flow (client_secrets.json → token.json, refresh automatically)
  - Per-video retention curves (second-by-second % of viewers retained)
  - Traffic source breakdown (shorts feed, subscribers, browse, external, search)
  - Impressions + CTR where available
  - Channel-wide baseline stats, computed PER MONTH so videos are
    normalized against the channel at time of publish — not today.

The output of this module feeds into:
  - analyzer/baseline/ — which stores channel_context.json
  - analyzer/gemini/prompts.py — so Gemini's analysis is evidence-grounded
  - analyzer/synthesis/ — for quintile splits by breakout score

See game_plan.md → "Layer 1 — Ground truth from Analytics" for the full spec.
"""

# TODO(phase-1): OAuth flow
# TODO(phase-1): retention curve fetch
# TODO(phase-1): traffic source breakdown
# TODO(phase-1): impressions + CTR
# TODO(phase-1): monthly channel baselines
