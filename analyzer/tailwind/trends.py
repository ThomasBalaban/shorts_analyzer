"""Optional Google Trends validator for tailwind hypotheses.

The game plan calls Trends integration optional — and for good reason:
`pytrends` is an unofficial scraper that Google rate-limits
aggressively, its responses shift without warning, and its error
surface is broad (captchas, 429s, empty frames). We keep the wiring
clean but opt-in, and we degrade loudly rather than silently when it
fails.

Enable by passing `--use-trends` on the CLI. If pytrends is not
installed, the orchestrator logs that Trends was requested but
skipped, and continues — we never let Trends failure take the whole
run down.

What we do with Trends data: for each hypothesis's window and
search_terms, check whether interest-over-time for the terms showed
measurable activity inside the window. We attach the numeric signal
to the hypothesis as `trends_signal` — a dict the downstream app can
use to weight confidence. We do NOT rewrite Gemini's confidence
field: Trends evidence is for the human reader and downstream models
to reason about, not for this layer to auto-grade.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Callable, Optional


# pytrends default frontend used to throttle around 5-10 req/min; pad
# between calls to stay comfortably below whatever the current limit is.
_PYTRENDS_THROTTLE_SEC = 3.0


def trends_available() -> bool:
    """True if pytrends is importable. Safe to call from hot paths."""
    try:
        import pytrends  # noqa: F401
        return True
    except ImportError:
        return False


def _widen_window(start: str, end: str, pad_days: int = 30) -> tuple[str, str]:
    """Pad a hypothesis window so Trends has baseline on either side.

    A cultural moment that lasted a week will look flat if we query
    exactly that week (no ramp-up, no decay to compare against).
    """
    try:
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")
    except (TypeError, ValueError):
        return start, end
    s2 = (s - timedelta(days=pad_days)).strftime("%Y-%m-%d")
    e2 = (e + timedelta(days=pad_days)).strftime("%Y-%m-%d")
    return s2, e2


def check_hypothesis(
    search_terms: list[str],
    window_start: str,
    window_end: str,
    log_func: Optional[Callable[[str], None]] = None,
) -> Optional[dict]:
    """Fetch Google Trends interest-over-time for a hypothesis.

    Returns a dict:
      {
        "queried_terms": [...],
        "timeframe": "YYYY-MM-DD YYYY-MM-DD",
        "peak_interest": int (0-100, Trends' relative scale),
        "peak_date": "YYYY-MM-DD",
        "avg_interest_in_window": float,
        "avg_interest_outside_window": float,
        "verdict": "supported" | "ambiguous" | "contradicted",
      }

    Returns None on any failure (network, rate limit, empty payload).
    Callers should treat None as "no Trends evidence" — never as
    evidence against the hypothesis.
    """
    log = log_func or print

    try:
        from pytrends.request import TrendReq  # type: ignore
    except ImportError:
        log("  pytrends not installed — skipping Trends validation")
        return None

    if not search_terms:
        return None

    padded_start, padded_end = _widen_window(window_start, window_end)
    timeframe = f"{padded_start} {padded_end}"
    terms = search_terms[:5]  # pytrends caps at 5 keywords per batch

    try:
        pytrends = TrendReq(hl="en-US", tz=0, retries=1, backoff_factor=0.5)
        pytrends.build_payload(terms, timeframe=timeframe)
        df = pytrends.interest_over_time()
        time.sleep(_PYTRENDS_THROTTLE_SEC)
    except Exception as e:
        log(f"  Trends query failed ({type(e).__name__}): {e}")
        return None

    if df is None or df.empty:
        return None

    # Drop the 'isPartial' column pytrends sometimes adds
    if "isPartial" in df.columns:
        df = df.drop(columns=["isPartial"])

    # Max across any of the queried terms at each date — hypothesis is
    # "any of these terms was hot in this window," not "all of them."
    series = df.max(axis=1)
    if series.empty:
        return None

    peak_val = int(series.max())
    peak_ts = series.idxmax()
    peak_date = peak_ts.strftime("%Y-%m-%d") if peak_ts is not None else None

    # Split series into "inside the claimed window" and "outside" to
    # see whether interest was actually elevated when the hypothesis
    # claims it was.
    try:
        win_start = datetime.strptime(window_start, "%Y-%m-%d")
        win_end = datetime.strptime(window_end, "%Y-%m-%d")
        inside = series[(series.index >= win_start) & (series.index <= win_end)]
        outside = series[(series.index < win_start) | (series.index > win_end)]
        avg_in = float(inside.mean()) if not inside.empty else 0.0
        avg_out = float(outside.mean()) if not outside.empty else 0.0
    except ValueError:
        avg_in = float(series.mean())
        avg_out = 0.0

    if avg_out == 0 and avg_in == 0:
        verdict = "ambiguous"
    elif avg_in >= max(1.5 * avg_out, avg_out + 10):
        verdict = "supported"
    elif avg_in < avg_out * 0.7:
        verdict = "contradicted"
    else:
        verdict = "ambiguous"

    return {
        "queried_terms": terms,
        "timeframe": timeframe,
        "peak_interest": peak_val,
        "peak_date": peak_date,
        "avg_interest_in_window": round(avg_in, 2),
        "avg_interest_outside_window": round(avg_out, 2),
        "verdict": verdict,
    }


def enrich_hypotheses(
    hypotheses: list[dict],
    log_func: Optional[Callable[[str], None]] = None,
) -> list[dict]:
    """Attach a `trends_signal` dict to each hypothesis in place.

    Mutates the input list (returns it too for chain-call convenience).
    Missing terms or Trends failures result in `trends_signal = None`.
    """
    log = log_func or print
    for i, h in enumerate(hypotheses, 1):
        terms = h.get("search_terms") or []
        log(
            f"  Trends [{i}/{len(hypotheses)}]: "
            f"{', '.join(terms[:3]) or '(no terms)'}"
        )
        signal = check_hypothesis(
            terms,
            h.get("window_start", ""),
            h.get("window_end", ""),
            log_func=log,
        )
        h["trends_signal"] = signal
    return hypotheses
