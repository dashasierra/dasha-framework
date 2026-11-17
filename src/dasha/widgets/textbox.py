"""Text boxes: a single line of text, which can be typed in, selected, cut,
copied and pasted."""

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
    """What an undo goes back to: the text, cursor and selection as were."""

    text: str
    cursor: int
    anchor: int | None


class TextBox(Widget):
    """A ``TextBox`` holds a single line of text (a ``TextArea`` holds many).
    Its first and last columns are kept for arrows: ``◄`` (code page 437
    character 17) appears when there is more text off to the left, and ``►``
    (16) when there is more to the right. When there is no more text in a
    direction, that column is blank. The text scrolls sideways to keep the
    cursor in view. After the last character, the cursor sits in the blank
    right-hand column, so a box ``max_length + 2`` columns wide always shows all
    of its text. While the box has the focus, the terminal's own cursor shows
    where typing goes.

    By default, a text box accepts any single line of text: anything except
    line breaks (and surrogates, which no file or terminal could hold). Control
    characters, such as those in a file name, are shown as their code page 437
    pictures (escape appears as ←), and are never sent to the terminal to act
    on. Two limits can be set:

    - ``max_length``: at most this many characters.
    - ``pattern``: a regular expression, as a string or compiled with
      ``re.compile`` (so that it can carry flags). After every change, the whole
      text must match it (``fullmatch``).

    A key that would break a limit is refused, and the text stays as it was.
    Empty text is always allowed, so a box can always be cleared. The pattern is
    checked as each character is typed, so it must also accept text that has
    only been partly typed:

    ::

        TextBox(2, 7, 16, max_length=40)                  # any text
        TextBox(3, 7, 5, pattern=r"[0-9]*", max_length=3)  # up to three digits
        TextBox(4, 7, 10, pattern=r"-?[0-9]*")             # whole numbers
        TextBox(5, 7, 10, pattern=r"[0-9]*([.][0-9]*)?")   # decimals

    A pattern such as ``[0-9]{3}``, which matches only finished text, would
    refuse the first digit. Setting ``text`` from code checks the same limits,
    and raises ``ValueError`` if they are broken. ``accepts(text)`` checks text
    without changing anything. ``on_change(box)`` is called after each change
    made by typing, and ``cursor`` is where typing goes (from 0 to
    ``len(text)``).

    **Selecting.** Text is selected with Shift and the cursor keys, with Ctrl+A
    for all of it, or by dragging with the mouse. While the box has the focus,
    the selection is shown in the ``textbox.selected`` colours. Typing a
    character that the box accepts replaces the selection, and Backspace or
    Delete deletes it. A replacement that the limits refuse leaves the text and
    the selection as they were. Code can read ``selection`` (``(start, end)``,
    or ``None``) and ``selected_text``, and call ``select(start, end)`` and
    ``select_all()``. Setting ``text`` or ``cursor`` clears the selection.

    Dragging onto ``◄`` or ``►`` (or beyond the box in that direction) keeps
    selecting in that direction: one character straight away, and then one more
    every ``TextBox.scroll_delay`` seconds (0.1 by default) while the mouse is
    held there, until the end of the text. Set ``TextBox.scroll_delay = 0.2``
    once to change this for a whole project, or set it on a single box.

    - Any printable character, including Space: insert it at the cursor, or
      replace the selection with it
    - Left / Right (``text_left`` / ``text_right``): move the cursor; with a
      selection, go to its start / end
    - Home / End (``text_home`` / ``text_end``): go to the start / end
    - Shift+Left / Shift+Right (``text_select_left`` / ``text_select_right``):
      select one character more, or less
    - Shift+Home / Shift+End (``text_select_home`` / ``text_select_end``): select
      to the start / end
    - Ctrl+A (``text_select_all``): select all the text
    - Ctrl+X / Ctrl+C (``text_cut`` / ``text_copy``): cut / copy the selection
      to the clipboard
    - Ctrl+V (``text_paste``): paste the clipboard's text over the selection, or
      at the cursor
    - Backspace / Del (``text_backspace`` / ``text_delete``): delete the
      selection, or otherwise the character before / at the cursor
    - Ctrl+Y (``text_clear``): empty the box (its whole line)
    - Ctrl+Left / Ctrl+Right (``text_word_left`` / ``text_word_right``): move by
      a word, to the start of this word or the previous one, or of the next
    - Ctrl+Shift+Left / Ctrl+Shift+Right (``text_select_word_left`` /
      ``text_select_word_right``): select a word at a time
    - Ctrl+Z (``text_undo``): undo the last change, and press again for the one
      before, up to ``undo_limit`` (20)
    - Alt+Z or Ctrl+Shift+Z (``text_redo``): redo what was undone
    - A click: put the cursor there; on ``◄`` or ``►``, move one character
      further in that direction
    - Shift and a click: select from the cursor to there
    - A drag: select; held over ``◄`` or ``►``, keep selecting in that direction

    Keys bound to ``next_widget``, ``previous_widget`` and ``dialog_cancel`` always
    pass through a text box, so that it never traps the keyboard. So does Enter,
    which presses a dialog's default button. In a dialog, letters go into the
    focused text box rather than pressing buttons, though Alt with a button's
    letter still presses the button.

    Pasting, whether with Dasha Framework's own paste key or through the terminal (with
    its own Ctrl+V or right-click), is all or nothing: if the box would not accept
    the result as a whole, nothing changes. A single line break at the end of text
    pasted through the terminal is removed, because copying a whole line in a
    terminal often copies its line break too.
    """

    focusable = True
    style: Style = Style(foreground=BLUE, background=CYAN)
    focused_style: Style = Style(foreground=BRIGHT_WHITE, background=CYAN, bold=True)
    selected_style: Style = Style(foreground=BRIGHT_WHITE, background=GREEN, bold=True)
    """The style of selected text, while the box has the focus."""
    arrow_style: Style = Style(foreground=CYAN, background=BLUE, bold=True)
    """The style of the ``◄`` and ``►`` that show there is more text in that
    direction."""
    min_width: int = 3
    """The narrowest width: the two arrow columns, and room for one character
    between them."""
    clipboard: Clipboard = CLIPBOARD
    """The clipboard used for cut, copy and paste: the one shared by all of
    Dasha Framework, unless a box (or a subclass) is given another."""
    undo_limit: int | None = 20
    """How many changes Ctrl+Z can undo, with the oldest forgotten first. Any
    number will do, or ``None`` for no limit."""
    scroll_delay: float = 0.01
    """How many seconds each character takes while a mouse selection is held
    over an arrow. Set ``TextBox.scroll_delay`` to change it for a whole
    project, or set it on a single box."""

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
        """The text in the box. Setting it puts the cursor at the end, and text
        that the box does not accept raises ``ValueError``."""
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
        """Where typing goes, as a character index from 0 to ``len(text)``.
        Setting it clears the selection."""
        return self._cursor

    @cursor.setter
    def cursor(self, position: int) -> None:
        self._move(position, extend=False)

    def _move(self, position: int, extend: bool) -> None:
        """Move the cursor; with ``extend``, the selection goes with it."""
        if not extend:
            self._anchor = None
        elif self._anchor is None:
            self._anchor = self._cursor
        self._cursor = max(0, min(position, len(self._text)))

    # The selection

    @property
    def selection(self) -> tuple[int, int] | None:
        """The selected characters as ``(start, end)`` indexes (``end`` not
        included), or ``None`` when nothing is selected."""
        if self._anchor is None or self._anchor == self._cursor:
            return None
        return min(self._anchor, self._cursor), max(self._anchor, self._cursor)

    @property
    def selected_text(self) -> str:
        """The selected text, which is empty when nothing is selected."""
        selection = self.selection
        return "" if selection is None else self._text[selection[0] : selection[1]]

    def select(self, start: int, end: int) -> None:
        """Select from ``start`` to ``end``, leaving the cursor at ``end``."""
        self._anchor = max(0, min(start, len(self._text)))
        self._cursor = max(0, min(end, len(self._text)))

    def select_all(self) -> None:
        """Select all the text."""
        self.select(0, len(self._text))

    # The clipboard

    def copy(self) -> bool:
        """Copy the selection to the clipboard as text. Returns ``False`` if
        nothing is selected."""
        if self.selection is None:
            return False
        self.clipboard.copy_text(self.selected_text)
        return True

    def cut(self) -> bool:
        """Copy the selection to the clipboard and delete it. Nothing happens
        (and ``False`` is returned) if nothing is selected, or if the box would
        not accept the text left behind."""
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
        """Put the clipboard's text in place of the selection, or at the
        cursor. Nothing happens (and ``False`` is returned) unless the
        clipboard holds text and the box accepts the result as a whole, so
        pasting ``"hello"`` into a box for numbers changes nothing at all."""
        pasted = self.clipboard.text
        return pasted is not None and self.insert(pasted)

    def handle_paste(self, text: str) -> bool:
        """Text pasted through the terminal is inserted as ``insert`` does it,
        all or nothing, without one line break at the end."""
        return self.insert(text.removesuffix("\n").removesuffix("\r"))

    def insert(self, text: str) -> bool:
        """Put text in place of the selection, or at the cursor, as a paste
        does. Nothing happens (and ``False`` is returned) unless the box
        accepts the result as a whole."""
        if not text:
            return False
        start, end = self.selection or (self._cursor, self._cursor)
        result = self._text[:start] + text + self._text[end:]
        if result == self._text or not self.accepts(result):
            return False
        self._edit(result, start + len(text))
        return True

    def accepts(self, text: str) -> bool:
        """Whether the box may hold this text: either empty, or a single line
        (with no line breaks or surrogates) within ``max_length`` that matches
        ``pattern``. Control characters are allowed, because they are drawn as
        their pictures."""
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
        """Make a change, if the result is allowed; it clears the selection.
        A refused change leaves the text and the selection as they were.
        ``typed`` is the character typed, if that is what this is: a run of
        typing, to the end of a word, is undone in one go. A change that
        leaves the text as it was (``1`` typed over a selected ``1``) just
        moves the cursor, as though it had been made."""
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
    """Whether the box's text can be copied or cut out (a password box's
        cannot)."""

    def popup_menu(self, shortcuts: Shortcuts) -> Menu | None:
        """The box's ``context_menu``, or otherwise a menu of Undo, Cut, Copy,
        Paste and Select all, each greyed out when it would do nothing."""
        if self.context_menu is not None:
            return self.context_menu
        return edit_menu(self, shortcuts, copies=self.copies_out)

    def undo(self) -> bool:
        """Undo the latest change (Ctrl+Z), putting the cursor and selection
        back as they were; ``False`` if there is nothing to undo."""
        step = self._history.pop()
        if step is None:
            return False
        self._history.undone(self._restore(step))
        return True

    def redo(self) -> bool:
        """Redo the latest change undone (Alt+Z, or Ctrl+Shift+Z where the
        terminal sends it); ``False`` if there is nothing to redo."""
        step = self._history.pop_redo()
        if step is None:
            return False
        self._history.push(self._restore(step), self.undo_limit, redoing=True)
        return True

    def _restore(self, step: _Before) -> _Before:
        """Go back (or forward) to the text, cursor and selection of
        ``step``; returns how things were, to come back to."""
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
        """How many characters can be shown at once, between the arrow
        columns."""
        return self.rect.width - 2

    @property
    def first_visible(self) -> int:
        """The index of the first character shown, after scrolling just
        enough to keep the cursor in view."""
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
        """Whether there is text off to the left (so that ``◄`` is shown)."""
        return self.first_visible > 0

    @property
    def has_more_right(self) -> bool:
        """Whether there is text off to the right (so that ``►`` is shown)."""
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
        """Edit the text. The keys that move the focus or cancel a dialog are
        left for the window, so that a text box never traps the keyboard, and
        so is Enter, so that it presses a dialog's default button."""
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
        """Deleting, clearing and typing: what changes the text in place."""
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
        """A click puts the cursor under the pointer (or, on an arrow, one
        character further in that direction, scrolling the text), and Shift
        with a click selects up to there. A double-click selects all the
        text, as Ctrl+A does (and as a double-click in a text area selects
        its line). Dragging selects from where the button was pressed. Held
        over an arrow, or beyond the box, a drag keeps selecting in that
        direction, one character every ``scroll_delay`` seconds."""
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
        """The text index for a column ``offset`` from the box's left edge,
        kept to what shows."""
        first = self.first_visible
        index = first + max(0, min(offset - 1, self.visible_width))
        return min(index, len(self._text))

    def _beyond(self, direction: int) -> int:
        """The index just past what shows, to the left (-1) or right (1)."""
        first = self.first_visible
        return first - 1 if direction < 0 else first + self.visible_width

    def _scroll_step(self, now: float) -> None:
        """Select one more character in the scrolling direction."""
        self._move(self._beyond(self._scrolling), extend=True)
        self._next_scroll = now + self.scroll_delay
        if self._cursor in (0, len(self._text)):
            self._scrolling = 0  # selected all the way to that end

    def wake_time(self) -> float | None:
        return self._next_scroll if self._scrolling else None

    def on_timer(self, now: float) -> None:
        if self._scrolling:
            self._scroll_step(now)
