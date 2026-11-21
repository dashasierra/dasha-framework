"""Safe printing straight to the terminal."""

import sys
from typing import TextIO

from dasha.canvas import CONTROL_GLYPHS, UNSHOWABLE


def printable(text: str) -> str:
    """Text made safe to print.

    :param text: The text.
    """
    if text.isprintable():
        return text  # the common case: nothing to replace
    return "".join(_printed(char) for char in text)


def _printed(char: str) -> str:
    if char in "\n\t" or char.isprintable():
        return char
    return CONTROL_GLYPHS.get(char, UNSHOWABLE)


def say(*values: object, sep: str = " ", file: TextIO | None = None) -> None:
    """A safe ``print``.

    :param values: What to print.
    :param sep: Separator between values.
    :param file: Where to print, or ``None`` for standard output.
    """
    text = printable(sep.join(str(value) for value in values))
    print(text, file=sys.stdout if file is None else file)
