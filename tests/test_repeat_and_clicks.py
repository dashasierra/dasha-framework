"""Tests for double-clicks, Shift+click ranges and auto-repeating scroll bars."""

import unittest
from unittest import mock

from dasha.canvas import Rect
from dasha.dialog import Dialog
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.scrollbar import AutoRepeat
from dasha.widgets import Button, ListBox, ScrollBar
from dasha.window import Window

NAMES = [f"file{number:02}.txt" for number in range(20)]


def press(row: int, column: int, *, shift: bool = False, clicks: int = 1) -> MouseEvent:
    """A left-button press."""
    return MouseEvent("press", "left", row, column, shift=shift, clicks=clicks)


def release(row: int, column: int) -> MouseEvent:
    """A left-button release."""
    return MouseEvent("release", "left", row, column)


class ClickCountTests(unittest.TestCase):
    """The presentation manager counts double-clicks."""

    def setUp(self) -> None:
        self.seen: list[int] = []
        seen = self.seen

        class Recorder(Button):
            """Notes how many clicks each press it gets counts."""

            def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
                if event.action == "press":
                    seen.append(event.clicks)
                return True

        window = Window("W", Rect(1, 0, 6, 30))
        window.add(Recorder("&R", 0, 0))
        self.manager = PresentationManager(windows=[window])
        self.manager.handle_resize(40, 12)

    def clicks_at(self, times: list[float], cells: list[tuple[int, int]]) -> list[int]:
        """Press at each cell at each time; the click counts seen."""
        with mock.patch("dasha.manager.time.monotonic", side_effect=times):
            for row, column in cells:
                self.manager.handle_event(press(row, column))
                self.manager.handle_event(release(row, column))
        return self.seen

    def test_double_and_triple(self) -> None:
        """Quick presses in the same cell count up."""
        self.assertEqual(self.clicks_at([0.0, 0.2, 0.3], [(2, 2)] * 3), [1, 2, 3])

    def test_too_slow_or_elsewhere(self) -> None:
        """Too long between presses, or another cell, starts again."""
        self.assertEqual(
            self.clicks_at([0.0, 1.0, 1.1], [(2, 2), (2, 2), (2, 3)]), [1, 1, 1]
        )


class ListBoxClickTests(unittest.TestCase):
    """Double-clicks choose; Shift+click selects a range."""

    def test_double_click_calls_on_choose(self) -> None:
        """The second press of a double-click on the same item chooses it."""
        chosen: list[list[str]] = []
        box = ListBox(
            NAMES, 0, 0, 14, 5, on_choose=lambda b: chosen.append(b.selected_items)
        )
        box.handle_mouse(press(2, 1), 2, 1)
        box.handle_mouse(press(2, 1, clicks=2), 2, 1)
        self.assertEqual(chosen, [["file02.txt"]])
        box.handle_mouse(press(3, 1, clicks=2), 3, 1)  # a new item: not chosen
        self.assertEqual(len(chosen), 1)

    def test_double_click_presses_the_default_button(self) -> None:
        """Without on_choose, a double-click in a dialog presses OK."""
        dialog = Dialog("Open", 30, 12)
        box = dialog.add(ListBox(NAMES, 0, 1, 20, 5, multiple=True))
        dialog.add(Button("&OK", 7, 1, result="ok", default=True))
        box.handle_mouse(press(1, 2), 1, 2)
        box.handle_mouse(press(1, 2, clicks=2), 1, 2)
        self.assertEqual(dialog.result, "ok")
        self.assertEqual(box.value, (1,))  # toggled once, by the first press

    def test_shift_click_selects_a_range(self) -> None:
        """From the last item clicked to the one Shift+clicked, either way."""
        box = ListBox(NAMES, 0, 0, 14, 10, multiple=True)
        box.handle_mouse(press(2, 1), 2, 1)
        box.handle_mouse(press(5, 1, shift=True), 5, 1)
        self.assertEqual(box.value, (2, 3, 4, 5))
        box.handle_mouse(press(8, 1), 8, 1)
        box.handle_mouse(press(7, 1, shift=True), 7, 1)
        self.assertEqual(box.value, (2, 3, 4, 5, 7, 8))

    def test_shift_click_after_space(self) -> None:
        """Space sets where the next range starts, too."""
        box = ListBox(NAMES, 0, 0, 14, 10, multiple=True)
        box.cursor = 6
        box.toggle(6)
        box.handle_mouse(press(4, 1, shift=True), 4, 1)
        self.assertEqual(box.value, (4, 5, 6))

    def test_shift_click_with_single_selection(self) -> None:
        """With single selection, Shift+click just selects."""
        box = ListBox(NAMES, 0, 0, 14, 5)
        box.handle_mouse(press(3, 1, shift=True), 3, 1)
        self.assertEqual(box.value, 3)


