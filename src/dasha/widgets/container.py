"""Containers, which hold widgets inside a window: collapsible areas, group
boxes, tab pages and the panes of a splitter.

A container's widgets are still ordinary widgets of the window. They are in
``window.widgets``, so Tab, mnemonics, ``window.widget(name)`` and
``dialog.values`` all find them. Each widget knows its container as
``widget.parent``, and is shown only while every container it is in is
showing its children (``Widget.is_shown``). Containers of any kind can be
nested.
"""

from collections import defaultdict
from collections.abc import Sequence
from typing import TypeVar

from dasha.canvas import Rect
from dasha.widgets.base import Widget

W = TypeVar("W", bound=Widget)


class Container:
    """Holds widgets, positioned relative to its content, which move with
    the widget it belongs to (its ``anchor``).

    Subclasses provide ``anchor`` and ``content_origin``, and say when their
    widgets are shown (``is_showing_children``). A collapsible area also takes up
    room below itself while it is showing them (``opens_below``); every
    other kind of container keeps its widgets within its own rectangle.
    """

    noun = "container"
    """What the container is called in error messages."""

    opens_below = False
    """Whether showing its widgets moves the widgets below it down by
    their height (as a collapsible area does), rather than the widgets being
    inside its rectangle."""

    sizes_children = False
    """Whether the container moves and stretches its widgets itself, as
    their window would (as a splitter's pane does), so that the window's own
    size changes leave them alone."""

    help: str | None = None
    """The help topic for the widgets in it that have none of their own (see
    ``dasha.help``). Set it on a container, such as a tab page."""

    def __init__(self) -> None:
        self.children: list[Widget] = []
        """The widgets in it, in the order they were added."""

    @property
    def anchor(self) -> Widget:
        """The widget the container belongs to: the container itself, for a
        container that is a widget, or the widget that owns it, for a tab
        page or a pane."""
        raise NotImplementedError

    @property
    def is_showing_children(self) -> bool:
        """Whether the container's widgets are shown (if the container itself
        is)."""
        return True

    def content_origin(self) -> tuple[int, int]:
        """Where row 0, column 0 of the container's widgets is in the
        window's content, as laid out (before any collapsible area moved
        it)."""
        raise NotImplementedError

    def add(self, widget: W) -> W:
        """Put a widget in the container, at the widget's ``row`` and
        ``column`` relative to the container's content, and return it. The
        container must already be in a window."""
        window = self.anchor.window
        if window is None:
            raise ValueError(f"add the {self.noun} to a window first")
        row, column = self.content_origin()
        rect = widget.rect
        widget.rect = Rect(
            row + rect.row, column + rect.column, rect.height, rect.width
        )
        widget.parent = self
        widget.area_shift = 0
        self.children.append(widget)
        window.add(widget)
        return widget

    @property
    def home_row(self) -> int:
        """Where the anchor's top row is, as originally laid out."""
        anchor = self.anchor
        return anchor.rect.row - anchor.area_shift


def ancestors(widget: Widget) -> list[Container]:
    """The containers that a widget is in, nearest first."""
    found: list[Container] = []
    container = widget.parent
    while container is not None:
        found.append(container)
        container = container.anchor.parent
    return found


def owners(widget: Widget) -> list[Widget]:
    """``widget`` itself, then the widgets whose containers it is in,
    nearest first (such as the tabs on one of whose pages it sits)."""
    return [widget] + [container.anchor for container in ancestors(widget)]


def sized_by_container(widget: Widget) -> bool:
    """Whether a container the widget is in moves and stretches it (as a
    splitter's pane does), rather than its window doing so."""
    return any(container.sizes_children for container in ancestors(widget))


def lay_out(widgets: Sequence[Widget]) -> None:
    """Move each of a window's ``widgets`` to where its containers put it:
    along with the widget its container belongs to, and down by the height
    of every expanded collapsible area whose header is above it and that it
    is not inside, as though every area had been collapsed when the window
    was laid out. Only the rows that the areas add are changed
    (``Widget.area_shift``), so widgets moved by code, or grown with the
    window, keep their positions."""
    homes = {widget: widget.rect.row - widget.area_shift for widget in widgets}
    members: dict[Container | None, list[Widget]] = defaultdict(list)
    for widget in widgets:
        members[widget.parent].append(widget)
    anchored: dict[Widget, list[Container]] = defaultdict(list)
    for container in members:
        if container is not None:
            anchored[container.anchor].append(container)
    heights: dict[Container, int] = {}

    def opens(widget: Widget) -> bool:
        """Whether a widget is an area taking room below itself now."""
        return (
            isinstance(widget, Container)
            and widget.opens_below
            and widget.is_showing_children
        )

    def within(container: Container | None) -> dict[Widget, int]:
        """How far each widget directly in ``container`` (or the window) is
        moved down by the open areas above it there."""
        inside = members[container]
        open_areas = [w for w in inside if opens(w)]
        return {
            widget: sum(height(a) for a in open_areas if homes[a] < homes[widget])
            for widget in inside
        }

    def height(area: Widget) -> int:
        """How many rows an open area takes below its header."""
        assert isinstance(area, Container)
        if area not in heights:
            moved = within(area)
            bottom = max(
                (homes[w] + w.rect.height + moved[w] for w in members[area]),
                default=homes[area] + 1,
            )
            heights[area] = max(0, bottom - homes[area] - 1)
        return heights[area]

    def place(container: Container | None, base: int) -> None:
        for widget, moved in within(container).items():
            shift = base + moved
            if shift != widget.area_shift:
                rect = widget.rect
                widget.rect = Rect(
                    rect.row + shift - widget.area_shift,
                    rect.column,
                    rect.height,
                    rect.width,
                )
                widget.area_shift = shift
            for inner in anchored.get(widget, []):
                place(inner, shift)

    place(None, 0)
