"""A terminal running a program in a widget."""

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from itertools import groupby
from operator import itemgetter

from dasha.canvas import UNSHOWABLE, Canvas, Rect
from dasha.clipboard import CLIPBOARD, TEXT
from dasha.events import MouseEvent
from dasha.menu import Menu, MenuItem
from dasha.pseudoterminal import PseudoTerminal, open_pty
from dasha.shell import shell_command
from dasha.shortcuts import DESKTOP_KEYS, Shortcuts
from dasha.style import DEFAULT, Style
from dasha.vt import SCROLLBACK, Line, Screen, encode_key, encode_mouse
from dasha.widgets.base import Widget

RESERVED_ACTIONS = DESKTOP_KEYS + ("open_menu", "command_prompt", "show_mouse")
"""Actions whose keys the desktop keeps."""

FEED_LIMIT = 65536
"""Most output bytes shown at once."""

WHEEL_LINES = 3
"""Lines per mouse wheel notch."""

PASTE_START, PASTE_END = "\x1b[200~", "\x1b[201~"
"""Bracketed paste markers."""


def shown_text(text: str) -> str:
    """How a cell's text is drawn.

    :param text: The cell's text.
    """
    if len(text) == 1:
        return text
    return " " if not text else UNSHOWABLE


class TerminalView(Widget):  # pylint: disable=too-many-instance-attributes
    """A command-line program in a terminal.

    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param height: Height in rows.
    :param command: Command to run, or ``None`` for the shell.
    :param cwd: Working folder, if any.
    :param env: Environment variables, if any.
    :param scrollback: Most lines kept off the top.
    :param on_output: Called with the view after output is shown.
    :param on_exit: Called with the view after the program ends.
    :param send_mouse: Whether the mouse goes to programs that ask.
    :param name: Widget name.
    :param status: Status bar text.
    """

    focusable = True

    default_style: Style = DEFAULT
    """Style for the program's default colours."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        row: int,
        column: int,
        width: int,
        height: int,
        *,
        command: Sequence[str] | None = None,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        scrollback: int = SCROLLBACK,
        on_output: "Callable[[TerminalView], object] | None" = None,
        on_exit: "Callable[[TerminalView], object] | None" = None,
        send_mouse: bool = True,
        name: str | None = None,
        status: str = 'Type "exit" or close window to terminate',
    ) -> None:
        super().__init__(row, column, width, height, name=name, status=status)
        self.command = list(command) if command else shell_command()
        """The command that runs."""
        self.cwd = cwd
        self.env = env
        self.on_output = on_output
        self.on_exit = on_exit
        self.screen = Screen(columns=width, lines=height, scrollback=scrollback)
        """What the program shows."""
        self.pty: PseudoTerminal = open_pty()
        """The pseudo-terminal the program runs in."""
        self.exit_code: int | None = None
        """Exit code, or ``-1`` if unknown."""
        self.send_mouse = send_mouse
        """Whether the mouse goes to programs that ask."""
        self.back = 0
        """How many lines the view is scrolled back into the scrollback."""
        self.selection: tuple[int, int, int, int] | None = None
        """Selected text range, as (line, column) pairs."""
        self._selecting = False
        self._anchor = (0, 0)
        self._pressed_for_program = False
        self._output = bytearray()
        self._output_lock = threading.Lock()
        self._output_due = False
        self._scrolled_off = 0
        self.context_menu = Menu(
            title="Terminal",
            items=[
                MenuItem(
                    label="&Copy",
                    action=self.copy,
                    status="Copies the selected text",
                    enabled=lambda: self.selection is not None,
                ),
                MenuItem(
                    label="&Paste",
                    action=self.paste,
                    status="Sends the clipboard's text to the program",
                ),
            ],
        )

    # The program

    def start(self) -> None:
        """Start the program. Raises ``OSError`` if it cannot be."""
        self.pty.on_output = self._arrived
        self.pty.on_exit = self._exited
        self.pty.start(
            argv=self.command,
            cwd=self.cwd,
            env=self.env,
            size=(self.screen.columns, self.screen.lines),
        )

    @property
    def is_mouse_for_program(self) -> bool:
        """Whether the mouse goes to the program now."""
        return (
            self.send_mouse and self.screen.is_tracking_mouse and self.exit_code is None
        )

    @property
    def is_running(self) -> bool:
        """Whether the program has started and not yet ended."""
        return self.pty.is_running

    def close(self) -> None:
        """End the program."""
        self.pty.close()

    def _arrived(self, data: bytes) -> None:
        """Queue output from the reader thread.

        :param data: The output.
        """
        with self._output_lock:
            self._output += data
            if self._output_due:
                return
            self._output_due = True
        self._call_soon(self._show_output)

    def _exited(self) -> None:
        self._call_soon(self._ended)

    def _call_soon(self, callback: Callable[[], object]) -> None:
        manager = self.window.manager if self.window is not None else None
        if manager is not None:
            manager.call_from_thread(callback)

    def _show_output(self) -> None:
        """Feed queued output to the screen."""
        with self._output_lock:
            data = bytes(self._output[:FEED_LIMIT])
            del self._output[:FEED_LIMIT]
            more = bool(self._output)
            self._output_due = more
        self._feed(data)
        if more:
            self._call_soon(self._show_output)

    def _feed(self, data: bytes) -> None:
        screen = self.screen
        screen.feed_bytes(data)
        replies = screen.take_replies()
        if replies:
            self.pty.write(replies)
        if self.back:  # scrolled back: stay on the lines shown
            self.scroll_back(screen.scrolled_off - self._scrolled_off)
        self._scrolled_off = screen.scrolled_off
        if self.on_output is not None:
            self.on_output(self)

    def _ended(self) -> None:
        """Show remaining output, then report the end."""
        with self._output_lock:
            data = bytes(self._output)
            self._output.clear()
            self._output_due = False
        self._feed(data)
        self.exit_code = self.pty.exit_code if self.pty.exit_code is not None else -1
        if self.on_exit is not None:
            self.on_exit(self)

    def on_resize(self) -> None:
        """The terminal follows the widget's size."""
        columns, lines = self.rect.width, self.rect.height
        self.screen.resize(columns=columns, lines=lines)
        self._scrolled_off = self.screen.scrolled_off
        self.selection = None
        self.scroll_back(0)
        if self.exit_code is None:
            self.pty.resize(columns=columns, lines=lines)

    def min_size(self) -> tuple[int, int]:
        return 2, 1

    # Drawing

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        rows = self.screen.shown_rows(self.back)[: self.rect.height]
        for index, line in enumerate(rows):
            self._paint_line(canvas, origin, index, line)
        if (
            focused
            and self.back == 0
            and self.screen.cursor_visible
            and self.exit_code is None
        ):
            row, column = self.screen.cursor
            canvas.place_cursor(
                origin.row + self.rect.row + row,
                origin.column + self.rect.column + column,
            )

    def _paint_line(self, canvas: Canvas, origin: Rect, index: int, line: Line) -> None:
        """Draw one row.

        :param canvas: Canvas to draw on.
        :param origin: The window's interior on screen.
        :param index: Row of the view.
        :param line: The line to draw.
        """
        row = origin.row + self.rect.row + index
        column = origin.column + self.rect.column
        selected = range(
            *self._selected_columns(self._line_number(index), self.rect.width)
        )
        cells = line[: self.rect.width]
        cells += [(" ", DEFAULT)] * (self.rect.width - len(cells))
        styled = [
            (
                shown_text(text),
                (
                    replace(style, reverse=not style.reverse)
                    if place in selected
                    else style
                ),
            )
            for place, (text, style) in enumerate(cells)
        ]
        for style, group in groupby(styled, key=itemgetter(1)):
            text = "".join(char for char, _ in group)
            canvas.write(row, column, text, self._in_colours(style), clip=origin)
            column += len(text)

    def _in_colours(self, style: Style) -> Style:
        """A program style with default colours filled in.

        :param style: The program's style.
        """
        default = self.default_style
        foreground = (
            default.foreground if style.foreground is None else style.foreground
        )
        background = (
            default.background if style.background is None else style.background
        )
        return replace(style, foreground=foreground, background=background)

    def _line_number(self, row: int) -> int:
        """A view row's line number.

        :param row: Row of the view.
        """
        return self.screen.scrolled_off - self.back + row

    def _selected_columns(self, number: int, width: int) -> tuple[int, int]:
        """A line's selected (start, end) columns.

        :param number: Line number.
        :param width: Line width.
        """
        if self.selection is None:
            return (0, 0)
        first, first_column, last, last_column = self._ordered()
        if not first <= number <= last:
            return (0, 0)
        start = first_column if number == first else 0
        end = last_column + 1 if number == last else width
        return (start, end)

    def _ordered(self) -> tuple[int, int, int, int]:
        """The selection, from its first cell to its last."""
        assert self.selection is not None
        line, column, end_line, end_column = self.selection
        if (end_line, end_column) < (line, column):
            return end_line, end_column, line, column
        return line, column, end_line, end_column

    # Scrolling back

    def scroll_back(self, lines: int) -> None:
        """Scroll back or forward.

        :param lines: Lines back; negative for forward.
        """
        self.back = max(0, min(self.back + lines, len(self.screen.scrollback)))

    def clear_scrollback(self) -> None:
        """Forget the lines scrolled off the top."""
        self.selection = None
        self.back = 0
        self.screen.clear_scrollback()

    # Input

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Send a key to the program.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        if any(shortcuts.matches(action, key) for action in RESERVED_ACTIONS):
            return False
        if shortcuts.matches("terminal_copy", key):
            self.copy()
            return True
        if shortcuts.matches("terminal_paste", key):
            self.paste()
            return True
        data = encode_key(key, app_cursor_keys=self.screen.app_cursor_keys)
        if data is None:
            return False
        self.send(data)
        return True

    def send(self, data: bytes) -> None:
        """Send input to the program.

        :param data: The input.
        """
        self.back = 0
        self.selection = None
        self.pty.write(data)

    def handle_paste(self, text: str) -> bool:
        """Send pasted text to the program.

        :param text: The pasted text.
        """
        text = text.replace("\r\n", "\r").replace("\n", "\r")
        if self.screen.bracketed_paste:
            text = PASTE_START + text.replace(PASTE_END, "") + PASTE_END
        self.send(text.encode("utf-8", "replace"))
        return True

    def paste(self) -> None:
        """Paste the clipboard's text."""
        item = CLIPBOARD.item
        if item is not None and item.type == TEXT and isinstance(item.data, str):
            self.handle_paste(item.data)

    def copy(self) -> None:
        """Copy the selected text to the clipboard."""
        text = self.selected_text()
        if text:
            CLIPBOARD.copy_text(text)

    def selected_text(self) -> str:
        """The selected text, as plain text (``""`` if none)."""
        if self.selection is None:
            return ""
        first, first_column, last, last_column = self._ordered()
        pieces: list[Line] = []
        for number in range(first, last + 1):
            line = self._line(number)
            if line is None:
                continue
            start = first_column if number == first else 0
            end = last_column + 1 if number == last else len(line)
            piece = Line(line[start:end])
            piece.wrapped = line.wrapped and number != last
            pieces.append(piece)
        return self.screen.text(pieces)

    def select_all(self) -> None:
        """Select everything: the scrollback and the screen."""
        screen = self.screen
        first = screen.scrolled_off - len(screen.scrollback)
        self.selection = (first, 0, screen.scrolled_off + screen.lines - 1, 1 << 16)

    def _line(self, number: int) -> Line | None:
        """A line by number, if still kept.

        :param number: Line number.
        """
        screen = self.screen
        index = number - (screen.scrolled_off - len(screen.scrollback))
        if index < 0:
            return None
        if index < len(screen.scrollback):
            return screen.scrollback[index]
        index -= len(screen.scrollback)
        return screen.rows[index] if index < screen.lines else None

    def popup_menu(self, shortcuts: Shortcuts) -> Menu | None:
        """Copy and Paste menu, unless the program takes the mouse.

        :param shortcuts: Key bindings shown in the menu.
        """
        return None if self.is_mouse_for_program else super().popup_menu(shortcuts)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Send, scroll or select with the mouse.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        if self._for_program(event):
            self._report(event, row, column)
            return True
        if event.action == "scroll":
            if event.button in ("up", "down"):
                self.scroll_back(WHEEL_LINES if event.button == "up" else -WHEEL_LINES)
                return True
            return False
        if event.button not in ("left", "none") and event.action != "release":
            return False
        row = min(max(0, row - self.rect.row), self.rect.height - 1)
        column = min(max(0, column - self.rect.column), self.rect.width - 1)
        number = self._line_number(row)
        if event.action == "press":
            self._selecting = True
            self.selection = None
            self._anchor = (number, column)
        elif event.action in ("drag", "release") and self._selecting:
            if (number, column) != self._anchor or self.selection is not None:
                self.selection = (*self._anchor, number, column)
            if event.action == "release":
                self._selecting = False
        return True

    def _for_program(self, event: MouseEvent) -> bool:
        """Whether mouse activity goes to the program.

        :param event: The mouse event.
        """
        if event.action == "press":
            self._pressed_for_program = self.is_mouse_for_program and not event.shift
            return self._pressed_for_program
        if event.action in ("drag", "release"):
            pressed = self._pressed_for_program
            if event.action == "release":
                self._pressed_for_program = False
            return pressed
        return self.is_mouse_for_program and not event.shift

    def _report(self, event: MouseEvent, row: int, column: int) -> None:
        """Report mouse activity to the program.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        row = min(max(0, row - self.rect.row), self.rect.height - 1)
        column = min(max(0, column - self.rect.column), self.rect.width - 1)
        data = encode_mouse(event, row, column, self.screen.mouse_modes)
        if data is not None:
            self.pty.write(data)
