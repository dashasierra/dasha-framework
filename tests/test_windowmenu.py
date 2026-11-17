"""Tests for a window's own Window menu (``windowmenu.window_menu``)."""

import unittest

from dasha.canvas import Rect
from dasha.manager import PresentationManager
from dasha.menu import Menu
from dasha.windowmenu import window_menu
from dasha.window import Window


def labels(menu: Menu) -> list[str]:
    """A menu's labels, separators as ""."""
    return [item.label for item in menu.items]


class WindowMenuTests(unittest.TestCase):
    """What a window's Window menu offers, and what each item does."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.handle_resize(80, 24)
        self.back = Window("Back", Rect(1, 0, 6, 20), closable=True)
        self.window = Window(
            "Front",
            Rect(3, 10, 8, 30),
            resizable=True,
            maximisable=True,
            minimisable=True,
            closable=True,
        )
        for window in (self.back, self.window):
            self.manager.add(window)

    def choose(self, menu: Menu, label: str) -> None:
        """Run an item's action."""
        item = next(item for item in menu.items if item.label == label)
        assert item.action is not None
        item.action()

    def test_everything_a_window_allows(self) -> None:
        """Every item, with the keys from the shortcuts."""
        menu = window_menu(self.manager, self.window)
        self.assertEqual(menu.title, "&Window")
        self.assertTrue(menu.lists_minimised)
        self.assertEqual(
            [label for label in labels(menu) if label],
            [
                "Ma&ximise / restore",
                "Mi&nimise",
                "&Move",
                "&Size",
                "Send to &back",
                "&Next window",
                "&Close",
            ],
        )
        maximise = menu.items[0]
        self.assertEqual(
            maximise.shortcut, self.manager.shortcuts.hint("maximise_window")
        )

    def test_only_what_it_allows(self) -> None:
        """A plain window: no Maximise, Minimise or Size."""
        menu = window_menu(self.manager, self.back)
        for missing in ("Ma&ximise / restore", "Mi&nimise", "&Size"):
            self.assertNotIn(missing, labels(menu))
        self.assertIn("&Move", labels(menu))

    def test_the_items_act_on_the_window(self) -> None:
        """Maximise, send to back, next window, minimise and close."""
        menu = window_menu(self.manager, self.window)
        self.choose(menu, "Ma&ximise / restore")
        self.assertTrue(self.window.maximised)
        self.choose(menu, "Ma&ximise / restore")
        self.assertFalse(self.window.maximised)
        self.choose(menu, "Send to &back")
        self.assertIs(self.manager.windows[0], self.window)
        self.choose(menu, "&Next window")
        self.assertIs(self.manager.windows[-1], self.window)
        self.choose(menu, "Mi&nimise")
        self.assertIn(self.window, self.manager.minimised)
        self.manager.show_window(self.window)
        self.choose(menu, "&Close")
        self.assertNotIn(self.window, self.manager.windows)

    def test_move_and_size_start_adjusting(self) -> None:
        """Move and Size start moving or resizing it with the keyboard."""
        menu = window_menu(self.manager, self.window)
        self.choose(menu, "&Move")
        self.assertTrue(self.window.adjusting)
        self.manager.handle_event("enter")
        self.choose(menu, "&Size")
        self.assertTrue(self.window.adjusting)


if __name__ == "__main__":
    unittest.main()
