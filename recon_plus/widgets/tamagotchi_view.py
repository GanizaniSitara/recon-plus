"""Tamagotchi view — pixel-art creatures from the original recon project."""

from __future__ import annotations

from collections import defaultdict

from rich.text import Text
from textual.widgets import Static

from ..session import Session
from ..status import Status, determine_status

# ── Exact sprites and palettes from gavraz/recon ─────────────────────
# RGB truecolor — requires PowerShell or Windows Terminal for proper rendering.

Sprite = list[list[int]]
Palette = list[str]  # index 0 = "" (transparent), rest = "rgb(r,g,b)"


def _rgb(r, g, b) -> str:
    return f"rgb({r},{g},{b})"


# --- Egg (New) ---
PAL_EGG: Palette = [
    "", _rgb(255, 250, 230), _rgb(220, 200, 170), _rgb(180, 220, 180),
]
SPRITE_EGG: Sprite = [
    [0,0,0,0,1,1,1,0,0,0],
    [0,0,0,1,1,1,1,1,0,0],
    [0,0,1,1,1,3,1,1,1,0],
    [0,0,1,1,1,1,1,1,1,0],
    [0,0,1,3,1,1,1,3,1,0],
    [0,0,1,1,1,1,1,1,1,0],
    [0,0,1,1,1,1,1,1,1,0],
    [0,0,0,1,2,1,2,1,0,0],
    [0,0,0,0,1,1,1,0,0,0],
    [0,0,0,0,0,0,0,0,0,0],
]

# --- Working (happy green blob) ---
PAL_WORKING: Palette = [
    "", _rgb(120, 220, 120), _rgb(80, 180, 80), _rgb(40, 40, 40),
    _rgb(255, 255, 255), _rgb(255, 150, 150), _rgb(200, 100, 80),
    _rgb(100, 200, 100), _rgb(255, 220, 60),
]
SPRITES_WORKING: list[Sprite] = [
    [  # Frame 0: happy, sparkles top
        [0,0,0,8,1,1,1,8,0,0],
        [0,0,1,1,1,1,1,1,0,0],
        [0,1,1,1,1,1,1,1,1,0],
        [0,1,3,4,1,1,3,4,1,0],
        [0,1,1,1,1,1,1,1,1,0],
        [0,5,1,1,6,6,1,1,5,0],
        [0,1,1,1,1,1,1,1,1,0],
        [0,0,1,1,1,1,1,1,0,0],
        [0,0,0,7,0,0,7,0,0,0],
        [0,0,0,0,0,0,0,0,0,0],
    ],
    [  # Frame 1: squinting
        [0,0,0,1,1,1,1,0,0,0],
        [0,0,1,1,1,1,1,1,0,0],
        [0,1,1,1,1,1,1,1,1,0],
        [0,1,1,3,1,1,3,1,1,0],
        [0,1,1,1,1,1,1,1,1,0],
        [0,5,1,6,1,1,6,1,5,0],
        [0,1,1,1,1,1,1,1,1,0],
        [0,0,1,1,1,1,1,1,0,0],
        [0,0,7,0,0,0,0,7,0,0],
        [0,0,0,0,0,0,0,0,0,0],
    ],
    [  # Frame 2: arms out, sparkles
        [0,0,8,1,1,1,1,8,0,0],
        [0,0,1,1,1,1,1,1,0,0],
        [0,1,1,1,1,1,1,1,1,0],
        [0,1,4,3,1,1,4,3,1,0],
        [0,1,1,1,1,1,1,1,1,0],
        [0,5,1,1,6,6,1,1,5,0],
        [8,1,1,1,1,1,1,1,1,8],
        [0,0,1,1,1,1,1,1,0,0],
        [0,0,0,7,0,0,7,0,0,0],
        [0,0,0,0,0,0,0,0,0,0],
    ],
]

# --- Idle (sleeping blue-grey blob) ---
PAL_IDLE: Palette = [
    "", _rgb(140, 160, 200), _rgb(110, 130, 170), _rgb(60, 60, 80),
    _rgb(180, 190, 220), _rgb(120, 140, 180), _rgb(200, 200, 255),
]
SPRITE_IDLE: Sprite = [
    [0,0,0,1,1,1,1,0,0,0],
    [0,0,1,1,1,1,1,1,0,6],
    [0,1,1,1,1,1,1,1,1,0],
    [0,1,3,3,1,1,3,3,1,6],
    [0,1,1,1,1,1,1,1,1,0],
    [0,1,1,1,1,1,1,1,1,0],
    [0,1,1,1,1,1,1,1,1,0],
    [0,0,1,1,1,1,1,1,0,0],
    [0,0,0,5,0,0,5,0,0,0],
    [0,0,0,0,0,0,0,0,0,0],
]

