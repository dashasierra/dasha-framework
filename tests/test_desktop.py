"""Tests for the Desktop background."""

import unittest

from dasha.canvas import Canvas
from dasha.desktop import Desktop
from dasha.style import BLACK, BLUE, BRIGHT_BLUE, Style


def paint(desktop: Desktop, width: int, height: int) -> Canvas:
    """Paint a desktop onto a fresh canvas.

    :param desktop: The desktop.
    :param width: Canvas width.
    :param height: Canvas height.
    """
    canvas = Canvas(width, height)
    desktop.paint(canvas)
    return canvas


class DesktopTests(unittest.TestCase):
    """The desktop fills the screen and can be customised."""

    def test_default_pattern_is_light_shade(self) -> None:
        """The default pattern is light shade."""
        self.assertEqual(Desktop.pattern, "\N{LIGHT SHADE}")
        self.assertEqual(Desktop.style, Style(foreground=BRIGHT_BLUE, background=BLACK))

    def test_paint_fills_every_cell(self) -> None:
        """Every row is filled to the full width."""
        canvas = paint(Desktop(), 5, 3)
        for row in range(3):
            self.assertEqual(canvas.text(row), Desktop.pattern * 5)

    def test_pattern_and_style_can_be_set_per_instance(self) -> None:
        """Constructor arguments override the class defaults."""
        style = Style(foreground=BLUE)
        canvas = paint(Desktop(pattern="ab", style=style), 5, 1)
        self.assertEqual(canvas.text(0), "ababa")
        self.assertEqual(canvas.cell(0, 0), ("a", style))
        self.assertEqual(Desktop.pattern, "\N{LIGHT SHADE}")  # class unchanged

    def test_subclass_can_change_defaults(self) -> None:
        """Third parties can subclass to change the defaults."""

        class DottedDesktop(Desktop):
            """A desktop with a different pattern."""

            pattern = "."

        self.assertEqual(paint(DottedDesktop(), 5, 1).text(0), ".....")

    def test_subclass_can_override_character_at(self) -> None:
        """Overriding character_at allows patterns that vary by row."""

        class StripedDesktop(Desktop):
            """Alternates characters on each row."""

            def character_at(self, row: int, column: int) -> str:
                return "#" if row % 2 else "-"

        canvas = paint(StripedDesktop(), 3, 2)
        self.assertEqual(canvas.text(0), "---")
        self.assertEqual(canvas.text(1), "###")

    def test_empty_pattern_is_rejected(self) -> None:
        """An empty pattern cannot tile the screen."""
        with self.assertRaises(ValueError):
            Desktop(pattern="")


if __name__ == "__main__":
    unittest.main()
