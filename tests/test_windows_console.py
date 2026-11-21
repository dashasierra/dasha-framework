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

    class ConsoleModeTests(unittest.TestCase):
        """Setting the console's modes, and putting them back."""

        def setUp(self) -> None:
            self.console = WindowsConsole()
            # pylint: disable-next=protected-access
            self.hider = self.console._scroll_bars
            self.set_modes: list[tuple[int, int]] = []
            for name, value in (
                ("_get_mode", {"side_effect": [0x0003, 0x01F7]}),
                ("_set_mode", {"side_effect": self.record_mode}),
            ):
                patcher = patch.object(_windows, name, **value)
                patcher.start()
                self.addCleanup(patcher.stop)

        def record_mode(self, handle: int, mode: int) -> None:
            """Note a mode set.

            :param handle: The console handle.
            :param mode: The mode.
            """
            self.set_modes.append((handle, mode))

        def test_enable_then_restore(self) -> None:
            """Enable turns on VT output and raw input; restore puts both
            back once."""
            with patch.object(self.hider, "hide") as hide:
                self.console.enable()
            hide.assert_called_once_with()
            output_mode = self.set_modes[0][1]
            input_mode = self.set_modes[1][1]
            self.assertEqual(len(self.set_modes), 2)
            self.assertTrue(output_mode & _windows.ENABLE_VIRTUAL_TERMINAL_PROCESSING)
            self.assertTrue(input_mode & _windows.ENABLE_VIRTUAL_TERMINAL_INPUT)
            self.assertFalse(input_mode & _windows.ENABLE_LINE_INPUT)
            self.assertFalse(input_mode & _windows.ENABLE_QUICK_EDIT_MODE)
            self.set_modes.clear()
            with patch.object(self.hider, "restore") as restore:
                self.console.restore()
                self.console.restore()
            self.assertEqual([mode for _, mode in self.set_modes], [0x01F7, 0x0003])
            self.assertEqual(restore.call_count, 2)

        def test_scroll_bar_errors_are_ignored(self) -> None:
            """Scroll bars that cannot be hidden or restored stop nothing."""
            with patch.object(self.hider, "hide", side_effect=OSError):
                self.console.enable()
            with patch.object(self.hider, "restore", side_effect=OSError):
                self.console.restore()
            self.assertEqual(len(self.set_modes), 4)

        def test_console_without_vt_output(self) -> None:
            """A console that cannot take VT output says so, and changes no
            input mode."""
            with patch.object(_windows, "_set_mode", side_effect=OSError):
                with self.assertRaisesRegex(OSError, "ANSI escape sequences"):
                    self.console.enable()
            self.console.restore()
            self.assertEqual(self.set_modes, [])

    class ConsoleCallTests(unittest.TestCase):
        """Failing console calls, waiting and reading."""

        def test_failures_raise(self) -> None:
            """Failed handle and mode calls raise ``OSError``."""
            # pylint: disable=protected-access
            with patch.object(
                _windows, "_GetStdHandle", return_value=_windows.INVALID_HANDLE_VALUE
            ):
                with self.assertRaises(OSError):
                    _windows._std_handle(_windows.STD_INPUT_HANDLE)
            with patch.object(_windows, "_GetConsoleMode", return_value=0):
                with self.assertRaises(OSError):
                    _windows._get_mode(0)
            with patch.object(_windows, "_SetConsoleMode", return_value=0):
                with self.assertRaises(OSError):
                    _windows._set_mode(0, 0)

        def test_wait_results(self) -> None:
            """Input, a timeout, a wake and a failure."""
            console = WindowsConsole()
            results = [
                _windows.WAIT_OBJECT_0,
                _windows.WAIT_TIMEOUT,
                _windows.WAIT_OBJECT_0 + 1,
                0xFFFFFFFF,
            ]
            with patch.object(
                _windows, "_WaitForMultipleObjects", side_effect=results
            ) as wait:
                # pylint: disable=protected-access
                self.assertTrue(console._wait(None))
                self.assertFalse(console._wait(0))
                self.assertFalse(console.is_woken)
                self.assertFalse(console._wait(0))
                self.assertTrue(console.is_woken)
                with self.assertRaises(OSError):
                    console._wait(0)
            self.assertEqual(wait.call_args_list[0].args[3], _windows.INFINITE)
            self.assertEqual(wait.call_args_list[1].args[3], 0)

        def test_wake_sets_the_event(self) -> None:
            """Wake signals the event a read waits on; failing to make one
            raises ``OSError``."""
            # pylint: disable=protected-access
            console = WindowsConsole()
            console.wake()
            handles = (ctypes.wintypes.HANDLE * 1)(console._wake_event)
            waited = _windows._WaitForMultipleObjects(1, handles, False, 0)
            self.assertEqual(waited, _windows.WAIT_OBJECT_0)
            with patch.object(_windows, "_CreateEventW", return_value=None):
                with self.assertRaises(OSError):
                    WindowsConsole()

        def test_other_records_are_skipped(self) -> None:
            """Focus and menu records give no text."""
            records = make_records((0x0010, "\0", False), (KEY_EVENT, "a", True))
            array = (INPUT_RECORD * 2)(*records)
            self.assertEqual(records_to_text(array, 2), ("a", False))

        def test_failed_read_raises(self) -> None:
            """A failed read raises ``OSError``."""
            console = WindowsConsole()
            with (
                patch.object(console, "_wait", return_value=True),
                patch.object(_windows, "_ReadConsoleInputW", return_value=0),
            ):
                with self.assertRaises(OSError):
                    console.read(0)

        def test_releases_alone_keep_waiting(self) -> None:
            """Records with no text and no resize are read past."""

            def one_release(
                _handle: int, records: "ctypes.Array[INPUT_RECORD]", *args: Any
            ) -> int:
                records[0] = make_records((KEY_EVENT, "a", False))[0]
                # pylint: disable-next=protected-access
                args[-1]._obj.value = 1  # the count, passed by reference
                return 1

            console = WindowsConsole()
            with (
                patch.object(console, "_wait", side_effect=[True, False]) as wait,
                patch.object(_windows, "_ReadConsoleInputW", one_release),
            ):
                self.assertEqual(console.read(0), "")
            self.assertEqual(wait.call_count, 2)
            self.assertFalse(console.is_woken)


if __name__ == "__main__":
    unittest.main()
