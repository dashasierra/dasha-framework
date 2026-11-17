"""Tests for a text area's line numbers: a column at its left, right-
aligned, widening past 999 lines, by each line's first row with word wrap,
and staying in view as the window scrolls sideways."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.theme import DARK_THEME, DEFAULT_THEME, MONOCHROME_THEME
from dasha.widgets import TextArea
from dasha.widgets.textarea import NUMBERS_BAR
from dasha.window import Window

TEXT = "The quick brown fox jumps over the lazy dog\nshort\n\nlast"


def editor(text: str = TEXT, word_wrap: bool = False) -> tuple[Window, TextArea]:
    """A window whose interior is 24 columns by 6 rows, holding a text area
    with line numbers (and word wrap, if asked)."""
    window = Window("W", Rect(0, 0, 8, 26), resizable=True)
    area = window.add(TextArea(0, 0, text=text, line_numbers=True, word_wrap=word_wrap))
    return window, area


def painted(window: Window) -> Canvas:
    """The window, painted."""
    canvas = Canvas(window.rect.width, window.rect.height)
    window.paint(canvas, True)
    return canvas


def rows(window: Window) -> list[str]:
    """The window's interior, a row at a time, without trailing spaces."""
    canvas = painted(window)
    interior = window.interior
    return [
        canvas.text(row)[interior.column : interior.right].rstrip()
        for row in range(interior.row, interior.bottom)
    ]


class NumbersTests(unittest.TestCase):
    """The column of numbers."""

    def test_off_by_default(self) -> None:
        """A text area has no numbers unless asked."""
        window = Window("W", Rect(0, 0, 8, 24))
        area = window.add(TextArea(0, 0, text=TEXT))
        self.assertFalse(area.line_numbers)
        self.assertEqual(area.numbers_width, 0)
        self.assertEqual(rows(window)[0], "The quick brown fox ju")

    def test_numbers_right_aligned_before_a_bar(self) -> None:
        """Three columns of numbers, right-aligned, then the bar and the
        text; the bar goes on below the last line."""
        window, _ = editor()
        edge = NUMBERS_BAR
        self.assertEqual(
            rows(window),
            [
                f"  1{edge}The quick brown fox",
                f"  2{edge}short",
                f"  3{edge}",
                f"  4{edge}last",
                f"   {edge}",
                f"   {edge}",
            ],
        )

    def test_wider_from_line_1000(self) -> None:
        """999 lines fit three digits; the thousandth makes it four."""
        _, area = editor("\n".join("x" * 999))
        self.assertEqual(area.numbers_width, 4)
        area.insert("\n")
        self.assertEqual(len(area.lines), 1000)
        self.assertEqual(area.numbers_width, 5)
        area.handle_key("backspace", Shortcuts())
        self.assertEqual(area.numbers_width, 4)

    def test_wrapped_line_numbered_on_its_first_row(self) -> None:
        """With word wrap, a line's number is by its first row only, and
        the rows are as wide as what is left beside the numbers."""
        window, area = editor(word_wrap=True)
        edge = NUMBERS_BAR
        self.assertEqual(
            rows(window)[:5],
            [
                f"  1{edge}The quick brown fox",
                f"   {edge}jumps over the lazy",
                f"   {edge}dog",
                f"  2{edge}short",
                f"  3{edge}",
            ],
        )
        self.assertEqual(area.rect.width, 24)

    def test_widening_wraps_again(self) -> None:
        """A wider column of numbers leaves less for the text, which wraps
        again to fit."""
        _, area = editor("word " * 4 + "\n" * 998, word_wrap=True)
        self.assertEqual(area.lines[0], "word " * 4)
        self.assertEqual(area.rect.width, 24)
        self.assertEqual(area.numbers_width, 4)  # 999 lines
        area.cursor = (998, 0)
        area.insert("\n")
        self.assertEqual(area.numbers_width, 5)

    def test_cursor_after_the_numbers(self) -> None:
        """The cursor shows in the text, past the numbers."""
        window, area = editor()
        area.cursor = (1, 2)
        self.assertEqual(painted(window).cursor, (2, 1 + 4 + 2))

    def test_numbers_stay_as_the_window_scrolls_sideways(self) -> None:
        """Scrolled to a long line's end, the numbers still show at the
        left, and the text goes on from beside them."""
        window, area = editor()
        area.handle_key("end", Shortcuts())
        self.assertGreater(window.scroll_column, 0)
        first = rows(window)[0]
        self.assertTrue(first.startswith(f"  1{NUMBERS_BAR}"))
        self.assertTrue(first.endswith("lazy dog"))
        canvas = painted(window)
        assert canvas.cursor is not None
        self.assertEqual(canvas.cursor[0], 1)
        self.assertGreater(canvas.cursor[1], 4)

    def test_clicks(self) -> None:
        """A click in the text goes there, beside the numbers; a click on
        the numbers goes to the start of the row."""
        window, area = editor()
        window.handle_mouse(MouseEvent("press", "left", 1, 7))
        self.assertEqual(area.cursor, (0, 2))
        window.handle_mouse(MouseEvent("press", "left", 2, 2))
        self.assertEqual(area.cursor, (1, 0))

    def test_turned_on_and_off(self) -> None:
        """Turning numbers off gives their columns back to the text."""
        window, area = editor(word_wrap=True)
        area.line_numbers = False
        self.assertEqual(rows(window)[0], "The quick brown fox")
        self.assertEqual(rows(window)[1], "jumps over the lazy dog")  # room now
        area.line_numbers = True
        self.assertEqual(rows(window)[0], f"  1{NUMBERS_BAR}The quick brown fox")

    def test_colours(self) -> None:
        """The numbers have a colour of their own, in every theme."""
        window, _ = editor()
        canvas = painted(window)
        self.assertEqual(canvas.cell(1, 3), ("1", TextArea.number_style))
        self.assertEqual(canvas.cell(1, 4), (NUMBERS_BAR, TextArea.number_style))
        for colours in (DEFAULT_THEME, DARK_THEME, MONOCHROME_THEME):
            self.assertIn("textarea.numbers", colours)


if __name__ == "__main__":
    unittest.main()
