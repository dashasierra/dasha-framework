"""Tests for decoding terminal input into key and mouse events."""

import unittest

from dasha.events import (
    PASTE_END,
    PASTE_START,
    PASTE_TIMEOUT,
    InputDecoder,
    MouseEvent,
    PasteEvent,
    decode,
    read_events,
)


class DecodeTests(unittest.TestCase):
    """Raw input to key names."""

    def test_plain_and_control_keys(self) -> None:
        """Characters pass through; control codes get names."""
        self.assertEqual(
            decode("a\t\r\x7f\x11"), ["a", "tab", "enter", "backspace", "ctrl+q"]
        )

    def test_lone_escape(self) -> None:
        """A lone ESC is the Escape key."""
        self.assertEqual(decode("\x1b"), ["escape"])

    def test_cursor_and_function_keys(self) -> None:
        """CSI and SS3 sequences become key names."""
        self.assertEqual(
            decode("\x1b[A\x1b[D\x1bOP\x1b[17~\x1b[6~"),
            ["up", "left", "f1", "f6", "pagedown"],
        )

    def test_modifiers(self) -> None:
        """Shift, Alt and Ctrl modifiers are decoded."""
        self.assertEqual(
            decode("\x1b[Z\x1b[17;2~\x1b[1;5C\x1bx"),
            ["shift+tab", "shift+f6", "ctrl+right", "alt+x"],
        )

    def test_escape_prefixed_alt_keys(self) -> None:
        """ESC-prefixed Alt with function keys."""
        self.assertEqual(
            decode("\x1b\x1bOR\x1b\x1b[13~\x1b\x1b[1;2R\x1b\x1b[24~"),
            ["alt+f3", "alt+f3", "shift+alt+f3", "alt+f12"],
        )
        self.assertEqual(decode("\x1b\x1b[A"), ["escape", "up"])

    def test_escape_then_other_things(self) -> None:
        """Escape followed by other input."""
        self.assertEqual(decode("\x1b\x1b"), ["escape", "escape"])
        self.assertEqual(decode("\x1b\x1bx"), ["escape", "alt+x"])
        events = decode("\x1b\x1b[<0;2;3M\x1b\x1b[200~hi\x1b[201~")
        self.assertEqual(events[0], "escape")
        self.assertIsInstance(events[1], MouseEvent)
        self.assertEqual(events[2:], ["escape", PasteEvent("hi")])

    def test_escape_prefixed_alt_key_split_across_reads(self) -> None:
        """The prefixed sequence can arrive in pieces."""
        decoder = InputDecoder()
        self.assertEqual(decoder.feed("\x1b\x1b["), [])
        self.assertEqual(decoder.feed("13~"), ["alt+f3"])

    def test_a_long_paste_in_pieces(self) -> None:
        """A long paste in pieces."""
        text = "line\n" * 2000
        data = PASTE_START + text + PASTE_END + "x"
        # pylint: disable=protected-access
        for size in (1, 3, 5, 6, 7, 4096):
            with self.subTest(size=size):
                decoder = InputDecoder()
                events = []
                for at in range(0, len(data), size):
                    events += decoder.feed(data[at : at + size])
                    self.assertLess(len(decoder._buffer), len(PASTE_END) + size)
                self.assertEqual(events, [PasteEvent(text), "x"])
                self.assertFalse(decoder.is_pending)

    def test_split_just_after_the_second_escape(self) -> None:
        """A split just after the second ESC."""
        decoder = InputDecoder()
        self.assertEqual(decoder.feed("\x1b\x1b"), [])
        self.assertTrue(decoder.is_pending)
        self.assertEqual(decoder.feed("OR"), ["alt+f3"])
        for rest, keys in (("[A", ["escape", "up"]), ("x", ["escape", "alt+x"])):
            with self.subTest(rest=rest):
                self.assertEqual(decoder.feed("\x1b\x1b") + decoder.feed(rest), keys)

    def test_escape_twice_when_nothing_follows(self) -> None:
        """If nothing more comes (the escape timeout), two Escapes."""
        decoder = InputDecoder()
        self.assertEqual(decoder.feed("\x1b\x1b"), [])
        self.assertEqual(decoder.flush(), ["escape", "escape"])

    def test_unknown_sequence_is_reported(self) -> None:
        """Unrecognised sequences are named rather than dropped."""
        self.assertEqual(decode("\x1b[99~"), ["unknown(99~)"])


