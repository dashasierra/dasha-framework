"""Single-line text boxes."""

import re
import time
from collections.abc import Callable
from typing import NamedTuple

from dasha.canvas import Canvas, Rect
from dasha.clipboard import CLIPBOARD, Clipboard
from dasha.events import MouseEvent
from dasha.scrollbar import LEFT, RIGHT
from dasha.shortcuts import Shortcuts
from dasha.style import BLUE, BRIGHT_WHITE, CYAN, GREEN, Style
from dasha.widgets.base import Widget
from dasha.menu import Menu
from dasha.widgets.editing import (
    UndoHistory,
    edit_menu,
    word_left,
    word_right,
)


class _Before(NamedTuple):
    """Text, cursor and selection to undo to."""

    text: str
    cursor: int
    anchor: int | None


class TextBox(Widget):
    """A single line of editable text.

    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param text: Initial text.
    :param max_length: Longest text allowed, if limited.
    :param pattern: Regular expression the text must fully match, if any.
    :param on_change: Called with the box after each user change.
    :param name: Widget name.
    :param status: Status bar text.
    """

    focusable = True
    style: Style = Style(foreground=BLUE, background=CYAN)
    """The style of the box and its text."""
    focused_style: Style = Style(foreground=BRIGHT_WHITE, background=CYAN, bold=True)
    """Style while focused."""
    selected_style: Style = Style(foreground=BRIGHT_WHITE, background=GREEN, bold=True)
    """The style of selected text, while the box has the focus."""
    arrow_style: Style = Style(foreground=CYAN, background=BLUE, bold=True)
    """Style of the scroll arrows."""
    min_width: int = 3
    """Narrowest width."""
    clipboard: Clipboard = CLIPBOARD
    """Clipboard for cut, copy and paste."""
    undo_limit: int | None = 20
    """Most changes Ctrl+Z can undo, or ``None``."""
    scroll_delay: float = 0.01
    """Seconds per character when drag-scrolling."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        row: int,
        column: int,
        width: int,
        *,
        text: str = "",
        max_length: int | None = None,
        pattern: "str | re.Pattern[str] | None" = None,
        on_change: Callable[["TextBox"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        if width < self.min_width:
            raise ValueError(f"a text box must be at least {self.min_width} wide")
        if max_length is not None and max_length < 0:
            raise ValueError("max_length must not be negative")
        super().__init__(row, column, width, name=name, status=status)
        self.max_length = max_length
        self.pattern: re.Pattern[str] | None = (
            re.compile(pattern) if isinstance(pattern, str) else pattern
        )
        self.on_change = on_change
        self._text = ""
        self._cursor = 0  # where typing goes: 0 to len(text)
        self._anchor: int | None = None  # the other end of the selection
        self._first = 0  # the first character shown
        self._history: UndoHistory[_Before] = UndoHistory()
        self._typing_at: int | None = None  # where typing adds to the last step
        self._scrolling = 0  # -1 or 1 while a drag is held over an arrow
        self._next_scroll = 0.0  # when, by time.monotonic, to scroll again
        self.text = text

    # The text

    @property
    def text(self) -> str:
        """The text."""
        return self._text

    @text.setter
    def text(self, text: str) -> None:
        if not self.accepts(text):
            raise ValueError(f"{text!r} is not allowed in this text box")
        self._text = text
        self._cursor = len(text)
        self._anchor = None
        self._first = 0
        self._history.clear()

    @property
    def value(self) -> str:
        return self._text

    @property
    def cursor(self) -> int:
        """Cursor index."""
        return self._cursor

    @cursor.setter
    def cursor(self, position: int) -> None:
        self._move(position, extend=False)

    def _move(self, position: int, extend: bool) -> None:
        """Move the cursor.

        :param position: New index.
        :param extend: Whether to extend the selection.
        """
        if not extend:
            self._anchor = None
        elif self._anchor is None:
            self._anchor = self._cursor
        self._cursor = max(0, min(position, len(self._text)))

    # The selection

    @property
    def selection(self) -> tuple[int, int] | None:
        """Selected ``(start, end)``, or ``None``."""
        if self._anchor is None or self._anchor == self._cursor:
            return None
        return min(self._anchor, self._cursor), max(self._anchor, self._cursor)

    @property
    def selected_text(self) -> str:
        """The selected text, which is empty when nothing is selected."""
        selection = self.selection
        return "" if selection is None else self._text[selection[0] : selection[1]]

    def select(self, start: int, end: int) -> None:
        """Select a range.

        :param start: Start index.
        :param end: End index, where the cursor goes.
        """
        self._anchor = max(0, min(start, len(self._text)))
        self._cursor = max(0, min(end, len(self._text)))

    def select_all(self) -> None:
        """Select all the text."""
        self.select(0, len(self._text))

    # The clipboard

    def copy(self) -> bool:
        """Copy the selection; return whether anything was selected."""
        if self.selection is None:
            return False
        self.clipboard.copy_text(self.selected_text)
        return True

    def cut(self) -> bool:
        """Cut the selection; return whether it was cut."""
        selection = self.selection
        if selection is None:
            return False
        start, end = selection
        remaining = self._text[:start] + self._text[end:]
        if not self.accepts(remaining):
            return False
        self.copy()
        self._edit(remaining, start)
        return True

    def paste(self) -> bool:
        """Paste the clipboard's text; return whether it was pasted."""
        pasted = self.clipboard.text
        return pasted is not None and self.insert(pasted)

    def handle_paste(self, text: str) -> bool:
        """Insert pasted text.

        :param text: The pasted text.
        """
        return self.insert(text.removesuffix("\n").removesuffix("\r"))

    def insert(self, text: str) -> bool:
        """Insert text; return whether it was accepted.

        :param text: The text.
        """
        if not text:
            return False
        start, end = self.selection or (self._cursor, self._cursor)
        result = self._text[:start] + text + self._text[end:]
        if result == self._text or not self.accepts(result):
            return False
        self._edit(result, start + len(text))
        return True

    def accepts(self, text: str) -> bool:
        """Whether the box may hold some text.

        :param text: The text.
        """
        if not text:
            return True
        if not text.isprintable() and any(
            char in "\n\r" or "\ud800" <= char <= "\udfff" for char in text
        ):
            return False
        if self.max_length is not None and len(text) > self.max_length:
            return False
        return self.pattern is None or self.pattern.fullmatch(text) is not None

    def _edit(self, text: str, cursor: int, typed: str = "") -> None:
        """Make a change if allowed.

        :param text: The new text.
        :param cursor: The new cursor index.
        :param typed: The character typed, if any.
        """
        if not self.accepts(text):
            return
        if text == self._text:
            self.cursor = cursor
            return
        typing_on = (
            typed
            and not typed.isspace()
            and self.selection is None
            and self._typing_at == self._cursor
        )
        if not typing_on:
            before = _Before(self._text, self._cursor, self._anchor)
            self._history.push(before, self.undo_limit)
        self._text = text
        self.cursor = cursor
        self._typing_at = self._cursor if typed else None
        if self.on_change is not None:
            self.on_change(self)

    @property
    def can_undo(self) -> bool:
        """Whether there is a change to undo."""
        return len(self._history) > 0

    copies_out: bool = True
    """Whether text can be copied out."""

    def popup_menu(self, shortcuts: Shortcuts) -> Menu | None:
        """The context menu.

        :param shortcuts: Key bindings shown in the menu.
        """
        if self.context_menu is not None:
            return self.context_menu
        return edit_menu(self, shortcuts, copies=self.copies_out)

    def undo(self) -> bool:
        """Undo the latest change; return whether there was one."""
        step = self._history.pop()
        if step is None:
            return False
        self._history.undone(self._restore(step))
        return True

    def redo(self) -> bool:
        """Redo the latest undone change; return whether there was one."""
        step = self._history.pop_redo()
        if step is None:
            return False
        self._history.push(self._restore(step), self.undo_limit, redoing=True)
        return True

    def _restore(self, step: _Before) -> _Before:
        """Restore a step; return the state replaced.

        :param step: The step to restore.
        """
        now = _Before(self._text, self._cursor, self._anchor)
        self._text, self._cursor, self._anchor = step.text, step.cursor, step.anchor
        self._typing_at = None
        if self.on_change is not None:
            self.on_change(self)
        return now

    # Layout

    def min_size(self) -> tuple[int, int]:
        return self.min_width, 1

    @property
    def visible_width(self) -> int:
        """Characters shown at once."""
        return self.rect.width - 2

    @property
    def first_visible(self) -> int:
        """Index of the first character shown."""
        visible, cursor = self.visible_width, self._cursor
        # After the last character, the cursor may use the right-hand arrow
        # column, which is blank then: a box max_length + 2 wide shows it all.
        room = visible + 1 if cursor == len(self._text) else visible
        if cursor < self._first:
            self._first = cursor
        elif cursor >= self._first + room:
            self._first = cursor - room + 1
        self._first = max(0, min(self._first, len(self._text) - visible))
        return self._first

    @property
    def has_more_left(self) -> bool:
        """Whether text is off to the left."""
        return self.first_visible > 0

    @property
    def has_more_right(self) -> bool:
        """Whether text is off to the right."""
        return len(self._text) > self.first_visible + self.visible_width

    # Drawing and input

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        row = origin.row + self.rect.row
        column = origin.column + self.rect.column
        first, visible = self.first_visible, self.visible_width
        style = self.focused_style if focused else self.style
        shown = self._text[first : first + visible].ljust(visible)
        canvas.write(row, column, " " + shown + " ", style, clip=origin)
        selection = self.selection if focused else None
        if selection is not None:
            start = max(selection[0], first)
            end = min(selection[1], first + visible)
            if start < end:
                canvas.write(
                    row,
                    column + 1 + start - first,
                    self._text[start:end],
                    self.selected_style,
                    clip=origin,
                )
        if self.has_more_left:
            canvas.write(row, column, LEFT, self.arrow_style, clip=origin)
        if self.has_more_right:
            right = column + visible + 1
            canvas.write(row, right, RIGHT, self.arrow_style, clip=origin)
        if focused:
            canvas.place_cursor(row, column + 1 + self._cursor - first)

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Edit the text.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        for action in ("next_widget", "previous_widget", "dialog_cancel"):
            if shortcuts.matches(action, key):
                return False
        text, cursor = self._text, self._cursor
        # With text selected, Left and Right go to its start or end.
        start, end = self.selection or (cursor - 1, cursor + 1)
        moves = {
            "text_left": (start, False),
            "text_right": (end, False),
            "text_home": (0, False),
            "text_end": (len(text), False),
            "text_select_left": (cursor - 1, True),
            "text_select_right": (cursor + 1, True),
            "text_select_home": (0, True),
            "text_select_end": (len(text), True),
            "text_word_left": (word_left(text, cursor), False),
            "text_word_right": (word_right(text, cursor), False),
            "text_select_word_left": (word_left(text, cursor), True),
            "text_select_word_right": (word_right(text, cursor), True),
        }
        for action, (position, extend) in moves.items():
            if shortcuts.matches(action, key):
                self._move(position, extend)
                return True
        commands: dict[str, Callable[[], object]] = {
            "text_undo": self.undo,
            "text_redo": self.redo,
            "text_select_all": self.select_all,
            "text_cut": self.cut,
            "text_copy": self.copy,
            "text_paste": self.paste,
        }
        for action, command in commands.items():
            if shortcuts.matches(action, key):
                command()
                return True
        return self._typing_key(key, shortcuts)

    def _typing_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Delete, clear or type.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        text, cursor = self._text, self._cursor
        start, end = self.selection or (cursor, cursor)
        if self.selection is None:
            # Nothing selected: Backspace and Delete take one character.
            edits = {
                "text_backspace": (
                    text[: max(0, cursor - 1)] + text[cursor:],
                    cursor - 1,
                ),
                "text_delete": (text[:cursor] + text[cursor + 1 :], cursor),
            }
        else:
            edits = dict.fromkeys(
                ("text_backspace", "text_delete"), (text[:start] + text[end:], start)
            )
        edits["text_clear"] = ("", 0)
        for action, (new_text, new_cursor) in edits.items():
            if shortcuts.matches(action, key):
                self._edit(new_text, new_cursor)
                return True
        if len(key) == 1 and key.isprintable():
            # Typing replaces the selection (or goes in at the cursor).
            self._edit(text[:start] + key + text[end:], start + 1, typed=key)
            return True
        return False

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Place the cursor or select with the mouse.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        del row
        if event.button != "left":
            return False
        offset = column - self.rect.column
        if event.action == "press" and event.clicks >= 2:
            self._scrolling = 0
            self.select_all()
            return True
        if event.action == "press":
            self._scrolling = 0
            if (offset <= 0 and self.has_more_left) or offset >= self.rect.width - 1:
                self._move(self._beyond(-1 if offset <= 0 else 1), event.shift)
            else:
                self._move(self._position_at(offset), event.shift)
            if self._anchor is None:
                self._anchor = self._cursor  # where a drag selects from
            return True
        if event.action == "drag":
            direction = 0
            if offset <= 0 and self.has_more_left:
                direction = -1
            elif offset >= self.rect.width - 1 and self.has_more_right:
                direction = 1
            if direction == 0:
                self._scrolling = 0
                self._move(self._position_at(offset), extend=True)
            elif direction != self._scrolling:
                # Onto an arrow: a character now, then one per scroll_delay.
                self._scrolling = direction
                self._scroll_step(time.monotonic())
            return True
        if event.action == "release":
            self._scrolling = 0
            return True
        return False

    def _position_at(self, offset: int) -> int:
        """The text index at a column.

        :param offset: Columns from the left edge.
        """
        first = self.first_visible
        index = first + max(0, min(offset - 1, self.visible_width))
        return min(index, len(self._text))

    def _beyond(self, direction: int) -> int:
        """The index just past what shows.

        :param direction: -1 for left, 1 for right.
        """
        first = self.first_visible
        return first - 1 if direction < 0 else first + self.visible_width

    def _scroll_step(self, now: float) -> None:
        """Select one more character while drag-scrolling.

        :param now: The current ``time.monotonic``.
        """
        self._move(self._beyond(self._scrolling), extend=True)
        self._next_scroll = now + self.scroll_delay
        if self._cursor in (0, len(self._text)):
            self._scrolling = 0  # selected all the way to that end

    def wake_time(self) -> float | None:
        return self._next_scroll if self._scrolling else None

    def on_timer(self, now: float) -> None:
        if self._scrolling:
            self._scroll_step(now)
