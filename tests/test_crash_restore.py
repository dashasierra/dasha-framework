"""Crashes restore the terminal."""

import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dasha.application import Application
from dasha.canvas import Canvas, Rect
from dasha.shortcuts import Shortcuts
from dasha.terminal import Terminal, ansi
from dasha.window import Window
import tests.support  # pylint: disable=unused-import  # cleans the environment
from tests.test_terminal import FakeConsole


class Crash(BaseException):
    """A crash the desktop does not recover from."""


class Bug(Exception):
    """An ordinary bug, which the desktop recovers from."""


class PaintBug(Window):
    """Fails every time it is drawn."""

    def paint_content(self, canvas: Canvas) -> None:
        raise Bug("paint")


class Stream(StringIO):
    """Standard output that remembers how much had been flushed."""

    def __init__(self) -> None:
        super().__init__()
        self.flushed = 0

    def flush(self) -> None:
        super().flush()
        self.flushed = len(self.getvalue())


class KeyCrash(Window):
    """Crashes on the first key."""

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        raise Crash(key)


class PaintCrash(Window):
    """Crashes the first time it is drawn."""

    def paint_content(self, canvas: Canvas) -> None:
        raise Crash("paint")


def crashing(window_class: type[Window]) -> Application:
    """An application with one window of a class.

    :param window_class: The window class.
    """

    class Crashing(Application):  # pylint: disable=too-few-public-methods
        """Opens the crashing window."""

        name = "Crashing"

        def start(self) -> None:
            self.open(window_class("Crash", Rect(2, 2, 6, 30)))

    return Crashing()


class CrashRestoreTests(unittest.TestCase):
    """The terminal comes back whatever the application does."""

    def setUp(self) -> None:
        self.console = FakeConsole()  # its read gives "q"
        console = patch("dasha.terminal._make_console", return_value=self.console)
        console.start()
        self.addCleanup(console.stop)
        self.stream = Stream()
        stdout = patch("sys.stdout", self.stream)
        stdout.start()
        self.addCleanup(stdout.stop)
        # Not the theme in this computer's settings, which would stay in use.
        starting_theme = patch("dasha.manager.PresentationManager.use_starting_theme")
        starting_theme.start()
        self.addCleanup(starting_theme.stop)

    def run_crashing(self, application: Application) -> str:
        """Run an application until it crashes; return the output.

        :param application: The application.
        """
        with self.assertRaises(Crash):
            application.run()
        self.assertIs(sys.stdout, self.stream)  # what Terminal() wrote to
        output = self.stream.getvalue()
        # All of it flushed, so it reached the terminal before the traceback.
        self.assertEqual(self.stream.flushed, len(output))
        return output

    def assert_restored(self, output: str) -> None:
        """Check the terminal was restored.

        :param output: The output written.
        """
        self.assertTrue(output.startswith(ansi.ENTER_ALT_SCREEN), output[:40])
        ending = output[output.rindex(ansi.ENABLE_MOUSE) :]
        tail = output[output.rindex(ansi.DISABLE_MOUSE) :]
        for sequence in (
            ansi.DISABLE_MOUSE,
            ansi.DISABLE_BRACKETED_PASTE,
            ansi.RESET_ATTRIBUTES,
            ansi.SHOW_CURSOR,
            ansi.LEAVE_ALT_SCREEN,
            ansi.RESTORE_SCROLLBAR,
        ):
            self.assertIn(sequence, tail, f"{sequence!r} missing at the end")
        self.assertIn(ansi.DISABLE_MOUSE, ending)
        # Nothing drawn after the screen was left.
        self.assertTrue(
            output.endswith(ansi.LEAVE_ALT_SCREEN + ansi.RESTORE_SCROLLBAR),
            repr(output[-80:]),
        )
        self.assertEqual(self.console.calls[0], "enable")
        self.assertEqual(self.console.calls[-1], "restore")
        self.assertEqual(self.console.calls.count("restore"), 1)

    def test_a_crash_on_a_key(self) -> None:
        """A crash while handling a key, after the screen was drawn."""
        output = self.run_crashing(crashing(KeyCrash))
        self.assertIn("Crash", output)  # its title was drawn
        self.assertIn("read(", "".join(self.console.calls))
        self.assert_restored(output)

    def test_a_crash_while_drawing(self) -> None:
        """A crash part-way through drawing the first frame."""
        self.assert_restored(self.run_crashing(crashing(PaintCrash)))

    def test_a_bug_that_keeps_failing(self) -> None:
        """A bug that keeps failing ends the desktop."""
        errors = StringIO()
        application = crashing(PaintBug)
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("sys.stderr", errors),
        ):
            application.log_folder = Path(folder)
            self.assertEqual(application.run(), 1)
            # Named after the application, not the desktop.
            logged = list(Path(folder).glob("crashing-*.log"))
        self.assert_restored(self.stream.getvalue())
        self.assertEqual(len(logged), 1)
        self.assertIn(
            "Crashing: stopped, as something kept going wrong", errors.getvalue()
        )

    def test_a_crash_while_starting(self) -> None:
        """A crash in ``start`` comes before the terminal is touched."""

        class StartCrash(Application):  # pylint: disable=too-few-public-methods
            """Crashes as it starts."""

            def start(self) -> None:
                raise Crash("start")

        output = self.run_crashing(StartCrash())
        self.assertEqual(output, "")
        self.assertEqual(self.console.calls, [])

    def test_mouse_switched_off_though_the_setting_changed(self) -> None:
        """Mouse reporting is switched off as it was on."""
        for before, after in ((True, False), (False, True)):
            with self.subTest(before=before):
                stream = StringIO()
                with self.assertRaises(Crash):
                    with Terminal(stream, mouse=before) as terminal:
                        terminal.mouse = after
                        raise Crash("mouse")
                output = stream.getvalue()
                self.assertEqual(ansi.ENABLE_MOUSE in output, before)
                self.assertEqual(ansi.DISABLE_MOUSE in output, before)


if __name__ == "__main__":
    unittest.main()
