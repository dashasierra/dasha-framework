"""Tests for maximising, minimising and restoring windows."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.menu import MenuItem
from dasha.shortcuts import Shortcuts
from dasha.window import Window

MINIMISE = "[\N{DOWNWARDS ARROW}]"
MAXIMISE = "[\N{UPWARDS ARROW}]"
RESTORE = "[\N{UP DOWN ARROW}]"


def press(row: int, column: int) -> MouseEvent:
    """A left-button press.

    :param row: Screen row.
    :param column: Screen column.
    """
    return MouseEvent("press", "left", row, column)


class TitleButtonTests(unittest.TestCase):
    """The buttons at the right of a window's title bar."""

    def test_buttons_follow_options(self) -> None:
        """Each option adds its button, right to left: maximise, minimise."""
        rect = Rect(1, 0, 5, 30)
        self.assertEqual(Window("w", rect).title_buttons, [])
        both = Window("w", rect, maximisable=True, minimisable=True)
        self.assertEqual(
            both.title_buttons,
            [("maximise", Rect(1, 25, 1, 3)), ("minimise", Rect(1, 22, 1, 3))],
        )
        self.assertEqual(
            Window("w", rect, minimisable=True).title_buttons,
            [("minimise", Rect(1, 25, 1, 3))],
        )

    def test_restore_button_when_maximised(self) -> None:
        """A maximised window offers restore instead of maximise."""
        window = Window("w", Rect(1, 0, 5, 30), maximisable=True)
        window.maximise(Rect(1, 0, 20, 60))
        self.assertEqual(window.title_buttons, [("restore", Rect(1, 55, 1, 3))])

    def test_buttons_use_code_page_437(self) -> None:
        """Button arrows are code page 437 glyphs."""
        low_glyphs = {
            "\N{UP DOWN ARROW}": 18,
            "\N{UPWARDS ARROW}": 24,
            "\N{DOWNWARDS ARROW}": 25,
        }
        for text in (MINIMISE, MAXIMISE, RESTORE):
            brackets, arrow = text[0] + text[2], text[1]
            brackets.encode("cp437")
            self.assertIn(arrow, low_glyphs)

    def test_buttons_drawn_only_on_active_window(self) -> None:
        """The active window shows its buttons; the title moves left of them."""
        window = Window("Title", Rect(0, 0, 4, 24), maximisable=True, minimisable=True)
        canvas = Canvas(24, 4)
        window.paint(canvas, active=True)
        top = canvas.text(0)
        self.assertEqual(top[16:22], MINIMISE + MAXIMISE)
        self.assertEqual(canvas.cell(0, 17), (MINIMISE[1], window.button_style))
        self.assertLess(top.index("Title"), 16)
        canvas = Canvas(24, 4)
        window.paint(canvas, active=False)
        self.assertNotIn(MAXIMISE, canvas.text(0))

    def test_too_narrow_for_buttons(self) -> None:
        """Buttons that would not fit are left out rather than overlapping."""
        window = Window("w", Rect(0, 0, 3, 6), maximisable=True, minimisable=True)
        self.assertEqual(window.title_buttons, [("maximise", Rect(0, 1, 1, 3))])

    def test_maximise_remembers_size(self) -> None:
        """Maximise then unmaximise returns to the original rectangle."""
        window = Window("w", Rect(3, 4, 6, 20), resizable=True)
        window.maximise(Rect(1, 0, 22, 80))
        self.assertTrue(window.maximised)
        self.assertEqual(window.restored_rect, Rect(3, 4, 6, 20))
        # The grip stays, to resize it from here.
        grip = window.resize_grip
        self.assertEqual(
            window.resize_grip_rect, Rect(22, 80 - len(grip), 1, len(grip))
        )
        canvas = Canvas(80, 24)
        window.paint(canvas, active=True)
        self.assertEqual(canvas.text(22)[80 - len(grip) : 80], grip)
        window.maximise(Rect(1, 0, 10, 40))  # refit: keeps the saved size
        window.unmaximise()
        self.assertFalse(window.maximised)
        self.assertEqual(window.rect, Rect(3, 4, 6, 20))


