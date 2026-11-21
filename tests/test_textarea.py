"""Tests for text areas: many lines of text to edit."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.clipboard import Clipboard, ClipboardItem
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.shortcuts import Shortcuts
from dasha.widgets import TextArea, TextBox
from dasha.window import Window


def keys(area: TextArea, *names: str, shortcuts: Shortcuts | None = None) -> list[bool]:
    """Offer keys to a text area.

    :param area: The text area.
    :param names: The keys.
    :param shortcuts: Key bindings, or ``None`` for the defaults.
    """
    shortcuts = shortcuts if shortcuts is not None else Shortcuts()
    return [area.handle_key(name, shortcuts) for name in names]


def press(area: TextArea, row: int, column: int, **options: object) -> None:
    """A left press in the window's interior.

    :param area: The text area.
    :param row: Content row.
    :param column: Content column.
    :param options: Mouse event options.
    """
    event = MouseEvent("press", "left", row, column, **options)  # type: ignore[arg-type]
    area.handle_mouse(event, row, column)


def editor(text: str = "", width: int = 20, height: int = 6) -> tuple[Window, TextArea]:
    """A window holding just a text area.

    :param text: The text.
    :param width: Interior width.
    :param height: Interior height.
    """
    window = Window("E", Rect(1, 0, height + 2, width + 2), resizable=True)
    area = window.add(TextArea(0, 0, text=text))
    area.clipboard = Clipboard()
    return window, area


class EditingTests(unittest.TestCase):
    """Typing, new lines and deleting."""

    def test_text_is_cleaned(self) -> None:
        """Text is cleaned."""
        area = TextArea(0, 0, text="a\r\nb\tc\rd\x07e\x1b[2J\udcff")
        self.assertEqual(area.lines, ["a", "b\tc", "d\x07e\x1b[2J"])
        self.assertEqual(area.value, "a\nb\tc\nd\x07e\x1b[2J")

    def test_typing_and_enter(self) -> None:
        """Characters go in at the cursor; Enter splits the line."""
        area = TextArea(0, 0, text="hel")
        keys(area, "end", "l", "o", "home", "right", "right", "enter")
        self.assertEqual(area.lines, ["he", "llo"])
        self.assertEqual(area.cursor, (1, 0))

    def test_backspace_and_delete_join_lines(self) -> None:
        """Backspace and Delete join lines."""
        area = TextArea(0, 0, text="one\ntwo\nthree")
        area.cursor = (1, 0)
        keys(area, "backspace")
        self.assertEqual((area.lines, area.cursor), (["onetwo", "three"], (0, 3)))
        keys(area, "end", "delete")
        self.assertEqual(area.lines, ["onetwothree"])
        keys(area, "home", "backspace", "end", "delete")  # nothing to join
        self.assertEqual(area.lines, ["onetwothree"])

    def test_delete_line(self) -> None:
        """Ctrl+Y deletes the line the cursor is on, the last one too."""
        area = TextArea(0, 0, text="one\ntwo\nthree")
        area.cursor = (1, 1)
        keys(area, "ctrl+y")
        self.assertEqual(area.lines, ["one", "three"])
        keys(area, "down", "ctrl+y")
        self.assertEqual(area.lines, ["one"])
        keys(area, "ctrl+y")
        self.assertEqual(area.lines, [""])

    def test_on_change(self) -> None:
        """on_change hears about edits, not moves."""
        changes: list[str] = []
        area = TextArea(0, 0, text="ab", on_change=lambda a: changes.append(a.text))
        keys(area, "end", "c", "left", "backspace")
        self.assertEqual(changes, ["abc", "ac"])


class MovingTests(unittest.TestCase):
    """The cursor keys."""

    def setUp(self) -> None:
        self.area = TextArea(0, 0, text="a long line\nshort\nanother long line")

    def test_left_and_right_wrap(self) -> None:
        """Left and Right wrap."""
        self.area.cursor = (1, 0)
        keys(self.area, "left")
        self.assertEqual(self.area.cursor, (0, 11))
        keys(self.area, "right")
        self.assertEqual(self.area.cursor, (1, 0))

    def test_up_and_down_remember_the_column(self) -> None:
        """Through a short line, the cursor comes back to its column."""
        self.area.cursor = (0, 9)
        keys(self.area, "down")
        self.assertEqual(self.area.cursor, (1, 5))
        keys(self.area, "down")
        self.assertEqual(self.area.cursor, (2, 9))
        keys(self.area, "down", "up", "up", "up", "up")
        self.assertEqual(self.area.cursor, (0, 9))

    def test_ends(self) -> None:
        """Home and End for the line; Ctrl+Home and Ctrl+End for the text."""
        self.area.cursor = (1, 2)
        keys(self.area, "end")
        self.assertEqual(self.area.cursor, (1, 5))
        keys(self.area, "ctrl+end")
        self.assertEqual(self.area.cursor, (2, 17))
        keys(self.area, "ctrl+home")
        self.assertEqual(self.area.cursor, (0, 0))

    def test_page_keys(self) -> None:
        """PgDn and PgUp move by what the window shows, less one."""
        window, area = editor("\n".join(str(n) for n in range(30)), height=6)
        del window
        keys(area, "pagedown")
        self.assertEqual(area.cursor, (5, 0))
        keys(area, "pagedown", "pageup")
        self.assertEqual(area.cursor, (5, 0))


class SelectionTests(unittest.TestCase):
    """Selecting, and what typing and pasting do to a selection."""

    def setUp(self) -> None:
        self.window, self.area = editor("first line\nsecond line\nthird")

    def test_shift_keys_select_across_lines(self) -> None:
        """Shift with the arrows selects, over line breaks too."""
        self.area.cursor = (0, 6)
        keys(self.area, "shift+down", "shift+right")
        self.assertEqual(self.area.selection, ((0, 6), (1, 7)))
        self.assertEqual(self.area.selected_text, "line\nsecond ")

    def test_typing_replaces_the_selection(self) -> None:
        """Typing replaces the selection."""
        self.area.select((0, 6), (1, 6))
        keys(self.area, "a")
        self.assertEqual(self.area.lines, ["first a line", "third"])
        self.assertIsNone(self.area.selection)

    def test_ctrl_a_selects_everything(self) -> None:
        """Ctrl+A selects all the text, and typing replaces it."""
        keys(self.area, "ctrl+a")
        self.assertEqual(self.area.selected_text, "first line\nsecond line\nthird")
        keys(self.area, "x")
        self.assertEqual(self.area.lines, ["x"])

    def test_cut_copy_paste(self) -> None:
        """Cut, copy and paste."""
        self.area.select((0, 0), (1, 6))
        keys(self.area, "ctrl+c")
        self.assertEqual(self.area.clipboard.text, "first line\nsecond")
        keys(self.area, "ctrl+x")
        self.assertEqual(self.area.lines, [" line", "third"])
        self.area.select((1, 0), (1, 5))
        keys(self.area, "ctrl+v")
        self.assertEqual(self.area.lines, [" line", "first line", "second"])
        self.area.clipboard.copy(ClipboardItem("text/uri-list", ["file:///x"]))
        keys(self.area, "ctrl+v")
        self.assertEqual(self.area.lines, [" line", "first line", "second"])

    def test_terminal_paste(self) -> None:
        """Text pasted through the terminal replaces the selection too."""
        self.area.select_line(2)
        self.area.handle_paste("one\ntwo")
        self.assertEqual(self.area.lines, ["first line", "second line", "one", "two"])

    def test_double_click_selects_the_line(self) -> None:
        """A double-click selects the whole line it lands on."""
        press(self.area, 1, 3)
        press(self.area, 1, 3, clicks=2)
        self.assertEqual(self.area.selected_text, "second line")
        keys(self.area, "a")
        self.assertEqual(self.area.lines, ["first line", "a", "third"])

    def test_click_drag_and_shift_click(self) -> None:
        """Click, drag and Shift+click."""
        press(self.area, 2, 15)
        self.assertEqual(self.area.cursor, (2, 5))
        press(self.area, 0, 2)
        self.area.handle_mouse(MouseEvent("drag", "left", 1, 4), 1, 4)
        self.assertEqual(self.area.selected_text, "rst line\nseco")
        press(self.area, 0, 0)
        press(self.area, 0, 5, shift=True)
        self.assertEqual(self.area.selected_text, "first")

    def test_selection_is_drawn(self) -> None:
        """The selection is drawn."""
        self.area.select((0, 6), (1, 2))
        canvas = Canvas(30, 10)
        self.window.paint(canvas, active=True)
        top, left = 2, 1  # the window's interior on screen
        styles = [canvas.cell(top, left + column)[1] for column in (5, 6, 10)]
        selected = self.area.selected_style
        self.assertEqual(styles, [self.area.style, selected, selected])
        self.assertEqual(canvas.cell(top + 1, left + 1)[1], selected)
        self.assertEqual(canvas.cell(top + 1, left + 2)[1], self.area.style)
        self.assertEqual(canvas.cursor, (top + 1, left + 2))


class WindowTests(unittest.TestCase):
    """Filling the window, and its scroll bars."""

    def test_fills_the_window(self) -> None:
        """Fills the window."""
        window, area = editor("hi", width=20, height=6)
        self.assertEqual((area.rect.width, area.rect.height), (20, 6))
        self.assertEqual(window.scroll_bars, (None, None))
        window.resize(40, 12)
        self.assertEqual((area.rect.width, area.rect.height), (38, 10))

    def test_bigger_text_brings_the_window_scroll_bars(self) -> None:
        """Bigger text brings scroll bars."""
        window, area = editor("x" * 30 + "\n" * 10, width=20, height=6)
        vertical, horizontal = window.scroll_bars
        self.assertIsNotNone(vertical)
        self.assertIsNotNone(horizontal)
        keys(area, "ctrl+a", "backspace")
        self.assertEqual(window.scroll_bars, (None, None))

    def test_window_scrolls_to_the_cursor(self) -> None:
        """The window scrolls to the cursor."""
        window, area = editor("\n".join(f"line {n} {'y' * 30}" for n in range(20)))
        keys(area, "ctrl+end")
        self.assertEqual(window.scroll_row, 14)  # 20 lines, 6 showing
        self.assertGreater(window.scroll_column, 0)
        keys(area, "home")
        self.assertEqual(window.scroll_column, 0)
        keys(area, "ctrl+home")
        self.assertEqual((window.scroll_row, window.scroll_column), (0, 0))

    def test_maximise(self) -> None:
        """Maximised, the text area fills the bigger window."""
        window, area = editor("hi")
        manager = PresentationManager(windows=[window])
        manager.handle_resize(80, 24)
        manager.maximise(window)
        self.assertEqual((area.rect.width, area.rect.height), (78, 20))

    def test_keys_left_for_the_window(self) -> None:
        """Keys left for the window."""
        area = TextArea(0, 0)
        passed = keys(area, "ctrl+tab", "shift+ctrl+tab", "shift+tab", "escape")
        self.assertEqual(passed, [False] * 4)
        self.assertEqual(keys(area, "tab", "enter"), [True, True])
        self.assertEqual(area.lines, ["\t", ""])

    def test_remapped_keys(self) -> None:
        """The text area's keys are shortcuts like any other."""
        area = TextArea(0, 0, text="a\nb")
        shortcuts = Shortcuts({"area_down": ["ctrl+n"], "area_newline": ["ctrl+j"]})
        keys(area, "ctrl+n", "ctrl+j", shortcuts=shortcuts)
        self.assertEqual(area.lines, ["a", "", "b"])


