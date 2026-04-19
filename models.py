"""
Gemini model configuration for the Shorts Analyzer.

Kept separate from the main SimpleAutoSubs app so this tool is fully
standalone. If you upgrade the model, change it here.
"""

from google import genai
from google.genai import types

from config import get_gemini_api_key


# Gemini 3.1 Pro — flagship reasoning model. This tool runs infrequently
# (you build a corpus once per channel) and the title-effectiveness
# analysis is the whole point, so we pay for Pro-quality reasoning.
#
# Note: the previous Pro preview (gemini-3-pro-preview) was shut down
# March 9, 2026. Use 3.1 going forward.
MODEL_PRO = "gemini-3.1-pro-preview"

# Kept around in case you ever want to switch a call to Flash for speed.
MODEL_FLASH = "gemini-3-flash-preview"

# Thinking level for the analysis call.
#   - Pro defaults to "high" but that's overkill for "describe this video and
#     explain why the title worked" — it's a reasoning task, not a hard one.
#   - "medium" keeps the Pro quality bump without paying for a full deep think.
#   - Pro does NOT support "minimal".
THINKING_ANALYSIS = "medium"


def get_safety_settings():
    """Permissive safety settings — gaming content often trips false positives."""
    return [
        types.SafetySetting(
            category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        types.SafetySetting(
            category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        types.SafetySetting(
            category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
    ]


def get_gemini_client() -> genai.Client:
    """Standard Gemini client on the v1beta endpoint (for File API uploads)."""
    return genai.Client(api_key=get_gemini_api_key())