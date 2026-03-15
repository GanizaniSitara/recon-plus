"""Determine session status from filesystem signals."""

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


# Cache for Claude PID check — refreshed periodically
_claude_live_pids: dict[int, dict] | None = None
_claude_live_pids_ts: float = 0


def _get_claude_live_pids() -> dict[int, dict]:
    """Read ~/.claude/sessions/*.json to get currently live session PIDs.
    Cached for 5 seconds."""
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
    """Check if a Claude Code session has a running process."""
    raw_id = sess.session_id.split(":", 1)[-1]
    live = _get_claude_live_pids()

    for pid, data in live.items():
        # Direct session ID match
        if data.get("sessionId") == raw_id:
            return True
        # CWD match via encoded project path
        pid_cwd = data.get("cwd", "")
        if pid_cwd:
            encoded = pid_cwd.replace("\\", "-").replace("/", "-").replace(":", "-")
            # Check if our JSONL lives in a project dir matching this cwd
            projects_dir = Path.home() / ".claude" / "projects"
            for project_dir in projects_dir.iterdir():
                if not project_dir.is_dir():
                    continue
                if encoded.lower() == project_dir.name.lower():
                    jsonl = project_dir / f"{raw_id}.jsonl"
                    if jsonl.is_file():
                        return True
    return False


def determine_status(sess: Session) -> str:
    """Determine session status from filesystem/event signals."""
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

    if sess.events_mtime > 0:
        age = time.time() - sess.events_mtime
        if age < 5:
            return Status.WORKING

    last = sess.last_event_type
    if last in (
        "tool.execution_start",
        "assistant.message",
        "assistant.turn_start",
        "subagent.started",
        "session.compaction_start",
    ):
        age = time.time() - sess.events_mtime
        if age < 120:
            return Status.WORKING
        return Status.DONE

    if last in ("assistant.turn_end", "user.message"):
        age = time.time() - sess.events_mtime
        if age < 3600:
            return Status.IDLE
        return Status.DONE

    if last == "abort":
        return Status.DONE

    if sess.events_mtime > 0:
        age = time.time() - sess.events_mtime
        if age < 3600:
            return Status.IDLE

    return Status.DONE


def _claude_status(sess: Session) -> str:
    if not sess.last_event_type:
        return Status.NEW

    # Recently modified = actively working
    if sess.events_mtime > 0:
        age = time.time() - sess.events_mtime
        if age < 5:
            return Status.WORKING

    last = sess.last_event_type

    # Mid-turn events
    if last in ("assistant", "progress", "tool_use"):
        age = time.time() - sess.events_mtime
        if age < 120:
            return Status.WORKING
        # Stale but process might still be alive (waiting for user input)
        if _claude_session_is_live(sess):
            return Status.IDLE
        return Status.DONE

    # User sent a message — session is idle waiting for next input
    if last == "user":
        if _claude_session_is_live(sess):
            return Status.IDLE
        age = time.time() - sess.events_mtime
        if age < 3600:
            return Status.IDLE
        return Status.DONE

    # Any other event type — check if process is alive
    if _claude_session_is_live(sess):
        return Status.IDLE

    if sess.events_mtime > 0:
        age = time.time() - sess.events_mtime
        if age < 3600:
            return Status.IDLE

    return Status.DONE


def _codex_status(sess: Session) -> str:
    if sess.has_shutdown:
        return Status.DONE
    if sess.events_mtime > 0:
        age = time.time() - sess.events_mtime
        if age < 10:
            return Status.WORKING
        if age < 3600:
            return Status.IDLE
    return Status.DONE
