"""Tables: rows of fields under column headings, which can be sorted by
clicking a heading, and whose column widths can be changed by dragging
between the headings."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.menu import split_mnemonic
from dasha.shortcuts import Shortcuts
from dasha.style import (
    BLACK,
    BRIGHT_WHITE,
    BRIGHT_YELLOW,
    CYAN,
    GREEN,
    WHITE,
    Style,
)
from dasha.widgets.listbox import ListBox
from dasha.widgets.scrollbar import ScrollBar

UP_ARROW = "\N{BLACK UP-POINTING TRIANGLE}"
DOWN_ARROW = "\N{BLACK DOWN-POINTING TRIANGLE}"
"""``▲`` and ``▼`` (code page 437 glyphs 30 and 31), which mark the heading
the rows are sorted by, smallest first or largest first."""


@dataclass
class Column:
    """One column of a ``Table``: its heading, its width, and how its fields
    are aligned (``"left"``, ``"right"`` or ``"centre"``). ``key`` turns a field
    into the value that sorting compares (``int`` for numbers, for example);
    without one, fields are sorted as text, ignoring case."""

    title: str
    width: int
    align: str = "left"
    key: Callable[[str], Any] | None = None

    def __post_init__(self) -> None:
        if self.align not in ("left", "right", "centre"):
            raise ValueError("align must be left, right or centre")
        self.width = max(1, self.width)

    def fit(self, text: str) -> str:
        """A field, cut to the column's width and aligned within it."""
        text = text[: self.width]
        if self.align == "right":
            return text.rjust(self.width)
        if self.align == "centre":
            return text.center(self.width)
        return text.ljust(self.width)


