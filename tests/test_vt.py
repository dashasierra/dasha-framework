"""Tests for the VT emulator (``dasha.vt``): what a program's output
leaves on the screen."""

import unittest

from dasha.style import DEFAULT, Rgb, Style
from dasha.vt import Screen, char_width


def texts(screen: Screen) -> list[str]:
    """Each row's characters, trailing blanks dropped."""
    return ["".join(cell[0] for cell in row).rstrip() for row in screen.rows]


class TextTests(unittest.TestCase):
    """Writing text, line endings and wrapping."""

    def test_writes_and_moves_the_cursor(self) -> None:
        """Text goes where the cursor is; CR LF starts the next line."""
        screen = Screen(columns=10, lines=3)
        screen.feed("one\r\ntwo")
        self.assertEqual(texts(screen), ["one", "two", ""])
        self.assertEqual(screen.cursor, (1, 3))

    def test_wraps_at_the_last_column_only_when_more_comes(self) -> None:
        """A full line leaves the cursor on its last column until more text
        arrives (so a CR LF does not leave a blank line)."""
        screen = Screen(columns=5, lines=3)
        screen.feed("abcde")
        self.assertEqual(screen.cursor, (0, 4))
        screen.feed("\r\nf")
        self.assertEqual(texts(screen), ["abcde", "f", ""])
        screen.feed("\x1b[H" + "123456")
        self.assertEqual(texts(screen)[:2], ["12345", "6"])
        self.assertTrue(screen.rows[0].wrapped)

    def test_no_autowrap(self) -> None:
        """With autowrap off, text past the end overwrites the last column."""
        screen = Screen(columns=5, lines=2)
        screen.feed("\x1b[?7labcdefg")
        self.assertEqual(texts(screen), ["abcdg", ""])

    def test_scrolls_into_the_scrollback(self) -> None:
        """Lines off the top go into the scrollback, oldest first."""
        screen = Screen(columns=10, lines=2, scrollback=2)
        screen.feed("1\r\n2\r\n3\r\n4")
        self.assertEqual(texts(screen), ["3", "4"])
        self.assertEqual(
            ["".join(c[0] for c in line).rstrip() for line in screen.scrollback],
            ["1", "2"],
        )
        self.assertEqual(screen.scrolled_off, 2)
        shown = screen.shown_rows(back=1)
        self.assertEqual(["".join(c[0] for c in r).rstrip() for r in shown], ["2", "3"])

    def test_tabs_backspace_and_bell(self) -> None:
        """Tab goes to the next stop of eight; backspace moves back."""
        screen = Screen(columns=20, lines=1)
        screen.feed("a\tb\x08c\x07")
        self.assertEqual(texts(screen), ["a       c"])
        self.assertEqual(screen.bells, 1)

    def test_split_sequences_and_characters(self) -> None:
        """A sequence, or a UTF-8 character, split between two pieces of
        output is put back together."""
        screen = Screen(columns=10, lines=2)
        screen.feed("\x1b[")
        screen.feed("31mx")
        self.assertEqual(screen.rows[0][0], ("x", Style(foreground=1)))
        screen.feed_bytes("\N{POUND SIGN}".encode()[:1])
        screen.feed_bytes("\N{POUND SIGN}".encode()[1:])
        self.assertEqual(screen.rows[0][1][0], "\N{POUND SIGN}")

    def test_controls_are_never_text(self) -> None:
        """Unknown sequences and strings are read and dropped."""
        screen = Screen(columns=20, lines=1)
        screen.feed("a\x1bP1$r0m\x1b\\b\x1b[>4;2mc\x1b]52;c;aGk=\x07d\x1b[?2026$pe")
        self.assertEqual(texts(screen), ["abcde"])