# --- Input/Attention (angry orange blob — from recon's Input status) ---
PAL_INPUT: Palette = [
    "", _rgb(255, 180, 60), _rgb(220, 150, 40), _rgb(40, 40, 40),
    _rgb(255, 255, 255), _rgb(255, 60, 60), _rgb(200, 140, 40),
    _rgb(255, 100, 100),
]
SPRITES_INPUT: list[Sprite] = [
    [  # Frame 0: angry brows down
        [0,0,0,1,1,1,1,0,0,0],
        [0,0,1,1,1,1,1,1,0,0],
        [0,1,5,1,1,1,1,5,1,0],
        [0,1,1,4,3,3,4,1,1,0],
        [0,7,1,1,1,1,1,1,7,0],
        [0,1,1,5,5,5,5,1,1,0],
        [0,1,1,1,1,1,1,1,1,0],
        [0,0,1,1,1,1,1,1,0,0],
        [0,0,0,6,0,0,6,0,0,0],
        [0,0,0,0,0,0,0,0,0,0],
    ],
    [  # Frame 1: brows shifted
        [0,0,0,1,1,1,1,0,0,0],
        [0,0,1,1,1,1,1,1,0,0],
        [0,1,1,5,1,1,5,1,1,0],
        [0,1,1,4,3,3,4,1,1,0],
        [0,7,1,1,1,1,1,1,7,0],
        [0,1,1,1,5,5,1,1,1,0],
        [0,1,1,1,1,1,1,1,1,0],
        [0,0,1,1,1,1,1,1,0,0],
        [0,0,6,0,0,0,0,6,0,0],
        [0,0,0,0,0,0,0,0,0,0],
    ],
    [  # Frame 2: wider stance
        [0,0,0,1,1,1,1,0,0,0],
        [0,0,1,1,1,1,1,1,0,0],
        [0,1,5,1,1,1,1,5,1,0],
        [0,1,1,3,4,4,3,1,1,0],
        [0,1,7,1,1,1,1,7,1,0],
        [0,1,5,1,5,5,1,5,1,0],
        [0,1,1,1,1,1,1,1,1,0],
        [0,0,1,1,1,1,1,1,0,0],
        [0,0,0,6,0,0,6,0,0,0],
        [0,0,0,0,0,0,0,0,0,0],
    ],
]

# --- Done (grey, sleeping) ---
PAL_DONE: Palette = [
    "", _rgb(100, 100, 100), _rgb(80, 80, 80), _rgb(50, 50, 50),
    _rgb(130, 130, 130), _rgb(90, 90, 90),
]
SPRITE_DONE: Sprite = [
    [0,0,0,1,1,1,1,0,0,0],
    [0,0,1,1,1,1,1,1,0,0],
    [0,1,1,1,1,1,1,1,1,0],
    [0,1,3,3,1,1,3,3,1,0],
    [0,1,1,1,1,1,1,1,1,0],
    [0,1,1,1,1,1,1,1,1,0],
    [0,1,1,1,1,1,1,1,1,0],
    [0,0,1,1,1,1,1,1,0,0],
    [0,0,0,5,0,0,5,0,0,0],
    [0,0,0,0,0,0,0,0,0,0],
]


def _get_sprite_and_palette(status: str, frame: int) -> tuple[Sprite, Palette]:
    if status == Status.NEW:
        return SPRITE_EGG, PAL_EGG
    if status == Status.WORKING:
        return SPRITES_WORKING[frame % 3], PAL_WORKING
    if status == Status.IDLE:
        return SPRITE_IDLE, PAL_IDLE
    return SPRITE_DONE, PAL_DONE


# ── Half-block renderer (exact same technique as recon) ──────────────

def _render_sprite_lines(sprite: Sprite, palette: Palette) -> list[Text]:
    lines = []
    rows = len(sprite)
    cols = len(sprite[0]) if rows else 0

    for y in range(0, rows, 2):
        text = Text()
        for x in range(cols):
            top = sprite[y][x]
            bot = sprite[y + 1][x] if y + 1 < rows else 0

            if top == 0 and bot == 0:
                text.append(" ")
            elif top == 0:
                text.append("\u2584", style=palette[bot])
            elif bot == 0:
                text.append("\u2580", style=palette[top])
            else:
                text.append("\u2580", style=f"{palette[top]} on {palette[bot]}")
        lines.append(text)
    return lines


