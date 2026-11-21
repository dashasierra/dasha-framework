"""Tests for collapsible areas."""

import unittest

from dasha import theme
from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.scrollbar import DOWN, RIGHT
from dasha.shortcuts import Shortcuts
from dasha.style import BLUE, BRIGHT_BLACK, BRIGHT_WHITE, BRIGHT_YELLOW
from dasha.widgets import Button, CheckBoxes, Collapsible, Label, TextBox
from dasha.window import Window


def press(row: int, column: int) -> MouseEvent:
    """A left press at a screen position.

    :param row: Screen row.
    :param column: Screen column.
    """
    return MouseEvent(action="press", button="left", row=row, column=column)


class CollapsibleTests(unittest.TestCase):
    """A window with a collapsible area."""

    def setUp(self) -> None:
        self.changes: list[bool] = []
        self.window = Window("W", Rect(0, 0, 12, 40))
        self.name = self.window.add(TextBox(0, 6, 10, name="name"))
        self.area = self.window.add(
            Collapsible(
                "&Advanced", 1, 0, on_change=lambda a: self.changes.append(a.value)
            )
        )
        self.side = self.window.add(Label("Side", 1, 20))
        self.verbose = self.area.add(CheckBoxes(["&Verbose"], 0, 3, name="verbose"))
        self.retries = self.area.add(TextBox(1, 3, 6, name="retries"))
        self.below = self.window.add(TextBox(2, 6, 10, name="below"))
        self.right = self.window.add(Label("Right", 2, 20))

    def keys(self, *names: str) -> None:
        """Send keys to the window.

        :param names: The keys.
        """
        for name in names:
            self.window.handle_key(name, Shortcuts())

    def drawn(self) -> Canvas:
        """The window painted."""
        canvas = Canvas(40, 12)
        self.window.paint(canvas, active=True)
        return canvas

    def test_children_placed_in_the_area(self) -> None:
        """Rows relative to the area: under the header, from its column."""
        self.assertEqual(self.verbose.rect.row, 2)
        self.assertEqual(self.retries.rect.row, 3)
        self.assertEqual(self.verbose.rect.column, 3)

    def test_label_colours(self) -> None:
        """Label colours."""
        self.window.focus(self.name)
        canvas = self.drawn()
        label, letter = canvas.cell(2, 4)[1], canvas.cell(2, 3)[1]  # "d", "A"
        self.assertEqual((label.foreground, label.background), (BRIGHT_BLACK, BLUE))
        self.assertEqual((letter.foreground, letter.background), (BRIGHT_YELLOW, BLUE))
        self.assertFalse(letter.underline or label.reverse)
        self.window.focus(self.area)
        canvas = self.drawn()
        label, focused_letter = canvas.cell(2, 4)[1], canvas.cell(2, 3)[1]
        self.assertEqual((label.foreground, label.background), (BRIGHT_WHITE, BLUE))
        self.assertEqual(focused_letter, letter)
        self.assertFalse(label.reverse or focused_letter.reverse)
        saved = theme.current_theme()
        self.addCleanup(theme.apply_theme, saved)
        theme.apply_theme(theme.MONOCHROME_THEME)
        self.window.focus(self.name)
        letter = self.drawn().cell(2, 3)[1]
        self.assertTrue(letter.underline)
        self.assertIsNone(letter.foreground)
        self.window.focus(self.area)
        self.assertTrue(self.drawn().cell(2, 4)[1].bold)

    def test_collapsed(self) -> None:
        """► and the label; its widgets are not drawn, nothing has moved."""
        canvas = self.drawn()
        self.assertEqual(canvas.text(2)[1:12], RIGHT + " Advanced ")
        self.assertNotIn("Verbose", "".join(canvas.text(r) for r in range(12)))
        self.assertEqual((self.below.rect.row, self.right.rect.row), (2, 2))
        self.assertFalse(self.verbose.is_shown)

    def test_expanding_moves_everything_below(self) -> None:
        """Expanding moves the widgets below."""
        self.area.expand()
        canvas = self.drawn()
        self.assertEqual(canvas.text(2)[1:3], DOWN + " ")
        self.assertIn("Verbose", canvas.text(3))
        self.assertEqual((self.below.rect.row, self.right.rect.row), (4, 4))
        self.assertEqual((self.name.rect.row, self.side.rect.row), (0, 1))
        self.assertEqual(self.changes, [True])

    def test_collapsing_moves_them_back(self) -> None:
        """Exactly where they were."""
        before = [w.rect for w in self.window.widgets]
        self.area.expand()
        self.area.collapse()
        self.assertEqual([w.rect for w in self.window.widgets], before)

    def test_tab_skips_hidden_widgets(self) -> None:
        """Collapsed, Tab goes past the area's widgets; expanded, into them."""
        self.keys("tab")
        self.assertIs(self.window.focused, self.area)
        self.keys("tab")
        self.assertIs(self.window.focused, self.below)
        self.keys("shift+tab", " ", "tab")
        self.assertIs(self.window.focused, self.verbose)

    def test_hidden_widgets_take_no_clicks_or_letters(self) -> None:
        """Hidden widgets take no clicks or letters."""
        interior = self.window.interior
        self.window.handle_mouse(press(interior.row + 2, interior.column + 5))
        self.assertIs(self.window.focused, self.name)
        self.keys("alt+v")
        self.assertEqual(self.verbose.value, ())
        self.area.expand()
        self.keys("alt+v")
        self.assertEqual(self.verbose.value, (0,))

    def test_values_include_hidden_widgets(self) -> None:
        """A dialog's values still have what is inside a collapsed area."""
        self.assertIn("retries", self.window.values)

    def test_collapsing_moves_the_focus_out(self) -> None:
        """With the focus inside, collapsing puts it on the header."""
        self.area.expand()
        self.window.focus(self.retries)
        self.area.collapse()
        self.assertIs(self.window.focused, self.area)

    def test_keys_and_clicks(self) -> None:
        """Keys and clicks toggle the area."""
        self.window.focus(self.area)
        self.keys(" ", "enter", "right", "right", "left")
        self.assertEqual(self.changes, [True, False, True, False])
        interior = self.window.interior
        self.window.handle_mouse(press(interior.row + 1, interior.column + 3))
        self.keys("alt+a")
        self.assertEqual(self.changes, [True, False, True, False, True, False])

    def test_set_from_code_tells_no_one(self) -> None:
        """Setting expanded from code moves things, without on_change."""
        self.area.expanded = True
        self.assertEqual(self.below.rect.row, 4)
        self.assertEqual(self.changes, [])

    def test_scroll_bars_when_it_overflows(self) -> None:
        """The content grows and shrinks with the area."""
        self.assertEqual(self.window.content_size[1], 3)
        self.area.expand()
        self.assertEqual(self.window.content_size[1], 5)

    def test_needs_a_window(self) -> None:
        """Widgets go in once the area is in a window."""
        with self.assertRaises(ValueError):
            Collapsible("X", 0, 0).add(Label("x", 0, 0))


