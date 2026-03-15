"""Session table widget for the dashboard."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Footer, Static

from .. import config
from ..session import Session
from ..status import Status, determine_status


class SessionSelected(Message):
    """Fired when user presses Enter on a session."""

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session


class SessionDeleteRequest(Message):
    """Fired when user presses x on a session."""

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session


class SessionTable(Vertical):
    """DataTable showing all sessions."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("n", "new_session", "New"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._sessions: list[Session] = []

    def compose(self) -> ComposeResult:
        table = DataTable(id="session-table", cursor_type="row")
        table.fixed_columns = 2  # # and Src stay fixed
        yield table

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("#", width=4)
        table.add_column("Src", width=4)
        table.add_column("Status", width=10)
        table.add_column("Summary")  # stretches
        table.add_column("Project", width=20)
        table.add_column("Directory", width=22)
        table.add_column("Model", width=16)
        table.add_column("Reqs", width=5)
        table.add_column("Size", width=6)
        table.add_column("Activity", width=10)

    def update_sessions(self, sessions: list[Session]) -> None:
        table = self.query_one(DataTable)

        # Remember cursor position
        saved_row = table.cursor_row

        self._sessions = sessions
        table.clear()

        for i, sess in enumerate(sessions, 1):
            status = determine_status(sess)
            dot = Status.DOTS.get(status, "")
            status_cell = f"{dot} {status}"

            model = _short_model(sess.model)
            if not model or model == "-":
                if sess.provider == "copilot":
                    model = _short_model(config.default_model())
            effort = config.reasoning_effort() if sess.provider == "copilot" else ""
            if effort and effort != "default" and model != "-":
                model = f"{model}({effort})"
            requests = str(sess.total_premium_requests) if sess.total_premium_requests else "-"

            table.add_row(
                str(i),
                sess.provider_tag,
                status_cell,
                sess.summary_display,
                sess.project_display,
                sess.short_cwd,
                model,
                requests,
                sess.size_display,
                sess.last_activity_display,
                key=sess.session_id,
            )

        # Restore cursor position
        if saved_row is not None and sessions:
            table.move_cursor(row=min(saved_row, len(sessions) - 1))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value)
        for sess in self._sessions:
            if sess.session_id == key:
                self.post_message(SessionSelected(sess))
                break

    def get_selected_session(self) -> Session | None:
        table = self.query_one(DataTable)
        if table.cursor_row is not None and table.cursor_row < len(self._sessions):
            return self._sessions[table.cursor_row]
        return None


def _short_model(model: str) -> str:
    if not model:
        return "-"
    replacements = {
        "claude-opus-4.6": "Opus 4.6",
        "claude-opus-4-6": "Opus 4.6",
        "claude-sonnet-4.6": "Sonnet 4.6",
        "claude-sonnet-4-6": "Sonnet 4.6",
        "claude-sonnet-4-5-20250514": "Sonnet 4.5",
        "claude-haiku-4-5-20251001": "Haiku 4.5",
        "gpt-5.4": "GPT-5.4",
        "gpt-5.3": "GPT-5.3",
        "gpt-5.3-codex": "GPT-5.3 Codex",
        "gpt-4o": "GPT-4o",
        "o3": "o3",
        "o4-mini": "o4-mini",
    }
    return replacements.get(model, model)
