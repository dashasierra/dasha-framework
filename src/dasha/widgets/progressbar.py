"""Progress bars."""

from dasha.canvas import Canvas, Rect
from dasha.style import BLUE, BRIGHT_WHITE, CYAN, Style
from dasha.widgets.base import Widget

EMPTY = "\N{LIGHT SHADE}"
HALF_ACROSS = "\N{LEFT HALF BLOCK}"
HALF_UP = "\N{LOWER HALF BLOCK}"
"""Track and half-filled cell characters."""


class ProgressBar(Widget):
    """A horizontal bar showing progress.

    :param row: Row in the window.
    :param column: Column in the window.
    :param length: Length in cells.
    :param thickness: Thickness in cells.
    :param value: Progress so far.
    :param maximum: Value when complete.
    :param text: Format string for the middle text, or ``None``.
    :param name: Widget name.
    :param status: Status bar text.
    """

    filled_style: Style = Style(foreground=BRIGHT_WHITE, background=CYAN, bold=True)
    """The style of the filled part, and of the text over it."""
    empty_style: Style = Style(foreground=CYAN, background=BLUE)
    """Style of the unreached track."""
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
        """Progress, from 0 to ``maximum``."""
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
        """Whether a cell counts as reached.

        :param along: Cells from the start.
        """
        return 2 * along < self.halves

    def _cell(self, along: int) -> tuple[str, Style]:
        """The track's character and style at a cell.

        :param along: Cells from the start.
        """
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
        """The text, with where it is placed."""
        label = self.label[: self.length]
        return label, (self.thickness - 1) // 2, (self.length - len(label)) // 2

    def _shown_at(self, down: int, across: int) -> tuple[str, Style]:
        """The character and style at a cell.

        :param down: Rows from the top.
        :param across: Columns from the left.
        """
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
    """A vertical progress bar, filling upwards."""

    vertical = True
