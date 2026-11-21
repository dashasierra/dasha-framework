"""Containers that hold widgets in a window."""

from collections import defaultdict
from collections.abc import Sequence
from typing import TypeVar

from dasha.canvas import Rect
from dasha.widgets.base import Widget

W = TypeVar("W", bound=Widget)


class Container:
    """Holds widgets positioned relative to its content."""

    noun = "container"
    """What the container is called in error messages."""

    opens_below = False
    """Whether showing its widgets pushes those below down."""

    sizes_children = False
    """Whether it sizes its own widgets."""

    help: str | None = None
    """Help topic for its widgets."""

    def __init__(self) -> None:
        self.children: list[Widget] = []
        """The widgets in it, in the order they were added."""

    @property
    def anchor(self) -> Widget:
        """The widget the container belongs to."""
        raise NotImplementedError

    @property
    def is_showing_children(self) -> bool:
        """Whether its widgets are shown."""
        return True

    def content_origin(self) -> tuple[int, int]:
        """Where its content starts in the window."""
        raise NotImplementedError

    def add(self, widget: W) -> W:
        """Add a widget to the container and return it.

        :param widget: The widget to add.
        """
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
    """A widget's containers, nearest first.

    :param widget: The widget.
    """
    found: list[Container] = []
    container = widget.parent
    while container is not None:
        found.append(container)
        container = container.anchor.parent
    return found


def owners(widget: Widget) -> list[Widget]:
    """A widget and the widgets owning its containers.

    :param widget: The widget.
    """
    return [widget] + [container.anchor for container in ancestors(widget)]


def sized_by_container(widget: Widget) -> bool:
    """Whether a container sizes the widget.

    :param widget: The widget.
    """
    return any(container.sizes_children for container in ancestors(widget))


def lay_out(widgets: Sequence[Widget]) -> None:
    """Position widgets for their containers.

    :param widgets: The window's widgets.
    """
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
        """Whether a widget is an open area.

        :param widget: The widget.
        """
        return (
            isinstance(widget, Container)
            and widget.opens_below
            and widget.is_showing_children
        )

    def within(container: Container | None) -> dict[Widget, int]:
        """How far each widget is moved down.

        :param container: The container, or ``None`` for the window.
        """
        inside = members[container]
        open_areas = [w for w in inside if opens(w)]
        return {
            widget: sum(height(a) for a in open_areas if homes[a] < homes[widget])
            for widget in inside
        }

    def height(area: Widget) -> int:
        """Rows an open area takes.

        :param area: The area.
        """
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
