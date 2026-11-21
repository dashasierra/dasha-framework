"""Common pseudo-terminal behaviour."""

import os
import queue
import shutil
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence

READ_SIZE = 65536
"""The most bytes read from the program at once."""

KILL_DELAY = 2.0
"""Seconds before a closing program is killed."""


class PseudoTerminal(ABC):
    """A program in a pseudo-terminal."""

    def __init__(self) -> None:
        self.on_output: Callable[[bytes], None] = lambda data: None
        """Called with each piece of output."""
        self.on_exit: Callable[[], None] = lambda: None
        """Called once the program ends."""
        self.pid: int | None = None
        """The program's process id, once it has started."""
        self.exit_code: int | None = None
        """Exit code, once ended."""
        self._writes: queue.SimpleQueue[bytes | None] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._finished = threading.Event()

    @property
    def is_running(self) -> bool:
        """Whether the program has started and not yet ended."""
        return self.pid is not None and not self._finished.is_set()

    def start(
        self,
        argv: Sequence[str],
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        size: tuple[int, int] = (80, 24),
    ) -> None:
        """Start a program.

        :param argv: The program and its arguments.
        :param cwd: Working folder, or ``None`` for this one.
        :param env: Environment, or ``None`` for this process's.
        :param size: Terminal (columns, lines).
        """
        if not argv:
            raise ValueError("no program to run")
        if self.pid is not None:
            raise RuntimeError("a pseudo-terminal runs one program")
        columns, lines = max(1, size[0]), max(1, size[1])
        self._spawn(list(argv), cwd, env, (columns, lines))
        threading.Thread(target=self._read_all, daemon=True).start()
        threading.Thread(target=self._write_all, daemon=True).start()

    def write(self, data: bytes) -> None:
        """Send input to the program.

        :param data: The input.
        """
        if data and self.is_running:
            self._writes.put(data)

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the program to end; return whether it has.

        :param timeout: Seconds to wait, or ``None`` for ever.
        """
        return self._finished.wait(timeout)

    def _read_all(self) -> None:
        """Read output until the program ends."""
        try:
            while data := self._read():
                self.on_output(data)
        finally:
            self.exit_code = self._reap()
            self._writes.put(None)  # the writing thread ends, and tidies up
            self._finished.set()
            self.on_exit()

    def _write_all(self) -> None:
        """The writing thread: input to the program, until the end."""
        while (data := self._writes.get()) is not None:
            try:
                self._write(data)
            except OSError:
                pass  # it has gone (or is going); the reader will see
        with self._lock:
            self._release()

    # What each system does

    @abstractmethod
    def _spawn(
        self,
        argv: list[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        size: tuple[int, int],
    ) -> None:
        """Start the program.

        :param argv: The program and its arguments.
        :param cwd: Working folder, or ``None`` for this one.
        :param env: Environment, or ``None`` for this process's.
        :param size: Terminal (columns, lines).
        """

    @abstractmethod
    def _read(self) -> bytes:
        """The next output (waiting for it); ``b""`` once there is none."""

    @abstractmethod
    def _write(self, data: bytes) -> None:
        """Write all input to the program.

        :param data: The input.
        """

    @abstractmethod
    def _reap(self) -> int | None:
        """Once the output has ended: the exit code."""

    @abstractmethod
    def _release(self) -> None:
        """Close whatever is left open, with ``_lock`` held."""

    @abstractmethod
    def resize(self, columns: int, lines: int) -> None:
        """Resize the terminal.

        :param columns: New width.
        :param lines: New height.
        """

    @abstractmethod
    def close(self) -> None:
        """End the program."""

    def foreground_busy(self) -> bool:
        """Whether a foreground child is running."""
        return False


def find_program(argv: Sequence[str], env: Mapping[str, str] | None) -> None:
    """Raise ``FileNotFoundError`` if the program is missing.

    :param argv: The program and its arguments.
    :param env: Environment, or ``None`` for this process's.
    """
    path = (os.environ if env is None else env).get("PATH")
    if shutil.which(argv[0], path=path) is None:
        raise FileNotFoundError(2, "No such program", argv[0])
