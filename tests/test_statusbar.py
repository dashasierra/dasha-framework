"""Tests for the status bar."""

import unittest
from typing import cast

from dasha.canvas import Canvas, Rect
from dasha.dialog import Dialog
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.menu import SEPARATOR_LEFT, Menu, MenuItem, separator
from dasha.recovery import Recovery
from dasha.shortcuts import Shortcuts
from dasha.statusbar import StatusBar, status_text
from dasha.terminal import Terminal
from dasha.widgets import TextArea, TextBox
from dasha.window import Window
from tests.support import without_styles
from tests.test_application import Hello
from tests.test_manager import FakeTerminal


class StatusTextTests(unittest.TestCase):
    """Status text is optional and never causes an error."""

    def test_sources_without_text_give_empty(self) -> None:
        """No attribute, None, empty or non-text all mean nothing to show."""

        class Plain:  # pylint: disable=too-few-public-methods
            """Has no status attribute at all."""

        class Odd:  # pylint: disable=too-few-public-methods
            """Has a status that is not text."""

            status = 42

        for source in (
            None,
            Plain(),
            Odd(),
            MenuItem("x"),
            Window("w", Rect(0, 0, 3, 3)),
        ):
            self.assertEqual(status_text(source), "")

    def test_text_is_returned(self) -> None:
        """A string status is used as it is."""
        self.assertEqual(
            status_text(MenuItem("&Open", status="Opens a file")), "Opens a file"
        )


class StatusBarPaintTests(unittest.TestCase):
    """Drawing the bottom row."""

    def test_paints_text_on_bottom_row(self) -> None:
        """Text on the bottom row."""
        canvas = Canvas(12, 3)
        status_bar = StatusBar()
        status_bar.paint(canvas, "Opens a file")
        self.assertEqual(canvas.text(2), " Opens a fil")
        self.assertEqual(canvas.cell(2, 0), (" ", status_bar.style))
        self.assertEqual(canvas.text(1), " " * 12)

    def test_blank_and_multiline_text(self) -> None:
        """Empty text leaves a blank bar; only the first line is shown."""
        canvas = Canvas(10, 2)
        StatusBar().paint(canvas, "")
        self.assertEqual(canvas.text(1), " " * 10)
        StatusBar().paint(canvas, "one\ntwo")
        self.assertEqual(canvas.text(1), " one      ")

    def test_empty_canvas(self) -> None:
        """A zero-height canvas is not an error."""
        StatusBar().paint(Canvas(5, 0), "text")


class ManagerStatusTests(unittest.TestCase):
    """What the status bar says, as focus moves."""

    def setUp(self) -> None:
        self.file = Menu(
            "&File",
            [
                MenuItem("&Open", print, "F3", "Opens a file"),
                MenuItem("&Save", print),  # no status text
                separator(),
                MenuItem("E&xit", print, status="Leaves"),
            ],
        )
        self.with_status = Window(
            "A", Rect(1, 0, 4, 10), status="Window A", menus=[self.file]
        )
        self.without_status = Window("B", Rect(2, 30, 4, 10))
        self.manager = PresentationManager(
            windows=[self.with_status, self.without_status]
        )
        self.manager.handle_resize(40, 10)

    def test_active_window_status(self) -> None:
        """The active window's text shows; a window without any shows nothing."""
        self.assertEqual(self.manager.status(), "")
        self.manager.bring_to_front(self.with_status)
        self.assertEqual(self.manager.status(), "Window A")
        self.manager.remove(self.with_status)
        self.manager.remove(self.without_status)
        self.assertEqual(self.manager.status(), "")

    def test_highlighted_menu_item_status(self) -> None:
        """With a menu open, the highlighted item's text shows."""
        self.manager.bring_to_front(self.with_status)
        self.manager.handle_event("alt+f")
        self.assertEqual(self.manager.status(), "Opens a file")
        self.manager.handle_event("down")
        self.assertEqual(self.manager.status(), "")  # Save has none
        self.manager.handle_event("down")
        self.assertEqual(self.manager.status(), "Leaves")
        self.manager.handle_event("escape")
        self.assertEqual(self.manager.status(), "Window A")

    def test_status_bar_is_drawn(self) -> None:
        """The status bar is drawn."""
        self.manager.bring_to_front(self.with_status)
        canvas = Canvas(40, 10)
        self.manager.compose(canvas)
        self.assertEqual(
            canvas.text(9).rstrip(), " Dasha Desktop │ Window A      F10 Menu"
        )

    def test_open_menu_covers_status_bar(self) -> None:
        """A drop-down reaching the bottom row is drawn over the status bar."""
        self.manager.bring_to_front(self.with_status)
        self.manager.handle_resize(40, 5)
        self.manager.handle_event("alt+f")
        canvas = Canvas(40, 5)
        self.manager.compose(canvas)
        # File's drop-down starts at column 3, its frame (after the blank side
        # column) at 4; its separator lands on row 4.
        self.assertEqual(canvas.cell(4, 4)[0], SEPARATOR_LEFT)


