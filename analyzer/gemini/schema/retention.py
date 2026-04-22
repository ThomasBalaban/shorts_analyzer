"""Retention-interpretation schema.

Forces Gemini to explicitly describe what the retention curve shows. This
is the check against hand-wavy prose: if the hook is claimed strong but
retention collapses in the first 2 seconds, the two fields will contradict
and the contradiction is visible to a reader (and to Phase 4 synthesis).

The YouTube Analytics API returns ~20 data points (one per ~5% of length)
with `watch_ratio` — the fraction of the starting audience still watching
at that point. Values can exceed 1.0 when viewers loop/rewatch.
"""

from __future__ import annotations

from google.genai import types  # type: ignore


RETENTION_SCHEMA = types.Schema(
    type="OBJECT",
    description=(
        "Interpret the retention curve provided in the prompt. If no "
        "retention data was provided (null), write 'no retention data "
        "available' in each field."
    ),
    properties={
        "opening_drop_off": types.Schema(
            type="STRING",
            description=(
                "0-20% of video: how steep is the drop, does the hook hold? "
                "Cite specific watch_ratio values if they tell a story."
            ),
        ),
        "mid_video": types.Schema(
            type="STRING",
            description=(
                "20-80%: flat plateau, secondary dips, rewatch spikes? "
                "Call out any moment where watch_ratio jumps up."
            ),
        ),
        "end_behavior": types.Schema(
            type="STRING",
            description=(
                "80-100%: retention spike (rewatch) or tail off? "
                "If values exceed 1.0, note that viewers are looping."
            ),
        ),
        "avg_view_percentage_read": types.Schema(
            type="STRING",
            description=(
                "One-sentence read of the avg_view_percentage number itself. "
                ">100% indicates loop/rewatch; ~50% is typical for shorts."
            ),
        ),
    },
    required=[
        "opening_drop_off",
        "mid_video",
        "end_behavior",
        "avg_view_percentage_read",
    ],
)
