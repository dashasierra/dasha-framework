"""Password boxes: a text box that does not show what is typed in it."""

from dasha.canvas import Canvas, Rect
from dasha.shortcuts import Shortcuts
from dasha.widgets.textbox import TextBox

MASK = "\N{BULLET}"
"""``•`` (code page 437 glyph 7), which is shown for each character."""


class PasswordBox(TextBox):
    """A ``PasswordBox`` is a ``TextBox`` for a password or a key. It shows
    ``•`` (code page 437 glyph 7) for each character, and does not copy or cut
    its contents to the clipboard: Ctrl+C and Ctrl+X do nothing. Pasting into it
    works, as typing does. Words in it are not told apart, so Ctrl+Left and
    Ctrl+Right go to either end, rather than revealing where its spaces are. Set
    ``revealed`` to show the text itself (from a "Show password" switch, for
    example). Everything else works as in a text box: ``value`` is the text
    itself, and ``max_length`` and ``pattern`` limit it.
    """

    copies_out = False  # so its context menu has no Cut or Copy

    revealed: bool = False
    """Whether the text is shown as it is, rather than as ``•``."""

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        if self.revealed:
            super().paint(canvas, origin, focused)
            return
        text = self._text
        self._text = MASK * len(text)  # drawn as bullets, the same length
        try:
            super().paint(canvas, origin, focused)
        finally:
            self._text = text

    def copy(self) -> bool:
        """Never: the password stays in the box."""
        return False

    def cut(self) -> bool:
        """Never: the password stays in the box."""
        return False

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """As for a text box, except that moving a word at a time goes to
        either end."""
        end = len(self.text)
        ends = {
            "text_word_left": (0, False),
            "text_word_right": (end, False),
            "text_select_word_left": (0, True),
            "text_select_word_right": (end, True),
        }
        for action, (position, extend) in ends.items():
            if shortcuts.matches(action, key):
                self._move(position, extend)
                return True
        return super().handle_key(key, shortcuts)
