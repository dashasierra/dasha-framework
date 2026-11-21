"""Paragraphs and line alignment."""

import textwrap
from collections.abc import Callable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.style import Style
from dasha.widgets.base import Widget, run_shortcut
from dasha.widgets.scrollbar import ScrollBar

ALIGNMENTS = ("left", "centre", "right", "justify")
"""The ways a paragraph, or a dialog's message, can be aligned."""


def align_lines(lines: list[str], width: int, align: str) -> list[tuple[int, str]]:
    """Lines aligned in a width, as (indent, text) pairs.

    :param lines: The lines.
    :param width: Width in columns.
    :param align: ``"left"``, ``"centre"``, ``"right"`` or ``"justify"``.
    """
    if align not in ALIGNMENTS:
        raise ValueError(f"align must be one of {', '.join(ALIGNMENTS)}")
    placed = []
    for number, line in enumerate(lines):
        if align == "centre":
            placed.append(((width - len(line)) // 2, line))
        elif align == "right":
            placed.append((width - len(line), line))
        elif align == "justify":
            last = number == len(lines) - 1 or not lines[number + 1].strip()
            placed.append((0, line if last else _justified(line, width)))
        else:
            placed.append((0, line))
    return [(max(0, offset), text) for offset, text in placed]


def _justified(line: str, width: int) -> str:
    """A line justified to a width.

    :param line: The line.
    :param width: Width in columns.
    """
    words = line.split()
    if len(words) < 2:
        return line
    gaps = len(words) - 1
    each, extra = divmod(max(0, width - sum(len(word) for word in words)), gaps)
    spaced = [
        word + " " * (each + (1 if gap < extra else 0))
        for gap, word in enumerate(words[:-1])
    ]
    return "".join(spaced) + words[-1]


def wrap(text: str, width: int) -> list[list[str]]:
    """Wrap text into lines, per original line.

    :param text: The text.
    :param width: Width in columns.
    """
    width = max(1, width)
    return [
        textwrap.wrap(line, width, replace_whitespace=False, drop_whitespace=True)
        or [""]
        for line in text.splitlines() or [""]
    ]


class Paragraph(Widget):  # pylint: disable=too-many-instance-attributes
    """Static wrapped text that can scroll.

    :param text: The text.
    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param height: Height in rows, or ``None`` to fit.
    :param align: ``"left"``, ``"centre"``, ``"right"`` or ``"justify"``.
    :param style: Style, or ``None`` for the window's.
    :param name: Widget name.
    :param status: Status bar text.
    """

    focusable = True
    wheel_rows = 3
    """How many lines one notch of the mouse wheel scrolls."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        text: str,
        row: int,
        column: int,
        width: int,
        height: int | None = None,
        *,
        align: str = "left",
        style: Style | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        if width < 2:
            raise ValueError("a paragraph needs at least two columns")
        align_lines([], width, align)  # refuses an alignment it does not know
        super().__init__(row, column, width, height or 1, name=name, status=status)
        self.align = align
        self.style = style
        self._fixed_height = height
        self._first = 0
        self._lines: list[tuple[int, str]] = []
        self.scroll_bar = ScrollBar(
            row, column + width - 1, 2, on_change=self._scrolled
        )
        self._bar_mouse = False
        self._text = ""
        self.text = text

    # The text

    @property
    def text(self) -> str:
        """The text."""
        return self._text

    @text.setter
    def text(self, text: str) -> None:
        self._text = text
        self._first = 0
        self._wrap()

    @property
    def value(self) -> str:
        return self._text

    @property
    def lines(self) -> list[str]:
        """The lines as shown, wrapped and aligned."""
        return [" " * offset + line for offset, line in self._lines]

    def _wrap(self) -> None:
        """Wrap the text to the width."""
        width = self.rect.width
        placed = self._placed(width)
        if self._fixed_height is not None and len(placed) > self._fixed_height:
            placed = self._placed(width - 1)
        self._lines = placed
        height = self._fixed_height if self._fixed_height is not None else len(placed)
        self.rect = Rect(self.rect.row, self.rect.column, max(1, height), width)
        self.scroll_to(self._first)

    def _placed(self, width: int) -> list[tuple[int, str]]:
        """Every wrapped line, aligned.

        :param width: Width in columns.
        """
        placed: list[tuple[int, str]] = []
        for group in wrap(self._text, width):
            placed += align_lines(group, width, self.align)
        return placed

    # Scrolling

    @property
    def is_scrollable(self) -> bool:
        """Whether there is more text than can be shown at once."""
        return len(self._lines) > self.rect.height

    def can_focus(self) -> bool:
        return self.is_scrollable

    @property
    def first_visible(self) -> int:
        """The first line shown."""
        return self._first

    def scroll_to(self, first: int) -> None:
        """Scroll to a line.

        :param first: First line to show.
        """
        last = max(0, len(self._lines) - self.rect.height)
        self._first = max(0, min(first, last))

    def _scrolled(self, scroll_bar: ScrollBar) -> None:
        self.scroll_to(scroll_bar.value)

    def _sync_bar(self) -> None:
        rect = self.rect
        self.scroll_bar.rect = Rect(rect.row, rect.right - 1, rect.height, 1)
        self.scroll_bar.set_range(max(0, len(self._lines) - rect.height), rect.height)
        self.scroll_bar.value = self._first

    def on_resize(self) -> None:
        self._wrap()

    def min_size(self) -> tuple[int, int]:
        return 2, 1

    # Drawing and input

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        del focused
        body = self.window.body_style if self.window is not None else Style()
        style = self.style or body
        row, column = origin.row + self.rect.row, origin.column + self.rect.column
        width = self.rect.width - (1 if self.is_scrollable else 0)
        shown = self._lines[self._first : self._first + self.rect.height]
        for number in range(self.rect.height):
            offset, line = shown[number] if number < len(shown) else (0, "")
            text = (" " * offset + line)[:width].ljust(width)
            canvas.write(row + number, column, text, style, clip=origin)
        if self.is_scrollable:
            self._sync_bar()
            self.scroll_bar.paint(canvas, origin, False)

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Scroll with the keys.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        if not self.is_scrollable:
            return False
        page = max(1, self.rect.height - 1)
        actions: dict[str, Callable[[], object]] = {
            "list_up": lambda: self.scroll_to(self._first - 1),
            "list_down": lambda: self.scroll_to(self._first + 1),
            "list_page_up": lambda: self.scroll_to(self._first - page),
            "list_page_down": lambda: self.scroll_to(self._first + page),
            "list_home": lambda: self.scroll_to(0),
            "list_end": lambda: self.scroll_to(len(self._lines)),
        }
        return run_shortcut(shortcuts, key, actions)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Scroll with the mouse.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        if not self.is_scrollable:
            return False
        self._sync_bar()
        on_bar = self.scroll_bar.rect.contains(row, column)
        if event.action == "press" and event.button == "left":
            self._bar_mouse = on_bar
        if self._bar_mouse:
            if event.action == "release":
                self._bar_mouse = False
            return self.scroll_bar.handle_mouse(event, row, column)
        if event.action == "scroll":
            back = event.button in ("up", "left")
            self.scroll_to(
                self._first + (-self.wheel_rows if back else self.wheel_rows)
            )
            return True
        return event.button == "left" and event.action in ("press", "drag", "release")

    def wake_time(self) -> float | None:
        return self.scroll_bar.wake_time()  # its arrows repeat while held

    def on_timer(self, now: float) -> None:
        self._sync_bar()
        self.scroll_bar.on_timer(now)
