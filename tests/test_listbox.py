"""Tests for list boxes."""

import unittest
from unittest import mock

from dasha.canvas import Canvas, Rect
from dasha.dialog import Dialog
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.scrollbar import DOWN, LEFT, RIGHT, UP
from dasha.shortcuts import Shortcuts
from dasha.widgets import Button, ListBox
from dasha.window import Window

NAMES = [f"file{number:02}.txt" for number in range(20)]


def keys(box: ListBox, *names: str, shortcuts: Shortcuts | None = None) -> list[bool]:
    """Offer keys to a list box.

    :param box: The list box.
    :param names: The keys.
    :param shortcuts: Key bindings, or ``None`` for the defaults.
    """
    shortcuts = shortcuts if shortcuts is not None else Shortcuts()
    return [box.handle_key(name, shortcuts) for name in names]


def mouse(
    box: ListBox, action: str, row: int, column: int, button: str = "left"
) -> bool:
    """A mouse event in the window's interior.

    :param box: The list box.
    :param action: Mouse action.
    :param row: Interior row.
    :param column: Interior column.
    :param button: Mouse button.
    """
    return box.handle_mouse(MouseEvent(action, button, row, column), row, column)


def paint(box: ListBox, focused: bool = True) -> Canvas:
    """Paint a box on a canvas of its size.

    :param box: The list box.
    :param focused: Whether it has the focus.
    """
    canvas = Canvas(box.rect.right, box.rect.bottom)
    box.paint(canvas, canvas.bounds, focused)
    return canvas