class WheelThenClickTests(unittest.TestCase):
    """Clicking after scrolling with the wheel."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.handle_resize(80, 24)
        self.window = Window("Long", Rect(2, 2, 15, 60), closable=True)
        text = "\n".join(f"line {number}" for number in range(100))
        self.area = self.window.add(TextArea(0, 0, text=text))
        self.manager.add(self.window)
        for _ in range(5):
            self.manager.handle_event(MouseEvent("scroll", "down", 8, 20))
        self.scrolled = self.window.scroll_row

    def mouse(self, action: str, row: int, column: int) -> None:
        """A left button event.

        :param action: Mouse action.
        :param row: Screen row.
        :param column: Screen column.
        """
        self.manager.handle_event(MouseEvent(action, "left", row, column))

    def test_the_click_lands_where_it_was_made(self) -> None:
        """The cursor goes to the line under the pointer; nothing scrolls."""
        self.assertGreater(self.scrolled, 0)
        self.mouse("press", 8, 6)
        self.mouse("release", 8, 6)
        line = self.scrolled + 8 - self.window.interior.row
        self.assertEqual(self.area.cursor, (line, 3))
        self.assertEqual(self.window.scroll_row, self.scrolled)
        self.assertIsNone(self.area.selection)

    def test_a_shaky_click_selects_nothing(self) -> None:
        """A shaky click selects nothing."""
        self.mouse("press", 8, 6)
        self.mouse("drag", 8, 6)
        self.mouse("release", 8, 6)
        self.assertIsNone(self.area.selection)
        self.assertEqual(self.window.scroll_row, self.scrolled)

    def test_tab_into_it_keeps_the_view(self) -> None:
        """Tabbing in keeps the view."""
        other = Window("Two", Rect(2, 2, 15, 60))
        area = other.add(TextArea(0, 0, text="\n".join("x" * 100)))
        box = other.add(TextBox(0, 0, 5))
        other.focus(box)
        other.scroll_to(20, 0)
        other.focus(area)
        self.assertEqual(other.scroll_row, 20)


if __name__ == "__main__":
    unittest.main()
