"""Tests for the VT emulator's less common sequences and edge cases."""

# pylint: disable=protected-access

import unittest

from dasha import vt
from dasha.events import MouseEvent
from dasha.style import DEFAULT, Rgb, Style
from dasha.vt import Screen, char_width, encode_key, encode_mouse


def texts(screen: Screen) -> list[str]:
    """Each row's characters, trimmed.

    :param screen: The screen.
    """
    return ["".join(cell[0] for cell in row).rstrip() for row in screen.rows]


WIDE = "\N{CJK UNIFIED IDEOGRAPH-5BEC}"
ACUTE = "\N{COMBINING ACUTE ACCENT}"


class ControlTests(unittest.TestCase):
    """C0 controls and simple escapes."""

    def test_newline_mode(self) -> None:
        """With LNM (mode 20) on, LF also returns the carriage."""
        screen = Screen(columns=5, lines=3)
        screen.feed("\x1b[20hab\ncd\x1b[20l\nef")
        self.assertEqual(texts(screen), ["ab", "cd", "  ef"])
        self.assertFalse(screen.newline)

    def test_backspace_at_the_edges(self) -> None:
        """Backspace cancels a pending wrap, and stops at column 0."""
        screen = Screen(columns=3, lines=2)
        screen.feed("abc\x08x")
        self.assertEqual(texts(screen), ["abx", ""])
        screen.feed("\r\x08\x08y")
        self.assertEqual(texts(screen), ["ybx", ""])

    def test_shift_out_and_in(self) -> None:
        """SO uses G1, SI goes back to G0."""
        screen = Screen(columns=5, lines=1)
        screen.feed("\x1b)0\x0eq\x0fq")
        self.assertEqual(texts(screen), ["\N{BOX DRAWINGS LIGHT HORIZONTAL}q"])

    def test_escapes_within_escapes(self) -> None:
        """ESC ESC starts again; controls in a sequence are carried out; long
        intermediates are cut short."""
        screen = Screen(columns=5, lines=2)
        screen.feed("\x1b\x1b[2Ca")
        self.assertEqual(texts(screen), ["  a", ""])
        screen.feed("\x1b\r(0q")
        self.assertEqual(texts(screen), ["\N{BOX DRAWINGS LIGHT HORIZONTAL} a", ""])
        screen.feed("\x1b(((((Bq")
        self.assertEqual(screen.rows[0][1][0], "\N{BOX DRAWINGS LIGHT HORIZONTAL}")

    def test_alignment_pattern(self) -> None:
        """ESC # 8 fills the screen with Es."""
        screen = Screen(columns=3, lines=2)
        screen.feed("\x1b#8")
        self.assertEqual(texts(screen), ["EEE", "EEE"])

    def test_index_next_line_and_tab_set(self) -> None:
        """ESC D, ESC E and ESC H."""
        screen = Screen(columns=20, lines=3)
        screen.feed("ab\x1bDc\x1bEd")
        self.assertEqual(texts(screen), ["ab", "  c", "d"])
        screen.feed("\x1b[3g\x1b[1;4H\x1bH\r\tx")
        self.assertEqual(texts(screen)[0], "ab x")

    def test_keypad_modes(self) -> None:
        """ESC = and ESC > turn the application keypad on and off."""
        screen = Screen()
        screen.feed("\x1b=")
        self.assertTrue(screen.app_keypad)
        screen.feed("\x1b>")
        self.assertFalse(screen.app_keypad)

    def test_unknown_controls_and_escapes_are_ignored(self) -> None:
        """NUL, unknown escapes and designations change nothing."""
        screen = Screen(columns=5, lines=1)
        screen.feed("a\x00\x1bZ\x1b#3\x1b%Gb")
        self.assertEqual(texts(screen), ["ab"])
        self.assertEqual(screen.cursor, (0, 2))

    def test_replies_are_capped(self) -> None:
        """A program that asks without reading gets 100 replies at most."""
        screen = Screen()
        screen.feed("\x1b[5n" * 150)
        self.assertEqual(screen.take_replies(), b"\x1b[0n" * 100)


