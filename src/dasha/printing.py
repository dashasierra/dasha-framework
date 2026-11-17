"""Messages printed directly on the terminal, outside the screen that
Dasha Framework draws: the command line's errors and reports, printed before the
screen is taken over or after it has been given back.

Everything shown on the screen goes through ``Canvas.render``, which never
sends a control character as it is. A message printed with plain ``print``
would, and messages can contain text from outside, such as an application's
name from its manifest, a file name, or the last line an application wrote
to its log. Any of these could hold an escape sequence that the terminal
would carry out. ``say`` prints messages as the screen would show them
instead.
"""

import sys
from typing import TextIO

from dasha.canvas import CONTROL_GLYPHS, UNSHOWABLE


def printable(text: str) -> str:
    """Text made safe to print on a terminal. Control characters (other
    than line breaks and tabs) become their code page 437 pictures
    (``CONTROL_GLYPHS``, so escape becomes ←), and characters that would
    print as nothing or reorder what follows (direction marks and
    overrides, surrogates and separators) become ``UNSHOWABLE``."""
    if text.isprintable():
        return text  # the common case: nothing to replace
    return "".join(_printed(char) for char in text)


def _printed(char: str) -> str:
    if char in "\n\t" or char.isprintable():
        return char
    return CONTROL_GLYPHS.get(char, UNSHOWABLE)


def say(*values: object, sep: str = " ", file: TextIO | None = None) -> None:
    """A safe version of ``print`` (using ``printable``), for every message
    Dasha Framework prints directly on the terminal. ``file`` is standard output
    unless another is given."""
    text = printable(sep.join(str(value) for value in values))
    print(text, file=sys.stdout if file is None else file)
