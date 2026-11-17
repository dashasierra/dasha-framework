"""Tests for splitters: two panes, and a divider between them."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.widgets import Collapsible, GroupBox, Grow, Label, ListBox, Splitter
from dasha.widgets.splitter import ACROSS, STACKED
from dasha.window import Window


class SplitterTests(unittest.TestCase):
    """A splitter 40 wide and 8 tall, the divider at 15: a list filling the
    left pane, a label in the right one."""

    def setUp(self) -> None:
        self.changes: list[int] = []
        self.window = Window("W", Rect(0, 0, 12, 50), resizable=True)
        self.splitter = self.window.add(
            Splitter(
                0,
                0,
                40,
                8,
                position=15,
                minimum=5,
                on_change=lambda s: self.changes.append(s.value),
            ),
            grow=Grow.ALL,
        )
        self.items = self.splitter.first.add(ListBox(["a", "b"], 0, 0, 15, 8))
        self.items.grow = Grow.ALL
        self.label = self.splitter.second.add(Label("right", 1, 2))

    def keys(self, *names: str) -> None:
        """Keys to the splitter."""
        for name in names:
            self.assertTrue(self.splitter.handle_key(name, Shortcuts()), name)

    def mouse(self, action: str, column: int) -> None:
        """A left button event on the splitter's row 3, at a content column."""
        self.splitter.handle_mouse(MouseEvent(action, "left", 3, column), 3, column)

    def test_panes(self) -> None:
        """Side by side, the divider between them."""
        self.assertEqual(self.splitter.pane_rect(False), Rect(0, 0, 8, 15))
        self.assertEqual(self.splitter.pane_rect(True), Rect(0, 16, 8, 24))
        self.assertEqual((self.label.rect.row, self.label.rect.column), (1, 18))
        canvas = Canvas(40, 8)
        self.splitter.paint(canvas, canvas.bounds, False)
        self.assertEqual([canvas.text(r)[15] for r in range(8)], [ACROSS] * 8)

    def test_keys_move_the_divider(self) -> None:
        """Right moves it on: the list grows, the label moves with its pane."""
        self.keys("right", "right")
        self.assertEqual(self.splitter.position, 17)
        self.assertEqual(self.items.rect.width, 17)
        self.assertEqual(self.label.rect.column, 20)
        self.keys("left")
        self.assertEqual(self.changes, [16, 17, 16])

    def test_kept_to_the_minimum(self) -> None:
        """Neither pane is made smaller than the minimum."""
        self.splitter.position = 1
        self.assertEqual(self.splitter.position, 5)
        self.splitter.position = 100
        self.assertEqual(self.splitter.position, 40 - 1 - 5)
        self.assertEqual(self.changes, [])  # from code: no one told

    def test_dragging(self) -> None:
        """A press on the divider and a drag moves it; a press elsewhere is
        not taken."""
        self.mouse("press", 15)
        self.mouse("drag", 25)
        self.mouse("release", 25)
        self.assertEqual(self.splitter.position, 25)
        self.assertEqual(self.items.rect.width, 25)
        press = MouseEvent("press", "left", 3, 30)
        self.assertFalse(self.splitter.handle_mouse(press, 3, 30))
        self.assertFalse(
            self.splitter.handle_mouse(MouseEvent("drag", "left", 3, 2), 3, 2)
        )
        right = MouseEvent("press", "right", 3, 15)
        self.assertFalse(self.splitter.handle_mouse(right, 3, 15))

    def test_the_window_resized(self) -> None:
        """The splitter grows with the window, and the second pane takes the
        room; the list in the first pane only grows taller."""
        rect = self.window.rect
        self.window.rect = Rect(rect.row, rect.column, rect.height + 2, rect.width + 6)
        self.assertEqual(self.splitter.rect.width, 46)
        self.assertEqual(self.splitter.position, 15)
        self.assertEqual((self.items.rect.width, self.items.rect.height), (15, 10))
        self.assertEqual(self.splitter.pane_rect(True).width, 30)

    def test_the_window_made_smaller(self) -> None:
        """Shrunk below its height, the splitter shrinks too, and so does
        the list in it: the list scrolls by itself, not the window."""
        rect = self.window.rect
        self.window.rect = Rect(rect.row, rect.column, 6, rect.width)
        # The window lost 6 rows, so the 8-row splitter is left with 2.
        self.assertEqual((self.splitter.rect.height, self.items.rect.height), (2, 2))
        self.assertEqual(self.window.max_scroll, (0, 0))

    def test_focused_divider(self) -> None:
        """Drawn in its focused colours while it has the focus."""
        canvas = Canvas(40, 8)
        self.splitter.paint(canvas, canvas.bounds, True)
        self.assertTrue(canvas.cell(0, 15)[1].reverse != Window.body_style.reverse)
        self.assertEqual(self.splitter.min_size(), (11, 1))

    def click(self, button: str, column: int) -> None:
        """Press and release a button on the window, at row 3 of the
        content."""
        row, left = self.window.interior.row + 3, self.window.interior.column
        for action in ("press", "release"):
            self.window.handle_mouse(MouseEvent(action, button, row, left + column))

    def test_a_click_a_pane_does_not_use_keeps_the_focus_there(self) -> None:
        """A click on a pane's widget that the widget does not use (the
        right button on a list, with no menu) focuses that widget, not the
        splitter behind it, which is offered the click next."""
        self.window.focus(self.splitter)
        self.click("right", 4)
        self.assertIs(self.window.focused, self.items)
        self.click("middle", 4)
        self.assertIs(self.window.focused, self.items)

    def test_a_click_on_the_divider_focuses_the_splitter(self) -> None:
        """The divider is the splitter's own: a click there focuses it."""
        self.window.focus(self.items)
        self.click("left", 15)
        self.assertIs(self.window.focused, self.splitter)


