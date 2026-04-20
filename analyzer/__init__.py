"""Shorts Analyzer package.

Public API is re-exported here so callers can just do:

    from analyzer import YouTubeShortAnalyzer

instead of reaching into core.analyzer directly.
"""

from analyzer.core.analyzer import YouTubeShortAnalyzer

__all__ = ["YouTubeShortAnalyzer"]
