"""Tests for resizable windows: the grip, resize(), and dragging the grip."""

import unittest
from typing import cast

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.terminal import Terminal
from dasha.window import DOUBLE, SINGLE, Window

from tests.test_manager import FakeTerminal

GRIP = "\N{BOX DRAWINGS LIGHT HORIZONTAL}\N{BOX DRAWINGS LIGHT UP AND LEFT}"


def grip_cells(canvas: Canvas, row: int, right: int) -> tuple[str, set[object]]:
    """The two grip cells ending at column ``right``: text and styles."""
    cells = [canvas.cell(row, column) for column in (right - 1, right)]
    return "".join(char for char, _ in cells), {style for _, style in cells}


def press(row: int, column: int) -> MouseEvent:
    """A left-button press."""
    return MouseEvent("press", "left", row, column)


def drag(row: int, column: int) -> MouseEvent:
    """Moving with the left button held."""
    return MouseEvent("drag", "left", row, column)


def release(row: int, column: int) -> MouseEvent:
    """A left-button release."""
    return MouseEvent("release", "left", row, column)


class GripTests(unittest.TestCase):
    """How a resizable window shows that it can be resized."""

    def paint(self, window: Window, active: bool) -> Canvas:
        """Paint one window on a fresh canvas."""
        canvas = Canvas(20, 8)
        window.paint(canvas, active)
        return canvas

    def test_resizable_window_has_highlighted_grip(self) -> None:
        """The active window's corner is the grip, in the grip colours."""
        window = Window("W", Rect(1, 1, 5, 14), resizable=True)
        canvas = self.paint(window, active=True)
        self.assertEqual(grip_cells(canvas, 5, 14), (GRIP, {window.resize_grip_style}))
        self.assertEqual(window.resize_grip_rect, Rect(5, 13, 1, 2))
        self.assertNotEqual(canvas.cell(5, 12)[1], window.resize_grip_style)

    def test_grip_uses_code_page_437_characters(self) -> None:
        """Both grip characters exist in code page 437."""
        self.assertEqual(len(Window.resize_grip), 2)
        Window.resize_grip.encode("cp437")  # raises if either is missing

    def test_inactive_grip_uses_frame_colours(self) -> None:
        """An inactive window keeps the grip shape, in its frame's colours."""
        window = Window("W", Rect(1, 1, 5, 14), resizable=True)
        canvas = self.paint(window, active=False)
        self.assertEqual(
            grip_cells(canvas, 5, 14), (GRIP, {window.inactive_frame_style})
        )

    def test_fixed_window_has_ordinary_corner(self) -> None:
        """Windows are fixed-size unless asked, with a plain corner."""
        window = Window("W", Rect(1, 1, 5, 14))
        self.assertFalse(window.resizable)
        self.assertIsNone(window.resize_grip_rect)
        self.assertEqual(self.paint(window, True).cell(5, 14)[0], DOUBLE.bottom_right)
        self.assertEqual(self.paint(window, False).cell(5, 14)[0], SINGLE.bottom_right)

    def test_resize_keeps_corner_and_minimum(self) -> None:
        """resize() keeps the top-left corner and respects the minimum size."""
        window = Window("W", Rect(2, 3, 5, 14), resizable=True)
        window.resize(30, 9)
        self.assertEqual(window.rect, Rect(2, 3, 9, 30))
        window.resize(1, 1)
        self.assertEqual(window.rect, Rect(2, 3, window.min_height, window.min_width))