class StackedTests(unittest.TestCase):
    """One pane above the other."""

    def test_stacked(self) -> None:
        """The divider ─ across; Down moves it down, the bottom pane's
        widgets with it."""
        window = Window("W", Rect(0, 0, 14, 30))
        splitter = window.add(Splitter(0, 0, 20, 9, vertical=True, position=4))
        below = splitter.second.add(Label("below", 0, 1))
        self.assertEqual(below.rect.row, 5)
        splitter.handle_key("down", Shortcuts())
        self.assertEqual(below.rect.row, 6)
        canvas = Canvas(20, 9)
        splitter.paint(canvas, canvas.bounds, False)
        self.assertEqual(canvas.text(5), STACKED * 20)
        self.assertEqual(splitter.min_size(), (1, 3))
        with self.assertRaises(ValueError):
            Splitter(0, 0, 2, 9)


class NestingTests(unittest.TestCase):
    """Splitters with containers, and in them."""

    def test_group_box_in_a_pane(self) -> None:
        """A group box in the second pane moves with the divider, its
        widgets with it."""
        window = Window("W", Rect(0, 0, 14, 50))
        splitter = window.add(Splitter(0, 0, 40, 10, position=10))
        group = splitter.second.add(GroupBox("&G", 0, 0, 20, 4))
        inside = group.add(Label("in", 0, 0))
        splitter.position = 14
        self.assertEqual((group.rect.column, inside.rect.column), (15, 16))

    def test_in_a_collapsible_area(self) -> None:
        """Opening an area above moves the splitter and its panes' widgets
        down; moving the divider afterwards moves them only sideways."""
        window = Window("W", Rect(0, 0, 20, 50))
        area = window.add(Collapsible("Area", 0, 0))
        area.add(Label("in the area", 0, 2))
        splitter = window.add(Splitter(1, 0, 40, 6, position=10))
        right = splitter.second.add(Label("right", 0, 0))
        area.expand()
        self.assertEqual((splitter.rect.row, right.rect.row), (2, 2))
        splitter.position = 12
        self.assertEqual((right.rect.row, right.rect.column), (2, 13))


if __name__ == "__main__":
    unittest.main()
