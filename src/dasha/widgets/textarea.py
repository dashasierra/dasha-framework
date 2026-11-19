"""Text areas, which hold many lines of text to edit."""

from bisect import bisect_right
from collections import Counter
from collections.abc import Callable, Iterable
from typing import NamedTuple

from dasha.canvas import Canvas, Rect
from dasha.clipboard import CLIPBOARD, Clipboard
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.style import BLUE, BRIGHT_WHITE, BRIGHT_YELLOW, CYAN, GREEN, Style
from dasha.widgets.base import Widget
from dasha.menu import Menu
from dasha.widgets.editing import UndoHistory, edit_menu, word_left, word_right

type Position = tuple[int, int]
"""A place in the text: (line, character), both counted from 0."""

NUMBERS_BAR = "\N{BOX DRAWINGS LIGHT VERTICAL}"
"""The bar between the line numbers and the text: ``│`` (code page 437 179)."""


class _Change(NamedTuple):
    """One undoable change: at ``start``, ``removed`` was replaced by
    ``inserted``; the cursor and selection were as given."""

    start: Position
    removed: str
    inserted: str
    cursor: Position
    anchor: Position | None


# pylint: disable-next=too-many-instance-attributes,too-many-public-methods
class TextArea(Widget):
    """A ``TextArea`` holds many lines of text to edit. Put one in an
    otherwise empty window, and the window becomes a text editor:

    ::

        editor = Window(title="Editor", rect=rect, resizable=True, maximisable=True)
        area = editor.add(widget=TextArea(row=0, column=0, text=notes))

    **Size and scrolling.** A text area is always at least as big as the rest of its
    window's interior (``width`` and ``height``, both 1 by default, are the least it
    is), and it follows the window as it is resized or maximised. It also grows with
    its text: when the text is longer or wider than the window, the text area is
    bigger than the window, so the window's own frame scroll bars appear, and the
    window scrolls to keep the cursor in view. When the cursor fits without
    scrolling sideways, the window shows the lines from their start. Deleting text
    shrinks it again, and the scroll bars go. Only the lines and columns showing are
    drawn, so long texts cost no more than short ones.

    **Word wrap.** With ``word_wrap`` on (off by default), a line too long for the
    window goes on in the rows below it, broken after a space where it can be, and
    within a word only when the word is longer than a row. The text area then stays
    as wide as the window, which never scrolls sideways; resizing the window wraps
    the text again. The line breaks in the text stay where they were: wrapping only
    changes how it is shown. Up and Down, PgUp and PgDn, and clicks go by the rows
    shown, while Home and End, Ctrl+Y and a double-click take the whole line.

    **Line numbers.** With ``line_numbers`` on (off by default), each line's number
    shows at its left, right-aligned in a column of its own, with ``│`` between it
    and the text. The column is ``number_digits`` (3) wide, and wider once there are
    more lines than that many digits can number: four digits from line 1000. With
    word wrap, a line's number is on its first row only. The numbers stay in view
    as the window scrolls sideways; a click on them goes to the start of that row.

    **Editing.** It edits as a text box does, with the same keys, plus some of its
    own:

    - Left / Right (``text_left`` / ``text_right``): Move a character, onto the line
      above or below at the ends
    - Ctrl+Left / Ctrl+Right (``text_word_left`` / ``text_word_right``): Move a
      word, onto the line above or below at the ends
    - Up / Down (``area_up`` / ``area_down``): Move a line, keeping to the same
      column where the line is long enough
    - PgUp / PgDn (``area_page_up`` / ``area_page_down``): Move a page: what the
      window shows, less one line
    - Home / End (``text_home`` / ``text_end``): Go to the start / end of the line
    - Ctrl+Home / Ctrl+End (``area_top`` / ``area_bottom``): Go to the start / end
      of the text
    - Shift with any of these (bar Ctrl+Home/End) (``text_select_*``,
      ``area_select_up`` / ``area_select_down``): Select as it moves
    - Ctrl+A (``text_select_all``): Select all the text
    - Enter (``area_newline``): Start a new line
    - Tab (``area_tab``): Type a tab
    - Ctrl+Tab / Ctrl+Shift+Tab (``area_next_widget`` / ``area_previous_widget``):
      Move the focus to the next / previous control
    - Ctrl+Z (``text_undo``): Undo the last change; again for the one before
    - Alt+Z, Ctrl+Shift+Z (``text_redo``): Redo what was undone
    - Backspace / Del (``text_backspace`` / ``text_delete``): Delete the selection,
      or a character; at a line's start or end, join the lines
    - Ctrl+Y (``area_delete_line``): Delete the line
    - Ctrl+X / Ctrl+C / Ctrl+V (``text_cut`` / ``text_copy`` / ``text_paste``): Cut,
      copy and paste, line breaks and all
    - Click: Put the cursor there (past a line's end, at its end)
    - Shift+click, drag: Select to there
    - Double-click: Select the whole line

    Typing a character, pressing Enter or pasting (with Ctrl+V or through the
    terminal) replaces the selection, just as in a text box. Only text is pasted:
    anything else on the clipboard is ignored. Shift+Tab and Escape are left for the
    window, and the mouse wheel scrolls the window.

    **Tabs and the focus.** Tab types a tab, which stays in the text and is drawn as
    spaces up to the next multiple of ``tab_size`` (4) columns. The cursor, clicks,
    selections and Up/Down all go by those columns on screen. Since Tab is taken,
    Ctrl+Tab and Ctrl+Shift+Tab move the focus to the next or previous control
    instead, in any window: out of a text area, and into one from the control before
    it. Many terminals send Ctrl+Tab just as they send Tab, so it never reaches
    Dasha Framework; those that can tell them apart send it in the "CSI u" or xterm
    "modifyOtherKeys" form, which Dasha Framework reads. Where it does not arrive,
    ``area_next_widget`` and ``area_previous_widget`` can be bound to other keys
    (``dasha --key-test`` shows what arrives). They cannot both be left without
    keys.

    **Undo.** Ctrl+Z undoes the last change, and pressing it again undoes the one
    before, back through the last ``undo_limit`` changes (20; any number is fine,
    2000 say, or ``None`` for no limit; set it on ``TextArea`` for a whole project
    or on one text area). Typing is undone a word at a time: a run of typed
    characters is one change, and a space starts the next. Undoing puts the cursor
    and the selection back as they were. Setting ``text`` from code starts afresh,
    with nothing to undo.

    **Redo.** Alt+Z redoes what Ctrl+Z undid, a step at a time, cursor and selection
    included, and Ctrl+Shift+Z does the same in terminals that send it: most send
    Ctrl+Shift+Z just as they send Ctrl+Z, so Alt+Z, which arrives everywhere, is
    the first key for it (Ctrl+Y deletes a line). As in any
    editor, making a new change forgets what could be redone. Text boxes undo and
    redo the same way.

    ``text`` (and ``value``) is all the text, its lines joined with ``"\\n"``, and
    ``lines`` the lines themselves (each one line, however many rows it wraps to).
    Text put in has its line breaks made ``\\n``. Control characters stay, as a file
    had them, drawn as their code page 437 pictures (escape as ←), never sent to
    the terminal to act on. ``cursor`` is (line, character),
    ``selection`` the selected (start, end) and ``selected_text`` what they hold.
    ``select``, ``select_all``, ``select_line``, ``insert``, ``delete_line``,
    ``cut``, ``copy``, ``paste``, ``undo`` and ``redo`` do from code what the keys
    do. ``on_change(area)`` is called after each edit, undoing included. Colours:
    ``textarea`` (bright yellow on blue), ``textarea.selected`` and
    ``textarea.numbers`` (cyan on blue).
    """

    focusable = True
    style: Style = Style(foreground=BRIGHT_YELLOW, background=BLUE)
    """The style of the text."""
    selected_style: Style = Style(foreground=BRIGHT_WHITE, background=GREEN, bold=True)
    """The style of selected text, while the text area has the focus."""
    number_style: Style = Style(foreground=CYAN, background=BLUE)
    """The style of the line numbers, and of the bar beside them."""
    number_digits: int = 3
    """The smallest width of the line numbers' column, in digits; it is
    wider when there are more lines than that many digits can number."""
    clipboard: Clipboard = CLIPBOARD
    """The clipboard used for cut, copy and paste."""
    tab_size: int = 4
    """How many columns apart the tab stops are."""
    undo_limit: int | None = 20
    """How many changes Ctrl+Z can undo, oldest forgotten first. Any number
    will do (2000, say), or ``None`` for no limit; set it on the class for a
    whole project, or on one text area."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        row: int,
        column: int,
        width: int = 1,
        height: int = 1,
        *,
        text: str = "",
        word_wrap: bool = False,
        line_numbers: bool = False,
        on_change: Callable[["TextArea"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        super().__init__(row, column, width, height, name=name, status=status)
        self._least = (max(1, width), max(1, height))
        self.on_change = on_change
        self.lines: list[str] = [""]
        """The text, a line at a time (without line breaks)."""
        self._cursor: Position = (0, 0)
        self._anchor: Position | None = None  # the other end of the selection
        self._goal = 0  # the screen column Up and Down aim for
        self._history: UndoHistory[_Change] = UndoHistory()
        self._typing_at: Position | None = None  # where typing goes on a step
        # How many lines are drawn how wide, and at what tab size: kept up
        # to date as lines change, so finding the widest line on every
        # keystroke does not mean measuring them all.
        self._widths: Counter[int] = Counter()
        self._widths_tab_size = self.tab_size
        # Word wrap: where each line is broken (the index of the first
        # character of each row after its first), for rows how many columns
        # wide (0: to be worked out again) at what tab size; and the row
        # each line starts on, worked out again when the rows change.
        self._word_wrap = word_wrap
        self._line_numbers = line_numbers
        self._breaks: list[tuple[int, ...]] = []
        self._wrap_limit = 0
        self._wrap_tab_size = self.tab_size
        self._row_starts: list[int] | None = None
        self.text = text

    # The text

    @property
    def text(self) -> str:
        """All the text. Setting it puts the cursor at the start, and forgets
        everything that could be undone."""
        return "\n".join(self.lines)

    @text.setter
    def text(self, text: str) -> None:
        self.lines = self._clean(text).split("\n")
        self._count_widths()
        self._wrap_limit = 0  # wrapped afresh by fit
        self._cursor, self._anchor, self._goal = (0, 0), None, 0
        self._history.clear()
        self._typing_at = None
        self.fit()

    @property
    def value(self) -> str:
        return self.text

    @property
    def line_numbers(self) -> bool:
        """Whether each line's number is shown at its left. Off by default."""
        return self._line_numbers

    @line_numbers.setter
    def line_numbers(self, on: bool) -> None:
        self._line_numbers = on
        self.fit()
        self._reveal()

    @property
    def numbers_width(self) -> int:
        """How many columns the line numbers take, including the bar; none
        without ``line_numbers``."""
        if not self._line_numbers:
            return 0
        return max(self.number_digits, len(str(len(self.lines)))) + 1

    @property
    def _text_column(self) -> int:
        """Where in the window's content the text's first column is: after
        the line numbers."""
        return self.rect.column + self.numbers_width

    @property
    def word_wrap(self) -> bool:
        """Whether long lines continue on the rows below, rather than past
        the window's right edge. Off by default."""
        return self._word_wrap

    @word_wrap.setter
    def word_wrap(self, on: bool) -> None:
        self._word_wrap = on
        self._wrap_limit = 0
        self.fit()
        self._goal = self._goal_of(self._cursor)
        self._reveal()

    @staticmethod
    def _clean(text: str) -> str:
        """Text as it is kept: ``\\n`` line breaks, and the rest as it came,
        control characters too (drawn as pictures), bar surrogates."""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if text.replace("\n", "").replace("\t", "").isprintable():
            return text  # nothing to look at: no need to go a character at a time
        return "".join(char for char in text if not "\ud800" <= char <= "\udfff")

    @property
    def cursor(self) -> Position:
        """Where typing goes, as (line, character). Setting it clears the
        selection."""
        return self._cursor

    @cursor.setter
    def cursor(self, position: Position) -> None:
        self._move(position, extend=False)

    def _clamp(self, position: Position) -> Position:
        line = max(0, min(position[0], len(self.lines) - 1))
        return line, max(0, min(position[1], len(self.lines[line])))

    # Tabs: characters to screen columns and back

    def _shown(self, line: str) -> str:
        """A line as it is drawn, its tabs spread to the tab stops."""
        return line.expandtabs(self.tab_size)

    def _count_widths(self) -> None:
        """Measure every line afresh."""
        self._widths = Counter(len(self._shown(line)) for line in self.lines)
        self._widths_tab_size = self.tab_size

    def _recount(self, removed: Iterable[str], added: Iterable[str]) -> None:
        """Lines ``removed`` have gone and ``added`` arrived: count their
        widths out and in."""
        widths = self._widths
        for line in removed:
            width = len(self._shown(line))
            widths[width] -= 1
            if widths[width] <= 0:
                del widths[width]
        widths.update(len(self._shown(line)) for line in added)

    def _column_of(self, position: Position) -> int:
        """The screen column (within the text area) of a position."""
        line, index = position
        return len(self._shown(self.lines[line][:index]))

    def _index_at(self, line: int, column: int) -> int:
        """The character in a line that a screen column falls on (or after
        the last, past the end); within a tab, the tab."""
        width = 0
        for index, char in enumerate(self.lines[line]):
            after = (
                (width // self.tab_size + 1) * self.tab_size
                if char == "\t"
                else width + 1
            )
            if column < after:
                return index
            width = after
        return len(self.lines[line])

    # Word wrap: lines into rows and back

    def _line_breaks(self, text: str, limit: int) -> tuple[int, ...]:
        """Where a line is broken into rows ``limit`` columns wide: after the
        last space that fits (a space that does not fit stays at the end of
        its row), or within a word too long for a row. The last row is
        never wider than ``limit``, leaving a cell for the cursor after it."""
        if len(text) <= limit and "\t" not in text:
            return ()  # fits, and no tabs to measure
        ends = []  # the screen column after each character
        column, tab = 0, self.tab_size
        for char in text:
            column = (column // tab + 1) * tab if char == "\t" else column + 1
            ends.append(column)
        breaks: list[int] = []
        start = base = 0  # the row's first character, and its column
        while ends[-1] - base > limit:
            fits = bisect_right(ends, base + limit, lo=start)  # the first that does not
            if text[fits] == " ":
                cut = fits + 1
            else:
                space = text.rfind(" ", start, fits)
                cut = space + 1 if space >= start else max(fits, start + 1)
            breaks.append(cut)
            if cut >= len(text):
                break  # a space that did not fit ends the line: the cursor goes on
            start, base = cut, ends[cut - 1]
        return tuple(breaks)

    def _wrap(self, limit: int) -> None:
        """Break every line into rows ``limit`` columns wide, afresh."""
        self._wrap_limit = limit
        self._wrap_tab_size = self.tab_size
        self._breaks = [self._line_breaks(line, limit) for line in self.lines]
        self._row_starts = None

    def _rewrap(self, first: int, removed: int, added: list[str]) -> None:
        """``removed`` lines from ``first`` have been replaced by ``added``:
        break those into rows (if word wrap is on and the rows are known)."""
        if not self._word_wrap or not self._wrap_limit:
            return
        new = [self._line_breaks(line, self._wrap_limit) for line in added]
        old = self._breaks[first : first + removed]
        if [len(rows) for rows in old] != [len(rows) for rows in new]:
            self._row_starts = None  # lines start on other rows now
        self._breaks[first : first + removed] = new

    def _line_rows(self) -> list[int]:
        """The row each line starts on, with word wrap."""
        if self._row_starts is None:
            starts, row = [], 0
            for breaks in self._breaks:
                starts.append(row)
                row += len(breaks) + 1
            self._row_starts = starts
        return self._row_starts

    def _row_count(self) -> int:
        """How many rows the text takes."""
        if not self._word_wrap:
            return len(self.lines)
        return self._line_rows()[-1] + len(self._breaks[-1]) + 1

    def _segment(self, row: int) -> tuple[int, int, int, bool]:
        """The line a row shows part of, its characters from and to (not
        including), and whether it is the line's last row."""
        if not self._word_wrap:
            return row, 0, len(self.lines[row]), True
        starts = self._line_rows()
        line = bisect_right(starts, row) - 1
        breaks = self._breaks[line]
        part = row - starts[line]
        start = breaks[part - 1] if part else 0
        last = part == len(breaks)
        return line, start, len(self.lines[line]) if last else breaks[part], last

    def _row_of(self, position: Position) -> tuple[int, int]:
        """The row a position is shown on, and its column in that row. At a
        break, it is the start of the row after."""
        if not self._word_wrap:
            return position[0], self._column_of(position)
        line, index = position
        breaks = self._breaks[line]
        part = bisect_right(breaks, index)
        start = breaks[part - 1] if part else 0
        row = self._line_rows()[line] + part
        return row, self._column_of(position) - self._column_of((line, start))

    def _at_row(self, row: int, column: int) -> Position:
        """The position a column of a row falls on: within the row, or at
        its end (just before its last character, for a row the next goes on
        from, since after it is the next row's start)."""
        row = max(0, min(row, self._row_count() - 1))
        line, start, end, last = self._segment(row)
        index = self._index_at(line, self._column_of((line, start)) + max(0, column))
        return line, max(start, min(index, end if last else end - 1))

    def _goal_of(self, position: Position) -> int:
        """The column Up and Down aim for from a position: on its row."""
        return self._row_of(position)[1]

    # The selection

    @property
    def selection(self) -> tuple[Position, Position] | None:
        """The selected text's (start, end), or ``None``."""
        if self._anchor is None or self._anchor == self._cursor:
            return None
        return min(self._anchor, self._cursor), max(self._anchor, self._cursor)

    @property
    def selected_text(self) -> str:
        """The selected text, lines joined with ``"\\n"``."""
        selection = self.selection
        return "" if selection is None else self._between(*selection)

    def _between(self, start: Position, end: Position) -> str:
        """The text from ``start`` to ``end``."""
        (first, begin), (last, finish) = start, end
        if first == last:
            return self.lines[first][begin:finish]
        middle = self.lines[first + 1 : last]
        return "\n".join(
            [self.lines[first][begin:], *middle, self.lines[last][:finish]]
        )

    def select(self, start: Position, end: Position) -> None:
        """Select from ``start`` to ``end``, leaving the cursor at ``end``."""
        self._anchor = self._clamp(start)
        self._move(end, extend=True)

    def select_all(self) -> None:
        """Select all the text (Ctrl+A)."""
        self.select((0, 0), (len(self.lines) - 1, len(self.lines[-1])))

    def select_line(self, line: int) -> None:
        """Select one whole line, as a double-click does."""
        line = self._clamp((line, 0))[0]
        self.select((line, 0), (line, len(self.lines[line])))

    def _move(self, position: Position, extend: bool, keep_goal: bool = False) -> None:
        """Move the cursor; with ``extend`` the selection goes with it."""
        if not extend:
            self._anchor = None
        elif self._anchor is None:
            self._anchor = self._cursor
        self._cursor = self._clamp(position)
        if not keep_goal:
            self._goal = self._goal_of(self._cursor)
        self._reveal()

    def _vertical(self, lines: int) -> Position:
        """The position ``lines`` (rows, with word wrap) up (negative) or
        down, at the goal column."""
        if self._word_wrap:
            return self._at_row(self._row_of(self._cursor)[0] + lines, self._goal)
        line = max(0, min(self._cursor[0] + lines, len(self.lines) - 1))
        return line, self._index_at(line, self._goal)

    def _word(self, direction: int) -> Position:
        """Where Ctrl+Left (-1) or Ctrl+Right (1) goes, onto the line above
        or below from the start or end of a line."""
        line, index = self._cursor
        text = self.lines[line]
        if direction < 0:
            if index == 0 and line > 0:
                return line - 1, len(self.lines[line - 1])
            return line, word_left(text, index)
        if index == len(text) and line < len(self.lines) - 1:
            return line + 1, 0
        return line, word_right(text, index)

    # Editing

    def insert(self, text: str) -> bool:
        """Put text in place of the selection, or at the cursor, as typing
        and pasting do; the text may contain line breaks and tabs. Returns
        ``False`` if nothing changed."""
        text = self._clean(text)
        start, end = self.selection or (self._cursor, self._cursor)
        if not text and start == end:
            return False
        self._replace(start, end, text)
        return True

    def _type(self, text: str) -> None:
        """A character typed: as ``insert``, but a run of typing (to the end
        of a word) is undone in one go."""
        typing_on = (
            self.selection is None
            and self._typing_at == self._cursor
            and not text.isspace()
            and self._history.last is not None
        )
        if typing_on:
            last = self._history.last
            assert last is not None
            self._replace(self._cursor, self._cursor, text, record=False)
            self._history.replace_last(last._replace(inserted=last.inserted + text))
        else:
            self.insert(text)
        self._typing_at = self._cursor

    def _replace(
        self, start: Position, end: Position, text: str, *, record: bool = True
    ) -> None:
        """Replace the text from ``start`` to ``end`` with ``text``, leave
        the cursor after it, remember it for undoing (unless ``record`` is
        off), and tell whoever is listening."""
        if record:
            change = _Change(
                start, self._between(start, end), text, self._cursor, self._anchor
            )
            self._history.push(change, self.undo_limit)
        self._typing_at = None
        before = self.lines[start[0]][: start[1]]
        after = self.lines[end[0]][end[1] :]
        parts = text.split("\n")
        new = [before + parts[0], *parts[1:]]
        self._cursor = (start[0] + len(new) - 1, len(new[-1]))
        new[-1] += after
        self._recount(self.lines[start[0] : end[0] + 1], new)
        self.lines[start[0] : end[0] + 1] = new
        self._rewrap(start[0], end[0] + 1 - start[0], new)
        self._anchor = None
        self._goal = self._goal_of(self._cursor)
        self.fit()
        self._reveal()
        if self.on_change is not None:
            self.on_change(self)

    @property
    def can_undo(self) -> bool:
        """Whether there is a change to undo."""
        return len(self._history) > 0

    def popup_menu(self, shortcuts: Shortcuts) -> Menu | None:
        """The area's ``context_menu``, or otherwise Undo, Cut, Copy, Paste and
        Select all, each greyed out when it would do nothing."""
        if self.context_menu is not None:
            return self.context_menu
        return edit_menu(self, shortcuts)

    def undo(self) -> bool:
        """Undo the latest change (Ctrl+Z), putting the cursor and selection
        back as they were; ``False`` if there is nothing to undo."""
        change = self._history.pop()
        if change is None:
            return False
        self._history.undone(self._apply(change))
        return True

    def redo(self) -> bool:
        """Redo the latest change undone (Alt+Z, or Ctrl+Shift+Z where the
        terminal sends it); ``False`` if there is nothing to redo."""
        change = self._history.pop_redo()
        if change is None:
            return False
        self._history.push(self._apply(change), self.undo_limit, redoing=True)
        return True

    def _apply(self, change: _Change) -> _Change:
        """Put ``change.removed`` back where ``change.inserted`` is, and the
        cursor and selection as ``change`` has them. Returns the change
        that reverses this, to redo (or undo again)."""
        parts = change.inserted.split("\n")
        if len(parts) == 1:
            end = (change.start[0], change.start[1] + len(parts[0]))
        else:
            end = (change.start[0] + len(parts) - 1, len(parts[-1]))
        reverse = _Change(
            change.start, change.inserted, change.removed, self._cursor, self._anchor
        )
        self._replace(change.start, end, change.removed, record=False)
        self._cursor, self._anchor = change.cursor, change.anchor
        self._goal = self._goal_of(self._cursor)
        self._reveal()
        return reverse

    def _back(self, position: Position) -> Position:
        """The position one character back, onto the previous line if need be."""
        line, column = position
        if column > 0:
            return line, column - 1
        if line > 0:
            return line - 1, len(self.lines[line - 1])
        return position

    def _forward(self, position: Position) -> Position:
        """The position one character on, onto the next line if need be."""
        line, column = position
        if column < len(self.lines[line]):
            return line, column + 1
        if line < len(self.lines) - 1:
            return line + 1, 0
        return position

    def delete_line(self) -> None:
        """Delete the line the cursor is on (Ctrl+Y)."""
        line = self._cursor[0]
        if len(self.lines) == 1:
            self._replace((0, 0), (0, len(self.lines[0])), "")
        elif line < len(self.lines) - 1:
            self._replace((line, 0), (line + 1, 0), "")
        else:
            previous = len(self.lines[line - 1])
            self._replace((line - 1, previous), (line, len(self.lines[line])), "")

    # The clipboard

    def copy(self) -> bool:
        """Copy the selection to the clipboard; ``False`` if nothing is
        selected."""
        if self.selection is None:
            return False
        self.clipboard.copy_text(self.selected_text)
        return True

    def cut(self) -> bool:
        """Copy the selection to the clipboard and delete it; ``False`` if
        nothing is selected."""
        if not self.copy():
            return False
        return self.insert("")

    def paste(self) -> bool:
        """Put the clipboard's text in place of the selection, or at the
        cursor. Nothing happens unless the clipboard holds text."""
        text = self.clipboard.text
        return bool(text) and self.insert(text or "")

    def handle_paste(self, text: str) -> bool:
        """Text pasted through the terminal is inserted as if typed."""
        return self.insert(text)

    # Layout

    def on_add(self) -> None:
        self.fit()

    def follow_resize(self, before: tuple[int, int], after: tuple[int, int]) -> None:
        """A text area always fits its window, whatever its ``grow`` is."""
        del before, after
        self.fit()

    def fit(self) -> None:
        """Be at least as big as the rest of the window's interior, and as
        big as the text (plus a column for the cursor after the end); with
        word wrap, exactly as wide as the interior, and as tall as the rows."""
        rect = self.rect
        least_width, least_height = self._least
        if self.window is not None:
            interior = self.window.interior
            least_width = max(least_width, interior.width - rect.column)
            least_height = max(least_height, interior.height - rect.row)
        if self.tab_size != self._widths_tab_size:
            self._count_widths()
        numbers = self.numbers_width
        if self._word_wrap:
            # A column for the cursor at the end, and the line numbers'.
            limit = max(1, least_width - 1 - numbers)
            if limit != self._wrap_limit or self.tab_size != self._wrap_tab_size:
                self._wrap(limit)
            height = max(least_height, self._row_count())
            self.rect = Rect(rect.row, rect.column, height, least_width)
        else:
            widest = max(self._widths, default=0)
            width = max(least_width, widest + 1 + numbers)
            height = max(least_height, len(self.lines))
            self.rect = Rect(rect.row, rect.column, height, width)
        if self.window is not None:
            self.window.scroll_by(0, 0)  # back in range, if the text shrank

    def _reveal(self) -> None:
        """Scroll the window to show the cursor."""
        window = self.window
        if window is not None:
            row, column = self._row_of(self._cursor)
            numbers = self.numbers_width
            # The cursor's cell, and room for the line numbers left of it,
            # since they stay on the left as the window scrolls sideways.
            cell = Rect(
                self.rect.row + row,
                self._text_column + column - numbers,
                1,
                numbers + 1,
            )
            window.scroll_into_view(cell)
            if cell.right <= window.interior.width:
                # The cursor fits without scrolling sideways: show the
                # lines from their start, as editors do.
                window.scroll_to(window.scroll_row, 0)

    def _page(self) -> int:
        """Lines a page moves: what the window shows, less one."""
        if self.window is None:
            return max(1, self.rect.height - 1)
        return max(1, self.window.interior.height - 1)

    # Drawing

    def _visible(self) -> tuple[int, int, int, int]:
        """The rows and columns that can show: (first row, row count, first
        column, column count), so a long text costs no more to draw than a
        short one. Without word wrap, each row is a line."""
        if self.window is None:
            return 0, self._row_count(), 0, self.rect.width
        interior = self.window.interior
        return (
            max(0, self.window.scroll_row - self.rect.row),
            interior.height + 1,
            max(0, self.window.scroll_column - self._text_column),
            interior.width + 1,
        )

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        rect = self.rect
        top, left = origin.row + rect.row, origin.column + self._text_column
        canvas.fill(
            origin.intersect(
                Rect(top, origin.column + rect.column, rect.height, rect.width)
            ),
            " ",
            self.style,
        )
        first, count, column, width = self._visible()
        selection = self.selection if focused else None
        for row in range(first, min(self._row_count(), first + count)):
            self._paint_row(canvas, origin, row, (column, width), selection)
        numbers_end = self._paint_numbers(canvas, origin, first, count)
        if focused:
            row, at = self._row_of(self._cursor)
            if left + at >= numbers_end:  # not scrolled under the numbers
                canvas.place_cursor(top + row, left + at)

    def _numbers_column(self) -> int:
        """Where in the window's content the line numbers are: at the text
        area's left, or the window's, whichever is further right."""
        scrolled = self.window.scroll_column if self.window is not None else 0
        return max(self.rect.column, scrolled)

    def _paint_numbers(
        self, canvas: Canvas, origin: Rect, first: int, count: int
    ) -> int:
        """Draw the line numbers of the rows that show, each by its line's
        first row, and the bar beside them, all the text area's height.
        Returns the screen column just after them."""
        width = self.numbers_width
        left = origin.column + self._numbers_column()
        if not width:
            return left
        rows = self._row_count()
        for row in range(first, min(self.rect.height, first + count)):
            number = ""
            if row < rows:
                line, begin, _, _ = self._segment(row)
                number = str(line + 1) if begin == 0 else ""
            canvas.write(
                origin.row + self.rect.row + row,
                left,
                number.rjust(width - 1) + NUMBERS_BAR,
                self.number_style,
                clip=origin,
            )
        return left + width

    def _paint_row(  # pylint: disable=too-many-arguments
        self,
        canvas: Canvas,
        origin: Rect,
        row: int,
        view: tuple[int, int],
        selection: tuple[Position, Position] | None,
    ) -> None:
        """Draw one row (a line, or with word wrap part of one): the columns
        of it ``view`` says (the first, and how many), and its selection."""
        number, begin, finish, last = self._segment(row)
        shown = self._shown(self.lines[number])
        # The columns of the line as drawn that this row shows.
        offset = self._column_of((number, begin))
        end = len(shown) if last else self._column_of((number, finish))
        low = offset + view[0]
        high = min(end, low + view[1])
        canvas.write(
            origin.row + self.rect.row + row,
            origin.column + self._text_column + view[0],
            shown[low:high],
            self.style,
            clip=origin,
        )
        if selection is not None:
            # The line break's cell is on the line's last row.
            self._paint_selected(
                canvas,
                origin,
                (row, number, offset),
                selection,
                (low, low + view[1] if last else high),
            )

    def _paint_selected(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        canvas: Canvas,
        origin: Rect,
        place: tuple[int, int, int],
        selection: tuple[Position, Position],
        view: tuple[int, int],
    ) -> None:
        """Highlight the selected part of one row, and a cell for its line's
        break when the selection goes on past it. ``place`` is the row, its
        line, and the column of the line as drawn that the row starts at;
        ``view`` the columns of the line it shows, from and to."""
        row, number, offset = place
        (first, start), (last, end) = selection
        if not first <= number <= last:
            return
        shown = self._shown(self.lines[number]) + " "  # the line break, as a cell
        low = self._column_of((number, start)) if number == first else 0
        high = self._column_of((number, end)) if number == last else len(shown)
        low, high = max(low, view[0]), min(high, view[1])
        if low < high:
            canvas.write(
                origin.row + self.rect.row + row,
                origin.column + self._text_column + low - offset,
                shown[low:high],
                self.selected_style,
                clip=origin,
            )

    # Input

    def key_help(self, shortcuts: Shortcuts) -> list[tuple[str, str]]:
        window = self.window
        if window is None or sum(w.can_focus() for w in window.widgets) < 2:
            return []
        key = shortcuts.hint("area_next_widget")
        return [(key, "Next")] if key else []

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Edit the text. Tab types a tab, while Ctrl+Tab, Ctrl+Shift+Tab
        (and the window's own focus keys other than Tab) and Escape are left
        for the window."""
        if shortcuts.matches("area_tab", key):
            self._type("\t")
            return True
        leaving = (
            "area_next_widget",
            "area_previous_widget",
            "next_widget",
            "previous_widget",
            "dialog_cancel",
        )
        if any(shortcuts.matches(action, key) for action in leaving):
            return False
        return (
            self._movement_key(key, shortcuts)
            or self._command_key(key, shortcuts)
            or self._editing_key(key, shortcuts)
        )

    def _movement_key(self, key: str, shortcuts: Shortcuts) -> bool:
        line = self._cursor[0]
        selection = self.selection
        last = len(self.lines) - 1
        page = self._page()
        left = selection[0] if selection else self._back(self._cursor)
        right = selection[1] if selection else self._forward(self._cursor)
        moves: dict[str, tuple[Position, bool, bool]] = {
            # action: (where to, extend the selection, keep the goal column)
            "text_left": (left, False, False),
            "text_right": (right, False, False),
            "text_word_left": (self._word(-1), False, False),
            "text_word_right": (self._word(1), False, False),
            "text_home": ((line, 0), False, False),
            "text_end": ((line, len(self.lines[line])), False, False),
            "area_up": (self._vertical(-1), False, True),
            "area_down": (self._vertical(1), False, True),
            "area_page_up": (self._vertical(-page), False, True),
            "area_page_down": (self._vertical(page), False, True),
            "area_top": ((0, 0), False, False),
            "area_bottom": ((last, len(self.lines[last])), False, False),
            "text_select_left": (self._back(self._cursor), True, False),
            "text_select_right": (self._forward(self._cursor), True, False),
            "text_select_word_left": (self._word(-1), True, False),
            "text_select_word_right": (self._word(1), True, False),
            "text_select_home": ((line, 0), True, False),
            "text_select_end": ((line, len(self.lines[line])), True, False),
            "area_select_up": (self._vertical(-1), True, True),
            "area_select_down": (self._vertical(1), True, True),
        }
        for action, (position, extend, keep_goal) in moves.items():
            if shortcuts.matches(action, key):
                self._move(position, extend, keep_goal)
                return True
        return False

    def _command_key(self, key: str, shortcuts: Shortcuts) -> bool:
        commands: dict[str, Callable[[], object]] = {
            "text_cut": self.cut,
            "text_copy": self.copy,
            "text_paste": self.paste,
            "text_undo": self.undo,
            "text_redo": self.redo,
            "text_select_all": self.select_all,
            "area_newline": lambda: self.insert("\n"),
            "area_delete_line": self.delete_line,
        }
        for action, command in commands.items():
            if shortcuts.matches(action, key):
                command()
                return True
        return False

    def _editing_key(self, key: str, shortcuts: Shortcuts) -> bool:
        selection = self.selection
        if shortcuts.matches("text_backspace", key):
            if selection is not None:
                self.insert("")
            elif (back := self._back(self._cursor)) != self._cursor:
                self._replace(back, self._cursor, "")
            return True
        if shortcuts.matches("text_delete", key):
            if selection is not None:
                self.insert("")
            elif (forward := self._forward(self._cursor)) != self._cursor:
                self._replace(self._cursor, forward, "")
            return True
        if len(key) == 1 and key.isprintable():
            self._type(key)  # in place of the selection, if there is one
            return True
        return False

    def _position_at(self, row: int, column: int) -> Position:
        """The text position for a place within the text area; on the line
        numbers, the start of the row (or of what shows of it)."""
        column = max(column, self._numbers_column() + self.numbers_width)
        column -= self._text_column
        if self._word_wrap:
            return self._at_row(row - self.rect.row, column)
        line = self._clamp((row - self.rect.row, 0))[0]
        return line, self._index_at(line, column)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """A click puts the cursor there, Shift with a click selects to
        there, a drag selects, and a double-click selects the line. The wheel
        is left for the window, which scrolls."""
        if event.button != "left":
            return False
        position = self._position_at(row, column)
        if event.action == "press":
            if event.clicks >= 2:
                self.select_line(position[0])
            else:
                self._move(position, extend=event.shift)
                if self._anchor is None:
                    self._anchor = self._cursor  # where a drag selects from
            return True
        if event.action == "drag":
            self._move(position, extend=True)
            return True
        return event.action == "release"
