"""Tests for switches."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.dialog import Dialog
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.widgets import SHADOW_BELOW, SHADOW_RIGHT, Button, Switch
from dasha.widgets.switch import KNOB, TRACK
from dasha.window import Window


def paint(window: Window) -> Canvas:
    """Paint a window on a canvas just big enough."""
    canvas = Canvas(window.rect.right, window.rect.bottom)
    window.paint(canvas, active=True)
    return canvas


class SwitchTests(unittest.TestCase):
    """Drawing, keys, the mouse and reading it back."""

    def setUp(self) -> None:
        self.changes: list[bool] = []
        self.window = Window("W", Rect(0, 0, 8, 30))
        self.switch = self.window.add(
            Switch(
                "&Dark mode",
                1,
                1,
                on_change=lambda s: self.changes.append(s.on),
                name="dark",
            )
        )
        self.window.add(Button("&OK", 4, 1))
        self.shortcuts = Shortcuts()

    def keys(self, *names: str) -> list[bool]:
        """Offer keys to the window."""
        return [self.window.handle_key(name, self.shortcuts) for name in names]

    def test_drawn_off_and_on(self) -> None:
        """The knob on the left when off, on the right when on, in the
        switch's colours, with a button's shadow and the label after it."""
        canvas = paint(self.window)
        top, left = 2, 2  # interior row 1, column 1
        self.assertEqual(canvas.text(top)[left : left + 3], KNOB + TRACK + TRACK)
        self.assertEqual(canvas.cell(top, left)[1], Switch.off_style)
        self.assertEqual(canvas.cell(top, left + 3)[0], SHADOW_RIGHT)
        self.assertEqual(canvas.text(top + 1)[left + 1 : left + 4], SHADOW_BELOW * 3)
        self.assertEqual(canvas.text(top)[left + 5 : left + 14], "Dark mode")
        self.switch.on = True
        canvas = paint(self.window)
        self.assertEqual(canvas.text(top)[left : left + 3], TRACK + TRACK + KNOB)
        self.assertEqual(canvas.cell(top, left)[1], Switch.on_style)

    def test_outline_shadow_in_monochrome(self) -> None:
        """With the outline button shadow, the switch has it too."""
        before = Button.shadow_shape
        Button.shadow_shape = "outline"
        try:
            canvas = paint(self.window)
        finally:
            Button.shadow_shape = before
        self.assertEqual(canvas.cell(2, 5)[0], "\N{BOX DRAWINGS LIGHT DOWN AND LEFT}")
        self.assertEqual(
            canvas.text(3)[2:6],
            "\N{BOX DRAWINGS LIGHT UP AND RIGHT}"
            + "\N{BOX DRAWINGS LIGHT HORIZONTAL}" * 2
            + "\N{BOX DRAWINGS LIGHT UP AND LEFT}",
        )

    def test_focus_reverses_the_label(self) -> None:
        """The focused switch's label is drawn in reverse video, its letter
        underlined; unfocused it is in the window's colours."""
        canvas = paint(self.window)  # the switch is focused (added first)
        self.assertTrue(canvas.cell(2, 8)[1].reverse)
        self.assertTrue(canvas.cell(2, 7)[1].underline)  # the D
        self.keys("tab")
        canvas = paint(self.window)
        self.assertEqual(canvas.cell(2, 8)[1], self.window.body_style)

    def test_keys(self) -> None:
        """Space flips it; Right turns it on and Left off, again and again
        changing nothing more; Enter and Tab are left for the window."""
        self.keys(" ")
        self.assertTrue(self.switch.on)
        self.keys(" ", "right", "right")
        self.assertTrue(self.switch.on)
        self.keys("left", "left")
        self.assertFalse(self.switch.on)
        self.assertEqual(self.changes, [True, False, True, False])
        self.assertFalse(self.switch.handle_key("enter", self.shortcuts))
        self.assertFalse(self.switch.handle_key("tab", self.shortcuts))

    def test_mouse(self) -> None:
        """A press on the track or the label flips it."""
        self.switch.handle_mouse(MouseEvent("press", "left", 1, 1), 1, 1)
        self.assertTrue(self.switch.on)
        self.switch.handle_mouse(MouseEvent("press", "left", 1, 8), 1, 8)
        self.assertFalse(self.switch.on)

    def test_mnemonic_and_dialog_values(self) -> None:
        """In a dialog its letter alone flips it, and the caller reads a
        true-or-false value."""
        dialog = Dialog("Q", 30, 8)
        dialog.add(Button("&OK", 4, 1, result="ok", default=True))
        dialog.add(Switch("&Dark mode", 1, 1, name="dark"))
        dialog.handle_key("d", self.shortcuts)
        self.assertEqual(dialog.values["dark"], True)

    def test_disabled(self) -> None:
        """A disabled switch is greyed out, takes no focus, and nothing
        changes it, not even its letter."""
        switch = Switch("&Sound", 0, 0, disabled=True)
        self.assertFalse(switch.can_focus())
        self.assertFalse(switch.handle_key(" ", self.shortcuts))
        switch.handle_mouse(MouseEvent("press", "left", 0, 0), 0, 0)
        self.assertEqual(switch.mnemonics(), set())
        self.assertFalse(switch.on)
        window = Window("W", Rect(0, 0, 4, 20))
        window.add(switch)
        self.assertEqual(paint(window).cell(1, 1)[1], Switch.disabled_style)

    def test_remapped_keys(self) -> None:
        """The switch's keys are shortcuts like any other."""
        shortcuts = Shortcuts({"switch_toggle": ["t"], "switch_on": ["l"]})
        self.switch.handle_key("t", shortcuts)
        self.assertTrue(self.switch.on)
        self.assertFalse(self.switch.handle_key(" ", shortcuts))

    def test_size(self) -> None:
        """Three cells, the shadow column, a gap and the label, two rows."""
        self.assertEqual((self.switch.rect.width, self.switch.rect.height), (14, 2))
        self.assertEqual(Switch("", 0, 0).rect.width, 4)


if __name__ == "__main__":
    unittest.main()
