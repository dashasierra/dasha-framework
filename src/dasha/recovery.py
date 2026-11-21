"""Surviving errors in the desktop's own code."""

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
    """Reading or writing the terminal failed."""


class GuardedTerminal:
    """A terminal that raises ``TerminalFailed``.

    :param terminal: The terminal.
    """

    def __init__(self, terminal: Any) -> None:
        self._terminal = terminal

    def size(self) -> tuple[int, int]:
        """The terminal's size."""
        try:
            return self._terminal.size()  # type: ignore[no-any-return]
        except OSError as error:
            raise TerminalFailed(*error.args) from error

    def read(self, timeout: float | None = None) -> str:
        """Read input.

        :param timeout: Seconds to wait, or ``None`` for ever.
        """
        try:
            return self._terminal.read(timeout)  # type: ignore[no-any-return]
        except OSError as error:
            raise TerminalFailed(*error.args) from error

    def write(self, text: str) -> None:
        """Write output.

        :param text: The output.
        """
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
        """Give the terminal back for a while.

        :param suspended: Called while given back.
        """
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
    """Logs and counts the desktop's failures.

    :param folder: Log folder.
    :param name: The program's name.
    :param log_name: Start of the log's file name.
    """

    limit: int = 5
    """Failures in a row before giving up."""
    quiet: float = 60.0
    """Least seconds between unprompted error dialogs."""

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
        """Start of the log's file name."""
        self.name = name
        """The program's name."""
        self.log_path: Path | None = None
        """The log, once a failure has been written to it."""
        self.count = 0
        """How many failures there have been."""
        self._running: dict[str, int] = {}
        self._told: float | None = None

    def record(self, error: BaseException, kind: str | None = None) -> Path | None:
        """Log a failure; return the log, or ``None``.

        :param error: The exception.
        :param kind: Step kind, or ``None`` for input handling.
        """
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
        """Reset a step kind's failure run.

        :param kind: Step kind.
        """
        self._running.pop(kind, None)

    @property
    def has_too_many_failures(self) -> bool:
        """Whether a step kind failed ``limit`` times running."""
        return any(count >= self.limit for count in self._running.values())

    def should_tell(self, by_user: bool) -> bool:
        """Whether to tell the user of the latest failure.

        :param by_user: Whether the user's input caused it.
        """
        now = time.monotonic()
        if not by_user and self._told is not None and now - self._told < self.quiet:
            return False
        self._told = now
        return True

    def summary(self, gave_up: bool) -> str:
        """The closing summary of failures.

        :param gave_up: Whether the desktop gave up.
        """
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
