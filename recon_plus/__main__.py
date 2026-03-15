"""Entry point for recon-plus."""

from __future__ import annotations

import json
import sys


def main() -> None:
    args = sys.argv[1:]

    if "--json" in args:
        _json_mode()
        return

    if "--purge" in args:
        from .session import purge_empty_sessions
        count = purge_empty_sessions()
        print(f"Purged {count} empty session(s)")
        return

    if "--help" in args or "-h" in args:
        print("Usage: recon-plus [--json | --purge]")
        print()
        print("  TUI dashboard for GitHub Copilot CLI sessions.")
        print()
        print("Options:")
        print("  --json    Output sessions as JSON and exit")
        print("  --purge   Delete empty/unused sessions and exit")
        print()
        print("Keybindings:")
        print("  j/k       Navigate sessions")
        print("  Enter     Resume selected session in new terminal")
        print("  n         Launch new copilot session")
        print("  p         Purge empty sessions")
        print("  r         Refresh")
        print("  q         Quit")
        return

    from .app import ReconCopilotApp

    app = ReconCopilotApp()
    app.run()


def _json_mode() -> None:
    from .session import discover_sessions
    from .status import determine_status

    sessions = discover_sessions()
    output = []
    for s in sessions:
        output.append(
            {
                "session_id": s.session_id,
                "provider": s.provider,
                "summary": s.summary,
                "repository": s.repository,
                "branch": s.branch,
                "cwd": s.cwd,
                "model": s.model,
                "status": determine_status(s),
                "total_output_tokens": s.total_output_tokens,
                "total_premium_requests": s.total_premium_requests,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "last_event_type": s.last_event_type,
                "last_event_time": s.last_event_time,
            }
        )
    print(json.dumps({"sessions": output}, indent=2))


if __name__ == "__main__":
    main()
