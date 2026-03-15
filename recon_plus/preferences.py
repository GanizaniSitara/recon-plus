"""Recon-copilot user preferences stored in ~/.recon-plus.json."""

from __future__ import annotations

import json
from pathlib import Path

PREFS_PATH = Path.home() / ".recon-plus.json"

AGENTS = ["copilot", "claude", "codex"]

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        _cache = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _cache = {}
    return _cache


def _save(data: dict) -> None:
    global _cache
    _cache = data
    PREFS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def default_agent() -> str:
    return _load().get("default_agent", "copilot")


def set_default_agent(agent: str) -> None:
    data = _load()
    data["default_agent"] = agent
    _save(data)


def next_agent() -> str:
    """Cycle to the next agent and return it."""
    current = default_agent()
    idx = AGENTS.index(current) if current in AGENTS else 0
    new = AGENTS[(idx + 1) % len(AGENTS)]
    set_default_agent(new)
    return new
