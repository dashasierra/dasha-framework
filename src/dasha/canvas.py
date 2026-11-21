"""An off-screen grid of styled cells."""

import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from dasha.style import DEFAULT, Style
from dasha.terminal import ansi

type Cell = tuple[str, Style]


@dataclass(frozen=True, slots=True)
class Rect:
    """A rectangle of cells. ``row`` and ``column`` are 0-based."""

    row: int
    column: int
    height: int
    width: int

    @property
    def bottom(self) -> int:
        """The row just below the rectangle."""
        return self.row + self.height

    @property
    def right(self) -> int:
        """The column just right of the rectangle."""
        return self.column + self.width

    @property
    def is_empty(self) -> bool:
        """Whether the rectangle covers no cells."""
        return self.height <= 0 or self.width <= 0

    def contains(self, row: int, column: int) -> bool:
        """Whether a cell is inside the rect.

        :param row: Cell row.
        :param column: Cell column.
        """
        return self.row <= row < self.bottom and self.column <= column < self.right

    def intersect(self, other: "Rect") -> "Rect":
        """The overlap with another rect.

        :param other: The other rect.
        """
        row = max(self.row, other.row)
        column = max(self.column, other.column)
        return Rect(
            row,
            column,
            max(0, min(self.bottom, other.bottom) - row),
            max(0, min(self.right, other.right) - column),
        )

    def inset(self, amount: int = 1) -> "Rect":
        """The rect shrunk on every side.

        :param amount: Cells to shrink by.
        """
        return Rect(
            self.row + amount,
            self.column + amount,
            max(0, self.height - 2 * amount),
            max(0, self.width - 2 * amount),
        )


SHADOW_BLANKS = frozenset(
    "\N{LOWER HALF BLOCK}\N{UPPER HALF BLOCK}\N{FULL BLOCK}"
    "\N{LEFT HALF BLOCK}\N{RIGHT HALF BLOCK}"
)
"""Characters a shadow blanks out."""

_C0_GLYPHS = (
    " \N{WHITE SMILING FACE}\N{BLACK SMILING FACE}\N{BLACK HEART SUIT}"
    "\N{BLACK DIAMOND SUIT}\N{BLACK CLUB SUIT}\N{BLACK SPADE SUIT}\N{BULLET}"
    "\N{INVERSE BULLET}\N{WHITE CIRCLE}\N{INVERSE WHITE CIRCLE}\N{MALE SIGN}"
    "\N{FEMALE SIGN}\N{EIGHTH NOTE}\N{BEAMED EIGHTH NOTES}\N{WHITE SUN WITH RAYS}"
    "\N{BLACK RIGHT-POINTING POINTER}\N{BLACK LEFT-POINTING POINTER}"
    "\N{UP DOWN ARROW}\N{DOUBLE EXCLAMATION MARK}\N{PILCROW SIGN}\N{SECTION SIGN}"
    "\N{BLACK RECTANGLE}\N{UP DOWN ARROW WITH BASE}\N{UPWARDS ARROW}"
    "\N{DOWNWARDS ARROW}\N{RIGHTWARDS ARROW}\N{LEFTWARDS ARROW}\N{RIGHT ANGLE}"
    "\N{LEFT RIGHT ARROW}\N{BLACK UP-POINTING TRIANGLE}"
    "\N{BLACK DOWN-POINTING TRIANGLE}"
)
"""Code page 437's pictures for the C0 control characters, 0x00 to 0x1F."""

CONTROL_GLYPHS: dict[str, str] = {
    **{chr(code): glyph for code, glyph in enumerate(_C0_GLYPHS)},
    "\x7f": "\N{HOUSE}",
    **{chr(code): "?" for code in range(0x80, 0xA0)},
}
"""Safe replacements for control characters."""

UNSHOWABLE = "?"
"""Replacement for unshowable characters."""

_shown_cache: dict[str, str] = {}


def shown(char: str) -> str:
    """What the terminal is sent for a character.

    :param char: The cell's character.
    """
    if len(char) != 1:  # a cell holds one character; anything else is not one
        return UNSHOWABLE
    if char < "̀" and char not in CONTROL_GLYPHS:
        return char  # the common case: ASCII and Latin-1, nothing to look up
    known = _shown_cache.get(char)
    if known is None:
        known = CONTROL_GLYPHS.get(char) or _looked_up(char)
        if len(_shown_cache) < 4096:
            _shown_cache[char] = known
    return known


def _looked_up(char: str) -> str:
    if "\ud800" <= char <= "\udfff":
        return UNSHOWABLE
    if unicodedata.east_asian_width(char) in ("W", "F"):
        return UNSHOWABLE
    if unicodedata.category(char) in ("Mn", "Me", "Cf", "Cs", "Co", "Cn"):
        return UNSHOWABLE
    return char


def shadow_rects(rect: Rect, width: int = 2, height: int = 1) -> tuple[Rect, Rect]:
    """Where a drop shadow falls.

    :param rect: The shadowed area.
    :param width: Shadow width in columns.
    :param height: Shadow height in rows.
    """
    return (
        Rect(rect.row + height, rect.right, rect.height, width),
        Rect(rect.bottom, rect.column + width, height, rect.width - width),
    )


