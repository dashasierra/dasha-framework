"""Tests for widgets following their window's size (``Grow``)."""

import unittest

from dasha.canvas import Rect
from dasha.manager import PresentationManager
from dasha.widgets import Button, Grow, Label, ListBox, TextBox
from dasha.window import Window

NAMES = [f"file{number:02}.txt" for number in range(40)]


def window() -> Window:
    """A 30x10 window: a 28x8 interior."""
    return Window("W", Rect(0, 0, 10, 30), resizable=True, maximisable=True)


class GrowTests(unittest.TestCase):
    """Each flag, and the combinations."""

    def test_default_stays_put(self) -> None:
        """Without grow, resizing the window leaves a widget alone."""
        win = window()
        label = win.add(Label("Hi", 2, 3))
        win.resize(50, 20)
        self.assertEqual(label.rect, Rect(2, 3, 1, 2))

    def test_stretch(self) -> None:
        """WIDTH, HEIGHT and ALL stretch the right and bottom edges."""
        win = window()
        wide = win.add(TextBox(0, 2, 10), grow=Grow.WIDTH)
        tall = win.add(ListBox(NAMES, 2, 0, 10, 4), grow=Grow.HEIGHT)
        both = win.add(ListBox(NAMES, 2, 12, 10, 4), grow=Grow.ALL)
        win.resize(40, 15)  # the interior is 10 wider and 5 taller
        self.assertEqual(wide.rect, Rect(0, 2, 1, 20))
        self.assertEqual(tall.rect, Rect(2, 0, 9, 10))
        self.assertEqual(both.rect, Rect(2, 12, 9, 20))

    def test_stick(self) -> None:
        """STICK_RIGHT and STICK_BOTTOM move a widget, keeping its size."""
        win = window()
        ok = win.add(Button("&OK", 6, 17), grow=Grow.STICK_RIGHT | Grow.STICK_BOTTOM)
        win.resize(40, 15)
        self.assertEqual(ok.rect, Rect(11, 27, 2, 11))

    def test_shrinking_and_growing_back(self) -> None:
        """Shrinking and growing back."""
        win = window()
        box = win.add(ListBox(NAMES, 0, 0, 20, 6), grow=Grow.ALL)
        win.resize(12, 3)  # far smaller than the list box
        self.assertEqual((box.rect.width, box.rect.height), box.min_size())
        win.resize(30, 10)
        self.assertEqual(box.rect, Rect(0, 0, 6, 20))

    def test_maximise_and_restore(self) -> None:
        """Maximising grows the widgets; restoring shrinks them back."""
        win = window()
        box = win.add(ListBox(NAMES, 0, 0, 28, 8, columns=2), grow=Grow.ALL)
        manager = PresentationManager(windows=[win])
        manager.handle_resize(80, 24)
        manager.maximise(win)
        self.assertEqual(box.rect, Rect(0, 0, 20, 78))  # the work area's interior
        manager.restore(win)
        self.assertEqual(box.rect, Rect(0, 0, 8, 28))

    def test_moved_by_code_becomes_the_layout(self) -> None:
        """A widget moved by code is laid out afresh."""
        win = window()
        label = win.add(Label("Hi", 2, 3), grow=Grow.STICK_RIGHT)
        label.rect = Rect(4, 5, 1, 2)
        win.resize(40, 10)
        self.assertEqual(label.rect, Rect(4, 15, 1, 2))

    def test_list_box_keeps_its_highlight_in_view(self) -> None:
        """Shrunk, a list box scrolls so the highlight still shows."""
        win = window()
        box = win.add(ListBox(NAMES, 0, 0, 20, 8), grow=Grow.HEIGHT)
        box.move_to(7)  # the bottom row
        win.resize(30, 6)  # four rows fewer
        self.assertEqual(box.rect.height, 4)
        self.assertEqual(box.first_visible, 4)

    def test_minimum_sizes(self) -> None:
        """Widgets are never made smaller than they can be drawn."""
        self.assertEqual(TextBox(0, 0, 10).min_size(), (3, 1))
        self.assertEqual(Button("&OK", 0, 0).min_size(), (5, 2))
        self.assertEqual(ListBox(NAMES, 0, 0, 20, 5, columns=3).min_size(), (7, 2))
        self.assertEqual(Label("Hi", 0, 0).min_size(), (1, 1))

    def test_moving_does_not_relayout(self) -> None:
        """Only a change of size moves widgets; moving the window does not."""
        win = window()
        box = win.add(TextBox(0, 0, 10), grow=Grow.ALL)
        win.move_to(5, 5)
        self.assertEqual(box.rect, Rect(0, 0, 1, 10))


if __name__ == "__main__":
    unittest.main()
