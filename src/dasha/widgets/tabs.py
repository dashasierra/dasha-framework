"""Tabbed pages."""

from collections.abc import Callable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.menu import mnemonic_key, split_mnemonic
from dasha.shortcuts import Shortcuts
from dasha.style import BRIGHT_BLACK, Style
from dasha.widgets.base import Widget, run_shortcut
from dasha.widgets.container import Container
from dasha.widgets.label import on_window, paint_mnemonic_label

DIVIDER = "\N{BOX DRAWINGS LIGHT VERTICAL}"
LINE = "\N{BOX DRAWINGS LIGHT HORIZONTAL}"
JOIN = "\N{BOX DRAWINGS LIGHT UP AND HORIZONTAL}"
"""Tab line characters."""
OPEN_LEFT = "\N{BOX DRAWINGS LIGHT UP AND LEFT}"
OPEN_RIGHT = "\N{BOX DRAWINGS LIGHT UP AND RIGHT}"
"""Corner characters for the chosen tab."""


class TabPage(Container):
    """One page of a ``Tabs`` widget.

    :param tabs: The tabs widget.
    :param label: Tab label; ``&`` marks the mnemonic.
    """

    noun = "tabs"

    def __init__(self, tabs: "Tabs", label: str) -> None:
        super().__init__()
        self.tabs = tabs
        self.label = label
        """The tab's text, ``&`` marking its mnemonic letter."""

    @property
    def anchor(self) -> Widget:
        return self.tabs

    @property
    def is_showing_children(self) -> bool:
        return self.tabs.selected_page is self

    def content_origin(self) -> tuple[int, int]:
        return self.home_row + 2, self.tabs.rect.column


