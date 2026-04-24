"""Per-phase `_meta` stamping for reruns.

Every phase that produces records stamps a small `_meta` block onto what
it writes:

    _meta: {
      model: str | None,    # Gemini model used (None for non-Gemini output)
      schema_version: int,  # the phase's own schema version
      prompt_hash: str | None,  # hash of the prompt FUNCTION SOURCE
      ran_at: str,          # ISO timestamp
    }

The orchestrator never acts on this block automatically. It's there so a
rerun endpoint can ask predicate questions ("which records ran on a
different model than the current default?") when the operator decides
to.

Prompt hashing takes the function source, not the function output. Per-
video content differs across calls, so hashing output would give every
video a different hash. Hashing source gives one stable hash per prompt
version — which is the staleness signal we want.
"""

from __future__ import annotations

import hashlib
import inspect
from datetime import datetime
from typing import Callable, Optional


def prompt_source_hash(*sources: Callable | str) -> str:
    """Stable hash across 1-N prompt inputs (functions or raw strings).

    Pass the prompt-building function plus anything else that materially
    shapes the prompt (e.g. `format_vocabulary` for Phase 2, so tag
    vocabulary edits flip the hash). Short-hex output so it's readable
    in the JSON.
    """
    h = hashlib.sha256()
    for src in sources:
        text = src if isinstance(src, str) else inspect.getsource(src)
        h.update(text.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def build_meta(
    *,
    model: Optional[str],
    schema_version: int,
    prompt_hash: Optional[str],
    ran_at: Optional[str] = None,
) -> dict:
    return {
        "model": model,
        "schema_version": schema_version,
        "prompt_hash": prompt_hash,
        "ran_at": ran_at or datetime.now().isoformat(),
    }


def backfill_analysis_meta(data: dict, current_schema: int) -> bool:
    """Stamp `_meta` onto gemini_analysis blocks that don't have one.

    Records written before stamping went live have `analysis_timestamp`
    at the record root; we reuse that as `ran_at`. `model` and
    `prompt_hash` are left null so downstream predicate checks can
    distinguish "unknown legacy" from "stamped with an older value" —
    legacy records are intentionally NOT flagged as mismatches.

    Returns True if anything was changed, so callers can decide to save.
    """
    touched = False
    for entry in data.get("shorts", []):
        analysis = entry.get("gemini_analysis")
        if not isinstance(analysis, dict):
            continue
        if isinstance(analysis.get("_meta"), dict):
            continue
        analysis["_meta"] = build_meta(
            model=None,
            schema_version=current_schema,
            prompt_hash=None,
            ran_at=entry.get("analysis_timestamp"),
        )
        touched = True
    return touched


def backfill_tailwind_meta(tailwind_data: dict, current_schema: int) -> bool:
    """Same treatment for tailwind blocks produced before stamping went live.

    Tailwind output lives in a separate file with shape
    {"videos": {video_id: {tailwind: {...}, ...}}}. We walk each
    video's tailwind sub-dict and stamp a legacy `_meta` when missing.
    """
    touched = False
    for entry in (tailwind_data.get("videos") or {}).values():
        tw = entry.get("tailwind")
        if not isinstance(tw, dict):
            continue
        if isinstance(tw.get("_meta"), dict):
            continue
        tw["_meta"] = build_meta(
            model=None,
            schema_version=current_schema,
            prompt_hash=None,
            ran_at=tailwind_data.get("metadata", {}).get("generated_at"),
        )
        touched = True
    return touched
