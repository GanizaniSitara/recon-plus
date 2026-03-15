"""Discover and parse sessions from Copilot CLI, Claude Code, and Codex CLI."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import config


@dataclass
class Session:
    session_id: str
    provider: str = ""  # "copilot", "claude", "codex"
    cwd: str = ""
    git_root: str = ""
    repository: str = ""
    branch: str = ""
    summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    model: str = ""
    total_output_tokens: int = 0
    total_premium_requests: int = 0
    last_event_type: str = ""
    last_event_time: str = ""
    has_shutdown: bool = False
    events_mtime: float = 0.0
    session_size: int = 0  # total size of session directory in bytes
    # Cached for incremental reads
    _last_file_size: int = 0

    @property
    def project_display(self) -> str:
        repo = self.repository
        if not repo:
            repo = Path(self.cwd).name if self.cwd else "unknown"
        if self.branch:
            return f"{repo}::{self.branch}"
        return repo

    @property
    def short_cwd(self) -> str:
        home = str(Path.home())
        if self.cwd.startswith(home):
            return "~" + self.cwd[len(home):]
        return self.cwd

    @property
    def summary_display(self) -> str:
        return self.summary or self.session_id[:8]

    @property
    def last_activity_display(self) -> str:
        ts = self.last_event_time or self.updated_at
        if not ts:
            return "-"
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            diff = now - dt
            secs = int(diff.total_seconds())
            if secs < 60:
                return f"{secs}s ago"
            mins = secs // 60
            if mins < 60:
                return f"{mins}m ago"
            hours = mins // 60
            if hours < 24:
                return f"{hours}h ago"
            days = hours // 24
            return f"{days}d ago"
        except (ValueError, TypeError):
            return ts[:16]

    @property
    def size_display(self) -> str:
        b = self.session_size
        if b == 0:
            return "-"
        if b < 1024:
            return f"{b}B"
        if b < 1024 * 1024:
            return f"{b // 1024}K"
        return f"{b / (1024 * 1024):.1f}M"

    @property
    def provider_tag(self) -> str:
        return {"copilot": "COP", "claude": "CC", "codex": "CDX"}.get(
            self.provider, "?"
        )


# ---------------------------------------------------------------------------
# Unified discovery
# ---------------------------------------------------------------------------

def discover_sessions(
    prev: dict[str, Session] | None = None,
    max_age_days: int = 7,
) -> list[Session]:
    """Discover sessions across all providers."""
    if prev is None:
        prev = {}

    sessions: list[Session] = []
    sessions.extend(_discover_copilot(prev, max_age_days))
    sessions.extend(_discover_claude(prev, max_age_days))
    sessions.extend(_discover_codex(prev, max_age_days))

    sessions.sort(key=lambda s: s.updated_at or "", reverse=True)
    return sessions


# ---------------------------------------------------------------------------
# Copilot CLI  (~/.copilot/session-state/{uuid}/workspace.yaml + events.jsonl)
# ---------------------------------------------------------------------------

def _discover_copilot(
    prev: dict[str, Session], max_age_days: int
) -> list[Session]:
    base = config.copilot_home() / "session-state"
    if not base.is_dir():
        return []

    sessions = []
    now = datetime.now(timezone.utc)

    for ws_path in base.glob("*/workspace.yaml"):
        session_dir = ws_path.parent
        sid = f"copilot:{session_dir.name}"

        try:
            ws = yaml.safe_load(ws_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(ws, dict):
            continue

        updated = ws.get("updated_at", "")
        if updated and max_age_days > 0:
            try:
                dt = datetime.fromisoformat(
                    _to_str(updated).replace("Z", "+00:00")
                )
                if (now - dt).days > max_age_days:
                    continue
            except (ValueError, TypeError):
                pass

        sess = Session(
            session_id=sid,
            provider="copilot",
            cwd=ws.get("cwd", ""),
            git_root=ws.get("git_root", ""),
            repository=ws.get("repository", ""),
            branch=ws.get("branch", ""),
            summary=ws.get("summary", ""),
            created_at=_to_str(ws.get("created_at", "")),
            updated_at=_to_str(updated),
        )

        _parse_copilot_events(sess, session_dir / "events.jsonl", prev.get(sid))
        sess.session_size = _dir_size(session_dir)
        sessions.append(sess)

    return sessions


def _parse_copilot_events(
    sess: Session, events_path: Path, prev: Session | None
) -> None:
    if not events_path.is_file():
        return

    try:
        stat = events_path.stat()
    except OSError:
        return

    sess.events_mtime = stat.st_mtime
    file_size = stat.st_size

    if prev:
        sess.model = prev.model
        sess.total_output_tokens = prev.total_output_tokens
        sess.total_premium_requests = prev.total_premium_requests
        sess.has_shutdown = prev.has_shutdown
        sess.last_event_type = prev.last_event_type
        sess.last_event_time = prev.last_event_time
        sess._last_file_size = prev._last_file_size

    if file_size == sess._last_file_size and sess._last_file_size > 0:
        return

    if sess._last_file_size == 0 or file_size < sess._last_file_size:
        sess.total_output_tokens = 0
        sess.total_premium_requests = 0
        sess.has_shutdown = False
        seek_pos = 0
    else:
        seek_pos = sess._last_file_size

    try:
        with open(events_path, "r", encoding="utf-8") as f:
            if seek_pos > 0:
                f.seek(seek_pos)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ev_type = ev.get("type", "")
                ev_ts = ev.get("timestamp", "")
                if ev_ts:
                    sess.last_event_time = ev_ts
                sess.last_event_type = ev_type

                data = ev.get("data", {})
                if ev_type == "session.model_change":
                    sess.model = data.get("newModel", sess.model)
                elif ev_type == "tool.execution_complete":
                    if m := data.get("model"):
                        sess.model = m
                elif ev_type == "assistant.message":
                    if tok := data.get("outputTokens"):
                        sess.total_output_tokens += tok
                elif ev_type == "session.shutdown":
                    sess.has_shutdown = True
                    sess.total_premium_requests = data.get(
                        "totalPremiumRequests", sess.total_premium_requests
                    )
    except OSError:
        pass

    sess._last_file_size = file_size


# ---------------------------------------------------------------------------
# Claude Code  (~/.claude/projects/{dir}/*.jsonl + ~/.claude/sessions/*.json)
# ---------------------------------------------------------------------------

def _claude_home() -> Path:
    return Path.home() / ".claude"


def _discover_claude(
    prev: dict[str, Session], max_age_days: int
) -> list[Session]:
    claude_dir = _claude_home() / "projects"
    if not claude_dir.is_dir():
        return []

    # Build PID -> session info map from ~/.claude/sessions/*.json
    pid_map = _claude_pid_map()

    sessions = []
    now = datetime.now(timezone.utc)
    cutoff_ts = now.timestamp() - max_age_days * 86400

    for project_dir in claude_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_path in project_dir.glob("*.jsonl"):
            # Skip subagent files
            if "subagents" in str(jsonl_path):
                continue

            try:
                mtime = jsonl_path.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff_ts:
                continue

            session_id_raw = jsonl_path.stem
            sid = f"claude:{session_id_raw}"

            cwd = _decode_claude_project_path(project_dir)
            prev_sess = prev.get(sid)

            sess = Session(
                session_id=sid,
                provider="claude",
                cwd=cwd,
            )

            _parse_claude_jsonl(sess, jsonl_path, prev_sess)
            try:
                sess.session_size = jsonl_path.stat().st_size
            except OSError:
                pass

            # Git info from cwd
            repo_name = Path(cwd).name if cwd else ""
            sess.repository = repo_name

            sessions.append(sess)

    return sessions


def _claude_pid_map() -> dict[int, dict]:
    """Read ~/.claude/sessions/{PID}.json files."""
    sessions_dir = _claude_home() / "sessions"
    if not sessions_dir.is_dir():
        return {}

    result = {}
    for path in sessions_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pid = data.get("pid")
            if pid:
                result[pid] = data
        except (OSError, json.JSONDecodeError):
            continue
    return result


def _parse_claude_jsonl(
    sess: Session, path: Path, prev: Session | None
) -> None:
    try:
        stat = path.stat()
    except OSError:
        return

    sess.events_mtime = stat.st_mtime
    file_size = stat.st_size

    if prev:
        sess.model = prev.model
        sess.total_output_tokens = prev.total_output_tokens
        sess.branch = prev.branch
        sess.summary = prev.summary
        sess.last_event_type = prev.last_event_type
        sess.last_event_time = prev.last_event_time
        sess.created_at = prev.created_at
        sess.updated_at = prev.updated_at
        sess._last_file_size = prev._last_file_size

    if file_size == sess._last_file_size and sess._last_file_size > 0:
        return

    if sess._last_file_size == 0 or file_size < sess._last_file_size:
        sess.total_output_tokens = 0
        seek_pos = 0
    else:
        seek_pos = sess._last_file_size

    try:
        with open(path, "r", encoding="utf-8") as f:
            if seek_pos > 0:
                f.seek(seek_pos)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ev_type = ev.get("type", "")
                ev_ts = ev.get("timestamp", "")

                if ev_ts:
                    sess.last_event_time = ev_ts
                    if not sess.created_at:
                        sess.created_at = ev_ts
                    sess.updated_at = ev_ts
                sess.last_event_type = ev_type

                if ev_type == "assistant":
                    msg = ev.get("message", {})
                    if m := msg.get("model"):
                        sess.model = m
                    usage = msg.get("usage", {})
                    if tok := usage.get("output_tokens"):
                        sess.total_output_tokens += tok

                # Pick up git branch
                if not sess.branch:
                    if b := ev.get("gitBranch"):
                        sess.branch = b

                # Pick up summary from first user message
                if ev_type == "user" and not sess.summary:
                    msg = ev.get("message", {})
                    if isinstance(msg, dict):
                        content = msg.get("content", "")
                        if isinstance(content, str) and content:
                            sess.summary = content[:60].split("\n")[0]
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    sess.summary = block.get("text", "")[:60].split("\n")[0]
                                    break
    except OSError:
        pass

    sess._last_file_size = file_size


def _decode_claude_project_path(project_dir: Path) -> str:
    """Decode Claude Code's encoded project directory name back to a path.
    e.g. 'C--git-recon-plus' -> 'C:\\git\\recon-plus'
    Note: this is lossy (can't distinguish original - from path separators)."""
    name = project_dir.name
    if name.startswith("C--"):
        # Windows path: C--git-foo -> C:\git\foo
        return "C:\\" + name[3:].replace("-", "\\")
    if name.startswith("-"):
        # Unix path: -Users-foo -> /Users/foo
        return "/" + name[1:].replace("-", "/")
    return name


# ---------------------------------------------------------------------------
# Codex CLI  (~/.codex/state_5.sqlite threads table)
# ---------------------------------------------------------------------------

def _codex_home() -> Path:
    import os
    if env := os.environ.get("CODEX_HOME"):
        return Path(env)
    return Path.home() / ".codex"


def _discover_codex(
    prev: dict[str, Session], max_age_days: int
) -> list[Session]:
    db_path = _codex_home() / "state_5.sqlite"
    if not db_path.is_file():
        return []

    sessions = []
    now = datetime.now(timezone.utc)
    cutoff = int((now.timestamp() - max_age_days * 86400) * 1000)

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM threads WHERE updated_at > ? ORDER BY updated_at DESC",
            (cutoff,),
        )
        for row in cursor.fetchall():
            row_id = row["id"]
            sid = f"codex:{row_id}"

            created_ms = row["created_at"] or 0
            updated_ms = row["updated_at"] or 0

            # Extract repo name from git_origin_url
            origin = row["git_origin_url"] or ""
            repo = ""
            if origin:
                repo = origin.rstrip("/").rsplit("/", 1)[-1]
                if repo.endswith(".git"):
                    repo = repo[:-4]

            # Summary from title or first_user_message
            title = row["title"] or ""
            summary = title[:60].split("\n")[0] if title else ""

            sess = Session(
                session_id=sid,
                provider="codex",
                cwd=row["cwd"] or "",
                repository=repo,
                branch=row["git_branch"] or "",
                summary=summary,
                model=row["model_provider"] or "",
                total_output_tokens=row["tokens_used"] or 0,
                created_at=_epoch_ms_to_iso(created_ms),
                updated_at=_epoch_ms_to_iso(updated_ms),
                has_shutdown=True,  # Codex threads in DB are completed
            )

            # Check for rollout JSONL for mtime + size
            _codex_enrich_from_rollout(sess, row_id)

            sessions.append(sess)

        conn.close()
    except (sqlite3.Error, OSError):
        pass

    return sessions


