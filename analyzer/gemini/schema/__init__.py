"""Gemini structured-output schema.

One export: ANALYSIS_SCHEMA. Composed from four parts for readability:
  - base: top-level prose fields + composition
  - retention: retention-curve interpretation sub-schema
  - attribution: 4-bucket attribution object
  - tags: controlled vocabulary (built from analyzer.tags.vocabulary)
"""

from analyzer.gemini.schema.base import ANALYSIS_SCHEMA

__all__ = ["ANALYSIS_SCHEMA"]
