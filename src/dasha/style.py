"""Cell colours and attributes."""

import os
import re
from dataclasses import dataclass

from dasha.terminal import ansi

# The 16 standard ANSI colour numbers, for readability.
BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)
BRIGHT_BLACK, BRIGHT_RED, BRIGHT_GREEN, BRIGHT_YELLOW = range(8, 12)
BRIGHT_BLUE, BRIGHT_MAGENTA, BRIGHT_CYAN, BRIGHT_WHITE = range(12, 16)

_HEX = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})")

_CUBE_LEVELS = (0, 95, 135, 175, 215, 255)
"""Colour cube levels of the 256-colour palette."""

CGA_COLOURS = (
    (0x00, 0x00, 0x00),
    (0xAA, 0x00, 0x00),
    (0x00, 0xAA, 0x00),
    (0xAA, 0x55, 0x00),
    (0x00, 0x00, 0xAA),
    (0xAA, 0x00, 0xAA),
    (0x00, 0xAA, 0xAA),
    (0xAA, 0xAA, 0xAA),
    (0x55, 0x55, 0x55),
    (0xFF, 0x55, 0x55),
    (0x55, 0xFF, 0x55),
    (0xFF, 0xFF, 0x55),
    (0x55, 0x55, 0xFF),
    (0xFF, 0x55, 0xFF),
    (0x55, 0xFF, 0xFF),
    (0xFF, 0xFF, 0xFF),
)
"""RGB values of the 16 standard colours."""


def _nearest_level(value: int) -> int:
    return min(range(6), key=lambda index: abs(_CUBE_LEVELS[index] - value))


