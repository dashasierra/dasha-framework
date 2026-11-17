"""Tests for lining up a dialog's message."""

import unittest
from collections.abc import Sequence

from dasha.dialog import align_lines, confirm, information
from dasha.widgets import Label


def starts(dialog_lines: list[tuple[int, str]]) -> list[int]:
    """Where each line starts."""
    return [offset for offset, _ in dialog_lines]


class AlignLinesTests(unittest.TestCase):
    """``align_lines`` on its own."""

    LINES = ["one two three", "four", "", "five six", "seven"]

    def test_left(self) -> None:
        """Left keeps every line as it is, at the start."""
        self.assertEqual(
            align_lines(self.LINES, 20, "left"), [(0, line) for line in self.LINES]
        )

    def test_centre_and_right(self) -> None:
        """Centre puts the spare room either side (the odd column after);
        right puts it all before."""
        self.assertEqual(starts(align_lines(["abcd", "ab"], 10, "centre")), [3, 4])
        self.assertEqual(starts(align_lines(["abcd", "ab"], 10, "right")), [6, 8])

    def test_justify(self) -> None:
        """Lines are spread to the full width, extra spaces in the first
        gaps; a paragraph's last line and one-word lines are left alone."""
        placed = align_lines(self.LINES, 20, "justify")
        self.assertEqual(placed[0], (0, "one     two    three"))
        self.assertEqual(len(placed[0][1]), 20)
        self.assertEqual(placed[1], (0, "four"))  # last before a blank line
        self.assertEqual(placed[3], (0, "five             six"))
        self.assertEqual(placed[4], (0, "seven"))  # the very last line

    def test_lines_wider_than_the_width(self) -> None:
        """A line that does not fit is not moved off the left edge."""
        self.assertEqual(starts(align_lines(["much too long"], 5, "right")), [0])

    def test_unknown(self) -> None:
        """Anything else is refused."""
        with self.assertRaises(ValueError):
            align_lines(["x"], 5, "middle")


class DialogAlignmentTests(unittest.TestCase):
    """``confirm`` and ``information`` with ``align``."""

    def label_columns(self, dialog_widgets: Sequence[object]) -> list[int]:
        """Where the message labels start, within the dialog."""
        return [w.rect.column for w in dialog_widgets if isinstance(w, Label)]

    def test_default_is_left(self) -> None:
        """Without align, every line starts at the same column."""
        dialog = information("T", "A longer first line\nShort")
        self.assertEqual(self.label_columns(dialog.widgets), [2, 2])

    def test_centre_right_and_justify(self) -> None:
        """The message is lined up across the room between the frame's
        margins, which may be the buttons' width if that is wider."""
        message = "A longer first line\nShort"
        centred = confirm("T", message, align="centre")
        self.assertEqual(self.label_columns(centred.widgets), [4, 11])  # 24 wide
        right = information("T", message, align="right")
        self.assertEqual(self.label_columns(right.widgets), [2, 16])
        justified = confirm("T", "A b\nlast line", align="justify")
        first = justified.widget("message")
        assert isinstance(first, Label)
        self.assertEqual(first.text.split(), ["A", "b"])
        self.assertGreater(len(first.text), 3)
        self.assertEqual(justified.values["message2"], "last line")


if __name__ == "__main__":
    unittest.main()