def move(row: int, column: int) -> MouseEvent:
    """A mouse move with no button.

    :param row: Screen row.
    :param column: Screen column.
    """
    return MouseEvent("move", "none", row, column)


class MenuKeyHintTests(unittest.TestCase):
    """The menu key hint."""

    def test_on_an_empty_desktop(self) -> None:
        """No application, no window: still F10 Menu."""
        manager = PresentationManager()
        manager.handle_resize(40, 10)
        self.assertEqual(manager.key_hints(), [("F10", "Menu")])
        canvas = Canvas(40, 10)
        manager.compose(canvas)
        self.assertTrue(canvas.text(9).rstrip().endswith("F10 Menu"))

    def test_first_before_the_widgets_keys(self) -> None:
        """First before the widget's keys."""
        manager = PresentationManager()
        window = Window("Notes", Rect(2, 2, 8, 30))
        window.add(TextArea(0, 0, 20, 2))
        window.add(TextBox(3, 0, 20))
        manager.add(window)
        hints = manager.key_hints()
        self.assertEqual(hints[0], ("F10", "Menu"))
        self.assertGreater(len(hints), 1)

    def test_follows_the_shortcuts(self) -> None:
        """Follows the shortcuts."""
        remapped = PresentationManager(shortcuts=Shortcuts({"open_menu": ["f9"]}))
        self.assertEqual(remapped.key_hints(), [("F9", "Menu")])
        unbound = PresentationManager(shortcuts=Shortcuts({"open_menu": []}))
        self.assertEqual(unbound.key_hints(), [])

    def test_not_while_it_would_not_open(self) -> None:
        """Not while it would not open."""
        manager = PresentationManager()
        manager.handle_event("f10")
        self.assertEqual(manager.key_hints(), [])
        manager.handle_event("escape")
        dialog = Window("Question", Rect(2, 2, 6, 30))
        dialog.modal = True
        manager.add(dialog)
        self.assertEqual(manager.key_hints(), [])
        manager.remove(dialog)
        alone = PresentationManager()
        alone.show_system_menu = False
        alone.launch(Hello)
        alone.add(Window("No application's", Rect(4, 4, 6, 30)))  # menus inert
        self.assertEqual(alone.key_hints(), [])