class CursorTests(unittest.TestCase):
    """Moving and saving the cursor."""

    def test_movement(self) -> None:
        """CUP, CUU/CUD/CUF/CUB, CHA and VPA, kept on the screen."""
        screen = Screen(columns=10, lines=5)
        screen.feed("\x1b[3;4H")
        self.assertEqual(screen.cursor, (2, 3))
        screen.feed("\x1b[A\x1b[2C")
        self.assertEqual(screen.cursor, (1, 5))
        screen.feed("\x1b[99B\x1b[99D")
        self.assertEqual(screen.cursor, (4, 0))
        screen.feed("\x1b[7G\x1b[2d")
        self.assertEqual(screen.cursor, (1, 6))

    def test_save_and_restore(self) -> None:
        """ESC 7 and ESC 8 keep the place and the colours."""
        screen = Screen(columns=10, lines=5)
        screen.feed("\x1b[2;2H\x1b[32m\x1b7\x1b[H\x1b[0m\x1b8x")
        self.assertEqual(screen.rows[1][1], ("x", Style(foreground=2)))

    def test_reports(self) -> None:
        """Where the cursor is, the terminal's status and attributes."""
        screen = Screen(columns=10, lines=5)
        screen.feed("\x1b[3;7H\x1b[6n\x1b[5n\x1b[c\x1b[>c")
        self.assertEqual(
            screen.take_replies(),
            b"\x1b[3;7R\x1b[0n\x1b[?62;22c\x1b[>1;10;0c",
        )
        self.assertEqual(screen.take_replies(), b"")

    def test_cursor_visibility_and_modes(self) -> None:
        """DECTCEM, DECCKM and bracketed paste are noted."""
        screen = Screen()
        screen.feed("\x1b[?25l\x1b[?1h\x1b[?2004h")
        self.assertFalse(screen.cursor_visible)
        self.assertTrue(screen.app_cursor_keys)
        self.assertTrue(screen.bracketed_paste)
        screen.feed("\x1b[?25h\x1b[?1l\x1b[?2004l")
        self.assertEqual(
            (screen.cursor_visible, screen.app_cursor_keys, screen.bracketed_paste),
            (True, False, False),
        )

    def test_mouse_modes(self) -> None:
        """The mouse modes are noted; tracking is on with 1000, 1002 or
        1003, not with 1006 alone."""
        screen = Screen()
        screen.feed("\x1b[?1006h")
        self.assertFalse(screen.is_tracking_mouse)
        screen.feed("\x1b[?1002h")
        self.assertTrue(screen.is_tracking_mouse)
        self.assertEqual(screen.mouse_modes, {1002, 1006})
        screen.feed("\x1b[?1002;1006l")
        self.assertFalse(screen.mouse_modes)


class EraseTests(unittest.TestCase):
    """Erasing, inserting and deleting."""

    def setUp(self) -> None:
        self.screen = Screen(columns=6, lines=3)
        self.screen.feed("abcdef\r\nghijkl\r\nmnopqr")

    def test_erase_in_line(self) -> None:
        """EL 0, 1 and 2."""
        self.screen.feed("\x1b[1;3H\x1b[K\x1b[2;3H\x1b[1K\x1b[3;3H\x1b[2K")
        self.assertEqual(texts(self.screen), ["ab", "   jkl", ""])

    def test_erase_in_display(self) -> None:
        """ED 0 and 2; erased cells take the background colour."""
        self.screen.feed("\x1b[2;3H\x1b[J")
        self.assertEqual(texts(self.screen), ["abcdef", "gh", ""])
        self.screen.feed("\x1b[44m\x1b[2J")
        self.assertEqual(self.screen.rows[0][0], (" ", Style(background=4)))

    def test_insert_and_delete_characters(self) -> None:
        """ICH, DCH and ECH."""
        self.screen.feed("\x1b[1;2H\x1b[2@\x1b[2;2H\x1b[2P\x1b[3;2H\x1b[2X")
        self.assertEqual(texts(self.screen), ["a  bcd", "gjkl", "m  pqr"])

    def test_insert_and_delete_lines(self) -> None:
        """IL and DL, within the scroll region."""
        self.screen.feed("\x1b[1;1H\x1b[L")
        self.assertEqual(texts(self.screen), ["", "abcdef", "ghijkl"])
        self.screen.feed("\x1b[M")
        self.assertEqual(texts(self.screen), ["abcdef", "ghijkl", ""])

    def test_insert_mode(self) -> None:
        """IRM pushes text right."""
        self.screen.feed("\x1b[1;1H\x1b[4hXY\x1b[4l")
        self.assertEqual(texts(self.screen)[0], "XYabcd")


