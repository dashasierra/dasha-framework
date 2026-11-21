"""Tests for the clipboard, and cut, copy and paste in text boxes."""

import unittest
from typing import cast

from dasha.canvas import Rect
from dasha.clipboard import CLIPBOARD, TEXT, Clipboard, ClipboardItem
from dasha.dialog import Dialog
from dasha.events import PasteEvent
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuItem
from dasha.shortcuts import Shortcuts
from dasha.terminal import Terminal
from dasha.widgets import Button, TextBox
from dasha.window import Window
from tests.test_manager import FakeTerminal

FILE = "text/uri-list"
"""A type a text box does not take."""


def press(box: TextBox, *keys: str) -> list[bool]:
    """Offer keys to a box.

    :param box: The text box.
    :param keys: The keys.
    """
    shortcuts = Shortcuts()
    return [box.handle_key(key, shortcuts) for key in keys]


class ClipboardTests(unittest.TestCase):
    """The clipboard itself."""

    def test_starts_empty(self) -> None:
        """A new clipboard holds nothing."""
        clipboard = Clipboard()
        self.assertIsNone(clipboard.item)
        self.assertIsNone(clipboard.text)
        self.assertIsNone(clipboard.get())

    def test_text(self) -> None:
        """Copied text comes back as text, typed text/plain, with metadata."""
        clipboard = Clipboard()
        clipboard.copy_text("hello", source="test")
        self.assertEqual(clipboard.text, "hello")
        item = clipboard.get(TEXT)
        assert item is not None
        self.assertEqual((item.type, item.data), (TEXT, "hello"))
        self.assertEqual(item.metadata["source"], "test")

    def test_other_types(self) -> None:
        """Anything else is held with its type; asking for text gets None."""
        clipboard = Clipboard()
        clipboard.copy(ClipboardItem(FILE, ["file:///tmp/notes.txt"]))
        self.assertIsNone(clipboard.text)
        self.assertIsNone(clipboard.get(TEXT))
        self.assertIsNotNone(clipboard.get(FILE))
        self.assertIsNotNone(clipboard.get(TEXT, FILE))

    def test_text_must_be_a_string(self) -> None:
        """text/plain data that is not a str is refused."""
        with self.assertRaises(TypeError):
            ClipboardItem(TEXT, b"bytes")

    def test_listeners_and_clear(self) -> None:
        """Listeners hear about every change; clear empties it."""
        clipboard = Clipboard()
        heard: list[str | None] = []
        clipboard.listeners.append(lambda c: heard.append(c.text))
        clipboard.copy_text("a")
        clipboard.clear()
        self.assertEqual(heard, ["a", None])
        self.assertIsNone(clipboard.item)


