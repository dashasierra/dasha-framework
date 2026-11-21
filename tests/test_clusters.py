"""Tests for check boxes and radio buttons."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.dialog import Dialog
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.widgets import Button, CheckBoxes, Cluster, RadioButtons
from dasha.window import Window


def keys(widget: Cluster, *names: str) -> list[bool]:
    """Offer keys to a group.

    :param widget: The group.
    :param names: The keys.
    """
    shortcuts = Shortcuts()
    return [widget.handle_key(name, shortcuts) for name in names]


def click(widget: Cluster, row: int) -> bool:
    """A left press on a row.

    :param widget: The group.
    :param row: Interior row.
    """
    return widget.handle_mouse(MouseEvent("press", "left", row, 3), row, 3)


def paint(widget: Cluster, focused: bool = True) -> Canvas:
    """Paint a group on a canvas of its size.

    :param widget: The group.
    :param focused: Whether it has the focus.
    """
    canvas = Canvas(widget.rect.right, widget.rect.bottom)
    widget.paint(canvas, canvas.bounds, focused)
    return canvas


class CheckBoxTests(unittest.TestCase):
    """Any number of options at once."""

    def setUp(self) -> None:
        self.changes: list[object] = []
        self.boxes = CheckBoxes(
            ["&Bold", "&Italic", "&Underline"],
            0,
            0,
            checked=[1],
            on_change=lambda group: self.changes.append(group.value),
        )

    def test_initial_state(self) -> None:
        """checked= sets which start checked; value lists their indexes."""
        self.assertEqual(self.boxes.value, (1,))
        self.assertEqual(self.boxes.checked, [False, True, False])
        self.assertEqual(self.boxes.checked_labels, ["Italic"])

    def test_space_toggles_the_current_one(self) -> None:
        """Space toggles the current option."""
        keys(self.boxes, " ", "down", "down", " ", "up", " ")
        self.assertEqual(self.boxes.value, (0, 2))
        self.assertEqual(self.changes, [(0, 1), (0, 1, 2), (0, 2)])

    def test_moving_stops_at_the_ends(self) -> None:
        """Moving stops at the ends."""
        self.assertEqual(keys(self.boxes, "up"), [True])
        self.assertEqual(self.boxes.current, 0)
        keys(self.boxes, "down", "down", "down")
        self.assertEqual(self.boxes.current, 2)
        self.assertEqual(self.changes, [])  # moving never toggles

    def test_other_keys_pass_on(self) -> None:
        """Enter, Tab and letters are left for the window."""
        self.assertEqual(keys(self.boxes, "enter", "tab", "b"), [False] * 3)

    def test_click_toggles(self) -> None:
        """A click on an option makes it current and toggles it."""
        click(self.boxes, 2)
        self.assertEqual((self.boxes.current, self.boxes.value), (2, (1, 2)))
        click(self.boxes, 1)
        self.assertEqual(self.boxes.value, (2,))

    def test_mnemonics(self) -> None:
        """Each option's letter is a mnemonic that toggles it."""
        self.assertEqual(self.boxes.mnemonics(), {"b", "i", "u"})
        self.boxes.activate_mnemonic("u")
        self.assertEqual((self.boxes.current, self.boxes.value), (2, (1, 2)))

    def test_paint(self) -> None:
        """Painting the options."""
        canvas = paint(self.boxes)
        self.assertEqual(
            [canvas.text(row) for row in range(3)],
            [" [ ] Bold      ", " [X] Italic    ", " [ ] Underline "],
        )
        self.assertEqual(
            canvas.cell(0, 5)[1].foreground, self.boxes.mnemonic_style.foreground
        )
        self.assertEqual(canvas.cell(0, 0)[1], self.boxes.selected_style)
        self.assertEqual(canvas.cell(1, 0)[1], self.boxes.style)
        self.assertIsNone(canvas.cursor)  # the highlight is enough
        unfocused = paint(self.boxes, focused=False)
        self.assertEqual(unfocused.cell(0, 0)[1], self.boxes.style)
        self.assertIsNone(unfocused.cursor)

    def test_width(self) -> None:
        """At least wide enough for the labels; wider if asked."""
        self.assertEqual(self.boxes.rect.width, 15)
        self.assertEqual(CheckBoxes(["A"], 0, 0, width=20).rect.width, 20)
        self.assertEqual(self.boxes.rect.height, 3)
        with self.assertRaises(ValueError):
            CheckBoxes([], 0, 0)