class MouseTests(unittest.TestCase):
    """SGR mouse reports."""

    def test_press_and_release(self) -> None:
        """M is a press, m a release; positions become 0-based."""
        self.assertEqual(
            decode("\x1b[<0;10;5M\x1b[<0;10;5m"),
            [MouseEvent("press", "left", 4, 9), MouseEvent("release", "left", 4, 9)],
        )

    def test_buttons_and_modifiers(self) -> None:
        """Right button with Ctrl; middle with Shift and Alt."""
        self.assertEqual(
            decode("\x1b[<18;1;1M\x1b[<13;2;3M"),
            [
                MouseEvent("press", "right", 0, 0, ctrl=True),
                MouseEvent("press", "middle", 2, 1, shift=True, alt=True),
            ],
        )

    def test_drag_move_and_scroll(self) -> None:
        """Drags, moves and the wheel."""
        self.assertEqual(
            decode("\x1b[<32;5;5M\x1b[<35;6;6M\x1b[<64;1;1M\x1b[<65;1;1M"),
            [
                MouseEvent("drag", "left", 4, 4),
                MouseEvent("move", "none", 5, 5),
                MouseEvent("scroll", "up", 0, 0),
                MouseEvent("scroll", "down", 0, 0),
            ],
        )

    def test_large_coordinates(self) -> None:
        """SGR reports have no 223-column limit."""
        self.assertEqual(
            decode("\x1b[<0;300;100M"), [MouseEvent("press", "left", 99, 299)]
        )

    def test_malformed_report(self) -> None:
        """A broken report is named rather than crashing."""
        self.assertEqual(decode("\x1b[<0;1M"), ["unknown(<0;1M)"])


class StreamingTests(unittest.TestCase):
    """Input that arrives in pieces."""

    def test_sequence_split_across_reads(self) -> None:
        """An unfinished sequence is held back until the rest arrives."""
        decoder = InputDecoder()
        self.assertEqual(decoder.feed("a\x1b[<0;10"), ["a"])
        self.assertTrue(decoder.is_pending)
        self.assertEqual(decoder.feed(";5M"), [MouseEvent("press", "left", 4, 9)])
        self.assertFalse(decoder.is_pending)

    def test_lone_escape_waits_for_flush(self) -> None:
        """A trailing ESC is held back, and becomes Escape on flush."""
        decoder = InputDecoder()
        self.assertEqual(decoder.feed("\x1b"), [])
        self.assertTrue(decoder.is_pending)
        self.assertEqual(decoder.flush(), ["escape"])
        self.assertFalse(decoder.is_pending)

    def test_escape_then_sequence_start(self) -> None:
        """ESC ESC [ A is Escape then Up."""
        self.assertEqual(decode("\x1b\x1b[A"), ["escape", "up"])

    def test_runaway_sequence_is_not_held_forever(self) -> None:
        """Garbage that never finishes is released, not buffered forever."""
        decoder = InputDecoder()
        events = decoder.feed("\x1b[" + "1" * 40)
        self.assertEqual(events[0], "alt+[")
        self.assertFalse(decoder.is_pending)


START, END = "\x1b[200~", "\x1b[201~"


