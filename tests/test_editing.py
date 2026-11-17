"""Tests for undo, moving by words, tabs in text areas, Ctrl+Tab, and the
key hints on the status bar."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent, decode
from dasha.manager import PresentationManager
from dasha.shortcuts import Shortcuts, ShortcutsError
from dasha.statusbar import StatusBar
from dasha.style import BLUE, BRIGHT_YELLOW
from dasha.widgets import Button, TextArea, TextBox
from dasha.widgets.editing import UndoHistory, word_left, word_right
from dasha.window import Window


def keys(widget: TextArea | TextBox, *names: str) -> None:
    """Offer keys with the default shortcuts."""
    shortcuts = Shortcuts()
    for name in names:
        widget.handle_key(name, shortcuts)


class WordTests(unittest.TestCase):
    """Where Ctrl+Left and Ctrl+Right go."""

    def test_word_left_and_right(self) -> None:
        """Left goes to the start of a word; right to the start of the next."""
        text = "one, two  three"
        self.assertEqual(word_left(text, 15), 10)
        self.assertEqual(word_left(text, 10), 5)
        self.assertEqual(word_left(text, 2), 0)
        self.assertEqual(word_right(text, 0), 5)
        self.assertEqual(word_right(text, 5), 10)
        self.assertEqual(word_right(text, 12), 15)

    def test_text_box_words(self) -> None:
        """Ctrl+Left/Right move by words; with Shift they select."""
        box = TextBox(0, 0, 30, text="hello big world")
        keys(box, "ctrl+left")
        self.assertEqual(box.cursor, 10)
        keys(box, "shift+ctrl+left")
        self.assertEqual(box.selected_text, "big ")
        keys(box, "home", "ctrl+right")
        self.assertEqual(box.cursor, 6)

    def test_text_area_words_cross_lines(self) -> None:
        """At a line's start Ctrl+Left goes to the end of the line above;
        at its end Ctrl+Right goes to the next line."""
        area = TextArea(0, 0, text="first line\nsecond")
        area.cursor = (1, 0)
        keys(area, "ctrl+left")
        self.assertEqual(area.cursor, (0, 10))
        keys(area, "ctrl+left")
        self.assertEqual(area.cursor, (0, 6))
        keys(area, "ctrl+right", "ctrl+right")
        self.assertEqual(area.cursor, (1, 0))
        keys(area, "shift+ctrl+right")
        self.assertEqual(area.selected_text, "second")


class UndoHistoryTests(unittest.TestCase):
    """The shared history."""

    def test_limit(self) -> None:
        """The oldest steps go beyond the limit; None means no limit."""
        history: UndoHistory[int] = UndoHistory()
        for step in range(30):
            history.push(step, 20)
        self.assertEqual(len(history), 20)
        self.assertEqual(history.pop(), 29)
        for step in range(3000):
            history.push(step, None)
        self.assertEqual(len(history), 3019)


class TextBoxUndoTests(unittest.TestCase):
    """Ctrl+Z in a text box."""

    def test_typing_is_undone_a_word_at_a_time(self) -> None:
        """A run of typing goes in one undo; a space starts the next."""
        box = TextBox(0, 0, 30)
        keys(box, *"hello world")
        keys(box, "ctrl+z")
        self.assertEqual(box.text, "hello")
        keys(box, "ctrl+z")
        self.assertEqual(box.text, "")

    def test_each_edit_and_the_selection_come_back(self) -> None:
        """Deleting, clearing and typing over a selection are undone in turn,
        putting the cursor and selection back."""
        box = TextBox(0, 0, 30, text="abcdef")
        box.select(1, 4)
        keys(box, "x", "backspace", "ctrl+y")
        keys(box, "ctrl+z")
        self.assertEqual(box.text, "aef")
        keys(box, "ctrl+z", "ctrl+z")
        self.assertEqual((box.text, box.selection), ("abcdef", (1, 4)))
        self.assertFalse(box.undo())  # nothing more

    def test_redo(self) -> None:
        """Redo goes forward again through what was undone; something new
        typed forgets it."""
        box = TextBox(0, 0, 30)
        keys(box, *"hi", " ", *"there")  # two steps: "hi" and " there"
        keys(box, "ctrl+z", "ctrl+z")
        self.assertEqual(box.text, "")
        keys(box, "alt+z")
        self.assertEqual(box.text, "hi")
        keys(box, "alt+z")
        self.assertEqual((box.text, box.cursor), ("hi there", 8))
        keys(box, "ctrl+z", "!")
        self.assertFalse(box.redo())
        self.assertEqual(box.text, "hi!")

    def test_limit_can_be_large(self) -> None:
        """The limit is 20 by default and can be raised (or set on a box)."""
        box = TextBox(0, 0, 30)
        box.undo_limit = 2000
        for _ in range(100):
            keys(box, "a", "backspace")
        undone = 0
        while box.undo():
            undone += 1
        self.assertEqual(undone, 200)
        self.assertEqual(TextBox.undo_limit, 20)


class TextAreaUndoTests(unittest.TestCase):
    """Ctrl+Z in a text area."""

    def test_typing_lines_and_pasting(self) -> None:
        """Typing, new lines and multi-line pastes undo one step at a time."""
        area = TextArea(0, 0)
        keys(area, *"one", "enter", *"two")
        area.handle_paste("x\ny")
        keys(area, "ctrl+z")
        self.assertEqual(area.text, "one\ntwo")
        keys(area, "ctrl+z")
        self.assertEqual(area.text, "one\n")
        keys(area, "ctrl+z", "ctrl+z")
        self.assertEqual((area.text, area.cursor), ("", (0, 0)))

    def test_delete_line_and_cut_come_back(self) -> None:
        """Ctrl+Y and Ctrl+X are undone, the selection with them."""
        area = TextArea(0, 0, text="a\nb\nc")
        area.cursor = (1, 0)
        keys(area, "ctrl+y")
        self.assertEqual(area.text, "a\nc")
        area.select((0, 0), (1, 1))
        keys(area, "ctrl+x", "ctrl+z")
        self.assertEqual(area.selection, ((0, 0), (1, 1)))
        keys(area, "ctrl+z")
        self.assertEqual(area.text, "a\nb\nc")

    def test_limit(self) -> None:
        """Only undo_limit steps are kept."""
        area = TextArea(0, 0)
        for _ in range(25):
            keys(area, "enter")
        count = 0
        while area.undo():
            count += 1
        self.assertEqual(count, 20)
        self.assertEqual(len(area.lines), 6)

    def test_redo(self) -> None:
        """Alt+Z redoes what Ctrl+Z undid, cursor and all, step by step;
        Ctrl+Shift+Z does too where the terminal sends it."""
        area = TextArea(0, 0)
        keys(area, *"one", " ", *"two", "enter")
        keys(area, "ctrl+z", "ctrl+z")
        self.assertEqual(area.text, "one")
        keys(area, "alt+z")
        self.assertEqual((area.text, area.cursor), ("one two", (0, 7)))
        keys(area, "shift+ctrl+z")
        self.assertEqual(area.text, "one two\n")
        self.assertFalse(area.redo())  # nothing more to redo
        keys(area, "ctrl+z", "ctrl+z", "alt+z", "alt+z", "ctrl+z")
        self.assertEqual(area.text, "one two")

    def test_redo_of_a_selection_replaced(self) -> None:
        """Undoing typing over a selection, then redoing it, works both ways
        with the selection coming back on undo."""
        area = TextArea(0, 0, text="a\nb\nc")
        area.select((0, 0), (2, 1))
        keys(area, "x", "ctrl+z")
        self.assertEqual((area.text, area.selection), ("a\nb\nc", ((0, 0), (2, 1))))
        keys(area, "alt+z")
        self.assertEqual(area.text, "x")
        keys(area, "ctrl+z")
        self.assertEqual(area.text, "a\nb\nc")

    def test_a_new_change_forgets_redo(self) -> None:
        """Once something new is typed, what was undone cannot be redone."""
        area = TextArea(0, 0)
        keys(area, *"ab", "ctrl+z", "c")
        self.assertFalse(area.redo())
        self.assertEqual(area.text, "c")

    def test_setting_text_forgets(self) -> None:
        """New text from code cannot be undone back past."""
        area = TextArea(0, 0, text="a")
        keys(area, "b")
        area.text = "new"
        self.assertFalse(area.undo())


class TabTests(unittest.TestCase):
    """Real tabs in a text area."""

    def setUp(self) -> None:
        self.window = Window("E", Rect(0, 0, 8, 30))
        self.area = self.window.add(TextArea(0, 0, text="a\tb\n12345678"))

    def test_tab_key_types_a_tab(self) -> None:
        """Tab puts a tab in the text."""
        area = TextArea(0, 0)
        keys(area, "x", "tab", "y")
        self.assertEqual(area.text, "x\ty")

    def test_drawn_to_the_next_stop(self) -> None:
        """A tab is drawn as spaces to the next multiple of tab_size, and
        the cursor after it is drawn there."""
        self.area.cursor = (0, 2)
        canvas = Canvas(30, 8)
        self.window.paint(canvas, active=True)
        self.assertEqual(canvas.text(1)[1:7], "a   b ")
        self.assertEqual(canvas.cursor, (1, 1 + 4))

    def test_up_and_down_by_screen_column(self) -> None:
        """Going up and down keeps to the column on screen, past tabs."""
        self.area.cursor = (1, 4)
        keys(self.area, "up")
        self.assertEqual(self.area.cursor, (0, 2))  # past the tab, at "b"
        self.area.cursor = (1, 2)
        keys(self.area, "up")
        self.assertEqual(self.area.cursor, (0, 1))  # inside the tab: at it

    def test_click_on_a_tab(self) -> None:
        """A click on the cells of a tab puts the cursor before it."""
        event = MouseEvent("press", "left", 0, 3)
        self.area.handle_mouse(event, 0, 3)
        self.assertEqual(self.area.cursor, (0, 1))


class FocusKeyTests(unittest.TestCase):
    """Ctrl+Tab and Ctrl+Shift+Tab."""

    def test_decoded(self) -> None:
        """Both ways terminals can send them decode to the same names."""
        self.assertEqual(
            decode("\x1b[9;5u\x1b[9;6u\x1b[27;5;9~\x1b[27;6;9~\x1b[1;5Z"),
            [
                "ctrl+tab",
                "shift+ctrl+tab",
                "ctrl+tab",
                "shift+ctrl+tab",
                "shift+ctrl+tab",
            ],
        )

    def test_into_and_out_of_a_text_area(self) -> None:
        """Ctrl+Tab moves the focus on from a text area (and from anything
        else), Ctrl+Shift+Tab back, while Tab types a tab."""
        window = Window("W", Rect(0, 0, 12, 30))
        area = window.add(TextArea(0, 0, 20, 5))
        ok = window.add(Button("&OK", 6, 1))
        shortcuts = Shortcuts()
        window.handle_key("tab", shortcuts)
        self.assertIs(window.focused, area)
        window.handle_key("ctrl+tab", shortcuts)
        self.assertIs(window.focused, ok)
        window.handle_key("shift+ctrl+tab", shortcuts)
        self.assertIs(window.focused, area)
        self.assertEqual(area.text, "\t")

    def test_need_a_way_out(self) -> None:
        """Shortcuts without either focus key out of a text area are refused."""
        with self.assertRaises(ShortcutsError):
            Shortcuts({"area_next_widget": [], "area_previous_widget": []})


class LooksTests(unittest.TestCase):
    """The text area's colours, and the key hints on the status bar."""

    def test_text_area_colours(self) -> None:
        """Bright yellow on blue."""
        self.assertEqual(TextArea.style.foreground, BRIGHT_YELLOW)
        self.assertEqual(TextArea.style.background, BLUE)

    def test_status_bar_hints(self) -> None:
        """Hints go on the right, key names in key_style; those that do not
        fit are left off, and the text gives way to the rest."""
        status_bar = StatusBar()
        hints = [("Ctrl+Z", "Undo"), ("Ctrl+A", "All")]
        canvas = Canvas(50, 2)
        status_bar.paint(canvas, "Some status text here", hints)
        self.assertEqual(
            canvas.text(1).rstrip(), " Some status text here    Ctrl+Z Undo  Ctrl+A All"
        )
        self.assertEqual(canvas.cell(1, 26)[1], status_bar.key_style)
        self.assertEqual(canvas.cell(1, 33)[1], status_bar.style)
        narrow = Canvas(16, 1)
        status_bar.paint(narrow, "Status", hints)
        self.assertEqual(narrow.text(0), " S  Ctrl+Z Undo ")

    def test_hints_follow_the_focus_and_the_bindings(self) -> None:
        """The manager shows the focused widget's keys, as remapped."""
        window = Window("E", Rect(1, 0, 10, 40))
        window.add(TextArea(0, 0))
        window.add(TextBox(5, 0, 10))
        manager = PresentationManager(
            windows=[window], shortcuts=Shortcuts({"area_next_widget": ["alt+n"]})
        )
        manager.handle_resize(80, 24)
        # After the key that opens the menu bar, which comes first.
        self.assertEqual(manager.key_hints()[0], ("F10", "Menu"))
        self.assertIn(("Alt+N", "Next"), manager.key_hints())
        canvas = Canvas(80, 24)
        manager.compose(canvas)
        self.assertIn("Alt+N Next", canvas.text(23))
        manager.handle_event("f10")  # with a menu open, the menu's help
        self.assertEqual(manager.key_hints(), [])


if __name__ == "__main__":
    unittest.main()
