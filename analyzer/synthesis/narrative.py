"""Gemini-written narrative layer over the stats block.

Reads the numeric tables built by `analyzer.synthesis.stats` and asks
Gemini to explain what the patterns mean in prose that a downstream
title/edit-advice model can paste verbatim into a system prompt.

The output is structured JSON (not free-form prose) so downstream
consumers don't have to parse markdown. Five fields:

  - top_quintile_signature:  what breakouts look like
  - bottom_quintile_signature:  what misses look like
  - load_bearing_patterns:  tags that are plausibly causal for breakouts
  - conditional_insights:  "when X, also do Y" observations
  - cautions:  shared-baseline traits and what NOT to read as causal

Uses MODEL_PRO at thinking_level="low" — text-only synthesis doesn't
need the high-thinking budget the per-video video analysis uses, but
Pro's judgment on what's load-bearing vs. noise is worth paying for.
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from google.genai import types  # type: ignore

from analyzer.core.models import (
    MODEL_PRO,
    get_gemini_client,
    get_safety_settings,
)


_NARRATIVE_SCHEMA = types.Schema(
    type="OBJECT",
    properties={
        "top_quintile_signature": types.Schema(
            type="STRING",
            description=(
                "What the top-quintile breakouts have in common, written as "
                "dense prose for a downstream title/edit-advice model. "
                "Cite specific tags and their lift numbers. Distinguish "
                "tags that look causal from tags that are just common "
                "channel traits. 4-7 sentences."
            ),
        ),
        "bottom_quintile_signature": types.Schema(
            type="STRING",
            description=(
                "What the bottom-quintile misses have in common, or what's "
                "missing from them vs. the breakouts. Cite tags. Do not "
                "moralize — describe the pattern. 3-5 sentences."
            ),
        ),
        "load_bearing_patterns": types.Schema(
            type="STRING",
            description=(
                "The tags that are overrepresented in breakouts AND absent "
                "or rare in misses — the patterns most plausibly causal "
                "rather than correlational. Reference specific lift values "
                "and sample sizes. If the corpus is too small for confident "
                "claims, say so. 4-6 sentences."
            ),
        ),
        "conditional_insights": types.Schema(
            type="STRING",
            description=(
                "'When tag A is present, tag B correlates with higher "
                "breakout score' observations. Pick the 2-4 strongest "
                "pairings from the conditional_patterns table and explain "
                "what they mean in editorial terms. If none of the "
                "conditional patterns are strong enough, say so explicitly. "
                "3-5 sentences."
            ),
        ),
        "cautions": types.Schema(
            type="STRING",
            description=(
                "Tags that look like channel defaults (common in BOTH top "
                "and bottom quintile) — a downstream model should NOT read "
                "these as causal signals. Also flag any pattern that looks "
                "suspicious (e.g. too small a sample, confounds with "
                "publish date). 3-5 sentences."
            ),
        ),
    },
    required=[
        "top_quintile_signature",
        "bottom_quintile_signature",
        "load_bearing_patterns",
        "conditional_insights",
        "cautions",
    ],
)


# Cap the payload we send to Gemini so the prompt stays tight. The
# per-axis frequency table is the bulky part; trimming to the top
# couple tags per axis keeps the narrative focused on what moves the
# needle. The raw table is still written to the synthesis.json on disk,
# so nothing is lost — we just don't pay tokens to re-narrate zeros.
def _compact_frequency_table(
    frequency_table: dict[str, dict[str, dict]],
    per_axis_top_n: int = 6,
) -> dict[str, list[dict]]:
    compact: dict[str, list[dict]] = {}
    for axis_field, axis_block in frequency_table.items():
        rows = []
        for tag_id, cell in axis_block.items():
            if cell["overall"]["count"] == 0:
                continue
            rows.append({
                "tag": tag_id,
                "n_overall": cell["overall"]["count"],
                "rate_overall": cell["overall"]["rate"],
                "rate_top": cell["top_quintile"]["rate"],
                "rate_bottom": cell["bottom_quintile"]["rate"],
                "lift_top": cell["lift_top_vs_overall"],
                "avg_breakout_when_present":
                    cell["avg_breakout_score_when_present"],
            })
        rows.sort(
            key=lambda r: (r["n_overall"], r["lift_top"] or 0.0),
            reverse=True,
        )
        compact[axis_field] = rows[:per_axis_top_n]
    return compact


def _build_prompt(stats: dict) -> str:
    corpus = stats["corpus_stats"]
    quintiles = stats["quintiles"]

    compact_freq = _compact_frequency_table(stats["tag_frequencies"])

    payload = {
        "corpus": corpus,
        "quintile_thresholds": {
            "top_breakout_score_min": quintiles["top_threshold"],
            "bottom_breakout_score_max": quintiles["bottom_threshold"],
            "n_top": quintiles["n_top"],
            "n_bottom": quintiles["n_bottom"],
        },
        "unique_to_breakouts": stats["unique_to_breakouts"],
        "absent_from_breakouts": stats["absent_from_breakouts"],
        "shared_baseline_traits": stats["shared_baseline_traits"],
        "conditional_patterns": stats["conditional_patterns"],
        "tag_frequencies_compact": compact_freq,
    }
    data_block = json.dumps(payload, indent=2)

    return f"""You are writing the channel-level strategy layer for a YouTube Shorts analysis corpus. This file gets pasted into the system prompt of downstream apps that recommend titles and guide edits. Your prose becomes those apps' working knowledge of what makes this specific channel's shorts break out.

