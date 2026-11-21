"""Tests for centred titles and double-clicking the system menu."""

import unittest
from typing import cast

from dasha.canvas import Canvas, Rect
from dasha.dialog import Dialog
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.terminal import Terminal
from dasha.window import Window
from tests.test_manager import FakeTerminal


def title_at(window: Window, active: bool = True) -> int:
    """The column the title starts at.

    :param window: The window.
    :param active: Whether it is drawn active.
    """
    canvas = Canvas(window.rect.right + 1, window.rect.bottom + 1)
    window.paint(canvas, active)
    return canvas.text(window.rect.row).index(f" {window.title} ")


class TitleTests(unittest.TestCase):
    """Titles sit in the middle of the frame, whatever the buttons."""

    def test_dialog_title_is_centred(self) -> None:
        """A dialog's close button no longer pushes its title right."""
        dialog = Dialog("Exit", 40, 8)
        start = title_at(dialog)
        self.assertEqual(start, (40 - len(" Exit ")) // 2)
        self.assertEqual(start + len(" Exit ") // 2, 20)  # its middle

    def test_same_place_active_or_not(self) -> None:
        """The title does not move as buttons come and go."""
        window = Window("Notes", Rect(0, 0, 6, 30), closable=True, maximisable=True)
        self.assertEqual(title_at(window, True), title_at(window, False))
        self.assertEqual(title_at(window), (30 - len(" Notes ")) // 2)

    def test_moves_aside_for_a_button(self) -> None:
        """A long title in a narrow window keeps clear of the buttons."""
        window = Window("A longer title", Rect(0, 0, 4, 22), closable=True)
        start = title_at(window)
        self.assertGreaterEqual(start, 5)  # past ╔═[■]
        self.assertLessEqual(start + len(" A longer title "), 21)


class SystemMenuDoubleClickTests(unittest.TestCase):
    """Double-clicking ≡ asks to shut down, like its Exit item."""

    def run_with(self, inputs: list[str], confirm_exit: bool = True) -> FakeTerminal:
        """Run a manager on scripted input.

        :param inputs: Input to read.
        :param confirm_exit: Whether exit asks first.
        """
        terminal = FakeTerminal(inputs, sizes=[(60, 20)])
        manager = PresentationManager()
        manager.double_click_time, manager.confirm_exit = 60.0, confirm_exit
        manager.run(cast(Terminal, terminal))
        self.assertFalse(manager.is_running)
        return terminal

    CLICK = "\x1b[<0;3;1M\x1b[<0;3;1m"  # on ≡, row 0 column 2

    def test_double_click_asks_then_shuts_down(self) -> None:
        """The Shutdown dialog appears; Enter (Shutdown) leaves."""
        terminal = self.run_with([self.CLICK, self.CLICK, "\r", "never read"])
        self.assertEqual(terminal.inputs, ["never read"])
        self.assertIn("Shutdown", terminal.output.getvalue())

    def test_cancel_stays(self) -> None:
        """Cancelling the dialog stays in Dasha Framework, with the menu closed."""
        terminal = self.run_with([self.CLICK, self.CLICK, "\x1b", "", "\x11", "\r"])
        self.assertEqual(terminal.inputs, [])

    def test_without_confirmation(self) -> None:
        """With confirm_exit off, a double-click leaves at once."""
        terminal = self.run_with(
            [self.CLICK, self.CLICK, "never read"], confirm_exit=False
        )
        self.assertEqual(terminal.inputs, ["never read"])

    def test_single_click_just_opens_the_menu(self) -> None:
        """One click opens the system menu as before."""
        manager = PresentationManager()
        manager.handle_resize(60, 20)
        manager.handle_event(MouseEvent("press", "left", 0, 2))
        self.assertTrue(manager.menu_bar.is_open)
        self.assertIs(manager.menu_bar.open_menu, manager.system_menu)


if __name__ == "__main__":
    unittest.main()
