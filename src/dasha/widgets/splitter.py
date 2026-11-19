"""Splitters: two panes of widgets, side by side or one above the other,
with a divider between them that can be dragged."""

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
"""The divider: ``│`` between panes side by side, and ``─`` between
stacked panes (code page 437 glyphs 179 and 196)."""


class SplitPane(Container):
    """One of a ``Splitter``'s two panes. ``add`` puts a widget in the pane,
    positioned relative to it, and the pane moves and stretches its widgets as
    their window would (each according to its own ``grow``) as the divider
    moves."""

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
    """A ``Splitter`` holds two panes of widgets side by side, with a divider
    ``│`` between them that can be dragged. With ``vertical=True``, one pane is
    above the other, and the divider is ``─``:

    ::

        Documents     │ changes.txt
        Programs      │ draft.doc
        Settings      │ help.txt

    ::

        splitter = window.add(
            widget=Splitter(
                row=0, column=0, width=58, height=12, position=16, minimum=8
            ),
            grow=Grow.ALL,
        )
        folders = splitter.first.add(
            widget=ListBox(items=names, row=0, column=0, width=16, height=12)
        )
        folders.grow = Grow.ALL
        files = splitter.second.add(
            widget=ListBox(items=items, row=0, column=0, width=41, height=12)
        )
        files.grow = Grow.ALL

    - **The panes.** ``first`` and ``second`` are containers (``SplitPane``),
      and ``pane.add(widget)`` places a widget relative to the pane.
    - **Moving and stretching.** A pane moves and stretches its widgets as their
      window would, each according to its own ``grow``, whenever the divider
      moves or the splitter is resized; changes to the window's own size leave
      them alone (``Container.sizes_children``). So a list with ``Grow.ALL``
      fills its pane wherever the divider is.
    - **The divider.** ``position`` is how far the divider is from the left (or
      top), and neither pane is made smaller than ``minimum``. Dragging the
      divider moves it, and so do Left and Right, or Up and Down
      (``splitter_decrease``, ``splitter_increase``), while the splitter has the
      focus, which it can take. ``move_divider(position)`` moves it as the user
      does, and ``on_change(splitter)`` is called for every move the user makes.
    - **Resizing.** When the splitter itself is resized (through its ``grow``,
      along with the window), the second pane takes up the room it gains or
      loses.
    - **Colours.** The divider uses ``splitter``, and ``splitter.focused`` while
      the splitter has the focus; colours left as ``default`` are the
      window's.
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
        """How many cells the panes and divider take up across (or down, if
        they are stacked)."""
        return self.rect.height if self.vertical else self.rect.width

    def _fit(self, position: int) -> int:
        """``position`` kept clear of ``minimum`` from either end."""
        return max(self.minimum, min(position, self.length - 1 - self.minimum))

    @property
    def position(self) -> int:
        """How far the divider is from the left (or top). Setting it from
        code moves the panes' widgets, without calling ``on_change``."""
        return self._position

    @position.setter
    def position(self, position: int) -> None:
        self._position = self._fit(position)
        self._arrange()

    @property
    def value(self) -> int:
        return self._position

    def move_divider(self, position: int) -> None:
        """Move the divider as the user does, calling ``on_change``."""
        before = self._position
        self.position = position
        if self._position != before and self.on_change is not None:
            self.on_change(self)

    def pane_rect(self, second: bool) -> Rect:
        """Where a pane is in the window's content."""
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
        """Both panes, relative to the splitter: what moving the splitter
        itself (its widgets move with it) leaves alone."""
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
        """When the splitter grows with the window, the second pane takes up
        the difference."""
        self._position = self._fit(self._position)
        self._arrange()

    def min_size(self) -> tuple[int, int]:
        """Room for both panes' ``minimum`` and the divider along its length,
        and one row (or column) across, so that it shrinks with its window in
        both directions, and what its panes hold (such as a list or a table)
        scrolls by itself, rather than the window scrolling both panes at
        once."""
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
        """The arrow keys move the divider by one cell."""
        actions: dict[str, Callable[[], object]] = {
            "splitter_decrease": lambda: self.move_divider(self._position - 1),
            "splitter_increase": lambda: self.move_divider(self._position + 1),
        }
        return run_shortcut(shortcuts, key, actions)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """A press on the divider followed by a drag moves the divider; clicks
        on the panes are not used up."""
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
