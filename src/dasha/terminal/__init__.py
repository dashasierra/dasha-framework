"""Cross-platform full-screen terminal access."""

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Protocol, Self, TextIO

from dasha.terminal import ansi

__all__ = ["Terminal", "ansi"]

_FALLBACK_COLUMNS = 80
_FALLBACK_LINES = 24


class _Console(Protocol):
    """What each platform backend provides."""

    def enable(self) -> None:
        """Prepare the console for full-screen use."""

    def restore(self) -> None:
        """Undo ``enable``."""

    def read(self, timeout: float | None = None) -> str:
        """Wait for and return input.

        :param timeout: Seconds to wait, or ``None`` for ever.
        """

    def wake(self) -> None:
        """Cut short a ``read`` that is waiting, from any thread."""

    @property
    def is_woken(self) -> bool:
        """Whether the last ``read`` ended early: woken, or resized."""

    def refit(self) -> None:
        """Refit the main screen to the window."""


def _make_console() -> _Console:
    # if/else (not an early return) lets mypy skip the other platform's branch.
    if sys.platform == "win32":  # pylint: disable=no-else-return
        from dasha.terminal._windows import (  # pylint: disable=import-outside-toplevel
            WindowsConsole,
        )

        return WindowsConsole()
    else:
        from dasha.terminal._posix import (  # pylint: disable=import-outside-toplevel
            PosixConsole,
        )

        return PosixConsole()


class Terminal:
    """A full-screen session on the alternate screen.

    :param stream: Output stream, or ``None`` for standard output.
    :param mouse: Whether to report the mouse.
    """

    def __init__(self, stream: TextIO | None = None, mouse: bool = True) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._console = _make_console()
        self.mouse = mouse
        """Whether to ask the terminal to report mouse activity."""
        # Whether it was asked, so leaving switches off exactly what entering
        # switched on, even if ``mouse`` changed in between.
        self._mouse_on = False
        self._cleared = False  # since take_cleared was last called

    def __enter__(self) -> Self:
        self._take()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._give_back()

    @contextmanager
    def suspended(self) -> Iterator[None]:
        """Give the terminal back while held."""
        self._give_back()
        try:
            yield
        finally:
            self._take()

    def _take(self) -> None:
        self._console.enable()
        self._mouse_on = self.mouse
        try:
            self.write(
                ansi.ENTER_ALT_SCREEN
                + ansi.HIDE_SCROLLBAR
                + ansi.HIDE_CURSOR
                + ansi.CLEAR_SCREEN
                + ansi.ENABLE_BRACKETED_PASTE
            )
            if self._mouse_on:
                self.write(ansi.ENABLE_MOUSE)
            self.flush()
        except BaseException:
            self._console.restore()
            raise

    def _give_back(self) -> None:
        try:
            if self._mouse_on:
                self.write(ansi.DISABLE_MOUSE)
            self.write(
                ansi.DISABLE_BRACKETED_PASTE
                + ansi.RESET_ATTRIBUTES
                + ansi.SHOW_CURSOR
                + ansi.LEAVE_ALT_SCREEN
                + ansi.RESTORE_SCROLLBAR
            )
            self.flush()
        finally:
            self._console.restore()

    def size(self) -> os.terminal_size:
        """The terminal's (columns, lines)."""
        try:
            columns, lines = os.get_terminal_size(self._stream.fileno())
        except (AttributeError, ValueError, OSError):
            columns = lines = 0
        return os.terminal_size(
            (columns or _FALLBACK_COLUMNS, lines or _FALLBACK_LINES)
        )

    def write(self, text: str) -> None:
        """Queue text for output.

        :param text: The text.
        """
        try:
            self._stream.write(text)
        except UnicodeEncodeError:
            encoding = getattr(self._stream, "encoding", None) or "utf-8"
            safe = text.encode(encoding, "replace").decode(encoding, "replace")
            self._stream.write(safe)

    def flush(self) -> None:
        """Send queued output to the terminal."""
        self._stream.flush()

    @property
    def can_report_key_releases(self) -> bool:
        """Whether Space releases are reported."""
        return bool(getattr(self._console, "can_report_key_releases", False))

    def read(self, timeout: float | None = None) -> str:
        """Wait for and return input.

        :param timeout: Seconds to wait, or ``None`` for ever.
        """
        text = self._console.read(timeout)
        if getattr(self._console, "has_outgrown_window", False):
            self._renew_screen()
        return text

    def _renew_screen(self) -> None:
        """Re-enter the alternate screen to fit the window."""
        self.write(ansi.LEAVE_ALT_SCREEN)
        self.flush()
        self._console.refit()
        self.write(
            ansi.ENTER_ALT_SCREEN
            + ansi.HIDE_CURSOR
            + ansi.CLEAR_SCREEN
            + ansi.ENABLE_BRACKETED_PASTE
        )
        if self._mouse_on:
            self.write(ansi.ENABLE_MOUSE)
        self.flush()
        self._cleared = True

    def take_cleared(self) -> bool:
        """Whether the terminal cleared the screen since last asked."""
        cleared, self._cleared = self._cleared, False
        return cleared

    def wake(self) -> None:
        """Make a waiting ``read`` return; thread-safe."""
        self._console.wake()

    @property
    def is_woken(self) -> bool:
        """Whether the last ``read`` was woken early."""
        return self._console.is_woken
