"""Tests for a text area's word wrap: long lines going on in the rows
below them, and the cursor, keys, clicks and selection going by rows."""

import time
import unittest

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.widgets import TextArea
from dasha.window import Window

FOX = "The quick brown fox jumps over the lazy dog"


def editor(text: str, width: int = 12, wrap: bool = True) -> tuple[Window, TextArea]:
    """A window whose interior is ``width`` columns by 6 rows, holding a
    text area (wrapping, unless told not to)."""
    window = Window("W", Rect(0, 0, 8, width + 2), resizable=True)
    area = window.add(TextArea(0, 0, text=text, word_wrap=wrap))
    return window, area


def rows(window: Window) -> list[str]:
    """The text area's rows as the window shows them, without the frame
    or trailing spaces."""
    canvas = Canvas(window.rect.width, window.rect.height)
    window.paint(canvas, True)
    interior = window.interior
    return [
        canvas.text(row)[interior.column : interior.right].rstrip()
        for row in range(interior.row, interior.bottom)
    ]


class _Keys(unittest.TestCase):
    """Pressing keys in a text area."""

    def setUp(self) -> None:
        self.keys = Shortcuts()

    def key(self, area: TextArea, *names: str) -> None:
        """Press keys in the text area."""
        for name in names:
            area.handle_key(name, self.keys)


class WrapTests(_Keys):
    """How lines are broken into rows."""

    def test_off_by_default(self) -> None:
        """Without word wrap, a long line runs on, and the text area is
        wider than the window."""
        window = Window("W", Rect(0, 0, 8, 14))
        area = window.add(TextArea(0, 0, text=FOX))
        self.assertFalse(area.word_wrap)
        self.assertEqual(area.rect.width, len(FOX) + 1)
        self.assertEqual(rows(window)[:2], [FOX[:12], ""])

    def test_breaks_after_spaces(self) -> None:
        """A long line goes on in the rows below, broken after spaces, and
        the text area is as wide as the window."""
        window, area = editor(FOX)
        self.assertEqual(
            rows(window),
            ["The quick", "brown fox", "jumps over", "the lazy", "dog", ""],
        )
        self.assertEqual(area.rect.width, 12)
        self.assertEqual(area.lines, [FOX])  # the text is as it was

    def test_long_word_broken_within(self) -> None:
        """A word longer than a row is broken where the row ends."""
        window, _ = editor("a supercalifragilistic word")
        self.assertEqual(rows(window)[:4], ["a", "supercalifr", "agilistic", "word"])

    def test_tabs_measured(self) -> None:
        """A tab takes the columns it is drawn as."""
        window, _ = editor("\tone two three")
        self.assertEqual(rows(window)[:2], ["    one two", "three"])

    def test_typing_wraps_again(self) -> None:
        """Typing on a line breaks it again, and the text area grows and
        shrinks with its rows."""
        window, area = editor("one two")
        self.assertEqual(area.rect.height, 6)
        area.cursor = (0, 7)
        for char in " three four five six seven eight nine":
            self.key(area, char)
        self.assertEqual(
            rows(window),
            ["one two", "three four", "five six", "seven eight", "nine", ""],
        )
        self.key(area, "enter", *"ten eleven twelve")
        self.assertEqual(area.rect.height, 7)
        self.assertEqual(area.cursor, (1, 17))
        self.assertEqual(window.scroll_row, 1)  # the cursor's row in view
        area.text = "short"
        self.assertEqual(area.rect.height, 6)

    def test_resizing_wraps_again(self) -> None:
        """A wider window takes more on each row."""
        window, area = editor(FOX)
        window.resize(22, 8)
        self.assertEqual(area.rect.width, 20)
        self.assertEqual(
            rows(window)[:3], ["The quick brown fox", "jumps over the lazy", "dog"]
        )

    def test_turned_on_and_off(self) -> None:
        """Turning word wrap off lets the line run on again."""
        window, area = editor(FOX, wrap=False)
        area.word_wrap = True
        self.assertEqual(rows(window)[1], "brown fox")
        area.word_wrap = False
        self.assertEqual(area.rect.width, len(FOX) + 1)
        self.assertEqual(rows(window)[1], "")