class Table(ListBox):  # pylint: disable=too-many-instance-attributes
    """A ``Table`` shows rows of fields under column headings, as a list of
    files with their types and sizes does:

    ::

        Name          │Type     │ Size K ▲
        config.sys    │System   │     12
        autoexec.bat  │Batch    │    170

    ::

        files = window.add(
            widget=Table(
                columns=[
                    Column(title="Name", width=14),
                    Column(title="Type", width=9),
                    Column(title="Size K", width=7, align="right", key=int),
                ],
                row=0,
                column=0,
                width=43,
                height=12,
                rows=[["config.sys", "System", "12"], ...],
            )
        )

    - **Columns.** Each ``Column`` has a heading, a width, an alignment
      (``"left"``, ``"right"`` or ``"centre"``) and optionally a ``key``, which
      turns a field into the value that sorting compares (``int`` for numbers).
      Without one, fields are sorted as text, ignoring case.
    - **Keys.** Underneath, a table is a list box, with the same keys and actions
      (``list_up`` and the rest), typing to find a row by its first field, and,
      with ``multiple=True``, Space and Ctrl+A to select several rows. Left and
      Right scroll sideways when the columns are wider than the table. Enter
      (``table_choose``) calls ``on_choose(table)``, if the table has one.
    - **Sorting.** A click on a heading sorts the rows by that column, smallest
      first (``▲``), and another click sorts them largest first (``▼``).
      ``sort(column, reverse=False)`` does the same from code. The highlight and
      selection stay on their rows.
    - **Resizing.** Dragging the ``│`` between two headings changes the width of
      the column on its left.
    - **Scrolling.** A scroll bar appears on the right for the rows, and another
      along the bottom when the columns are wider than the table.
    - **Values.** ``value`` is the index of the highlighted row among the rows as
      given (or, with ``multiple=True``, a tuple of the selected rows' indexes),
      whatever the order shown. ``selected_rows`` holds the rows themselves, and
      ``order`` the indexes in the order shown. ``set_rows(rows)`` shows other
      rows. The colours are ``table``, ``table.header``, ``table.focused`` and
      ``table.selected``.
    """

    style: Style = Style(foreground=BLACK, background=CYAN)
    """The style of the rows."""
    focused_style: Style = Style(foreground=BRIGHT_WHITE, background=GREEN, bold=True)
    """The style of the highlighted row, while the table has the focus."""
    selected_style: Style = Style(foreground=BRIGHT_YELLOW, background=CYAN, bold=True)
    """The style of the selected rows, with ``multiple=True``."""
    header_style: Style = Style(foreground=BLACK, background=WHITE)
    """The style of the headings."""
    column_step: int = 4
    """How many columns of characters Left and Right scroll sideways."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        columns: Sequence[Column],
        row: int,
        column: int,
        width: int,
        height: int,
        *,
        rows: Iterable[Sequence[str]] = (),
        multiple: bool = False,
        on_change: Callable[["Table"], object] | None = None,
        on_choose: Callable[["Table"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        if not columns:
            raise ValueError("a table needs a column")
        if height < 2 or width < 3:
            raise ValueError("a table needs a row for its headings and one more")
        self.table_columns: list[Column] = list(columns)
        """The columns, left to right."""
        self.data: list[list[str]] = []
        """The rows' fields, in the order the rows were given."""
        self.order: list[int] = []
        """The rows' indexes in ``data``, in the order shown."""
        self.sorted_by: int | None = None
        """The column sorted by, if any."""
        self.reverse = False
        """Whether that sorting is largest first."""
        self._left = 0  # columns of characters scrolled off to the left
        self._resizing: int | None = None  # the column whose edge is dragged
        self._side_mouse = False  # whether the mouse is working the bottom bar
        self.side_bar = ScrollBar(0, 0, 2, vertical=False, on_change=self._slid)
        """The scroll bar along the bottom, for columns wider than the table."""
        super().__init__(
            [],
            row,
            column,
            width,
            height,
            multiple=multiple,
            on_change=on_change,  # type: ignore[arg-type]
            on_choose=on_choose,  # type: ignore[arg-type]
            name=name,
            status=status,
        )
        self.set_rows(rows)

    # The rows

    def set_rows(self, rows: Iterable[Sequence[str]]) -> None:
        """Show these rows instead, sorted as before, with nothing
        selected."""
        width = len(self.table_columns)
        self.data = [[*map(str, row), *[""] * width][:width] for row in rows]
        self.selected = set()
        self.cursor = 0
        self._order()

    def _order(self) -> None:
        """Put the rows in order (sorted, if by a column) and show them."""
        order = list(range(len(self.data)))
        column = self.sorted_by
        if column is not None:
            key = self.table_columns[column].key or str.casefold
            order.sort(
                key=lambda index: key(self.data[index][column]), reverse=self.reverse
            )
        self.order = order
        self.set_items(self.data[index][0] for index in order)

    def sort(self, column: int, reverse: bool = False) -> None:
        """Sort the rows by a column, keeping the highlight and the selection
        on the rows they were on."""
        cursor = self.order[self.cursor] if self.order else None
        selected = {self.order[index] for index in self.selected}
        self.sorted_by, self.reverse = column, reverse
        self._order()
        where = {data: shown for shown, data in enumerate(self.order)}
        self.selected = {where[data] for data in selected}
        if cursor is not None:
            self.cursor = where[cursor]
            self._scroll_to_cursor()

    @property
    def value(self) -> int | None | tuple[int, ...]:
        if self.multiple:
            return tuple(sorted(self.order[index] for index in self.selected))
        return self.order[self.cursor] if self.order else None

    @property
    def selected_rows(self) -> list[list[str]]:
        """The selected rows (with single selection, the highlighted row), in
        the order in which they were given."""
        chosen = self.value
        if chosen is None:
            return []
        indexes = chosen if isinstance(chosen, tuple) else (chosen,)
        return [self.data[index] for index in indexes]

    # Layout

    @property
    def content_width(self) -> int:
        """The total width of the columns, including the dividers between
        them."""
        return sum(c.width for c in self.table_columns) + len(self.table_columns) - 1

    def _room(self) -> int:
        """Columns of characters that show (less the right-hand scroll bar)."""
        return self.rect.width - (1 if self._needs_bar() else 0)

    def _needs_side_bar(self) -> bool:
        return self.content_width > self.rect.width - 1

    @property
    def rows(self) -> int:
        """How many rows of fields are shown, below the headings."""
        return max(1, self.rect.height - 1 - (1 if self._needs_side_bar() else 0))

    def _needs_bar(self) -> bool:
        return len(self.items) > max(
            1, self.rect.height - 1 - (1 if self._needs_side_bar() else 0)
        )

    def _column_widths(self) -> list[int]:
        return [self._room()]

    def min_size(self) -> tuple[int, int]:
        return 3, 2  # the headings, and a row

    def _max_left(self) -> int:
        return max(0, self.content_width - self._room())

    def scroll_sideways(self, left: int) -> None:
        """Show the columns starting ``left`` characters in."""
        self._left = max(0, min(left, self._max_left()))

    def _slid(self, scroll_bar: ScrollBar) -> None:
        self.scroll_sideways(scroll_bar.value)

    def index_at(self, row: int, column: int) -> int | None:
        """The row shown at a position within the table (where row 0 is the
        headings), if there is one."""
        del column
        if not 1 <= row <= self.rows:
            return None
        index = self._first + row - 1
        return index if self._valid(index) else None

    def _sync_bar(self) -> None:
        rect = self.rect
        self.scroll_bar.rect = Rect(rect.row + 1, rect.right - 1, self.rows, 1)
        self.scroll_bar.set_range(self._max_first(), self.rows)
        self.scroll_bar.value = self._first

    def _sync_side_bar(self) -> None:
        rect = self.rect
        self.side_bar.rect = Rect(rect.bottom - 1, rect.column, 1, self._room())
        self.side_bar.set_range(self._max_left(), self._room())
        self.side_bar.value = self._left

    def _edges(self) -> list[int]:
        """Where each column's right-hand divider is, from the table's left
        edge as shown (scrolled)."""
        edges, at = [], -self._left
        for column in self.table_columns:
            at += column.width
            edges.append(at)
            at += 1
        return edges

    def column_at(self, column: int) -> int | None:
        """The column of fields at a given column within the table, if there
        is one."""
        at = column + self._left
        for number, field in enumerate(self.table_columns):
            if at < field.width:
                return number
            at -= field.width + 1
            if at < 0:
                return None  # on a divider
        return None

    # Drawing

    def _line(self, fields: Sequence[str]) -> str:
        """A row's fields lined up in their columns, divided."""
        return "\N{BOX DRAWINGS LIGHT VERTICAL}".join(
            column.fit(text) for column, text in zip(self.table_columns, fields)
        )

    def _headings(self) -> list[str]:
        titles = []
        for number, column in enumerate(self.table_columns):
            title = split_mnemonic(column.title)[0]
            if number == self.sorted_by:
                arrow = DOWN_ARROW if self.reverse else UP_ARROW
                if len(title) + 2 <= column.width:
                    title = f"{title} {arrow}"  # the whole title, and the arrow
                else:
                    title = title[: max(0, column.width - 1)] + arrow
            titles.append(title)
        return titles

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        top, left = origin.row + self.rect.row, origin.column + self.rect.column
        room = self._room()
        header = self._line(self._headings())[self._left : self._left + room]
        canvas.write(
            top, left, header.ljust(self.rect.width), self.header_style, clip=origin
        )
        for offset in range(self.rows):
            index = self._first + offset
            if self._valid(index):
                text = self._line(self.data[self.order[index]])
                style = self._item_style(index, focused)
            else:
                text, style = "", self.style
            shown = text[self._left : self._left + room].ljust(room)
            canvas.write(top + 1 + offset, left, shown, style, clip=origin)
        if self._needs_bar():
            self._sync_bar()
            self.scroll_bar.paint(canvas, origin, False)
        if self._needs_side_bar():
            self._sync_side_bar()
            self.side_bar.paint(canvas, origin, False)

    # Input

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Handle keys as a list box does, except that Left and Right scroll
        sideways, and Enter chooses (``table_choose``) if there is an
        ``on_choose``."""
        if self._needs_side_bar():
            if shortcuts.matches("list_left", key):
                self.scroll_sideways(self._left - self.column_step)
                return True
            if shortcuts.matches("list_right", key):
                self.scroll_sideways(self._left + self.column_step)
                return True
        if shortcuts.matches("table_choose", key) and self.on_choose is not None:
            self.choose()
            return True
        return super().handle_key(key, shortcuts)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """A click on a heading sorts the rows by it, and dragging the divider
        between two headings resizes the column on its left. Everything else
        is handled as in a list box, with the bottom scroll bar scrolling
        sideways."""
        inside = (row - self.rect.row, column - self.rect.column)
        if self._resizing is not None:
            return self._resize(event, inside[1])
        if self._needs_side_bar():
            self._sync_side_bar()
            on_side = self.side_bar.rect.contains(row, column)
            if event.action == "press" and event.button == "left":
                self._side_mouse = on_side
            if self._side_mouse or (on_side and event.action == "scroll"):
                if event.action == "release":
                    self._side_mouse = False
                return self.side_bar.handle_mouse(event, row, column)
        if inside[0] == 0 and event.button == "left" and event.action == "press":
            return self._press_heading(inside[1])
        if inside[0] == 0:
            return event.button == "left"
        return super().handle_mouse(event, row, column)

    def _press_heading(self, column: int) -> bool:
        """A press on the headings: on a divider, start resizing; on a
        heading, sort by it (again: the other way round)."""
        if column in self._edges():
            self._resizing = self._edges().index(column)
            return True
        number = self.column_at(column)
        if number is not None:
            again = number == self.sorted_by and not self.reverse
            self.sort(number, reverse=again)
        return True

    def _resize(self, event: MouseEvent, column: int) -> bool:
        """Drag the divider: the column on its left is as wide as reaches it."""
        assert self._resizing is not None
        if event.action == "release":
            self._resizing = None
            return True
        field = self.table_columns[self._resizing]
        start = self._edges()[self._resizing] - field.width
        field.width = max(1, column - start)
        self.scroll_sideways(self._left)
        return True

    def wake_time(self) -> float | None:
        side = self.side_bar.wake_time()
        return side if side is not None else super().wake_time()

    def on_timer(self, now: float) -> None:
        if self.side_bar.wake_time() is not None:
            self._sync_side_bar()
            self.side_bar.on_timer(now)
        else:
            super().on_timer(now)
