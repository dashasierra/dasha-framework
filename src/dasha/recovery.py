"""Failing softly: what the desktop does when its own code goes wrong.

No program is free of bugs, and before this an unexpected exception in the
desktop's own code (a menu action, a dialog, Settings..., a widget, a
timer) ended the desktop, and with it every application and their unsaved
work. With ``PresentationManager.survive_errors`` on, as it is when
Dasha Framework is started from the command line or an application runs on its
own, each step of the desktop's loop (handling one event, running the
timers, taking in applications' messages, drawing a frame) is guarded
instead. When a step fails:

1. The traceback is written to a log (``Recovery.record``), in
   ``~/.dasha/logs/`` beside the applications' logs.
2. Whatever was under way is put aside: an open menu is closed, and a drag,
   a move or resize from the keyboard and an animation are ended, and the
   whole screen is drawn afresh.
3. The user is told, in a dialog, that something went wrong but that their
   applications are still running, and where the log is: every time for a
   failure the user caused (handling a key, a click or a paste), and at most
   once every ``Recovery.quiet`` seconds (a minute) for one that happened
   by itself (drawing, the timers, applications' messages), so that a bug
   that comes and goes cannot bury the screen in dialogs. Every failure is
   logged all the same.
4. The desktop carries on.

A step that fails every time, with no success in between (drawing, say, so
that every frame fails), would make that go on for ever, so ``Recovery``
counts each kind of step's failures in a row: once one kind has failed
``Recovery.limit`` times running, the desktop gives up and shuts down as it
would for Exit, without asking, and the command line says where the log
is. A step that fails only now and then never makes it give up, nor does a
failure the user caused, as the user is told of each before going on (a
widget whose keys fail does not shut the desktop down after a few
keystrokes); the error dialog failing in turn does count.

What is never caught: ``KeyboardInterrupt`` and ``SystemExit`` (ending the
desktop on purpose, as SIGTERM does), and ``TerminalFailed``, a failure to
read or write the terminal itself, after which there is no screen to
recover on. Those end the desktop as before.

A failed step may have left something half done, which is why the message
suggests saving work and restarting if anything looks wrong, rather than
claiming all is well.
"""

import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from dasha import logs


class TerminalFailed(OSError):
    """Reading or writing the terminal failed (an SSH connection dropping,
    say). Raised in place of the original ``OSError``, with the same
    details, so that guarded steps let it through."""


class GuardedTerminal:
    """A terminal whose failures are ``TerminalFailed``, so that they are
    told apart from failures in the desktop's own code. Everything else is
    the terminal's own."""

    def __init__(self, terminal: Any) -> None:
        self._terminal = terminal

    def size(self) -> tuple[int, int]:
        """The terminal's size."""
        try:
            return self._terminal.size()  # type: ignore[no-any-return]
        except OSError as error:
            raise TerminalFailed(*error.args) from error

    def read(self, timeout: float | None = None) -> str:
        """Read input, as the terminal does."""
        try:
            return self._terminal.read(timeout)  # type: ignore[no-any-return]
        except OSError as error:
            raise TerminalFailed(*error.args) from error

    def write(self, text: str) -> None:
        """Write output, as the terminal does."""
        try:
            self._terminal.write(text)
        except OSError as error:
            raise TerminalFailed(*error.args) from error

    def flush(self) -> None:
        """Flush output, as the terminal does."""
        try:
            self._terminal.flush()
        except OSError as error:
            raise TerminalFailed(*error.args) from error

    @contextmanager
    def _suspended(self, suspended: Callable[[], Any]) -> Iterator[None]:
        """Give the terminal back for a while, as its ``suspended`` does.
        Failing to give it back or take it again is ``TerminalFailed``; a
        failure while it is given back is not the terminal's, and stays as
        it is."""
        # Entered and left by hand, so that only those count as the
        # terminal failing, not what goes on in between.
        held = suspended()
        with _as_terminal_failure():
            held.__enter__()  # pylint: disable=unnecessary-dunder-call
        failure: BaseException | None = None
        try:
            yield
        except BaseException as error:
            failure = error
            raise
        finally:
            with _as_terminal_failure():
                if failure is None:
                    held.__exit__(None, None, None)
                else:
                    held.__exit__(type(failure), failure, failure.__traceback__)

    def __getattr__(self, name: str) -> Any:
        found = getattr(self._terminal, name)
        if name == "suspended":  # only where the terminal has it
            return partial(self._suspended, found)
        return found


