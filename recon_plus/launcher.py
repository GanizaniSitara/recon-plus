"""Launch, resume, and focus sessions in terminal windows."""

from __future__ import annotations

import ctypes
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .session import Session

if sys.platform == "win32":
    user32 = ctypes.windll.user32


def _has_wt() -> bool:
    return shutil.which("wt") is not None


def launch_session(cwd: str | None = None, agent: str | None = None) -> None:
    """Launch a new session with the specified or default agent."""
    from .preferences import default_agent
    work_dir = cwd or str(Path.cwd())
    cmd = agent or default_agent()
    _start_in_new_window([cmd], work_dir)


def resume_session(sess: Session) -> None:
    """Focus an existing session window, or launch/resume in a new one."""
    # Try to find and focus the existing window first
    if _try_focus_session(sess):
        return

    # Not running — resume in a new window
    raw_id = sess.session_id.split(":", 1)[-1]
    work_dir = sess.cwd or str(Path.cwd())

    if sess.provider == "copilot":
        _start_in_new_window(["copilot", "--resume", raw_id], work_dir)
    elif sess.provider == "claude":
        _start_in_new_window(["claude", "--resume", raw_id], work_dir)
    elif sess.provider == "codex":
        _start_in_new_window(["codex", "resume", raw_id], work_dir)


def _try_focus_session(sess: Session) -> bool:
    """Try to find the window for a running session and focus it.
    Returns True if found and focused."""
    if sys.platform != "win32":
        return False

    hwnd = _find_session_window(sess)
    if hwnd:
        # SW_RESTORE = 9, then SetForegroundWindow
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        return True
    return False


def _find_session_window(sess: Session) -> int | None:
    """Find the console window handle for a running session."""
    if sess.provider == "claude":
        return _find_claude_window(sess)
    if sess.provider == "copilot":
        return _find_copilot_window(sess)
    return None


def _find_claude_window(sess: Session) -> int | None:
    """Find window for a Claude Code session via PID -> parent cmd window.

    Claude Code writes ~/.claude/sessions/{PID}.json for each running process.
    The JSONL filename is the *original* session ID but the PID file may contain
    a different sessionId (e.g. after resume). We match by checking if the PID's
    JSONL is the same file as our session's JSONL (via the project directory).

    As a simpler heuristic: try all live PIDs and find any whose parent window
    exists. Match by checking if the PID file's cwd or sessionId relates to ours.
    """
    raw_id = sess.session_id.split(":", 1)[-1]
    sessions_dir = Path.home() / ".claude" / "sessions"

    for json_file in sessions_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            pid = data.get("pid")
            if not pid:
                continue

            # Match 1: session ID matches directly
            if data.get("sessionId") == raw_id:
                hwnd = _get_parent_window(pid)
                if hwnd:
                    return hwnd
                continue

            # Match 2: check if this PID's JSONL is in the same project
            # directory as ours (handles resumed sessions)
            their_sid = data.get("sessionId", "")
            if their_sid:
                projects_dir = Path.home() / ".claude" / "projects"
                for project_dir in projects_dir.iterdir():
                    if not project_dir.is_dir():
                        continue
                    our_jsonl = project_dir / f"{raw_id}.jsonl"
                    their_jsonl = project_dir / f"{their_sid}.jsonl"
                    if our_jsonl.is_file() and their_jsonl.is_file():
                        hwnd = _get_parent_window(pid)
                        if hwnd:
                            return hwnd
                    # Also check if our JSONL is directly this PID's
                    if our_jsonl.is_file():
                        # Check if this PID's CWD matches the project dir
                        pid_cwd = data.get("cwd", "")
                        proj_name = project_dir.name
                        if pid_cwd and proj_name.startswith("C--"):
                            # Encode pid_cwd same way Claude does
                            encoded = pid_cwd.replace("\\", "-").replace("/", "-").replace(":", "-")
                            if encoded.lower() == proj_name.lower():
                                hwnd = _get_parent_window(pid)
                                if hwnd:
                                    return hwnd
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _find_copilot_window(sess: Session) -> int | None:
    """Find window for a Copilot CLI session.
    Copilot doesn't store PIDs directly, so for now we can't find the window.
    Returns None (will launch a new resume window instead)."""
    return None


def _get_parent_window(target_pid: int) -> int | None:
    """Walk up the process tree using ctypes to find the first ancestor with a window."""
    if sys.platform != "win32":
        return None

    import ctypes.wintypes

    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.wintypes.DWORD),
            ("cntUsage", ctypes.wintypes.DWORD),
            ("th32ProcessID", ctypes.wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", ctypes.wintypes.DWORD),
            ("cntThreads", ctypes.wintypes.DWORD),
            ("th32ParentProcessID", ctypes.wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    kernel32 = ctypes.windll.kernel32

    # Build pid -> parent_pid map
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return None

    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
    parent_map = {}

    if kernel32.Process32First(snap, ctypes.byref(pe)):
        while True:
            parent_map[pe.th32ProcessID] = pe.th32ParentProcessID
            if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                break
    kernel32.CloseHandle(snap)

    # Walk up from target_pid, check each for a window
    current = target_pid
    for _ in range(8):
        try:
            import ctypes.wintypes
            hwnd = user32.GetTopWindow(None)
            # Use EnumWindows approach to find window owned by this PID
            found_hwnd = _find_window_for_pid(current)
            if found_hwnd:
                return found_hwnd
        except Exception:
            pass
        parent = parent_map.get(current)
        if not parent or parent == current:
            break
        current = parent

    return None


# Cache for EnumWindows callback results
_enum_result = []


def _find_window_for_pid(target_pid: int) -> int | None:
    """Find a visible window owned by a specific PID."""
    if sys.platform != "win32":
        return None

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    result = [None]

    def callback(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == target_pid:
            # Check it has a title (is a real window)
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                result[0] = hwnd
                return False  # stop enumeration
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return result[0]


def _start_in_new_window(cmd: list[str], cwd: str) -> None:
    import threading, time as _time

    if _has_wt():
        subprocess.Popen(
            ["wt", "nt", "-d", cwd] + cmd,
            creationflags=_detached(),
        )
    else:
        cmd_str = 'start "recon-plus" ' + " ".join(cmd)
        subprocess.Popen(
            cmd_str,
            cwd=cwd,
            shell=True,
            creationflags=_detached(),
        )

    # Focus the new window after it appears
    def _focus_new():
        for _ in range(10):
            _time.sleep(0.5)
            hwnd = _find_window_by_title("recon-plus")
            if hwnd:
                user32.ShowWindow(hwnd, 9)
                user32.SetForegroundWindow(hwnd)
                return

    if sys.platform == "win32":
        threading.Thread(target=_focus_new, daemon=True).start()


def _find_window_by_title(title: str) -> int | None:
    """Find a visible window by exact title."""
    if sys.platform != "win32":
        return None

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    result = [None]
    buf = ctypes.create_unicode_buffer(256)

    def callback(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value == title:
            result[0] = hwnd
            return False
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return result[0]


def _detached() -> int:
    if sys.platform == "win32":
        return subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return 0
