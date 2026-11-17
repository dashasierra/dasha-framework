"""Tests for scrollable window contents and the scroll bars on the frame."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.scrollbar import DOWN, LEFT, RIGHT, THUMB, TRACK, UP, ScrollBarLayout
from dasha.shortcuts import Shortcuts
from dasha.widgets import Button, Label, ScrollBar
from dasha.window import Window


def press(row: int, column: int) -> MouseEvent:
    """A left-button press."""
    return MouseEvent("press", "left", row, column)


def tall_window(lines: int = 20, width: int = 20, height: int = 8) -> Window:
    """A resizable window with more numbered lines than fit."""
    return Window(
        "W",
        Rect(1, 0, height, width),
        [f"line {number}" for number in range(lines)],
        resizable=True,
    )


class CanvasClipTests(unittest.TestCase):
    """The canvas clipping region used for scrolled contents."""

    def test_clipped_writes_and_nesting(self) -> None:
        """Drawing stays inside the clip; clips nest and are restored."""
        canvas = Canvas(10, 3)
        with canvas.clipped(Rect(0, 2, 3, 6)):
            canvas.write(0, 0, "abcdefghij")
            with canvas.clipped(Rect(1, 0, 1, 5)):
                canvas.fill(Rect(0, 0, 3, 10), "#")
        canvas.write(2, 0, "z")
        self.assertEqual(canvas.text(0), "  cdefgh  ")
        self.assertEqual(canvas.text(1), "  ###     ")
        self.assertEqual(canvas.text(2), "z         ")


class ScrollBarTests(unittest.TestCase):
    """Scroll scroll_bar geometry and parts."""

    def test_parts_and_thumb(self) -> None:
        """Arrows at the ends, the thumb where the value is, track around it."""
        scroll_bar = ScrollBarLayout(True, 2, 10, 7, value=5, maximum=10, page=5)
        self.assertEqual(scroll_bar.track_length, 5)
        self.assertEqual(scroll_bar.thumb, 2)
        parts = [scroll_bar.part_at(2 + index, 10) for index in range(7)]
        self.assertEqual(
            parts,
            [
                "back",
                "page_back",
                "page_back",
                "thumb",
                "page_forward",
                "page_forward",
                "forward",
            ],
        )
        self.assertIsNone(scroll_bar.part_at(2, 11))

    def test_value_at_maps_the_track(self) -> None:
        """Dragging the thumb: track positions map onto 0..maximum."""
        scroll_bar = ScrollBarLayout(False, 0, 0, 7, value=0, maximum=40, page=10)
        self.assertEqual(
            [scroll_bar.value_at(0, c) for c in (0, 1, 3, 5, 6)], [0, 0, 20, 40, 40]
        )

    def test_paint(self) -> None:
        """▲ ▒ ■ ▼ vertically; ◄ ► horizontally; all code page 437."""
        canvas = Canvas(6, 5)
        ScrollBarLayout(True, 0, 0, 5, 0, 10, 3).paint(canvas, canvas.cell(0, 0)[1])
        ScrollBarLayout(False, 4, 1, 5, 10, 10, 3).paint(canvas, canvas.cell(0, 0)[1])
        column = "".join(canvas.cell(row, 0)[0] for row in range(4))
        self.assertEqual(column, UP + THUMB + TRACK + TRACK)
        self.assertEqual(canvas.text(4)[1:6], LEFT + TRACK + TRACK + THUMB + RIGHT)
        self.assertEqual(canvas.cell(3, 0)[0], TRACK)
        for char in (TRACK, THUMB):
            char.encode("cp437")
        self.assertEqual({UP, DOWN, LEFT, RIGHT}, {"▲", "▼", "◄", "►"})


class StepTests(unittest.TestCase):
    """What a click on each part of a bar scrolls by."""

    def test_step(self) -> None:
        """A line for an arrow, a page less one for the track, else 0."""
        layout = ScrollBarLayout(True, 0, 0, 7, value=5, maximum=10, page=5)
        steps = {
            part: layout.step(part, line=2)
            for part in ("back", "forward", "page_back", "page_forward", "thumb", None)
        }
        self.assertEqual(
            steps,
            {
                "back": -2,
                "forward": 2,
                "page_back": -4,
                "page_forward": 4,
                "thumb": 0,
                None: 0,
            },
        )


def bar_event(scroll_bar: ScrollBar, action: str, row: int, column: int) -> bool:
    """A left-button event at a position in the window's interior."""
    return scroll_bar.handle_mouse(MouseEvent(action, "left", row, column), row, column)


