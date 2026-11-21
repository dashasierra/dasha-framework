"""Tests for group boxes."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.dialog import Dialog
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.style import Style
from dasha.widgets import Button, CheckBoxes, GroupBox, Label, TextBox
from dasha.window import Window


class GroupBoxTests(unittest.TestCase):
    """A group box in a window."""

    def setUp(self) -> None:
        self.window = Window("W", Rect(0, 0, 10, 40))
        self.group = self.window.add(GroupBox("&Options", 1, 1, 24, 4))
        self.check = self.group.add(CheckBoxes(["&Verbose"], 0, 1))
        self.box = self.group.add(TextBox(1, 1, 10))
        self.outside = self.window.add(TextBox(6, 1, 10))

    def drawn(self) -> Canvas:
        """The window painted."""
        canvas = Canvas(40, 10)
        self.window.paint(canvas, active=True)
        return canvas

    def test_frame_and_title(self) -> None:
        """A single-line frame, the title in its top edge."""
        canvas = self.drawn()
        top = canvas.text(2)[2:26]
        self.assertEqual(top, "┌─ Options ────────────┐")
        self.assertEqual(canvas.text(5)[2:26], "└" + "─" * 22 + "┘")
        self.assertEqual((canvas.text(3)[2], canvas.text(3)[25]), ("│", "│"))
        self.assertIn("Verbose", canvas.text(3))

    def test_window_colours_and_underlined_letter(self) -> None:
        """No colours of its own: the window's; its letter is underlined."""
        canvas = self.drawn()
        body = Window.body_style
        self.assertEqual(canvas.cell(2, 2)[1].background, body.background)
        self.assertTrue(canvas.cell(2, 5)[1].underline)  # the O of Options
        GroupBox.style = Style(bold=True)
        try:
            self.assertTrue(self.drawn().cell(2, 2)[1].bold)
        finally:
            GroupBox.style = Style()

    def test_widgets_inside_the_frame(self) -> None:
        """Placed from the first cell inside it."""
        self.assertEqual((self.check.rect.row, self.check.rect.column), (2, 3))

    def test_the_letter_focuses_the_first_widget(self) -> None:
        """The letter focuses the first widget."""
        self.window.focus(self.outside)
        self.window.handle_key("alt+o", Shortcuts())
        self.assertIs(self.window.focused, self.check)
        self.assertFalse(self.group.can_focus())

    def test_in_a_dialog_the_letter_alone(self) -> None:
        """In a dialog, the letter alone."""
        dialog = Dialog("D", 30, 8)
        group = dialog.add(GroupBox("&Options", 0, 1, 24, 4))
        dialog.add(Button("&Cancel", 5, 1))
        inside = group.add(TextBox(0, 1, 10))
        dialog.handle_key("o", Shortcuts())
        self.assertIs(dialog.focused, inside)

    def test_clicks_go_to_the_widgets_inside(self) -> None:
        """The frame is under its widgets: a click on one reaches it."""
        interior = self.window.interior
        press = MouseEvent("press", "left", interior.row + 3, interior.column + 3)
        self.window.handle_mouse(press)
        self.assertIs(self.window.focused, self.box)

    def test_short_titles_and_none(self) -> None:
        """No title: a plain frame; a long one is cut to fit."""
        window = Window("W", Rect(0, 0, 8, 20))
        window.add(GroupBox("", 0, 0, 8, 3))
        window.add(GroupBox("A very long title", 3, 0, 10, 3))
        canvas = Canvas(20, 8)
        window.paint(canvas, active=True)
        self.assertEqual(canvas.text(1)[1:9], "┌──────┐")
        self.assertEqual(canvas.text(4)[1:11], "┌─ A ver ┐")
        with self.assertRaises(ValueError):
            GroupBox("x", 0, 0, 1, 1)
        self.assertEqual(GroupBox("x", 0, 0, 4, 4).min_size(), (2, 2))

    def test_letter_with_nothing_to_focus(self) -> None:
        """A group of labels only: its letter does nothing."""
        window = Window("W", Rect(0, 0, 8, 20))
        group = window.add(GroupBox("&Info", 0, 0, 12, 3))
        group.add(Label("text", 0, 0))
        group.activate()
        self.assertIsNone(window.focused)
        GroupBox("&Info", 0, 0, 4, 4).activate()  # in no window: nothing


if __name__ == "__main__":
    unittest.main()
