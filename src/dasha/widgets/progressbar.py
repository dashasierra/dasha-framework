"""Progress bars, which show how far a task has progressed, as a bar that
fills up.

A ``ProgressBar`` fills from left to right, and a ``ColumnBar`` from the
bottom up. Either can show text in its middle (``42%`` by default), which
changes colour where the bar has reached it::

    ██████████42%░░░░░░░░░░

A column bar's text reads from top to bottom, one character to a row::

    ░
    4
    2
    %
    █

Each cell is filled, empty or half filled (``▌`` across, ``▄`` upwards), so
the bar moves in steps of half a cell.
"""

from dasha.canvas import Canvas, Rect
from dasha.style import BLUE, BRIGHT_WHITE, CYAN, Style
from dasha.widgets.base import Widget

EMPTY = "\N{LIGHT SHADE}"
HALF_ACROSS = "\N{LEFT HALF BLOCK}"
HALF_UP = "\N{LOWER HALF BLOCK}"
"""The empty track ``░`` (code page 437 glyph 176), and the half-filled
cells ``▌`` (221) and ``▄`` (220)."""


class ProgressBar(Widget):
    """A ``ProgressBar`` shows how far a task has progressed, filling from left
    to right as its ``value`` goes from 0 to ``maximum`` (100 by default). A
    ``ColumnBar`` is the same, but vertical, filling from the bottom to the top.
    Each is ``length`` cells long and ``thickness`` cells across, and moves in
    steps of half a cell: a half-filled cell is ``▌`` across, or ``▄`` upwards
    (code page 437 glyphs 221 and 220), and the part of the track not yet
    reached is ``░`` (176).

    ::

        ██████████42%░░░░░░░░░░

    ``text`` is written in the middle. It is a format string that is given
    ``value``, ``maximum`` and ``per_cent`` (the default is ``"{per_cent:.0f}%"``,
    and ``"{value} of {maximum}"`` works too), or ``None`` for no text. Where the
    bar has reached the text, the text is drawn in the bar's colours
    (``progress.filled``), and the rest of it in the track's colours
    (``progress.empty``), so it changes colour one character at a time as the bar
    passes over it. A column bar's text is written down its middle column, one
    character to a row, reading from top to bottom, and each character changes
    colour as the bar rises past it; make the column tall enough for the text (4
    rows for ``100%``), or it is cut short. Neither kind takes the keyboard focus:
    code sets ``value`` as the work goes on, and it is kept between 0 and
    ``maximum``.

    ::

        bar = window.add(
            ProgressBar(
                row=2, column=1, length=30, maximum=12, text="{value} of {maximum}"
            )
        )
        bar.value = 5  # shows "5 of 12", the bar five twelfths full
    """

    filled_style: Style = Style(foreground=BRIGHT_WHITE, background=CYAN, bold=True)
    """The style of the filled part, and of the text over it."""
    empty_style: Style = Style(foreground=CYAN, background=BLUE)
    """The style of the ``░`` track not yet reached, and of the text over
    it."""
    vertical = False

    def __init__(  # pylint: disable=too-many-arguments
        self,
        row: int,
        column: int,
        length: int,
        thickness: int = 1,
        *,
        value: float = 0,
        maximum: float = 100,
        text: str | None = "{per_cent:.0f}%",
        name: str | None = None,
        status: str = "",
    ) -> None:
        if length < 1 or thickness < 1:
            raise ValueError("a progress bar needs at least one cell")
        if maximum <= 0:
            raise ValueError("maximum must be more than 0")
        width, height = (thickness, length) if self.vertical else (length, thickness)
        super().__init__(row, column, width, height, name=name, status=status)
        self.maximum = maximum
        self.text = text
        self._value: float = 0
        self.value = value

    @property
    def value(self) -> float:
        """How far the task has progressed, from 0 to ``maximum``. Setting it
        keeps it within that range."""
        return self._value

    @value.setter
    def value(self, value: float) -> None:
        self._value = max(0, min(value, self.maximum))

    @property
    def fraction(self) -> float:
        """How full the bar is, from 0 to 1."""
        return self._value / self.maximum

    @property
    def label(self) -> str:
        """The text shown in the middle (``""`` for none)."""
        if self.text is None:
            return ""
        return self.text.format(
            value=self._value, maximum=self.maximum, per_cent=self.fraction * 100
        )

    @property
    def length(self) -> int:
        """How many cells long the bar is."""
        return self.rect.height if self.vertical else self.rect.width

    @property
    def thickness(self) -> int:
        """How many cells wide the bar is."""
        return self.rect.width if self.vertical else self.rect.height

    def min_size(self) -> tuple[int, int]:
        return 1, 1

    @property
    def halves(self) -> int:
        """How many half cells are filled."""
        return round(self.fraction * self.length * 2)

    def filled(self, along: int) -> bool:
        """Whether cell ``along`` (counted from the start, which is the left or
        the bottom) counts as reached, for the colour of the text over it. A
        half-filled cell counts."""
        return 2 * along < self.halves

    def _cell(self, along: int) -> tuple[str, Style]:
        """The track's character and colours at cell ``along``."""
        halves = self.halves
        if 2 * along + 2 <= halves:
            return " ", self.filled_style
        if 2 * along + 1 == halves:
            half = Style(
                foreground=self.filled_style.background,
                background=self.empty_style.background,
            )
            return (HALF_UP if self.vertical else HALF_ACROSS), half
        return EMPTY, self.empty_style

    def _placed_label(self) -> tuple[str, int, int]:
        """The text, cut to the bar's length, with the line along the bar it
        is written on (a row across, a column up) and how far from the top
        or left it starts: in the middle both ways."""
        label = self.label[: self.length]
        return label, (self.thickness - 1) // 2, (self.length - len(label)) // 2

    def _shown_at(self, down: int, across: int) -> tuple[str, Style]:
        """The character and colours at a cell of the bar: the text's, in
        the colours of the part it is on, or the track's."""
        label, middle, start = self._placed_label()
        along = self.length - 1 - down if self.vertical else across
        line, reading = (across, down) if self.vertical else (down, across)
        offset = reading - start
        if line == middle and 0 <= offset < len(label):
            style = self.filled_style if self.filled(along) else self.empty_style
            return label[offset], style
        return self._cell(along)

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        del focused
        top, left = origin.row + self.rect.row, origin.column + self.rect.column
        for down in range(self.rect.height):
            for across in range(self.rect.width):
                char, style = self._shown_at(down, across)
                canvas.write(top + down, left + across, char, style, clip=origin)


class ColumnBar(ProgressBar):
    """A vertical progress bar, which fills from the bottom to the top, and
    is ``length`` rows tall and ``thickness`` columns wide. Its text is written
    down its middle column, one character to a row from top to bottom, each
    changing colour as the bar rises past it; make the bar tall enough for the
    text (4 rows for ``100%``)."""

    vertical = True
