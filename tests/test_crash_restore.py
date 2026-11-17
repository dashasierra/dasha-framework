"""An application that crashes, run standalone on a real ``Terminal``,
leaves the user's terminal as it found it before the traceback prints:
the alternate screen left, mouse reporting and bracketed paste off, the
cursor shown, and the console out of raw mode."""

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
    """What the crashing applications raise: not an ``Exception``, so that
    the desktop's soft failing (``dasha.recovery``) lets it through, as
    it does ``KeyboardInterrupt``, and the application really ends."""


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
    """An application whose one window is a ``window_class``."""

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
        """Run ``application`` standalone, as ``Application.run`` does on
        the real terminal; check it crashes, and return what was written."""
        with self.assertRaises(Crash):
            application.run()
        self.assertIs(sys.stdout, self.stream)  # what Terminal() wrote to
        output = self.stream.getvalue()
        # All of it flushed, so it reached the terminal before the traceback.
        self.assertEqual(self.stream.flushed, len(output))
        return output

    def assert_restored(self, output: str) -> None:
        """After the last drawing, everything switched on is switched off,
        ending on the user's own screen, and the console is out of raw mode."""
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
        """An ordinary exception is recovered from; one on every frame makes
        it give up after ``Recovery.limit``, putting the terminal back as
        ever, and saying where the log is."""
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
        """Mouse reporting switched on is switched off on leaving, even if
        ``mouse`` was changed while the terminal was in use; and one never
        switched on is never switched off."""
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
