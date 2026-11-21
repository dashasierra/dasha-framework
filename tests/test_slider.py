"""Tests for sliders, across and standing up."""

import unittest

from dasha.canvas import Canvas
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.widgets import Slider
from dasha.widgets.slider import ACROSS, KNOB, UP_AND_DOWN


def press(row: int, column: int, action: str = "press") -> MouseEvent:
    """A left button event.

    :param row: Screen row.
    :param column: Screen column.
    :param action: Mouse action.
    """
    return MouseEvent(action=action, button="left", row=row, column=column)


class SliderTests(unittest.TestCase):
    """A slider across, 0 to 100 over 11 cells."""

    def setUp(self) -> None:
        self.changes: list[int] = []
        self.slider = Slider(
            0, 0, 11, value=50, on_change=lambda s: self.changes.append(s.value)
        )

    def keys(self, *names: str) -> None:
        """Offer keys to the slider.

        :param names: The keys.
        """
        for name in names:
            self.assertTrue(self.slider.handle_key(name, Shortcuts()), name)

    def test_drawn(self) -> None:
        """The knob halfway along the track."""
        canvas = Canvas(11, 1)
        self.slider.paint(canvas, canvas.bounds, False)
        self.assertEqual(canvas.text(0), ACROSS * 5 + KNOB + ACROSS * 5)
        self.assertEqual(canvas.cell(0, 5)[1], Slider.knob_style)
        self.slider.paint(canvas, canvas.bounds, True)
        self.assertEqual(canvas.cell(0, 5)[1], Slider.focused_knob_style)
        self.assertEqual(canvas.cell(0, 0)[1], Slider.focused_style)

    def test_keys(self) -> None:
        """Steps, pages and the ends."""
        self.keys("right", "up")
        self.assertEqual(self.slider.value, 52)
        self.keys("left", "pagedown")
        self.assertEqual(self.slider.value, 41)
        self.keys("end")
        self.assertEqual(self.slider.value, 100)
        self.keys("right", "home")
        self.assertEqual(self.changes, [51, 52, 51, 41, 100, 0])

    def test_mouse(self) -> None:
        """A press puts the knob there, and a drag takes it along."""
        self.assertTrue(self.slider.handle_mouse(press(0, 2), 0, 2))
        self.assertEqual(self.slider.value, 20)
        self.slider.handle_mouse(press(0, 30, "drag"), 0, 30)
        self.assertEqual(self.slider.value, 100)
        self.slider.handle_mouse(press(0, 9, "release"), 0, 9)
        self.slider.handle_mouse(press(0, 0, "drag"), 0, 0)
        self.assertEqual(self.slider.value, 100)  # released: no longer dragging
        wheel = MouseEvent(action="scroll", button="down", row=0, column=3)
        self.slider.handle_mouse(wheel, 0, 3)
        self.assertEqual(self.slider.value, 99)

    def test_steps(self) -> None:
        """Values keep to the steps and the range."""
        slider = Slider(0, 0, 5, minimum=10, maximum=50, step=10, value=33)
        self.assertEqual(slider.value, 30)
        slider.value = 99
        self.assertEqual(slider.value, 50)
        self.assertEqual(slider.page, 10)


class VerticalSliderTests(unittest.TestCase):
    """Standing up: the maximum at the top."""

    def test_drawn_and_clicked(self) -> None:
        """Drawn and clicked vertically."""
        slider = Slider(0, 0, 5, vertical=True)
        canvas = Canvas(1, 5)
        slider.paint(canvas, canvas.bounds, False)
        self.assertEqual([canvas.text(r) for r in range(5)], [UP_AND_DOWN] * 4 + [KNOB])
        slider.handle_mouse(press(0, 0), 0, 0)
        self.assertEqual(slider.value, 100)
        slider.handle_mouse(press(2, 0, "drag"), 2, 0)
        self.assertEqual(slider.value, 50)
        self.assertTrue(slider.handle_key("down", Shortcuts()))
        self.assertEqual(slider.value, 49)


if __name__ == "__main__":
    unittest.main()
