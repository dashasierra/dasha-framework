"""Tests for Window drawing."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.window import DOUBLE, SINGLE, Window


class WindowTests(unittest.TestCase):
    """Frames, titles and content."""

    def test_active_window_has_double_frame_and_title(self) -> None:
        """The active window uses the double border with a centred title."""
        canvas = Canvas(12, 4)
        Window("Hi", Rect(0, 0, 4, 12), ["text"]).paint(canvas, active=True)
        h = DOUBLE.horizontal
        self.assertEqual(
            canvas.text(0),
            DOUBLE.top_left + h * 3 + " Hi " + h * 3 + DOUBLE.top_right,
        )
        self.assertEqual(
            canvas.text(1), DOUBLE.vertical + " text     " + DOUBLE.vertical
        )
        self.assertEqual(
            canvas.text(3), DOUBLE.bottom_left + h * 10 + DOUBLE.bottom_right
        )

    def test_inactive_window_has_single_frame(self) -> None:
        """Windows that are not active use the single border."""
        canvas = Canvas(6, 3)
        Window("", Rect(0, 0, 3, 6)).paint(canvas, active=False)
        self.assertEqual(canvas.text(1), SINGLE.vertical + "    " + SINGLE.vertical)

    def test_content_is_clipped_to_interior(self) -> None:
        """Long lines and extra lines stay inside the frame."""
        canvas = Canvas(8, 4)
        window = Window("", Rect(0, 0, 4, 8), ["a long line", "two", "three"])
        window.paint(canvas, active=True)
        self.assertEqual(canvas.text(1)[1:-1], " a lon")
        self.assertEqual(canvas.text(2)[1:-1], " two  ")
        self.assertEqual(canvas.text(3)[0], DOUBLE.bottom_left)

    def test_window_partly_off_screen(self) -> None:
        """A window hanging off the canvas edge is clipped, not an error."""
        canvas = Canvas(5, 3)
        Window("", Rect(1, 2, 4, 6)).paint(canvas, active=True)
        self.assertEqual(canvas.text(1)[2:], DOUBLE.top_left + DOUBLE.horizontal * 2)

    def test_title_bar_and_move_to(self) -> None:
        """The title bar is the top row; moving keeps the size."""
        window = Window("x", Rect(2, 3, 5, 10))
        self.assertEqual(window.title_bar, Rect(2, 3, 1, 10))
        window.move_to(-1, 70)
        self.assertEqual(window.rect, Rect(-1, 70, 5, 10))

    def test_too_small_window_rejected(self) -> None:
        """A window must be large enough for its frame."""
        with self.assertRaises(ValueError):
            Window("x", Rect(0, 0, 1, 5))


if __name__ == "__main__":
    unittest.main()
