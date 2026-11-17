"""Tests for tabs: pages of widgets, one showing at a time."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.dialog import Dialog
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.widgets import Button, GroupBox, Label, Splitter, Tabs, TextBox
from dasha.widgets.tabs import DIVIDER, JOIN, LINE, OPEN_LEFT, OPEN_RIGHT
from dasha.window import Window
from tests.support import painted


class TabsTests(unittest.TestCase):
    """Tabs with General and Advanced pages, a text box on each, in a
    window with a button below the tabs."""

    def setUp(self) -> None:
        self.changes: list[int] = []
        self.window = Window("W", Rect(0, 0, 12, 40))
        self.tabs = self.window.add(
            Tabs(0, 0, 30, 6, on_change=lambda t: self.changes.append(t.value))
        )
        self.general = self.tabs.add_page("&General")
        self.advanced = self.tabs.add_page("&Advanced")
        self.name = self.general.add(TextBox(0, 1, 10, name="name"))
        self.level = self.advanced.add(TextBox(1, 1, 10, name="level"))
        self.ok = self.window.add(Button("&OK", 7, 1))

    def keys(self, *names: str) -> None:
        """Keys to the window."""
        for name in names:
            self.window.handle_key(name, Shortcuts())

    def drawn(self) -> Canvas:
        """The window painted."""
        return painted(self.window)

    def test_drawn(self) -> None:
        """The tabs, divided; the line under them open under the chosen one."""
        canvas = self.drawn()
        self.assertEqual(canvas.text(1)[1:22], f" General {DIVIDER} Advanced {DIVIDER}")
        self.assertEqual(canvas.text(2)[1:12], " " * 9 + OPEN_RIGHT + LINE)
        self.assertEqual(canvas.text(2)[21], JOIN)  # below a tab not chosen
        self.assertTrue(canvas.cell(1, 2)[1].bold)  # the chosen tab
        self.assertTrue(canvas.cell(1, 2)[1].underline)  # its letter, G

    def test_the_chosen_tab_opens(self) -> None:
        """The line turns up into the chosen tab's sides, ┘ and └."""
        self.tabs.select(1)
        canvas = self.drawn()
        self.assertEqual(
            canvas.text(2)[1:23], LINE * 9 + OPEN_LEFT + " " * 10 + OPEN_RIGHT + LINE
        )

    def test_only_the_chosen_page_shows(self) -> None:
        """The first page's widgets show, the second's do not."""
        self.assertTrue(self.name.is_shown)
        self.assertFalse(self.level.is_shown)
        self.assertEqual((self.name.rect.row, self.level.rect.row), (2, 3))
        self.tabs.select(1)
        self.assertFalse(self.name.is_shown)
        self.assertTrue(self.level.is_shown)
        self.assertEqual(self.tabs.selected_page, self.advanced)
        self.assertEqual(self.changes, [1])

    def test_left_and_right_on_the_tabs(self) -> None:
        """With the tabs focused, Right and Left choose the tab beside."""
        self.window.focus(self.tabs)
        self.keys("right")
        self.assertEqual(self.tabs.selected, 1)
        self.keys("right")  # no further
        self.keys("left")
        self.assertEqual(self.changes, [1, 0])

    def test_ctrl_pagedown_anywhere(self) -> None:
        """From a widget on the page, Ctrl+PgDn and Ctrl+PgUp change page,
        round from the last to the first; the focus, left on a page that no
        longer shows, goes to the tabs."""
        self.window.focus(self.name)
        self.keys("ctrl+pagedown")
        self.assertEqual(self.tabs.selected, 1)
        self.assertIs(self.window.focused, self.tabs)
        self.keys("ctrl+pagedown")
        self.assertEqual(self.tabs.selected, 0)
        self.keys("ctrl+pageup")
        self.assertEqual(self.tabs.selected, 1)

    def test_focus_elsewhere_stays(self) -> None:
        """Changing page from the OK button leaves the focus on it."""
        self.window.focus(self.ok)
        self.keys("ctrl+pagedown")
        self.assertIs(self.window.focused, self.ok)

    def test_tab_goes_through_the_chosen_page(self) -> None:
        """Tab: the tabs, the page's widgets, then the rest."""
        self.window.focus(self.tabs)
        self.keys("tab")
        self.assertIs(self.window.focused, self.name)
        self.keys("tab")
        self.assertIs(self.window.focused, self.ok)

    def test_clicks_and_letters(self) -> None:
        """A click on a tab chooses it; so does its letter."""
        interior = self.window.interior
        press = MouseEvent("press", "left", interior.row, interior.column + 13)
        self.window.handle_mouse(press)
        self.window.handle_mouse(MouseEvent("release", "left", press.row, press.column))
        self.assertEqual(self.tabs.selected, 1)
        self.keys("alt+g")
        self.assertEqual(self.tabs.selected, 0)
        between = MouseEvent("press", "left", interior.row, interior.column + 25)
        self.assertFalse(self.window.handle_mouse(between))  # beyond the tabs
        self.assertEqual(self.tabs.tab_at(9), None)  # on a divider

    def test_values_include_every_page(self) -> None:
        """Every page's named widgets count, chosen or not."""
        self.assertEqual(set(self.window.values), {"name", "level"})

    def test_no_pages(self) -> None:
        """Tabs with no pages yet: nothing to choose, nothing breaks."""
        tabs = Tabs(0, 0, 10, 3)
        self.assertIsNone(tabs.selected_page)
        tabs.select(2)
        tabs.step(1)
        self.assertFalse(tabs.window_key("ctrl+pagedown", Shortcuts()))
        with self.assertRaises(ValueError):
            Tabs(0, 0, 10, 2)
        with self.assertRaisesRegex(ValueError, "tabs"):
            tabs.add_page("A").add(Label("x", 0, 0))
        self.assertEqual(tabs.min_size(), (1, 3))


class NestingTests(unittest.TestCase):
    """Tabs in a dialog, holding a group box and a splitter."""

    def test_nested(self) -> None:
        """A group box on one page, a splitter on another: what each holds
        shows with its page."""
        dialog = Dialog("D", 50, 16)
        tabs = dialog.add(Tabs(0, 1, 46, 10))
        one, two = tabs.add_page("&One"), tabs.add_page("&Two")
        group = one.add(GroupBox("&Group", 0, 0, 20, 4))
        inside = group.add(TextBox(0, 1, 10))
        splitter = two.add(Splitter(0, 0, 40, 6))
        left = splitter.first.add(Label("left", 0, 0))
        self.assertTrue(inside.is_shown and not left.is_shown)
        tabs.select(1)
        self.assertTrue(left.is_shown and not inside.is_shown)
        self.assertEqual(left.rect.row, 2)


if __name__ == "__main__":
    unittest.main()