def _codex_enrich_from_rollout(sess: Session, thread_id: str) -> None:
    """Find the rollout JSONL for a thread and get its mtime."""
    sessions_dir = _codex_home() / "sessions"
    if not sessions_dir.is_dir():
        return
    # Rollout files are named: rollout-{date}T{time}-{thread_id}.jsonl
    for path in sessions_dir.rglob(f"*{thread_id}.jsonl"):
        try:
            st = path.stat()
            sess.events_mtime = st.st_mtime
            sess.session_size = st.st_size
        except OSError:
            pass
        break


# ---------------------------------------------------------------------------
# Purge (Copilot only for now)
# ---------------------------------------------------------------------------

def delete_session(sess: Session) -> bool:
    """Delete a session's local data. Returns True on success."""
    import shutil

    raw_id = sess.session_id.split(":", 1)[-1]

    if sess.provider == "copilot":
        path = config.copilot_home() / "session-state" / raw_id
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            return True

    elif sess.provider == "claude":
        # Delete the JSONL file (and subagents dir if present)
        claude_projects = _claude_home() / "projects"
        for project_dir in claude_projects.iterdir():
            if not project_dir.is_dir():
                continue
            jsonl = project_dir / f"{raw_id}.jsonl"
            if jsonl.is_file():
                jsonl.unlink(missing_ok=True)
                # Also remove subagents dir for this session
                sub_dir = project_dir / raw_id
                if sub_dir.is_dir():
                    shutil.rmtree(sub_dir, ignore_errors=True)
                return True

    elif sess.provider == "codex":
        # Remove from SQLite threads table
        db_path = _codex_home() / "state_5.sqlite"
        if db_path.is_file():
            try:
                conn = sqlite3.connect(str(db_path))
                conn.execute("DELETE FROM threads WHERE id = ?", (raw_id,))
                conn.commit()
                conn.close()
            except sqlite3.Error:
                return False
            # Also remove rollout JSONL
            sessions_dir = _codex_home() / "sessions"
            for path in sessions_dir.rglob(f"*{raw_id}.jsonl"):
                path.unlink(missing_ok=True)
            return True

    return False


def purge_empty_sessions() -> int:
    """Delete Copilot session directories that have no events."""
    import shutil

    base = config.copilot_home() / "session-state"
    if not base.is_dir():
        return 0

    count = 0
    for workspace_path in base.glob("*/workspace.yaml"):
        session_dir = workspace_path.parent
        events_path = session_dir / "events.jsonl"
        if events_path.is_file() and events_path.stat().st_size > 0:
            continue
        shutil.rmtree(session_dir, ignore_errors=True)
        count += 1

    return count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def session_state_dir() -> Path:
    return config.copilot_home() / "session-state"


def _to_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)


def _dir_size(path: Path) -> int:
    """Sum of all file sizes in a directory tree."""
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        pass
    return total


def _epoch_ms_to_iso(ms: int) -> str:
    if not ms:
        return ""
    try:
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        return dt.isoformat()
    except (OSError, ValueError):
        return ""
