"""Pure-function statistics for channel-level tag pattern extraction.

Takes a list of analyzed shorts (the `shorts` array from the main output
JSON) and produces the numeric tables that Phase 4's narrative layer
reads on top of. No Gemini calls here — keep the math auditable.

Quintiles are computed on `breakout_score` (views ÷ channel median at
publish month, from Phase 1). A video missing a breakout_score is
excluded from quintile splits but still counted in overall frequencies.

Lift = rate_in_subset / rate_overall. A lift of 1.0 means the tag is
just as common in the subset as in the corpus; > 1.5 means
overrepresented, < 0.5 means underrepresented. We require a minimum
`n` in the subset before trusting the number — otherwise any tag that
happens to appear in a single breakout looks decisive.
"""

from __future__ import annotations

import statistics
from typing import Iterable, Iterator

from analyzer.tags.vocabulary import ALL_AXES


# Don't surface a "unique to breakouts" claim unless the tag appears in
# at least this many top-quintile records. One hit is noise.
MIN_N_FOR_LIFT = 2

# Conditional-pattern pairs are expensive to scan and most are noise.
# Only consider a "base" tag once it's present in at least this many
# records channel-wide.
MIN_N_FOR_CONDITIONAL_BASE = 3


# ─── Record iteration ─────────────────────────────────────────────────────

def _iter_tags(short: dict) -> Iterator[tuple[str, str]]:
    """Yield (axis_field, tag_id) for every tag present on a short.

    Handles both multi-tag axes (list of strings) and single-tag axes
    (a single string). Skips records that don't have tags (e.g. parse
    failures from older schema versions).
    """
    tags = short.get("gemini_analysis", {}).get("tags") or {}
    for axis in ALL_AXES:
        val = tags.get(axis.field)
        if val is None:
            continue
        if axis.multi:
            if isinstance(val, list):
                for tag_id in val:
                    if isinstance(tag_id, str) and tag_id:
                        yield axis.field, tag_id
        else:
            if isinstance(val, str) and val:
                yield axis.field, val


def _tag_set(short: dict) -> set[tuple[str, str]]:
    return set(_iter_tags(short))


# ─── Quintile split ───────────────────────────────────────────────────────

