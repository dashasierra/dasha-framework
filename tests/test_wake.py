"""Tests for waking the loop from another thread."""

import os
import sys
import threading
import time
import unittest
from collections.abc import Callable
from functools import partial
from typing import cast
from unittest import mock

from dasha.client import ClientManager
from dasha.events import InputDecoder, read_events
from dasha.manager import PresentationManager
from dasha.protocol import send
from dasha.terminal import Terminal
from tests.test_hosting import WELCOME
from tests.support import pipe

PATIENCE = 5.0
"""Seconds to wait before failing."""


class WakeableTerminal:
    """A terminal whose ``read`` waits until woken."""

    def __init__(self) -> None:
        self.screen_size = (80, 24)
        self._woken = threading.Event()
        self.is_woken = False
        self.timed_out = False

    def size(self) -> tuple[int, int]:
        """The screen's size, as a terminal reports it."""
        return self.screen_size

    def write(self, text: str) -> None:
        """Drop output.

        :param text: The output.
        """
        del text

    def flush(self) -> None:
        """Nothing to flush."""

    def read(self, timeout: float | None = None) -> str:
        """Wait for a wake or the timeout.

        :param timeout: Seconds to wait, at most ``PATIENCE``.
        """
        limit = PATIENCE if timeout is None else min(timeout, PATIENCE)
        self.is_woken = self._woken.wait(limit)
        self._woken.clear()
        if not self.is_woken and (timeout is None or timeout >= PATIENCE):
            self.timed_out = True
        return ""

    def wake(self) -> None:
        """End the wait, from any thread."""
        self._woken.set()


def later(action: Callable[[], object], delay: float = 0.05) -> threading.Thread:
    """Do an action on a thread after a delay.

    :param action: The action.
    :param delay: Seconds to wait.
    """

    def run() -> None:
        time.sleep(delay)
        action()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


class ManagerTests(unittest.TestCase):
    """``call_from_thread`` on a desktop of its own."""

    def test_wakes_the_loop_and_calls_on_its_thread(self) -> None:
        """Wakes the loop and calls on its thread."""
        manager = PresentationManager()
        terminal = WakeableTerminal()
        called: list[int] = []

        def callback() -> None:
            called.append(threading.get_ident())
            manager.quit()

        later(lambda: manager.call_from_thread(callback))
        started = time.monotonic()
        manager.run(cast(Terminal, terminal))
        self.assertEqual(called, [threading.get_ident()])
        self.assertFalse(terminal.timed_out)
        self.assertLess(time.monotonic() - started, PATIENCE / 2)

    def test_in_order_and_once(self) -> None:
        """Callbacks run in order; one added by a callback waits a pass."""
        manager = PresentationManager()
        calls: list[str] = []

        def first() -> None:
            calls.append("first")
            manager.call_from_thread(third)

        def third() -> None:
            calls.append("third")
            manager.quit()

        manager.call_from_thread(first)
        manager.call_from_thread(lambda: calls.append("second"))
        manager.run(cast(Terminal, WakeableTerminal()))
        self.assertEqual(calls, ["first", "second", "third"])

    def test_without_wake_waits_for_input(self) -> None:
        """Without wake, waits for input."""
        manager = PresentationManager()
        calls: list[str] = []
        manager.call_from_thread(lambda: calls.append("called"))
        manager.call_from_thread(manager.quit)

        class Plain:  # pylint: disable=too-few-public-methods
            """A terminal without ``wake``."""

            def size(self) -> tuple[int, int]:
                """A fixed size."""
                return (80, 24)

            def write(self, text: str) -> None:
                """Drop output.

                :param text: The output.
                """
                del text

            def flush(self) -> None:
                """Nothing to flush."""

            def read(self, timeout: float | None = None) -> str:
                """A key press, at once.

                :param timeout: Ignored.
                """
                del timeout
                return "z"

        manager.wake()  # not running: nothing to wake
        manager.run(cast(Terminal, Plain()))
        self.assertEqual(calls, ["called"])


