"""Frame characters for windows, menus and other boxes."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Border:
    """The six characters that draw a window frame."""

    top_left: str
    top_right: str
    bottom_left: str
    bottom_right: str
    horizontal: str
    vertical: str


SINGLE = Border(
    "\N{BOX DRAWINGS LIGHT DOWN AND RIGHT}",
    "\N{BOX DRAWINGS LIGHT DOWN AND LEFT}",
    "\N{BOX DRAWINGS LIGHT UP AND RIGHT}",
    "\N{BOX DRAWINGS LIGHT UP AND LEFT}",
    "\N{BOX DRAWINGS LIGHT HORIZONTAL}",
    "\N{BOX DRAWINGS LIGHT VERTICAL}",
)

DOUBLE = Border(
    "\N{BOX DRAWINGS DOUBLE DOWN AND RIGHT}",
    "\N{BOX DRAWINGS DOUBLE DOWN AND LEFT}",
    "\N{BOX DRAWINGS DOUBLE UP AND RIGHT}",
    "\N{BOX DRAWINGS DOUBLE UP AND LEFT}",
    "\N{BOX DRAWINGS DOUBLE HORIZONTAL}",
    "\N{BOX DRAWINGS DOUBLE VERTICAL}",
)
