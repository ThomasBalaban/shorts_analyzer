"""Controlled-vocabulary tag system.

The vocabulary module (analyzer.tags.vocabulary) is the single source of
truth for all tag axes and tag IDs. The Gemini schema (analyzer.gemini.schema)
and the prompt appendix (analyzer.tags.prompt_format) both consume it.

Adding or renaming a tag is a one-file edit: change vocabulary.py and both
the schema enum and the prompt text regenerate automatically on next run.
"""

from analyzer.tags.types import Tag, TagAxis
from analyzer.tags.vocabulary import ALL_AXES
from analyzer.tags.prompt_format import format_vocabulary

__all__ = ["Tag", "TagAxis", "ALL_AXES", "format_vocabulary"]