class StartingExpandedTests(unittest.TestCase):
    """Laid out as though collapsed, it moves the rest down itself."""

    def test_widgets_added_after_move_down(self) -> None:
        """An area that starts expanded pushes later widgets below it."""
        window = Window("W", Rect(0, 0, 12, 40))
        area = window.add(Collapsible("Open", 0, 0, expanded=True))
        area.add(Label("inside", 0, 2))
        below = window.add(Button("&OK", 1, 0))
        self.assertEqual(below.rect.row, 2)
        area.collapse()
        self.assertEqual(below.rect.row, 1)


class NestingTests(unittest.TestCase):
    """An area inside an area."""

    def setUp(self) -> None:
        self.window = Window("W", Rect(0, 0, 16, 40))
        self.outer = self.window.add(Collapsible("Outer", 0, 0, expanded=True))
        self.inner = self.outer.add(Collapsible("Inner", 0, 2))
        self.deep = self.inner.add(Label("deep", 0, 2))
        self.after = self.outer.add(Label("after inner", 1, 2))
        self.below = self.window.add(Label("below", 1, 0))

    def test_laid_out(self) -> None:
        """Outer expanded, inner collapsed: two rows inside."""
        self.assertEqual(
            [self.inner.rect.row, self.after.rect.row, self.below.rect.row], [1, 2, 3]
        )
        self.assertFalse(self.deep.is_shown)

    def test_inner_expanding_moves_both(self) -> None:
        """The outer area's later widgets, and everything below it."""
        self.inner.expand()
        self.assertEqual(
            [self.deep.rect.row, self.after.rect.row, self.below.rect.row], [2, 3, 4]
        )
        self.assertTrue(self.deep.is_shown)

    def test_outer_collapsing_hides_all(self) -> None:
        """Everything inside hides, and below moves back by the whole height."""
        self.inner.expand()
        self.outer.collapse()
        self.assertFalse(self.deep.is_shown)
        self.assertFalse(self.inner.is_shown)
        self.assertEqual(self.below.rect.row, 1)
        self.outer.expand()
        self.assertEqual(self.below.rect.row, 4)


if __name__ == "__main__":
    unittest.main()