class ClientTests(unittest.TestCase):
    """``call_from_thread`` in an application hosted by a desktop."""

    def test_wakes_the_wait_for_messages(self) -> None:
        """The wait for the desktop's next message is cut short."""
        desktop, app_end = pipe()
        manager = ClientManager(app_end, WELCOME)
        self.addCleanup(manager.stop_listening)
        called: list[int] = []
        later(lambda: manager.call_from_thread(lambda: called.append(1)))
        # Should the wake fail, a ping ends the wait, and the test fails.
        rescue = threading.Timer(PATIENCE, lambda: send(desktop, "ping"))
        rescue.start()
        self.addCleanup(rescue.cancel)
        started = time.monotonic()
        manager.pump()
        self.assertEqual(called, [1])
        self.assertLess(time.monotonic() - started, PATIENCE / 2)

    def test_many_wakes_are_one(self) -> None:
        """Wake-ups before the loop comes round are sent once."""
        _, app_end = pipe()
        manager = ClientManager(app_end, WELCOME)
        self.addCleanup(manager.stop_listening)
        called: list[int] = []
        for number in range(50):
            manager.call_from_thread(partial(called.append, number))
        manager.pump()
        self.assertEqual(called, list(range(50)))
        # The pipe is empty again: the next wait is not cut short.
        waker = manager._waker  # pylint: disable=protected-access
        self.assertFalse(waker.reader.poll())


class ScriptedReader:  # pylint: disable=too-few-public-methods
    """Scripted reads; ``None`` is a woken empty read.

    :param inputs: The reads.
    """

    def __init__(self, inputs: list[str | None]) -> None:
        self.inputs = inputs
        self.is_woken = False

    def read(self, timeout: float | None = None) -> str:
        """The next scripted input.

        :param timeout: Ignored.
        """
        del timeout
        data = self.inputs.pop(0)
        self.is_woken = data is None
        return data or ""


class EscapeTests(unittest.TestCase):
    """A wake does not split an escape sequence."""

    def test_woken_waits_for_the_rest(self) -> None:
        """Woken after ESC, the read waits again, and the rest arrives."""
        reader = ScriptedReader(["\x1b", None, None, "[A"])
        self.assertEqual(read_events(reader, InputDecoder(), 10.0), ["up"])

    def test_timed_out_is_the_escape_key(self) -> None:
        """An empty read that was not woken still ends the wait."""
        reader = ScriptedReader(["\x1b", "", "[A"])
        self.assertEqual(read_events(reader, InputDecoder(), 10.0), ["escape"])

    def test_woken_wait_still_ends(self) -> None:
        """A woken wait still ends."""
        reader = ScriptedReader(["\x1b"] + [None] * 1000)
        self.assertEqual(read_events(reader, InputDecoder(), 0.0), ["escape"])


class TerminalTests(unittest.TestCase):
    """``Terminal.wake`` passes to the console."""

    def test_wake_and_woken(self) -> None:
        """The wrapper asks the console."""
        console = mock.Mock(is_woken=True)
        with mock.patch("dasha.terminal._make_console", return_value=console):
            terminal = Terminal()
        terminal.wake()
        console.wake.assert_called_once_with()
        self.assertTrue(terminal.is_woken)


if sys.platform != "win32":
    from dasha.terminal._posix import PosixConsole

    class PosixConsoleTests(unittest.TestCase):
        """The POSIX console, on a pseudo-terminal of its own."""

        def test_wake_ends_a_read(self) -> None:
            """A read waiting forever ends when another thread wakes it."""
            main, other = os.openpty()  # pylint: disable=no-member
            self.addCleanup(os.close, main)
            self.addCleanup(os.close, other)
            stdin = mock.Mock()
            stdin.fileno.return_value = other
            with mock.patch("sys.stdin", stdin):
                console = PosixConsole()
            console.enable()
            self.addCleanup(console.restore)
            later(console.wake)
            started = time.monotonic()
            self.assertEqual(console.read(PATIENCE), "")
            self.assertTrue(console.is_woken)
            self.assertLess(time.monotonic() - started, PATIENCE / 2)
            os.write(main, b"x")
            self.assertEqual(console.read(PATIENCE), "x")
            self.assertFalse(console.is_woken)

        def test_wake_when_not_enabled(self) -> None:
            """Waking a console that is not enabled does nothing."""
            PosixConsole().wake()

else:
    import ctypes

    from dasha.terminal import _windows

    class WindowsConsoleTests(unittest.TestCase):
        """The Windows console's wait, woken by its event."""

        def test_wake_ends_a_read(self) -> None:
            """A read waiting forever ends when another thread wakes it."""
            # pylint: disable=protected-access
            console = _windows.WindowsConsole()
            # No input ever arrives: an event never set stands in for it.
            quiet = _windows._CreateEventW(None, True, False, None)
            self.addCleanup(ctypes.windll.kernel32.CloseHandle, quiet)
            console._input = quiet
            later(console.wake)
            started = time.monotonic()
            self.assertEqual(console.read(PATIENCE), "")
            self.assertTrue(console.is_woken)
            self.assertLess(time.monotonic() - started, PATIENCE / 2)
            self.assertEqual(console.read(0.05), "")
            self.assertFalse(console.is_woken)


if __name__ == "__main__":
    unittest.main()
