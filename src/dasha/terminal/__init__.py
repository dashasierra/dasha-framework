"""Cross-platform full-screen terminal access.

``Terminal`` is a context manager. Entering it prepares the console (raw
input, and on Windows, support for ANSI output), switches to the alternate
screen, hides the cursor and (where it can) the terminal's scroll bar, and
turns on bracketed paste and mouse reporting. Leaving it, even because of
an exception, undoes all of this, so that the user's original screen and
shell come back untouched.

``Terminal.suspended`` gives the terminal back for a while (for a command
prompt, say) and then takes it again, as leaving and entering would.

``Terminal.wake``, called from any thread, cuts short a ``read`` that is
waiting for input, so that another thread can have the desktop's loop come
round (see ``PresentationManager.call_from_thread``).
"""

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
        """Wait (forever, or up to ``timeout`` seconds) and return input."""

    def wake(self) -> None:
        """Cut short a ``read`` that is waiting, from any thread."""

    @property
    def is_woken(self) -> bool:
        """Whether the last ``read`` ended early: woken, or resized."""

    def refit(self) -> None:
        """Fit the main screen to the window again, after a resize that
        set ``has_outgrown_window`` (only the Windows console sets it)."""


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
    """A full-screen session on the alternate screen of the current terminal."""

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
        """While held, give the terminal back as leaving does: the user's own
        screen and shell's settings return, for another program to use. Then
        take it again as entering does, onto a cleared alternate screen,
        even if that program failed. Whatever was drawn before is gone (the
        program may have used the alternate screen too), so everything must
        be drawn again."""
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
        """The terminal's current size, in columns and lines.

        Some terminals (serial lines and some SSH sessions) report a size of
        0x0, or no size at all; for those, the size falls back to the
        traditional 80x24.
        """
        try:
            columns, lines = os.get_terminal_size(self._stream.fileno())
        except (AttributeError, ValueError, OSError):
            columns = lines = 0
        return os.terminal_size(
            (columns or _FALLBACK_COLUMNS, lines or _FALLBACK_LINES)
        )

    def write(self, text: str) -> None:
        """Queue text (including escape sequences) for output. A character
        that the terminal's encoding cannot represent is sent as ``?``,
        rather than stopping the program."""
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
        """Whether releasing Space arrives as a ``KeyReleaseEvent``. On
        Windows, the console's input records report it; terminals on other
        systems, and over SSH, report only key presses."""
        return bool(getattr(self._console, "can_report_key_releases", False))

    def read(self, timeout: float | None = None) -> str:
        """Wait for input and return whatever is available.

        Waits indefinitely when ``timeout`` is ``None``, and otherwise for
        up to ``timeout`` seconds, returning ``""`` if nothing arrived. It
        also returns ``""`` early when the terminal is resized, or when
        ``wake`` is called.

        A resize can leave the classic Windows console's screen larger than
        its window, and drawing in the wrong place; the alternate screen is
        then entered afresh, which clears it (see ``take_cleared``).
        """
        text = self._console.read(timeout)
        if getattr(self._console, "has_outgrown_window", False):
            self._renew_screen()
        return text

    def _renew_screen(self) -> None:
        """Leave the alternate screen and enter it again, so that it fits
        the window once more, refitting the main screen in between."""
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
        """Whether the terminal cleared the screen by itself since this was
        last called (after a resize, say), so that everything must be drawn
        again."""
        cleared, self._cleared = self._cleared, False
        return cleared

    def wake(self) -> None:
        """Make a ``read`` that is waiting return ``""`` straight away (or,
        if none is, the next one). Safe to call from any thread, which is
        what it is for: another thread uses it to have the loop that reads
        input come round."""
        self._console.wake()

    @property
    def is_woken(self) -> bool:
        """Whether the last ``read`` returned early, because of ``wake`` or
        a resize, rather than because input arrived or time ran out. A wait
        for the rest of an escape sequence uses this to carry on waiting
        (see ``dasha.events.read_events``)."""
        return self._console.is_woken
