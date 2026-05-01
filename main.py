"""
Direct CLI entry point — analyze a channel and exit.

Usage:
    python main.py                                    # uses defaults below
    python main.py --channel @PeepingOtter
    python main.py --channel https://youtube.com/@PeepingOtter --max 50
    python main.py --channel @PeepingOtter --recent 50
    python main.py --channel @PeepingOtter --output my_results.json
"""

import argparse
import os
import sys

from analyzer import YouTubeShortAnalyzer
from analyzer.synthesis import run_synthesis
from analyzer.tailwind import run_tailwind_analysis


# Defaults — edit these to change what `python main.py` does with no args
DEFAULT_CHANNEL = "https://www.youtube.com/@PeepingOtter/shorts"
# Split evenly between the top-by-views and bottom-by-views cohorts
# (so 100 → top 50 + bottom 50). The recent-by-upload cohort is sized
# separately by --recent.
DEFAULT_MAX_SHORTS = 100
DEFAULT_RECENT_N = 30
DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "output")


def _normalize_channel(channel: str) -> str:
    """Accept either '@handle' or a full URL and return a full URL."""
    channel = channel.strip()
    if channel.startswith("http://") or channel.startswith("https://"):
        return channel
    if channel.startswith("@"):
        return f"https://www.youtube.com/{channel}/shorts"
    return f"https://www.youtube.com/@{channel}/shorts"


def _derive_output_filename(channel_url: str) -> str:
    """Pull the @handle out of a URL to name the output file."""
    for part in channel_url.rstrip("/").split("/"):
        if part.startswith("@"):
            return f"{part.lstrip('@')}.json"
    return "shorts_analysis.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze a YouTube channel's top Shorts with Gemini.")
    parser.add_argument(
        "--channel", "-c",
        default=DEFAULT_CHANNEL,
        help=f"Channel URL or @handle (default: {DEFAULT_CHANNEL})",
    )
    parser.add_argument(
        "--max", "-m",
        type=int, default=DEFAULT_MAX_SHORTS, dest="max_shorts",
        help=(
            "Total size of the views-based cohorts, split evenly between "
            "top-by-views and bottom-by-views "
            f"(default: {DEFAULT_MAX_SHORTS} → top 50 + bottom 50)"
        ),
    )
    parser.add_argument(
        "--recent",
        type=int, default=DEFAULT_RECENT_N, dest="recent_n",
        help=(
            "Size of the most-recent-by-upload cohort "
            f"(default: {DEFAULT_RECENT_N})"
        ),
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output JSON filename or path. Defaults to output/<handle>.json.",
    )
    parser.add_argument(
        "--skip-synthesis",
        action="store_true",
        help=(
            "Skip the Phase 4 channel-level synthesis step after per-video "
            "analysis. Useful when iterating on per-video analysis alone."
        ),
    )
    parser.add_argument(
        "--skip-synthesis-narrative",
        action="store_true",
        help=(
            "Run Phase 4 synthesis but skip the Gemini narrative call — "
            "emit stats only. Cheaper and faster for iteration."
        ),
    )
    parser.add_argument(
        "--skip-tailwind",
        action="store_true",
        help=(
            "Skip the Phase 5 tailwind analysis step. Useful when "
            "iterating on earlier phases."
        ),
    )
    parser.add_argument(
        "--tailwind-all",
        action="store_true",
        help=(
            "Run Phase 5 tailwind on every short instead of only those "
            "above the residual cutoffs. Costs more Gemini calls."
        ),
    )
    parser.add_argument(
        "--tailwind-use-trends",
        action="store_true",
        help=(
            "Validate Phase 5 tailwind hypotheses against Google Trends. "
            "Requires `pip install pytrends`."
        ),
    )
    args = parser.parse_args()

    channel_url = _normalize_channel(args.channel)

    # Work out where the JSON should land
    if args.output:
        # Absolute or relative path from user — respect it exactly
        output_path = args.output
        if not output_path.endswith(".json"):
            output_path += ".json"
    else:
        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        output_path = os.path.join(
            DEFAULT_OUTPUT_DIR, _derive_output_filename(channel_url))

    analyzer = YouTubeShortAnalyzer(
        channel_url=channel_url,
        output_file=output_path,
        max_shorts=args.max_shorts,
        recent_n=args.recent_n,
    )

    try:
        analyzer.process_shorts()
        if not args.skip_synthesis:
            # Phase 4: channel-level synthesis. Runs after per-video
            # analysis so the synthesis reads the just-written output file.
            # A synthesis failure should not mask a successful analysis
            # run — log it and return 0 anyway.
            try:
                run_synthesis(
                    analysis_file=output_path,
                    skip_narrative=args.skip_synthesis_narrative,
                )
            except Exception as e:
                print(f"\n⚠️  Synthesis step failed: {e}")
                print("Per-video analysis succeeded; synthesis can be "
                      "re-run later with: python synthesize.py --analysis "
                      f"{output_path}")
                import traceback
                traceback.print_exc()
        if not args.skip_tailwind:
            # Phase 5: cultural tailwind. Reads the just-written output
            # file; same fail-soft policy as Phase 4.
            try:
                run_tailwind_analysis(
                    analysis_file=output_path,
                    include_all=args.tailwind_all,
                    use_trends=args.tailwind_use_trends,
                )
            except Exception as e:
                print(f"\n⚠️  Tailwind step failed: {e}")
                print("Per-video analysis succeeded; tailwind can be "
                      "re-run later with: python tailwind.py --analysis "
                      f"{output_path}")
                import traceback
                traceback.print_exc()
        return 0
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Progress has been saved.")
        return 130
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        analyzer.cleanup()


if __name__ == "__main__":
    sys.exit(main())