class ScrollBarWidgetTests(unittest.TestCase):
    """The scroll scroll_bar as a widget of its own."""

    def setUp(self) -> None:
        self.moves: list[int] = []
        # Rows 1-7 at column 4: ▲, a five-cell track, ▼.
        self.scroll_bar = ScrollBar(
            1,
            4,
            7,
            maximum=20,
            page=5,
            on_change=lambda moved: self.moves.append(moved.value),
        )

    def test_arrows_and_track(self) -> None:
        """Arrows move a line, the track a page; the user's moves call
        on_change."""
        bar_event(self.scroll_bar, "press", 7, 4)  # ▼
        bar_event(self.scroll_bar, "press", 6, 4)  # the track below the thumb
        bar_event(self.scroll_bar, "press", 1, 4)  # ▲
        self.assertEqual(self.moves, [1, 5, 4])

    def test_thumb_drag(self) -> None:
        """The thumb follows the pointer, past the ends too."""
        bar_event(self.scroll_bar, "press", 2, 4)  # the thumb, at the top
        bar_event(self.scroll_bar, "drag", 9, 4)
        self.assertEqual(self.scroll_bar.value, 20)
        bar_event(self.scroll_bar, "release", 9, 4)
        bar_event(self.scroll_bar, "drag", 2, 4)  # no longer dragging
        self.assertEqual(self.scroll_bar.value, 20)

    def test_value_is_kept_in_range(self) -> None:
        """Code can set the value, kept in range, without on_change; the
        range can change."""
        self.scroll_bar.value = 99
        self.assertEqual(self.scroll_bar.value, 20)
        self.scroll_bar.set_range(8, page=2)
        self.assertEqual((self.scroll_bar.value, self.scroll_bar.page), (8, 2))
        bar_event(self.scroll_bar, "press", 7, 4)  # ▼ at the end: no move
        self.assertEqual(self.moves, [])

    def test_wheel_and_paint(self) -> None:
        """The wheel moves it a line; it draws with the shared layout."""
        self.scroll_bar.handle_mouse(MouseEvent("scroll", "down", 3, 4), 3, 4)
        self.assertEqual(self.scroll_bar.value, 1)
        canvas = Canvas(6, 9)
        self.scroll_bar.paint(canvas, canvas.bounds, False)
        column = "".join(canvas.cell(row, 4)[0] for row in range(1, 8))
        self.assertEqual(column, UP + THUMB + TRACK * 4 + DOWN)
        self.assertEqual(canvas.cell(1, 4)[1], self.scroll_bar.style)

    def test_horizontal_and_in_a_window(self) -> None:
        """A horizontal scroll_bar is placed with the other widgets; it takes no
        focus, but takes clicks."""
        window = Window("W", Rect(0, 0, 6, 20))
        button = window.add(Button("&OK", 0, 1))
        scroll_bar = window.add(ScrollBar(3, 2, 10, vertical=False, maximum=4))
        self.assertEqual(scroll_bar.rect, Rect(3, 2, 1, 10))
        self.assertFalse(scroll_bar.can_focus())
        window.handle_mouse(MouseEvent("press", "left", 4, 12))  # ►
        self.assertEqual(scroll_bar.value, 1)
        self.assertIs(window.focused, button)
        with self.assertRaises(ValueError):
            ScrollBar(0, 0, 1)