class ScrollRegionTests(unittest.TestCase):
    """Scroll regions (DECSTBM)."""

    def test_region_scrolls_alone(self) -> None:
        """Only the region's lines move, and none reach the scrollback."""
        screen = Screen(columns=5, lines=4)
        screen.feed("top\r\na\r\nb\r\nfoot\x1b[2;3r\x1b[3;1H\n")
        self.assertEqual(texts(screen), ["top", "b", "", "foot"])
        self.assertEqual(len(screen.scrollback), 0)

    def test_reverse_index_and_scroll_down(self) -> None:
        """RI at the top, and SD, move the lines down."""
        screen = Screen(columns=5, lines=3)
        screen.feed("a\r\nb\r\nc\x1b[H\x1bM")
        self.assertEqual(texts(screen), ["", "a", "b"])
        screen.feed("\x1b[S")
        self.assertEqual(texts(screen), ["a", "b", ""])

    def test_origin_mode(self) -> None:
        """In origin mode, addresses count from the region's top."""
        screen = Screen(columns=5, lines=5)
        screen.feed("\x1b[2;4r\x1b[?6h\x1b[1;1Hx\x1b[9;1Hy")
        self.assertEqual(texts(screen), ["", "x", "", "y", ""])


class StyleTests(unittest.TestCase):
    """SGR: colours and attributes."""

    def style_after(self, sgr: str) -> Style:
        """The style of a character written after ``CSI sgr m``."""
        screen = Screen(columns=5, lines=1)
        screen.feed(f"\x1b[{sgr}mx")
        return screen.rows[0][0][1]

    def test_colours(self) -> None:
        """16, 256 and 24-bit colours, written with ; or :."""
        self.assertEqual(self.style_after("31;42"), Style(foreground=1, background=2))
        self.assertEqual(self.style_after("91;104"), Style(foreground=9, background=12))
        self.assertEqual(self.style_after("38;5;208"), Style(foreground=208))
        self.assertEqual(self.style_after("48:5:17"), Style(background=17))
        self.assertEqual(
            self.style_after("38;2;10;20;30"), Style(foreground=Rgb(10, 20, 30))
        )
        self.assertEqual(
            self.style_after("38:2::10:20:30;1"),
            Style(foreground=Rgb(10, 20, 30), bold=True),
        )

    def test_attributes(self) -> None:
        """Bold, underline and reverse on and off; unsupported ones dropped."""
        self.assertEqual(
            self.style_after("1;4;7;3;5;9"),
            Style(bold=True, underline=True, reverse=True),
        )
        self.assertEqual(self.style_after("1;4;7;22;24;27"), DEFAULT)
        self.assertEqual(self.style_after("31;1;0"), DEFAULT)
        self.assertEqual(self.style_after("31;39"), DEFAULT)

    def test_hidden(self) -> None:
        """Hidden text is written as blanks."""
        screen = Screen(columns=5, lines=1)
        screen.feed("\x1b[8msecret")
        self.assertEqual(texts(screen), [""])

    def test_bad_colours_are_ignored(self) -> None:
        """A colour out of range sets nothing."""
        self.assertEqual(self.style_after("38;5;999"), DEFAULT)
        self.assertEqual(self.style_after("38;2;300;0;0"), DEFAULT)