class StringTests(unittest.TestCase):
    """OSC and other strings."""

    def test_escape_in_a_string_starts_a_sequence(self) -> None:
        """ESC then anything but a backslash ends the string and begins a
        new sequence."""
        screen = Screen(columns=10, lines=1)
        screen.feed("\x1b]2;name\x1b[3Cx")
        self.assertEqual(screen.title, "")
        self.assertEqual(texts(screen), ["   x"])

    def test_other_osc_numbers_are_ignored(self) -> None:
        """Only OSC 0 and 2 set the title."""
        screen = Screen()
        screen.feed("\x1b]7;file:///tmp\x07")
        self.assertEqual(screen.title, "")


class CsiTests(unittest.TestCase):
    """Control sequences."""

    def test_escape_and_controls_within_a_sequence(self) -> None:
        """ESC abandons a sequence; a control is carried out in it."""
        screen = Screen(columns=10, lines=2)
        screen.feed("\x1b[3\x1b[2Ca")
        self.assertEqual(texts(screen), ["  a", ""])
        screen.feed("\x1b[\r2Cb")
        self.assertEqual(texts(screen), ["  b", ""])

    def test_overlong_sequences_are_dropped(self) -> None:
        """A sequence past the longest kept is garbage."""
        screen = Screen(columns=10, lines=1)
        screen.feed("\x1b[" + ";" * 257 + "x")
        self.assertEqual(texts(screen), ["x"])

    def test_soft_reset_keeps_the_screen(self) -> None:
        """CSI ! p resets the modes but keeps the text and the cursor."""
        screen = Screen(columns=5, lines=3)
        screen.feed("ab\x1b[31m\x1b[?25l\x1b[2;3r\x1b[2;2H\x1b[!p")
        self.assertEqual(texts(screen), ["ab", "", ""])
        self.assertEqual(screen.cursor, (1, 1))
        self.assertTrue(screen.cursor_visible)
        self.assertEqual(screen.style, DEFAULT)
        self.assertEqual((screen.top, screen.bottom), (0, 2))

    def test_line_movement(self) -> None:
        """CPL and CNL move lines and go to column 0."""
        screen = Screen(columns=10, lines=5)
        screen.feed("\x1b[3;5H\x1b[F")
        self.assertEqual(screen.cursor, (1, 0))
        screen.feed("\x1b[4G\x1b[2E")
        self.assertEqual(screen.cursor, (3, 0))

    def test_scroll_down(self) -> None:
        """SD moves the lines down."""
        screen = Screen(columns=5, lines=3)
        screen.feed("a\r\nb\r\nc\x1b[2T")
        self.assertEqual(texts(screen), ["", "", "a"])

    def test_tab_forward_and_back(self) -> None:
        """CHT and CBT; without stops, to the edges."""
        screen = Screen(columns=20, lines=1)
        screen.feed("\x1b[2I")
        self.assertEqual(screen.cursor, (0, 16))
        screen.feed("\x1b[Z")
        self.assertEqual(screen.cursor, (0, 8))
        screen.feed("\x1b[3g\x1b[Z")
        self.assertEqual(screen.cursor, (0, 0))
        screen.feed("\x1b[I")
        self.assertEqual(screen.cursor, (0, 19))

    def test_clearing_one_tab_stop(self) -> None:
        """TBC 0 clears the stop under the cursor."""
        screen = Screen(columns=20, lines=1)
        screen.feed("\x1b[9G\x1b[g\r\t")
        self.assertEqual(screen.cursor, (0, 16))

    def test_repeat(self) -> None:
        """REP writes the last character again."""
        screen = Screen(columns=10, lines=1)
        screen.feed("x\x1b[3b")
        self.assertEqual(texts(screen), ["xxxx"])

    def test_save_and_restore_with_csi(self) -> None:
        """CSI s and CSI u save and restore the cursor."""
        screen = Screen(columns=10, lines=3)
        screen.feed("\x1b[2;3H\x1b[s\x1b[H\x1b[ux")
        self.assertEqual(texts(screen), ["", "  x", ""])

    def test_unknown_parameters_are_ignored(self) -> None:
        """TBC 2, SM 3, ED 4 and DEC mode 9999 change nothing."""
        screen = Screen(columns=20, lines=2)
        screen.feed("ab\x1b[2g\x1b[3h\x1b[4J\x1b[?9999h\r\t")
        self.assertEqual(texts(screen), ["ab", ""])
        self.assertEqual(screen.cursor, (0, 8))
        self.assertFalse(screen.insert)

    def test_other_reports_are_ignored(self) -> None:
        """A report not known gets no answer."""
        screen = Screen()
        screen.feed("\x1b[99n\x1b[1c")
        self.assertEqual(screen.take_replies(), b"")

    def test_cursor_report_in_origin_mode(self) -> None:
        """In origin mode, the place is counted from the region's top."""
        screen = Screen(columns=10, lines=5)
        screen.feed("\x1b[2;4r\x1b[?6h\x1b[2;3H\x1b[6n")
        self.assertEqual(screen.take_replies(), b"\x1b[2;3R")

    def test_bad_scroll_region_is_ignored(self) -> None:
        """A region whose top is not above its bottom changes nothing."""
        screen = Screen(columns=5, lines=5)
        screen.feed("\x1b[2;2H\x1b[4;2r")
        self.assertEqual((screen.top, screen.bottom), (0, 4))
        self.assertEqual(screen.cursor, (1, 1))