class WindowScrollTests(unittest.TestCase):
    """Content size, scroll bars appearing and disappearing, scrolling."""

    def test_content_size_from_lines_and_widgets(self) -> None:
        """The content reaches as far as the furthest line or widget."""
        window = Window("W", Rect(0, 0, 6, 20), ["abc", "a longer line"])
        self.assertEqual(window.content_size, (14, 2))
        window.add(Label("far", 9, 30))
        self.assertEqual(window.content_size, (33, 10))

    def test_no_scroll_bars_when_content_fits(self) -> None:
        """Content that fits shows no bars, and cannot scroll."""
        window = Window("W", Rect(0, 0, 6, 20), ["short"])
        self.assertEqual(window.scroll_bars, (None, None))
        window.scroll_by(5, 5)
        self.assertEqual((window.scroll_row, window.scroll_column), (0, 0))

    def test_bars_appear_only_in_the_direction_that_overflows(self) -> None:
        """Too tall: a vertical scroll_bar only; too wide as well: both."""
        window = tall_window()
        vertical, horizontal = window.scroll_bars
        self.assertIsNotNone(vertical)
        self.assertIsNone(horizontal)
        window.lines.append("x" * 40)
        vertical, horizontal = window.scroll_bars
        assert vertical is not None and horizontal is not None
        self.assertEqual(vertical.rect, Rect(2, 19, 6, 1))  # right edge
        self.assertEqual(horizontal.rect, Rect(8, 2, 1, 16))  # bottom edge
        grip = window.resize_grip_rect
        assert grip is not None
        self.assertTrue(horizontal.rect.intersect(grip).is_empty)

    def test_resizing_bigger_removes_bars_and_scroll(self) -> None:
        """Once everything fits, the bars go and the view returns to the top."""
        window = tall_window(lines=10)
        window.scroll_by(3, 0)
        self.assertEqual(window.scroll_row, 3)
        window.resize(20, 12)  # interior 10 rows: all ten lines fit
        self.assertEqual(window.scroll_bars, (None, None))
        self.assertEqual(window.scroll_row, 0)

    def test_scrolled_lines_are_drawn_shifted(self) -> None:
        """The view starts at the scroll position; bars sit on the frame."""
        window = tall_window()
        window.scroll_to(5, 0)
        canvas = Canvas(20, 10)
        window.paint(canvas, active=True)
        self.assertEqual(canvas.text(2)[2:8], "line 5")
        self.assertEqual(canvas.cell(2, 19)[0], UP)
        self.assertEqual(canvas.cell(7, 19)[0], DOWN)

    def test_scrolled_widgets_stay_inside_frame(self) -> None:
        """A widget scrolled partly out of view is cut off at the frame."""
        window = Window("W", Rect(0, 0, 5, 16))
        window.add(Label("0123456789ABCDEFGHIJ", 0, 0))  # 6 wider than inside
        window.scroll_to(0, 4)
        canvas = Canvas(16, 5)
        window.paint(canvas, active=True)
        self.assertEqual(canvas.text(1)[1:15], "456789ABCDEFGH")
        self.assertEqual(canvas.cell(1, 0)[0], window.border.vertical)

    def test_clicks_land_on_scrolled_widgets(self) -> None:
        """A click hits the widget drawn there, wherever it is scrolled to."""
        pressed: list[str] = []
        window = Window("W", Rect(0, 0, 6, 20))
        window.add(Button("Far", 10, 1, action=lambda _b: pressed.append("far")))
        window.scroll_to(8, 0)  # the most it scrolls: the face is on screen row 3
        window.handle_mouse(press(3, 3))
        window.handle_mouse(MouseEvent("release", "left", 3, 3))
        self.assertEqual(pressed, ["far"])

    def test_focus_scrolls_into_view(self) -> None:
        """Tabbing to a widget out of view scrolls to show it."""
        window = Window("W", Rect(0, 0, 6, 20))
        window.add(Button("One", 0, 1))
        far = window.add(Button("Two", 12, 1))
        window.focus_next()
        self.assertIs(window.focused, far)
        self.assertEqual(window.scroll_row, 10)  # rows 12-13 at the bottom

    def test_keys_scroll_only_when_there_is_something_to_scroll(self) -> None:
        """Arrow and page keys scroll; with nothing to scroll they pass on."""
        shortcuts = Shortcuts()
        window = tall_window()
        self.assertTrue(window.handle_key("down", shortcuts))
        self.assertTrue(window.handle_key("pagedown", shortcuts))
        self.assertEqual(window.scroll_row, 1 + 5)
        self.assertTrue(window.handle_key("pageup", shortcuts))
        self.assertEqual(window.scroll_row, 1)
        self.assertFalse(window.handle_key("right", shortcuts))  # fits sideways


