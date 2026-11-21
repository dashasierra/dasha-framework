"""Splitters."""

from collections.abc import Callable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.style import Style
from dasha.widgets.base import Widget, run_shortcut
from dasha.widgets.container import Container, ancestors
from dasha.widgets.label import on_window

ACROSS = "\N{BOX DRAWINGS LIGHT VERTICAL}"
STACKED = "\N{BOX DRAWINGS LIGHT HORIZONTAL}"
"""Divider characters."""


class SplitPane(Container):
    """One of a splitter's two panes.

    :param splitter: The splitter.
    :param second: Whether this is the second pane.
    """

    noun = "splitter"
    sizes_children = True

    def __init__(self, splitter: "Splitter", second: bool) -> None:
        super().__init__()
        self.splitter = splitter
        self.second = second

    @property
    def anchor(self) -> Widget:
        return self.splitter

    @property
    def rect(self) -> Rect:
        """Where the pane is in the window's content."""
        return self.splitter.pane_rect(self.second)

    def content_origin(self) -> tuple[int, int]:
        rect = self.rect
        return rect.row - self.splitter.area_shift, rect.column


class Splitter(Widget):  # pylint: disable=too-many-instance-attributes
    """Two panes with a draggable divider.

    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param height: Height in rows.
    :param vertical: Whether the panes are stacked.
    :param position: Divider position, if not centred.
    :param minimum: Smallest pane size.
    :param on_change: Called with the splitter when the user moves it.
    :param name: Widget name.
    :param status: Status bar text.
    """

    focusable = True
    style: Style = Style()
    """The style of the divider."""
    focused_style: Style = Style(bold=True, reverse=True)
    """The style of the divider while the splitter has the focus."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        row: int,
        column: int,
        width: int,
        height: int,
        *,
        vertical: bool = False,
        position: int | None = None,
        minimum: int = 1,
        on_change: Callable[["Splitter"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        super().__init__(row, column, width, height, name=name, status=status)
        self.vertical = vertical
        self.minimum = max(1, minimum)
        length = height if vertical else width
        if length < 2 * self.minimum + 1:
            raise ValueError("a splitter needs room for two panes and a divider")
        self.on_change = on_change
        self._position = self._fit(length // 2 if position is None else position)
        self.first = SplitPane(self, second=False)
        """The pane on the left (or at the top)."""
        self.second = SplitPane(self, second=True)
        """The pane on the right (or at the bottom)."""
        self._dragging = False
        self._placed = self._panes()  # where the panes' widgets were put

    # The divider

    @property
    def length(self) -> int:
        """Cells the panes and divider span."""
        return self.rect.height if self.vertical else self.rect.width

    def _fit(self, position: int) -> int:
        """A position kept clear of the ends.

        :param position: The position.
        """
        return max(self.minimum, min(position, self.length - 1 - self.minimum))

    @property
    def position(self) -> int:
        """Divider position."""
        return self._position

    @position.setter
    def position(self, position: int) -> None:
        self._position = self._fit(position)
        self._arrange()

    @property
    def value(self) -> int:
        return self._position

    def move_divider(self, position: int) -> None:
        """Move the divider, as the user does.

        :param position: New position.
        """
        before = self._position
        self.position = position
        if self._position != before and self.on_change is not None:
            self.on_change(self)

    def pane_rect(self, second: bool) -> Rect:
        """A pane's rect in the window's content.

        :param second: Whether to give the second pane.
        """
        rect, at = self.rect, self._position
        if self.vertical:
            if second:
                return Rect(
                    rect.row + at + 1, rect.column, rect.height - at - 1, rect.width
                )
            return Rect(rect.row, rect.column, at, rect.width)
        if second:
            return Rect(
                rect.row, rect.column + at + 1, rect.height, rect.width - at - 1
            )
        return Rect(rect.row, rect.column, rect.height, at)

    @property
    def divider_rect(self) -> Rect:
        """Where the divider is in the window's content."""
        rect, at = self.rect, self._position
        if self.vertical:
            return Rect(rect.row + at, rect.column, 1, rect.width)
        return Rect(rect.row, rect.column + at, rect.height, 1)

    # Keeping the panes' widgets in place

    def _panes(self) -> tuple[Rect, Rect]:
        """Both panes, relative to the splitter."""
        rect = self.rect

        def relative(pane: Rect) -> Rect:
            return Rect(
                pane.row - rect.row, pane.column - rect.column, pane.height, pane.width
            )

        return relative(self.pane_rect(False)), relative(self.pane_rect(True))

    def _arrange(self) -> None:
        """Move and stretch each pane's widgets for where it is now."""
        window = self.window
        placed, now = self._placed, self._panes()
        self._placed = now
        if window is None:
            return
        for before, after, pane in zip(placed, now, (self.first, self.second)):
            if before == after:
                continue
            down, across = after.row - before.row, after.column - before.column
            for widget in window.widgets:
                if pane not in ancestors(widget):
                    continue
                rect = widget.rect
                widget.rect = Rect(
                    rect.row + down, rect.column + across, rect.height, rect.width
                )
                inner = [c for c in ancestors(widget) if c.sizes_children]
                if inner and inner[0] is pane:  # the nearest pane sizes it
                    widget.follow_resize(
                        (before.width, before.height), (after.width, after.height)
                    )

    def on_add(self) -> None:
        self._placed = self._panes()

    def on_resize(self) -> None:
        """Give the second pane the size change."""
        self._position = self._fit(self._position)
        self._arrange()

    def min_size(self) -> tuple[int, int]:
        """Room for both panes and the divider."""
        least = 2 * self.minimum + 1
        return (1, least) if self.vertical else (least, 1)

    # Drawing and input

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        body = self.window.body_style if self.window is not None else Style()
        style = on_window(self.focused_style if focused else self.style, body)
        divider = self.divider_rect
        row, column = origin.row + divider.row, origin.column + divider.column
        if self.vertical:
            canvas.write(row, column, STACKED * divider.width, style, clip=origin)
        else:
            for offset in range(divider.height):
                canvas.write(row + offset, column, ACROSS, style, clip=origin)

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Move the divider with the arrow keys.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        actions: dict[str, Callable[[], object]] = {
            "splitter_decrease": lambda: self.move_divider(self._position - 1),
            "splitter_increase": lambda: self.move_divider(self._position + 1),
        }
        return run_shortcut(shortcuts, key, actions)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Drag the divider.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        if event.button != "left":
            return False
        along = row - self.rect.row if self.vertical else column - self.rect.column
        if event.action == "press":
            self._dragging = self.divider_rect.contains(row, column)
            return self._dragging
        if not self._dragging:
            return False
        if event.action == "drag":
            self.move_divider(along)
        elif event.action == "release":
            self._dragging = False
        return event.action in ("drag", "release")