def _split_quintiles(shorts: list[dict]) -> tuple[list[dict], list[dict], float, float]:
    """Return (top_quintile, bottom_quintile, top_threshold, bottom_threshold).

    Top/bottom quintile = top/bottom 20% of records sorted by
    breakout_score. Videos without a breakout_score are dropped from
    both splits (they can't be compared). With < 5 records we can't
    carve clean quintiles — caller should treat the outputs as
    exploratory rather than authoritative.
    """
    scored = [s for s in shorts if isinstance(s.get("breakout_score"), (int, float))]
    if not scored:
        return [], [], 0.0, 0.0

    scored.sort(key=lambda s: s["breakout_score"], reverse=True)
    n = len(scored)
    q = max(1, n // 5)
    top = scored[:q]
    bottom = scored[-q:]
    top_threshold = top[-1]["breakout_score"]
    bottom_threshold = bottom[0]["breakout_score"]
    return top, bottom, top_threshold, bottom_threshold


# ─── Tag-frequency tables ─────────────────────────────────────────────────

def _tag_counts(shorts: list[dict]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for s in shorts:
        for key in _tag_set(s):
            counts[key] = counts.get(key, 0) + 1
    return counts


def _avg_breakout_when_present(
    shorts: list[dict],
    axis: str,
    tag: str,
) -> float | None:
    """Mean breakout_score across shorts where this tag is present."""
    scores = [
        s["breakout_score"]
        for s in shorts
        if (axis, tag) in _tag_set(s)
        and isinstance(s.get("breakout_score"), (int, float))
    ]
    if not scores:
        return None
    return round(statistics.mean(scores), 3)


def _build_frequency_table(
    overall: list[dict],
    top: list[dict],
    bottom: list[dict],
) -> dict[str, dict[str, dict]]:
    """Per-axis, per-tag frequency block.

    Shape: {axis: {tag: {overall: {count, rate}, top_quintile: {...},
    bottom_quintile: {...}, lift_top_vs_overall, lift_bottom_vs_overall,
    avg_breakout_score_when_present}}}

    Every tag in the vocabulary is emitted even if count = 0, so
    downstream consumers can distinguish "not scored" from "scored zero"
    without schema drift.
    """
    overall_counts = _tag_counts(overall)
    top_counts = _tag_counts(top)
    bottom_counts = _tag_counts(bottom)

    n_overall = len(overall) or 1
    n_top = len(top) or 1
    n_bottom = len(bottom) or 1

    table: dict[str, dict[str, dict]] = {}
    for axis in ALL_AXES:
        axis_block: dict[str, dict] = {}
        for tag in axis.tags:
            key = (axis.field, tag.id)
            c_overall = overall_counts.get(key, 0)
            c_top = top_counts.get(key, 0)
            c_bottom = bottom_counts.get(key, 0)

            rate_overall = c_overall / n_overall
            rate_top = c_top / n_top
            rate_bottom = c_bottom / n_bottom

            lift_top = rate_top / rate_overall if rate_overall > 0 else None
            lift_bottom = rate_bottom / rate_overall if rate_overall > 0 else None

            axis_block[tag.id] = {
                "overall": {"count": c_overall, "rate": round(rate_overall, 3)},
                "top_quintile": {"count": c_top, "rate": round(rate_top, 3)},
                "bottom_quintile": {
                    "count": c_bottom, "rate": round(rate_bottom, 3)},
                "lift_top_vs_overall": (
                    round(lift_top, 3) if lift_top is not None else None),
                "lift_bottom_vs_overall": (
                    round(lift_bottom, 3) if lift_bottom is not None else None),
                "avg_breakout_score_when_present":
                    _avg_breakout_when_present(overall, axis.field, tag.id),
            }
        table[axis.field] = axis_block
    return table


# ─── Rankings: "unique to breakouts" / "absent from breakouts" ────────────

def _rank_unique_to_breakouts(
    frequency_table: dict[str, dict[str, dict]],
    top_n: int = 20,
) -> list[dict]:
    """Tags overrepresented in the top quintile vs the corpus baseline.

    Sort by lift descending. Requires MIN_N_FOR_LIFT hits in the top
    quintile so a single-video coincidence can't top the list. Ties
    broken by absolute top-quintile rate (more common wins).
    """
    rows: list[dict] = []
    for axis_field, axis_block in frequency_table.items():
        for tag_id, cell in axis_block.items():
            n_top = cell["top_quintile"]["count"]
            lift = cell["lift_top_vs_overall"]
            if lift is None or lift <= 1.0:
                continue
            if n_top < MIN_N_FOR_LIFT:
                continue
            rows.append({
                "axis": axis_field,
                "tag": tag_id,
                "lift": lift,
                "top_rate": cell["top_quintile"]["rate"],
                "overall_rate": cell["overall"]["rate"],
                "n_in_top": n_top,
                "n_overall": cell["overall"]["count"],
                "avg_breakout_when_present":
                    cell["avg_breakout_score_when_present"],
            })
    rows.sort(key=lambda r: (r["lift"], r["top_rate"]), reverse=True)
    return rows[:top_n]


def _rank_absent_from_breakouts(
    frequency_table: dict[str, dict[str, dict]],
    top_n: int = 15,
) -> list[dict]:
    """Tags that show up channel-wide but are missing from breakouts.

    Requires an overall rate ≥ 15% (otherwise "never in the top"
    just means "rare everywhere"). Sorted by overall rate desc —
    most conspicuously absent tags first.
    """
    rows: list[dict] = []
    for axis_field, axis_block in frequency_table.items():
        for tag_id, cell in axis_block.items():
            if cell["top_quintile"]["count"] > 0:
                continue
            if cell["overall"]["rate"] < 0.15:
                continue
            rows.append({
                "axis": axis_field,
                "tag": tag_id,
                "overall_rate": cell["overall"]["rate"],
                "n_overall": cell["overall"]["count"],
                "avg_breakout_when_present":
                    cell["avg_breakout_score_when_present"],
            })
    rows.sort(key=lambda r: r["overall_rate"], reverse=True)
    return rows[:top_n]


def _rank_shared_baseline(
    frequency_table: dict[str, dict[str, dict]],
    top_n: int = 15,
) -> list[dict]:
    """Tags common in both top AND bottom quintile — channel defaults.

    These are the "this is just how this channel makes shorts" tags.
    Useful to flag so downstream AIs don't misread them as causal.
    Criterion: present in ≥ 50% of both top and bottom quintile.
    """
    rows: list[dict] = []
    for axis_field, axis_block in frequency_table.items():
        for tag_id, cell in axis_block.items():
            top_rate = cell["top_quintile"]["rate"]
            bottom_rate = cell["bottom_quintile"]["rate"]
            if top_rate < 0.5 or bottom_rate < 0.5:
                continue
            rows.append({
                "axis": axis_field,
                "tag": tag_id,
                "top_rate": top_rate,
                "bottom_rate": bottom_rate,
                "overall_rate": cell["overall"]["rate"],
            })
    rows.sort(key=lambda r: r["overall_rate"], reverse=True)
    return rows[:top_n]


# ─── Conditional patterns ────────────────────────────────────────────────

def _rank_conditional_patterns(
    shorts: list[dict],
    frequency_table: dict[str, dict[str, dict]],
    top_n: int = 15,
) -> list[dict]:
    """"When tag A is present, tag B correlates with Nx higher score."

    For every pair (A, B) where A is present in ≥ MIN_N_FOR_CONDITIONAL_BASE
    records, compare mean breakout score among records with A alone
    vs records with A and B. Keep pairs where the A+B mean is
    meaningfully higher AND both subsets have ≥ 2 records.
    """
    # Pre-index tag sets per record so we don't recompute per pair
    indexed = [
        (s.get("breakout_score"), _tag_set(s))
        for s in shorts
        if isinstance(s.get("breakout_score"), (int, float))
    ]

    # Collect candidate "A" tags — any tag with enough population to
    # split further. Reading from the frequency table keeps this pass
    # O(tags) rather than O(records × tags).
    candidate_a: list[tuple[str, str]] = []
    for axis_field, axis_block in frequency_table.items():
        for tag_id, cell in axis_block.items():
            if cell["overall"]["count"] >= MIN_N_FOR_CONDITIONAL_BASE:
                candidate_a.append((axis_field, tag_id))

    rows: list[dict] = []
    for a in candidate_a:
        with_a = [(bs, tags) for bs, tags in indexed if a in tags]
        if len(with_a) < MIN_N_FOR_CONDITIONAL_BASE:
            continue
        mean_a = statistics.mean(bs for bs, _ in with_a)

        # Pair A with every other present tag
        other_tags: dict[tuple[str, str], int] = {}
        for _, tags in with_a:
            for t in tags:
                if t == a:
                    continue
                other_tags[t] = other_tags.get(t, 0) + 1

        for b, count_b in other_tags.items():
            if count_b < 2:
                continue
            with_ab = [(bs, tags) for bs, tags in with_a if b in tags]
            with_a_only = [(bs, tags) for bs, tags in with_a if b not in tags]
            if len(with_a_only) < 2 or len(with_ab) < 2:
                continue
            mean_ab = statistics.mean(bs for bs, _ in with_ab)
            mean_a_only = statistics.mean(bs for bs, _ in with_a_only)

            if mean_a_only <= 0:
                continue
            lift = mean_ab / mean_a_only
            if lift < 1.25:
                continue

            rows.append({
                "when": {"axis": a[0], "tag": a[1]},
                "with": {"axis": b[0], "tag": b[1]},
                "mean_breakout_when_A": round(mean_a, 3),
                "mean_breakout_when_A_and_B": round(mean_ab, 3),
                "mean_breakout_when_A_not_B": round(mean_a_only, 3),
                "lift_B_given_A": round(lift, 3),
                "n_A": len(with_a),
                "n_A_and_B": len(with_ab),
                "n_A_not_B": len(with_a_only),
            })

    # De-duplicate symmetric pairs (A→B and B→A often both show up):
    # keep whichever direction has more samples under A.
    seen: dict[frozenset, dict] = {}
    for row in rows:
        key = frozenset([
            (row["when"]["axis"], row["when"]["tag"]),
            (row["with"]["axis"], row["with"]["tag"]),
        ])
        current = seen.get(key)
        if current is None or row["n_A"] > current["n_A"]:
            seen[key] = row
    deduped = list(seen.values())

    deduped.sort(key=lambda r: (r["lift_B_given_A"], r["n_A_and_B"]), reverse=True)
    return deduped[:top_n]


# ─── Corpus-level summary stats ───────────────────────────────────────────

def _corpus_stats(shorts: list[dict]) -> dict:
    scores = [
        s["breakout_score"] for s in shorts
        if isinstance(s.get("breakout_score"), (int, float))
    ]
    views = [s["views"] for s in shorts if isinstance(s.get("views"), int)]

    def _summary(xs: list[float]) -> dict:
        if not xs:
            return {"n": 0, "min": None, "max": None,
                    "mean": None, "median": None}
        return {
            "n": len(xs),
            "min": round(min(xs), 3),
            "max": round(max(xs), 3),
            "mean": round(statistics.mean(xs), 3),
            "median": round(statistics.median(xs), 3),
        }

    return {
        "total_shorts": len(shorts),
        "breakout_score": _summary(scores),
        "views": _summary([float(v) for v in views]),
    }


# ─── Public entry point ──────────────────────────────────────────────────

def compute_stats(shorts: list[dict]) -> dict:
    """Build the full stats block from a list of analyzed shorts.

    The dict returned here is both (a) the math underpinning the
    narrative layer and (b) a queryable artifact in its own right —
    downstream apps can skip the prose and read the numbers directly.
    """
    top, bottom, top_thresh, bottom_thresh = _split_quintiles(shorts)
    frequency_table = _build_frequency_table(shorts, top, bottom)

    return {
        "corpus_stats": _corpus_stats(shorts),
        "quintiles": {
            "top_threshold": round(top_thresh, 3),
            "bottom_threshold": round(bottom_thresh, 3),
            "n_top": len(top),
            "n_bottom": len(bottom),
            "top_video_ids": [s["video_id"] for s in top],
            "bottom_video_ids": [s["video_id"] for s in bottom],
        },
        "tag_frequencies": frequency_table,
        "unique_to_breakouts": _rank_unique_to_breakouts(frequency_table),
        "absent_from_breakouts": _rank_absent_from_breakouts(frequency_table),
        "shared_baseline_traits": _rank_shared_baseline(frequency_table),
        "conditional_patterns": _rank_conditional_patterns(
            shorts, frequency_table),
    }
