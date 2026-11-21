"""The desktop background."""

from dasha.canvas import Canvas
from dasha.style import BLACK, Style, CYAN


class Desktop:
    """A repeating background pattern.

    :param pattern: Pattern characters, or ``None`` for the default.
    :param style: Pattern style, or ``None`` for the default.
    """

    pattern: str = "\u2591"
    """Pattern characters."""

    style: Style = Style(foreground=CYAN, background=BLACK)
    """Colours and attributes applied to the whole desktop."""

    def __init__(self, pattern: str | None = None, style: Style | None = None) -> None:
        if pattern is not None:
            self.pattern = pattern
        if style is not None:
            self.style = style
        if not self.pattern:
            raise ValueError("Desktop pattern must not be empty")

    def character_at(self, row: int, column: int) -> str:
        """The character at a screen position.

        :param row: Screen row.
        :param column: Screen column.
        """
        del row  # the default pattern repeats the same way on every row
        return self.pattern[column % len(self.pattern)]

    def paint(self, canvas: Canvas) -> None:
        """Paint the whole canvas.

        :param canvas: Canvas to draw on.
        """
        for row in range(canvas.height):
            self.paint_row(canvas, row)

    def paint_row(self, canvas: Canvas, row: int) -> None:
        """Paint one row.

        :param canvas: Canvas to draw on.
        :param row: The row.
        """
        canvas.write(
            row,
            0,
            "".join(self.character_at(row, column) for column in range(canvas.width)),
            self.style,
        )
