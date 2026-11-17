"""The POSIX pseudo-terminal (Linux, macOS): ``os.forkpty``."""

import errno
import os
import signal
import sys
import termios  # pylint: disable=import-error  # absent on Windows
import threading
import warnings
from collections.abc import Mapping

from dasha.pseudoterminal.base import (
    KILL_DELAY,
    READ_SIZE,
    PseudoTerminal,
    find_program,
)

assert sys.platform != "win32"  # lets mypy skip this module on Windows


class PosixPty(PseudoTerminal):
    """A pseudo-terminal on Linux and macOS: ``os.forkpty``, whose child
    becomes the program, with the pseudo-terminal as its controlling
    terminal (so that Ctrl+C, job control and resizes work)."""

    def __init__(self) -> None:
        super().__init__()
        self._fd: int | None = None
        self._killer: threading.Timer | None = None

    def _spawn(
        self,
        argv: list[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        size: tuple[int, int],
    ) -> None:
        environment = dict(os.environ if env is None else env)
        environment["TERM"] = "xterm-256color"
        environment["COLORTERM"] = "truecolor"
        for name in ("LINES", "COLUMNS"):
            environment.pop(name, None)
        find_program(argv, environment)
        if cwd is not None and not os.path.isdir(cwd):
            raise NotADirectoryError(20, "Not a folder", cwd)
        with warnings.catch_warnings():
            # Forking with other threads running is warned against, as
            # the child could find a lock held. The child only execs.
            warnings.simplefilter("ignore", DeprecationWarning)
            pid, fd = os.forkpty()  # pylint: disable=no-member
        if pid == 0:  # the child
            try:
                termios.tcsetwinsize(0, (size[1], size[0]))
                if cwd is not None:
                    os.chdir(cwd)
                os.execvpe(argv[0], argv, environment)
            except BaseException as error:  # pylint: disable=broad-exception-caught
                os.write(2, f"{argv[0]}: {error}\r\n".encode(errors="replace"))
            finally:
                os._exit(127)  # pylint: disable=protected-access
        self.pid, self._fd = pid, fd

    def _read(self) -> bytes:
        assert self._fd is not None
        try:
            return os.read(self._fd, READ_SIZE)
        except OSError as error:
            if error.errno == errno.EIO:  # the child's side has closed
                return b""
            raise

    def _write(self, data: bytes) -> None:
        assert self._fd is not None
        view = memoryview(data)
        while view:
            view = view[os.write(self._fd, view) :]

    def _reap(self) -> int | None:
        if self._killer is not None:
            self._killer.cancel()
        assert self.pid is not None
        try:
            _, status = os.waitpid(self.pid, 0)
        except ChildProcessError:
            return None
        return os.waitstatus_to_exitcode(status)

    def _release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def resize(self, columns: int, lines: int) -> None:
        with self._lock:
            if self._fd is not None:
                try:
                    termios.tcsetwinsize(self._fd, (max(1, lines), max(1, columns)))
                except OSError:
                    pass  # ending

    def close(self) -> None:
        if not self.is_running:
            return
        self._signal(signal.SIGHUP)  # pylint: disable=no-member
        if self._killer is None:
            self._killer = threading.Timer(
                KILL_DELAY,
                self._signal,
                args=(signal.SIGKILL,),  # pylint: disable=no-member
            )
            self._killer.daemon = True
            self._killer.start()

    def _signal(self, number: int) -> None:
        """Send a signal to the program and everything in its process
        group (which it leads)."""
        if self.pid is None or not self.is_running:
            return
        try:
            os.killpg(self.pid, number)  # pylint: disable=no-member
        except (ProcessLookupError, PermissionError):
            pass

    def foreground_busy(self) -> bool:
        with self._lock:
            if self._fd is None or not self.is_running:
                return False
            try:
                group = os.tcgetpgrp(self._fd)  # pylint: disable=no-member
                return group != self.pid
            except OSError:
                return False