class ModeTests(unittest.TestCase):
    """DEC private modes."""

    def test_autowrap_back_on(self) -> None:
        """Turning autowrap on again wraps as before."""
        screen = Screen(columns=3, lines=2)
        screen.feed("\x1b[?7l\x1b[?7habcd")
        self.assertEqual(texts(screen), ["abc", "d"])

    def test_mode_47_keeps_the_alternate_screen(self) -> None:
        """Mode 47 switches screens without clearing; 1047 clears on the way
        back."""
        screen = Screen(columns=5, lines=1)
        screen.feed("main\x1b[?47h\ralt\x1b[?47l")
        self.assertEqual(texts(screen), ["main"])
        screen.feed("\x1b[?47h")
        self.assertEqual(texts(screen), ["alt"])
        screen.feed("\x1b[?47h\x1b[?1047l\x1b[?47h")
        self.assertEqual(texts(screen), [""])

    def test_mode_1048_saves_the_cursor(self) -> None:
        """Mode 1048 saves and restores the cursor."""
        screen = Screen(columns=10, lines=3)
        screen.feed("\x1b[2;4H\x1b[?1048h\x1b[H\x1b[?1048lx")
        self.assertEqual(texts(screen), ["", "   x", ""])


class AttributeTests(unittest.TestCase):
    """SGR edge cases."""

    def style_after(self, sgr: str) -> Style:
        """The style of a character written after ``CSI sgr m``.

        :param sgr: The SGR parameters.
        """
        screen = Screen(columns=5, lines=1)
        screen.feed(f"\x1b[{sgr}mx")
        return screen.rows[0][0][1]

    def test_underline_colour_is_read_and_dropped(self) -> None:
        """SGR 58 is taken in, parameters and all, and sets nothing."""
        self.assertEqual(self.style_after("58;5;9;1"), Style(bold=True))
        self.assertEqual(self.style_after("58:2::1:2:3;4"), Style(underline=True))

    def test_default_background_and_reveal(self) -> None:
        """SGR 49 drops the background; SGR 28 shows hidden text again."""
        self.assertEqual(self.style_after("41;49"), DEFAULT)
        screen = Screen(columns=5, lines=1)
        screen.feed("\x1b[8ma\x1b[28mb")
        self.assertEqual(texts(screen), [" b"])

    def test_extended_colours_without_enough_parameters(self) -> None:
        """38 with nothing after it, or too little, sets nothing."""
        self.assertEqual(self.style_after("38"), DEFAULT)
        self.assertEqual(self.style_after("38;2;1;2"), DEFAULT)
        self.assertEqual(self.style_after("38:2:1:2:3"), Style(foreground=Rgb(1, 2, 3)))

    def test_hidden_combining_marks_write_nothing(self) -> None:
        """A hidden combining mark takes no cell."""
        screen = Screen(columns=5, lines=1)
        screen.feed("a\x1b[8m" + ACUTE)
        self.assertEqual(texts(screen), ["a"])
        self.assertEqual(screen.cursor, (0, 1))


