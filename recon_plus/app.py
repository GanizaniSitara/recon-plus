"""Textual app for the recon-plus dashboard."""

from __future__ import annotations

from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.widgets import Footer, Header, Input

from . import config, launcher
from .preferences import AGENTS, default_agent, set_default_agent
from .session import Session, delete_session, discover_sessions, purge_empty_sessions
from .status import Status, determine_status
from .widgets.new_session_dialog import NewSessionDialog
from .widgets.table_view import SessionDeleteRequest, SessionSelected, SessionTable
from .widgets.tamagotchi_view import TamagotchiView

PROVIDERS = ["all", "copilot", "claude", "codex"]
PROVIDER_LABELS = {"all": "All", "copilot": "COP", "claude": "CC", "codex": "CDX"}
SORT_MODES = ["time", "directory", "status", "model"]
SCOPE_MODES = ["active", "all"]  # active = hide Done


class ReconCopilotApp(App):
    """TUI dashboard for GitHub Copilot CLI sessions."""

    TITLE = "recon-plus"
    CSS = """
    Screen {
        background: $surface;
    }
    #session-table {
        height: 1fr;
    }
    DataTable {
        height: 1fr;
    }
    DataTable > .datatable--header {
        text-style: bold;
        color: $accent;
    }
    Header {
        dock: top;
        height: 1;
    }
    HeaderTitle {
        content-align: center middle;
    }
    FooterKey.-command-palette {
        border-left: none;
    }
    Footer {
        scrollbar-size: 0 0;
    }
    Toast {
        max-height: 1;
        padding: 0 1;
        margin: 0;
    }
    TamagotchiView {
        height: 1fr;
        overflow-y: auto;
    }
    #search-bar {
        dock: bottom;
        height: 1;
        margin: 0;
        padding: 0 1;
        display: none;
    }
    #search-bar.visible {
        display: block;
    }
    """

    ENABLE_COMMAND_PALETTE = True

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("n", "new_session", "New"),
        Binding("f", "toggle_filter", "Filter"),
        Binding("s", "toggle_sort", "Sort"),
        Binding("a", "toggle_scope", "Active/All"),
        Binding("v", "toggle_view", "View"),
        Binding("slash", "search", "Search"),
        Binding("x", "delete_selected", "Delete"),
        Binding("p", "purge", "Purge"),
        Binding("enter", "resume_selected", "Resume", show=False),
        Binding("escape", "cancel_search", "Cancel", show=False),
    ]

    _pending_delete: Session | None = None
    _view_mode: str = "table"
    _tick: int = 0

    def __init__(self) -> None:
        super().__init__()
        self._prev_sessions: dict[str, Session] = {}
        self._all_sessions: list[Session] = []
        self._filter_idx = 0
        self._sort_idx = 0
        self._scope_idx = 0  # 0=active, 1=all
        self._search_query = ""
        self._searching = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False, icon=">>")
        yield SessionTable()
        tama = TamagotchiView()
        tama.display = False
        yield tama
        yield Input(placeholder="Search sessions...", id="search-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._do_refresh()
        self.set_interval(2.0, self._do_refresh)

    def _do_refresh(self) -> None:
        self._tick += 1
        if self._view_mode == "table" or self._tick % 2 == 0:
            self._all_sessions = discover_sessions(prev=self._prev_sessions)
            self._prev_sessions = {s.session_id: s for s in self._all_sessions}
        self._update_view()

    def _update_view(self) -> None:
        sessions = self._filtered_sorted()
        if self._view_mode == "table":
            self.query_one(SessionTable).update_sessions(sessions)
        else:
            self.query_one(TamagotchiView).update_sessions(sessions, self._tick)
        self._update_title()

    def _filtered_sorted(self) -> list[Session]:
        provider = PROVIDERS[self._filter_idx]
        if provider == "all":
            sessions = list(self._all_sessions)
        else:
            sessions = [s for s in self._all_sessions if s.provider == provider]

        # Scope filter
        if SCOPE_MODES[self._scope_idx] == "active":
            sessions = [s for s in sessions if determine_status(s) != Status.DONE]

        # Search filter
        if self._search_query:
            q = self._search_query.lower()
            sessions = [
                s for s in sessions
                if q in s.summary.lower()
                or q in s.repository.lower()
                or q in s.branch.lower()
                or q in s.cwd.lower()
                or q in s.model.lower()
                or q in s.provider.lower()
                or q in (s.last_event_type or "").lower()
            ]

        sort_mode = SORT_MODES[self._sort_idx]
        if sort_mode == "directory":
            sessions.sort(key=lambda s: (s.cwd.lower(), s.updated_at or ""))
        elif sort_mode == "status":
            order = {"Input": 0, "Working": 1, "Idle": 2, "New": 3, "Done": 4}
            sessions.sort(key=lambda s: (order.get(determine_status(s), 9), s.updated_at or ""))
        elif sort_mode == "model":
            sessions.sort(key=lambda s: (s.model or "zzz", s.updated_at or ""))

        return sessions

    def _update_title(self) -> None:
        parts = ["recon-plus"]
        # Provider filter
        if self._filter_idx != 0:
            parts.append(f"[{PROVIDER_LABELS[PROVIDERS[self._filter_idx]]}]")
        # Scope
        scope = SCOPE_MODES[self._scope_idx]
        if scope == "all":
            parts.append("{all}")
        # Sort
        sort_mode = SORT_MODES[self._sort_idx]
        if sort_mode != "time":
            parts.append(f"(by {sort_mode})")
        # Search
        if self._search_query:
            parts.append(f'"{self._search_query}"')
        self.title = " ".join(parts)

    # --- Actions ---

    def get_system_commands(self, screen) -> SystemCommand:
        yield from super().get_system_commands(screen)
        yield SystemCommand("Quit", "Exit recon-plus", self.action_quit)
        current = default_agent()
        for agent in AGENTS:
            marker = " *" if agent == current else ""
            yield SystemCommand(
                f"Default agent: {agent}{marker}",
                f"Set {agent} as the default for new sessions (n key)",
                lambda a=agent: self._set_agent(a),
            )

    def _set_agent(self, agent: str) -> None:
        set_default_agent(agent)
        self.notify(f"Default agent: {agent}")

    def action_toggle_view(self) -> None:
        try:
            table = self.query_one(SessionTable)
            tama = self.query_one(TamagotchiView)
            if self._view_mode == "table":
                self._view_mode = "tamagotchi"
                table.display = False
                tama.display = True
                tama.focus()
            else:
                self._view_mode = "table"
                table.display = True
                tama.display = False
            self._update_view()
        except Exception:
            pass

    def action_refresh(self) -> None:
        self._do_refresh()

    def action_toggle_filter(self) -> None:
        self._filter_idx = (self._filter_idx + 1) % len(PROVIDERS)
        self._update_view()
        self.notify(f"Filter: {PROVIDER_LABELS[PROVIDERS[self._filter_idx]]}")

    def action_toggle_sort(self) -> None:
        self._sort_idx = (self._sort_idx + 1) % len(SORT_MODES)
        self._update_view()
        self.notify(f"Sort: {SORT_MODES[self._sort_idx]}")

    def action_toggle_scope(self) -> None:
        self._scope_idx = (self._scope_idx + 1) % len(SCOPE_MODES)
        self._update_view()
        scope = SCOPE_MODES[self._scope_idx]
        total = len(self._all_sessions)
        done = sum(1 for s in self._all_sessions if determine_status(s) == Status.DONE)
        if scope == "active":
            self.notify(f"Active only ({total - done} shown, {done} done hidden)")
        else:
            self.notify(f"All sessions ({total})")

    def action_search(self) -> None:
        search_bar = self.query_one("#search-bar", Input)
        search_bar.add_class("visible")
        search_bar.value = self._search_query
        search_bar.focus()
        self._searching = True

    def action_cancel_search(self) -> None:
        if self._searching:
            search_bar = self.query_one("#search-bar", Input)
            search_bar.remove_class("visible")
            self._searching = False
            # Refocus the table
            if self._view_mode == "table":
                self.query_one(SessionTable).query_one("DataTable").focus()
        else:
            self.action_quit()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-bar":
            self._search_query = event.value
            self._update_view()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-bar":
            # Close search bar, keep query active
            search_bar = self.query_one("#search-bar", Input)
            search_bar.remove_class("visible")
            self._searching = False
            if self._view_mode == "table":
                self.query_one(SessionTable).query_one("DataTable").focus()

    def action_new_session(self) -> None:
        # Get cwd from selected row
        preselect = ""
        if self._view_mode == "table":
            sess = self.query_one(SessionTable).get_selected_session()
            if sess:
                preselect = sess.cwd
        elif self._view_mode == "tamagotchi":
            sess = self.query_one(TamagotchiView).get_selected_session()
            if sess:
                preselect = sess.cwd

        def _on_result(cwd: str | None) -> None:
            if cwd:
                agent = default_agent()
                launcher.launch_session(cwd=cwd, agent=agent)
                self.notify(f"New {agent} session in {cwd}")

        self.push_screen(
            NewSessionDialog(self._all_sessions, preselect_cwd=preselect),
            _on_result,
        )

    def action_resume_selected(self) -> None:
        if self._searching:
            self.action_cancel_search()
            return
        if self._view_mode == "tamagotchi":
            tama = self.query_one(TamagotchiView)
            sess = tama.get_selected_session()
        else:
            table = self.query_one(SessionTable)
            sess = table.get_selected_session()
        if sess:
            launcher.resume_session(sess)

    def action_delete_selected(self) -> None:
        table = self.query_one(SessionTable)
        sess = table.get_selected_session()
        if not sess:
            return
        if self._pending_delete and self._pending_delete.session_id == sess.session_id:
            delete_session(sess)
            self._pending_delete = None
            self._prev_sessions.pop(sess.session_id, None)
            self._do_refresh()
            self.notify(f"Deleted: {sess.summary_display}")
        else:
            self._pending_delete = sess
            self.notify(f"Press x again to delete: {sess.summary_display}")

    def on_key(self, event) -> None:
        if event.key != "x" and self._pending_delete:
            self._pending_delete = None

    def action_purge(self) -> None:
        count = purge_empty_sessions()
        self._prev_sessions.clear()
        self._do_refresh()
        self.notify(f"Purged {count} empty session(s)")

    def on_session_selected(self, event: SessionSelected) -> None:
        launcher.resume_session(event.session)
