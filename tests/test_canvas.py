"""Tests for Rect, Canvas and Style."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.style import BLUE, BRIGHT_WHITE, DEFAULT, Style
from dasha.terminal import ansi


class RectTests(unittest.TestCase):
    """Rectangle geometry."""

    def test_contains(self) -> None:
        """Contains includes the top-left edge and excludes the bottom-right."""
        rect = Rect(1, 2, height=3, width=4)
        self.assertTrue(rect.contains(1, 2))
        self.assertTrue(rect.contains(3, 5))
        self.assertFalse(rect.contains(4, 5))
        self.assertFalse(rect.contains(3, 6))

    def test_intersect(self) -> None:
        """Overlapping rectangles intersect; separate ones give an empty one."""
        self.assertEqual(Rect(0, 0, 4, 4).intersect(Rect(2, 2, 4, 4)), Rect(2, 2, 2, 2))
        self.assertTrue(Rect(0, 0, 2, 2).intersect(Rect(5, 5, 2, 2)).is_empty)

    def test_inset(self) -> None:
        """Insetting shrinks every side."""
        self.assertEqual(Rect(0, 0, 5, 6).inset(), Rect(1, 1, 3, 4))


class CanvasTests(unittest.TestCase):
    """Painting onto the off-screen grid."""

    def test_write_clips_to_canvas_and_clip_rect(self) -> None:
        """Text never spills outside the canvas or the clip rectangle."""
        canvas = Canvas(6, 2)
        canvas.write(0, 4, "abcdef")
        canvas.write(1, -2, "xyz")
        canvas.write(5, 0, "ignored")
        self.assertEqual(canvas.text(0), "    ab")
        self.assertEqual(canvas.text(1), "z     ")
        canvas.write(1, 0, "123456", clip=Rect(1, 2, 1, 2))
        self.assertEqual(canvas.text(1), "z 34  ")

    def test_fill(self) -> None:
        """Fill covers the rectangle and stops at the canvas edge."""
        canvas = Canvas(4, 3)
        canvas.fill(Rect(1, 2, 5, 5), "#")
        self.assertEqual(
            [canvas.text(row) for row in range(3)], ["    ", "  ##", "  ##"]
        )

    def test_full_render_draws_every_cell(self) -> None:
        """With nothing on screen yet, every cell is sent."""
        canvas = Canvas(3, 2)
        canvas.write(0, 0, "abc")
        canvas.write(1, 0, "def")
        output = canvas.render()
        self.assertIn(ansi.move_to(0, 0), output)
        self.assertIn("abc", output)
        self.assertIn(ansi.move_to(1, 0), output)
        self.assertIn("def", output)

    def test_render_sends_only_changes(self) -> None:
        """Only cells that differ from the screen are sent."""
        before = Canvas(5, 2)
        after = Canvas(5, 2)
        after.write(1, 3, "x", Style(foreground=BLUE))
        self.assertEqual(
            after.render(before),
            ansi.move_to(1, 3)
            + Style(foreground=BLUE).sgr()
            + "x"
            + ansi.RESET_ATTRIBUTES,
        )
        self.assertEqual(after.render(after), "")

    def test_control_characters_are_never_sent(self) -> None:
        """Control characters are never sent."""
        unsafe = "\x1b\x07\x7f\x9b"  # escape, bell, delete, one-byte CSI
        canvas = Canvas(4, 1)
        canvas.write(0, 0, unsafe)
        plain = Canvas(4, 1)
        plain.write(0, 0, "abcd")
        output = canvas.render(Canvas(4, 1))
        self.assertIn("\N{LEFTWARDS ARROW}\N{BULLET}\N{HOUSE}?", output)
        for char in "\x07\x7f\x9b":
            self.assertNotIn(char, output)
        # Only the canvas's own escape sequences, as for ordinary text.
        escapes = plain.render(Canvas(4, 1)).count("\x1b")
        self.assertEqual(output.count("\x1b"), escapes)
        self.assertEqual(canvas.text(0), unsafe)

    def test_size_change_forces_full_render(self) -> None:
        """A canvas of a different size (after a resize) redraws every cell."""
        output = Canvas(2, 1).render(Canvas(3, 1))
        self.assertEqual(output.count(" "), 2)


class StyleTests(unittest.TestCase):
    """Style to escape sequence conversion."""

    def test_default_resets(self) -> None:
        """The default style just resets attributes."""
        self.assertEqual(DEFAULT.sgr(), "\x1b[0m")

    def test_colours_and_attributes(self) -> None:
        """Standard, bright and 256-palette colours use the right codes."""
        self.assertEqual(
            Style(foreground=BRIGHT_WHITE, background=BLUE, bold=True).sgr(),
            "\x1b[0;1;97;44m",
        )
        self.assertEqual(
            Style(foreground=200, reverse=True).sgr(), "\x1b[0;7;38;5;200m"
        )

    def test_invalid_colour(self) -> None:
        """Colours outside 0-255 are rejected."""
        with self.assertRaises(ValueError):
            Style(foreground=256).sgr()


if __name__ == "__main__":
    unittest.main()
