"""Small dataclasses for the controlled-vocabulary tag system.

The vocabulary (analyzer.tags.vocabulary) is the single source of truth —
both the Gemini schema (analyzer.gemini.schema) and the prompt appendix
(analyzer.tags.prompt_format) consume it, so a tag added here propagates
everywhere.

An axis is either single-tag (one value, STRING + enum) or multi-tag
(array of values, ARRAY of STRING + enum on items). Gemini's structured
output decoder enforces the enum, so off-vocabulary tags are impossible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Tag:
    id: str
    description: str


@dataclass(frozen=True)
class TagAxis:
    field: str
    label: str
    description: str
    multi: bool
    tags: Tuple[Tag, ...]

    @property
    def tag_ids(self) -> Tuple[str, ...]:
        return tuple(t.id for t in self.tags)