class ScreenTests(unittest.TestCase):
    """The alternate screen, titles, character sets and resizing."""

    def test_alternate_screen(self) -> None:
        """1049 saves the main screen and cursor, and gives them back."""
        screen = Screen(columns=5, lines=2)
        screen.feed("main\x1b[?1049h")
        self.assertTrue(screen.is_alternate)
        self.assertEqual(texts(screen), ["", ""])
        screen.feed("full\r\n\n\n")
        self.assertEqual(len(screen.scrollback), 0)
        screen.feed("\x1b[?1049l")
        self.assertFalse(screen.is_alternate)
        self.assertEqual(texts(screen), ["main", ""])
        self.assertEqual(screen.cursor, (0, 4))

    def test_title(self) -> None:
        """OSC 0 and 2 set the title, ended by BEL or ST, without controls."""
        screen = Screen()
        screen.feed("\x1b]2;one\x07")
        self.assertEqual(screen.title, "one")
        screen.feed("\x1b]0;two\x1b\\")
        self.assertEqual(screen.title, "two")
        screen.feed("\x1b]0;" + "x" * 5000 + "\x07")
        self.assertEqual(len(screen.title), 1000)

    def test_line_drawing(self) -> None:
        """The DEC special graphics set draws boxes, and is put away again."""
        screen = Screen(columns=10, lines=1)
        screen.feed("\x1b(0lqk\x1b(Bq\x0e")
        self.assertEqual(
            texts(screen),
            [
                "\N{BOX DRAWINGS LIGHT DOWN AND RIGHT}"
                "\N{BOX DRAWINGS LIGHT HORIZONTAL}"
                "\N{BOX DRAWINGS LIGHT DOWN AND LEFT}q"
            ],
        )

    def test_wide_and_combining_characters(self) -> None:
        """A wide character takes two cells; a combining mark joins the
        character before it."""
        screen = Screen(columns=6, lines=2)
        screen.feed("\N{CJK UNIFIED IDEOGRAPH-5BEC}xe\N{COMBINING ACUTE ACCENT}")
        row = screen.rows[0]
        self.assertEqual(
            [cell[0] for cell in row[:4]],
            [
                "\N{CJK UNIFIED IDEOGRAPH-5BEC}",
                "",
                "x",
                "\N{LATIN SMALL LETTER E WITH ACUTE}",
            ],
        )
        self.assertEqual(screen.cursor, (0, 4))
        screen.feed("\x1b[1;2Hy")
        self.assertEqual([cell[0] for cell in row[:2]], [" ", "y"])
        self.assertEqual(
            (char_width("a"), char_width("\N{CJK UNIFIED IDEOGRAPH-5BEC}")), (1, 2)
        )

    def test_resize_keeps_the_cursor_line(self) -> None:
        """Shrinking puts the top lines into the scrollback; growing brings
        them back."""
        screen = Screen(columns=5, lines=4)
        screen.feed("1\r\n2\r\n3\r\n4")
        screen.resize(columns=3, lines=2)
        self.assertEqual(texts(screen), ["3", "4"])
        self.assertEqual(screen.cursor, (1, 1))
        self.assertEqual(len(screen.scrollback), 2)
        screen.resize(columns=8, lines=4)
        self.assertEqual(texts(screen), ["1", "2", "3", "4"])
        self.assertEqual(screen.cursor, (3, 1))
        self.assertTrue(all(len(row) == 8 for row in screen.rows))

    def test_copying_text(self) -> None:
        """Copied text drops trailing blanks and joins wrapped lines."""
        screen = Screen(columns=4, lines=3)
        screen.feed("abcdef\r\ngh")
        self.assertEqual(screen.text(screen.rows), "abcdef\ngh")

    def test_reset(self) -> None:
        """ESC c clears the screen and the modes."""
        screen = Screen(columns=5, lines=2)
        screen.feed("x\x1b[?25l\x1b[31m\x1bc")
        self.assertEqual(texts(screen), ["", ""])
        self.assertTrue(screen.cursor_visible)
        self.assertEqual(screen.style, DEFAULT)


if __name__ == "__main__":
    unittest.main()
