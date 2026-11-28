"""Sortable, resizable tables."""

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
    BLUE,
    WHITE,
    Style,
)
from dasha.widgets.listbox import ListBox
from dasha.widgets.scrollbar import ScrollBar

UP_ARROW = "\N{BLACK UP-POINTING TRIANGLE}"
DOWN_ARROW = "\N{BLACK DOWN-POINTING TRIANGLE}"
"""Sort direction arrows."""


@dataclass
class Column:
    """A table column."""

    title: str
    width: int
    align: str = "left"
    key: Callable[[str], Any] | None = None

    def __post_init__(self) -> None:
        if self.align not in ("left", "right", "centre"):
            raise ValueError("align must be left, right or centre")
        self.width = max(1, self.width)

    def fit(self, text: str) -> str:
        """A field cut and aligned to the column.

        :param text: The field.
        """
        text = text[: self.width]
        if self.align == "right":
            return text.rjust(self.width)
        if self.align == "centre":
            return text.center(self.width)
        return text.ljust(self.width)


class Table(ListBox):  # pylint: disable=too-many-instance-attributes
    """Rows of fields under column headings.

    :param columns: The columns.
    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param height: Height in rows.
    :param rows: The rows of fields.
    :param multiple: Whether several rows can be selected.
    :param on_change: Called with the table when the selection changes.
    :param on_choose: Called with the table when a row is chosen.
    :param name: Widget name.
    :param status: Status bar text.
    """

    style: Style = Style(foreground=BLACK, background=CYAN)
    """The style of the rows."""
    focused_style: Style = Style(foreground=BRIGHT_WHITE, background=BLUE, bold=True)
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
        """Show other rows.

        :param rows: The new rows.
        """
        width = len(self.table_columns)
        self.data = [[*map(str, row), *[""] * width][:width] for row in rows]
        self.selected = set()
        self.cursor = 0
        self._order()

    def _order(self) -> None:
        """Sort and show the rows."""
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
        """Sort by a column.

        :param column: Column index.
        :param reverse: Whether largest comes first.
        """
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
        """The selected rows."""
        chosen = self.value
        if chosen is None:
            return []
        indexes = chosen if isinstance(chosen, tuple) else (chosen,)
        return [self.data[index] for index in indexes]

    # Layout

    @property
    def content_width(self) -> int:
        """Total width of the columns and dividers."""
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
        """Scroll sideways.

        :param left: Characters to scroll in.
        """
        self._left = max(0, min(left, self._max_left()))

    def _slid(self, scroll_bar: ScrollBar) -> None:
        self.scroll_sideways(scroll_bar.value)

    def index_at(self, row: int, column: int) -> int | None:
        """The row at a position, if any.

        :param row: Row in the table.
        :param column: Column in the table.
        """
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
        """Each column's right divider position."""
        edges, at = [], -self._left
        for column in self.table_columns:
            at += column.width
            edges.append(at)
            at += 1
        return edges

    def column_at(self, column: int) -> int | None:
        """The column at a position, if any.

        :param column: Column in the table.
        """
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
        """A row's fields laid out.

        :param fields: The fields.
        """
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
        """Handle keys as a list box does.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
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
        """Sort, resize or select with the mouse.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
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
        """Start resizing or sort by a heading.

        :param column: Column in the table.
        """
        if column in self._edges():
            self._resizing = self._edges().index(column)
            return True
        number = self.column_at(column)
        if number is not None:
            again = number == self.sorted_by and not self.reverse
            self.sort(number, reverse=again)
        return True

    def _resize(self, event: MouseEvent, column: int) -> bool:
        """Resize a column by dragging.

        :param event: The mouse event.
        :param column: Column in the table.
        """
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
