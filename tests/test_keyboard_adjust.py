"""Tests for moving and resizing windows from the keyboard."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.dialog import Dialog
from dasha.events import MouseEvent, PasteEvent
from dasha.manager import PresentationManager
from dasha.shortcuts import Shortcuts, ShortcutsError
from dasha.widgets import TextBox
from dasha.window import DOUBLE, SINGLE, Window


class KeyboardAdjustTests(unittest.TestCase):
    """Alt+F7 to move, Alt+F8 to resize, arrows, Tab, Enter and Escape."""

    def setUp(self) -> None:
        self.back = Window("Back", Rect(10, 30, 5, 20))
        self.window = Window("W", Rect(5, 10, 6, 20), resizable=True)
        self.manager = PresentationManager(windows=[self.back, self.window])
        self.manager.handle_resize(80, 24)

    def keys(self, *keys: str) -> None:
        """Send keys through the manager.

        :param keys: The keys.
        """
        for key in keys:
            self.manager.handle_event(key)

    def test_move_with_arrows_and_keep(self) -> None:
        """Alt+F7, arrows move a cell at a time, Enter keeps the result."""
        self.keys("alt+f7")
        self.assertIs(self.manager.adjusting, self.window)
        self.assertTrue(self.window.adjusting)
        self.keys("right", "right", "down", "left", "up", "up")
        self.assertEqual(self.window.rect, Rect(4, 11, 6, 20))
        self.keys("enter")
        self.assertIsNone(self.manager.adjusting)
        self.assertFalse(self.window.adjusting)
        self.assertEqual(self.window.rect, Rect(4, 11, 6, 20))

    def test_escape_puts_it_back(self) -> None:
        """Escape cancels, after moving and resizing both."""
        self.keys("alt+f7", "down", "tab", "right", "down", "escape")
        self.assertEqual(self.window.rect, Rect(5, 10, 6, 20))
        self.assertIsNone(self.manager.adjusting)

    def test_resize_and_switch(self) -> None:
        """Resize and switch modes."""
        self.keys("alt+f8", "right", "down", "down")
        self.assertEqual(self.window.rect, Rect(5, 10, 8, 21))
        self.keys("tab", "left")
        self.assertEqual(self.window.rect, Rect(5, 9, 8, 21))
        self.keys("tab", *["left"] * 30, "enter")
        self.assertEqual(self.window.rect.width, self.window.min_width)

    def test_it_cannot_be_moved_off_screen(self) -> None:
        """It cannot be moved off screen."""
        self.keys("alt+f7", *["left"] * 200)
        self.assertEqual(self.window.rect.column, 4 - 20)
        self.keys(*["right"] * 300)
        self.assertEqual(self.window.rect.column, 80 - 4)
        self.keys(*["down"] * 100)
        self.assertEqual(self.window.rect.row, 22)  # just above the status bar
        self.keys(*["up"] * 100, "enter")
        self.assertEqual(self.window.rect.row, 1)  # just below the menu bar

    def test_resizing_cannot_lose_it_either(self) -> None:
        """Resizing cannot lose it."""
        self.window.move_to(5, -14)  # six columns showing
        self.keys("alt+f8", *["left"] * 30, "enter")
        rect = self.window.rect
        self.assertEqual(rect.width, self.window.min_width)
        self.assertGreaterEqual(rect.column + rect.width, min(4, rect.width))

    def test_a_window_put_off_screen_is_brought_back(self) -> None:
        """A window put off screen is brought back."""
        lost = Window("Lost", Rect(40, 500, 6, 20))
        self.manager.add(lost)
        self.assertEqual((lost.rect.row, lost.rect.column), (22, 76))
        early = PresentationManager()  # before the screen size is known
        wide = Window("Wide", Rect(2, 100, 6, 20))
        early.add(wide)
        early.handle_resize(132, 40)
        self.assertEqual(wide.rect.column, 100)  # left where it was put

    def test_ctrl_f5_moves_too(self) -> None:
        """Ctrl+F5 is a second key for moving."""
        self.keys("ctrl+f5", "down", "enter")
        self.assertEqual(self.window.rect.row, 6)

    def test_not_resizable(self) -> None:
        """Not resizable."""
        self.manager.bring_to_front(self.back)
        self.keys("alt+f8")
        self.assertIsNone(self.manager.adjusting)
        self.keys("alt+f7", "tab", "right", "enter")
        self.assertEqual(self.back.rect, Rect(10, 31, 5, 20))

    def test_title_bar_stays_between_the_bars(self) -> None:
        """The title bar stays between the bars."""
        self.keys("alt+f7", *["up"] * 10)
        self.assertEqual(self.window.rect.row, 1)
        self.keys(*["down"] * 40)
        self.assertEqual(self.window.rect.row, 22)

    def test_maximised_window_is_restored_first(self) -> None:
        """Moving a maximised window restores it, then moves it."""
        self.manager.maximise(self.window)
        self.keys("alt+f7", "right", "enter")
        self.assertFalse(self.window.maximised)
        self.assertEqual(self.window.rect, Rect(5, 11, 6, 20))

    def test_keys_go_to_the_mode_not_the_window(self) -> None:
        """Keys go to the mode, not the window."""
        box = self.window.add(TextBox(0, 0, 10, text="abc"))
        self.keys("alt+f7", "left", "f10", "x")
        self.manager.handle_event(PasteEvent("pasted"))
        self.assertEqual((box.text, box.cursor), ("abc", 3))
        self.assertFalse(self.manager.menu_bar.is_open)
        self.keys("enter")

    def test_mouse_press_finishes(self) -> None:
        """A click keeps the window where it is and is then handled."""
        self.keys("alt+f7", "right")
        self.manager.handle_event(MouseEvent("press", "left", 11, 45))  # Back
        self.assertIsNone(self.manager.adjusting)
        self.assertIs(self.manager.active_window, self.back)
        self.assertEqual(self.window.rect.column, 11)

    def test_status_bar_explains_the_keys(self) -> None:
        """The status bar says what the keys do."""
        self.keys("alt+f7")
        self.assertEqual(
            self.manager.status(),
            "Moving: arrows move, Tab to resize, Enter to finish, Esc to cancel",
        )
        self.keys("tab")
        self.assertTrue(self.manager.status().startswith("Resizing: arrows resize"))

    def test_frame_shows_the_mode(self) -> None:
        """The frame is drawn in its own colours while adjusting."""
        self.keys("alt+f7")
        canvas = Canvas(80, 24)
        self.manager.compose(canvas)
        corner = canvas.cell(self.window.rect.row, self.window.rect.column)
        self.assertEqual(corner[1], self.window.adjusting_frame_style)

    def corner_style(self) -> object:
        """The style the window's top-left corner is drawn in."""
        canvas = Canvas(80, 24)
        self.manager.compose(canvas)
        return canvas.cell(self.window.rect.row, self.window.rect.column)[1]

    def test_mouse_move_shows_the_same_frame(self) -> None:
        """A mouse move shows the same frame."""
        title = (self.window.rect.row, self.window.rect.column + 8)
        self.manager.handle_event(MouseEvent("press", "left", *title))
        self.assertEqual(self.corner_style(), self.window.adjusting_frame_style)
        self.manager.handle_event(MouseEvent("drag", "left", title[0] + 2, title[1]))
        self.assertEqual(self.corner_style(), self.window.adjusting_frame_style)
        self.manager.handle_event(MouseEvent("release", "left", title[0] + 2, title[1]))
        self.assertEqual(self.corner_style(), self.window.frame_style)
        self.assertFalse(self.window.adjusting)

    def test_single_lines_while_moving(self) -> None:
        """Single lines while moving."""
        canvas = Canvas(80, 24)
        corner = (self.window.rect.row, self.window.rect.column)
        self.manager.compose(canvas)
        self.assertEqual(canvas.cell(*corner)[0], DOUBLE.top_left)
        self.keys("alt+f7")
        self.manager.compose(canvas)
        self.assertEqual(canvas.cell(*corner)[0], SINGLE.top_left)
        self.keys("enter")
        title = (self.window.rect.row, self.window.rect.column + 8)
        self.manager.handle_event(MouseEvent("press", "left", *title))
        self.manager.compose(canvas)
        self.assertEqual(canvas.cell(*corner)[0], SINGLE.top_left)
        self.manager.handle_event(MouseEvent("release", "left", *title))
        self.manager.compose(canvas)
        self.assertEqual(canvas.cell(*corner)[0], DOUBLE.top_left)

    def test_dialog_keeps_its_background(self) -> None:
        """A dialog keeps its background."""
        dialog = Dialog("Q", 30, 8)
        dialog.move_to(5, 5)
        manager = PresentationManager(windows=[dialog])
        manager.handle_resize(80, 24)
        manager.handle_event(MouseEvent("press", "left", 5, 12))
        canvas = Canvas(80, 24)
        manager.compose(canvas)
        style = canvas.cell(5, 5)[1]
        self.assertEqual(style, Dialog.adjusting_frame_style)
        self.assertEqual(style.background, Dialog.frame_style.background)
        self.assertNotEqual(style.background, Window.adjusting_frame_style.background)

    def test_mouse_resize_shows_it_too(self) -> None:
        """Dragging the resize grip shows it as well."""
        rect = self.window.rect
        grip = (rect.bottom - 1, rect.right - 1)
        self.manager.handle_event(MouseEvent("press", "left", *grip))
        self.assertTrue(self.window.adjusting)
        self.manager.handle_event(MouseEvent("release", "left", *grip))
        self.assertFalse(self.window.adjusting)

    def test_minimised_mid_drag(self) -> None:
        """A window minimised while dragged keeps no moving frame."""
        title = (self.window.rect.row, self.window.rect.column + 8)
        self.manager.handle_event(MouseEvent("press", "left", *title))
        self.manager.minimise(self.window)
        self.assertFalse(self.window.adjusting)

    def test_closing_or_minimising_ends_it(self) -> None:
        """A window that goes away stops being adjusted."""
        self.manager.start_moving(self.window)
        self.manager.minimise(self.window)
        self.assertIsNone(self.manager.adjusting)
        self.manager.restore(self.window)
        self.manager.start_resizing()
        self.manager.remove(self.window)
        self.assertIsNone(self.manager.adjusting)
        self.assertFalse(self.window.adjusting)

    def test_remapped_keys(self) -> None:
        """Every key of the mode can be remapped."""
        shortcuts = Shortcuts(
            {"move_window": ["ctrl+w"], "adjust_right": ["l"], "adjust_accept": ["q"]}
        )
        manager = PresentationManager(windows=[self.window], shortcuts=shortcuts)
        manager.handle_resize(80, 24)
        for key in ("ctrl+w", "l", "right", "q"):
            manager.handle_event(key)
        self.assertEqual(self.window.rect.column, 11)
        self.assertIsNone(manager.adjusting)

    def test_needs_a_way_out(self) -> None:
        """Shortcuts with no key to accept or cancel are refused."""
        with self.assertRaises(ShortcutsError):
            Shortcuts({"adjust_accept": [], "adjust_cancel": []})


if __name__ == "__main__":
    unittest.main()
