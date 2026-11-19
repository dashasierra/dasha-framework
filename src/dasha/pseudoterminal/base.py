"""What every pseudo-terminal has in common (see ``dasha.pseudoterminal``):
the threads that read the program's output and write its input, and the
hooks each system fills in."""

import os
import queue
import shutil
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence

READ_SIZE = 65536
"""The most bytes read from the program at once."""

KILL_DELAY = 2.0
"""How many seconds a program has, once asked to end (``close``), before
it is made to."""


class PseudoTerminal(ABC):
    """A program running in a pseudo-terminal: what is common to every
    system. Use ``open_pty`` for the one for this system."""

    def __init__(self) -> None:
        self.on_output: Callable[[bytes], None] = lambda data: None
        """Called with each piece of the program's output, from the thread
        that reads it."""
        self.on_exit: Callable[[], None] = lambda: None
        """Called once the program has ended and all its output has been
        given to ``on_output``, from the same thread."""
        self.pid: int | None = None
        """The program's process id, once it has started."""
        self.exit_code: int | None = None
        """How the program ended, once it has: its exit code (on POSIX,
        minus the signal number, if a signal ended it)."""
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
        """Start ``argv`` (a program, found on ``PATH``, and its arguments)
        in a pseudo-terminal of ``size`` (columns, lines), in the folder
        ``cwd`` (this one, if ``None``) with the environment ``env`` (this
        process's, if ``None``). Raises ``OSError`` if it cannot be
        started."""
        if not argv:
            raise ValueError("no program to run")
        if self.pid is not None:
            raise RuntimeError("a pseudo-terminal runs one program")
        columns, lines = max(1, size[0]), max(1, size[1])
        self._spawn(list(argv), cwd, env, (columns, lines))
        threading.Thread(target=self._read_all, daemon=True).start()
        threading.Thread(target=self._write_all, daemon=True).start()

    def write(self, data: bytes) -> None:
        """Send input to the program, as though typed. It goes in the order
        given, from another thread; once the program has ended, it is
        dropped."""
        if data and self.is_running:
            self._writes.put(data)

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the program to end and its output to be read (forever,
        or up to ``timeout`` seconds); returns whether it has."""
        return self._finished.wait(timeout)

    def _read_all(self) -> None:
        """The reading thread: output to ``on_output`` until there is no
        more, then the ending."""
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
        """Start the program (see ``start``)."""

    @abstractmethod
    def _read(self) -> bytes:
        """The next output (waiting for it); ``b""`` once there is none."""

    @abstractmethod
    def _write(self, data: bytes) -> None:
        """Write input to the program, all of it."""

    @abstractmethod
    def _reap(self) -> int | None:
        """Once the output has ended: the exit code."""

    @abstractmethod
    def _release(self) -> None:
        """Close whatever is left open, with ``_lock`` held."""

    @abstractmethod
    def resize(self, columns: int, lines: int) -> None:
        """Tell the program its terminal is now ``columns`` by ``lines``."""

    @abstractmethod
    def close(self) -> None:
        """End the program, if it is still running: ask it to end, and force
        it to if it has not ended after ``KILL_DELAY`` seconds. Its ending
        is reported as usual."""

    def foreground_busy(self) -> bool:
        """Whether the program has started another that is running in the
        foreground (a shell running a command, say), as far as can be
        told."""
        return False


def find_program(argv: Sequence[str], env: Mapping[str, str] | None) -> None:
    """Raise ``FileNotFoundError`` if the program ``argv`` starts with is
    not there (found as the program would be: on ``PATH``, if it is a bare
    name)."""
    path = (os.environ if env is None else env).get("PATH")
    if shutil.which(argv[0], path=path) is None:
        raise FileNotFoundError(2, "No such program", argv[0])
