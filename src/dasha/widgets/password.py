"""Password boxes."""

from dasha.canvas import Canvas, Rect
from dasha.shortcuts import Shortcuts
from dasha.widgets.textbox import TextBox

MASK = "\N{BULLET}"
"""``•`` (code page 437 glyph 7), which is shown for each character."""


class PasswordBox(TextBox):
    """A text box that hides its text."""

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
        """Handle a key as a text box does.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
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
