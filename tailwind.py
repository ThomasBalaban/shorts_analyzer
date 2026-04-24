"""Phase 5 CLI — build `<handle>.tailwind.json` from an analysis file.

Usage:
    python tailwind.py                                        # default analysis file
    python tailwind.py --analysis output/PeepingOtter.json
    python tailwind.py --analysis output/PeepingOtter.json --all
    python tailwind.py --analysis output/PeepingOtter.json --use-trends
    python tailwind.py --analysis output/PeepingOtter.json --min-breakout 2.0

Tailwind analysis is scoped to the *residual* performance that retention
can't explain — by default only shorts with a breakout_score above
`--min-breakout` AND a residual_ratio above `--min-residual-ratio` are
sent to Gemini. Use `--all` to force tailwind analysis on every record.
"""

import argparse
import os
import sys

from analyzer.tailwind import run_tailwind_analysis
from analyzer.tailwind.residual import (
    DEFAULT_MIN_BREAKOUT,
    DEFAULT_MIN_RESIDUAL_RATIO,
)


DEFAULT_ANALYSIS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "output", "PeepingOtter.json",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build channel-level tailwind analysis from an "
        "analyzer output file.")
    parser.add_argument(
        "--analysis", "-a",
        default=DEFAULT_ANALYSIS,
        help=f"Path to the analyzer output JSON (default: {DEFAULT_ANALYSIS})",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help=(
            "Path to write the tailwind JSON. Defaults to "
            "<analysis_basename>.tailwind.json alongside the input."
        ),
    )
    parser.add_argument(
        "--min-breakout",
        type=float,
        default=DEFAULT_MIN_BREAKOUT,
        help=(
            "Minimum breakout_score to consider a short worth tailwind "
            f"analysis (default: {DEFAULT_MIN_BREAKOUT}). Ignored with --all."
        ),
    )
    parser.add_argument(
        "--min-residual-ratio",
        type=float,
        default=DEFAULT_MIN_RESIDUAL_RATIO,
        help=(
            "Minimum residual_ratio (breakout ÷ retention-quality factor) "
            f"to consider (default: {DEFAULT_MIN_RESIDUAL_RATIO}). "
            "Ignored with --all."
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Bypass residual cutoffs — run tailwind analysis on every "
            "short in the corpus. Costs more Gemini calls; use only "
            "when you need a complete tailwind record."
        ),
    )
    parser.add_argument(
        "--use-trends",
        action="store_true",
        help=(
            "Attach Google Trends interest-over-time to each hypothesis. "
            "Requires `pip install pytrends`. Network-bound and rate-"
            "limited; expect ~3s delay per hypothesis."
        ),
    )
    args = parser.parse_args()

    try:
        run_tailwind_analysis(
            analysis_file=args.analysis,
            output_file=args.output,
            min_breakout=args.min_breakout,
            min_residual_ratio=args.min_residual_ratio,
            include_all=args.all,
            use_trends=args.use_trends,
        )
        return 0
    except FileNotFoundError as e:
        print(f"\nError: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        return 130
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
