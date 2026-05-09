"""Config loader for the Shorts Analyzer (analyzer.core variant).

API keys and YouTube OAuth credentials come from the centralized youtube_hub
config.
"""

import os
import sys

# project root: analyzer/core/config.py → project root is two levels up
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_HUB_CONFIG = os.path.abspath(
    os.path.join(_PROJECT_ROOT, "..", "youtube_hub", "config"))
if _HUB_CONFIG not in sys.path:
    sys.path.insert(0, _HUB_CONFIG)

from shared_secrets import (  # noqa: E402
    get_gemini_api_key as _shared_gemini,
    get_youtube_api_key as _shared_youtube,
    get_oauth_client_secrets_path,
    get_oauth_token_path,
)


def get_gemini_api_key() -> str:
    key = _shared_gemini()
    if not key or key == "YOUR_API_KEY_HERE":
        raise ValueError(
            "GEMINI_API_KEY not set in youtube_hub/config/secrets.json")
    return key


def get_youtube_api_key() -> str:
    key = _shared_youtube()
    if not key or key == "YOUR_API_KEY_HERE":
        raise ValueError(
            "YOUTUBE_API_KEY not set in youtube_hub/config/secrets.json")
    return key


# ─── Analytics OAuth paths ────────────────────────────────────────────────────
# Shared client_secret.json and a scope-specific token file both live under
# youtube_hub/config/oauth/. Tokens are written there on first OAuth run.

def get_analytics_client_secrets() -> str:
    return str(get_oauth_client_secrets_path())


def get_analytics_token_path() -> str:
    return str(get_oauth_token_path("yt_analytics"))


def analytics_available() -> bool:
    """True if client_secret.json exists (OAuth credentials have been set up)."""
    return os.path.exists(get_analytics_client_secrets())
