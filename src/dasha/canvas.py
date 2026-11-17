"""An off-screen grid of styled cells, on which each frame of the screen is
composed.

Everything on the screen (the desktop, windows, menus and the status bar) is
painted onto a ``Canvas``, from back to front. The finished canvas is then
compared with the one currently on screen, and only the cells that have
changed are sent to the terminal. This keeps redrawing fast and free of
flicker, even over SSH.

Control characters never reach the terminal, where they could act as
commands (for example, from a file whose name contains an escape sequence):
``render`` shows them as code page 437 pictures instead (``CONTROL_GLYPHS``).
Nor do characters that would not take up exactly one cell, or that cannot be
written at all; see ``shown``.
"""

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
        """Whether the cell at ``row``, ``column`` is inside the rectangle."""
        return self.row <= row < self.bottom and self.column <= column < self.right

    def intersect(self, other: "Rect") -> "Rect":
        """The overlap of two rectangles (possibly empty)."""
        row = max(self.row, other.row)
        column = max(self.column, other.column)
        return Rect(
            row,
            column,
            max(0, min(self.bottom, other.bottom) - row),
            max(0, min(self.right, other.right) - column),
        )

    def inset(self, amount: int = 1) -> "Rect":
        """The rectangle shrunk by ``amount`` cells on every side."""
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
"""Characters a drop shadow replaces with a space: ▄ ▀ █ ▌ ▐."""

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
"""What ``render`` sends in place of each control character, which the
terminal could otherwise take as a command or part of one. C0 controls are
sent as their code page 437 pictures (escape as ←, bell as •), delete as ⌂,
and C1 controls as ``?``. The canvas itself keeps the original character."""

UNSHOWABLE = "?"
"""What ``shown`` draws for a character that cannot take up exactly one
cell."""

_shown_cache: dict[str, str] = {}


def shown(char: str) -> str:
    """What the terminal is sent for a cell holding ``char``: either the
    character itself, or a replacement that is safe to send and takes up
    exactly one column, as every cell must for the rows to line up.

    - Control characters are replaced by their ``CONTROL_GLYPHS``.
    - Surrogates (such as ``"\\udcff"``, which Python produces for a file
      name that is not valid UTF-8, and which JSON may contain) cannot be
      encoded at all, so they become ``UNSHOWABLE``.
    - Wide characters (such as ``"\\u5bec"``, and most emoji) take up two
      columns, and zero-width characters (combining accents, joiners and
      direction marks) take up none and could make text read in a different
      order, so they also become ``UNSHOWABLE``.

    Every code page 437 character is shown as it is."""
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
    """Where the drop shadow falls for something occupying ``rect``.

    The shadow is a strip ``width`` columns wide down the right side,
    starting ``height`` rows below the top, and a strip ``height`` rows high
    along the bottom, starting ``width`` columns in, so that the box seems to
    float above the screen. Two columns by one row looks square in most
    terminal fonts.
    """
    return (
        Rect(rect.row + height, rect.right, rect.height, width),
        Rect(rect.bottom, rect.column + width, height, rect.width - width),
    )


class Canvas:
    """A grid of ``width`` by ``height`` cells, each holding a character and
    a style."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._rows: list[list[Cell]] = [[(" ", DEFAULT)] * width for _ in range(height)]
        self._clip: Rect | None = None
        self.cursor: tuple[int, int] | None = None
        """Where the terminal's cursor is shown (row, column), or ``None`` to
        hide it. A focused text box puts the cursor where typing will go."""

    @property
    def bounds(self) -> Rect:
        """The rectangle covering the whole canvas."""
        return Rect(0, 0, self.height, self.width)

    @contextmanager
    def clipped(self, rect: Rect) -> Iterator[None]:
        """Keep all drawing inside ``rect`` (and inside any outer clipping
        area) until the ``with`` block ends.

        This is used to draw a window's scrolled contents: the widgets draw
        as usual, at positions that may lie outside the window, and only the
        part inside the frame reaches the canvas. Clipping areas can be
        nested.
        """
        outer = self._clip
        self._clip = rect if outer is None else outer.intersect(rect)
        try:
            yield
        finally:
            self._clip = outer

    def _area(self, rect: Rect | None = None) -> Rect:
        """The part of the canvas drawing may touch: the canvas, within the
        current clip, within ``rect``."""
        area = self.bounds if self._clip is None else self.bounds.intersect(self._clip)
        return area if rect is None else area.intersect(rect)

    def place_cursor(self, row: int, column: int) -> None:
        """Show the cursor at a position, if that position is inside the
        canvas and the current clipping area; otherwise, leave it hidden."""
        if self._area().contains(row, column):
            self.cursor = (row, column)

    def cell(self, row: int, column: int) -> Cell:
        """Return the character and style at a position."""
        return self._rows[row][column]

    def text(self, row: int) -> str:
        """Return the characters of one row, without styles."""
        return "".join(char for char, _ in self._rows[row])

    def write(
        self,
        row: int,
        column: int,
        text: str,
        style: Style = DEFAULT,
        clip: Rect | None = None,
    ) -> None:
        """Write text at a position, one character to a cell, clipped to
        ``clip`` and to the canvas."""
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
        """Fill a rectangle (clipped to the canvas) with a single character."""
        area = self._area(rect)
        for row in range(area.row, area.bottom):
            self._rows[row][area.column : area.right] = [(char, style)] * area.width

    def copy_from(
        self, source: "Canvas", row: int, column: int, clip: Rect | None = None
    ) -> None:
        """Copy every cell of another canvas onto this one, with its top-left
        cell at ``row``, ``column``, clipped to ``clip`` and to this
        canvas."""
        area = self._area(clip).intersect(
            Rect(row, column, source.height, source.width)
        )
        for target in range(area.row, area.bottom):
            cells = source._rows[target - row]  # pylint: disable=protected-access
            self._rows[target][area.column : area.right] = cells[
                area.column - column : area.right - column
            ]

    def restyle(self, rect: Rect, style: Style) -> None:
        """Give every cell in a rectangle (clipped) a new style, keeping its
        character. Shadows use this to darken whatever lies beneath them."""
        area = self._area(rect)
        for row in range(area.row, area.bottom):
            cells = self._rows[row]
            for column in range(area.column, area.right):
                cells[column] = (cells[column][0], style)

    def cast_shadow(
        self, rect: Rect, style: Style, width: int = 2, height: int = 1
    ) -> None:
        """Darken the area where ``rect`` casts its drop shadow, keeping the
        characters beneath.

        Block characters (``SHADOW_BLANKS``) become spaces instead, because
        redrawn dark grey on black they would look like bright patches (as
        button shadows did under a window's shadow).
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
        """Return the terminal output that changes the screen from
        ``previous`` to this canvas.

        Without ``previous`` (or if it is a different size), every cell is
        drawn. Each cell is sent as ``shown`` translates it: control
        characters as ``CONTROL_GLYPHS``, and characters that cannot take up
        exactly one cell as ``UNSHOWABLE``, never as they are. The cursor
        stays hidden until a canvas has a ``cursor``; the output then ends by
        moving the cursor there and showing it.
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