class ManagerStateTests(unittest.TestCase):
    """Maximise, minimise and restore through the presentation manager."""

    def setUp(self) -> None:
        self.notes = Window(
            "Notes", Rect(2, 2, 6, 30), maximisable=True, minimisable=True
        )
        self.files = Window(
            "Files", Rect(4, 20, 6, 30), maximisable=True, minimisable=True
        )
        self.manager = PresentationManager(windows=[self.notes, self.files])
        self.manager.handle_resize(80, 24)

    def system_labels(self) -> list[str]:
        """Labels in the system menu, separators shown as '-'."""
        return [
            "-" if item.is_separator else item.label
            for item in self.manager.system_menu.items
        ]

    def test_maximise_fills_work_area_and_follows_terminal(self) -> None:
        """A maximised window fills the work area, even after a resize."""
        self.manager.maximise(self.notes)
        self.assertIs(self.manager.active_window, self.notes)
        self.assertEqual(self.notes.rect, Rect(1, 0, 22, 80))
        self.manager.handle_resize(100, 30)
        self.assertEqual(self.notes.rect, Rect(1, 0, 28, 100))
        self.manager.restore(self.notes)
        self.assertEqual(self.notes.rect, Rect(2, 2, 6, 30))

    def test_dragging_a_maximised_window_restores_it(self) -> None:
        """Dragging a maximised window restores it."""
        self.manager.maximise(self.files)
        self.manager.handle_event(press(1, 40))
        self.manager.handle_event(MouseEvent("release", "left", 1, 40))
        self.assertTrue(self.files.maximised)
        # Another cell, or that would be a double-click, which restores it.
        self.manager.handle_event(press(1, 42))
        self.manager.handle_event(MouseEvent("drag", "left", 8, 42))
        self.assertFalse(self.files.maximised)
        self.assertEqual(self.files.rect, Rect(8, 42 - 16, 6, 30))
        self.manager.handle_event(MouseEvent("drag", "left", 9, 43))
        self.assertEqual(self.files.rect, Rect(9, 43 - 16, 6, 30))

    def test_resizing_a_maximised_window(self) -> None:
        """Resizing a maximised window."""
        self.files.resizable = True
        self.manager.maximise(self.files)
        grip = self.files.resize_grip_rect
        assert grip is not None
        self.manager.handle_event(press(grip.row, 79))
        self.manager.handle_event(MouseEvent("drag", "left", 15, 60))
        self.assertFalse(self.files.maximised)
        self.assertEqual(self.files.rect, Rect(1, 0, 15, 61))
        self.manager.restore(self.files)  # nothing to go back to now
        self.assertEqual(self.files.rect, Rect(1, 0, 15, 61))

    def test_from_the_keyboard(self) -> None:
        """From the keyboard."""
        self.files.resizable = True
        self.manager.maximise(self.files)
        for key in ("alt+f8", "left", "up", "enter"):
            self.manager.handle_event(key)
        self.assertFalse(self.files.maximised)
        self.assertEqual(self.files.rect, Rect(1, 0, 21, 79))
        self.manager.maximise(self.files)
        for key in ("alt+f7", "right", "down", "enter"):
            self.manager.handle_event(key)
        self.assertFalse(self.files.maximised)
        self.assertEqual(self.files.rect, Rect(2, 1, 21, 79))  # its size before
        self.manager.maximise(self.files)
        for key in ("alt+f7", "right", "escape"):
            self.manager.handle_event(key)
        self.assertTrue(self.files.maximised)
        self.assertEqual(self.files.rect, Rect(1, 0, 22, 80))
        self.manager.restore(self.files)
        self.assertEqual(self.files.rect, Rect(2, 1, 21, 79))

    def test_a_minimised_window_brought_to_the_front(self) -> None:
        """A minimised window brought to the front."""
        self.manager.minimise(self.notes)
        self.manager.send_to_back(self.notes)
        self.assertEqual(self.manager.minimised, (self.notes,))
        self.manager.bring_to_front(self.notes)
        self.assertEqual(self.manager.minimised, ())
        self.assertEqual(self.manager.windows, (self.files, self.notes))
        self.assertIs(self.manager.active_window, self.notes)

    def test_a_window_it_does_not_have(self) -> None:
        """Brought to the front or sent to the back, changes nothing."""
        stranger = Window("Stranger", Rect(0, 0, 4, 10))
        self.manager.bring_to_front(stranger)
        self.manager.send_to_back(stranger)
        self.assertEqual(self.manager.windows, (self.notes, self.files))

    def test_minimise_hides_and_lists_in_system_menu(self) -> None:
        """A minimised window leaves the screen and appears in the ≡ menu."""
        self.manager.minimise(self.files)
        self.assertEqual(self.manager.windows, (self.notes,))
        self.assertEqual(self.manager.minimised, (self.files,))
        self.assertEqual(
            self.system_labels(),
            [
                "&1 Files",
                "-",
                "&About",
                "S&ettings...",
                "&Themes",
                "A&nimations: Off",
                "&Command prompt",
                "-",
                "&Shutdown",
            ],
        )
        self.manager.minimise(self.notes)
        self.assertIsNone(self.manager.active_window)
        self.assertEqual(
            self.system_labels(),
            [
                "&1 Files",
                "&2 Notes",
                "-",
                "&About",
                "S&ettings...",
                "&Themes",
                "A&nimations: Off",
                "&Command prompt",
                "-",
                "&Shutdown",
            ],
        )
        self.assertEqual(self.manager.bar_menus(), [self.manager.system_menu])

    def test_restore_from_system_menu(self) -> None:
        """Restore from the system menu."""
        self.manager.minimise(self.files)
        self.manager.handle_event("f10")
        self.manager.handle_event("1")
        self.assertEqual(self.manager.minimised, ())
        self.assertIs(self.manager.active_window, self.files)
        self.assertEqual(self.files.rect, Rect(4, 20, 6, 30))
        self.assertEqual(
            self.system_labels(),
            [
                "&About",
                "S&ettings...",
                "&Themes",
                "A&nimations: Off",
                "&Command prompt",
                "-",
                "&Shutdown",
            ],
        )

    def test_minimised_while_maximised_comes_back_maximised(self) -> None:
        """Restoring from minimised returns to maximised, fitted to the screen."""
        self.manager.maximise(self.notes)
        self.manager.minimise(self.notes)
        self.manager.handle_resize(60, 20)
        self.manager.restore(self.notes)
        self.assertTrue(self.notes.maximised)
        self.assertEqual(self.notes.rect, Rect(1, 0, 18, 60))
        self.manager.restore(self.notes)  # and from maximised to normal
        self.assertEqual(self.notes.rect, Rect(2, 2, 6, 30))

    def test_tab_skips_minimised_windows(self) -> None:
        """Only windows on screen take part in cycling."""
        self.manager.minimise(self.notes)
        self.manager.handle_event("tab")
        self.assertIs(self.manager.active_window, self.files)

    def test_removing_minimised_window_unlists_it(self) -> None:
        """Closing a minimised window removes it from the ≡ menu too."""
        self.manager.minimise(self.notes)
        self.manager.remove(self.notes)
        self.assertEqual(self.manager.minimised, ())
        self.assertEqual(
            self.system_labels(),
            [
                "&About",
                "S&ettings...",
                "&Themes",
                "A&nimations: Off",
                "&Command prompt",
                "-",
                "&Shutdown",
            ],
        )

    def test_application_items_are_kept(self) -> None:
        """Application items are kept."""
        helper = MenuItem("&Help", print)
        self.manager.system_menu.items.insert(0, helper)
        self.manager.minimise(self.files)
        self.assertEqual(
            self.system_labels(),
            [
                "&1 Files",
                "-",
                "&Help",
                "&About",
                "S&ettings...",
                "&Themes",
                "A&nimations: Off",
                "&Command prompt",
                "-",
                "&Shutdown",
            ],
        )
        self.manager.restore(self.files)
        self.assertEqual(
            self.system_labels(),
            [
                "&Help",
                "&About",
                "S&ettings...",
                "&Themes",
                "A&nimations: Off",
                "&Command prompt",
                "-",
                "&Shutdown",
            ],
        )

    def test_ampersand_in_title_is_not_a_mnemonic(self) -> None:
        """A title with & is listed literally."""
        self.files.title = "Tom & Jerry"
        self.manager.minimise(self.files)
        self.assertEqual(self.system_labels()[0], "&1 Tom && Jerry")

    def test_title_buttons_by_mouse(self) -> None:
        """Click maximise, then restore, then minimise on the active window."""
        maximise_cell = self.files.title_buttons[0][1]
        self.manager.handle_event(press(maximise_cell.row, maximise_cell.column + 1))
        self.assertTrue(self.files.maximised)
        restore_cell = self.files.title_buttons[0][1]
        self.manager.handle_event(press(restore_cell.row, restore_cell.column))
        self.assertFalse(self.files.maximised)
        minimise_cell = self.files.title_buttons[1][1]
        self.manager.handle_event(press(minimise_cell.row, minimise_cell.column + 2))
        self.assertEqual(self.manager.minimised, (self.files,))

    def test_button_area_of_inactive_window_only_raises(self) -> None:
        """Buttons are not drawn on inactive windows, so clicks just raise."""
        self.manager.bring_to_front(self.files)  # notes inactive
        cell = self.notes.title_buttons[1][1]  # its minimise button
        self.manager.handle_event(press(cell.row, cell.column))
        self.assertIs(self.manager.active_window, self.notes)
        self.assertEqual(self.manager.minimised, ())

    def test_keyboard_shortcuts(self) -> None:
        """F5 toggles maximise; minimise works once a key is bound."""
        self.manager.handle_event("f5")
        self.assertTrue(self.files.maximised)
        self.manager.handle_event("f5")
        self.assertFalse(self.files.maximised)
        manager = PresentationManager(
            windows=[self.notes], shortcuts=Shortcuts({"minimise_window": ["f4"]})
        )
        manager.handle_event("f4")
        self.assertEqual(manager.minimised, (self.notes,))

    def test_shortcuts_respect_window_options(self) -> None:
        """F5 does nothing on a window that is not maximisable."""
        fixed = Window("Fixed", Rect(2, 2, 6, 30))
        manager = PresentationManager(windows=[fixed])
        manager.handle_event("f5")
        self.assertFalse(fixed.maximised)


