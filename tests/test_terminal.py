"""Tests for the cross-platform Terminal wrapper, using a fake console."""

import os
import unittest
from io import StringIO
from unittest.mock import patch

from dasha.terminal import Terminal, ansi


class FakeConsole:
    """Records calls instead of touching a real console."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.has_outgrown_window = False
        self.stream: StringIO | None = None
        self.output_at_refit = ""  # what had been written when refit came

    def enable(self) -> None:
        """Record that the console was enabled."""
        self.calls.append("enable")

    def restore(self) -> None:
        """Record that the console was restored."""
        self.calls.append("restore")

    def read(self, timeout: float | None = None) -> str:
        """Pretend the user pressed ``q``."""
        self.calls.append(f"read({timeout})")
        return "q"

    def refit(self) -> None:
        """Record the refit, and what had been written by then."""
        self.calls.append("refit")
        self.has_outgrown_window = False
        if self.stream is not None:
            self.output_at_refit = self.stream.getvalue()


class TerminalTests(unittest.TestCase):
    """Terminal must always leave the user's terminal as it found it."""

    def setUp(self) -> None:
        self.console = FakeConsole()
        patcher = patch("dasha.terminal._make_console", return_value=self.console)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.stream = StringIO()

    def test_enters_and_leaves_alternate_screen(self) -> None:
        """The alternate screen is entered on enter and left on exit."""
        with Terminal(self.stream) as terminal:
            self.assertTrue(self.stream.getvalue().startswith(ansi.ENTER_ALT_SCREEN))
            self.assertEqual(terminal.read(0.5), "q")
        output = self.stream.getvalue()
        self.assertTrue(output.endswith(ansi.LEAVE_ALT_SCREEN + ansi.RESTORE_SCROLLBAR))
        self.assertIn(ansi.SHOW_CURSOR, output)
        self.assertEqual(self.console.calls, ["enable", "read(0.5)", "restore"])

    def test_scroll_bar_is_saved_hidden_and_restored(self) -> None:
        """The scroll bar setting is saved and hidden on entry, restored on exit."""
        with Terminal(self.stream):
            entered = self.stream.getvalue()
            self.assertIn(ansi.HIDE_SCROLLBAR, entered)
            self.assertNotIn(ansi.RESTORE_SCROLLBAR, entered)
        self.assertEqual(self.stream.getvalue().count(ansi.RESTORE_SCROLLBAR), 1)
        self.assertEqual(ansi.HIDE_SCROLLBAR, "\x1b[?30s\x1b[?30l")
        self.assertEqual(ansi.RESTORE_SCROLLBAR, "\x1b[?30r")

    def test_mouse_reporting_is_switched_on_and_off(self) -> None:
        """Mouse reporting is enabled inside the session and disabled after."""
        with Terminal(self.stream):
            self.assertTrue(self.stream.getvalue().endswith(ansi.ENABLE_MOUSE))
        output = self.stream.getvalue()
        self.assertLess(
            output.index(ansi.DISABLE_MOUSE), output.index(ansi.LEAVE_ALT_SCREEN)
        )

    def test_bracketed_paste_is_switched_on_and_off(self) -> None:
        """Bracketed paste is enabled inside the session and disabled after,
        before leaving the alternate screen."""
        with Terminal(self.stream, mouse=False):
            self.assertIn(ansi.ENABLE_BRACKETED_PASTE, self.stream.getvalue())
            self.assertNotIn(ansi.DISABLE_BRACKETED_PASTE, self.stream.getvalue())
        output = self.stream.getvalue()
        self.assertLess(
            output.index(ansi.DISABLE_BRACKETED_PASTE),
            output.index(ansi.LEAVE_ALT_SCREEN),
        )
        self.assertEqual(ansi.ENABLE_BRACKETED_PASTE, "\x1b[?2004h")
        self.assertEqual(ansi.DISABLE_BRACKETED_PASTE, "\x1b[?2004l")

    def test_mouse_reporting_can_be_turned_off(self) -> None:
        """With mouse=False no mouse sequences are sent."""
        with Terminal(self.stream, mouse=False):
            pass
        self.assertNotIn(ansi.ENABLE_MOUSE, self.stream.getvalue())
        self.assertNotIn(ansi.DISABLE_MOUSE, self.stream.getvalue())

    def test_restores_console_after_exception(self) -> None:
        """An error inside the session still restores the terminal."""
        with self.assertRaises(RuntimeError):
            with Terminal(self.stream):
                raise RuntimeError("boom")
        self.assertTrue(
            self.stream.getvalue().endswith(
                ansi.LEAVE_ALT_SCREEN + ansi.RESTORE_SCROLLBAR
            )
        )
        self.assertEqual(self.console.calls, ["enable", "restore"])

    def test_suspended(self) -> None:
        """Suspended gives the terminal back as leaving does, then takes it
        again as entering does, onto a cleared alternate screen."""
        with Terminal(self.stream) as terminal:
            entered = self.stream.getvalue()
            with terminal.suspended():
                given_back = self.stream.getvalue()[len(entered) :]
                self.assertIn(ansi.DISABLE_MOUSE, given_back)
                self.assertIn(ansi.SHOW_CURSOR, given_back)
                self.assertTrue(
                    given_back.endswith(ansi.LEAVE_ALT_SCREEN + ansi.RESTORE_SCROLLBAR)
                )
                self.assertEqual(self.console.calls, ["enable", "restore"])
            taken = self.stream.getvalue()[len(entered) + len(given_back) :]
            self.assertEqual(taken, entered)
            self.assertIn(ansi.CLEAR_SCREEN, taken)
            self.assertEqual(self.console.calls, ["enable", "restore", "enable"])
        self.assertEqual(self.console.calls[-1], "restore")

    def test_suspended_takes_it_back_after_a_failure(self) -> None:
        """Even when what ran meanwhile failed."""
        with Terminal(self.stream) as terminal:
            with self.assertRaises(RuntimeError):
                with terminal.suspended():
                    raise RuntimeError("boom")
            self.assertEqual(self.console.calls, ["enable", "restore", "enable"])
            self.assertTrue(self.stream.getvalue().endswith(ansi.ENABLE_MOUSE))

    def test_suspended_without_the_mouse(self) -> None:
        """Mouse reporting stays off where it was not asked for."""
        with Terminal(self.stream, mouse=False) as terminal:
            with terminal.suspended():
                pass
        self.assertNotIn(ansi.ENABLE_MOUSE, self.stream.getvalue())

    def test_outgrown_screen_is_entered_afresh(self) -> None:
        """When a resize leaves the console's screen larger than its window
        (the classic Windows console, restored from maximised), the read
        leaves the alternate screen, has the console refit the main one,
        and enters it again, set up as before; the screen is then known to
        have been cleared, once."""
        self.console.stream = self.stream
        with Terminal(self.stream) as terminal:
            self.assertFalse(terminal.take_cleared())
            before = self.stream.getvalue()
            self.console.has_outgrown_window = True
            self.assertEqual(terminal.read(), "q")
            self.assertEqual(self.console.calls, ["enable", "read(None)", "refit"])
            self.assertEqual(
                self.console.output_at_refit, before + ansi.LEAVE_ALT_SCREEN
            )
            self.assertEqual(
                self.stream.getvalue()[len(self.console.output_at_refit) :],
                ansi.ENTER_ALT_SCREEN
                + ansi.HIDE_CURSOR
                + ansi.CLEAR_SCREEN
                + ansi.ENABLE_BRACKETED_PASTE
                + ansi.ENABLE_MOUSE,
            )
            self.assertTrue(terminal.take_cleared())
            self.assertFalse(terminal.take_cleared())
            self.assertEqual(terminal.read(), "q")  # it fits now: left alone
            self.assertFalse(terminal.take_cleared())
        self.assertEqual(self.console.calls.count("refit"), 1)

    def test_outgrown_screen_without_the_mouse(self) -> None:
        """Entering afresh does not turn on mouse reporting where it was not
        asked for."""
        with Terminal(self.stream, mouse=False) as terminal:
            self.console.has_outgrown_window = True
            terminal.read()
            self.assertTrue(terminal.take_cleared())
        self.assertNotIn(ansi.ENABLE_MOUSE, self.stream.getvalue())

    def test_reads_that_fit_leave_the_screen_alone(self) -> None:
        """Without the console's report, a read writes nothing."""
        with Terminal(self.stream) as terminal:
            before = self.stream.getvalue()
            terminal.read()
            self.assertEqual(self.stream.getvalue(), before)
            self.assertFalse(terminal.take_cleared())

    def test_size_falls_back_when_terminal_reports_none(self) -> None:
        """A terminal with no usable size is treated as 80x24."""
        with patch("os.get_terminal_size", return_value=os.terminal_size((0, 0))):
            self.assertEqual(tuple(Terminal(self.stream).size()), (80, 24))


class AnsiTests(unittest.TestCase):
    """Escape sequence helpers."""

    def test_move_to_is_one_based(self) -> None:
        """Rows and columns are 0-based in Python but 1-based on the wire."""
        self.assertEqual(ansi.move_to(0, 0), "\x1b[1;1H")
        self.assertEqual(ansi.move_to(4, 9), "\x1b[5;10H")


if __name__ == "__main__":
    unittest.main()