class SingleColumnTests(unittest.TestCase):
    """One column, single selection, a vertical scroll bar."""

    def setUp(self) -> None:
        self.changes: list[object] = []
        self.box = ListBox(
            NAMES, 0, 0, 14, 5, on_change=lambda box: self.changes.append(box.value)
        )

    def test_moving_selects(self) -> None:
        """With single selection, the highlighted item is the selected one."""
        self.assertEqual(self.box.value, 0)
        keys(self.box, "down", "down")
        self.assertEqual(self.box.value, 2)
        self.assertEqual(self.box.selected_items, ["file02.txt"])
        self.assertEqual(self.changes, [1, 2])

    def test_moves_stay_in_bounds(self) -> None:
        """Up from the top, Down from the bottom, Home, End, and pages."""
        keys(self.box, "up")
        self.assertEqual(self.box.cursor, 0)
        keys(self.box, "pagedown")
        self.assertEqual(self.box.cursor, 5)
        keys(self.box, "end", "down")
        self.assertEqual(self.box.cursor, 19)
        keys(self.box, "pageup")
        self.assertEqual(self.box.cursor, 14)
        keys(self.box, "home")
        self.assertEqual(self.box.cursor, 0)

    def test_scrolls_to_keep_the_highlight_in_view(self) -> None:
        """Moving past the bottom scrolls one row at a time."""
        keys(self.box, *["down"] * 6)
        self.assertEqual(self.box.first_visible, 2)  # rows 2-6 show
        canvas = paint(self.box)
        self.assertEqual(canvas.text(4)[:10], "file06.txt")
        self.assertEqual(canvas.cell(4, 0)[1], self.box.focused_style)
        self.assertIsNone(canvas.cursor)  # the highlight is enough

    def test_scroll_bar_only_when_needed(self) -> None:
        """A scroll bar only when needed."""
        canvas = paint(self.box)
        self.assertEqual(canvas.cell(0, 13)[0], UP)
        self.assertEqual(canvas.cell(4, 13)[0], DOWN)
        short = ListBox(["one", "two"], 0, 0, 14, 5)
        canvas = paint(short)
        self.assertEqual(canvas.text(0), "one".ljust(14))
        self.assertNotIn(UP, "".join(canvas.text(row) for row in range(5)))

    def test_bar_scrolls_without_moving_the_highlight(self) -> None:
        """Clicking the bar's down arrow and track scrolls the view only."""
        mouse(self.box, "press", 4, 13)  # ▼
        mouse(self.box, "release", 4, 13)
        self.assertEqual((self.box.first_visible, self.box.cursor), (1, 0))
        mouse(self.box, "press", 3, 13)  # the track below the thumb
        self.assertEqual(self.box.first_visible, 5)
        self.assertEqual(self.changes, [])

    def test_dragging_the_thumb(self) -> None:
        """The thumb follows the pointer down the track."""
        mouse(self.box, "press", 1, 13)  # the thumb, at the top
        mouse(self.box, "drag", 3, 13)  # the bottom of the track
        mouse(self.box, "release", 3, 13)
        self.assertEqual(self.box.first_visible, 15)  # the most it scrolls

    def test_click_selects(self) -> None:
        """A click on an item selects it."""
        mouse(self.box, "press", 3, 2)
        self.assertEqual(self.box.value, 3)

    def test_long_items_are_cut_off(self) -> None:
        """An item longer than the list box is cut at its edge."""
        box = ListBox(["a very long file name.txt"], 0, 0, 10, 2)
        self.assertEqual(paint(box).text(0), "a very lon")

    def test_space_is_taken_and_tab_enter_pass(self) -> None:
        """Space is taken; Tab, Escape and Enter pass."""
        self.assertEqual(keys(self.box, " "), [True])
        self.assertEqual(keys(self.box, "tab", "escape", "enter"), [False] * 3)
        self.assertEqual(keys(self.box, "left", "right"), [False, False])

    def typing(self, box: ListBox, timed: list[tuple[float, str]]) -> list[int]:
        """Type at given times; return the highlights.

        :param box: The list box.
        :param timed: (time, character) pairs.
        """
        cursors = []
        for when, character in timed:
            with mock.patch("dasha.widgets.listbox.time.monotonic", return_value=when):
                keys(box, character)
            cursors.append(box.cursor)
        return cursors

    def test_typing_finds_the_first_item_starting_with_it(self) -> None:
        """Typing finds the first match."""
        box = ListBox(["tea", "toast", "turtle.exe", "turnip"], 0, 0, 12, 4)
        typed = [(10.0, "t"), (10.2, "u"), (10.4, "r"), (10.6, "n")]
        self.assertEqual(self.typing(box, typed), [0, 2, 2, 3])

    def test_typing_resets_after_a_pause(self) -> None:
        """Typing resets after a pause."""
        box = ListBox(["apple", "banana", "cherry"], 0, 0, 12, 3)
        self.assertEqual(self.typing(box, [(5.0, "c"), (5.3, "x")]), [2, 2])
        self.assertEqual(self.typing(box, [(6.4, "b")]), [1])  # a new search
        self.assertEqual(self.typing(box, [(7.0, "a")]), [1])  # "ba": banana

    def test_nothing_found_stays_put(self) -> None:
        """A prefix nothing starts with leaves the highlight where it is."""
        box = ListBox(["apple", "banana"], 0, 0, 12, 2)
        self.assertEqual(self.typing(box, [(1.0, "b"), (1.1, "z")]), [1, 1])

    def test_same_letter_steps_through(self) -> None:
        """The same letter steps through."""
        box = ListBox(["apple", "banana", "avocado", "apricot"], 0, 0, 12, 4)
        typed = [(1.0, "a"), (1.1, "a"), (1.2, "a"), (1.3, "a")]
        self.assertEqual(self.typing(box, typed), [0, 2, 3, 0])

    def test_case(self) -> None:
        """Case does not matter by default; with case_sensitive it does."""
        names = ["readme.txt", "README.md"]
        relaxed = ListBox(names, 0, 0, 12, 2)
        self.assertEqual(self.typing(relaxed, [(1.0, "R"), (1.1, "E")]), [0, 0])
        strict = ListBox(names, 0, 0, 12, 2, case_sensitive=True)
        self.assertEqual(self.typing(strict, [(1.0, "R"), (1.1, "E")]), [1, 1])

    def test_typing_does_not_select(self) -> None:
        """With multiple selection, finding an item only highlights it."""
        box = ListBox(["tea", "turtle.exe"], 0, 0, 12, 2, multiple=True)
        self.typing(box, [(1.0, "t"), (1.1, "u")])
        self.assertEqual((box.cursor, box.value), (1, ()))

    def test_unfocused_selection_still_shows(self) -> None:
        """Without the focus, the selected item shows in selected_style."""
        keys(self.box, "down")
        canvas = paint(self.box, focused=False)
        self.assertEqual(canvas.cell(1, 0)[1], self.box.selected_style)
        self.assertIsNone(canvas.cursor)


