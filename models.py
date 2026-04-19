"""
Gemini model configuration for the Shorts Analyzer.

Kept separate from the main SimpleAutoSubs app so this tool is fully
standalone. If you upgrade the model, change it here.
"""

from google import genai
from google.genai import types

from config import get_gemini_api_key


# Flash is the right fit for this task — high-volume video captioning
# where latency matters more than deep reasoning.
MODEL_FLASH = "gemini-3-flash-preview"


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