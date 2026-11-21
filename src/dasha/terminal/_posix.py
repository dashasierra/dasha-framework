"""POSIX terminal backend."""

import codecs
import os
import select
import signal
import sys
import termios  # pylint: disable=import-error  # absent on Windows
import threading
import tty
from collections.abc import Callable
from types import FrameType
from typing import Any

assert sys.platform != "win32"  # lets mypy skip this module on Windows

type _SignalHandler = Callable[
    [int, FrameType | None], Any
] | int | signal.Handlers | None


class PosixConsole:
    """Puts the controlling terminal into raw mode and watches for resizes."""

    def __init__(self) -> None:
        self._fd = sys.stdin.fileno()
        self._saved_attributes: list[int | list[bytes | int]] | None = None
        # Incremental, so a UTF-8 character split across reads decodes correctly.
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._wake_read: int | None = None
        self._wake_write: int | None = None
        self._watching_resizes = False
        self._saved_handler: _SignalHandler = None
        # Held while wake writes to the pipe, so restore cannot close it
        # (and its number go to another file) part-way through.
        self._wake_lock = threading.Lock()
        self.is_woken = False
        """Whether the last ``read`` ended early: woken, or resized."""

    def enable(self) -> None:
        """Switch input to raw mode: no line buffering, echo or signal keys."""
        self._saved_attributes = termios.tcgetattr(self._fd)
        tty.setraw(self._fd, termios.TCSANOW)
        self._watch_resizes()

    def _watch_resizes(self) -> None:
        self._wake_read, self._wake_write = os.pipe()
        os.set_blocking(self._wake_read, False)
        os.set_blocking(self._wake_write, False)
        try:
            self._saved_handler = signal.signal(
                signal.SIGWINCH, self._on_resize  # pylint: disable=no-member
            )
            self._watching_resizes = True
        except ValueError:
            # Signal handlers can only be set from the main thread. Without one,
            # resizes are still picked up at the next input.
            pass

    def _on_resize(self, signum: int, frame: FrameType | None) -> None:
        del signum, frame
        if self._wake_write is not None:
            try:
                os.write(self._wake_write, b"\0")
            except BlockingIOError:
                pass  # a wake-up is already waiting

    def restore(self) -> None:
        """Put the terminal back the way ``enable`` found it."""
        if self._watching_resizes:
            signal.signal(signal.SIGWINCH, self._saved_handler)
            self._watching_resizes = False
        with self._wake_lock:
            for fd in (self._wake_read, self._wake_write):
                if fd is not None:
                    os.close(fd)
            self._wake_read = self._wake_write = None
        if self._saved_attributes is not None:
            # TCSAFLUSH also discards unread input so it does not reach the shell.
            termios.tcsetattr(self._fd, termios.TCSAFLUSH, self._saved_attributes)
            self._saved_attributes = None

    def _drain_wake_pipe(self) -> None:
        if self._wake_read is None:
            return
        try:
            while os.read(self._wake_read, 64):
                pass
        except BlockingIOError:
            pass

    def wake(self) -> None:
        """Make a waiting ``read`` return; thread-safe."""
        with self._wake_lock:
            if self._wake_write is None:
                return
            try:
                os.write(self._wake_write, b"\0")
            except BlockingIOError:
                pass  # a wake-up is already waiting

    def read(self, timeout: float | None = None) -> str:
        """Wait for and return input.

        :param timeout: Seconds to wait, or ``None`` for ever.
        """
        watched = [self._fd]
        if self._wake_read is not None:
            watched.append(self._wake_read)
        ready = select.select(watched, [], [], timeout)[0]
        self.is_woken = self._wake_read in ready
        if self.is_woken:
            self._drain_wake_pipe()
        if self._fd not in ready:
            return ""
        return self._decoder.decode(os.read(self._fd, 4096))

    def refit(self) -> None:
        """Nothing to do: a terminal's screen always fits its window."""
