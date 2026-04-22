"""Builds the `tags` sub-schema from the vocabulary.

Each axis becomes either a STRING (single-tag) with `enum`, or an ARRAY of
STRING with the same enum on items. Gemini's structured-output decoder
rejects off-vocabulary values — this is what makes the tag layer reliable.

A tag added to analyzer.tags.vocabulary appears here automatically on the
next process start. No manual sync.
"""

from __future__ import annotations

from google.genai import types  # type: ignore

from analyzer.tags.vocabulary import ALL_AXES


def _axis_schema(axis) -> types.Schema:
    enum_values = list(axis.tag_ids)
    if axis.multi:
        return types.Schema(
            type="ARRAY",
            items=types.Schema(type="STRING", enum=enum_values),
            description=axis.description,
        )
    return types.Schema(
        type="STRING",
        enum=enum_values,
        description=axis.description,
    )


def _build() -> types.Schema:
    properties = {axis.field: _axis_schema(axis) for axis in ALL_AXES}
    required = [axis.field for axis in ALL_AXES]
    return types.Schema(
        type="OBJECT",
        description=(
            "Controlled-vocabulary tags. Every field must use only values "
            "from its enum. Multi-tag axes are arrays; single-tag axes are "
            "strings. Apply every tag that legitimately fits — overlapping "
            "tags across axes (presence vs. role) are expected."
        ),
        properties=properties,
        required=required,
    )


TAGS_SCHEMA = _build()