Below is the numeric evidence: corpus stats, tag frequency tables split by performance quintile, "unique to breakouts" lift rankings, "absent from breakouts" gaps, shared-baseline traits, and conditional patterns. Every claim you make must cite specific tags and specific numbers from this data.

Breakout score = views ÷ channel median at publish month. 1.0 = a median short. 5.0 = a 5x-over-median outlier. Higher = bigger breakout. Top quintile = top 20% by breakout score.

Rules:
  - Cite tag IDs verbatim, not paraphrased (e.g. `smash_cut_to_reference`, not "smash cuts").
  - Include lift values and sample sizes in your claims where relevant (e.g. "lift 2.3 over channel average, n=4 of 6 top-quintile shorts").
  - A tag in `shared_baseline_traits` is a channel default — flag it as such and do NOT call it causal.
  - If the corpus is too small for confident quintile claims (n < ~20), say so plainly in `cautions` rather than overclaiming.
  - Do not invent tags. Only use tags that appear in the data below.
  - Be specific and editorial. "Breakouts over-index on X" beats "breakouts are generally X-ish."
  - Respond strictly in the required JSON schema. No markdown fences.

DATA:
{data_block}
"""


def write_narrative(
    stats: dict,
    log_func: Optional[Callable[[str], None]] = None,
) -> dict:
    """Run Gemini over the stats block and return the narrative dict.

    On parse failure, returns a shell with an `_error` flag so the
    caller can still emit a useful synthesis file containing the
    statistics, even if the prose layer fell over.
    """
    log = log_func or print
    client = get_gemini_client()
    prompt = _build_prompt(stats)

    log("  Calling Gemini for narrative synthesis...")
    response = client.models.generate_content(
        model=MODEL_PRO,
        contents=prompt,
        config=types.GenerateContentConfig(
            safety_settings=get_safety_settings(),
            thinking_config=types.ThinkingConfig(thinking_level="low"),
            response_mime_type="application/json",
            response_schema=_NARRATIVE_SCHEMA,
        ),
    )

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict) and parsed:
        return parsed

    raw = (response.text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError as e:
        log(f"  ⚠️  Failed to parse narrative JSON: {e}")
        log(f"  Raw response (first 500 chars): {raw[:500]}")

    return {
        "top_quintile_signature": "",
        "bottom_quintile_signature": "",
        "load_bearing_patterns": "",
        "conditional_insights": "",
        "cautions": "",
        "_parse_error": True,
        "_raw_response": raw,
    }