class TextBoxClipboardTests(unittest.TestCase):
    """Ctrl+X, Ctrl+C and Ctrl+V in a text box."""

    def setUp(self) -> None:
        self.clipboard = Clipboard()
        self.box = self.make(text="hello world")

    def make(self, **options: object) -> TextBox:
        """A text box with the test's clipboard.

        :param options: Text box options.
        """
        box = TextBox(0, 0, 20, **options)  # type: ignore[arg-type]
        box.clipboard = self.clipboard
        return box

    def test_copy(self) -> None:
        """Ctrl+C copies the selection and leaves the text alone."""
        self.box.select(0, 5)
        self.assertEqual(press(self.box, "ctrl+c"), [True])
        self.assertEqual(self.clipboard.text, "hello")
        self.assertEqual(self.box.text, "hello world")
        self.assertEqual(self.box.selection, (0, 5))

    def test_cut(self) -> None:
        """Ctrl+X copies the selection and deletes it."""
        self.box.select(5, 11)
        press(self.box, "ctrl+x")
        self.assertEqual(self.clipboard.text, " world")
        self.assertEqual((self.box.text, self.box.cursor), ("hello", 5))

    def test_nothing_selected_copies_nothing(self) -> None:
        """Without a selection, Ctrl+C and Ctrl+X leave the clipboard be."""
        self.clipboard.copy_text("kept")
        press(self.box, "ctrl+c", "ctrl+x")
        self.assertEqual(self.clipboard.text, "kept")
        self.assertEqual(self.box.text, "hello world")

    def test_paste_replaces_the_selection(self) -> None:
        """Ctrl+V puts the clipboard's text in place of the selection."""
        self.clipboard.copy_text("there")
        self.box.select(6, 11)
        press(self.box, "ctrl+v")
        self.assertEqual(self.box.text, "hello there")
        self.assertEqual((self.box.cursor, self.box.selection), (11, None))

    def test_paste_at_the_cursor(self) -> None:
        """With nothing selected, the text goes in at the cursor."""
        self.clipboard.copy_text(",")
        self.box.cursor = 5
        press(self.box, "ctrl+v")
        self.assertEqual((self.box.text, self.box.cursor), ("hello, world", 6))

    def test_paste_of_another_type_does_nothing(self) -> None:
        """A file (or anything but text) on the clipboard is not pasted."""
        self.clipboard.copy(ClipboardItem(FILE, ["file:///tmp/notes.txt"]))
        self.box.select_all()
        self.assertEqual(press(self.box, "ctrl+v"), [True])
        self.assertEqual(self.box.text, "hello world")
        self.assertEqual(self.box.selection, (0, 11))
        self.assertFalse(self.box.paste())

    def test_paste_the_box_would_refuse_does_nothing(self) -> None:
        """Text the pattern refuses is not pasted, not even partly."""
        numbers = self.make(text="12", pattern=r"[0-9]*")
        for text in ("hello", "3a4"):
            self.clipboard.copy_text(text)
            self.assertFalse(numbers.paste())
            self.assertEqual(numbers.text, "12")
        self.clipboard.copy_text("345")
        self.assertTrue(numbers.paste())
        self.assertEqual(numbers.text, "12345")

    def test_paste_too_long_or_multiline_does_nothing(self) -> None:
        """Too long for max_length, or more than one line: nothing pasted."""
        short = self.make(text="ab", max_length=4)
        self.clipboard.copy_text("cde")
        self.assertFalse(short.paste())
        short.select_all()
        self.assertTrue(short.paste())  # replacing the selection, it fits
        self.assertEqual(short.text, "cde")
        self.clipboard.copy_text("x\ny")
        self.assertFalse(self.make().paste())

    def test_cut_the_box_would_refuse_does_nothing(self) -> None:
        """A refused cut does nothing."""
        box = self.make(text="10", pattern=r"[1-9][0-9]*")
        box.select(0, 1)  # cutting the 1 would leave "0"
        self.clipboard.copy_text("kept")
        self.assertFalse(box.cut())
        self.assertEqual((box.text, self.clipboard.text), ("10", "kept"))

    def test_remapped_keys(self) -> None:
        """Cut, copy and paste are shortcuts like any other."""
        shortcuts = Shortcuts({"text_copy": ["alt+c"], "text_paste": []})
        self.box.select(0, 5)
        self.box.handle_key("alt+c", shortcuts)
        self.assertEqual(self.clipboard.text, "hello")
        self.assertFalse(self.box.handle_key("ctrl+v", shortcuts))

    def test_boxes_share_the_global_clipboard(self) -> None:
        """By default every box uses CLIPBOARD, so text moves between them."""
        before = CLIPBOARD.item
        try:
            first = TextBox(0, 0, 20, text="shared")
            second = TextBox(1, 0, 20)
            first.select_all()
            press(first, "ctrl+c")
            press(second, "ctrl+v")
            self.assertEqual(second.text, "shared")
        finally:
            if before is None:
                CLIPBOARD.clear()
            else:
                CLIPBOARD.copy(before)


def bracketed(text: str) -> str:
    """Text as a bracketed paste.

    :param text: The pasted text.
    """
    return "\x1b[200~" + text + "\x1b[201~"