@contextmanager
def _as_terminal_failure() -> Iterator[None]:
    try:
        yield
    except OSError as error:
        raise TerminalFailed(*error.args) from error


class Recovery:
    """Records the desktop's failures in a log, and counts them, to give up
    when a step fails every time (see the module's description)."""

    limit: int = 5
    """How many failures in a row of one kind of step, with no success in
    between, make the desktop give up."""
    quiet: float = 60.0
    """The fewest seconds between telling the user of failures that happened
    by themselves (not handling their input)."""

    def __init__(
        self,
        folder: Path = logs.LOG_FOLDER,
        *,
        name: str = "Dasha Desktop",
        log_name: str = "desktop",
    ) -> None:
        self.folder = folder
        """The folder the log is written in."""
        self.log_name = log_name
        """The start of the log's file name, before the time it was made
        (``desktop-20261114-162427.log``)."""
        self.name = name
        """What the user knows the program as, which the message names
        (``PresentationManager.program_name``)."""
        self.log_path: Path | None = None
        """The log, once a failure has been written to it."""
        self.count = 0
        """How many failures there have been."""
        self._running: dict[str, int] = {}
        self._told: float | None = None

    def record(self, error: BaseException, kind: str | None = None) -> Path | None:
        """Write a failure's traceback to the log (made on the first
        failure, one for each time the desktop runs), and count it. ``kind``
        is the kind of step that failed by itself (``"drawing"``, say), whose
        failures in a row count towards giving up (``has_too_many_failures``); ``None``
        for one handling the user's input. Returns the log, or ``None`` if it
        could not be written."""
        self.count += 1
        if kind is not None:
            self._running[kind] = self._running.get(kind, 0) + 1
        stamp = datetime.now()
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            if self.log_path is None:
                when = f"{stamp:%Y%m%d-%H%M%S}"
                self.log_path = self.folder / f"{self.log_name}-{when}.log"
                logs.prune(self.folder)
            with open(self.log_path, "a", encoding="utf-8") as log:
                log.write(f"--- {stamp:%Y-%m-%d %H:%M:%S}\n")
                log.write("".join(traceback.format_exception(error)))
        except OSError:
            return None
        return self.log_path

    def succeeded(self, kind: str) -> None:
        """A step of this kind went well: its failures are no longer in a
        row."""
        self._running.pop(kind, None)

    @property
    def has_too_many_failures(self) -> bool:
        """Whether one kind of step has failed ``limit`` times in a row, so
        that carrying on is no use."""
        return any(count >= self.limit for count in self._running.values())

    def should_tell(self, by_user: bool) -> bool:
        """Whether to tell the user of the failure just recorded: always for
        one they caused (``by_user``), otherwise only if they have not been
        told of one in the last ``quiet`` seconds."""
        now = time.monotonic()
        if not by_user and self._told is not None and now - self._told < self.quiet:
            return False
        self._told = now
        return True

    def summary(self, gave_up: bool) -> str:
        """What is said once the screen has been given back: how often
        something went wrong (or that the desktop gave up), and where the log
        is."""
        where = f"see {self.log_path}" if self.log_path else "it could not be logged"
        if gave_up:
            return f"stopped, as something kept going wrong ({where})"
        times = "once" if self.count == 1 else f"{self.count} times"
        return f"something went wrong {times} ({where})"

    @property
    def message(self) -> str:
        """What the user is told about a failure."""
        where = (
            f"The details are in {self.log_path.name}, in\n{self.log_path.parent}."
            if self.log_path is not None
            else "The details could not be written to a log."
        )
        return (
            f"Something went wrong in {self.name}, but\n"
            "everything is still running. If anything looks\n"
            f"wrong, save your work and restart {self.name}.\n\n" + where
        )
