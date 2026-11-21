"""Scroll bar widgets."""

import time
from collections.abc import Callable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.scrollbar import AutoRepeat, ScrollBarLayout
from dasha.style import BLUE, CYAN, Style
from dasha.widgets.base import Widget


class ScrollBar(Widget):  # pylint: disable=too-many-instance-attributes
    """A vertical or horizontal scroll bar.

    :param row: Row in the window.
    :param column: Column in the window.
    :param length: Length in cells.
    :param vertical: Whether it is vertical.
    :param value: Initial position.
    :param maximum: Largest position.
    :param page: Amount shown at once.
    :param line: Amount an arrow moves.
    :param on_change: Called with the bar when the user moves it.
    :param name: Widget name.
    :param status: Status bar text.
    """

    style: Style = Style(foreground=BLUE, background=CYAN)
    """The style of the arrows, the track and the thumb."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        row: int,
        column: int,
        length: int,
        *,
        vertical: bool = True,
        value: int = 0,
        maximum: int = 0,
        page: int = 1,
        line: int = 1,
        on_change: Callable[["ScrollBar"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        if length < 2:
            raise ValueError("a scroll bar needs room for its two arrows")
        width, height = (1, length) if vertical else (length, 1)
        super().__init__(row, column, width, height, name=name, status=status)
        self.vertical = vertical
        self.maximum = max(0, maximum)
        self.page = max(1, page)
        self.line = max(1, line)
        self.on_change = on_change
        self._value = 0
        self.value = value
        self._dragging = False
        self._repeat = AutoRepeat()

    @property
    def value(self) -> int:
        """Position, from 0 to ``maximum``."""
        return self._value

    @value.setter
    def value(self, value: int) -> None:
        self._value = max(0, min(value, self.maximum))

    def min_size(self) -> tuple[int, int]:
        return (1, 2) if self.vertical else (2, 1)

    @property
    def length(self) -> int:
        """How many cells long the bar is, including the arrows."""
        return self.rect.height if self.vertical else self.rect.width

    def set_range(self, maximum: int, page: int | None = None) -> None:
        """Change the range.

        :param maximum: Largest position.
        :param page: Amount shown at once, if changing.
        """
        self.maximum = max(0, maximum)
        if page is not None:
            self.page = max(1, page)
        self.value = self._value

    def scroll_to(self, value: int) -> None:
        """Move the bar, as the user does.

        :param value: New position.
        """
        before = self._value
        self.value = value
        if self._value != before and self.on_change is not None:
            self.on_change(self)

    def layout(self, row: int, column: int) -> ScrollBarLayout:
        """The bar's layout.

        :param row: First cell's row.
        :param column: First cell's column.
        """
        return ScrollBarLayout(
            self.vertical,
            row,
            column,
            self.length,
            self._value,
            self.maximum,
            self.page,
        )

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        del focused
        row, column = origin.row + self.rect.row, origin.column + self.rect.column
        self.layout(row, column).paint(canvas, self.style)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Step, drag or scroll with the mouse.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        layout = self.layout(self.rect.row, self.rect.column)
        if event.action == "scroll":
            back = event.button in ("up", "left")
            self.scroll_to(self._value + (-self.line if back else self.line))
            return True
        if event.button != "left":
            return False
        if event.action == "press":
            part = layout.part_at(row, column)
            self._dragging = part == "thumb"
            self.scroll_to(self._value + layout.step(part, self.line))
            self._repeat.start(part, row, column, time.monotonic())
            return True
        if event.action == "drag":
            self._repeat.move(row, column)
            if self._dragging:
                self.scroll_to(layout.value_at(row, column))
            return True
        if event.action == "release":
            self._dragging = False
            self._repeat.stop()
            return True
        return False

    def wake_time(self) -> float | None:
        return self._repeat.wake_time()

    def on_timer(self, now: float) -> None:
        """Repeat a held click.

        :param now: The current ``time.monotonic``.
        """
        repeat = self._repeat
        layout = self.layout(self.rect.row, self.rect.column)
        if repeat.due(now, layout.part_at(repeat.row, repeat.column)):
            self.scroll_to(self._value + layout.step(repeat.part, self.line))
