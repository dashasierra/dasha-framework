"""Tests for the Windows console backend's input record handling."""

import sys
import unittest
from typing import Any
from unittest.mock import patch

if sys.platform == "win32":
    import ctypes

    from dasha.terminal import _windows, ansi
    from dasha.terminal._winbuffer import (
        COORD,
        CONSOLE_SCREEN_BUFFER_INFO,
        SMALL_RECT,
    )
    from dasha.terminal._windows import (
        INPUT_RECORD,
        KEY_EVENT,
        VK_SPACE,
        WINDOW_BUFFER_SIZE_EVENT,
        WindowsConsole,
        records_to_text,
    )

    def make_records(*specs: tuple[int, str, bool]) -> "list[INPUT_RECORD]":
        """Build input records.

        :param specs: (event type, character, key down) triples.
        """
        records = []
        for event_type, char, down in specs:
            record = INPUT_RECORD(EventType=event_type)
            record.Event.KeyEvent.bKeyDown = down
            record.Event.KeyEvent.wRepeatCount = 1
            record.Event.KeyEvent.UnicodeChar = char
            records.append(record)
        return records

    class RecordsToTextTests(unittest.TestCase):
        """Turning console input records into text."""

        def convert(self, *specs: tuple[int, str, bool]) -> tuple[str, bool]:
            """Run ``records_to_text`` on built records.

            :param specs: (event type, character, key down) triples.
            """
            records = make_records(*specs)
            array = (INPUT_RECORD * len(records))(*records)
            return records_to_text(array, len(records))

        def test_key_downs_become_text(self) -> None:
            """Key presses give their characters; releases are skipped."""
            self.assertEqual(
                self.convert(
                    (KEY_EVENT, "\x1b", True),
                    (KEY_EVENT, "[", True),
                    (KEY_EVENT, "[", False),
                    (KEY_EVENT, "A", True),
                ),
                ("\x1b[A", False),
            )

        def test_resize_is_reported(self) -> None:
            """A window buffer size event sets the resized flag."""
            self.assertEqual(
                self.convert((WINDOW_BUFFER_SIZE_EVENT, "\0", False)), ("", True)
            )

        def test_surrogate_pairs_are_joined(self) -> None:
            """Characters beyond U+FFFF arrive in two halves and are joined."""
            text, _ = self.convert(
                (KEY_EVENT, chr(0xD83D), True), (KEY_EVENT, chr(0xDE00), True)
            )
            self.assertEqual(text, chr(0x1F600))

        def test_halves_split_between_reads(self) -> None:
            """Halves split between reads."""
            held: list[int] = []
            first = make_records((KEY_EVENT, "a", True), (KEY_EVENT, chr(0xD83D), True))
            second = make_records(
                (KEY_EVENT, chr(0xDE00), True), (KEY_EVENT, "b", True)
            )
            for records, expected in ((first, "a"), (second, chr(0x1F600) + "b")):
                array = (INPUT_RECORD * 2)(*records)
                self.assertEqual(records_to_text(array, 2, held), (expected, False))
            self.assertEqual(held, [])

        def test_repeat_count(self) -> None:
            """A held key's repeat count is honoured."""
            records = make_records((KEY_EVENT, "x", True))
            records[0].Event.KeyEvent.wRepeatCount = 3
            array = (INPUT_RECORD * 1)(*records)
            self.assertEqual(records_to_text(array, 1), ("xxx", False))

        def test_space_release_is_reported(self) -> None:
            """A Space release is reported."""
            records = make_records(
                (KEY_EVENT, " ", True), (KEY_EVENT, " ", False), (KEY_EVENT, "x", False)
            )
            records[1].Event.KeyEvent.wVirtualKeyCode = VK_SPACE
            records[2].Event.KeyEvent.wVirtualKeyCode = ord("X")
            array = (INPUT_RECORD * 3)(*records)
            text, _ = records_to_text(array, 3)
            self.assertEqual(text, " " + ansi.SPACE_RELEASED)
            self.assertTrue(WindowsConsole.can_report_key_releases)

    def buffer(
        columns: int, lines: int, window: tuple[int, int, int, int]
    ) -> CONSOLE_SCREEN_BUFFER_INFO:
        """A screen buffer's info.

        :param columns: Buffer width.
        :param lines: Buffer height.
        :param window: Window (left, top, right, bottom).
        """
        return CONSOLE_SCREEN_BUFFER_INFO(
            dwSize=COORD(columns, lines), srWindow=SMALL_RECT(*window)
        )

    class OutgrownWindowTests(unittest.TestCase):
        """Noticing an outgrown window."""

        def setUp(self) -> None:
            self.console = WindowsConsole()
            # pylint: disable-next=protected-access
            waiting = patch.object(self.console, "_wait", return_value=True)
            waiting.start()
            self.addCleanup(waiting.stop)

        def read_resize(self, info: "CONSOLE_SCREEN_BUFFER_INFO | OSError") -> str:
            """Read one resize event.

            :param info: Buffer info, or an error.
            """

            def one_resize(
                _handle: int, records: "ctypes.Array[INPUT_RECORD]", *args: Any
            ) -> int:
                records[0] = make_records((WINDOW_BUFFER_SIZE_EVENT, "\0", False))[0]
                # pylint: disable-next=protected-access
                args[-1]._obj.value = 1  # the count, passed by reference
                return 1

            with (
                patch.object(_windows, "_ReadConsoleInputW", one_resize),
                patch.object(_windows, "buffer_info", side_effect=[info]),
            ):
                return self.console.read(0)

        def test_restored_window_is_reported(self) -> None:
            """A restored window is reported."""
            self.assertEqual(self.read_resize(buffer(213, 63, (0, 35, 117, 62))), "")
            self.assertTrue(self.console.is_woken)
            self.assertTrue(self.console.has_outgrown_window)

        def test_fitting_buffer_is_not_reported(self) -> None:
            """Maximising: the buffer grows with the window."""
            self.read_resize(buffer(213, 63, (0, 0, 212, 62)))
            self.assertTrue(self.console.is_woken)
            self.assertFalse(self.console.has_outgrown_window)

        def test_unknown_buffer_is_not_reported(self) -> None:
            """If the console cannot say, the screen is left as it is."""
            self.read_resize(OSError("no console"))
            self.assertFalse(self.console.has_outgrown_window)

        def test_refit_fits_the_main_buffer_and_clears_the_report(self) -> None:
            """Refit fits the main buffer."""
            self.read_resize(buffer(213, 63, (0, 35, 117, 62)))
            # pylint: disable-next=protected-access
            hider = self.console._scroll_bars
            with patch.object(hider, "refit", side_effect=OSError) as refit:
                self.console.refit()
            refit.assert_called_once_with()
            self.assertFalse(self.console.has_outgrown_window)


if __name__ == "__main__":
    unittest.main()
