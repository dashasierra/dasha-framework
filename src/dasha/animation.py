"""Menu and window animations."""

from dataclasses import dataclass

from dasha.canvas import Canvas, Rect
from dasha.window import Window


def frame_parts(frames: int) -> list[float]:
    """Evenly spaced fractions for intermediate frames.

    :param frames: Number of frames.
    """
    return [step / (frames + 1) for step in range(1, frames + 1)]


def between(start: Rect, end: Rect, part: float) -> Rect:
    """A rect part of the way between two others.

    :param start: Starting rect.
    :param end: Ending rect.
    :param part: Fraction from 0 to 1.
    """

    def along(first: int, last: int) -> int:
        return round(first + (last - first) * part)

    top, left = along(start.row, end.row), along(start.column, end.column)
    bottom, right = along(start.bottom, end.bottom), along(start.right, end.right)
    return Rect(top, left, max(2, bottom - top), max(2, right - left))


def scroll_bars_shown(window: Window) -> tuple[bool, bool]:
    """Whether a window shows its (vertical, horizontal) scroll bars.

    :param window: The window.
    """
    vertical, horizontal = window.scroll_bars
    return vertical is not None, horizontal is not None


@dataclass
class WindowAnimation:
    """A window moving between two positions."""

    window: Window
    start: Rect
    end: Rect
    inside: Canvas
    """The window's contents when it began."""
    bars: tuple[bool, bool]
    """Scroll bars shown during the animation."""
    showing: bool = True
    """Whether the window ends on screen."""

    @classmethod
    def of(cls, window: Window) -> "WindowAnimation":
        """An animation from a window's current position.

        :param window: The window.
        """
        rect = window.rect
        return cls(
            window, rect, rect, window.render_interior(True), scroll_bars_shown(window)
        )

    def to_window(self, start: Rect | None = None) -> "WindowAnimation":
        """End the animation where the window is now.

        :param start: Where to start, if changing.
        """
        if start is not None:
            self.start = start
        self.end = self.window.rect
        self.bars = scroll_bars_shown(self.window)
        self.showing = True
        return self

    def paint(self, canvas: Canvas, part: float) -> None:
        """Draw the window part of the way along.

        :param canvas: Canvas to draw on.
        :param part: Fraction from 0 to 1.
        """
        rect = between(self.start, self.end, part)
        self.window.paint_between(canvas, rect, self.inside, self.bars)
