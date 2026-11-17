"""Tests for password boxes."""

import unittest

from dasha.canvas import Canvas
from dasha.clipboard import Clipboard
from dasha.shortcuts import Shortcuts
from dasha.widgets import PasswordBox
from dasha.widgets.password import MASK


class PasswordBoxTests(unittest.TestCase):
    """A password box with "secret" typed in it."""

    def setUp(self) -> None:
        self.box = PasswordBox(0, 0, 12)
        self.box.clipboard = Clipboard()
        self.box.clipboard.copy_text("from before")
        for key in "secret":
            self.box.handle_key(key, Shortcuts())

    def drawn(self) -> str:
        """The box as drawn, focused."""
        canvas = Canvas(12, 1)
        self.box.paint(canvas, canvas.bounds, True)
        return canvas.text(0)

    def test_shows_bullets(self) -> None:
        """A • for each character; the value is the text itself."""
        self.assertEqual(self.drawn(), " " + MASK * 6 + "     ")
        self.assertEqual(self.box.value, "secret")
        self.assertEqual(self.box.text, "secret")  # put back after drawing

    def test_revealed(self) -> None:
        """Revealed, the text shows as it is."""
        self.box.revealed = True
        self.assertEqual(self.drawn(), " secret     ")

    def test_never_copied_out(self) -> None:
        """Copy and cut do nothing, by key or from code; the clipboard keeps
        what it had."""
        shortcuts = Shortcuts()
        self.box.handle_key("ctrl+a", shortcuts)
        self.box.handle_key("ctrl+c", shortcuts)
        self.box.handle_key("ctrl+x", shortcuts)
        self.assertFalse(self.box.copy() or self.box.cut())
        self.assertEqual(self.box.clipboard.text, "from before")
        self.assertEqual(self.box.text, "secret")

    def test_paste_works(self) -> None:
        """Pasting into it, as typing does."""
        self.box.handle_key("ctrl+v", Shortcuts())
        self.assertEqual(self.box.text, "secretfrom before")

    def test_words_are_not_told_apart(self) -> None:
        """Ctrl+Left and Ctrl+Right go to either end, spaces or not."""
        shortcuts = Shortcuts()
        for key in " two":
            self.box.handle_key(key, shortcuts)
        self.box.handle_key("ctrl+left", shortcuts)
        self.assertEqual(self.box.cursor, 0)
        self.box.handle_key("ctrl+right", shortcuts)
        self.assertEqual(self.box.cursor, len("secret two"))
        self.box.handle_key("shift+ctrl+left", shortcuts)
        self.assertEqual(self.box.selection, (0, len("secret two")))
        self.box.handle_key("shift+ctrl+right", shortcuts)
        self.assertEqual(self.box.cursor, len("secret two"))


if __name__ == "__main__":
    unittest.main()
