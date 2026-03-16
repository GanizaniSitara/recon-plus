"""Dialog for launching a new agent session with directory selection."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from ..preferences import default_agent
from ..session import Session


class NewSessionResult(Message):
    def __init__(self, cwd: str, agent: str) -> None:
        super().__init__()
        self.cwd = cwd
        self.agent = agent


class NewSessionDialog(ModalScreen[str | None]):
    """Modal dialog to pick a directory for a new session."""

    CSS = """
    NewSessionDialog {
        align: center middle;
    }
    #new-session-box {
        width: 70;
        height: auto;
        max-height: 20;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    #dir-input {
        margin: 1 0;
        border: solid $accent;
    }
    #recent-list {
        height: auto;
        max-height: 8;
        margin: 0 0 1 0;
    }
    #hint-label {
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, sessions: list[Session], preselect_cwd: str = "") -> None:
        super().__init__()
        self._preselect = preselect_cwd
        self._recent_dirs = self._build_recent(sessions)
        self._agent = default_agent()

    def _build_recent(self, sessions: list[Session]) -> list[str]:
        """Get up to 4 unique recent directories from sessions."""
        seen: OrderedDict[str, None] = OrderedDict()
        # Put preselected first
        if self._preselect:
            seen[self._preselect] = None
        for s in sessions:
            if s.cwd and s.cwd not in seen:
                seen[s.cwd] = None
            if len(seen) >= 6:
                break
        return list(seen.keys())

    def compose(self) -> ComposeResult:
        with Vertical(id="new-session-box"):
            yield Label(f"New {self._agent} session", id="title-label")
            yield Input(
                value=self._preselect,
                placeholder="Working directory...",
                id="dir-input",
            )
            yield OptionList(
                *[Option(d, id=d) for d in self._recent_dirs],
                id="recent-list",
            )
            yield Label(
                "Enter to launch | Esc to cancel | Select a recent dir or type a path",
                id="hint-label",
            )

    def on_mount(self) -> None:
        self.query_one("#dir-input", Input).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        selected = str(event.option.id)
        inp = self.query_one("#dir-input", Input)
        inp.value = selected
        inp.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "dir-input":
            cwd = event.value.strip()
            if cwd:
                self.dismiss(cwd)

    def action_cancel(self) -> None:
        self.dismiss(None)
