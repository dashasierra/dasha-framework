"""Scroll bars: the drawing and hit-testing shared by window frames and
the ``ScrollBar`` widget (``dasha.widgets.scrollbar``).

A vertical bar runs down the right edge of the frame, with ``▲`` at the top
and ``▼`` at the bottom; a horizontal bar runs along the bottom edge,
between ``◄`` and ``►``. Between the arrows is a ``▒`` track, with a ``■``
thumb showing where the view is. All of these are code page 437
characters.
"""

from dataclasses import dataclass, field

from dasha.canvas import Canvas, Rect
from dasha.style import Style

UP = "\N{BLACK UP-POINTING TRIANGLE}"
DOWN = "\N{BLACK DOWN-POINTING TRIANGLE}"
LEFT = "\N{BLACK LEFT-POINTING POINTER}"
RIGHT = "\N{BLACK RIGHT-POINTING POINTER}"
TRACK = "\N{MEDIUM SHADE}"
THUMB = "\N{BLACK SQUARE}"
"""▲ ▼ ◄ ► (code page 437 glyphs 30, 31, 17, 16), ▒ (177) and ■ (254)."""


def track_position(value: int, maximum: int, cells: int) -> int:
    """Which of a track's ``cells`` stands for ``value`` (from 0 to
    ``maximum``): cell 0 for 0, the last cell for ``maximum``, and evenly
    spaced in between. A scroll bar's thumb and a slider's knob are placed in
    this way."""
    if maximum <= 0 or cells <= 1:
        return 0
    return round(min(max(value, 0), maximum) / maximum * (cells - 1))


def track_value(along: int, maximum: int, cells: int) -> int:
    """The value (from 0 to ``maximum``) that cell ``along`` of a track of
    ``cells`` cells stands for: the reverse of ``track_position``, used when
    a thumb or knob is dragged there. Cells beyond either end give 0 or
    ``maximum``."""
    if cells <= 1:
        return 0
    return round(min(max(along, 0), cells - 1) / (cells - 1) * maximum)


@dataclass(frozen=True)
class ScrollBarLayout:
    """A single scroll bar in its current state: where it is on the screen,
    and what it shows. It draws the bar, and reports which part is where and
    what a click on each part does.

    ``length`` counts every cell, including the arrows. ``value`` is the
    scroll offset, from 0 to ``maximum``, and ``page`` is how much is visible
    at once.
    """

    vertical: bool
    row: int
    column: int
    length: int
    value: int
    maximum: int
    page: int

    @property
    def rect(self) -> Rect:
        """The cells the bar covers."""
        if self.vertical:
            return Rect(self.row, self.column, self.length, 1)
        return Rect(self.row, self.column, 1, self.length)

    @property
    def track_length(self) -> int:
        """How many cells there are between the two arrows."""
        return max(0, self.length - 2)

    @property
    def thumb(self) -> int:
        """Where the thumb is along the track (0 is next to the first
        arrow)."""
        return track_position(self.value, self.maximum, self.track_length)

    def _index(self, row: int, column: int) -> int | None:
        """How far along the bar a position is, if it is on the bar."""
        if not self.rect.contains(row, column):
            return None
        return row - self.row if self.vertical else column - self.column

    def part_at(self, row: int, column: int) -> str | None:
        """Which part of the bar is at a position.

        ``"back"`` and ``"forward"`` are the arrows (up or left, and down or
        right), ``"page_back"`` and ``"page_forward"`` are the track before
        and after the thumb, and ``"thumb"`` is the thumb. Returns ``None``
        for a position that is not on the bar.
        """
        index = self._index(row, column)
        if index is None:
            return None
        if index == 0:
            return "back"
        if index == self.length - 1:
            return "forward"
        along = index - 1
        if along < self.thumb:
            return "page_back"
        if along > self.thumb:
            return "page_forward"
        return "thumb"

    def step(self, part: str | None, line: int = 1) -> int:
        """How far a click on a part scrolls: ``line`` for an arrow, a page
        (less one line, so that a line stays in view) for the track, and 0
        for the thumb or for no part. Negative values scroll back (up or
        left)."""
        page = max(1, self.page - 1)
        return {
            "back": -line,
            "forward": line,
            "page_back": -page,
            "page_forward": page,
        }.get(part or "", 0)

    def value_at(self, row: int, column: int) -> int:
        """The scroll offset that would put the thumb at a position, used for
        dragging it. Positions beyond the ends give 0 or ``maximum``."""
        along = (row - self.row if self.vertical else column - self.column) - 1
        return track_value(along, self.maximum, self.track_length)

    def paint(self, canvas: Canvas, style: Style) -> None:
        """Draw the arrows, the track and the thumb."""
        back, forward = (UP, DOWN) if self.vertical else (LEFT, RIGHT)
        cells = [back] + [TRACK] * self.track_length + [forward]
        if self.track_length:
            cells[1 + self.thumb] = THUMB
        for index, char in enumerate(cells):
            if self.vertical:
                canvas.write(self.row + index, self.column, char, style)
            else:
                canvas.write(self.row, self.column + index, char, style)


@dataclass
class AutoRepeat:
    """Repeats a click on a scroll bar's arrow or track while the mouse
    button is held down: first after ``delay`` seconds, then every
    ``interval`` seconds, but only while the pointer is still on the part
    first pressed. On the track, the repeating stops once the thumb reaches
    the pointer.

    The two timings are class attributes, shared by every scroll bar (both
    window frames and ``ScrollBar`` widgets), so setting
    ``AutoRepeat.delay`` or ``AutoRepeat.interval`` once changes them for a
    whole project.
    """

    delay = 0.4
    """How many seconds a click is held before it first repeats."""
    interval = 0.05
    """How many seconds apart the repeats come after that."""

    part: str | None = None
    """The part being held down, or ``None`` when nothing is."""
    row: int = 0
    """The row the pointer is on now, in the coordinates of whatever owns
    this object."""
    column: int = 0
    """The column the pointer is on now, in the same coordinates as
    ``row``."""
    next_time: float = field(default=0.0, repr=False)

    def start(self, part: str | None, row: int, column: int, now: float) -> None:
        """Record a press on ``part``, which has already been acted on once,
        so that it is repeated later."""
        self.part = part if part not in (None, "thumb") else None
        self.row, self.column = row, column
        self.next_time = now + self.delay

    def move(self, row: int, column: int) -> None:
        """Record that the pointer moved while the button is held down."""
        self.row, self.column = row, column

    def stop(self) -> None:
        """Record that the button was released."""
        self.part = None

    def wake_time(self) -> float | None:
        """When the next repeat is due, while a part is being held down."""
        return self.next_time if self.part is not None else None

    def due(self, now: float, part_now: str | None) -> bool:
        """Whether to repeat now: the time has come, and the pointer is on
        ``part_now``, the same part that was pressed. Also schedules the next
        repeat."""
        if self.part is None or now < self.next_time:
            return False
        self.next_time = now + self.interval
        return part_now == self.part