class TerminalPasteTests(unittest.TestCase):
    """Text pasted through the terminal itself (bracketed paste)."""

    def test_all_or_nothing(self) -> None:
        """Terminal pastes are all or nothing."""
        box = TextBox(0, 0, 20, text="12", pattern=r"[0-9]*")
        for text in ("hello", "3a4", "3\r4", "3\x114"):
            self.assertFalse(box.handle_paste(text))
            self.assertEqual(box.text, "12")
        self.assertTrue(box.handle_paste("345"))
        self.assertEqual((box.text, box.cursor), ("12345", 5))

    def test_replaces_the_selection(self) -> None:
        """A terminal paste goes in place of the selection, like Ctrl+V."""
        box = TextBox(0, 0, 20, text="hello world")
        box.select(6, 11)
        self.assertTrue(box.handle_paste("there"))
        self.assertEqual((box.text, box.selection), ("hello there", None))

    def test_too_long_does_nothing(self) -> None:
        """max_length applies to the whole result."""
        box = TextBox(0, 0, 20, text="ab", max_length=4)
        self.assertFalse(box.handle_paste("cde"))
        self.assertEqual(box.text, "ab")

    def test_one_trailing_line_break_is_dropped(self) -> None:
        """One trailing line break is dropped."""
        for ending in ("\r", "\n", "\r\n"):
            box = TextBox(0, 0, 20, pattern=r"[0-9]*")
            self.assertTrue(box.handle_paste("42" + ending))
            self.assertEqual(box.text, "42")
        box = TextBox(0, 0, 20)
        self.assertFalse(box.handle_paste("4\r2"))
        self.assertFalse(box.handle_paste("42\r\r"))
        self.assertEqual(box.text, "")

    def test_same_path_as_ctrl_v(self) -> None:
        """Dasha Framework's paste and the terminal's both go through insert."""
        box = TextBox(0, 0, 20)
        box.clipboard = Clipboard()
        box.clipboard.copy_text("abc")
        self.assertTrue(box.paste())
        self.assertTrue(box.handle_paste("def\n"))
        self.assertTrue(box.insert("g"))
        self.assertFalse(box.insert(""))
        self.assertEqual(box.text, "abcdefg")

    def test_on_change(self) -> None:
        """``on_change`` runs once per accepted paste."""
        changes: list[str] = []
        box = TextBox(
            0, 0, 20, pattern=r"[0-9]*", on_change=lambda b: changes.append(b.text)
        )
        box.handle_paste("1a")
        box.handle_paste("12")
        self.assertEqual(changes, ["12"])

    def test_other_widgets_ignore_pastes(self) -> None:
        """A window passes a paste to its focused widget only."""
        window = Window("W", Rect(1, 0, 6, 30))
        button = window.add(Button("&Go", 3, 1))
        box = window.add(TextBox(1, 1, 10))
        window.focus(button)
        self.assertFalse(window.handle_paste("x"))
        self.assertEqual(box.text, "")
        window.focus(box)
        self.assertTrue(window.handle_paste("x"))
        self.assertEqual(box.text, "x")

    def test_run_loop(self) -> None:
        """Pastes through the run loop."""
        window = Window("Numbers", Rect(1, 0, 6, 30))
        box = window.add(TextBox(1, 1, 10, pattern=r"[0-9]*"))
        manager = PresentationManager(windows=[window])
        refused, accepted = bracketed("3a4"), bracketed("56")
        terminal = FakeTerminal(
            [
                refused[:4],  # split in the start marker
                refused[4:],
                bracketed("1\x112"),
                accepted[:-3],  # split in the end marker
                accepted[-3:],
                "\x11",
                "\r",
            ],
            sizes=[(40, 10)],
        )
        manager.run(cast(Terminal, terminal))
        self.assertEqual(box.text, "56")
        self.assertEqual(terminal.inputs, [])
        self.assertFalse(manager.is_running)

    def test_ignored_while_a_menu_is_open(self) -> None:
        """With a menu open, a paste does not reach the window beneath."""
        window = Window("W", Rect(1, 0, 6, 30))
        window.menus = [Menu("&File", [MenuItem("&New")])]
        box = window.add(TextBox(1, 1, 10))
        manager = PresentationManager(windows=[window])
        manager.handle_event("f10")
        self.assertTrue(manager.menu_bar.is_open)
        manager.handle_event(PasteEvent("x"))
        self.assertEqual(box.text, "")

    def test_modal_dialog(self) -> None:
        """While a dialog waits for its answer, pastes go to its box."""
        manager = PresentationManager()
        dialog = Dialog("Name", 30, 8)
        box = dialog.add(TextBox(1, 2, 20))
        manager.handle_modal_event(dialog, PasteEvent("Bob\r\n"))
        self.assertEqual(box.text, "Bob")


if __name__ == "__main__":
    unittest.main()