class CursorTests(_Keys):
    """Moving about wrapped lines."""

    def test_cursor_on_its_row(self) -> None:
        """The cursor shows on the row its character is on; at a break, at
        the start of the row after."""
        window, area = editor(FOX)
        area.cursor = (0, 12)  # in "brown"
        canvas = Canvas(14, 8)
        window.paint(canvas, True)
        self.assertEqual(canvas.cursor, (2, 3))
        area.cursor = (0, 10)  # just after "quick ": the next row
        window.paint(canvas, True)
        self.assertEqual(canvas.cursor, (2, 1))

    def test_up_and_down_go_by_rows(self) -> None:
        """Up and Down move a row at a time, keeping to the column, and to
        a row's end where it is shorter."""
        _, area = editor(FOX)
        area.cursor = (0, 7)  # "The qui|ck"
        self.key(area, "down")
        self.assertEqual(area.cursor, (0, 17))  # "brown f|ox"
        self.key(area, "down", "down")
        self.assertEqual(area.cursor, (0, 38))  # "the laz|y dog"
        self.key(area, "up")
        self.assertEqual(area.cursor, (0, 27))  # "jumps o|ver"
        area.cursor = (0, 30)  # "jumps over| ", before the space ending its row
        self.key(area, "up")
        self.assertEqual(area.cursor, (0, 19))  # "brown fox| ": that row is shorter

    def test_down_onto_the_next_line(self) -> None:
        """From a line's last row, Down goes to the next line's first."""
        _, area = editor(FOX + "\nend")
        area.cursor = (0, 41)  # "d|og"
        self.key(area, "down")
        self.assertEqual(area.cursor, (1, 1))
        self.key(area, "up")
        self.assertEqual(area.cursor, (0, 41))

    def test_home_and_end_take_the_line(self) -> None:
        """Home and End go to the start and end of the whole line."""
        _, area = editor(FOX)
        area.cursor = (0, 17)
        self.key(area, "end")
        self.assertEqual(area.cursor, (0, len(FOX)))
        self.key(area, "home")
        self.assertEqual(area.cursor, (0, 0))

    def test_click_on_a_row(self) -> None:
        """A click puts the cursor in the row clicked, past its end at its
        end."""
        window, area = editor(FOX)
        window.handle_mouse(MouseEvent("press", "left", 3, 3))
        self.assertEqual(area.cursor, (0, 22))  # "ju|mps"
        window.handle_mouse(MouseEvent("press", "left", 5, 12))
        self.assertEqual(area.cursor, (0, len(FOX)))

    def test_selection_across_rows(self) -> None:
        """A selection shows on each row it covers, where it is on it."""
        window, area = editor(FOX)
        area.select((0, 12), (0, 22))  # "own fox ju"
        canvas = Canvas(14, 8)
        window.paint(canvas, True)
        selected = [
            (row, column)
            for row in range(1, 7)
            for column in range(1, 13)
            if canvas.cell(row, column)[1] == TextArea.selected_style
        ]
        self.assertEqual(selected[0], (2, 3))
        self.assertIn((2, 10), selected)  # the space at the row's end
        self.assertEqual(selected[-1], (3, 2))
        self.assertNotIn((2, 11), selected)


class LargeWrappedTextTests(unittest.TestCase):
    """Word wrap on a big text keeps typing quick."""

    def test_typing_is_quick(self) -> None:
        """Typing on a wrapped line of a 100,000-line text works on that
        line, not the whole text."""
        line = "The quick brown fox jumps over the lazy dog, now and again.\t1234"
        window = Window("Big", Rect(0, 0, 25, 42), resizable=True)
        area = window.add(
            TextArea(0, 0, text="\n".join([line] * 100_000), word_wrap=True)
        )
        canvas = Canvas(42, 25)
        keys = Shortcuts()
        area.cursor = (50_000, 10)
        start = time.perf_counter()
        for char in "typing ":
            area.handle_key(char, keys)
        window.paint(canvas, True)
        self.assertLess(time.perf_counter() - start, 0.25)
        self.assertEqual(area.cursor, (50_000, 17))


if __name__ == "__main__":
    unittest.main()
