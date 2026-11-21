"""Tests for combo boxes and the lists they drop down."""

import unittest
from typing import cast

from dasha.canvas import Canvas, Rect
from dasha.dialog import Dialog, ListPopup
from dasha.manager import PresentationManager
from dasha.shortcuts import Shortcuts
from dasha.terminal import Terminal
from dasha.widgets import ComboBox
from dasha.widgets.combobox import DROP_DOWN
from dasha.window import Window
from tests.test_manager import FakeTerminal

TYPES = ["All files (*)", "Text files (*.txt)", "Python (*.py)"]

ALT_DOWN = "\x1b[1;3B"
DOWN = "\x1b[B"


def keys(box: ComboBox, *names: str) -> None:
    """Offer keys to a combo box.

    :param box: The combo box.
    :param names: The keys.
    """
    shortcuts = Shortcuts()
    for name in names:
        box.handle_key(name, shortcuts)


class ComboBoxTests(unittest.TestCase):
    """The closed field."""

    def setUp(self) -> None:
        self.changes: list[int] = []
        self.box = ComboBox(
            TYPES, 0, 0, 16, on_change=lambda b: self.changes.append(b.value)
        )

    def test_drawn(self) -> None:
        """The choice, cut to fit, then ▼ in the button's colours."""
        canvas = Canvas(16, 1)
        self.box.paint(canvas, canvas.bounds, False)
        self.assertEqual(canvas.text(0), " All files (*)  "[:15] + DROP_DOWN)
        self.assertEqual(canvas.cell(0, 15)[1], ComboBox.button_style)
        self.assertEqual(canvas.cell(0, 1)[1], ComboBox.style)
        self.box.paint(canvas, canvas.bounds, True)
        self.assertEqual(canvas.cell(0, 1)[1], ComboBox.focused_style)

    def test_up_down_and_letters(self) -> None:
        """Up and Down step through without opening; a letter jumps."""
        keys(self.box, "down", "down", "down")
        self.assertEqual((self.box.value, self.box.selected_item), (2, "Python (*.py)"))
        keys(self.box, "up", "t")
        self.assertEqual(self.box.selected_item, "Text files (*.txt)")
        keys(self.box, "z")  # nothing starts with z: unchanged
        self.assertEqual(self.changes, [1, 2, 1])

    def test_left_for_the_window(self) -> None:
        """Enter, Tab and Escape pass on; Space is not taken either."""
        shortcuts = Shortcuts()
        for key in ("enter", "tab", "escape", " "):
            self.assertFalse(self.box.handle_key(key, shortcuts), key)

    def test_not_running_does_nothing(self) -> None:
        """With no running manager, dropping the list down shows nothing."""
        window = Window("W", Rect(0, 0, 4, 20))
        box = window.add(ComboBox(TYPES, 0, 0, 16))
        keys(box, "alt+down")
        PresentationManager(windows=[window])
        keys(box, "f4")
        self.assertEqual(box.value, 0)

    def test_set_items(self) -> None:
        """New items from code, without on_change."""
        self.box.set_items(["a", "b"], selected=1)
        self.assertEqual(self.box.selected_item, "b")
        self.assertEqual(self.changes, [])


class DropDownTests(unittest.TestCase):
    """Dropping the list down, through a running manager."""

    def run_with(self, inputs: list[str], row: int = 2) -> ComboBox:
        """Run a window with a combo box.

        :param inputs: Input to read.
        :param row: The box's row.
        """
        window = Window("W", Rect(1, 0, 18, 40))
        box = window.add(ComboBox(TYPES, row, 2, 20))
        manager = PresentationManager(windows=[window])
        terminal = FakeTerminal([*inputs, "\x11", "\r"], sizes=[(60, 20)])
        manager.run(cast(Terminal, terminal))
        self.assertEqual(terminal.inputs, [])
        return box

    def test_choose_with_the_keys(self) -> None:
        """Alt+Down drops it down; Down and Enter choose."""
        box = self.run_with([ALT_DOWN, DOWN, DOWN, "\r"])
        self.assertEqual(box.value, 2)

    def test_escape_leaves_it(self) -> None:
        """Escape closes the list and keeps the choice."""
        box = self.run_with([ALT_DOWN, DOWN, "\x1b", ""])
        self.assertEqual(box.value, 0)

    def test_click_to_open_and_choose(self) -> None:
        """Clicks open the list and choose."""
        box = self.run_with(["\x1b[<0;5;5M", "\x1b[<0;5;5m", "\x1b[<0;5;8M"])
        self.assertEqual(box.value, 1)

    def test_click_outside_closes_it(self) -> None:
        """A click away from the list closes it, unchanged."""
        box = self.run_with(["\x1b[<0;5;5M", "\x1b[<0;5;5m", DOWN, "\x1b[<0;50;18M"])
        self.assertEqual(box.value, 0)


class PlacementTests(unittest.TestCase):
    """Where the list drops down."""

    def placed(self, below: Rect, items: int = 3) -> Rect:
        """Where a list would be shown.

        :param below: The field's screen rect.
        :param items: Number of items.
        """
        seen: list[Rect] = []

        class Recording(PresentationManager):
            """Shows nothing: just notes where the list went."""

            def execute(self, dialog: Dialog) -> str | None:
                assert isinstance(dialog, ListPopup)
                seen.append(dialog.rect)
                return "cancel"

        manager = Recording()
        manager.handle_resize(60, 20)
        manager._terminal = cast(Terminal, object())  # pylint: disable=protected-access
        manager.pick([f"item {n}" for n in range(items)], 0, below)
        return seen[0]

    def test_below_the_field(self) -> None:
        """Under the field, as wide as it, its rows plus a frame."""
        self.assertEqual(self.placed(Rect(4, 10, 1, 20)), Rect(5, 10, 5, 20))

    def test_above_near_the_bottom(self) -> None:
        """With no room below, above the field instead."""
        self.assertEqual(self.placed(Rect(16, 10, 1, 20)), Rect(11, 10, 5, 20))

    def test_long_lists_and_the_right_edge(self) -> None:
        """At most pick_rows rows show; it stays on the screen sideways."""
        rect = self.placed(Rect(2, 50, 1, 20), items=30)
        self.assertEqual(
            (rect.height, rect.right), (PresentationManager.pick_rows + 2, 60)
        )


if __name__ == "__main__":
    unittest.main()
