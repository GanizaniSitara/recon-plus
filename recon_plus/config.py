"""Read ~/.copilot/config.json for global settings."""

import json
from pathlib import Path


def copilot_home() -> Path:
    """Return the Copilot CLI config directory."""
    import os
    if env := os.environ.get("COPILOT_HOME"):
        return Path(env)
    return Path.home() / ".copilot"


def read_config() -> dict:
    """Read ~/.copilot/config.json, returning {} on any error."""
    path = copilot_home() / "config.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def default_model() -> str:
    return read_config().get("model", "")


def reasoning_effort() -> str:
    return read_config().get("reasoning_effort", "")
