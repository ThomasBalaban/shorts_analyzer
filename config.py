"""Config loader for the Shorts Analyzer."""

import json
import os

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config.json")


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