"""Tests for the close button, labels, push buttons and widget focus."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.shortcuts import Shortcuts
from dasha.widgets import SHADOW_BELOW, SHADOW_RIGHT, Button, Label
from dasha.window import Window

CLOSE = "[\N{BLACK SQUARE}]"


def press(row: int, column: int) -> MouseEvent:
    """A left-button press.

    :param row: Screen row.
    :param column: Screen column.
    """
    return MouseEvent("press", "left", row, column)


def release(row: int, column: int) -> MouseEvent:
    """A left-button release.

    :param row: Screen row.
    :param column: Screen column.
    """
    return MouseEvent("release", "left", row, column)


class CloseButtonTests(unittest.TestCase):
    """The close button."""

    def test_close_button_at_left_of_title_bar(self) -> None:
        """[■] sits two cells in from the corner; the title moves right."""
        window = Window("Title", Rect(0, 0, 4, 30), closable=True)
        self.assertIn(("close", Rect(0, 2, 1, 3)), window.title_buttons)
        canvas = Canvas(30, 4)
        window.paint(canvas, active=True)
        self.assertEqual(canvas.text(0)[2:5], CLOSE)
        self.assertGreater(canvas.text(0).index("Title"), 5)
        CLOSE[0::2].encode("cp437")  # the brackets...
        CLOSE[1].encode("cp437")  # ...and ■ (254) are code page 437

    def test_click_and_shortcut_close(self) -> None:
        """Clicking [■], Alt+F4 or Alt+F3 closes the active window."""
        a = Window("A", Rect(1, 0, 4, 20), closable=True)
        b = Window("B", Rect(6, 0, 4, 20), closable=True)
        c = Window("C", Rect(11, 0, 4, 20), closable=True)
        manager = PresentationManager(windows=[a, b, c])
        manager.handle_event(press(11, 3))
        self.assertEqual(manager.windows, (a, b))
        manager.handle_event("alt+f4")
        self.assertEqual(manager.windows, (a,))
        manager.handle_event("alt+f3")
        self.assertEqual(manager.windows, ())
        self.assertEqual(manager.shortcuts.hint("close_window"), "Alt+F4")

    def test_request_close_can_refuse(self) -> None:
        """A window whose request_close says no stays open."""

        class Stubborn(Window):
            """Refuses to close."""

            def request_close(self) -> bool:
                return False

        window = Stubborn("S", Rect(1, 0, 4, 20), closable=True)
        manager = PresentationManager(windows=[window])
        manager.close(window)
        self.assertEqual(manager.windows, (window,))

    def test_not_closable_by_default(self) -> None:
        """Without closable, there is no button and Alt+F4 does nothing."""
        window = Window("W", Rect(1, 0, 4, 20))
        manager = PresentationManager(windows=[window])
        manager.handle_event("alt+f4")
        self.assertEqual(manager.windows, (window,))


class LabelTests(unittest.TestCase):
    """Static text."""

    def test_label_paints_in_window_colours(self) -> None:
        """A label draws at its place inside the frame, as its value."""
        window = Window("W", Rect(0, 0, 5, 20))
        label = window.add(Label("Hello", 1, 2, name="greeting"))
        canvas = Canvas(20, 5)
        window.paint(canvas, active=True)
        self.assertEqual(canvas.text(2)[3:8], "Hello")
        self.assertEqual(canvas.cell(2, 3)[1], window.body_style)
        self.assertEqual(window.values, {"greeting": "Hello"})
        label.text = "Hi"
        self.assertEqual(label.rect.width, 2)
        self.assertFalse(label.focusable)


class ButtonTests(unittest.TestCase):
    """Push buttons."""

    def setUp(self) -> None:
        self.pressed: list[str] = []
        self.window = Window("W", Rect(0, 0, 8, 40))
        self.ok = self.window.add(
            Button("&OK", 1, 1, action=self.record, default=True, name="ok")
        )
        self.no = self.window.add(Button("&No", 1, 14, action=self.record, name="no"))
        self.shortcuts = Shortcuts()

    def record(self, button: Button) -> None:
        """Remember the pressed button.

        :param button: The button.
        """
        self.pressed.append(str(button.name))

    def key(self, key: str) -> bool:
        """Offer a key to the window.

        :param key: The key.
        """
        return self.window.handle_key(key, self.shortcuts)

    def test_face_and_shadow(self) -> None:
        """A green face, at least 10 wide, with a half-block shadow."""
        canvas = Canvas(40, 8)
        self.window.paint(canvas, active=True)
        face_row = canvas.text(2)
        self.assertEqual(face_row[2:12], "    OK    ")
        self.assertEqual(canvas.cell(2, 12)[0], SHADOW_RIGHT)
        self.assertEqual(canvas.text(3)[3:13], SHADOW_BELOW * 10)
        self.assertEqual(canvas.cell(2, 2)[1], Button.focused_style)  # focused
        self.assertEqual(canvas.cell(2, 15)[1], Button.face_style)
        self.assertEqual(canvas.cell(2, 6), ("O", Button.focused_mnemonic_style))
        for char in (SHADOW_RIGHT, SHADOW_BELOW):
            char.encode("cp437")

    def test_first_focusable_has_focus_and_tab_moves_it(self) -> None:
        """Tab and Shift+Tab cycle the focus between buttons."""
        self.assertIs(self.window.focused, self.ok)
        self.assertTrue(self.key("tab"))
        self.assertIs(self.window.focused, self.no)
        self.assertTrue(self.key("tab"))
        self.assertIs(self.window.focused, self.ok)
        self.assertTrue(self.key("shift+tab"))
        self.assertIs(self.window.focused, self.no)

    def test_enter_space_and_mnemonics(self) -> None:
        """Enter and Space press the focused button; Alt+letter presses one."""
        self.key("enter")
        self.key("tab")
        self.key(" ")
        self.key("alt+o")
        self.assertEqual(self.pressed, ["ok", "no", "ok"])
        self.assertIs(self.window.focused, self.ok)
        self.assertFalse(self.key("o"))  # plain letters only in dialogs

    def test_enter_presses_default_when_focus_elsewhere(self) -> None:
        """Enter presses the default from elsewhere."""
        self.window.focus(self.no)
        self.window._focus = None  # pylint: disable=protected-access
        self.key("enter")
        self.assertEqual(self.pressed, ["ok"])

    def test_mouse_press_then_release(self) -> None:
        """A press pushes the button in; release on it presses it."""
        interior = self.window.interior
        row, column = interior.row + 1, interior.column + 3
        self.assertTrue(self.window.handle_mouse(press(row, column)))
        canvas = Canvas(40, 8)
        self.window.paint(canvas, active=True)
        self.assertEqual(canvas.cell(2, 2)[0], " ")  # shifted right, no shadow
        self.assertNotEqual(canvas.cell(2, 12)[0], SHADOW_RIGHT)
        self.window.handle_mouse(release(row, column))
        self.assertEqual(self.pressed, ["ok"])

    def test_release_elsewhere_changes_mind(self) -> None:
        """Dragging off the button before letting go does not press it."""
        interior = self.window.interior
        self.window.handle_mouse(press(interior.row + 1, interior.column + 16))
        self.assertIs(self.window.focused, self.no)
        self.window.handle_mouse(release(interior.row + 5, interior.column + 30))
        self.assertEqual(self.pressed, [])


class ManagerWidgetTests(unittest.TestCase):
    """Widgets through the presentation manager."""

    def setUp(self) -> None:
        self.pressed: list[str] = []
        self.window = Window("W", Rect(1, 0, 8, 40), status="The window")
        self.window.add(
            Button("&One", 1, 1, name="one", status="First", action=self.record)
        )
        self.window.add(Button("&Two", 1, 14, name="two", action=self.record))
        self.other = Window("Other", Rect(10, 0, 4, 20))
        self.manager = PresentationManager(windows=[self.other, self.window])

    def record(self, button: Button) -> None:
        """Remember the pressed button.

        :param button: The button.
        """
        self.pressed.append(str(button.name))

    def test_tab_moves_focus_not_windows(self) -> None:
        """With two or more buttons, Tab cycles them; F6 still changes window."""
        self.manager.handle_event("tab")
        self.assertIs(self.manager.active_window, self.window)
        self.assertEqual(self.window.focused, self.window.widget("two"))
        self.manager.handle_event("f6")
        self.assertIs(self.manager.active_window, self.other)

    def test_status_shows_focused_widget(self) -> None:
        """The focused widget's status wins; without one, the window's shows."""
        self.assertEqual(self.manager.status(), "First")
        self.manager.handle_event("tab")
        self.assertEqual(self.manager.status(), "The window")

    def test_click_presses_button(self) -> None:
        """Press and release on a button through the manager presses it."""
        interior = self.window.interior
        row, column = interior.row + 1, interior.column + 16
        self.manager.handle_event(press(row, column))
        self.manager.handle_event(release(row, column))
        self.assertEqual(self.pressed, ["two"])

    def test_menus_still_get_alt_letters_first(self) -> None:
        """Alt+letter goes to the menu bar before window mnemonics."""
        self.manager.handle_event("alt+o")  # no menu "O": the button gets it
        self.assertEqual(self.pressed, ["one"])

    def test_widget_lookup(self) -> None:
        """widget() finds by name; a missing name is a KeyError."""
        self.assertEqual(self.window.widget("one").name, "one")
        with self.assertRaises(KeyError):
            self.window.widget("three")
        self.assertEqual(self.window.values, {"one": None, "two": None})


if __name__ == "__main__":
    unittest.main()
