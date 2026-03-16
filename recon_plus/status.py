"""Determine session status from filesystem signals.

The core logic:
  - File changed since last refresh → Working
  - pending_tool + session alive → Input (needs user approval)
  - Process alive + not working → Idle
  - No process + stale → Done
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .session import Session
from . import config


class Status:
    NEW = "New"
    WORKING = "Working"
    INPUT = "Input"
    IDLE = "Idle"
    DONE = "Done"

    COLORS = {
        "New": "dodger_blue1",
        "Working": "green",
        "Input": "red",
        "Idle": "bright_black",
        "Done": "dark_gray",
    }

    DOTS = {
        "New": "[dodger_blue1]\u25cf[/]",
        "Working": "[green]\u25cf[/]",
        "Input": "[red]\u25cf[/]",
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


def _is_stale(sess: Session, max_age: float = 600) -> bool:
    """Is the events file older than max_age seconds?"""
    if sess.events_mtime <= 0:
        return True
    return (time.time() - sess.events_mtime) > max_age


# ── Copilot workspace.yaml liveness check ────────────────────────────

_copilot_ws_mtimes: dict[str, float] = {}
_copilot_ws_ts: float = 0


def _copilot_session_is_live(sess: Session) -> bool:
    """Check if a Copilot session's workspace.yaml was recently modified.
    Copilot updates workspace.yaml more frequently than events.jsonl."""
    global _copilot_ws_mtimes, _copilot_ws_ts
    now = time.time()

    # Refresh cache every 5s
    if now - _copilot_ws_ts > 5:
        _copilot_ws_mtimes.clear()
        base = config.copilot_home() / "session-state"
        if base.is_dir():
            for ws in base.glob("*/workspace.yaml"):
                try:
                    _copilot_ws_mtimes[ws.parent.name] = ws.stat().st_mtime
                except OSError:
                    pass
        _copilot_ws_ts = now

    raw_id = sess.session_id.split(":", 1)[-1]
    ws_mtime = _copilot_ws_mtimes.get(raw_id, 0)
    if ws_mtime <= 0:
        return False
    # If workspace.yaml was modified in last 10 minutes, session is likely alive
    return (now - ws_mtime) < 600


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


def _encode_cwd(cwd: str) -> str:
    """Encode a cwd path the same way Claude Code encodes project dirs."""
    return cwd.replace("\\", "-").replace("/", "-").replace(":", "-").lower()


def _claude_session_is_live(sess: Session) -> bool:
    """Check if a Claude session has a running process.
    Only matches by direct session ID to avoid false positives
    from multiple sessions sharing a project directory."""
    raw_id = sess.session_id.split(":", 1)[-1]
    live = _get_claude_live_pids()

    for pid, data in live.items():
        if data.get("sessionId") == raw_id:
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
        if _copilot_session_is_live(sess):
            return Status.NEW
        return Status.DONE  # empty stale session
    if sess.has_shutdown:
        return Status.DONE

    is_live = _copilot_session_is_live(sess)

    if _file_changed(sess):
        return Status.WORKING

    # Pending tool approval only matters if session is still alive
    if sess.pending_tool and is_live:
        return Status.INPUT

    last = sess.last_event_type
    if last in ("assistant.turn_end",):
        if is_live:
            return Status.IDLE
        return Status.DONE

    if last in ("user.message", "assistant.turn_start", "tool.execution_start",
                "assistant.message", "subagent.started"):
        if is_live:
            return Status.WORKING
        if not _is_stale(sess):
            return Status.WORKING
        return Status.DONE

    if last == "abort":
        return Status.DONE

    if is_live:
        return Status.IDLE
    if not _is_stale(sess, 3600):
        return Status.IDLE
    return Status.DONE


def _claude_status(sess: Session) -> str:
    if not sess.last_event_type:
        return Status.NEW
    if _file_changed(sess):
        return Status.WORKING

    is_live = _claude_session_is_live(sess)

    if sess.pending_tool and is_live:
        return Status.INPUT

    last = sess.last_event_type
    if last in ("assistant", "progress", "tool_use"):
        if is_live:
            return Status.IDLE
        if not _is_stale(sess):
            return Status.WORKING
        return Status.DONE

    if last == "user":
        if is_live:
            return Status.WORKING
        return Status.DONE

    if is_live:
        return Status.IDLE
    if not _is_stale(sess, 3600):
        return Status.IDLE
    return Status.DONE


def _codex_status(sess: Session) -> str:
    if sess.has_shutdown:
        return Status.DONE
    if _file_changed(sess):
        return Status.WORKING
    if sess.events_mtime > 0 and not _is_stale(sess, 3600):
        return Status.IDLE
    return Status.DONE
