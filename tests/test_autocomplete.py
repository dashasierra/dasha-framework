"""Tests for autocomplete boxes and the suggestions they drop down."""

import unittest
from typing import cast

from dasha.canvas import Rect
from dasha.dialog import Dialog, SuggestionPopup
from dasha.manager import PresentationManager
from dasha.shortcuts import Shortcuts
from dasha.terminal import Terminal
from dasha.widgets import AutoCompleteBox, Button, match_suggestions
from dasha.window import Window
from tests.support import without_styles
from tests.test_manager import FakeTerminal

SITES = ["example.com", "example.org", "sexagesimal.net", "python.org"]

DOWN = "\x1b[B"
UP = "\x1b[A"


class MatchTests(unittest.TestCase):
    """Which suggestions are like the text."""

    def test_starting_first(self) -> None:
        """Prefix matches come first."""
        self.assertEqual(
            match_suggestions("EXA", SITES),
            ["example.com", "example.org", "sexagesimal.net"],
        )

    def test_none_for_blank_or_exact(self) -> None:
        """Blank text suggests nothing, and the text itself is left out."""
        self.assertEqual(match_suggestions(" ", SITES), [])
        self.assertEqual(match_suggestions("python.org", SITES), [])


class SuggestingTests(unittest.TestCase):
    """Typing in a running window."""

    def setUp(self) -> None:
        self.pressed: list[str] = []
        self.terminal = FakeTerminal([])

    def run_with(self, inputs: list[str], row: int = 2) -> AutoCompleteBox:
        """Run a window with an autocomplete box.

        :param inputs: Input to read.
        :param row: The box's row.
        """
        window = Window("W", Rect(1, 0, 18, 40))
        box = window.add(AutoCompleteBox(row, 2, 20, suggestions=SITES))
        self.pressed.clear()
        window.add(
            Button(
                "OK", 12, 2, default=True, action=lambda b: self.pressed.append("ok")
            )
        )
        manager = PresentationManager(windows=[window])
        self.terminal = FakeTerminal([*inputs, "\x11", "\r"], sizes=[(60, 20)])
        manager.run(cast(Terminal, self.terminal))
        self.assertEqual(self.terminal.inputs, [])
        return box

    def test_free_text(self) -> None:
        """Free text is allowed."""
        box = self.run_with(["e", "x", "z", "\r"])
        self.assertEqual(box.text, "exz")  # matching nothing closed the popup
        self.assertEqual(self.pressed, ["ok"])
        box = self.run_with(["e", "x", "\r"])
        self.assertEqual(box.text, "ex")
        self.assertEqual(self.pressed, ["ok"])

    def test_take_a_suggestion(self) -> None:
        """Down highlights the first, again the second; Enter takes it."""
        box = self.run_with(["e", "x", DOWN, DOWN, "\r"])
        self.assertEqual(box.text, "example.org")
        self.assertEqual(self.pressed, [])

    def test_the_suggestions_follow_the_typing(self) -> None:
        """Shown as the text is typed, narrowed as it goes on."""
        box = self.run_with(["s", "e", "x", DOWN, "\r"])
        self.assertEqual(box.text, "sexagesimal.net")
        self.assertIn(
            "sexagesimal.net", without_styles(self.terminal.output.getvalue())
        )

    def test_up_from_the_first_is_none(self) -> None:
        """Up from the first suggestion highlights none again."""
        box = self.run_with(["p", DOWN, UP, "\r"])
        self.assertEqual((box.text, self.pressed), ("p", ["ok"]))

    def test_escape_keeps_the_text(self) -> None:
        """Escape closes the suggestions, keeping what was typed."""
        box = self.run_with(["p", "y", "\x1b", "", "t", "\x1b", ""])
        self.assertEqual(box.text, "pyt")

    def test_open_without_typing(self) -> None:
        """F4 in an empty box shows every suggestion."""
        box = self.run_with(["\x1bOS", DOWN, DOWN, DOWN, DOWN, "\r"])
        self.assertEqual(box.text, "python.org")

    def test_click_a_suggestion(self) -> None:
        """Clicking a suggestion takes it."""
        box = self.run_with(["e", "\x1b[<0;5;6M", "\x1b[<0;5;6m"])
        self.assertEqual(box.text, "example.com")


class PlacementTests(unittest.TestCase):
    """Where the suggestions drop down."""

    def placed(self, row: int) -> SuggestionPopup:
        """The popup for a box.

        :param row: The box's screen row.
        """
        seen: list[SuggestionPopup] = []

        class Recording(PresentationManager):
            """Shows nothing: just notes the popup."""

            def execute(self, dialog: Dialog) -> str | None:
                assert isinstance(dialog, SuggestionPopup)
                seen.append(dialog)
                return "cancel"

        window = Window("W", Rect(row - 1, 0, 3, 40))
        box = window.add(AutoCompleteBox(0, 4, 20, suggestions=SITES))
        manager = Recording(windows=[window])
        manager.handle_resize(60, 20)
        manager._terminal = cast(Terminal, object())  # pylint: disable=protected-access
        box.text = "e"
        self.assertIsNotNone(manager.suggest(box, box.matches()))
        return seen[0]

    def test_over_the_box(self) -> None:
        """Its first row lines up with the box, the suggestions below."""
        popup = self.placed(row=4)
        self.assertEqual(popup.rect, Rect(3, 4, 6, 22))
        self.assertEqual((popup.view.rect.row, popup.list.rect.row), (0, 1))

    def test_above_near_the_bottom(self) -> None:
        """Near the bottom, suggestions go above."""
        popup = self.placed(row=17)
        self.assertEqual(popup.rect, Rect(13, 4, 6, 22))
        self.assertEqual((popup.list.rect.row, popup.view.rect.row), (0, 3))

    def test_narrowing_keeps_the_box_in_place(self) -> None:
        """Fewer matches shrink it, towards the box."""
        popup = self.placed(row=17)
        for key in "xam":
            popup.handle_key(key, Shortcuts())
        self.assertEqual(popup.rect, Rect(14, 4, 5, 22))  # .com and .org
        self.assertEqual(popup.view.rect.row, 2)

    def test_no_match_closes_it(self) -> None:
        """Typing something nothing matches closes it."""
        popup = self.placed(row=4)
        popup.handle_key("q", Shortcuts())
        self.assertEqual(popup.result, "cancel")
        self.assertEqual(popup.box.text, "eq")


if __name__ == "__main__":
    unittest.main()
