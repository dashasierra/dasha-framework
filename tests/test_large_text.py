"""A text area holding a big file: about 5 MB, 100,000 lines.

Typing, moving and painting must cost about what they cost in a short
text, not time in proportion to the whole of it. The time bounds are
generous, for slow machines; work proportional to the text on every key
breaks them by far.
"""

import random
import time
import unittest

from dasha.canvas import Canvas, Rect
from dasha.clipboard import Clipboard
from dasha.shortcuts import Shortcuts
from dasha.widgets import TextArea
from dasha.window import Window

LINES = 100_000
LINE = "The quick brown fox jumps over the lazy dog, now and again.\t1234"

BOUND = 0.25
"""Seconds each step may take at most: generous, as a step without work in
proportion to the text takes well under a millisecond."""


def big_editor() -> tuple[Window, TextArea]:
    """A window of 80 by 25 holding 100,000 lines of text."""
    window = Window("Big", Rect(0, 0, 25, 80), resizable=True)
    area = window.add(TextArea(0, 0, text="\n".join([LINE] * LINES)))
    area.clipboard = Clipboard()
    return window, area


class LargeTextTests(unittest.TestCase):
    """Editing a big text takes no longer than editing a short one."""

    def setUp(self) -> None:
        self.window, self.area = big_editor()
        self.shortcuts = Shortcuts()
        self.canvas = Canvas(80, 25)

    def timed(self, label: str, action: object) -> None:
        """Run ``action`` (a callable) and check it was quick enough."""
        assert callable(action)
        start = time.perf_counter()
        action()
        took = time.perf_counter() - start
        self.assertLess(took, BOUND, f"{label} took {took:.3f}s")

    def key(self, name: str, times: int = 1) -> None:
        """Press a key in the text area (``times`` times)."""
        for _ in range(times):
            self.area.handle_key(name, self.shortcuts)

    def paint(self) -> None:
        """Paint the window."""
        self.window.paint(self.canvas, True)

    def test_loading_is_quick(self) -> None:
        """Loading the text takes about as long as splitting it into lines."""
        text = "\n".join([LINE] * LINES)
        self.assertGreater(len(text), 5_000_000)
        start = time.perf_counter()
        TextArea(0, 0, text=text)
        self.assertLess(time.perf_counter() - start, 8 * BOUND)

    def test_typing_moving_and_painting(self) -> None:
        """Typing a character, moving to the end, and painting, each a
        moment's work, here and at the end of the text."""
        self.timed("painting", self.paint)
        # A hundred together, so even a few milliseconds each of work in
        # proportion to the text adds up to more than the bound.
        self.timed("typing", lambda: self.key("x", times=100))
        self.timed("a new line", lambda: self.key("enter"))
        self.timed("Backspace", lambda: self.key("backspace"))
        self.timed("moving to the end", lambda: self.key("ctrl+end"))
        self.timed("painting at the end", self.paint)
        self.timed("typing at the end", lambda: self.key("z"))
        self.timed("moving up a page", lambda: self.key("pageup"))
        self.timed("undoing", lambda: self.key("ctrl+z"))
        self.timed("moving to the start", lambda: self.key("ctrl+home"))
        self.timed("painting at the start", self.paint)
        self.assertEqual(self.area.lines[0], "x" * 100 + LINE)
        self.assertEqual(self.area.cursor, (0, 0))
        self.assertEqual(len(self.area.lines), LINES)

    def test_width_follows_the_widest_line(self) -> None:
        """The text area is as wide as its widest line, as lines grow and
        shrink: the widest is kept count of, not measured afresh."""
        interior = self.window.interior.width
        self.assertEqual(self.area.rect.width, interior)  # the lines fit
        self.key("end")
        for _ in range(40):
            self.key("x")
        widest = len(self.area.lines[0].expandtabs(self.area.tab_size))
        self.assertGreater(widest, interior)
        self.assertEqual(self.area.rect.width, widest + 1)
        self.key("ctrl+y")  # the widest line goes
        self.assertEqual(self.area.rect.width, interior)
        self.area.select((0, 0), (LINES - 1, len(LINE)))
        self.key("delete")
        self.assertEqual(self.area.lines, [""])
        self.assertEqual(self.area.rect.width, interior)

    def test_random_edits_keep_the_width_right(self) -> None:
        """After random edits, undos and redos, the width is what measuring
        every line gives."""
        rng = random.Random(1)
        window = Window("Small", Rect(0, 0, 12, 30), resizable=True)
        area = window.add(TextArea(0, 0, text="one\ntwo\tthree\n\nfour"))
        area.clipboard = Clipboard()
        keys = ("x", "\t", "enter", "backspace", "delete", "ctrl+y", "ctrl+z",
                "alt+z", "up", "down", "end", "home", "shift+down", "shift+end",
                "ctrl+x", "ctrl+v", "ctrl+a")  # fmt: skip
        for _ in range(2000):
            area.handle_key(rng.choice(keys), self.shortcuts)
            widest = max(len(line.expandtabs(area.tab_size)) for line in area.lines)
            expected = max(widest + 1, window.interior.width)
            self.assertEqual(area.rect.width, expected, area.lines)


if __name__ == "__main__":
    unittest.main()