class AutoRepeatTests(unittest.TestCase):
    """Holding a scroll bar's arrow or track down repeats it."""

    def test_helper(self) -> None:
        """A wait of delay first, then interval, only on the same part."""
        repeat = AutoRepeat()
        repeat.start("forward", 0, 0, now=10.0)
        self.assertEqual(repeat.wake_time(), 10.0 + AutoRepeat.delay)
        self.assertFalse(repeat.due(10.1, "forward"))  # too soon
        self.assertTrue(repeat.due(10.0 + AutoRepeat.delay, "forward"))
        self.assertEqual(
            repeat.wake_time(), 10.0 + AutoRepeat.delay + AutoRepeat.interval
        )
        self.assertFalse(repeat.due(20.0, "page_forward"))  # moved off the arrow
        repeat.stop()
        self.assertIsNone(repeat.wake_time())
        repeat.start("thumb", 0, 0, now=0.0)  # the thumb drags; it never repeats
        self.assertIsNone(repeat.wake_time())

    def test_scroll_bar_widget(self) -> None:
        """A held arrow keeps scrolling until released."""
        scroll_bar = ScrollBar(0, 0, 7, maximum=50, page=5)
        scroll_bar.handle_mouse(press(6, 0), 6, 0)  # ▼
        self.assertEqual(scroll_bar.value, 1)
        for _ in range(3):
            wake = scroll_bar.wake_time()
            assert wake is not None
            scroll_bar.on_timer(wake)
        self.assertEqual(scroll_bar.value, 4)
        scroll_bar.handle_mouse(release(6, 0), 6, 0)
        self.assertIsNone(scroll_bar.wake_time())

    def test_track_stops_at_the_pointer(self) -> None:
        """Held on the track, it pages until the thumb reaches the pointer."""
        scroll_bar = ScrollBar(0, 0, 12, maximum=100, page=10)
        scroll_bar.handle_mouse(press(8, 0), 8, 0)  # the track, low down
        for _ in range(20):
            wake = scroll_bar.wake_time()
            assert wake is not None
            scroll_bar.on_timer(wake)
        layout = scroll_bar.layout(0, 0)
        self.assertEqual(layout.part_at(8, 0), "thumb")
        self.assertLess(scroll_bar.value, 100)

    def test_list_box_bar_repeats(self) -> None:
        """A list box passes its bar's repeats on, so the manager wakes it."""
        box = ListBox(NAMES, 0, 0, 14, 5)
        box.handle_mouse(press(4, 13), 4, 13)  # its bar's ▼
        wake = box.wake_time()
        assert wake is not None
        box.on_timer(wake)
        self.assertEqual((box.first_visible, box.cursor), (2, 0))

    def test_window_frame_bar(self) -> None:
        """A held arrow on a window's frame repeats through the manager's
        timers, and stops on release or when the pointer leaves it."""
        window = Window("W", Rect(1, 0, 8, 20), [str(n) for n in range(30)])
        manager = PresentationManager(windows=[window])
        manager.handle_resize(40, 20)
        manager.handle_event(press(7, 19))  # ▼ on the right edge
        self.assertEqual(window.scroll_row, 1)
        manager.run_timers(1e12)  # long past the delay
        self.assertEqual(window.scroll_row, 2)
        manager.handle_event(MouseEvent("drag", "left", 7, 25))  # off the arrow
        manager.run_timers(2e12)
        self.assertEqual(window.scroll_row, 2)
        manager.handle_event(MouseEvent("drag", "left", 7, 19))  # back on it
        manager.run_timers(3e12)
        self.assertEqual(window.scroll_row, 3)
        manager.handle_event(release(7, 19))
        self.assertIsNone(manager.dragging)
        manager.run_timers(4e12)
        self.assertEqual(window.scroll_row, 3)


if __name__ == "__main__":
    unittest.main()
