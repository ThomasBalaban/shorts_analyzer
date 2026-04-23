"""Phase 4 CLI — build `<handle>.synthesis.json` from an existing analysis file.

Usage:
    python synthesize.py                                   # default analysis file
    python synthesize.py --analysis output/PeepingOtter.json
    python synthesize.py --analysis output/PeepingOtter.json --output output/custom.json
    python synthesize.py --analysis output/PeepingOtter.json --skip-narrative

The synthesis module reads a per-video analysis JSON, computes tag-frequency
tables split by performance quintile, and writes a separate synthesis file
that downstream title/edit-advice apps load FIRST for strategy before
drilling into individual records for examples.
"""

import argparse
import os
import sys

from analyzer.synthesis import run_synthesis


DEFAULT_ANALYSIS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "output", "PeepingOtter.json",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build channel-level synthesis from an analyzer output file.")
    parser.add_argument(
        "--analysis", "-a",
        default=DEFAULT_ANALYSIS,
        help=f"Path to the analyzer output JSON (default: {DEFAULT_ANALYSIS})",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help=(
            "Path to write the synthesis JSON. Defaults to "
            "<analysis_basename>.synthesis.json alongside the input."
        ),
    )
    parser.add_argument(
        "--skip-narrative",
        action="store_true",
        help=(
            "Compute stats only; skip the Gemini narrative call. "
            "Useful for iterating on the stat math without burning API calls."
        ),
    )
    args = parser.parse_args()

    try:
        run_synthesis(
            analysis_file=args.analysis,
            output_file=args.output,
            skip_narrative=args.skip_narrative,
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
