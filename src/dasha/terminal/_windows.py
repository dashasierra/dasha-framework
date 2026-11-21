"""Windows console backend."""

import ctypes
import sys
import time
from ctypes import wintypes

assert sys.platform == "win32"  # lets mypy skip this module on other platforms

# After the platform check, so other platforms never import it.
from dasha.terminal import ansi  # pylint: disable=wrong-import-position
from dasha.terminal._winbuffer import (  # pylint: disable=wrong-import-position
    ScrollBarHider,
    buffer_info,
    window_size,
)

STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

# Input mode flags.
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004
# Reports window size changes as input records, so a resize wakes up read().
ENABLE_WINDOW_INPUT = 0x0008
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
# QuickEdit lets the mouse select text in the console window, which would
# swallow clicks meant for Dasha Framework. Changing it requires ENABLE_EXTENDED_FLAGS.
ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080

# Output mode flags.
ENABLE_PROCESSED_OUTPUT = 0x0001
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
# Delays the wrap after writing the last column (as VT terminals do), so filling
# the bottom-right cell does not scroll the whole screen up a line.
DISABLE_NEWLINE_AUTO_RETURN = 0x0008

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_GetStdHandle = _kernel32.GetStdHandle
_GetStdHandle.argtypes = [wintypes.DWORD]
_GetStdHandle.restype = wintypes.HANDLE

_GetConsoleMode = _kernel32.GetConsoleMode
_GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_GetConsoleMode.restype = wintypes.BOOL

_SetConsoleMode = _kernel32.SetConsoleMode
_SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_SetConsoleMode.restype = wintypes.BOOL

VK_SPACE = 0x20
"""The virtual key code of the Space bar."""

# Input record types (INPUT_RECORD.EventType).
KEY_EVENT = 0x0001
WINDOW_BUFFER_SIZE_EVENT = 0x0004


class KEY_EVENT_RECORD(ctypes.Structure):  # pylint: disable=invalid-name
    """A key press or release record."""

    _fields_ = [
        ("bKeyDown", wintypes.BOOL),
        ("wRepeatCount", wintypes.WORD),
        ("wVirtualKeyCode", wintypes.WORD),
        ("wVirtualScanCode", wintypes.WORD),
        ("UnicodeChar", wintypes.WCHAR),
        ("dwControlKeyState", wintypes.DWORD),
    ]


class _EventUnion(ctypes.Union):
    # Only the key event is read; the padding keeps the union 16 bytes, the
    # size of its largest member (MOUSE_EVENT_RECORD), as in the C headers.
    _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("_padding", ctypes.c_byte * 16)]


class INPUT_RECORD(ctypes.Structure):  # pylint: disable=invalid-name
    """One console input event."""

    _fields_ = [("EventType", wintypes.WORD), ("Event", _EventUnion)]


_ReadConsoleInputW = _kernel32.ReadConsoleInputW
_ReadConsoleInputW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(INPUT_RECORD),
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
_ReadConsoleInputW.restype = wintypes.BOOL

_WaitForMultipleObjects = _kernel32.WaitForMultipleObjects
_WaitForMultipleObjects.argtypes = [
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.BOOL,
    wintypes.DWORD,
]
_WaitForMultipleObjects.restype = wintypes.DWORD

_CreateEventW = _kernel32.CreateEventW
_CreateEventW.argtypes = [
    wintypes.LPVOID,
    wintypes.BOOL,
    wintypes.BOOL,
    wintypes.LPCWSTR,
]
_CreateEventW.restype = wintypes.HANDLE

_SetEvent = _kernel32.SetEvent
_SetEvent.argtypes = [wintypes.HANDLE]
_SetEvent.restype = wintypes.BOOL

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
INFINITE = 0xFFFFFFFF

_READ_BUFFER_RECORDS = 256


def _std_handle(which: int) -> int:
    handle = _GetStdHandle(wintypes.DWORD(which & 0xFFFFFFFF))
    if handle is None or handle == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def _get_mode(handle: int) -> int:
    mode = wintypes.DWORD()
    if not _GetConsoleMode(handle, ctypes.byref(mode)):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(mode.value)


def _set_mode(handle: int, mode: int) -> None:
    if not _SetConsoleMode(handle, mode):
        raise ctypes.WinError(ctypes.get_last_error())


def records_to_text(
    records: "ctypes.Array[INPUT_RECORD]",
    count: int,
    held: list[int] | None = None,
) -> tuple[str, bool]:
    """Text from input records, and whether the window resized.

    :param records: The input records.
    :param count: Records to read.
    :param held: Holds a split UTF-16 half between reads, if given.
    """
    units: list[int] = [] if held is None else held[:]
    if held is not None:
        held.clear()
    resized = False
    for record in records[:count]:
        if record.EventType == KEY_EVENT:
            key = record.Event.KeyEvent
            if key.bKeyDown and key.UnicodeChar != "\0":
                units.extend([ord(key.UnicodeChar)] * max(1, key.wRepeatCount))
            elif not key.bKeyDown and key.wVirtualKeyCode == VK_SPACE:
                units.extend(ord(char) for char in ansi.SPACE_RELEASED)
        elif record.EventType == WINDOW_BUFFER_SIZE_EVENT:
            resized = True
    if held is not None and units and 0xD800 <= units[-1] <= 0xDBFF:
        held.append(units.pop())  # the second half is in the next read
    data = b"".join(unit.to_bytes(2, "little") for unit in units)
    return data.decode("utf-16-le", errors="replace"), resized


