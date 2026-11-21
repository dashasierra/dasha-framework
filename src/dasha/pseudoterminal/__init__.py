"""Pseudo-terminals for running programs."""

import sys

from dasha.pseudoterminal.base import (
    KILL_DELAY,
    READ_SIZE,
    PseudoTerminal,
    find_program,
)

__all__ = ["KILL_DELAY", "READ_SIZE", "PseudoTerminal", "find_program", "open_pty"]


def open_pty() -> PseudoTerminal:
    """A pseudo-terminal for this system, ready to ``start`` a program."""
    # if/else (not an early return) lets mypy skip the other platform's branch.
    if sys.platform == "win32":  # pylint: disable=no-else-return
        # pylint: disable-next=import-outside-toplevel
        from dasha.pseudoterminal._windows import WindowsConPty

        return WindowsConPty()
    else:
        # pylint: disable-next=import-outside-toplevel
        from dasha.pseudoterminal._posix import PosixPty

        return PosixPty()
