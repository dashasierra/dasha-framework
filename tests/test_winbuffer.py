"""Tests for hiding the classic Windows console's scroll bars.

These use a private, inactive console screen buffer, so they do not disturb
whatever is on screen. They are skipped off Windows, or when the process has
no console (some CI runners).
"""

import ctypes
import sys
import unittest
from ctypes import wintypes

if sys.platform == "win32":
    from dasha.terminal._winbuffer import (
        COORD,
        SMALL_RECT,
        ScrollBarHider,
        buffer_info,
    )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateConsoleScreenBuffer.restype = wintypes.HANDLE
    kernel32.CreateConsoleScreenBuffer.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    kernel32.SetConsoleScreenBufferSize.argtypes = [wintypes.HANDLE, COORD]
    kernel32.WriteConsoleOutputCharacterW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        COORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.ReadConsoleOutputCharacterW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        COORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.SetConsoleCursorPosition.argtypes = [wintypes.HANDLE, COORD]
    kernel32.SetConsoleWindowInfo.argtypes = [
        wintypes.HANDLE,
        wintypes.BOOL,
        ctypes.POINTER(SMALL_RECT),
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    GENERIC_READ_WRITE = 0x80000000 | 0x40000000
    CONSOLE_TEXTMODE_BUFFER = 1
    INVALID_HANDLE = wintypes.HANDLE(-1).value

    class ScrollBarHiderTests(unittest.TestCase):
        """Shrinking to the window and restoring everything afterwards."""

        def setUp(self) -> None:
            handle = kernel32.CreateConsoleScreenBuffer(
                GENERIC_READ_WRITE, 0, None, CONSOLE_TEXTMODE_BUFFER, None
            )
            if handle in (None, INVALID_HANDLE):
                self.skipTest("no console attached to this process")
            self.handle = int(handle)
            self.addCleanup(kernel32.CloseHandle, self.handle)
            # A tall buffer, like a PowerShell window's, with 80 numbered rows:
            # more than one copy chunk (8000 cells is 66 rows at 120 columns).
            if not kernel32.SetConsoleScreenBufferSize(self.handle, COORD(120, 300)):
                self.skipTest("cannot resize a console buffer here")
            # A pseudoconsole (Windows Terminal, say) puts its buffer back to
            # the window's size once the window is set, so it never has scroll
            # bars to hide; these tests are for the classic console.
            window = buffer_info(self.handle).srWindow
            kernel32.SetConsoleWindowInfo(self.handle, True, ctypes.byref(window))
            if buffer_info(self.handle).dwSize.Y != 300:
                self.skipTest("this console fits its buffer to its window")
            for row in range(80):
                self.write_row(row, f"row {row}")
            kernel32.SetConsoleCursorPosition(self.handle, COORD(0, 79))

        def write_row(self, row: int, text: str) -> None:
            """Write text at the start of a row."""
            written = wintypes.DWORD()
            kernel32.WriteConsoleOutputCharacterW(
                self.handle, text, len(text), COORD(0, row), ctypes.byref(written)
            )

        def read_row(self, row: int) -> str:
            """The first characters of a row."""
            buffer = ctypes.create_unicode_buffer(10)
            read = wintypes.DWORD()
            kernel32.ReadConsoleOutputCharacterW(
                self.handle, buffer, 10, COORD(0, row), ctypes.byref(read)
            )
            return ctypes.wstring_at(buffer, read.value).rstrip()

        def test_hide_shrinks_and_restore_brings_everything_back(self) -> None:
            """The buffer fits the window while hidden; history survives."""
            before = buffer_info(self.handle)
            hider = ScrollBarHider(self.handle)
            hider.hide()
            self.assertTrue(hider.is_active)
            during = buffer_info(self.handle)
            window = during.srWindow
            self.assertEqual(
                (during.dwSize.X, during.dwSize.Y),
                (window.Right - window.Left + 1, window.Bottom - window.Top + 1),
            )
            hider.restore()
            self.assertFalse(hider.is_active)
            after = buffer_info(self.handle)
            self.assertEqual((after.dwSize.X, after.dwSize.Y), (120, 300))
            self.assertEqual(after.dwCursorPosition.Y, before.dwCursorPosition.Y)
            for row in (0, 1, 65, 66, 67, 79):
                self.assertEqual(self.read_row(row), f"row {row}")
            self.assertEqual(self.read_row(80), "")

        def set_window(self, columns: int, lines: int, bottom: int) -> None:
            """Show the buffer's left in a window of this size, down to a row."""
            window = SMALL_RECT(0, bottom - lines + 1, columns - 1, bottom)
            if not kernel32.SetConsoleWindowInfo(
                self.handle, True, ctypes.byref(window)
            ):
                self.skipTest(f"cannot make a {columns}x{lines} console window")

        def test_restore_while_the_window_is_larger(self) -> None:
            """Maximised since hiding: the window stays, history comes back.

            The window, now wider than the original buffer, cannot shrink
            without leaving maximised, so the buffer takes its width.
            """
            self.set_window(40, 20, 19)
            # A pseudoconsole (Windows Terminal, say) keeps its buffer's width.
            if not kernel32.SetConsoleScreenBufferSize(self.handle, COORD(60, 300)):
                self.skipTest("cannot change a console buffer's width here")
            hider = ScrollBarHider(self.handle)
            hider.hide()
            # Maximising grows the main buffer along with the window.
            kernel32.SetConsoleScreenBufferSize(self.handle, COORD(80, 30))
            self.set_window(80, 30, 29)
            written = wintypes.DWORD()
            kernel32.WriteConsoleOutputCharacterW(
                self.handle, "rewrapped", 9, COORD(60, 1), ctypes.byref(written)
            )
            hider.restore()
            after = buffer_info(self.handle)
            self.assertEqual((after.dwSize.X, after.dwSize.Y), (80, 300))
            self.assertEqual(after.dwCursorPosition.Y, 79)
            window = after.srWindow
            self.assertEqual(
                (window.Left, window.Top, window.Right, window.Bottom),
                (0, 0, 79, 29),
            )
            for row in (0, 1, 65, 66, 67, 79):
                self.assertEqual(self.read_row(row), f"row {row}")
            buffer = ctypes.create_unicode_buffer(9)
            kernel32.ReadConsoleOutputCharacterW(
                self.handle, buffer, 9, COORD(60, 1), ctypes.byref(written)
            )
            self.assertEqual(buffer.value.strip(), "")

        def test_buffer_that_fits_is_left_alone(self) -> None:
            """No scroll bars to hide: nothing is saved or changed."""
            info = buffer_info(self.handle)
            window = info.srWindow
            fitted = COORD(
                window.Right - window.Left + 1, window.Bottom - window.Top + 1
            )
            kernel32.SetConsoleScreenBufferSize(self.handle, fitted)
            hider = ScrollBarHider(self.handle)
            hider.hide()
            self.assertFalse(hider.is_active)
            hider.restore()  # harmless


if __name__ == "__main__":
    unittest.main()