class FakeReader:  # pylint: disable=too-few-public-methods
    """Scripted reads, recording each timeout.

    :param inputs: Reads; ``""`` is a timeout.
    """

    def __init__(self, inputs: list[str]) -> None:
        self.inputs = inputs
        self.timeouts: list[float | None] = []

    def read(self, timeout: float | None = None) -> str:
        """The next scripted input.

        :param timeout: Recorded.
        """
        self.timeouts.append(timeout)
        return self.inputs.pop(0)


class PasteTests(unittest.TestCase):
    """Bracketed paste: ESC[200~ ... ESC[201~ becomes one PasteEvent."""

    def test_paste_is_one_event(self) -> None:
        """A paste is one event."""
        self.assertEqual(
            decode("a" + START + "hello world" + END + "b"),
            ["a", PasteEvent("hello world"), "b"],
        )

    def test_control_characters_in_a_paste_are_text(self) -> None:
        """Control characters in a paste are text."""
        text = "1\r2\n\x11\x1b[A\x1b"
        self.assertEqual(decode(START + text + END), [PasteEvent(text)])

    def test_empty_paste_and_stray_end(self) -> None:
        """Empty pastes and stray ends."""
        self.assertEqual(decode(START + END + "x" + END), ["x"])

    def test_split_anywhere(self) -> None:
        """However the input is cut in two, the result is the same."""
        data = "a" + START + "3a4\r" + END + "\x1b[A"
        expected = ["a", PasteEvent("3a4\r"), "up"]
        for cut in range(len(data) + 1):
            with self.subTest(cut=cut):
                decoder = InputDecoder()
                events = decoder.feed(data[:cut]) + decoder.feed(data[cut:])
                self.assertEqual(events, expected)
                self.assertFalse(decoder.is_pending or decoder.is_pasting)

    def test_one_character_at_a_time(self) -> None:
        """A paste arriving a character per read is still one event."""
        decoder = InputDecoder()
        events = []
        for char in START + "hello" + END:
            events += decoder.feed(char)
        self.assertEqual(events, [PasteEvent("hello")])

    def test_paste_is_held_until_it_ends(self) -> None:
        """Text is held back, not delivered piecemeal, until the end marker."""
        decoder = InputDecoder()
        self.assertEqual(decoder.feed(START + "12"), [])
        self.assertTrue(decoder.is_pending and decoder.is_pasting)
        self.assertEqual(decoder.feed("34\x1b[20"), [])
        self.assertEqual(decoder.feed("1~"), [PasteEvent("1234")])
        self.assertFalse(decoder.is_pending or decoder.is_pasting)

    def test_flush_delivers_an_unfinished_paste(self) -> None:
        """Flush delivers an unfinished paste."""
        decoder = InputDecoder()
        decoder.feed(START + "12")
        self.assertEqual(decoder.flush(), [PasteEvent("12")])
        self.assertFalse(decoder.is_pending)
        self.assertTrue(decoder.is_pasting)
        self.assertEqual(decoder.feed("3\x11" + END + "a"), [PasteEvent("3\x11"), "a"])
        self.assertFalse(decoder.is_pasting)

    def test_read_events_waits_for_the_rest_of_a_paste(self) -> None:
        """``read_events`` waits for the rest of a paste."""
        reader = FakeReader([START + "12", "34", "5" + END + "\x1b", "[A"])
        events = read_events(reader, InputDecoder(), 0.05)
        self.assertEqual(events, [PasteEvent("12345"), "up"])
        self.assertEqual(reader.timeouts, [None, PASTE_TIMEOUT, PASTE_TIMEOUT, 0.05])

    def test_read_events_gives_up_on_a_stalled_paste(self) -> None:
        """``read_events`` gives up on a stalled paste."""
        reader = FakeReader([START + "12", ""])
        events = read_events(reader, InputDecoder(), 0.05, paste_timeout=2.0)
        self.assertEqual(events, [PasteEvent("12")])
        self.assertEqual(reader.timeouts, [None, 2.0])


if __name__ == "__main__":
    unittest.main()
