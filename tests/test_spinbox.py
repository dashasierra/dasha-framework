"""Tests for spin boxes: numbers stepped or typed, kept to their range."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.scrollbar import DOWN, UP, AutoRepeat
from dasha.shortcuts import Shortcuts
from dasha.widgets import Button, SpinBox
from dasha.window import Window


def press(column: int, action: str = "press") -> MouseEvent:
    """A left button event on row 0.

    :param column: Interior column.
    :param action: Mouse action.
    """
    return MouseEvent(action=action, button="left", row=0, column=column)


class SpinBoxTests(unittest.TestCase):
    """A 0 to 100 spin box in a window."""

    def setUp(self) -> None:
        self.changes: list[int] = []
        self.window = Window("W", Rect(0, 0, 6, 30))
        self.box = self.window.add(
            SpinBox(
                0,
                0,
                8,
                minimum=0,
                maximum=100,
                value=42,
                on_change=lambda b: self.changes.append(b.value),
            )
        )
        self.window.add(Button("&OK", 2, 0))

    def keys(self, *names: str) -> None:
        """Send keys to the window.

        :param names: The keys.
        """
        for name in names:
            self.window.handle_key(name, Shortcuts())

    def test_drawn(self) -> None:
        """The number in the field, then the arrows."""
        canvas = Canvas(8, 1)
        self.box.paint(canvas, canvas.bounds, False)
        self.assertEqual(canvas.text(0), " 42   " + DOWN + UP)
        self.assertEqual(canvas.cell(0, 6)[1], SpinBox.arrow_style)

    def test_steps_and_stops_at_the_ends(self) -> None:
        """Up, Down and the page keys, held to the range."""
        self.keys("up", "up", "pagedown", "down")
        self.assertEqual(self.box.value, 33)
        self.keys("pageup", "pageup", "pageup", "pageup", "pageup", "pageup", "pageup")
        self.assertEqual(self.box.value, 100)
        self.assertEqual(self.changes[-1], 100)
        self.assertEqual(self.changes.count(100), 1)

    def test_typing_replaces_the_number(self) -> None:
        """Typing replaces the number."""
        self.box.focus_changed(True)
        self.keys("7", "5")
        self.assertEqual(self.box.value, 42)  # not yet
        self.keys("tab")
        self.assertEqual(self.box.value, 75)
        self.assertEqual(self.changes, [75])

    def test_out_of_range_is_thrown_away(self) -> None:
        """Out of range is thrown away."""
        self.box.focus_changed(True)
        self.keys("1", "5", "0", "tab")
        self.assertEqual((self.box.value, self.box.field.text), (42, "42"))
        self.assertEqual(self.changes, [])

    def test_typing_its_own_first_digit(self) -> None:
        """Typing its own first digit."""
        self.box.value = 1
        self.box.focus_changed(True)
        self.keys("1", "5", "tab")
        self.assertEqual(self.box.value, 15)

    def test_empty_is_thrown_away(self) -> None:
        """Clearing it and leaving puts it back too."""
        self.keys("ctrl+y", "enter")
        self.assertEqual(self.box.field.text, "42")

    def test_letters_cannot_be_typed(self) -> None:
        """Only digits go in."""
        self.box.focus_changed(True)
        self.keys("x")
        self.assertEqual(self.box.field.text, "42")

    def test_stepping_takes_what_was_typed(self) -> None:
        """Typed 10, then Up: 11."""
        self.box.focus_changed(True)
        self.keys("1", "0", "up")
        self.assertEqual(self.box.value, 11)

    def test_negative_ranges(self) -> None:
        """A minus sign can be typed when the range goes below 0."""
        box = SpinBox(0, 0, 8, minimum=-10, maximum=10)
        self.assertEqual(box.value, -10)
        box.focus_changed(True)
        for key in ("-", "3"):
            box.handle_key(key, Shortcuts())
        box.commit()
        self.assertEqual(box.value, -3)

    def test_arrows_and_wheel(self) -> None:
        """Arrows and wheel."""
        self.box.handle_mouse(press(7), 0, 7)
        self.assertEqual(self.box.value, 43)
        wake = self.box.wake_time()
        assert wake is not None
        self.box.on_timer(wake)
        self.box.on_timer(wake + AutoRepeat.interval)
        self.assertEqual(self.box.value, 45)
        self.box.handle_mouse(press(7, "release"), 0, 7)
        self.assertIsNone(self.box.wake_time())
        self.box.handle_mouse(press(6), 0, 6)
        self.box.handle_mouse(press(6, "release"), 0, 6)
        self.assertEqual(self.box.value, 44)
        wheel = MouseEvent(action="scroll", button="up", row=0, column=2)
        self.box.handle_mouse(wheel, 0, 2)
        self.assertEqual(self.box.value, 45)

    def test_value_from_code(self) -> None:
        """Set from code: kept in range, no on_change."""
        self.box.value = 500
        self.assertEqual((self.box.value, self.box.field.text), (100, "100"))
        self.assertEqual(self.changes, [])
        with self.assertRaises(ValueError):
            SpinBox(0, 0, 8, minimum=5, maximum=1)

    def test_bad_sizes_and_steps(self) -> None:
        """Too narrow for the field and arrows, or a step below 1."""
        with self.assertRaises(ValueError):
            SpinBox(0, 0, 4, minimum=0, maximum=9)
        with self.assertRaises(ValueError):
            SpinBox(0, 0, 8, minimum=0, maximum=9, step=0)
        self.assertEqual(self.box.min_size(), (SpinBox.min_width, 1))

    def test_key_help(self) -> None:
        """Up/Down to step; with no keys to step, nothing."""
        self.assertEqual(self.box.key_help(Shortcuts()), [("Up/Down", "Step")])
        no_steps = Shortcuts({"spin_up": [], "spin_down": []})
        self.assertEqual(self.box.key_help(no_steps), [])

    def test_paste(self) -> None:
        """Pasting goes in the field, as typing does; it counts on leaving."""
        self.box.focus_changed(True)
        self.assertTrue(self.box.handle_paste("64"))
        self.keys("tab")
        self.assertEqual(self.box.value, 64)

    def test_the_field_takes_the_mouse(self) -> None:
        """The field takes the mouse."""
        self.box.focus_changed(False)
        self.box.handle_mouse(press(1), 0, 1)
        self.box.handle_mouse(press(3, "drag"), 0, 3)
        self.box.handle_mouse(press(3, "release"), 0, 3)
        self.assertEqual(self.box.field.selection, (0, 2))
        right = MouseEvent(action="press", button="right", row=0, column=1)
        self.assertFalse(self.box.handle_mouse(right, 0, 1))

    def test_holding_an_arrow_off_it(self) -> None:
        """Held on ▲ and dragged off it, it stops repeating, until back."""
        self.box.handle_mouse(press(7), 0, 7)
        self.assertEqual(self.box.value, 43)
        self.box.handle_mouse(press(2, "drag"), 0, 2)  # off the arrows
        wake = self.box.wake_time()
        assert wake is not None
        self.box.on_timer(wake)
        self.assertEqual(self.box.value, 43)
        self.box.handle_mouse(press(7, "drag"), 0, 7)  # back on ▲
        self.box.on_timer(wake + AutoRepeat.interval)
        self.assertEqual(self.box.value, 44)
        self.box.handle_mouse(press(7, "release"), 0, 7)

    def test_the_fields_timer(self) -> None:
        """With no arrow held, the field's own timer (drag-scrolling) runs."""
        box = SpinBox(0, 0, 6, minimum=0, maximum=99999, value=12345)
        box.focus_changed(False)
        box.handle_mouse(press(2), 0, 2)
        box.handle_mouse(press(0, "drag"), 0, 0)  # onto the field's ◄
        before = box.field.selection
        wake = box.wake_time()
        assert wake is not None and before is not None
        box.on_timer(wake)
        after = box.field.selection
        assert after is not None
        self.assertLess(after[0], before[0])  # it selected one more to the left


if __name__ == "__main__":
    unittest.main()
