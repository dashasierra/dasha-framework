"""Animations: the intermediate frames drawn as a menu drops down from the
menu bar, or as a window moves from one position to another (see
``PresentationManager.animations``).

A window is animated as a frame that moves, growing or shrinking, from its
old position to its new one. Throughout, it holds what was inside the window
when the animation began, exactly as it was: not laid out again or
scrolled, but cut off where the frame is smaller, and blank beyond it where
the frame is bigger.
"""

from dataclasses import dataclass

from dasha.canvas import Canvas, Rect
from dasha.window import Window


def frame_parts(frames: int) -> list[float]:
    """How far along each of ``frames`` intermediate frames is, from 0 (the
    start) to 1 (the end), evenly spaced: ``[1/3, 2/3]`` for two frames. The
    end itself is shown by the next ordinary frame."""
    return [step / (frames + 1) for step in range(1, frames + 1)]


def between(start: Rect, end: Rect, part: float) -> Rect:
    """The rectangle that is the fraction ``part`` (from 0 to 1) of the way
    from ``start`` to ``end``, with each edge moving in a straight line. It
    is never smaller than a frame's corners (two by two)."""

    def along(first: int, last: int) -> int:
        return round(first + (last - first) * part)

    top, left = along(start.row, end.row), along(start.column, end.column)
    bottom, right = along(start.bottom, end.bottom), along(start.right, end.right)
    return Rect(top, left, max(2, bottom - top), max(2, right - left))


def scroll_bars_shown(window: Window) -> tuple[bool, bool]:
    """Whether a window shows its (vertical, horizontal) scroll bars at its
    current position and size."""
    vertical, horizontal = window.scroll_bars
    return vertical is not None, horizontal is not None


@dataclass
class WindowAnimation:
    """A window moving from ``start`` to ``end``, as it is maximised,
    minimised or restored."""

    window: Window
    start: Rect
    end: Rect
    inside: Canvas
    """What was inside the window when the animation began
    (``Window.render_interior``), shown throughout."""
    bars: tuple[bool, bool]
    """The scroll bars (vertical, horizontal) the window may show during the
    animation: those it has at its full size, which is at the end (or at the
    start, when minimising)."""
    showing: bool = True
    """Whether the window is on the screen (rather than minimised) at the
    end. An animation is not drawn if its window is not, or is no longer,
    in the expected state."""

    @classmethod
    def of(cls, window: Window) -> "WindowAnimation":
        """An animation of a window from its current position, with its
        current contents, ending at the same position until ``end`` is
        set."""
        rect = window.rect
        return cls(
            window, rect, rect, window.render_interior(True), scroll_bars_shown(window)
        )

    def to_window(self, start: Rect | None = None) -> "WindowAnimation":
        """End the animation where the window is now (and start it from
        ``start``, if given), showing the scroll bars the window has
        there."""
        if start is not None:
            self.start = start
        self.end = self.window.rect
        self.bars = scroll_bars_shown(self.window)
        self.showing = True
        return self

    def paint(self, canvas: Canvas, part: float) -> None:
        """Draw the window the fraction ``part`` (from 0 to 1) of the way
        along."""
        rect = between(self.start, self.end, part)
        self.window.paint_between(canvas, rect, self.inside, self.bars)
