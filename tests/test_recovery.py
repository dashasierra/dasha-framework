"""Tests for surviving errors in the desktop."""

# pylint: disable=protected-access

import os
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast
from unittest import mock

from dasha import logs
from dasha.__main__ import _report_errors
from dasha.canvas import Canvas, Rect
from dasha.dialog import Dialog, information
from dasha.manager import PresentationManager
from dasha.recovery import GuardedTerminal, Recovery, TerminalFailed
from dasha.shortcuts import Shortcuts
from dasha.terminal import Terminal
from dasha.widgets import Button
from dasha.window import Window
from tests.support import (
    real_app_log_folder,
    assert_lines_shown,
    isolated_home,
    started_desktop,
)
from tests.test_manager import FakeTerminal

QUIT = ["\x11", "\r"]  # Ctrl+Q, and OK to leaving


class Broken(Window):
    """A window whose key ``x`` fails, as a bug would."""

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        if key == "x":
            raise RuntimeError("boom")
        return super().handle_key(key, shortcuts)


class BrokenDialog(Dialog):
    """A dialog whose key ``x`` fails, with an OK button."""

    def __init__(self) -> None:
        super().__init__("Broken", 30, 6)
        self.add(Button("&OK", 2, 8, result="ok", default=True, name="ok"))

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        if key == "x":
            raise RuntimeError("dialog boom")
        return super().handle_key(key, shortcuts)


