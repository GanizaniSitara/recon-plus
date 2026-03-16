"""Determine session status from filesystem signals.

The core logic is deterministic:
  - File changed since last refresh (2s ago) → Working
  - File didn't change + process alive → Idle
  - File didn't change + no process → Done
  - No events at all → New
  - Explicit shutdown event → Done
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .session import Session


class Status:
    NEW = "New"
    WORKING = "Working"
    IDLE = "Idle"
    DONE = "Done"

    COLORS = {
        "New": "dodger_blue1",
        "Working": "green",
        "Idle": "bright_black",
        "Done": "dark_gray",
    }

    DOTS = {
        "New": "[dodger_blue1]\u25cf[/]",
        "Working": "[green]\u25cf[/]",
        "Idle": "[bright_black]\u25cf[/]",
        "Done": "[dark_gray]\u25cf[/]",
    }


def _file_changed(sess: Session) -> bool:
    """Did the events file change since our last refresh?"""
    return (
        sess.events_mtime > 0
        and sess.prev_events_mtime > 0
        and sess.events_mtime != sess.prev_events_mtime
    )


# ── Claude live process detection ────────────────────────────────────

_claude_live_pids: dict[int, dict] | None = None
_claude_live_pids_ts: float = 0


def _get_claude_live_pids() -> dict[int, dict]:
    global _claude_live_pids, _claude_live_pids_ts
    now = time.time()
    if _claude_live_pids is not None and now - _claude_live_pids_ts < 5:
        return _claude_live_pids

    result = {}
    sessions_dir = Path.home() / ".claude" / "sessions"
    if sessions_dir.is_dir():
        for f in sessions_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                pid = data.get("pid")
                if pid:
                    result[pid] = data
            except (OSError, json.JSONDecodeError):
                continue

    _claude_live_pids = result
    _claude_live_pids_ts = now
    return result


def _claude_session_is_live(sess: Session) -> bool:
    raw_id = sess.session_id.split(":", 1)[-1]
    live = _get_claude_live_pids()

    for pid, data in live.items():
        if data.get("sessionId") == raw_id:
            return True
        pid_cwd = data.get("cwd", "")
        if pid_cwd:
            encoded = pid_cwd.replace("\\", "-").replace("/", "-").replace(":", "-")
            projects_dir = Path.home() / ".claude" / "projects"
            for project_dir in projects_dir.iterdir():
                if not project_dir.is_dir():
                    continue
                if encoded.lower() == project_dir.name.lower():
                    jsonl = project_dir / f"{raw_id}.jsonl"
                    if jsonl.is_file():
                        return True
    return False


# ── Status determination ─────────────────────────────────────────────

def determine_status(sess: Session) -> str:
    if sess.provider == "claude":
        return _claude_status(sess)
    if sess.provider == "codex":
        return _codex_status(sess)
    return _copilot_status(sess)


def _copilot_status(sess: Session) -> str:
    if not sess.last_event_type:
        return Status.NEW
    if sess.has_shutdown:
        return Status.DONE
    if _file_changed(sess):
        return Status.WORKING

    # File didn't change — check how stale it is
    last = sess.last_event_type
    if last in ("assistant.turn_end",):
        return Status.IDLE
    if last in ("user.message", "assistant.turn_start", "tool.execution_start",
                "assistant.message", "subagent.started"):
        # Mid-turn but file stopped changing — could be long model think
        age = time.time() - sess.events_mtime
        if age < 600:
            return Status.WORKING
        return Status.DONE
    if last == "abort":
        return Status.DONE
    # Fallback
    age = time.time() - sess.events_mtime
    if age < 3600:
        return Status.IDLE
    return Status.DONE


def _claude_status(sess: Session) -> str:
    if not sess.last_event_type:
        return Status.NEW
    if _file_changed(sess):
        return Status.WORKING

    # File didn't change — check process
    is_live = _claude_session_is_live(sess)

    last = sess.last_event_type
    if last in ("assistant", "progress", "tool_use"):
        if is_live:
            return Status.IDLE  # finished responding, waiting for user
        age = time.time() - sess.events_mtime
        if age < 600:
            return Status.WORKING  # first refresh, no prev_mtime yet
        return Status.DONE

    if last == "user":
        # User sent message — if process is alive, model is thinking
        if is_live:
            return Status.WORKING
        return Status.DONE

    if is_live:
        return Status.IDLE

    age = time.time() - sess.events_mtime
    if age < 3600:
        return Status.IDLE
    return Status.DONE


def _codex_status(sess: Session) -> str:
    if sess.has_shutdown:
        return Status.DONE
    if _file_changed(sess):
        return Status.WORKING
    if sess.events_mtime > 0:
        age = time.time() - sess.events_mtime
        if age < 3600:
            return Status.IDLE
    return Status.DONE
