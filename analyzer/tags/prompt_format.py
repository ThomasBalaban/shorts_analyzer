"""Renders the vocabulary as prompt text for Gemini.

Kept separate from vocabulary.py because the data and its prose rendering
are different concerns — the schema builder also consumes vocabulary but
never touches this module.
"""

from __future__ import annotations

from typing import Iterable

from analyzer.tags.types import TagAxis
from analyzer.tags.vocabulary import ALL_AXES


def format_axis(axis: TagAxis) -> str:
    """Render a single axis as a plain-text block for the prompt."""
    cardinality = "multi-tag" if axis.multi else "single-tag"
    header = f"## {axis.label}  ({axis.field}, {cardinality})\n{axis.description}"
    lines = [f"  - {t.id}: {t.description}" for t in axis.tags]
    return header + "\n" + "\n".join(lines)


def format_vocabulary(axes: Iterable[TagAxis] = ALL_AXES) -> str:
    """Render every axis as the appendix block the prompt pastes verbatim."""
    return "\n\n".join(format_axis(a) for a in axes)