class WindowsConsole:
    """Puts the attached Windows console into VT mode and raw input mode."""

    can_report_key_releases = True
    """The console's input records say when a key is let go of."""

    def __init__(self) -> None:
        self._input = _std_handle(STD_INPUT_HANDLE)
        self._output = _std_handle(STD_OUTPUT_HANDLE)
        self._saved_input_mode: int | None = None
        self._saved_output_mode: int | None = None
        self._scroll_bars = ScrollBarHider(self._output)
        self._held: list[int] = []  # half a character, until the other half
        # Set by wake, from any thread; reset by the wait it ends. Kept for
        # as long as the console is, so wake never sets a closed handle.
        self._wake_event = _CreateEventW(None, False, False, None)
        if not self._wake_event:
            raise ctypes.WinError(ctypes.get_last_error())
        self.is_woken = False
        """Whether the last ``read`` ended early: woken, or resized."""
        self.has_outgrown_window = False
        """Whether the buffer outgrew the window."""

    def _has_outgrown_window(self) -> bool:
        """Whether the screen buffer is larger than its window."""
        try:
            info = buffer_info(self._output)
        except OSError:
            return False
        return (info.dwSize.X, info.dwSize.Y) != window_size(info)

    def refit(self) -> None:
        """Refit the main screen buffer to the window."""
        self.has_outgrown_window = False
        try:
            self._scroll_bars.refit()
        except OSError:
            pass  # scroll bars showing are better than stopping here

    def enable(self) -> None:
        """Enable ANSI output processing and raw (unechoed) VT input."""
        output_mode = _get_mode(self._output)
        try:
            _set_mode(
                self._output,
                output_mode
                | ENABLE_PROCESSED_OUTPUT
                | ENABLE_VIRTUAL_TERMINAL_PROCESSING
                | DISABLE_NEWLINE_AUTO_RETURN,
            )
        except OSError as error:
            raise OSError(
                "This console does not support ANSI escape sequences "
                "(Windows 10 version 1511 or later is required)."
            ) from error
        self._saved_output_mode = output_mode

        input_mode = _get_mode(self._input)
        _set_mode(
            self._input,
            (
                input_mode
                & ~(
                    ENABLE_PROCESSED_INPUT
                    | ENABLE_LINE_INPUT
                    | ENABLE_ECHO_INPUT
                    | ENABLE_QUICK_EDIT_MODE
                )
            )
            | ENABLE_VIRTUAL_TERMINAL_INPUT
            | ENABLE_WINDOW_INPUT
            | ENABLE_EXTENDED_FLAGS,
        )
        self._saved_input_mode = input_mode

        # Hiding the scroll bars is cosmetic: if it cannot be done, carry on.
        try:
            self._scroll_bars.hide()
        except OSError:
            pass

    def restore(self) -> None:
        """Restore the console as found."""
        try:
            self._scroll_bars.restore()
        except OSError:
            pass  # best effort: never let this stop the modes being restored
        if self._saved_input_mode is not None:
            _set_mode(self._input, self._saved_input_mode)
            self._saved_input_mode = None
        if self._saved_output_mode is not None:
            _set_mode(self._output, self._saved_output_mode)
            self._saved_output_mode = None

    def wake(self) -> None:
        """Make a waiting ``read`` return; thread-safe."""
        _SetEvent(self._wake_event)

    def _wait(self, deadline: float | None) -> bool:
        """Wait for input; ``False`` on timeout or wake.

        :param deadline: When to stop, or ``None`` for never.
        """
        if deadline is None:
            milliseconds = INFINITE
        else:
            milliseconds = max(0, int((deadline - time.monotonic()) * 1000))
        handles = (wintypes.HANDLE * 2)(self._input, self._wake_event)
        result = _WaitForMultipleObjects(2, handles, False, milliseconds)
        if result == WAIT_TIMEOUT:
            return False
        if result == WAIT_OBJECT_0 + 1:
            self.is_woken = True
            return False
        if result != WAIT_OBJECT_0:
            raise ctypes.WinError(ctypes.get_last_error())
        return True

    def read(self, timeout: float | None = None) -> str:
        """Wait for and return input.

        :param timeout: Seconds to wait, or ``None`` for ever.
        """
        self.is_woken = False
        deadline = None if timeout is None else time.monotonic() + timeout
        records = (INPUT_RECORD * _READ_BUFFER_RECORDS)()
        count = wintypes.DWORD()
        while True:
            if not self._wait(deadline):
                return ""
            if not _ReadConsoleInputW(
                self._input, records, _READ_BUFFER_RECORDS, ctypes.byref(count)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            text, resized = records_to_text(records, count.value, self._held)
            if resized:
                self.has_outgrown_window = self._has_outgrown_window()
            if text or resized:
                self.is_woken = resized and not text
                return text
            # Only key releases or focus changes: keep waiting.