class HintClickTests(unittest.TestCase):
    """A click on a key hint presses that key."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.handle_resize(80, 24)

    def click_hint(self, key: str, on_label: bool = False) -> None:
        """A left press on a hint.

        :param key: The hint's key.
        :param on_label: Whether to press its label.
        """
        places = self.manager.status_bar.hint_places(
            80, self.manager.key_hints(), self.manager.status_owner
        )
        begin = next(begin for begin, _, (shown, _) in places if shown == key)
        column = begin + 1 + (len(key) + 1 if on_label else 0)
        self.manager.handle_event(MouseEvent("press", "left", 23, column))

    def test_f10_opens_the_menu_bar(self) -> None:
        """F10 opens the menu bar."""
        self.click_hint("F10")
        self.assertTrue(self.manager.menu_bar.is_open)
        self.manager.handle_event("escape")
        self.click_hint("F10", on_label=True)
        self.assertTrue(self.manager.menu_bar.is_open)

    def test_a_widgets_key(self) -> None:
        """A text area's Ctrl+Tab: the focus moves to the next widget."""
        window = Window("Notes", Rect(2, 2, 8, 30))
        window.add(TextArea(0, 0, 20, 2, text="hello"))
        box = window.add(TextBox(3, 0, 20))
        self.manager.add(window)
        self.click_hint("Ctrl+Tab")
        self.assertIs(window.focused, box)

    def test_elsewhere_on_the_bar_nothing(self) -> None:
        """Elsewhere on the bar, nothing."""
        for column in (1, 10, 80 - len("F10Menu") - 3):  # the gap before it
            self.manager.handle_event(MouseEvent("press", "left", 23, column))
            self.assertFalse(self.manager.menu_bar.is_open, column)

    def test_in_a_dialog(self) -> None:
        """In a dialog."""
        dialog = Dialog("Name", 40, 8)
        dialog.add(TextArea(0, 2, 20, 2))
        box = dialog.add(TextBox(3, 2, 20))
        self.manager.add(dialog)
        dialog.modal = True
        places = self.manager.status_bar.hint_places(
            80, self.manager.key_hints(), self.manager.status_owner
        )
        begin = next(begin for begin, _, (key, _) in places if key == "Ctrl+Tab")
        self.manager.handle_modal_event(
            dialog, MouseEvent("press", "left", 23, begin + 1)
        )
        self.assertIs(dialog.focused, box)


class HoverTests(unittest.TestCase):
    """Hovering in an open menu."""

    def setUp(self) -> None:
        self.chosen: list[str] = []
        self.file = Menu(
            "&File",
            [
                MenuItem(
                    "&Open", lambda: self.chosen.append("open"), status="Opens a file"
                ),
                separator(),
                MenuItem("&Save", lambda: self.chosen.append("save"), status="Saves"),
            ],
        )
        self.help = Menu(
            "&Help", [MenuItem("&About", print, status="About Dasha Desktop")]
        )
        window = Window("W", Rect(2, 2, 4, 10), menus=[self.file, self.help])
        self.manager = PresentationManager(windows=[window])
        self.manager.handle_resize(40, 12)
        self.manager.handle_event("alt+f")  # File: title at columns 4-9

    def test_hover_highlights_items(self) -> None:
        """Moving over an item highlights it and updates the status bar."""
        rect = self.manager.menu_bar.dropdown_rect(40)
        assert rect is not None
        self.manager.handle_event(move(rect.row + 3, rect.column + 3))
        self.assertEqual(self.manager.status(), "Saves")
        self.manager.handle_event(move(rect.row + 2, rect.column + 3))  # separator
        self.assertEqual(self.manager.status(), "Saves")
        self.manager.handle_event(move(9, 30))  # away from the menu
        self.assertEqual(self.manager.status(), "Saves")

    def test_hover_over_other_title_switches_menu(self) -> None:
        """With a menu open, moving across the bar opens the menu underneath."""
        self.manager.handle_event(move(0, 11))
        self.assertIs(self.manager.menu_bar.open_menu, self.help)
        self.assertEqual(self.manager.status(), "About Dasha Desktop")

    def test_press_drag_release_chooses(self) -> None:
        """Press, drag and release chooses."""
        self.manager.handle_event("escape")
        self.manager.handle_event(MouseEvent("press", "left", 0, 5))
        rect = self.manager.menu_bar.dropdown_rect(40)
        assert rect is not None
        self.manager.handle_event(MouseEvent("drag", "left", rect.row + 3, 5))
        self.manager.handle_event(MouseEvent("release", "left", rect.row + 3, 5))
        self.assertEqual(self.chosen, ["save"])
        self.assertFalse(self.manager.menu_bar.is_open)

    def test_moves_without_open_menu_change_nothing(self) -> None:
        """Hovering with no menu open does not open one or raise windows."""
        self.manager.handle_event("escape")
        self.manager.handle_event(move(0, 5))
        self.manager.handle_event(move(3, 3))
        self.assertFalse(self.manager.menu_bar.is_open)