class WideCharacterTests(unittest.TestCase):
    """Wide characters and combining marks at the edges."""

    def test_wide_character_at_the_last_column_wraps(self) -> None:
        """A wide character with no room goes onto the next line."""
        screen = Screen(columns=3, lines=2)
        screen.feed("ab" + WIDE)
        self.assertEqual([cell[0] for cell in screen.rows[0]], ["a", "b", " "])
        self.assertEqual([cell[0] for cell in screen.rows[1][:2]], [WIDE, ""])
        self.assertTrue(screen.rows[0].wrapped)

    def test_wide_character_without_autowrap_is_dropped(self) -> None:
        """With autowrap off, a wide character with no room is not written."""
        screen = Screen(columns=3, lines=2)
        screen.feed("\x1b[?7lab" + WIDE)
        self.assertEqual(texts(screen), ["ab", ""])

    def test_wrapping_wide_text(self) -> None:
        """Wide text fills the line, then wraps; without autowrap it
        overwrites the end."""
        screen = Screen(columns=4, lines=2)
        screen.feed(WIDE * 3)
        self.assertEqual(screen.rows[1][0][0], WIDE)
        self.assertEqual(screen.cursor, (1, 2))
        screen = Screen(columns=4, lines=2)
        screen.feed("\x1b[?7l" + WIDE * 2 + "\N{POUND SIGN}")
        self.assertEqual(
            [cell[0] for cell in screen.rows[0]], [WIDE, "", " ", "\N{POUND SIGN}"]
        )

    def test_combining_marks_at_the_edges(self) -> None:
        """A mark joins a wide character, does nothing at column 0, and
        joins only short clusters."""
        screen = Screen(columns=5, lines=1)
        screen.feed(WIDE + ACUTE)
        self.assertEqual(screen.rows[0][0][0], WIDE + ACUTE)
        screen.feed("\r" + ACUTE)
        self.assertEqual(screen.rows[0][0][0], WIDE + ACUTE)
        screen.feed("\x1b[4Gx" + ACUTE * 12)
        self.assertEqual(len(screen.rows[0][3][0]), 8)

    def test_combining_mark_at_the_end_of_the_line(self) -> None:
        """With a wrap pending, a mark joins the last column."""
        screen = Screen(columns=2, lines=1)
        screen.feed("ae" + ACUTE)
        self.assertEqual(screen.rows[0][1][0], "\N{LATIN SMALL LETTER E WITH ACUTE}")

    def test_overwriting_the_left_half_of_a_wide_character(self) -> None:
        """Writing over a wide character's left half blanks its right."""
        screen = Screen(columns=5, lines=1)
        screen.feed(WIDE + "\rx")
        self.assertEqual([cell[0] for cell in screen.rows[0][:2]], ["x", " "])

    def test_inserting_pushes_a_wide_character_half_off(self) -> None:
        """A wide character pushed half off the end is blanked."""
        screen = Screen(columns=4, lines=1)
        screen.feed("ab" + WIDE + "\r\x1b[@")
        self.assertEqual([cell[0] for cell in screen.rows[0]], [" ", "a", "b", " "])

    def test_inserting_keeps_a_wide_character_that_fits(self) -> None:
        """A wide character pushed to the very end is kept whole."""
        screen = Screen(columns=4, lines=1)
        screen.feed("a" + WIDE + "b\r\x1b[@")
        self.assertEqual([cell[0] for cell in screen.rows[0]], [" ", "a", WIDE, ""])

    def test_width_cache_stops_growing(self) -> None:
        """The width cache holds 4096 characters at most."""
        saved = dict(vt._width_cache)
        try:
            vt._width_cache.clear()
            for number in range(0x4E00, 0x4E00 + 4100):
                self.assertEqual(char_width(chr(number)), 2)
            self.assertEqual(len(vt._width_cache), 4096)
            self.assertEqual(char_width(ACUTE), 0)
        finally:
            vt._width_cache.clear()
            vt._width_cache.update(saved)


class CursorEdgeTests(unittest.TestCase):
    """Moving the cursor outside the scroll region."""

    def test_index_below_the_region(self) -> None:
        """Below the region, LF moves down and stops at the last line."""
        screen = Screen(columns=5, lines=4)
        screen.feed("\x1b[1;2r\x1b[3;1Ha\n\n\nb")
        self.assertEqual(texts(screen), ["", "", "a", " b"])

    def test_reverse_index_within_the_region(self) -> None:
        """RI below the region's top moves up a line."""
        screen = Screen(columns=5, lines=3)
        screen.feed("\x1b[3;1H\x1bM")
        self.assertEqual(screen.cursor, (1, 0))
        screen.feed("\x1b[2;3r\x1b[1;1H\x1bM")
        self.assertEqual(screen.cursor, (0, 0))

    def test_lines_outside_the_region(self) -> None:
        """IL and DL outside the region do nothing."""
        screen = Screen(columns=5, lines=3)
        screen.feed("a\r\nb\r\nc\x1b[2;3r\x1b[1;1H\x1b[L\x1b[M")
        self.assertEqual(texts(screen), ["a", "b", "c"])


