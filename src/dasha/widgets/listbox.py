"""List boxes: a list of items from which to choose."""

import time
from collections.abc import Callable, Iterable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.style import BLACK, BRIGHT_WHITE, BRIGHT_YELLOW, CYAN, GREEN, Style
from dasha.widgets.base import Widget
from dasha.widgets.scrollbar import ScrollBar


class ListBox(Widget):  # pylint: disable=too-many-instance-attributes
    """A ``ListBox`` is a list of items, one per line, from which to choose,
    such as a list of file names.

    ::

        # Pick one, from two columns:
        ListBox(items=names, row=0, column=0, width=32, height=7, columns=2)
        # Pick several:
        ListBox(
            items=names,
            row=2,
            column=2,
            width=34,
            height=8,
            multiple=True,
            name="files",
        )

    - **Single selection** (the default). The highlighted item is the selected
      one: moving onto an item selects it, and it stays selected. ``value`` is its
      index (``None`` for an empty list).
    - **Multiple selection** (``multiple=True``). Moving only moves the
      highlight. Space, or a click, selects or deselects the highlighted item, so
      any number of items can be selected. ``value`` is a tuple of their indexes,
      and ``selected`` is the set of them. ``selected=`` sets which items start
      selected (or, with single selection, which one).

    ``selected_items`` holds the selected items themselves, and ``on_change(box)``
    is called whenever the selection changes. ``set_items(items)`` shows other
    items, keeping the highlight and any selections that still exist.

    **Columns and scrolling.** With one column, the items run down the box, and a
    vertical scroll bar takes up its right edge when there are more items than
    fit. With ``columns=2`` or more, the items fill each column from top to
    bottom and then the next, with the columns separated by ``│``. When there
    are more columns of items than can be shown, a horizontal scroll bar takes up
    the bottom row and scrolls one column at a time. The bars appear only when
    needed, and scrolling with them, or with the mouse wheel, moves the view
    without moving the highlight. Items too long for their column are cut
    off.

    - Up / Down (``list_up`` / ``list_down``): move by one item
    - Left / Right (``list_left`` / ``list_right``): move by one column (with
      one column, these keys are left for the window)
    - PgUp / PgDn (``list_page_up`` / ``list_page_down``): move by a page, which
      is every item showing
    - Home / End (``list_home`` / ``list_end``): go to the first / last item
    - Space (``list_toggle``): select or deselect the item, with multiple
      selection (with single selection it does nothing, so that it does not
      press a button)
    - Ctrl+A (``list_select_all``): with multiple selection, select every item,
      or, if every item is already selected, deselect them all
    - Typing: go to the first item starting with what has been typed (see
      below)
    - A click on an item: highlight it, and with multiple selection, also
      select or deselect it
    - Shift and a click on an item: with multiple selection, select every item
      from the one last clicked or toggled to this one
    - A double-click on an item: choose it, by calling ``on_choose(box)``, or
      otherwise by pressing the window's default button
    - The scroll bar or mouse wheel: scroll the view

    **Typing to find an item.** Typing the start of an item goes straight to
    it: in a list of files, typing ``tur`` goes to ``turtle.exe``, or to whichever
    item is the first to start with ``tur``. Each character typed narrows the
    search. After ``ListBox.type_ahead_timeout`` seconds (1) without typing,
    what was typed is forgotten and the next character starts a new search, so
    a wrong key can be undone by waiting a moment. Typing the same letter again
    and again (``t``, ``t``, ``t``) steps through the items starting with it
    instead. Finding an item only moves the highlight: with multiple selection,
    nothing is selected (with single selection, the highlighted item is the
    selected one, as with the arrow keys). Matching ignores case, unless the list
    box is created with ``case_sensitive=True``. ``type_ahead(character)`` does
    the same from code.

    A double-click chooses an item, as in a file dialog: the list box calls
    ``on_choose(box)`` if it was given one, and otherwise presses the window's
    default button, so that in a dialog a double-click is the same as OK. With
    multiple selection, the first press of the double-click has already toggled
    the item, and the second press does not toggle it back. ``choose()`` does
    the same from code, and ``select_range(first, last)`` does what Shift and
    a click do.

    Tab, Escape and Enter are left for the window, so Enter presses a dialog's
    default button. The colours are ``listbox``, ``listbox.focused`` (the
    highlighted item while the box has the focus), ``listbox.selected`` and
    ``scrollbar``.
    """

    focusable = True
    style: Style = Style(foreground=BLACK, background=CYAN)
    """The style of the items."""
    focused_style: Style = Style(foreground=BRIGHT_WHITE, background=GREEN, bold=True)
    """The style of the highlighted item, while the list box has the
    focus."""
    selected_style: Style = Style(foreground=BRIGHT_YELLOW, background=CYAN, bold=True)
    """The style of selected items (with single selection, when the box does
    not have the focus)."""
    divider: str = "\N{BOX DRAWINGS LIGHT VERTICAL}"
    """The line between columns of items: ``│`` (code page 437 glyph
    179)."""
    type_ahead_timeout: float = 1.0
    """How many seconds without typing before what was typed is forgotten,
    so that typing starts a new search. Set ``ListBox.type_ahead_timeout`` to
    change it for a whole project."""
    wheel_rows: int = 3
    """How many rows one notch of the mouse wheel scrolls, with one column
    (with more columns, it scrolls by one column)."""

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
        """Show these items instead, keeping the highlight (and, with multiple
        selection, the selected items) where they still exist."""
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
        """Whether an item is selected."""
        if self.multiple:
            return index in self.selected
        return bool(self.items) and index == self.cursor

    def choose(self) -> None:
        """Do what a double-click does: call ``on_choose``, or otherwise press
        the window's default button (OK in a dialog), if it has one."""
        if self.on_choose is not None:
            self.on_choose(self)
        elif self.window is not None and (button := self.window.default_button):
            button.activate()

    def select_range(self, first: int, last: int) -> None:
        """With multiple selection, select every item from ``first`` to
        ``last`` (in either order), adding to what is already selected."""
        if not self.multiple:
            return
        low, high = sorted((first, last))
        added = {index for index in range(low, high + 1) if self._valid(index)}
        if not added <= self.selected:
            self.selected |= added
            self._changed()

    def toggle_all(self) -> None:
        """With multiple selection, select every item, or if every item is
        already selected, deselect them all (Ctrl+A)."""
        if not self.multiple or not self.items:
            return
        everything = set(range(len(self.items)))
        self.selected = set() if self.selected == everything else everything
        self._changed()

    def toggle(self, index: int) -> None:
        """With multiple selection, select or deselect an item."""
        if self.multiple and self._valid(index):
            self.selected ^= {index}
            self._anchor = index
            self._changed()

    def move_to(self, index: int) -> None:
        """Highlight an item (kept within range), scrolling it into view. With
        single selection, this also selects it."""
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
        """Show the items from this row (with one column) or column onwards,
        without moving the highlight."""
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
        """Where an item shows within the box (row, column offset), or
        ``None`` if it is scrolled out of view."""
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
        """The item at a position within the box, if there is one."""
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
        """Put the scroll bar along the right or bottom edge, showing where
        the list is scrolled to."""
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
        """The ``│`` lines between the columns."""
        offset = 0
        for width in self._column_widths()[:-1]:
            offset += width
            for row in range(self.rows):
                canvas.write(
                    top + row, left + offset, self.divider, self.style, clip=origin
                )
            offset += 1

    def _shown_column(self, offset: int) -> int:
        """Which shown column starts at an offset from the box's left edge."""
        left = 0
        for shown, width in enumerate(self._column_widths()):
            if offset < left + width:
                return shown
            left += width + 1
        return self.columns - 1

    # Input

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Move the highlight, select with Space, or jump to the next item
        starting with a typed letter. Tab, Escape and Enter are left for the
        window, so that Enter presses a dialog's default button."""
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
        """Find an item by typing: what has been typed so far (forgotten after
        ``type_ahead_timeout`` seconds without typing) moves to the first item
        that starts with it. Typing the same letter over and over instead steps
        through the items starting with that letter, as in Windows. This moves
        only the highlight: with multiple selection, nothing is selected."""
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
        """Text as matching compares it: as it is, or in either case."""
        return text if self.case_sensitive else text.casefold()

    def _first_starting(self, prefix: str, start: int) -> int | None:
        """The first item from ``start`` on (wrapping round) that starts
        with ``prefix``, if any."""
        count = len(self.items)
        for step in range(count):
            index = (start + step) % count
            if self._fold(self.items[index]).startswith(prefix):
                return index
        return None

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """A click highlights an item (and with multiple selection, toggles
        it). The scroll bar and the mouse wheel scroll without moving the
        highlight."""
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
        """A right-click on an item highlights it, for its context menu (with
        multiple selection, without selecting anything more)."""
        index = self.index_at(row - self.rect.row, column - self.rect.column)
        if index is not None:
            self.move_to(index)

    def _click(self, index: int, event: MouseEvent) -> None:
        """A press on an item: highlight it, then toggle it, select a range
        (Shift), or on the second press of a double-click, choose it."""
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
        """Scroll for the mouse wheel; ``False`` if there is nothing to
        scroll, so the window can scroll instead."""
        if not self._needs_bar():
            return False
        notch = 1 if self._multicolumn else self.wheel_rows
        back = event.button in ("up", "left")
        self.scroll_to(self._first + (-notch if back else notch))
        return True
