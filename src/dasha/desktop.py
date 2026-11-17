"""The desktop: the background that fills the screen behind everything else."""

from dasha.canvas import Canvas
from dasha.style import BLACK, Style, CYAN


class Desktop:
    r"""Fills the whole screen with a repeating background pattern.

    The defaults give the traditional text-mode desktop: a screen full of
    light shade characters (``░``, code page 437 character 176). They can be
    changed for a single instance::

        Desktop(pattern="\u2592")

    or for every instance by subclassing::

        class DottedDesktop(Desktop):
            pattern = "\u00b7"
            style = Style(foreground=BLUE)

    For anything more elaborate than a repeating pattern, override
    ``character_at``.
    """

    pattern: str = "\u2591"
    """The characters repeated across each row, each of which must take up
    exactly one column."""

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
        """Return the character drawn at a 0-based screen position."""
        del row  # the default pattern repeats the same way on every row
        return self.pattern[column % len(self.pattern)]

    def paint(self, canvas: Canvas) -> None:
        """Paint the desktop over the whole canvas."""
        for row in range(canvas.height):
            self.paint_row(canvas, row)

    def paint_row(self, canvas: Canvas, row: int) -> None:
        """Paint the desktop over one row of the canvas."""
        canvas.write(
            row,
            0,
            "".join(self.character_at(row, column) for column in range(canvas.width)),
            self.style,
        )
