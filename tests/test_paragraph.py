"""Tests for paragraphs: wrapped, lined up and scrolling text."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.scrollbar import THUMB, UP
from dasha.shortcuts import Shortcuts
from dasha.style import BLUE, Style
from dasha.widgets import Paragraph
from dasha.widgets.paragraph import wrap
from dasha.window import Window

TEXT = (
    "Dasha Desktop runs applications in windows, on a desktop of their own.\n"
    "\n"
    "Each runs in a process of its own."
)


def drawn(paragraph: Paragraph) -> list[str]:
    """The paragraph's rows as drawn.

    :param paragraph: The paragraph.
    """
    canvas = Canvas(paragraph.rect.width, paragraph.rect.height)
    paragraph.paint(canvas, canvas.bounds, False)
    return [canvas.text(row) for row in range(paragraph.rect.height)]


class WrapTests(unittest.TestCase):
    """Wrapping text."""

    def test_wraps_words_whole(self) -> None:
        """Words wrap whole."""
        self.assertEqual(
            wrap("one two three four\n\nfive", 9),
            [["one two", "three", "four"], [""], ["five"]],
        )

    def test_long_words_are_broken(self) -> None:
        """A word longer than the width is broken to fit."""
        self.assertEqual(wrap("abcdefghij", 4), [["abcd", "efgh", "ij"]])
        self.assertEqual(wrap("", 4), [[""]])


class ParagraphTests(unittest.TestCase):
    """A paragraph 24 columns wide."""

    def test_as_tall_as_its_text(self) -> None:
        """With no height given, every line shows, and it takes no focus."""
        paragraph = Paragraph(TEXT, 0, 0, 24)
        self.assertEqual(paragraph.rect.height, len(paragraph.lines))
        self.assertEqual(drawn(paragraph)[0].rstrip(), "Dasha Desktop runs")
        self.assertIn("", [line.strip() for line in drawn(paragraph)])
        self.assertFalse(paragraph.can_focus())
        self.assertEqual(paragraph.value, TEXT)

    def test_alignment(self) -> None:
        """Centred, right, and justified (but for each line's last)."""
        centred = Paragraph("ab", 0, 0, 10, align="centre")
        self.assertEqual(drawn(centred), ["    ab    "])
        right = Paragraph("ab", 0, 0, 10, align="right")
        self.assertEqual(drawn(right), ["        ab"])
        justified = Paragraph("aa bb cc dd ee", 0, 0, 7, align="justify")
        self.assertEqual(justified.lines, ["aa   bb", "cc   dd", "ee"])
        with self.assertRaises(ValueError):
            Paragraph("x", 0, 0, 10, align="middle")
        with self.assertRaises(ValueError):
            Paragraph("x", 0, 0, 1)

    def test_setting_text_wraps_afresh(self) -> None:
        """New text, new lines, and its height follows."""
        paragraph = Paragraph("short", 0, 0, 10)
        paragraph.text = "much longer text than before"
        self.assertEqual(paragraph.rect.height, len(paragraph.lines))
        self.assertGreater(paragraph.rect.height, 1)

    def test_colours(self) -> None:
        """The window's, unless it has its own."""
        window = Window("W", Rect(0, 0, 6, 30))
        paragraph = window.add(Paragraph("hello", 0, 0, 20))
        canvas = Canvas(30, 6)
        window.paint(canvas, active=True)
        self.assertEqual(canvas.cell(1, 1)[1], Window.body_style)
        paragraph.style = Style(foreground=BLUE)
        window.paint(canvas, active=True)
        self.assertEqual(canvas.cell(1, 1)[1], Style(foreground=BLUE))


class ScrollingTests(unittest.TestCase):
    """A paragraph of 20 lines, 5 tall."""

    def setUp(self) -> None:
        text = "\n".join(f"line {number}" for number in range(20))
        self.paragraph = Paragraph(text, 0, 0, 12, 5)

    def keys(self, *names: str) -> None:
        """Send keys to the paragraph.

        :param names: The keys.
        """
        for name in names:
            self.assertTrue(self.paragraph.handle_key(name, Shortcuts()), name)

    def test_scroll_bar(self) -> None:
        """It scrolls, with a bar on its right, and takes the focus."""
        self.assertTrue(self.paragraph.is_scrollable)
        self.assertTrue(self.paragraph.can_focus())
        rows = drawn(self.paragraph)
        self.assertEqual(rows[0], "line 0     " + UP)
        self.assertEqual(rows[1][-1], THUMB)

    def test_keys(self) -> None:
        """A line, a page, either end."""
        self.keys("down", "down")
        self.assertEqual(self.paragraph.first_visible, 2)
        self.keys("pagedown")
        self.assertEqual(self.paragraph.first_visible, 6)
        self.keys("end")
        self.assertEqual(self.paragraph.first_visible, 15)
        self.keys("pageup", "up", "home")
        self.assertEqual(self.paragraph.first_visible, 0)
        self.assertFalse(self.paragraph.handle_key("x", Shortcuts()))

    def test_wheel_and_bar(self) -> None:
        """The wheel scrolls three lines; the bar's arrows one."""
        down = MouseEvent("scroll", "down", 2, 2)
        self.assertTrue(self.paragraph.handle_mouse(down, 2, 2))
        self.assertEqual(self.paragraph.first_visible, 3)
        press = MouseEvent("press", "left", 4, 11)
        self.paragraph.handle_mouse(press, 4, 11)  # the bar's ▼
        self.paragraph.handle_mouse(MouseEvent("release", "left", 4, 11), 4, 11)
        self.assertEqual(self.paragraph.first_visible, 4)
        self.assertIsNone(self.paragraph.wake_time())
        self.paragraph.on_timer(0)
        click = MouseEvent("press", "left", 1, 1)
        self.assertTrue(self.paragraph.handle_mouse(click, 1, 1))

    def test_short_text_does_not_scroll(self) -> None:
        """Text that fits: no bar, no keys, no wheel."""
        paragraph = Paragraph("one line", 0, 0, 12, 5)
        self.assertFalse(paragraph.is_scrollable)
        self.assertFalse(paragraph.handle_key("down", Shortcuts()))
        down = MouseEvent("scroll", "down", 0, 0)
        self.assertFalse(paragraph.handle_mouse(down, 0, 0))
        self.assertEqual(paragraph.min_size(), (2, 1))

    def test_growing_wraps_afresh(self) -> None:
        """Grown with its window, it wraps to its new width."""
        paragraph = Paragraph("aaa bbb ccc", 0, 0, 4)
        self.assertEqual(len(paragraph.lines), 3)
        paragraph.rect = Rect(0, 0, 3, 12)
        paragraph.on_resize()
        self.assertEqual(paragraph.lines, ["aaa bbb ccc"])


if __name__ == "__main__":
    unittest.main()