class Tabs(Widget):  # pylint: disable=too-many-instance-attributes
    """Pages of widgets chosen by a row of tabs.

    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param height: Height in rows.
    :param on_change: Called with the tabs when the user changes page.
    :param name: Widget name.
    :param status: Status bar text.
    """

    focusable = True
    style: Style = Style()
    """The style of the tabs not selected, and of the lines."""
    selected_style: Style = Style(bold=True)
    """The style of the selected tab."""
    focused_style: Style = Style(bold=True, reverse=True)
    """The style of the selected tab, while the tabs have the focus."""
    disabled_style: Style = Style(foreground=BRIGHT_BLACK)
    """The style of the tabs that cannot be chosen."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        row: int,
        column: int,
        width: int,
        height: int,
        *,
        on_change: Callable[["Tabs"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        if height < 3:
            raise ValueError("tabs need a row for the tabs, a line and a page")
        super().__init__(row, column, width, height, name=name, status=status)
        self.pages: list[TabPage] = []
        """The pages, in the order of their tabs."""
        self.disabled: set[int] = set()
        """The numbers of the pages that cannot be chosen (see ``disable``)."""
        self.on_change = on_change
        self._index = 0

    # The pages

    def add_page(self, label: str) -> TabPage:
        """Add a page and return it.

        :param label: Tab label; ``&`` marks the mnemonic.
        """
        page = TabPage(self, label)
        self.pages.append(page)
        return page

    @property
    def selected(self) -> int:
        """The number of the selected page."""
        return self._index

    @property
    def value(self) -> int:
        return self._index

    @property
    def selected_page(self) -> TabPage | None:
        """The selected page (``None`` before any page has been added)."""
        return self.pages[self._index] if self.pages else None

    def help_topic(self) -> str | None:
        """The selected page's help topic, or the widget's."""
        page = self.selected_page
        return page.help if page is not None and page.help else self.help

    def select(self, index: int) -> None:
        """Choose a page, as the user does.

        :param index: Page index.
        """
        if not self.pages:
            return
        index = max(0, min(index, len(self.pages) - 1))
        if index == self._index or not self.is_enabled(index):
            return
        self._show(index)
        if self.on_change is not None:
            self.on_change(self)

    def _show(self, index: int) -> None:
        """Show a page.

        :param index: Page index.
        """
        self._index = index
        window = self.window
        if window is not None:
            focused = window.focused
            if focused is not None and not focused.is_shown:
                window.focus(self)

    def step(self, step: int) -> None:
        """Choose a page, wrapping round.

        :param step: Pages to move by.
        """
        number = self._next_enabled(step)
        if number is not None:
            self.select(number)

    def _next_enabled(self, step: int) -> int | None:
        """The next enabled page, or ``None``.

        :param step: Pages to move by.
        """
        count = len(self.pages)
        if not count or not step % count:
            return None
        number = self._index
        for _ in range(count - 1):
            number = (number + step) % count
            if self.is_enabled(number):
                return number
        return None

    def _beside(self, step: int) -> None:
        """Choose the nearest enabled page to one side.

        :param step: -1 or 1.
        """
        number = self._index + step
        while 0 <= number < len(self.pages) and not self.is_enabled(number):
            number += step
        if 0 <= number < len(self.pages):
            self.select(number)

    # Disabled pages

    def is_enabled(self, index: int) -> bool:
        """Whether a page can be chosen.

        :param index: Page index.
        """
        return index not in self.disabled

    def disable(self, *indexes: int) -> None:
        """Grey out pages.

        :param indexes: Page indexes.
        """
        self.disabled.update(indexes)
        if self.pages and not self.is_enabled(self._index):
            number = self._next_enabled(1)
            if number is not None:
                self._show(number)

    def enable(self, *indexes: int) -> None:
        """Re-enable pages.

        :param indexes: Page indexes.
        """
        self.disabled.difference_update(indexes)

    def can_focus(self) -> bool:
        """Not while every page is disabled."""
        return self.focusable and (
            not self.pages or any(map(self.is_enabled, range(len(self.pages))))
        )

    # Where each tab is

    def _spans(self) -> list[tuple[int, int]]:
        """Each tab's (first column, width)."""
        spans, column = [], 0
        for page in self.pages:
            width = len(split_mnemonic(page.label)[0]) + 2
            spans.append((column, width))
            column += width + 1
        return spans

    def tab_at(self, column: int) -> int | None:
        """The tab at a column, if any.

        :param column: Column in the window's content.
        """
        offset = column - self.rect.column
        for number, (first, width) in enumerate(self._spans()):
            if first <= offset < first + width:
                return number
        return None

    def min_size(self) -> tuple[int, int]:
        return 1, 3

    # Drawing and input

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        body = self.window.body_style if self.window is not None else Style()
        plain = on_window(self.style, body)
        chosen = on_window(self.focused_style if focused else self.selected_style, body)
        at = (origin.row + self.rect.row, origin.column + self.rect.column)
        width = self.rect.width
        canvas.write(at[0], at[1], " " * width, plain, clip=origin)
        line = [LINE] * width
        disabled = on_window(self.disabled_style, body)
        for number, span in enumerate(self._spans()):
            if span[0] >= width:
                break
            if not self.is_enabled(number):
                style = disabled
            else:
                style = chosen if number == self._index else plain
            self._paint_tab(
                canvas, origin, at=at, number=number, span=span, styles=(style, plain)
            )
            divider = span[0] + span[1]
            if divider < width:
                line[divider] = JOIN
            if number == self._index:
                for column in range(span[0], min(divider, width)):
                    line[column] = " "  # the chosen tab opens onto its page
                if 0 < span[0] <= width:
                    line[span[0] - 1] = OPEN_LEFT
                if divider < width:
                    line[divider] = OPEN_RIGHT
        canvas.write(at[0] + 1, at[1], "".join(line), plain, clip=origin)

    def _paint_tab(
        self,
        canvas: Canvas,
        origin: Rect,
        *,
        at: tuple[int, int],
        number: int,
        span: tuple[int, int],
        styles: tuple[Style, Style],
    ) -> None:
        """Draw one tab and its divider.

        :param canvas: Canvas to draw on.
        :param origin: The window's interior on screen.
        :param at: Screen row and column.
        :param number: Page index.
        :param span: First column and width.
        :param styles: Tab and plain styles.
        """
        (row, left), (first, length), width = at, span, self.rect.width
        style, plain = styles
        canvas.write(row, left + first, " ", style, clip=origin)
        paint_mnemonic_label(
            canvas,
            origin,
            (row, left + first + 1),
            self.pages[number].label,
            style,
            width=min(length - 2, width - first - 1),
            underline=self.is_enabled(number),
        )
        if first + length - 1 < width:
            canvas.write(row, left + first + length - 1, " ", style, clip=origin)
        if first + length < width:
            canvas.write(row, left + first + length, DIVIDER, plain, clip=origin)

    def mnemonics(self) -> set[str]:
        return {
            letter
            for number, page in enumerate(self.pages)
            if self.is_enabled(number)
            and (letter := mnemonic_key(page.label)) is not None
        }

    def activate_mnemonic(self, letter: str) -> None:
        for number, page in enumerate(self.pages):
            if self.is_enabled(number) and mnemonic_key(page.label) == letter:
                self.select(number)
                return

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Choose a neighbouring tab.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        actions: dict[str, Callable[[], object]] = {
            "tabs_left": lambda: self._beside(-1),
            "tabs_right": lambda: self._beside(1),
        }
        return run_shortcut(shortcuts, key, actions)

    def window_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Choose the next or previous page.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        actions: dict[str, Callable[[], object]] = {
            "tabs_next": lambda: self.step(1),
            "tabs_previous": lambda: self.step(-1),
        }
        return bool(self.pages) and run_shortcut(shortcuts, key, actions)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Choose the tab clicked.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        if event.button != "left" or row != self.rect.row:
            return False
        if event.action == "press":
            index = self.tab_at(column)
            if index is None:
                return False
            self.select(index)
        return event.action in ("press", "drag", "release")