class Canvas:
    """A grid of styled character cells.

    :param width: Width in cells.
    :param height: Height in cells.
    """

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._rows: list[list[Cell]] = [[(" ", DEFAULT)] * width for _ in range(height)]
        self._clip: Rect | None = None
        self.cursor: tuple[int, int] | None = None
        """Cursor position, or ``None`` to hide it."""

    @property
    def bounds(self) -> Rect:
        """The rectangle covering the whole canvas."""
        return Rect(0, 0, self.height, self.width)

    @contextmanager
    def clipped(self, rect: Rect) -> Iterator[None]:
        """Clip drawing to a rect within a ``with`` block.

        :param rect: The clipping area.
        """
        outer = self._clip
        self._clip = rect if outer is None else outer.intersect(rect)
        try:
            yield
        finally:
            self._clip = outer

    def _area(self, rect: Rect | None = None) -> Rect:
        """The drawable area.

        :param rect: Area to limit to, if any.
        """
        area = self.bounds if self._clip is None else self.bounds.intersect(self._clip)
        return area if rect is None else area.intersect(rect)

    def place_cursor(self, row: int, column: int) -> None:
        """Show the cursor if the position is drawable.

        :param row: Cursor row.
        :param column: Cursor column.
        """
        if self._area().contains(row, column):
            self.cursor = (row, column)

    def cell(self, row: int, column: int) -> Cell:
        """The character and style at a position.

        :param row: Cell row.
        :param column: Cell column.
        """
        return self._rows[row][column]

    def text(self, row: int) -> str:
        """A row's characters.

        :param row: The row.
        """
        return "".join(char for char, _ in self._rows[row])

    def write(
        self,
        row: int,
        column: int,
        text: str,
        style: Style = DEFAULT,
        clip: Rect | None = None,
    ) -> None:
        """Write text at a position.

        :param row: Starting row.
        :param column: Starting column.
        :param text: The text.
        :param style: Text style.
        :param clip: Area to clip to, if any.
        """
        area = self._area(clip)
        if not area.row <= row < area.bottom:
            return
        cells = self._rows[row]
        for offset, char in enumerate(text):
            col = column + offset
            if col >= area.right:
                break
            if col >= area.column:
                cells[col] = (char, style)

    def fill(self, rect: Rect, char: str = " ", style: Style = DEFAULT) -> None:
        """Fill a rect with a character.

        :param rect: The area.
        :param char: The character.
        :param style: Fill style.
        """
        area = self._area(rect)
        for row in range(area.row, area.bottom):
            self._rows[row][area.column : area.right] = [(char, style)] * area.width

    def copy_from(
        self, source: "Canvas", row: int, column: int, clip: Rect | None = None
    ) -> None:
        """Copy another canvas onto this one.

        :param source: The canvas to copy.
        :param row: Destination row.
        :param column: Destination column.
        :param clip: Area to clip to, if any.
        """
        area = self._area(clip).intersect(
            Rect(row, column, source.height, source.width)
        )
        for target in range(area.row, area.bottom):
            cells = source._rows[target - row]  # pylint: disable=protected-access
            self._rows[target][area.column : area.right] = cells[
                area.column - column : area.right - column
            ]

    def restyle(self, rect: Rect, style: Style) -> None:
        """Restyle a rect, keeping its characters.

        :param rect: The area.
        :param style: New style.
        """
        area = self._area(rect)
        for row in range(area.row, area.bottom):
            cells = self._rows[row]
            for column in range(area.column, area.right):
                cells[column] = (cells[column][0], style)

    def cast_shadow(
        self, rect: Rect, style: Style, width: int = 2, height: int = 1
    ) -> None:
        """Darken a rect's drop shadow.

        :param rect: The shadowed area.
        :param style: Shadow style.
        :param width: Shadow width in columns.
        :param height: Shadow height in rows.
        """
        area = self._area()  # the canvas, within any clip
        for shadow in shadow_rects(rect, width, height):
            shadow = area.intersect(shadow)
            for row in range(shadow.row, shadow.bottom):
                cells = self._rows[row]
                for column in range(shadow.column, shadow.right):
                    char = cells[column][0]
                    cells[column] = (" " if char in SHADOW_BLANKS else char, style)

    def render(self, previous: "Canvas | None" = None) -> str:
        """Terminal output to update the screen.

        :param previous: The canvas on screen, if any.
        """
        old_rows: list[list[Cell]] | None = None
        if previous is not None and previous.width == self.width:
            if previous.height == self.height:
                old_rows = previous._rows  # pylint: disable=protected-access
        parts: list[str] = []
        current_style: Style | None = None
        for row, cells in enumerate(self._rows):
            old_cells: list[Cell] | None = None if old_rows is None else old_rows[row]
            cursor: int | None = None  # column the cursor is known to be at
            for column, (char, style) in enumerate(cells):
                if old_cells is not None and old_cells[column] == (char, style):
                    continue
                if cursor != column:
                    parts.append(ansi.move_to(row, column))
                if style != current_style:
                    parts.append(style.sgr())
                    current_style = style
                parts.append(shown(char))
                cursor = column + 1
        if current_style is not None:
            parts.append(ansi.RESET_ATTRIBUTES)
        old_cursor = None if previous is None else previous.cursor
        if self.cursor is not None:
            if parts or self.cursor != old_cursor:  # drawing moves the cursor
                parts.append(ansi.move_to(*self.cursor))
            if old_cursor is None:
                parts.append(ansi.SHOW_CURSOR)
        elif old_cursor is not None:
            parts.append(ansi.HIDE_CURSOR)
        return "".join(parts)