class TitleBarDoubleClickTests(unittest.TestCase):
    """A double-click on the title bar maximises or restores."""

    def setUp(self) -> None:
        self.window = Window("W", Rect(3, 5, 6, 20), maximisable=True)
        self.manager = PresentationManager(windows=[self.window])
        self.manager.handle_resize(40, 20)

    def double_click(self, row: int, column: int) -> None:
        """A double click in a cell.

        :param row: Screen row.
        :param column: Screen column.
        """
        for _ in range(2):
            self.manager.handle_event(press(row, column))
            self.manager.handle_event(MouseEvent("release", "left", row, column))

    def test_maximise_and_restore(self) -> None:
        """Maximise and restore."""
        self.manager.double_click_time = 60.0  # however slow the test runs
        self.double_click(3, 12)
        self.assertTrue(self.window.maximised)
        self.double_click(1, 12)
        self.assertFalse(self.window.maximised)
        self.assertEqual(self.window.rect, Rect(3, 5, 6, 20))

    def test_single_clicks_and_slow_clicks_do_not(self) -> None:
        """One click, or two too far apart, leaves it as it is."""
        self.manager.handle_event(press(3, 12))
        self.manager.handle_event(MouseEvent("release", "left", 3, 12))
        self.manager.double_click_time = 0.0  # every click is a new one
        self.double_click(3, 12)
        self.assertFalse(self.window.maximised)

    def test_not_maximisable(self) -> None:
        """A window that cannot be maximised ignores the double-click."""
        fixed = Window("F", Rect(10, 5, 6, 20))
        self.manager.add(fixed)
        self.manager.double_click_time = 60.0
        self.double_click(10, 12)
        self.assertFalse(fixed.maximised)
        self.assertEqual(fixed.rect, Rect(10, 5, 6, 20))

    def test_double_click_inside_does_not(self) -> None:
        """Only the title bar counts, not the inside of the window."""
        self.manager.double_click_time = 60.0
        self.double_click(5, 12)
        self.assertFalse(self.window.maximised)


if __name__ == "__main__":
    unittest.main()