class Desktop(unittest.TestCase):
    """A desktop that fails softly, logging in an empty folder."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.logs = Path(folder.name)
        self.window = Broken("Broken", Rect(2, 2, 6, 30))
        self.manager = PresentationManager(windows=[self.window])
        self.manager.survive_errors = True
        self.manager.error_log_folder = self.logs

    def run_with(self, inputs: list[str]) -> FakeTerminal:
        """Run the desktop on input that must all be read.

        :param inputs: Input to read.
        """
        terminal = FakeTerminal(inputs, sizes=[(80, 24)])
        self.manager.run(cast(Terminal, terminal))
        self.assertEqual(terminal.inputs, [])
        return terminal

    def log_text(self) -> str:
        """The log of what went wrong."""
        recovery = self.manager.recovery
        assert recovery is not None and recovery.log_path is not None
        return recovery.log_path.read_text(encoding="utf-8")


class SurvivingTests(Desktop):
    """One failure: logged, told, and the desktop carries on."""

    def test_a_failing_key(self) -> None:
        """A failing key."""
        terminal = self.run_with(["x", "\r", *QUIT])
        recovery = self.manager.recovery
        assert recovery is not None and recovery.log_path is not None
        self.assertEqual(recovery.count, 1)
        self.assertFalse(self.manager.stopped_by_errors)
        self.assertEqual(recovery.log_path.parent, self.logs)
        self.assertTrue(recovery.log_path.name.startswith("desktop-"))
        self.assertIn("RuntimeError: boom", self.log_text())
        self.assertIn("handle_key", self.log_text())
        output = terminal.output.getvalue()
        assert_lines_shown(self, "Something went wrong in Dasha Desktop, but", output)
        assert_lines_shown(self, f"The details are in {recovery.log_path.name}", output)

    def test_put_aside(self) -> None:
        """An open menu is closed, and the screen drawn afresh."""
        self.manager.handle_resize(80, 24)
        self.manager.handle_event("f10")  # the system menu
        self.assertTrue(self.manager.menu_bar.is_open)
        self.manager._on_screen = Canvas(80, 24)
        self.manager._recover(RuntimeError("boom"), None)
        self.assertFalse(self.manager.menu_bar.is_open)
        self.assertIsNone(self.manager._on_screen)

    def test_in_a_dialog(self) -> None:
        """A failure in a dialog."""
        dialog = BrokenDialog()
        answers: list[str | None] = []
        self.manager.call_when_running(
            lambda: answers.append(self.manager.execute(dialog))
        )
        self.run_with(["x", "\r", "\r", *QUIT])  # fail, OK, then OK the dialog
        self.assertEqual(answers, ["ok"])
        self.assertIn("RuntimeError: dialog boom", self.log_text())

    def test_off(self) -> None:
        """With ``survive_errors`` off."""
        self.manager.survive_errors = False
        with self.assertRaisesRegex(RuntimeError, "boom"):
            self.manager.run(cast(Terminal, FakeTerminal(["x"], sizes=[(80, 24)])))
        self.assertIsNone(self.manager.recovery)


class GivingUpTests(Desktop):
    """Failing over and over: after Recovery.limit, the desktop gives up."""

    def test_drawing_that_always_fails(self) -> None:
        """Every frame fails, the dialog's too: it stops, saying so."""
        with mock.patch.object(
            Broken, "paint", side_effect=RuntimeError("cannot draw")
        ):
            terminal = FakeTerminal([""] * 10, sizes=[(80, 24)])
            self.manager.run(cast(Terminal, terminal))
        self.assertGreater(len(terminal.inputs), 0)  # it stopped by itself
        recovery = self.manager.recovery
        assert recovery is not None
        self.assertTrue(self.manager.stopped_by_errors)
        self.assertFalse(self.manager.is_running)
        self.assertEqual(recovery.count, Recovery.limit)
        self.assertEqual(self.log_text().count("RuntimeError: cannot draw"), 5)

    def test_failing_keys_never_give_up(self) -> None:
        """Failing keys never give up."""
        presses = ["x", "\r"] * (Recovery.limit * 2)  # fail, OK, over and over
        self.run_with([*presses, *QUIT])
        recovery = self.manager.recovery
        assert recovery is not None
        self.assertEqual(recovery.count, Recovery.limit * 2)
        self.assertFalse(self.manager.stopped_by_errors)
        self.assertFalse(recovery.has_too_many_failures)

    def test_now_and_then(self) -> None:
        """Failing now and then."""
        recovery = Recovery(self.logs)
        for _ in range(Recovery.limit * 4):
            recovery.record(RuntimeError("now and then"), "drawing")
            recovery.succeeded("drawing")
            self.assertFalse(recovery.has_too_many_failures)
        for _ in range(Recovery.limit - 1):
            recovery.record(RuntimeError("every time"), "timers")
            recovery.record(RuntimeError("once"), "drawing")
            recovery.succeeded("drawing")
            self.assertFalse(recovery.has_too_many_failures)
        recovery.record(RuntimeError("every time"), "timers")
        self.assertTrue(recovery.has_too_many_failures)

    def test_drawing_that_fails_now_and_then(self) -> None:
        """Drawing that fails now and then."""
        real_paint = Broken.paint
        drawn = {"frames": 0}

        def sometimes(window: Window, *args: object, **kwargs: object) -> None:
            drawn["frames"] += 1
            if drawn["frames"] % 3 == 0:
                raise RuntimeError("now and then")
            real_paint(window, *args, **kwargs)  # type: ignore[arg-type]

        with (
            mock.patch.object(Broken, "paint", sometimes),
            mock.patch("dasha.manager.information", wraps=information) as told,
        ):
            self.run_with(["", "", "\r", "", "", "", "", "", *QUIT])
        recovery = self.manager.recovery
        assert recovery is not None
        self.assertFalse(self.manager.stopped_by_errors)
        self.assertGreater(recovery.count, 1)
        dialogs = [
            c for c in told.call_args_list if c.args[0] == "Something went wrong"
        ]
        self.assertEqual(len(dialogs), 1)

    def test_told_now_and_then(self) -> None:
        """Told now and then."""
        recovery = Recovery(self.logs)
        with mock.patch("dasha.recovery.time.monotonic") as now:
            now.return_value = 100.0
            self.assertTrue(recovery.should_tell(by_user=False))
            now.return_value = 130.0
            self.assertFalse(recovery.should_tell(by_user=False))
            self.assertTrue(recovery.should_tell(by_user=True))
            now.return_value = 200.0
            self.assertTrue(recovery.should_tell(by_user=False))