class MultipleSelectionTests(unittest.TestCase):
    """Space selects and deselects; moving only moves."""

    def setUp(self) -> None:
        self.changes: list[object] = []
        self.box = ListBox(
            NAMES,
            0,
            0,
            14,
            5,
            multiple=True,
            selected=[4],
            on_change=lambda box: self.changes.append(box.value),
        )

    def test_space_toggles(self) -> None:
        """Space toggles."""
        self.assertEqual(self.box.value, (4,))
        keys(self.box, " ", "down", "down", " ", "up", "up", " ")
        self.assertEqual(self.box.value, (2, 4))
        self.assertEqual(self.box.selected_items, ["file02.txt", "file04.txt"])
        self.assertEqual(self.changes, [(0, 4), (0, 2, 4), (2, 4)])

    def test_click_toggles(self) -> None:
        """A click on an item highlights it and selects or deselects it."""
        mouse(self.box, "press", 4, 1)
        self.assertEqual((self.box.cursor, self.box.value), (4, ()))
        mouse(self.box, "press", 4, 1)
        self.assertEqual(self.box.value, (4,))

    def test_drawing(self) -> None:
        """Drawing selections."""
        canvas = paint(self.box)
        self.assertEqual(canvas.cell(4, 0)[1], self.box.selected_style)
        self.assertEqual(canvas.cell(0, 0)[1], self.box.focused_style)
        keys(self.box, *["down"] * 4)
        style = paint(self.box).cell(4, 0)[1]
        self.assertEqual(style.background, self.box.focused_style.background)
        self.assertEqual(style.foreground, self.box.selected_style.foreground)

    def test_ctrl_a_selects_all_or_none(self) -> None:
        """Ctrl+A selects all or none."""
        self.assertEqual(keys(self.box, "ctrl+a"), [True])
        self.assertEqual(self.box.value, tuple(range(20)))
        keys(self.box, "ctrl+a")
        self.assertEqual(self.box.value, ())
        keys(self.box, "ctrl+a", " ", "ctrl+a")  # one deselected: all again
        self.assertEqual(self.box.value, tuple(range(20)))
        self.assertEqual(len(self.changes), 5)

    def test_ctrl_a_remapped_and_single_selection(self) -> None:
        """Ctrl+A remapped and with single selection."""
        shortcuts = Shortcuts({"list_select_all": ["alt+a"]})
        keys(self.box, "alt+a", shortcuts=shortcuts)
        self.assertEqual(len(self.box.selected_items), 20)
        single = ListBox(NAMES, 0, 0, 14, 5)
        self.assertEqual(keys(single, "ctrl+a"), [False])
        self.assertEqual(single.value, 0)

    def test_set_items_keeps_what_still_exists(self) -> None:
        """New items keep the highlight and selections that are in range."""
        keys(self.box, "end", " ")
        self.box.set_items(NAMES[:10])
        self.assertEqual((self.box.cursor, self.box.value), (9, (4,)))
        self.box.set_items([])
        self.assertEqual((self.box.value, self.box.selected_items), ((), []))


