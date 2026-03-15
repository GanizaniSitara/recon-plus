# recon-plus

TUI dashboard for managing GitHub Copilot CLI sessions on Windows.

## Quick start

```bash
python -m pip install -e .
python -m recon_plus          # TUI dashboard
python -m recon_plus --json   # JSON output
```

## Architecture

- `recon_plus/config.py` — reads `~/.copilot/config.json`
- `recon_plus/session.py` — discovers sessions from `~/.copilot/session-state/*/workspace.yaml`, parses `events.jsonl` incrementally
- `recon_plus/status.py` — determines session status (New/Working/Idle/Done) from filesystem signals
- `recon_plus/launcher.py` — launches/resumes sessions via `wt.exe` or `cmd /c start`
- `recon_plus/app.py` — Textual TUI app
- `recon_plus/widgets/table_view.py` — DataTable-based session list

## Copilot CLI session data layout

```
~/.copilot/session-state/{uuid}/
├── workspace.yaml    # id, cwd, git info, summary, timestamps
├── events.jsonl      # full event stream (session.start, assistant.message, tool.*, session.shutdown)
├── session.db        # SQLite with todos/todo_deps (fleet tasks)
├── plan.md           # session plan (if any)
├── checkpoints/      # compaction checkpoints
├── files/            # file snapshots
└── research/         # research artifacts
```

## Key event types in events.jsonl

- `session.start` — session metadata, copilot version, git context
- `assistant.message` — model responses with `outputTokens`
- `tool.execution_complete` — includes `model` field
- `session.model_change` — `newModel` field
- `session.shutdown` — `totalPremiumRequests`, `codeChanges`
