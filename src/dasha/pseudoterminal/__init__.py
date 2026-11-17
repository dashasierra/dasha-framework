"""Pseudo-terminals: running a program as though in a terminal of its own.

A shell run with pipes for its input and output knows it has no terminal,
and behaves differently (no prompt editing, no colours, Ctrl+C that does
nothing). Run in a pseudo-terminal instead, it sees a terminal, of a size
it is told, and writes to it just as it would to a real one.
``dasha.widgets.TerminalView`` runs a program like this, and shows what
it writes in a window.

``open_pty()`` gives a ``PseudoTerminal`` for this system: a POSIX one
(``os.forkpty``) on Linux and macOS, and on Windows a pseudoconsole
(ConPTY, Windows 10 version 1809 or later), through ctypes. Each has the
same interface. Its output arrives through ``on_output``, called from a
thread of its own, which reads it as soon as it is written; input given to
``write`` goes to the program from another thread, so writing never holds
up the caller, even when the program is not reading.
"""

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