class ColumnTests(unittest.TestCase):
    """Several columns, filled top to bottom, scrolling sideways."""

    def setUp(self) -> None:
        # 20 items, 4 rows (the fifth row is the scroll bar): 5 columns of
        # items, 2 showing at a time.
        self.box = ListBox(NAMES, 0, 0, 25, 5, columns=2)

    def test_layout(self) -> None:
        """Column layout."""
        self.assertEqual(self.box.rows, 4)
        canvas = paint(self.box, focused=False)
        self.assertEqual(
            canvas.text(0), "file00.txt  \N{BOX DRAWINGS LIGHT VERTICAL}file04.txt  "
        )
        self.assertEqual(canvas.text(3)[:10], "file03.txt")
        self.assertEqual(canvas.cell(4, 0)[0], LEFT)
        self.assertEqual(canvas.cell(4, 24)[0], RIGHT)

    def test_no_bar_when_the_columns_fit(self) -> None:
        """No bar when the columns fit."""
        box = ListBox(NAMES[:8], 0, 0, 25, 4, columns=2)
        self.assertEqual(box.rows, 4)
        self.assertNotIn(LEFT, paint(box).text(3))

    def test_left_and_right_move_a_column(self) -> None:
        """Right moves a column on, scrolling sideways; Left comes back."""
        keys(self.box, "down", "right", "right")
        self.assertEqual(self.box.cursor, 9)
        self.assertEqual(self.box.first_visible, 1)  # columns 1-2 show
        keys(self.box, "right", "right", "right")
        self.assertEqual(self.box.cursor, 19)  # the last item
        self.assertEqual(self.box.first_visible, 3)
        keys(self.box, "left")
        self.assertEqual(self.box.cursor, 15)

    def test_pages_move_a_screenful(self) -> None:
        """A page is every item showing: rows times columns."""
        keys(self.box, "pagedown")
        self.assertEqual(self.box.cursor, 8)

    def test_click_in_the_second_column(self) -> None:
        """A click finds the item by its column."""
        mouse(self.box, "press", 2, 15)
        self.assertEqual(self.box.value, 6)
        self.assertIsNone(self.box.index_at(0, 12))  # on the divider

    def test_bar_scrolls_a_column(self) -> None:
        """The bar scrolls a column."""
        mouse(self.box, "press", 4, 24)
        self.assertEqual((self.box.first_visible, self.box.cursor), (1, 0))

    def test_too_small(self) -> None:
        """Columns need room, and a row as well as the bar."""
        with self.assertRaises(ValueError):
            ListBox(NAMES, 0, 0, 3, 5, columns=2)
        with self.assertRaises(ValueError):
            ListBox(NAMES, 0, 0, 20, 1, columns=2)
        with self.assertRaises(ValueError):
            ListBox(NAMES, 0, 0, 20, 5, columns=0)


class InWindowTests(unittest.TestCase):
    """List boxes in windows and dialogs."""

    def test_mouse_wheel(self) -> None:
        """The mouse wheel."""
        window = Window("W", Rect(1, 0, 8, 30), [""] * 20)
        box = window.add(ListBox(NAMES, 0, 0, 14, 5))
        manager = PresentationManager(windows=[window])
        manager.handle_resize(40, 20)
        manager.handle_event(MouseEvent("scroll", "down", 3, 3))
        self.assertEqual((box.first_visible, window.scroll_row), (3, 0))
        manager.handle_event(MouseEvent("scroll", "up", 3, 3))
        self.assertEqual(box.first_visible, 0)
        manager.handle_event(MouseEvent("scroll", "down", 3, 20))  # beside it
        self.assertEqual(window.scroll_row, 3)

    def test_dialog(self) -> None:
        """In a dialog."""
        dialog = Dialog("Open", 30, 14)
        box = dialog.add(ListBox(NAMES, 0, 1, 20, 6, multiple=True, name="files"))
        ok = dialog.add(Button("&OK", 8, 1, result="ok", default=True))
        shortcuts = Shortcuts()
        for key in (" ", "down", " ", "o"):  # o: type-ahead, not the OK button
            dialog.handle_key(key, shortcuts)
        self.assertIsNone(dialog.result)
        self.assertEqual(dialog.values["files"], (0, 1))
        dialog.handle_key("enter", shortcuts)  # from the list: the default
        self.assertEqual((dialog.result, dialog.focused), ("ok", box))
        dialog.handle_key("tab", shortcuts)
        self.assertIs(dialog.focused, ok)

    def test_remapped_keys(self) -> None:
        """The list's keys are shortcuts like any other."""
        box = ListBox(NAMES, 0, 0, 14, 5, multiple=True)
        shortcuts = Shortcuts({"list_down": ["j"], "list_toggle": ["x"]})
        keys(box, "j", "j", "x", shortcuts=shortcuts)
        self.assertEqual(box.value, (2,))


if __name__ == "__main__":
    unittest.main()
