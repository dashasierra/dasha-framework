"""Tests for the edges of popups: drop-down lists, suggestions and menus."""

# pylint: disable=protected-access

import unittest
from typing import cast
from unittest import mock

from dasha.canvas import Rect
from dasha.dialog import (
    ListPopup,
    MenuPopup,
    SuggestionPopup,
    _SuggestionList,
    question,
)
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuItem, separator
from dasha.shortcuts import Shortcuts
from dasha.terminal import Terminal
from dasha.widgets import AutoCompleteBox
from dasha.window import Window

SITES = ["example.com", "example.org", "sexagesimal.net", "python.org"]


def click(row: int, column: int, button: str = "left") -> MouseEvent:
    """A press at a screen position.

    :param row: Screen row.
    :param column: Screen column.
    :param button: The button.
    """
    return MouseEvent("press", button, row, column)


class ListPopupTests(unittest.TestCase):
    """A drop-down list."""

    def setUp(self) -> None:
        self.popup = ListPopup(["one", "two"], selected=0, width=10, rows=4)

    def test_choosing_in_the_list_answers(self) -> None:
        """Choosing the highlighted item answers OK."""
        self.popup.list.choose()
        self.assertEqual(self.popup.result, "ok")
        self.assertEqual(self.popup.chosen, 0)

    def test_a_click_below_the_items_chooses_nothing(self) -> None:
        """A click on an empty row leaves it open."""
        interior = self.popup.interior
        self.popup.handle_mouse(click(interior.row + 3, interior.column + 1))
        self.assertIsNone(self.popup.result)


class SuggestionListTests(unittest.TestCase):
    """The suggestions list on its own."""

    def setUp(self) -> None:
        self.list = _SuggestionList(["a", "b", "c", "d"], row=0, width=10, rows=2)

    def test_moving_scrolls(self) -> None:
        """Moving past the last row shown, or above the first, scrolls."""
        self.list.move(3)
        self.assertEqual((self.list.highlight, self.list.first), (2, 1))
        self.list.move(-2)
        self.assertEqual((self.list.highlight, self.list.first), (0, 0))

    def test_the_wheel_and_other_buttons(self) -> None:
        """The wheel moves the highlight; other buttons are not used; a
        click on no item chooses nothing."""
        down = MouseEvent("scroll", "down", 0, 0)
        up = MouseEvent("scroll", "up", 0, 0)
        self.assertTrue(self.list.handle_mouse(down, 0, 0))
        self.assertTrue(self.list.handle_mouse(down, 0, 0))
        self.assertTrue(self.list.handle_mouse(up, 0, 0))
        self.assertEqual(self.list.highlight, 0)
        self.assertFalse(self.list.handle_mouse(click(0, 0, "right"), 0, 0))
        self.list.items = ["a"]
        self.assertTrue(self.list.handle_mouse(click(0, 0), 1, 0))
        self.assertFalse(self.list.chosen)


class SuggestionPopupTests(unittest.TestCase):
    """An autocomplete box's popup, used directly."""

    def setUp(self) -> None:
        window = Window("W", Rect(3, 0, 3, 40))
        self.box = window.add(AutoCompleteBox(0, 4, 20, suggestions=SITES))
        manager = PresentationManager(windows=[window])
        manager.handle_resize(60, 20)
        manager._terminal = cast(Terminal, object())
        self.box.text = "e"
        with mock.patch.object(manager, "execute", return_value="cancel"):
            popup = manager.suggest(self.box, self.box.matches())
        assert isinstance(popup, SuggestionPopup)
        self.popup = popup

    def test_keys_that_change_no_text(self) -> None:
        """A key that leaves the text as it was keeps the suggestions."""
        before = list(self.popup.list.items)
        self.popup.handle_key("left", Shortcuts())
        self.assertEqual(self.popup.list.items, before)
        self.assertIsNone(self.popup.result)

    def test_pasting_narrows_the_suggestions(self) -> None:
        """Pasted text is typed into the box, and the suggestions follow."""
        self.assertTrue(self.popup.handle_paste("xample.o"))
        self.assertEqual(self.box.text, "example.o")
        self.assertEqual(self.popup.list.items, ["example.org"])

    def test_the_box_view_passes_on_mouse_and_timers(self) -> None:
        """The box drawn in the popup gets the mouse and timers, at its own
        place."""
        view = self.popup.view
        self.assertEqual(
            view._shift(view.rect.row, 3),
            (self.box.rect.row, self.box.rect.column + 3),
        )
        release = MouseEvent("release", "left", 0, 0)
        self.assertEqual(
            view.handle_mouse(release, view.rect.row, 0),
            self.box.handle_mouse(release, self.box.rect.row, self.box.rect.column),
        )
        view.on_timer(0.0)

    def test_a_click_on_no_suggestion(self) -> None:
        """A click away from the suggestions chooses nothing."""
        self.popup.handle_mouse(MouseEvent("release", "left", 0, 0))
        self.assertIsNone(self.popup.result)


class MenuPopupTests(unittest.TestCase):
    """A pop-up menu's edges."""

    def test_nothing_available(self) -> None:
        """With nothing to choose, nothing is highlighted, and choosing an
        unavailable item does nothing."""
        menu = Menu("M", [separator(), MenuItem("&Off")])
        popup = MenuPopup(menu)
        self.assertEqual(popup.items.highlight, -1)
        self.assertEqual(popup.status, "")
        popup.choose(1)
        self.assertIsNone(popup.result)

    def test_a_submenu_outside_a_desktop(self) -> None:
        """A submenu needs a desktop to open on."""
        sub = Menu("S", [MenuItem("&Deep", action=lambda: None)])
        popup = MenuPopup(Menu("M", [MenuItem("&More", submenu=sub)]))
        popup.choose(0)
        self.assertIsNone(popup.result)

    def test_keys_not_for_the_menu(self) -> None:
        """A letter no item has is taken; other keys are not."""
        popup = MenuPopup(Menu("M", [MenuItem("&Go", action=lambda: None)]))
        self.assertTrue(popup.handle_key("z", Shortcuts()))
        self.assertIsNone(popup.result)
        self.assertFalse(popup.handle_key("f9", Shortcuts()))


class QuestionTests(unittest.TestCase):
    """Question dialogs."""

    def test_needs_an_answer(self) -> None:
        """A question with no answers is refused."""
        with self.assertRaises(ValueError):
            question("Q", "Which?", [])


if __name__ == "__main__":
    unittest.main()
