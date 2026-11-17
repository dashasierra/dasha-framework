"""The command prompt: the user's own shell, run while the desktop waits.

The desktop gives the terminal back (``Terminal.suspended``), so the user's
own screen returns, and runs their shell there in the foreground
(``run_shell``) until they type ``exit``; then it takes the terminal again
and draws everything afresh. Applications carry on in their own processes
meanwhile, their messages waiting for the desktop.

Keys such as Ctrl+C typed at the shell are signals sent to every process in
the terminal's foreground group (on Windows, to every process attached to
the console), which includes the desktop. While the shell runs, the desktop
catches them and does nothing (``_quiet_signals``), rather than ending or
stopping. They are caught, not ignored, because a signal ignored is ignored
by a child too, which would leave Ctrl+C dead in the shell; one caught goes
back to doing what it normally does in a child.

A shell with job control (bash, say) makes its own process group the
terminal's foreground group, and gives it back when it exits; should it not
have, the desktop takes it back (``_take_back_terminal``), or it would be
stopped as soon as it set the terminal up again.
"""

import os
import signal
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, TextIO

SUSPENDED_VARIABLE = "DASHA_SUSPENDED"
"""Set in the shell's environment, so that a desktop is not started inside
the command prompt of another."""

_QUIET_SIGNALS = ("SIGINT", "SIGQUIT", "SIGTSTP", "SIGBREAK")


def shell_command() -> list[str]:
    """The user's shell: ``COMSPEC`` on Windows, and ``SHELL`` elsewhere,
    falling back to ``cmd.exe`` and ``/bin/sh``."""
    # if/else (not an early return) lets mypy skip the other platform's branch.
    if sys.platform == "win32":  # pylint: disable=no-else-return
        return [os.environ.get("COMSPEC") or "cmd.exe"]
    else:
        return [os.environ.get("SHELL") or "/bin/sh"]


def run_shell(
    command: list[str] | None = None,
    stream: TextIO | None = None,
    *,
    name: str = "Dasha Desktop",
) -> int:
    """Run ``command`` (the user's shell, by default) in the foreground, on
    the terminal as it is, after saying how to come back to ``name`` (what
    the user knows the program as: ``PresentationManager.program_name``);
    returns its exit code. Raises ``OSError`` if it cannot be started."""
    stream = stream if stream is not None else sys.stdout
    stream.write(f"\n{name} is still running. Type exit to return to it.\n\n")
    stream.flush()
    environment = dict(os.environ)
    environment[SUSPENDED_VARIABLE] = "1"
    with _quiet_signals():
        try:
            return subprocess.run(
                command or shell_command(), env=environment, check=False
            ).returncode
        finally:
            _take_back_terminal()


def _do_nothing(number: int, frame: object) -> None:
    del number, frame


@contextmanager
def _quiet_signals() -> Iterator[None]:
    """While held, catch the signals that keys typed at the shell send, and
    do nothing with them (see the module's description)."""
    caught: dict[int, Any] = {}
    if threading.current_thread() is threading.main_thread():
        for name in _QUIET_SIGNALS:
            number = getattr(signal, name, None)
            if number is not None:
                try:
                    caught[number] = signal.signal(number, _do_nothing)
                except (OSError, ValueError):
                    pass
    try:
        yield
    finally:
        for number, handler in caught.items():
            signal.signal(number, handler)


def _take_back_terminal() -> None:
    """Make the desktop's process group the terminal's foreground group
    again, if the shell left it with another (see the module's
    description)."""
    if sys.platform != "win32":
        try:
            terminal = sys.stdin.fileno()
            if os.tcgetpgrp(terminal) == os.getpgrp():
                return
        except (AttributeError, ValueError, OSError):
            return  # not a terminal: nothing to take back
        # Asking from the background stops the asker, unless it ignores that.
        try:
            previous = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        except ValueError:
            return  # not the main thread, which is the one that runs the shell
        try:
            os.tcsetpgrp(terminal, os.getpgrp())
        except OSError:
            pass
        finally:
            signal.signal(signal.SIGTTOU, previous)