class LayeringTests(unittest.TestCase):
    """Windows pass under the status bar."""

    def setUp(self) -> None:
        self.back = Window("Back", Rect(5, 0, 6, 20))  # rows 5-10 on 10 lines
        self.front = Window("Front", Rect(1, 25, 4, 10))
        self.manager = PresentationManager(windows=[self.back, self.front])
        self.manager.handle_resize(40, 10)

    def test_window_is_drawn_under_status_bar(self) -> None:
        """Windows are drawn under the status bar."""
        canvas = Canvas(40, 10)
        self.manager.compose(canvas)
        self.assertEqual(canvas.cell(9, 0), (" ", self.manager.status_bar.style))
        self.assertEqual(canvas.cell(8, 0)[0], self.back.inactive_border.vertical)

    def test_click_on_status_bar_does_not_reach_window(self) -> None:
        """Clicking the status bar over a hidden window does not raise it."""
        self.manager.handle_event(MouseEvent("press", "left", 9, 3))
        self.assertIs(self.manager.active_window, self.front)
        self.manager.handle_event(MouseEvent("press", "left", 8, 3))
        self.assertIs(self.manager.active_window, self.back)

    def test_cannot_drag_title_under_status_bar(self) -> None:
        """The title bar stops on the last row above the status bar."""
        self.manager.handle_event(MouseEvent("press", "left", 1, 27))
        self.manager.handle_event(MouseEvent("drag", "left", 9, 27))
        self.assertEqual(self.front.rect.row, 8)


DIVIDER = StatusBar.divider


class OwnerTests(unittest.TestCase):
    """The active application's name, on the left of the status bar."""

    def test_painted_first(self) -> None:
        """The name and a divider, then the text."""
        canvas = Canvas(40, 2)
        StatusBar().paint(canvas, "Typing", owner="Notepad")
        self.assertEqual(canvas.text(1).rstrip(), f" Notepad {DIVIDER} Typing")

    def test_text_gives_way_to_the_name_and_hints(self) -> None:
        """Short of room, the text is cut, not the name."""
        canvas = Canvas(30, 2)
        StatusBar().paint(canvas, "A long status text", [("F1", "Help")], "Notepad")
        self.assertEqual(canvas.text(1), f" Notepad {DIVIDER} A long st  F1 Help ")

    def test_named_by_the_manager(self) -> None:
        """Named by the manager."""
        manager = PresentationManager()
        manager.handle_resize(80, 24)
        self.assertEqual(manager.status_owner, "Dasha Desktop")
        first = manager.launch(Hello)
        manager.launch(Hello)
        self.assertEqual(manager.status_owner, "Hello (2)")
        manager.switch_to(first)
        self.assertEqual(manager.status_owner, "Hello")
        canvas = Canvas(80, 24)
        manager.compose(canvas)
        self.assertTrue(canvas.text(23).startswith(f" Hello {DIVIDER} "))
        for application in manager.applications:
            application.quit()
        self.assertEqual(manager.status_owner, "Dasha Desktop")

    def test_standalone(self) -> None:
        """Stand-alone naming."""
        terminal = FakeTerminal(["\x11", "\r"], sizes=[(80, 24)])
        Hello().run(cast(Terminal, terminal))
        shown = without_styles(terminal.output.getvalue())
        self.assertIn(f" Hello {DIVIDER} ", shown)
        self.assertNotIn("dasha", shown.casefold())

    def test_standalone_before_it_is_active(self) -> None:
        """Stand-alone before it is active."""
        manager = PresentationManager()
        manager.stand_alone("Hello")
        manager.handle_resize(40, 10)
        self.assertEqual(manager.status_owner, "")
        canvas = Canvas(40, 10)
        manager.compose(canvas)
        self.assertNotIn(DIVIDER, canvas.text(9))
        self.assertNotIn("dasha", canvas.text(9).casefold())

    def test_standalone_messages(self) -> None:
        """Stand-alone messages."""
        manager = PresentationManager()
        self.assertEqual(manager.program_name, "Dasha Desktop")
        manager.stand_alone("Notepad and Demo")
        self.assertEqual(manager.program_name, "Notepad and Demo")
        recovery = Recovery(name=manager.program_name)
        self.assertIn("Something went wrong in Notepad and Demo", recovery.message)
        self.assertIn("restart Notepad and Demo", recovery.message)
        self.assertNotIn("Dasha Framework", recovery.message)


if __name__ == "__main__":
    unittest.main()