class NeverCaughtTests(Desktop):
    """What ends the desktop on purpose, or a terminal that has gone."""

    def test_keyboard_interrupt(self) -> None:
        """Passes straight through."""
        with mock.patch.object(Broken, "handle_key", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.run(cast(Terminal, FakeTerminal(["a"], sizes=[(80, 24)])))
        self.assertIsNone(self.manager.recovery)

    def test_the_terminal_failing(self) -> None:
        """The terminal failing ends the desktop."""
        terminal = FakeTerminal([], sizes=[(80, 24)])
        with mock.patch.object(
            terminal, "read", side_effect=OSError(5, "Input/output error")
        ):
            with self.assertRaises(TerminalFailed) as caught:
                self.manager.run(cast(Terminal, terminal))
        self.assertIsInstance(caught.exception, OSError)
        self.assertEqual(caught.exception.strerror, "Input/output error")
        self.assertIsNone(self.manager.recovery)


class Suspending:  # pylint: disable=too-few-public-methods
    """A terminal that can fail to be given back.

    :param failing: What to fail, if anything.
    """

    def __init__(self, failing: str = "") -> None:
        self.failing = failing
        self.events: list[str] = []

    @contextmanager
    def suspended(self) -> Iterator[None]:
        """Give it back for a while."""
        if self.failing == "give":
            raise OSError(5, "Input/output error")
        self.events.append("given back")
        try:
            yield
        finally:
            if self.failing == "take":
                raise OSError(5, "Input/output error")
            self.events.append("taken")


class SuspendedTests(unittest.TestCase):
    """Giving a guarded terminal back, for the command prompt."""

    def test_passed_through(self) -> None:
        """Passed through."""
        inner = Suspending()
        guarded = GuardedTerminal(inner)
        with guarded.suspended():
            inner.events.append("shell")
        self.assertEqual(inner.events, ["given back", "shell", "taken"])
        with self.assertRaises(FileNotFoundError) as caught:
            with guarded.suspended():
                raise FileNotFoundError(2, "No such shell")
        self.assertNotIsInstance(caught.exception, TerminalFailed)
        self.assertEqual(inner.events[-1], "taken")

    def test_the_terminal_failing(self) -> None:
        """Failing to give back or take is the terminal's."""
        for failing in ("give", "take"):
            with self.subTest(failing=failing):
                with self.assertRaises(TerminalFailed) as caught:
                    with GuardedTerminal(Suspending(failing)).suspended():
                        pass
                self.assertEqual(caught.exception.strerror, "Input/output error")
        with self.assertRaises(TerminalFailed):
            with GuardedTerminal(Suspending("take")).suspended():
                raise FileNotFoundError(2, "No such shell")

    def test_only_where_the_terminal_has_it(self) -> None:
        """Only where the terminal has it."""
        self.assertFalse(hasattr(GuardedTerminal(object()), "suspended"))


class LogTests(unittest.TestCase):
    """The log itself."""

    def test_one_log_for_each_run(self) -> None:
        """Every failure goes in the same log, each with its time."""
        with tempfile.TemporaryDirectory() as folder:
            recovery = Recovery(Path(folder))
            first = recovery.record(RuntimeError("one"))
            second = recovery.record(ValueError("two"))
            self.assertEqual(first, second)
            assert first is not None
            text = first.read_text(encoding="utf-8")
            self.assertEqual(text.count("--- "), 2)
            self.assertIn("ValueError: two", text)

    def test_cannot_be_written(self) -> None:
        """Counted all the same, and the message says so."""
        with tempfile.TemporaryDirectory() as folder:
            blocked = Path(folder, "file")
            blocked.write_text("not a folder", encoding="utf-8")
            recovery = Recovery(blocked)
            self.assertIsNone(recovery.record(RuntimeError("boom")))
            self.assertEqual(recovery.count, 1)
            self.assertIn("could not be written", recovery.message)


class CommandLineTests(unittest.TestCase):
    """The command line turns it on, and says where the log is."""

    def setUp(self) -> None:
        isolated_home(self)

    def test_turned_on(self) -> None:
        """The desktop it starts fails softly."""
        code, desktop, _ = started_desktop()
        self.assertEqual(code, 0)
        self.assertTrue(desktop.return_value.survive_errors)

    def test_reported(self) -> None:
        """Reported on the command line."""
        manager = PresentationManager()
        self.assertFalse(_report_errors(manager))  # nothing went wrong
        with tempfile.TemporaryDirectory() as folder:
            manager.recovery = Recovery(Path(folder))
            path = manager.recovery.record(RuntimeError("boom"))
            with mock.patch("dasha.__main__.say") as say:
                self.assertFalse(_report_errors(manager))
                self.assertIn("went wrong once", say.call_args.args[0])
                self.assertIn(str(path), say.call_args.args[0])
                manager.stopped_by_errors = True
                self.assertTrue(_report_errors(manager))
                self.assertIn("kept going wrong", say.call_args.args[0])


class StandaloneLogTests(unittest.TestCase):
    """Stand-alone logs go where the system keeps logs."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        home = mock.patch.object(Path, "home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)

    def folder(self, platform: str, **environment: str) -> Path:
        """Notepad's log folder on a platform.

        :param platform: The platform.
        :param environment: Environment variables.
        """
        with (
            mock.patch.object(sys, "platform", platform),
            mock.patch.dict(os.environ, environment),
        ):
            for name in {"LOCALAPPDATA", "XDG_STATE_HOME"} - set(environment):
                os.environ.pop(name, None)
            return real_app_log_folder("Notepad")

    def test_windows(self) -> None:
        """%LOCALAPPDATA%\\Notepad\\logs, or the usual place without it."""
        local = str(self.home / "Local")
        self.assertEqual(
            self.folder("win32", LOCALAPPDATA=local), Path(local, "Notepad", "logs")
        )
        expected = self.home / "AppData" / "Local" / "Notepad" / "logs"
        self.assertEqual(self.folder("win32"), expected)
        self.assertEqual(self.folder("win32", LOCALAPPDATA="relative"), expected)

    def test_macos(self) -> None:
        """~/Library/Logs/Notepad."""
        expected = self.home / "Library" / "Logs" / "Notepad"
        self.assertEqual(self.folder("darwin"), expected)

    def test_elsewhere(self) -> None:
        """Elsewhere, XDG state."""
        state = str(self.home / "state")
        self.assertEqual(
            self.folder("linux", XDG_STATE_HOME=state),
            Path(state, "notepad", "logs"),
        )
        expected = self.home / ".local" / "state" / "notepad" / "logs"
        self.assertEqual(self.folder("linux"), expected)
        self.assertEqual(self.folder("linux", XDG_STATE_HOME="relative"), expected)

    def test_names_made_safe(self) -> None:
        """Only letters, digits and hyphens reach a file or folder name."""
        self.assertEqual(logs.log_name("Notepad and Demo"), "notepad-and-demo")
        self.assertEqual(
            logs.log_name("Notepad and Demo", keep_case=True), "Notepad-and-Demo"
        )
        self.assertEqual(logs.log_name("../../etc"), "etc")
        self.assertEqual(logs.log_name("☺"), "app")
        self.assertEqual(self.folder("win32").parent.name, "Notepad")

    def test_stand_alone_uses_it(self) -> None:
        """``stand_alone`` uses it."""
        manager = PresentationManager()
        self.assertEqual(manager.error_log_folder, logs.LOG_FOLDER)
        manager.stand_alone("Notepad")
        self.assertEqual(manager.error_log_folder, logs.app_log_folder("Notepad"))
        self.assertNotEqual(manager.error_log_folder, logs.LOG_FOLDER)
        manager.survive_errors = True
        manager.handle_resize(80, 24)
        with mock.patch.object(manager, "execute"):
            manager._recover(
                RuntimeError("boom"), None
            )  # pylint: disable=protected-access
        recovery = manager.recovery
        assert recovery is not None and recovery.log_path is not None
        self.assertTrue(recovery.log_path.name.startswith("notepad-"))
        self.assertEqual(recovery.log_path.parent, manager.error_log_folder)
        self.assertNotIn("dasha", recovery.message.casefold())
        self.assertNotIn("dasha", recovery.summary(gave_up=False).casefold())


if __name__ == "__main__":
    unittest.main()
