"""Text-only Gemini call producing a tailwind hypothesis block.

Re-uses the same client setup as the per-video and narrative calls.
Thinking level is "low" because the reasoning here is bounded: given
the residual estimate and the prior attribution, propose dated
hypotheses — not the full editor's breakdown.
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
from analyzer.tailwind.prompts import build_tailwind_prompt
from analyzer.tailwind.schema import TAILWIND_SCHEMA


def analyze_tailwind(
    short: dict,
    residual: dict,
    log_func: Optional[Callable[[str], None]] = None,
) -> dict:
    """Return a tailwind dict matching TAILWIND_SCHEMA for one short.

    On parse failure returns a shell with `_parse_error = True` so the
    orchestrator can still persist something and keep going.
    """
    log = log_func or print
    client = get_gemini_client()
    prompt = build_tailwind_prompt(short, residual)

    response = client.models.generate_content(
        model=MODEL_PRO,
        contents=prompt,
        config=types.GenerateContentConfig(
            safety_settings=get_safety_settings(),
            thinking_config=types.ThinkingConfig(thinking_level="low"),
            response_mime_type="application/json",
            response_schema=TAILWIND_SCHEMA,
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
        log(f"  ⚠️  Tailwind JSON parse failed: {e}")
        log(f"  Raw response (first 500 chars): {raw[:500]}")

    return {
        "residual_summary": "",
        "hypotheses": [],
        "overall_confidence": "low",
        "_parse_error": True,
        "_raw_response": raw,
    }
