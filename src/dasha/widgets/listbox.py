"""List boxes."""

import time
from collections.abc import Callable, Iterable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.style import BLACK, BRIGHT_WHITE, BRIGHT_YELLOW, CYAN, BLUE, Style
from dasha.widgets.base import Widget
from dasha.widgets.scrollbar import ScrollBar


class ListBox(Widget):  # pylint: disable=too-many-instance-attributes
    """A list of items to choose from.

    :param items: The items.
    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param height: Height in rows.
    :param columns: Number of columns.
    :param multiple: Whether several items can be selected.
    :param case_sensitive: Whether type-ahead matches case.
    :param selected: Initially selected index or indexes.
    :param on_change: Called with the box when the selection changes.
    :param on_choose: Called with the box on a double-click.
    :param name: Widget name.
    :param status: Status bar text.
    """

    focusable = True
    style: Style = Style(foreground=BLACK, background=CYAN)
    """The style of the items."""
    focused_style: Style = Style(foreground=BRIGHT_WHITE, background=BLUE, bold=True)
    """Highlighted item style while focused."""
    selected_style: Style = Style(foreground=BRIGHT_YELLOW, background=CYAN, bold=True)
    """Selected item style."""
    divider: str = "\N{BOX DRAWINGS LIGHT VERTICAL}"
    """Column divider character."""
    type_ahead_timeout: float = 1.0
    """Seconds before type-ahead resets."""
    wheel_rows: int = 3
    """Rows per mouse wheel notch."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        items: Iterable[str],
        row: int,
        column: int,
        width: int,
        height: int,
        *,
        columns: int = 1,
        multiple: bool = False,
        case_sensitive: bool = False,
        selected: int | Iterable[int] | None = None,
        on_change: Callable[["ListBox"], object] | None = None,
        on_choose: Callable[["ListBox"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        if columns < 1:
            raise ValueError("columns must be at least 1")
        if width < 2 * columns + 1 or height < (2 if columns > 1 else 1):
            raise ValueError("the list box is too small")
        super().__init__(row, column, width, height, name=name, status=status)
        self.columns = columns
        self.multiple = multiple
        self.case_sensitive = case_sensitive
        """Whether typing to find an item tells capitals from small letters."""
        self._typed = ""  # what has been typed to find an item
        self._typed_at = 0.0  # when the last of it was typed
        self.on_change = on_change
        self.on_choose = on_choose
        self._anchor = 0  # where a Shift+click range starts
        self.items: list[str] = []
        self.cursor = 0
        """The highlighted item (with single selection, the selected one)."""
        self.selected: set[int] = set()
        """With multiple selection, the indexes of the selected items."""
        self._first = 0  # the first row (one column) or column showing
        self._bar_mouse = False  # whether the mouse is working the scroll bar
        self.scroll_bar = ScrollBar(
            0, 0, 2, vertical=columns == 1, on_change=self._scrolled
        )
        """The list box's own scroll bar; it is not in the window."""
        self.set_items(items)
        if isinstance(selected, int):
            self.cursor = max(0, min(selected, len(self.items) - 1))
            self._scroll_to_cursor()
        elif selected is not None:
            self.selected = {index for index in selected if self._valid(index)}

    # Items and selection

    def set_items(self, items: Iterable[str]) -> None:
        """Show other items.

        :param items: The new items.
        """
        self.items = list(items)
        self.selected = {index for index in self.selected if self._valid(index)}
        self.cursor = max(0, min(self.cursor, len(self.items) - 1))
        self._scroll_to_cursor()

    def _valid(self, index: int) -> bool:
        return 0 <= index < len(self.items)

    @property
    def value(self) -> int | None | tuple[int, ...]:
        if self.multiple:
            return tuple(sorted(self.selected))
        return self.cursor if self.items else None

    @property
    def selected_items(self) -> list[str]:
        """The selected items, in the order of the list."""
        if self.multiple:
            return [self.items[index] for index in sorted(self.selected)]
        return [self.items[self.cursor]] if self.items else []

    def is_selected(self, index: int) -> bool:
        """Whether an item is selected.

        :param index: Item index.
        """
        if self.multiple:
            return index in self.selected
        return bool(self.items) and index == self.cursor

    def choose(self) -> None:
        """Choose the highlighted item, as a double-click does."""
        if self.on_choose is not None:
            self.on_choose(self)
        elif self.window is not None and (button := self.window.default_button):
            button.activate()

    def select_range(self, first: int, last: int) -> None:
        """Select a range of items.

        :param first: One end of the range.
        :param last: The other end.
        """
        if not self.multiple:
            return
        low, high = sorted((first, last))
        added = {index for index in range(low, high + 1) if self._valid(index)}
        if not added <= self.selected:
            self.selected |= added
            self._changed()

    def toggle_all(self) -> None:
        """Select or deselect every item."""
        if not self.multiple or not self.items:
            return
        everything = set(range(len(self.items)))
        self.selected = set() if self.selected == everything else everything
        self._changed()

    def toggle(self, index: int) -> None:
        """Select or deselect an item.

        :param index: Item index.
        """
        if self.multiple and self._valid(index):
            self.selected ^= {index}
            self._anchor = index
            self._changed()

    def move_to(self, index: int) -> None:
        """Highlight an item and scroll to it.

        :param index: Item index.
        """
        if not self.items:
            return
        before = self.cursor
        self.cursor = max(0, min(index, len(self.items) - 1))
        self._scroll_to_cursor()
        if not self.multiple and self.cursor != before:
            self._changed()

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change(self)

    # Layout

    def min_size(self) -> tuple[int, int]:
        return 2 * self.columns + 1, 2 if self._multicolumn else 1

    def on_resize(self) -> None:
        """When more or fewer rows are shown, keep the highlight in view."""
        self._scroll_to_cursor()

    @property
    def _multicolumn(self) -> bool:
        return self.columns > 1

    def _needs_bar(self) -> bool:
        if self._multicolumn:
            return -(-len(self.items) // self.rect.height) > self.columns
        return len(self.items) > self.rect.height

    @property
    def rows(self) -> int:
        """How many rows of items are shown."""
        if self._multicolumn and self._needs_bar():
            return self.rect.height - 1  # the bottom row is the scroll bar
        return self.rect.height

    def _column_widths(self) -> list[int]:
        """The width of each column of items, without the dividers."""
        width = self.rect.width
        if not self._multicolumn and self._needs_bar():
            width -= 1  # the right column is the scroll bar
        room = width - (self.columns - 1)
        each = room // self.columns
        return [each] * (self.columns - 1) + [room - each * (self.columns - 1)]

    def _max_first(self) -> int:
        if self._multicolumn:
            item_columns = -(-len(self.items) // self.rows)
            return max(0, item_columns - self.columns)
        return max(0, len(self.items) - self.rows)

    @property
    def first_visible(self) -> int:
        """The first row (with one column) or column of items shown."""
        return self._first

    def scroll_to(self, first: int) -> None:
        """Scroll without moving the highlight.

        :param first: First row or column to show.
        """
        self._first = max(0, min(first, self._max_first()))

    def _scroll_to_cursor(self) -> None:
        if self._multicolumn:
            position, showing = self.cursor // self.rows, self.columns
        else:
            position, showing = self.cursor, self.rows
        if position < self._first:
            self._first = position
        elif position >= self._first + showing:
            self._first = position - showing + 1
        self.scroll_to(self._first)

    def _slot(self, index: int) -> tuple[int, int] | None:
        """An item's (row, column offset), or ``None``.

        :param index: Item index.
        """
        if self._multicolumn:
            item_column, row = divmod(index, self.rows)
            shown = item_column - self._first
        else:
            row, shown = index - self._first, 0
        if not 0 <= row < self.rows or not 0 <= shown < self.columns:
            return None
        widths = self._column_widths()
        return row, sum(widths[:shown]) + shown

    def index_at(self, row: int, column: int) -> int | None:
        """The item at a position, if any.

        :param row: Row in the box.
        :param column: Column in the box.
        """
        if not 0 <= row < self.rows:
            return None
        left = 0
        for shown, width in enumerate(self._column_widths()):
            if left <= column < left + width:
                if self._multicolumn:
                    index = (self._first + shown) * self.rows + row
                else:
                    index = self._first + row
                return index if self._valid(index) else None
            left += width + 1  # and the divider
        return None

    def _sync_bar(self) -> None:
        """Update the scroll bar."""
        rect, scroll_bar = self.rect, self.scroll_bar
        if self._multicolumn:
            scroll_bar.rect = Rect(rect.bottom - 1, rect.column, 1, rect.width)
            page = self.columns
        else:
            scroll_bar.rect = Rect(rect.row, rect.right - 1, rect.height, 1)
            page = self.rows
        scroll_bar.set_range(self._max_first(), page)
        scroll_bar.value = self._first

    def _scrolled(self, scroll_bar: ScrollBar) -> None:
        self.scroll_to(scroll_bar.value)

    # Drawing

    def _item_style(self, index: int, focused: bool) -> Style:
        selected = self.is_selected(index)
        if focused and index == self.cursor:
            if self.multiple and selected:
                # Highlighted and selected: the selection's colour on green.
                return Style(
                    foreground=self.selected_style.foreground,
                    background=self.focused_style.background,
                    bold=True,
                    reverse=self.focused_style.reverse,
                    underline=self.selected_style.underline,
                )
            return self.focused_style
        return self.selected_style if selected else self.style

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        top = origin.row + self.rect.row
        left = origin.column + self.rect.column
        rect = self.rect
        canvas.fill(
            origin.intersect(Rect(top, left, rect.height, rect.width)), " ", self.style
        )
        self._paint_dividers(canvas, origin, top, left)
        widths = self._column_widths()
        for index, item in enumerate(self.items):
            slot = self._slot(index)
            if slot is None:
                continue
            row, column = slot
            width = widths[self._shown_column(column)]
            style = self._item_style(index, focused)
            canvas.write(
                top + row, left + column, item[:width].ljust(width), style, clip=origin
            )
        # No terminal cursor: the highlight already shows where the user is.
        if self._needs_bar():
            self._sync_bar()
            self.scroll_bar.paint(canvas, origin, False)

    def _paint_dividers(
        self, canvas: Canvas, origin: Rect, top: int, left: int
    ) -> None:
        """Draw the column dividers.

        :param canvas: Canvas to draw on.
        :param origin: The window's interior on screen.
        :param top: Box's top row.
        :param left: Box's left column.
        """
        offset = 0
        for width in self._column_widths()[:-1]:
            offset += width
            for row in range(self.rows):
                canvas.write(
                    top + row, left + offset, self.divider, self.style, clip=origin
                )
            offset += 1

    def _shown_column(self, offset: int) -> int:
        """The shown column at an offset.

        :param offset: Columns from the left edge.
        """
        left = 0
        for shown, width in enumerate(self._column_widths()):
            if offset < left + width:
                return shown
            left += width + 1
        return self.columns - 1

    # Input

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Move, select or type ahead.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        if shortcuts.matches("list_toggle", key):
            self.toggle(self.cursor)
            return True  # with single selection too, so Space is not a button
        if shortcuts.matches("list_select_all", key) and self.multiple:
            self.toggle_all()
            return True
        across = self.rows if self._multicolumn else 0
        page = self.rows * self.columns
        moves = {
            "list_up": self.cursor - 1,
            "list_down": self.cursor + 1,
            "list_left": self.cursor - across,
            "list_right": self.cursor + across,
            "list_page_up": self.cursor - page,
            "list_page_down": self.cursor + page,
            "list_home": 0,
            "list_end": len(self.items) - 1,
        }
        for action, index in moves.items():
            if shortcuts.matches(action, key):
                if action in ("list_left", "list_right") and not across:
                    return False  # one column: leave them for the window
                self.move_to(index)
                return True
        if len(key) == 1 and key.isprintable() and self.items:
            self.type_ahead(key)
            return True
        return False

    def type_ahead(self, character: str) -> None:
        """Find an item by typing.

        :param character: The character typed.
        """
        now = time.monotonic()
        if now - self._typed_at > self.type_ahead_timeout:
            self._typed = ""
        self._typed += character
        self._typed_at = now
        typed = self._fold(self._typed)
        found = self._first_starting(typed, 0)
        if found is None and len(set(typed)) == 1:
            # "ttt" matches nothing: step to the next item starting with "t".
            found = self._first_starting(typed[0], self.cursor + 1)
        if found is not None:
            self.move_to(found)

    def _fold(self, text: str) -> str:
        """Text folded for matching.

        :param text: The text.
        """
        return text if self.case_sensitive else text.casefold()

    def _first_starting(self, prefix: str, start: int) -> int | None:
        """The first item starting with a prefix, if any.

        :param prefix: Text to match.
        :param start: Index to start from.
        """
        count = len(self.items)
        for step in range(count):
            index = (start + step) % count
            if self._fold(self.items[index]).startswith(prefix):
                return index
        return None

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Highlight, toggle or scroll with the mouse.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        if self._needs_bar():
            self._sync_bar()
            on_bar = self.scroll_bar.rect.contains(row, column)
            if event.action == "press" and event.button == "left":
                self._bar_mouse = on_bar
            if self._bar_mouse or (on_bar and event.action == "scroll"):
                if event.action == "release":
                    self._bar_mouse = False
                return self.scroll_bar.handle_mouse(event, row, column)
        if event.action == "scroll":
            return self._wheel(event)
        if event.button != "left":
            return False
        if event.action == "press":
            index = self.index_at(row - self.rect.row, column - self.rect.column)
            if index is not None:
                self._click(index, event)
        return event.action in ("press", "drag", "release")

    def point_at(self, row: int, column: int) -> None:
        """Highlight the right-clicked item.

        :param row: Row clicked.
        :param column: Column clicked.
        """
        index = self.index_at(row - self.rect.row, column - self.rect.column)
        if index is not None:
            self.move_to(index)

    def _click(self, index: int, event: MouseEvent) -> None:
        """Handle a press on an item.

        :param index: Item index.
        :param event: The mouse event.
        """
        double = event.clicks >= 2 and index == self.cursor
        self.move_to(index)
        if double:
            self.choose()  # the first press already selected or toggled it
        elif event.shift and self.multiple:
            self.select_range(self._anchor, index)
        else:
            self.toggle(index)
            self._anchor = index

    def wake_time(self) -> float | None:
        return self.scroll_bar.wake_time()  # its arrows repeat while held

    def on_timer(self, now: float) -> None:
        self._sync_bar()
        self.scroll_bar.on_timer(now)

    def _wheel(self, event: MouseEvent) -> bool:
        """Scroll for the wheel; return whether it scrolled.

        :param event: The mouse event.
        """
        if not self._needs_bar():
            return False
        notch = 1 if self._multicolumn else self.wheel_rows
        back = event.button in ("up", "left")
        self.scroll_to(self._first + (-notch if back else notch))
        return True
