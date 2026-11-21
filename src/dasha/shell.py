"""The command prompt: the user's shell while the desktop waits."""

import os
import signal
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, TextIO

SUSPENDED_VARIABLE = "DASHA_SUSPENDED"
"""Environment variable marking the command prompt."""

_QUIET_SIGNALS = ("SIGINT", "SIGQUIT", "SIGTSTP", "SIGBREAK")


def shell_command() -> list[str]:
    """The user's shell command."""
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
    """Run the shell in the foreground; return its exit code.

    :param command: Command to run, or ``None`` for the shell.
    :param stream: Where to print the note, or ``None`` for standard output.
    :param name: The program's name.
    """
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
    """Catch and ignore terminal signals while held."""
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
    """Take back the terminal's foreground group."""
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
