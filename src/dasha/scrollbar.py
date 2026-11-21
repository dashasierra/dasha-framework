"""Scroll bar drawing and hit-testing."""

from dataclasses import dataclass, field

from dasha.canvas import Canvas, Rect
from dasha.style import Style

UP = "\N{BLACK UP-POINTING TRIANGLE}"
DOWN = "\N{BLACK DOWN-POINTING TRIANGLE}"
LEFT = "\N{BLACK LEFT-POINTING POINTER}"
RIGHT = "\N{BLACK RIGHT-POINTING POINTER}"
TRACK = "\N{MEDIUM SHADE}"
THUMB = "\N{BLACK SQUARE}"
"""Scroll bar characters."""


def track_position(value: int, maximum: int, cells: int) -> int:
    """The track cell for a value.

    :param value: The value.
    :param maximum: Largest value.
    :param cells: Track length.
    """
    if maximum <= 0 or cells <= 1:
        return 0
    return round(min(max(value, 0), maximum) / maximum * (cells - 1))


def track_value(along: int, maximum: int, cells: int) -> int:
    """The value for a track cell.

    :param along: Cell index.
    :param maximum: Largest value.
    :param cells: Track length.
    """
    if cells <= 1:
        return 0
    return round(min(max(along, 0), cells - 1) / (cells - 1) * maximum)


@dataclass(frozen=True)
class ScrollBarLayout:
    """A scroll bar's position and state."""

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
        """Thumb position along the track."""
        return track_position(self.value, self.maximum, self.track_length)

    def _index(self, row: int, column: int) -> int | None:
        """Distance along the bar, if on it.

        :param row: Screen row.
        :param column: Screen column.
        """
        if not self.rect.contains(row, column):
            return None
        return row - self.row if self.vertical else column - self.column

    def part_at(self, row: int, column: int) -> str | None:
        """The bar part at a position, or ``None``.

        :param row: Screen row.
        :param column: Screen column.
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
        """How far a click on a part scrolls.

        :param part: The part, or ``None``.
        :param line: One line's amount.
        """
        page = max(1, self.page - 1)
        return {
            "back": -line,
            "forward": line,
            "page_back": -page,
            "page_forward": page,
        }.get(part or "", 0)

    def value_at(self, row: int, column: int) -> int:
        """The value for a thumb at a position.

        :param row: Screen row.
        :param column: Screen column.
        """
        along = (row - self.row if self.vertical else column - self.column) - 1
        return track_value(along, self.maximum, self.track_length)

    def paint(self, canvas: Canvas, style: Style) -> None:
        """Draw the bar.

        :param canvas: Canvas to draw on.
        :param style: Bar style.
        """
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
    """Repeats a held scroll bar click."""

    delay = 0.4
    """How many seconds a click is held before it first repeats."""
    interval = 0.05
    """How many seconds apart the repeats come after that."""

    part: str | None = None
    """The part being held down, or ``None`` when nothing is."""
    row: int = 0
    """Pointer row."""
    column: int = 0
    """Pointer column."""
    next_time: float = field(default=0.0, repr=False)

    def start(self, part: str | None, row: int, column: int, now: float) -> None:
        """Record a press.

        :param part: The part pressed.
        :param row: Pointer row.
        :param column: Pointer column.
        :param now: The current ``time.monotonic``.
        """
        self.part = part if part not in (None, "thumb") else None
        self.row, self.column = row, column
        self.next_time = now + self.delay

    def move(self, row: int, column: int) -> None:
        """Record pointer movement.

        :param row: Pointer row.
        :param column: Pointer column.
        """
        self.row, self.column = row, column

    def stop(self) -> None:
        """Record that the button was released."""
        self.part = None

    def wake_time(self) -> float | None:
        """When the next repeat is due."""
        return self.next_time if self.part is not None else None

    def due(self, now: float, part_now: str | None) -> bool:
        """Whether to repeat now.

        :param now: The current ``time.monotonic``.
        :param part_now: The part under the pointer.
        """
        if self.part is None or now < self.next_time:
            return False
        self.next_time = now + self.interval
        return part_now == self.part