@dataclass(frozen=True, slots=True)
class Rgb:
    """A 24-bit colour."""

    red: int
    green: int
    blue: int

    def __post_init__(self) -> None:
        for part in (self.red, self.green, self.blue):
            if isinstance(part, bool) or not isinstance(part, int):
                raise ValueError(f"RGB parts must be numbers, not {part!r}")
            if not 0 <= part <= 255:
                raise ValueError(f"RGB parts must be 0-255, not {part}")

    @classmethod
    def parse(cls, text: str) -> "Rgb":
        """Parse a ``"#rrggbb"`` or ``"#rgb"`` colour.

        :param text: The colour text.
        """
        found = _HEX.fullmatch(text) if isinstance(text, str) else None
        if found is None:
            raise ValueError(f"{text!r} is not an RGB colour such as #ff8800")
        digits = found.group(1)
        if len(digits) == 3:
            digits = "".join(digit * 2 for digit in digits)
        red, green, blue = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
        return cls(red, green, blue)

    @property
    def hex(self) -> str:
        """The colour written as ``"#rrggbb"``."""
        return f"#{self.red:02x}{self.green:02x}{self.blue:02x}"

    def __str__(self) -> str:
        return self.hex

    def nearest_256(self) -> int:
        """The nearest colour from 16 to 255."""
        levels = [_nearest_level(part) for part in (self.red, self.green, self.blue)]
        cube = tuple(_CUBE_LEVELS[level] for level in levels)
        average = (self.red + self.green + self.blue) // 3
        step = min(23, max(0, round((average - 8) / 10)))
        grey = 8 + 10 * step
        if self._distance((grey,) * 3) < self._distance(cube):
            return 232 + step
        return 16 + 36 * levels[0] + 6 * levels[1] + levels[2]

    def nearest_16(self) -> int:
        """The nearest standard colour."""
        return min(range(16), key=lambda number: self._distance(CGA_COLOURS[number]))

    @classmethod
    def of_palette(cls, number: int) -> "Rgb":
        """A palette number's usual colour.

        :param number: Palette number, 0 to 255.
        """
        if number < 16:
            return cls(*CGA_COLOURS[number])
        if number >= 232:
            grey = 8 + 10 * (number - 232)
            return cls(grey, grey, grey)
        number -= 16
        return cls(
            _CUBE_LEVELS[number // 36],
            _CUBE_LEVELS[number // 6 % 6],
            _CUBE_LEVELS[number % 6],
        )

    def _distance(self, other: tuple[int, ...]) -> int:
        return sum(
            (a - b) ** 2 for a, b in zip((self.red, self.green, self.blue), other)
        )


Colour = int | Rgb
"""A palette number or an ``Rgb``."""

COLOUR_DEPTHS = ("auto", "16", "256", "24bit")
"""Ways to draw colours."""

SIXTEEN_COLOUR_TERMINALS = ("linux", "cons25", "ansi")
"""Terminals with only 16 colours."""

NO_COLOUR_TERMINALS = ("dumb", "vt52", "vt100", "vt102", "vt220", "vt320", "vt420")
"""Terminals (``TERM``) that show no colours at all."""

DRAWN_DEPTH = "24bit"
"""The colour depth in use."""

COLOURS_SHOWN = True
"""Whether colours are drawn at all. Set by ``show_colours``."""


def terminal_has_colours() -> bool:
    """Whether the terminal shows colours."""
    if os.name == "nt" or os.environ.get("COLORTERM"):
        return True
    return os.environ.get("TERM", "").lower() not in NO_COLOUR_TERMINALS


def show_colours(shown: bool) -> None:
    """Draw colours or none at all.

    :param shown: Whether colours are drawn.
    """
    global COLOURS_SHOWN  # pylint: disable=global-statement
    COLOURS_SHOWN = shown


def terminal_depth() -> str:
    """The depth the terminal seems to allow."""
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return "24bit"
    if os.name == "nt":
        return "24bit"
    if os.environ.get("TERM", "").lower() in SIXTEEN_COLOUR_TERMINALS:
        return "16"
    return "256"


def set_colour_depth(depth: str) -> None:
    """Set how colours are drawn.

    :param depth: One of ``COLOUR_DEPTHS``.
    """
    global DRAWN_DEPTH  # pylint: disable=global-statement
    if depth not in COLOUR_DEPTHS:
        raise ValueError(f"colour depth must be auto, 16, 256 or 24bit, not {depth!r}")
    DRAWN_DEPTH = terminal_depth() if depth == "auto" else depth


set_colour_depth("auto")


def _colour_parameters(colour: Colour, base: int, bright_base: int) -> str:
    if isinstance(colour, Rgb):
        if DRAWN_DEPTH == "24bit":
            return f"{base + 8};2;{colour.red};{colour.green};{colour.blue}"
        colour = colour.nearest_256() if DRAWN_DEPTH == "256" else colour.nearest_16()
    if not 0 <= colour <= 255:
        raise ValueError(f"colour must be 0-255, not {colour}")
    if colour >= 16 and DRAWN_DEPTH == "16":
        colour = Rgb.of_palette(colour).nearest_16()
    if colour < 8:
        return str(base + colour)
    if colour < 16:
        return str(bright_base + colour - 8)
    return f"{base + 8};5;{colour}"


@dataclass(frozen=True, slots=True)
class Style:
    """How a cell is drawn."""

    foreground: Colour | None = None
    background: Colour | None = None
    bold: bool = False
    reverse: bool = False
    underline: bool = False

    def sgr(self) -> str:
        """Return the escape sequence that switches the terminal to this style."""
        parameters = ["0"]
        if self.bold:
            parameters.append("1")
        if self.underline:
            parameters.append("4")
        if self.reverse or (not COLOURS_SHOWN and self.background is not None):
            parameters.append("7")
        if COLOURS_SHOWN and self.foreground is not None:
            parameters.append(_colour_parameters(self.foreground, 30, 90))
        if COLOURS_SHOWN and self.background is not None:
            parameters.append(_colour_parameters(self.background, 40, 100))
        return f"{ansi.CSI}{';'.join(parameters)}m"


DEFAULT = Style()
"""The terminal's own colours, with no attributes."""

SHADOW = Style(foreground=BRIGHT_BLACK, background=BLACK)
"""Drop shadow style."""