class ManagerScrollTests(unittest.TestCase):
    """Scroll bars and the wheel through the presentation manager."""

    def setUp(self) -> None:
        self.window = tall_window()  # rows 1-8, columns 0-19; scroll_bar at column 19
        self.manager = PresentationManager(windows=[self.window])
        self.manager.handle_resize(40, 20)

    def test_arrows_and_track(self) -> None:
        """Arrows scroll a line; the track scrolls a page."""
        self.manager.handle_event(press(7, 19))  # ▼
        self.assertEqual(self.window.scroll_row, 1)
        self.manager.handle_event(press(2, 19))  # ▲
        self.assertEqual(self.window.scroll_row, 0)
        self.manager.handle_event(press(6, 19))  # track below the thumb
        self.assertEqual(self.window.scroll_row, 5)

    def test_drag_thumb(self) -> None:
        """Dragging the thumb to the end of the track scrolls to the end."""
        self.manager.handle_event(press(3, 19))  # the thumb, at the top
        self.manager.handle_event(MouseEvent("drag", "left", 6, 19))
        self.manager.handle_event(MouseEvent("release", "left", 6, 19))
        self.assertEqual(self.window.scroll_row, self.window.max_scroll[0])
        self.assertIsNone(self.manager.dragging)

    def test_mouse_wheel(self) -> None:
        """The wheel scrolls the window under the pointer three lines."""
        self.manager.handle_event(MouseEvent("scroll", "down", 4, 5))
        self.assertEqual(self.window.scroll_row, 3)
        self.manager.handle_event(MouseEvent("scroll", "up", 4, 5))
        self.assertEqual(self.window.scroll_row, 0)
        self.manager.handle_event(MouseEvent("scroll", "down", 15, 30))  # desktop
        self.assertEqual(self.window.scroll_row, 0)

    def test_keys_through_manager(self) -> None:
        """Down scrolls the active window."""
        self.manager.handle_event("down")
        self.assertEqual(self.window.scroll_row, 1)


class IntoViewTests(unittest.TestCase):
    """Scrolling something into view, as little as can be. The window shows
    10 rows of 40 lines."""

    def setUp(self) -> None:
        self.window = Window("W", Rect(0, 0, 12, 30), [""] * 40)

    def into_view(self, scroll_row: int, rect: Rect) -> int:
        """Where the window is scrolled to, from ``scroll_row``."""
        self.window.scroll_to(scroll_row, 0)
        self.window.scroll_into_view(rect)
        return self.window.scroll_row

    def test_small_things(self) -> None:
        """Shown already: no scrolling; below: just enough; above: to it."""
        self.assertEqual(self.into_view(5, Rect(8, 0, 2, 5)), 5)
        self.assertEqual(self.into_view(5, Rect(20, 0, 2, 5)), 12)
        self.assertEqual(self.into_view(5, Rect(1, 0, 2, 5)), 1)

    def test_big_things_partly_shown(self) -> None:
        """Bigger than the window, part of it showing: no scrolling."""
        self.assertEqual(self.into_view(15, Rect(0, 0, 40, 5)), 15)
        self.assertEqual(self.into_view(2, Rect(8, 0, 20, 5)), 2)

    def test_big_things_out_of_view(self) -> None:
        """Bigger than the window and not showing: in until it fills it."""
        self.assertEqual(self.into_view(0, Rect(15, 0, 20, 5)), 15)
        self.assertEqual(self.into_view(30, Rect(2, 0, 15, 5)), 7)


if __name__ == "__main__":
    unittest.main()
