"""Sliders: a knob that slides along a track to choose a number within a
range, such as a volume, a brightness, or a position in a piece of music."""

from collections.abc import Callable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.scrollbar import track_position, track_value
from dasha.shortcuts import Shortcuts
from dasha.style import BLUE, BRIGHT_GREEN, BRIGHT_WHITE, CYAN, WHITE, Style
from dasha.widgets.base import Widget

ACROSS = "\N{BOX DRAWINGS LIGHT HORIZONTAL}"
UP_AND_DOWN = "\N{BOX DRAWINGS LIGHT VERTICAL}"
KNOB = "\N{MEDIUM SHADE}"
"""The tracks ``─`` and ``│`` (code page 437 glyphs 196 and 179), and the
knob ``▒`` (177)."""


class Slider(Widget):  # pylint: disable=too-many-instance-attributes
    """A ``Slider`` is a knob that slides along a track to choose a whole
    number from ``minimum`` to ``maximum`` (0 and 100 by default), in steps of
    ``step``, such as a volume or a position in a piece of music. By default it
    is horizontal, with its minimum at the left; ``vertical=True`` makes it
    vertical, with its minimum at the bottom and its maximum at the top, as on
    a mixing desk.

    ::

        ──────▒─────────

    - Left or Down (``slider_decrease``): one ``step`` towards the minimum
    - Right or Up (``slider_increase``): one ``step`` towards the maximum
    - Page Down / Page Up (``slider_page_decrease`` / ``slider_page_increase``):
      one ``page`` (a tenth of the range, unless given) either way
    - Home / End (``slider_minimum`` / ``slider_maximum``): to either end
    - A click or drag on it: the knob moves to the pointer
    - The mouse wheel: one ``step`` either way

    ``value`` is the number, which is kept within range and on a step when code
    sets it. ``slide_to(value)`` moves the knob as the user does, and
    ``on_change(slider)`` is called for every change the user makes. The track is
    ``─`` or ``│``, and the knob ``▒``
    (code page 437 glyphs 196, 179 and 177). Its colours are ``slider`` and
    ``slider.focused`` for the track, and ``slider.knob`` and
    ``slider.knob.focused`` for the knob. A slider shares its track arithmetic with
    scroll bars: ``dasha.scrollbar.track_position`` and ``track_value`` turn a
    value into a cell along a track and back.
    """

    focusable = True
    style: Style = Style(foreground=BLUE, background=CYAN)
    """The style of the track."""
    focused_style: Style = Style(foreground=BRIGHT_WHITE, background=CYAN, bold=True)
    """The style of the track while the slider has the focus."""
    knob_style: Style = Style(foreground=WHITE, background=CYAN)
    focused_knob_style: Style = Style(foreground=BRIGHT_GREEN, background=CYAN)

    def __init__(  # pylint: disable=too-many-arguments
        self,
        row: int,
        column: int,
        length: int,
        *,
        vertical: bool = False,
        value: int = 0,
        minimum: int = 0,
        maximum: int = 100,
        step: int = 1,
        page: int | None = None,
        on_change: Callable[["Slider"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        if length < 2:
            raise ValueError("a slider needs at least two cells")
        if maximum < minimum:
            raise ValueError("maximum must not be less than minimum")
        if step < 1:
            raise ValueError("step must be at least 1")
        width, height = (1, length) if vertical else (length, 1)
        super().__init__(row, column, width, height, name=name, status=status)
        self.vertical = vertical
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.page = max(step, page if page is not None else (maximum - minimum) // 10)
        self.on_change = on_change
        self._value = minimum
        self.value = value
        self._dragging = False

    @property
    def value(self) -> int:
        """The chosen number. Setting it from code keeps it within range and on
        a step, and does not call ``on_change``."""
        return self._value

    @value.setter
    def value(self, value: int) -> None:
        self._value = self._fit(value)

    def _fit(self, value: int) -> int:
        """``value`` kept within range, on the nearest step."""
        value = max(self.minimum, min(value, self.maximum))
        steps = round((value - self.minimum) / self.step)
        return min(self.minimum + steps * self.step, self.maximum)

    def slide_to(self, value: int) -> None:
        """Move the knob as the user does, keeping the value within range and
        on a step, and calling ``on_change`` if it moved."""
        before = self._value
        self.value = value
        if self._value != before and self.on_change is not None:
            self.on_change(self)

    @property
    def length(self) -> int:
        """How many cells long the track is."""
        return self.rect.height if self.vertical else self.rect.width

    def min_size(self) -> tuple[int, int]:
        return (1, 2) if self.vertical else (2, 1)

    @property
    def knob(self) -> int:
        """Which cell the knob is in, counted from the minimum end."""
        return track_position(
            self._value - self.minimum, self.maximum - self.minimum, self.length
        )

    def value_at(self, row: int, column: int) -> int:
        """The value the knob would have at a position in the window, for a
        click or drag there; a position beyond either end gives that end's
        value."""
        if self.vertical:
            along = self.rect.bottom - 1 - row
        else:
            along = column - self.rect.column
        span = self.maximum - self.minimum
        return self.minimum + track_value(along, span, self.length)

    # Drawing and input

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        row, column = origin.row + self.rect.row, origin.column + self.rect.column
        track = self.focused_style if focused else self.style
        knob = self.focused_knob_style if focused else self.knob_style
        for along in range(self.length):
            on_knob = along == self.knob
            char = KNOB if on_knob else UP_AND_DOWN if self.vertical else ACROSS
            style = knob if on_knob else track
            if self.vertical:
                canvas.write(
                    row + self.length - 1 - along, column, char, style, clip=origin
                )
            else:
                canvas.write(row, column + along, char, style, clip=origin)

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Slide the knob by a step or a page, or to either end."""
        moves = {
            "slider_decrease": self._value - self.step,
            "slider_increase": self._value + self.step,
            "slider_page_decrease": self._value - self.page,
            "slider_page_increase": self._value + self.page,
            "slider_minimum": self.minimum,
            "slider_maximum": self.maximum,
        }
        for action, value in moves.items():
            if shortcuts.matches(action, key):
                self.slide_to(value)
                return True
        return False

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """A press moves the knob to the pointer, and a drag takes it along;
        the mouse wheel moves it by a step."""
        if event.action == "scroll":
            down = event.button in ("down", "left")
            self.slide_to(self._value + (-self.step if down else self.step))
            return True
        if event.button != "left":
            return False
        if event.action == "press":
            self._dragging = True
            self.slide_to(self.value_at(row, column))
            return True
        if event.action == "drag":
            if self._dragging:
                self.slide_to(self.value_at(row, column))
            return True
        if event.action == "release":
            self._dragging = False
            return True
        return False