class RadioButtonTests(unittest.TestCase):
    """Exactly one option at a time."""

    def setUp(self) -> None:
        self.changes: list[object] = []
        self.radio = RadioButtons(
            ["&Small", "&Medium", "&Large"],
            0,
            0,
            selected=1,
            on_change=lambda group: self.changes.append(group.value),
        )

    def test_initial_state(self) -> None:
        """selected= picks the one selected, and the current one."""
        self.assertEqual((self.radio.value, self.radio.current), (1, 1))
        self.assertEqual(self.radio.selected_label, "Medium")
        with self.assertRaises(ValueError):
            RadioButtons(["A"], 0, 0, selected=3)

    def test_moving_selects(self) -> None:
        """Up and Down select as they go."""
        keys(self.radio, "down")
        self.assertEqual(self.radio.value, 2)
        keys(self.radio, "down")  # already the last: no change
        keys(self.radio, "up", "up")
        self.assertEqual(self.radio.value, 0)
        self.assertEqual(self.changes, [2, 1, 0])

    def test_only_one_at_a_time(self) -> None:
        """Selecting one deselects the rest, by click, Space or letter."""
        click(self.radio, 2)
        self.assertEqual(self.radio.value, 2)
        self.radio.activate_mnemonic("s")
        self.assertEqual(self.radio.value, 0)
        keys(self.radio, " ")  # already selected: nothing changes
        self.assertEqual(self.changes, [2, 0])
        marked = [self.radio.is_marked(index) for index in range(3)]
        self.assertEqual(marked, [True, False, False])

    def test_paint(self) -> None:
        """( ) and (•), code page 437 glyph 7."""
        canvas = paint(self.radio, focused=False)
        self.assertEqual(
            [canvas.text(row) for row in range(3)],
            [" ( ) Small  ", " (\N{BULLET}) Medium ", " ( ) Large  "],
        )


class InWindowTests(unittest.TestCase):
    """Groups among other widgets."""

    def test_tab_stops_once_per_group(self) -> None:
        """Tab stops once per group."""
        window = Window("W", Rect(0, 0, 10, 30))
        radio = window.add(RadioButtons(["&A", "&B"], 0, 0))
        boxes = window.add(CheckBoxes(["&C", "&D"], 3, 0))
        button = window.add(Button("&OK", 6, 0))
        shortcuts = Shortcuts()
        self.assertIs(window.focused, radio)
        window.handle_key("tab", shortcuts)
        self.assertIs(window.focused, boxes)
        window.handle_key("tab", shortcuts)
        self.assertIs(window.focused, button)

    def test_dialog_letters_and_values(self) -> None:
        """Dialog letters and values."""
        dialog = Dialog("Q", 30, 12)
        dialog.add(RadioButtons(["&Yes", "&No"], 0, 1, name="answer"))
        boxes = dialog.add(CheckBoxes(["&Red", "&Green"], 3, 1, name="colours"))
        dialog.add(Button("&OK", 6, 1, result="ok", default=True))
        shortcuts = Shortcuts()
        for key in ("n", "g", " ", "up", " ", "enter"):
            dialog.handle_key(key, shortcuts)
        self.assertIs(dialog.focused, boxes)
        self.assertEqual(dialog.values, {"answer": 1, "colours": (0,)})
        self.assertEqual(dialog.result, "ok")

    def test_click_through_the_window(self) -> None:
        """A click on an option focuses the group and presses the option."""
        window = Window("W", Rect(0, 0, 10, 30))
        window.add(Button("&OK", 6, 0))
        boxes = window.add(CheckBoxes(["&C", "&D"], 2, 1))
        window.handle_mouse(MouseEvent("press", "left", 4, 3))  # interior row 3: D
        self.assertIs(window.focused, boxes)
        self.assertEqual(boxes.value, (1,))


class DisabledTests(unittest.TestCase):
    """Options that cannot be chosen."""

    def setUp(self) -> None:
        self.boxes = CheckBoxes(["&Apple", "&Banana", "&Cherry"], 0, 0, disabled=[0])

    def test_starts_on_an_enabled_option(self) -> None:
        """The current option skips past a disabled first one."""
        self.assertEqual(self.boxes.current, 1)
        self.assertFalse(self.boxes.is_enabled(0))

    def test_cannot_be_pressed(self) -> None:
        """Keys, clicks and letters all leave a disabled option alone."""
        keys(self.boxes, "up", " ")  # Up has nowhere to go: Banana toggles
        self.assertEqual(self.boxes.current, 1)
        click(self.boxes, 0)
        self.assertNotIn("a", self.boxes.mnemonics())
        self.assertEqual(self.boxes.mnemonics(), {"b", "c"})
        self.assertEqual(self.boxes.value, (1,))
        self.boxes.press(0)  # code still can
        self.assertEqual(self.boxes.value, (0, 1))

    def test_moving_skips_disabled(self) -> None:
        """Up and Down jump over disabled options."""
        boxes = CheckBoxes(["A", "B", "C", "D"], 0, 0, disabled=[1, 2])
        keys(boxes, "down")
        self.assertEqual(boxes.current, 3)
        keys(boxes, "up")
        self.assertEqual(boxes.current, 0)

    def test_drawn_greyed_out(self) -> None:
        """A disabled option is in disabled_style, letter included."""
        canvas = paint(self.boxes)
        for column in range(self.boxes.rect.width):
            self.assertEqual(canvas.cell(0, column)[1], self.boxes.disabled_style)
        self.assertEqual(canvas.cell(1, 0)[1], self.boxes.selected_style)

    def test_disable_and_enable_later(self) -> None:
        """Disabling and enabling later."""
        self.boxes.disable(1)
        self.assertEqual(self.boxes.current, 2)
        self.boxes.enable(0, 1)
        self.assertEqual(self.boxes.disabled, set())
        self.assertIn("a", self.boxes.mnemonics())
        with self.assertRaises(IndexError):
            self.boxes.disable(7)

    def test_all_disabled_cannot_take_the_focus(self) -> None:
        """An all-disabled group cannot take the focus."""
        window = Window("W", Rect(0, 0, 10, 30))
        first = window.add(Button("&One", 0, 0))
        dead = window.add(CheckBoxes(["&X", "&Y"], 2, 0, disabled=[0, 1]))
        last = window.add(Button("&Two", 5, 0))
        self.assertFalse(dead.can_focus())
        shortcuts = Shortcuts()
        window.handle_key("tab", shortcuts)
        self.assertIs(window.focused, last)
        window.handle_key("tab", shortcuts)
        self.assertIs(window.focused, first)
        self.assertIsNone(paint(dead).cursor)

    def test_radio_selection_can_be_disabled(self) -> None:
        """A disabled option may stay selected, but cannot be chosen again."""
        radio = RadioButtons(["&X", "&Y", "&Z"], 0, 0, selected=0, disabled=[0])
        self.assertEqual((radio.value, radio.current), (0, 1))
        keys(radio, "down")
        self.assertEqual(radio.value, 2)
        keys(radio, "up", "up")
        self.assertEqual(radio.value, 1)  # stops before X
        radio.activate_mnemonic("x")
        self.assertEqual(radio.value, 1)


