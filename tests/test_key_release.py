"""Tests for key releases, and buttons held down by Space."""

import unittest
from typing import cast

from dasha.canvas import Canvas, Rect
from dasha.dialog import Dialog
from dasha.events import InputDecoder, KeyReleaseEvent, decode
from dasha.keytest import describe
from dasha.manager import PresentationManager
from dasha.shortcuts import Shortcuts
from dasha.terminal import Terminal, ansi
from dasha.widgets import Button, Widget
from dasha.window import Window
from tests.test_manager import FakeTerminal


class DecodingTests(unittest.TestCase):
    """The kitty keyboard protocol's event types."""

    def test_release(self) -> None:
        """Event 3 is a release; 1 and 2 (press, repeat) are the key."""
        self.assertEqual(decode(ansi.SPACE_RELEASED), [KeyReleaseEvent(" ")])
        self.assertEqual(decode("\x1b[97;5:3u"), [KeyReleaseEvent("ctrl+a")])
        self.assertEqual(decode("\x1b[97;5:1u\x1b[97;5:2u"), ["ctrl+a", "ctrl+a"])

    def test_split_across_reads(self) -> None:
        """A release can arrive in pieces."""
        decoder = InputDecoder()
        self.assertEqual(decoder.feed(" \x1b[32;1"), [" "])
        self.assertEqual(decoder.feed(":3u"), [KeyReleaseEvent(" ")])

    def test_key_test_shows_it(self) -> None:
        """The key test names releases."""
        self.assertEqual(describe(KeyReleaseEvent(" ")), "release  space")


class ButtonTests(unittest.TestCase):
    """Space holds a button in where releases are reported."""

    def setUp(self) -> None:
        self.pressed: list[str] = []
        self.window = Window("W", Rect(0, 0, 8, 40))
        self.ok = self.window.add(
            Button("&OK", 1, 1, action=lambda b: self.pressed.append("ok"))
        )
        self.other = self.window.add(Button("&No", 4, 1, default=True))
        self.shortcuts = Shortcuts()

    def tearDown(self) -> None:
        Widget.key_releases = False

    def test_held_until_released(self) -> None:
        """Space pushes the button in (drawn pushed, not yet pressed), the
        key's repeats change nothing, and letting go presses it once."""
        Widget.key_releases = True
        for _ in range(3):  # the press, and two repeats while held
            self.window.handle_key(" ", self.shortcuts)
        self.assertEqual(self.pressed, [])
        canvas = Canvas(40, 8)
        self.window.paint(canvas, active=True)
        face_row = 2  # the window's interior starts at row 1
        self.assertEqual(canvas.text(face_row)[1:4], "   ")  # moved right one
        self.window.handle_key_release(" ")
        self.assertEqual(self.pressed, ["ok"])
        self.window.handle_key_release(" ")  # a stray release: nothing more
        self.assertEqual(self.pressed, ["ok"])

    def test_focus_moved_away_cancels(self) -> None:
        """If the focus moves on while Space is held, letting go just lets
        the button spring back."""
        Widget.key_releases = True
        self.window.handle_key(" ", self.shortcuts)
        self.window.handle_key("tab", self.shortcuts)
        self.window.handle_key_release(" ")
        self.assertEqual(self.pressed, [])

    def test_without_releases_it_presses_at_once(self) -> None:
        """Where releases are not reported, Space presses straight away,
        exactly as before."""
        self.window.handle_key(" ", self.shortcuts)
        self.assertEqual(self.pressed, ["ok"])

    def test_enter_presses_at_once(self) -> None:
        """Enter never waits: it presses as soon as it arrives."""
        Widget.key_releases = True
        self.window.handle_key("enter", self.shortcuts)
        self.assertEqual(self.pressed, ["ok"])


class ReleasingTerminal(FakeTerminal):
    """A scripted terminal that reports key releases, as Windows does."""

    can_report_key_releases = True


class ManagerTests(unittest.TestCase):
    """Releases reach the focused widget, in windows and dialogs."""

    def test_in_a_dialog(self) -> None:
        """In the Shutdown dialog, Space then its release presses Shutdown."""
        manager = PresentationManager()
        terminal = ReleasingTerminal(["\x11", " ", ansi.SPACE_RELEASED, "never read"])
        manager.run(cast(Terminal, terminal))
        self.assertEqual(terminal.inputs, ["never read"])
        self.assertFalse(Widget.key_releases)  # put back once Dasha Framework stops

    def test_without_releases_in_a_dialog(self) -> None:
        """Without releases, Space alone presses Shutdown, as before."""
        manager = PresentationManager()
        terminal = FakeTerminal(["\x11", " ", "never read"])
        manager.run(cast(Terminal, terminal))
        self.assertEqual(terminal.inputs, ["never read"])

    def test_in_a_window(self) -> None:
        """The manager passes releases to the active window."""
        pressed: list[str] = []
        window = Window("W", Rect(1, 0, 8, 30))
        window.add(Button("&Go", 1, 1, action=lambda b: pressed.append("go")))
        window.add(Button("&Stop", 4, 1))
        manager = PresentationManager(windows=[window])
        manager.run(
            cast(
                Terminal,
                ReleasingTerminal([" ", "", ansi.SPACE_RELEASED, "\x11", "\r"]),
            )
        )
        self.assertEqual(pressed, ["go"])

    def test_dialog_widget_release(self) -> None:
        """A dialog is a window, so its buttons hear releases too."""
        dialog = Dialog("Q", 30, 8)
        dialog.add(Button("&OK", 1, 2, result="ok", default=True))
        Widget.key_releases = True
        try:
            dialog.handle_key(" ", Shortcuts())
            self.assertIsNone(dialog.result)
            dialog.handle_key_release(" ")
            self.assertEqual(dialog.result, "ok")
        finally:
            Widget.key_releases = False


if __name__ == "__main__":
    unittest.main()