class EraseEdgeTests(unittest.TestCase):
    """Erasing above and the scrollback."""

    def test_erase_above(self) -> None:
        """ED 1 erases from the top to the cursor."""
        screen = Screen(columns=4, lines=3)
        screen.feed("abcd\r\nefgh\r\nijkl\x1b[2;2H\x1b[1J")
        self.assertEqual(texts(screen), ["", "  gh", "ijkl"])
        self.assertTrue(screen.rows[1].wrapped is False)

    def test_erase_scrollback(self) -> None:
        """ED 3 forgets the scrollback."""
        screen = Screen(columns=4, lines=1)
        screen.feed("a\r\nb\x1b[3J")
        self.assertEqual(len(screen.scrollback), 0)
        self.assertEqual(texts(screen), ["b"])


class ResizeTests(unittest.TestCase):
    """Resizing edge cases."""

    def test_same_size_changes_nothing(self) -> None:
        """Resizing to the same size keeps everything."""
        screen = Screen(columns=5, lines=3)
        screen.feed("\x1b[1;2rab")
        screen.resize(columns=5, lines=3)
        self.assertEqual((screen.top, screen.bottom), (0, 1))
        self.assertEqual(texts(screen), ["ab", "", ""])

    def test_narrowing_through_a_wide_character(self) -> None:
        """A wide character cut in half by narrowing is blanked."""
        screen = Screen(columns=5, lines=1)
        screen.feed("ab" + WIDE)
        screen.resize(columns=3, lines=1)
        self.assertEqual([cell[0] for cell in screen.rows[0]], ["a", "b", " "])

    def test_narrowing_to_just_after_a_wide_character(self) -> None:
        """A wide character that still fits is kept whole."""
        screen = Screen(columns=6, lines=1)
        screen.feed("ab" + WIDE)
        screen.resize(columns=4, lines=1)
        self.assertEqual([cell[0] for cell in screen.rows[0]], ["a", "b", WIDE, ""])

    def test_shrinking_without_scrollback(self) -> None:
        """With no scrollback, lines off the top are dropped."""
        screen = Screen(columns=5, lines=3, scrollback=0)
        screen.feed("1\r\n2\r\n3")
        screen.resize(columns=5, lines=1)
        self.assertEqual(texts(screen), ["3"])
        self.assertEqual(screen.scrolled_off, 0)

    def test_growing_on_the_alternate_screen(self) -> None:
        """On the alternate screen, growing brings back the main screen's
        scrollback but leaves the cursor where it was."""
        screen = Screen(columns=5, lines=2)
        screen.feed("1\r\n2\r\n3\x1b[?1049h\x1b[2;1H")
        screen.resize(columns=5, lines=3)
        self.assertEqual(screen.cursor, (1, 0))
        screen.feed("\x1b[?1049l")
        self.assertEqual(texts(screen), ["1", "2", "3"])

    def test_saved_cursors_are_kept_on_the_screen(self) -> None:
        """A saved cursor off the new screen is brought onto it."""
        screen = Screen(columns=10, lines=5)
        screen.feed("\x1b[5;10H\x1b7")
        screen.resize(columns=4, lines=2)
        screen.feed("\x1b8")
        self.assertEqual(screen.cursor, (1, 3))


class EncodeEdgeTests(unittest.TestCase):
    """Keys and mouse events with nothing, or something odd, to send."""

    def test_plus_key(self) -> None:
        """A key name ending in ``++`` is the plus key with modifiers."""
        self.assertEqual(encode_key("alt++"), b"\x1b+")
        self.assertEqual(encode_key("shift+a"), b"A")
        self.assertEqual(encode_key("alt+space"), b"\x1b ")
        self.assertIsNone(encode_key("ctrl+"))

    def test_mouse_events_with_no_report(self) -> None:
        """An unknown wheel or button sends nothing."""
        modes = {1000, 1006}
        self.assertIsNone(
            encode_mouse(MouseEvent("scroll", "sideways", 0, 0), 0, 0, modes)
        )
        self.assertIsNone(encode_mouse(MouseEvent("press", "back", 0, 0), 0, 0, modes))
        self.assertEqual(
            encode_mouse(MouseEvent("drag", "left", 0, 0), 0, 0, {1002}),
            b"\x1b[M@!!",
        )


if __name__ == "__main__":
    unittest.main()
