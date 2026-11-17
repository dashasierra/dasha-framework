"""Tests for progress bars and column bars."""

import unittest

from dasha.canvas import Canvas
from dasha.widgets import ColumnBar, ProgressBar
from dasha.widgets.progressbar import EMPTY, HALF_ACROSS, HALF_UP


def drawn(progress: ProgressBar) -> Canvas:
    """The bar painted on a canvas just its size."""
    canvas = Canvas(progress.rect.width, progress.rect.height)
    progress.paint(canvas, canvas.bounds, False)
    return canvas


class ProgressBarTests(unittest.TestCase):
    """Filling from left to right."""

    def test_empty_and_full(self) -> None:
        """Nothing filled at 0; every cell at the maximum."""
        progress = ProgressBar(0, 0, 10, text=None)
        self.assertEqual(drawn(progress).text(0), EMPTY * 10)
        progress.value = 100
        self.assertEqual(drawn(progress).text(0), " " * 10)
        self.assertEqual(drawn(progress).cell(0, 9)[1], ProgressBar.filled_style)

    def test_half_cells(self) -> None:
        """25% of 10 cells is two and a half: ▌ for the half."""
        progress = ProgressBar(0, 0, 10, value=25, text=None)
        self.assertEqual(drawn(progress).text(0), "  " + HALF_ACROSS + EMPTY * 7)
        half = drawn(progress).cell(0, 2)[1]
        self.assertEqual(half.foreground, ProgressBar.filled_style.background)
        self.assertEqual(half.background, ProgressBar.empty_style.background)

    def test_text_changes_colour_where_reached(self) -> None:
        """The text is in the middle; the part the progress has reached is in
        its colours, the rest in the track's."""
        progress = ProgressBar(0, 0, 11, value=50)
        canvas = drawn(progress)
        self.assertEqual(canvas.text(0)[4:7], "50%")
        self.assertEqual(canvas.cell(0, 4)[1], ProgressBar.filled_style)
        self.assertEqual(
            canvas.cell(0, 5)[1], ProgressBar.filled_style
        )  # half: reached
        self.assertEqual(canvas.cell(0, 6)[1], ProgressBar.empty_style)

    def test_text_formats(self) -> None:
        """The text can say anything with the value and maximum."""
        progress = ProgressBar(
            0, 0, 20, value=3, maximum=8, text="{value} of {maximum}"
        )
        self.assertIn("3 of 8", drawn(progress).text(0))
        progress.text = "{per_cent:.1f}%"
        self.assertEqual(progress.label, "37.5%")

    def test_kept_in_range(self) -> None:
        """Values beyond either end are held there."""
        progress = ProgressBar(0, 0, 10, maximum=50)
        progress.value = 80
        self.assertEqual(progress.value, 50)
        progress.value = -5
        self.assertEqual(progress.value, 0)
        with self.assertRaises(ValueError):
            ProgressBar(0, 0, 10, maximum=0)

    def test_thick_bars_put_the_text_in_the_middle_row(self) -> None:
        """Three rows deep: the text is on the second."""
        progress = ProgressBar(0, 0, 10, 3, value=0)
        canvas = drawn(progress)
        self.assertIn("0%", canvas.text(1))
        self.assertEqual(canvas.text(0), EMPTY * 10)


class ColumnBarTests(unittest.TestCase):
    """Filling from the bottom up."""

    def test_fills_from_the_bottom(self) -> None:
        """Half of four rows: the bottom two filled."""
        progress = ColumnBar(0, 0, 4, value=50, text=None)
        canvas = drawn(progress)
        self.assertEqual((progress.rect.width, progress.rect.height), (1, 4))
        self.assertEqual(
            [canvas.text(row) for row in range(4)], [EMPTY, EMPTY, " ", " "]
        )

    def test_half_cells(self) -> None:
        """A half cell is ▄."""
        progress = ColumnBar(0, 0, 4, value=25 + 12.5, text=None)
        self.assertEqual(drawn(progress).text(2), HALF_UP)

    def test_text_down_the_middle(self) -> None:
        """The text reads from top to bottom down the middle column, each
        character changing colour as the bar rises past it."""
        progress = ColumnBar(0, 0, 5, 3, value=20)
        canvas = drawn(progress)
        self.assertEqual(
            [canvas.cell(row, 1)[0] for row in range(5)], list(EMPTY + "20%" + " ")
        )
        self.assertEqual(canvas.text(2), EMPTY + "0" + EMPTY)
        self.assertEqual(canvas.cell(3, 1)[1], ProgressBar.empty_style)
        progress.value = 50  # two and a half rows: the % and the 0 (half) reached
        canvas = drawn(progress)
        self.assertEqual(canvas.cell(3, 1)[1], ProgressBar.filled_style)
        self.assertEqual(canvas.cell(2, 1)[1], ProgressBar.filled_style)
        self.assertEqual(canvas.cell(1, 1)[1], ProgressBar.empty_style)

    def test_text_cut_to_the_height(self) -> None:
        """Too short for the text: as much as fits."""
        progress = ColumnBar(0, 0, 2, value=100)
        self.assertEqual([drawn(progress).text(row) for row in range(2)], ["1", "0"])


if __name__ == "__main__":
    unittest.main()