class ColumnTests(unittest.TestCase):
    """Options laid out in several columns."""

    def setUp(self) -> None:
        # Two columns, filled top to bottom: A B C, then D E.
        self.boxes = CheckBoxes(["&A", "&B", "&C", "&D", "&E"], 0, 0, columns=2)

    def test_layout(self) -> None:
        """Column layout."""
        self.assertEqual((self.boxes.rows, self.boxes.rect.height), (3, 3))
        self.assertEqual(self.boxes.rect.width, 14)
        canvas = paint(self.boxes, focused=False)
        self.assertEqual(
            [canvas.text(row) for row in range(3)],
            [" [ ] A  [ ] D ", " [ ] B  [ ] E ", " [ ] C        "],
        )
        self.assertEqual(canvas.cell(2, 10)[1], self.boxes.style)

    def test_columns_fit_their_own_labels(self) -> None:
        """Columns fit their own labels."""
        boxes = CheckBoxes(["Longer", "x", "y"], 0, 0, columns=2)
        self.assertEqual(boxes.rect.width, 6 + 6 + 6 + 1)
        self.assertEqual(
            CheckBoxes(["a", "b"], 0, 0, columns=2, width=30).rect.width, 30
        )
        self.assertEqual(CheckBoxes(["a"], 0, 0, columns=4).columns, 1)
        with self.assertRaises(ValueError):
            CheckBoxes(["a"], 0, 0, columns=0)

    def test_left_and_right(self) -> None:
        """Left and Right move between columns."""
        keys(self.boxes, "right")
        self.assertEqual(self.boxes.current, 3)
        keys(self.boxes, "down", "down")
        self.assertEqual(self.boxes.current, 4)  # E: the end
        self.assertEqual(keys(self.boxes, "right"), [True])  # no more columns
        keys(self.boxes, "left")
        self.assertEqual(self.boxes.current, 1)
        keys(self.boxes, "down", "right")
        self.assertEqual(self.boxes.current, 4)  # from C to E

    def test_up_and_down_run_through_the_columns(self) -> None:
        """Up and Down run through the columns."""
        keys(self.boxes, "down", "down", "down")
        self.assertEqual(self.boxes.current, 3)

    def test_one_column_leaves_left_and_right(self) -> None:
        """With one column, Left and Right are left for the window."""
        boxes = CheckBoxes(["A", "B"], 0, 0)
        self.assertEqual(keys(boxes, "left", "right"), [False, False])

    def test_click_in_a_column(self) -> None:
        """Clicking in a column."""
        self.assertEqual(self.boxes.index_at(1, 8), 4)
        self.assertIsNone(self.boxes.index_at(2, 8))
        self.boxes.handle_mouse(MouseEvent("press", "left", 0, 9), 0, 9)
        self.assertEqual(self.boxes.value, (3,))

    def test_sideways_finds_the_nearest_enabled(self) -> None:
        """Sideways moves find the nearest enabled option."""
        boxes = CheckBoxes(list("ABCDEF"), 0, 0, columns=2, disabled=[5])
        boxes.current = 2  # C, beside the disabled F
        keys(boxes, "right")
        self.assertEqual(boxes.current, 4)  # E, just above F
        skipping = CheckBoxes(list("ABCDEF"), 0, 0, columns=3, disabled=[2, 3])
        keys(skipping, "right")
        self.assertEqual(skipping.current, 4)  # past the C-D column to E
        keys(skipping, "left")
        self.assertEqual(skipping.current, 0)
        radio = RadioButtons(list("ABCD"), 0, 0, columns=2)
        keys(radio, "right")
        self.assertEqual(radio.value, 2)


if __name__ == "__main__":
    unittest.main()