class DragGripTests(unittest.TestCase):
    """Resizing with the mouse."""

    def setUp(self) -> None:
        self.back = Window("Back", Rect(1, 0, 6, 20), resizable=True)
        self.front = Window(
            "Front", Rect(3, 22, 5, 14)
        )  # fixed size; clear of the back grip
        self.manager = PresentationManager(windows=[self.back, self.front])
        self.manager.handle_resize(60, 20)

    def send(self, *events: MouseEvent) -> None:
        """Send mouse events to the manager."""
        for event in events:
            self.manager.handle_event(event)

    def test_drag_grip_resizes(self) -> None:
        """The grip follows the pointer; the top-left corner stays put."""
        self.front.resizable = True
        self.send(press(7, 35))
        self.assertTrue(self.manager.is_resizing)
        self.send(drag(10, 30), drag(12, 40))
        self.assertEqual(self.front.rect, Rect(3, 22, 10, 19))
        self.send(release(12, 40), drag(15, 50))
        self.assertIsNone(self.manager.dragging)
        self.assertEqual(self.front.rect, Rect(3, 22, 10, 19))

    def test_left_grip_cell_resizes_without_a_jump(self) -> None:
        """Grabbed by its left cell, the corner keeps its place under the pointer."""
        self.front.resizable = True  # grip cells (7, 34) and (7, 35)
        self.send(press(7, 34), drag(7, 34))
        self.assertTrue(self.manager.is_resizing)
        self.assertEqual(self.front.rect, Rect(3, 22, 5, 14))
        self.send(drag(10, 40), release(10, 40))
        self.assertEqual(self.front.rect, Rect(3, 22, 8, 20))

    def test_grip_of_back_window_raises_then_resizes(self) -> None:
        """Grabbing a back window's grip brings it forward first."""
        self.send(press(6, 19), drag(8, 9), release(8, 9))
        self.assertIs(self.manager.active_window, self.back)
        self.assertEqual(self.back.rect, Rect(1, 0, 8, 12))  # held at min width

    def test_shrinking_stops_at_minimum(self) -> None:
        """Dragging the grip past the top-left corner stops at the minimum."""
        self.send(press(6, 19), drag(0, 0))
        self.assertEqual(
            self.back.rect, Rect(1, 0, self.back.min_height, self.back.min_width)
        )

    def test_fixed_window_corner_does_not_resize(self) -> None:
        """A window that is not resizable just comes to the front."""
        self.manager.bring_to_front(self.back)
        self.send(press(7, 35), drag(12, 40), release(12, 40))
        self.assertIs(self.manager.active_window, self.front)
        self.assertEqual(self.front.rect, Rect(3, 22, 5, 14))
        self.assertFalse(self.manager.is_resizing)

    def test_title_bar_still_moves_a_resizable_window(self) -> None:
        """Resizable windows move by their title bar as before."""
        self.send(press(1, 3), drag(5, 8), release(5, 8))
        self.assertEqual(self.back.rect, Rect(5, 5, 6, 20))

    def test_grip_hidden_by_front_window_cannot_be_grabbed(self) -> None:
        """Only the front-most window at the pointer can be resized."""
        self.back.resize(25, 6)  # grip at (6, 24), under the front window
        self.send(press(6, 24), drag(10, 30))
        self.assertIs(self.manager.active_window, self.front)
        self.assertEqual(self.back.rect, Rect(1, 0, 6, 25))

    def test_shadow_follows_new_size(self) -> None:
        """After resizing, the shadow is drawn around the new size."""
        self.send(press(6, 19), drag(9, 29), release(9, 29))
        canvas = Canvas(60, 20)
        self.manager.compose(canvas)
        self.assertEqual(
            grip_cells(canvas, 9, 29), (GRIP, {self.back.resize_grip_style})
        )
        self.assertEqual(canvas.cell(10, 5)[1], self.back.shadow_style)
        self.assertEqual(canvas.cell(5, 31)[1], self.back.shadow_style)

    def test_resize_through_main_loop(self) -> None:
        """SGR mouse reports resize a window through the main loop."""
        window = Window("W", Rect(1, 0, 4, 12), resizable=True)
        manager = PresentationManager(windows=[window])
        # Grip at 0-based (4, 11) is 1-based column 12, row 5.
        terminal = FakeTerminal(
            ["\x1b[<0;12;5M", "\x1b[<32;16;7M\x1b[<0;16;7m", "\x11", "\r"],
            sizes=[(40, 12)],
        )
        manager.run(cast(Terminal, terminal))
        self.assertEqual(window.rect, Rect(1, 0, 6, 16))


if __name__ == "__main__":
    unittest.main()
