"""Config loader for the Shorts Analyzer."""

import json
import os

# config.json lives at the project root, two levels above this file
# (analyzer/core/config.py → project root)
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config.json")


def _load_config() -> dict:
    if not os.path.exists(_CONFIG_PATH):
        raise FileNotFoundError(
            f"config.json not found at {_CONFIG_PATH}. "
            "Copy config.example.json to config.json and add your API keys."
        )
    with open(_CONFIG_PATH, "r") as f:
        return json.load(f)


def get_gemini_api_key() -> str:
    key = _load_config().get("GEMINI_API_KEY", "")
    if not key or key == "YOUR_API_KEY_HERE":
        raise ValueError("GEMINI_API_KEY not set in config.json")
    return key


def get_youtube_api_key() -> str:
    key = _load_config().get("YOUTUBE_API_KEY", "")
    if not key or key == "YOUR_API_KEY_HERE":
        raise ValueError("YOUTUBE_API_KEY not set in config.json")
    return key


# ─── Analytics OAuth paths ────────────────────────────────────────────────────
# client_secrets.json: download from Google Cloud Console →
#   APIs & Services → Credentials → OAuth 2.0 Client IDs → Desktop app → Download
# token.json: written automatically on first OAuth authorization run.

def get_analytics_client_secrets() -> str:
    return os.path.join(_PROJECT_ROOT, "client_secret.json")


def get_analytics_token_path() -> str:
    return os.path.join(_PROJECT_ROOT, "data", "analytics_cache", "token.json")


def analytics_available() -> bool:
    """True if client_secret.json exists (OAuth credentials have been set up)."""
    return os.path.exists(get_analytics_client_secrets())