# ── Card rendering ───────────────────────────────────────────────────

CARD_WIDTH = 16


def _render_card(sess: Session, tick: int, selected: bool = False) -> list[Text]:
    status = determine_status(sess)
    offset = sum(sess.session_id.encode()) % 7
    frame = ((tick + offset)) % 3 if status == Status.WORKING else 0

    sprite, palette = _get_sprite_and_palette(status, frame)
    sprite_lines = _render_sprite_lines(sprite, palette)

    lines: list[Text] = []
    pad = (CARD_WIDTH - 10) // 2
    for sl in sprite_lines:
        padded = Text(" " * pad)
        padded.append_text(sl)
        lines.append(padded)

    name = sess.summary_display[:CARD_WIDTH]
    name_style = "bold cyan underline" if selected else "bold white"
    lines.append(Text(f"{name:^{CARD_WIDTH}}", style=name_style))

    tag = sess.provider_tag
    branch = sess.branch or ""
    info = f"{tag} {branch}"[:CARD_WIDTH]
    lines.append(Text(f"{info:^{CARD_WIDTH}}", style="green"))

    color = Status.COLORS.get(status, "white")
    sel = ">> " if selected else "   "
    lines.append(Text(f"{sel}{status:^{CARD_WIDTH - 3}}", style=color))

    return lines


# ── TamagotchiView widget ────────────────────────────────────────────

class TamagotchiView(Static, can_focus=True):
    """Renders active sessions as pixel-art creatures grouped by directory."""

    BINDINGS = [
        ("j", "next", "Next"),
        ("k", "prev", "Prev"),
        ("down", "next", "Next"),
        ("up", "prev", "Prev"),
        ("enter", "select", "Jump"),
    ]

    def __init__(self) -> None:
        super().__init__("")
        self._sessions: list[Session] = []
        self._active: list[Session] = []
        self._tick = 0
        self._selected = 0

    def update_sessions(self, sessions: list[Session], tick: int) -> None:
        self._sessions = sessions
        self._tick = tick
        self._active = [s for s in sessions if determine_status(s) != Status.DONE]
        if self._active and self._selected >= len(self._active):
            self._selected = len(self._active) - 1
        self.update(self._render_all())

    def action_next(self) -> None:
        if self._active and self._selected < len(self._active) - 1:
            self._selected += 1
            self.update(self._render_all())

    def action_prev(self) -> None:
        if self._selected > 0:
            self._selected -= 1
            self.update(self._render_all())

    def action_select(self) -> None:
        if self._active and self._selected < len(self._active):
            from .table_view import SessionSelected
            self.post_message(SessionSelected(self._active[self._selected]))

    def get_selected_session(self) -> Session | None:
        if self._active and self._selected < len(self._active):
            return self._active[self._selected]
        return None

    def _render_all(self) -> Text:
        if not self._active:
            done_count = len(self._sessions)
            return Text(
                f"No active sessions ({done_count} done -- press v for table)",
                style="dim",
            )

        rooms: dict[str, list[Session]] = defaultdict(list)
        for sess in self._active:
            key = sess.short_cwd or "unknown"
            rooms[key].append(sess)

        order = {Status.WORKING: 0, Status.IDLE: 1, Status.NEW: 2, Status.DONE: 3}

        def room_priority(name: str) -> int:
            return min(order.get(determine_status(s), 9) for s in rooms[name])

        output = Text()

        for room_name in sorted(rooms, key=room_priority):
            sessions = rooms[room_name]
            has_working = any(determine_status(s) == Status.WORKING for s in sessions)
            border_style = "bold green" if has_working else "dim"

            header = f" {room_name} ({len(sessions)}) "
            output.append(f"--- {header} ", style=border_style)
            output.append("-" * max(0, 60 - len(header)), style=border_style)
            output.append("\n")

            cards = [
                _render_card(
                    s, self._tick,
                    selected=(s is self._active[self._selected] if self._selected < len(self._active) else False),
                )
                for s in sessions
            ]
            max_lines = max(len(c) for c in cards) if cards else 0

            for line_idx in range(max_lines):
                for card_idx, card in enumerate(cards):
                    if card_idx > 0:
                        output.append("  ")
                    if line_idx < len(card):
                        output.append_text(card[line_idx])
                    else:
                        output.append(" " * CARD_WIDTH)
                output.append("\n")

            output.append("\n")

        return output
