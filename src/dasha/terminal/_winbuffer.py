"""Hiding the classic Windows console's scroll bars, without losing history.

The classic console (conhost: cmd.exe or PowerShell in their own window)
shows scroll bars whenever its screen buffer is larger than its window, and
the buffer is usually far taller (often 9,001 lines). Making the buffer
exactly the size of the window removes them (``SetConsoleScreenBufferSize``).

Shrinking the buffer throws away every line outside the window, and growing
it again only adds blank lines, so the user's scrollback would be lost.
``ScrollBarHider`` therefore copies the buffer's contents (characters and
colours), the cursor and the window position first, and puts all of them
back on exit.

Windows Terminal, and SSH sessions into Windows, give programs a buffer the
size of the window already, so there is nothing to hide and nothing is done.
"""

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

assert sys.platform == "win32"  # lets mypy skip this module on other platforms

# ReadConsoleOutputW and WriteConsoleOutputW fail for large requests, so
# contents are copied in chunks of about this many cells.
_CELLS_PER_CHUNK = 8000


class COORD(ctypes.Structure):  # pylint: disable=invalid-name
    """A column (X) and row (Y)."""

    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class SMALL_RECT(ctypes.Structure):  # pylint: disable=invalid-name
    """An inclusive rectangle of cells."""

    _fields_ = [
        ("Left", wintypes.SHORT),
        ("Top", wintypes.SHORT),
        ("Right", wintypes.SHORT),
        ("Bottom", wintypes.SHORT),
    ]


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):  # pylint: disable=invalid-name
    """Size, cursor and window position of a screen buffer."""

    _fields_ = [
        ("dwSize", COORD),
        ("dwCursorPosition", COORD),
        ("wAttributes", wintypes.WORD),
        ("srWindow", SMALL_RECT),
        ("dwMaximumWindowSize", COORD),
    ]


class CHAR_INFO(ctypes.Structure):  # pylint: disable=invalid-name
    """One cell: a character and its colours."""

    _fields_ = [("UnicodeChar", wintypes.WCHAR), ("Attributes", wintypes.WORD)]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_GetConsoleScreenBufferInfo = _kernel32.GetConsoleScreenBufferInfo
_GetConsoleScreenBufferInfo.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(CONSOLE_SCREEN_BUFFER_INFO),
]
_GetConsoleScreenBufferInfo.restype = wintypes.BOOL

_SetConsoleScreenBufferSize = _kernel32.SetConsoleScreenBufferSize
_SetConsoleScreenBufferSize.argtypes = [wintypes.HANDLE, COORD]
_SetConsoleScreenBufferSize.restype = wintypes.BOOL

_SetConsoleWindowInfo = _kernel32.SetConsoleWindowInfo
_SetConsoleWindowInfo.argtypes = [
    wintypes.HANDLE,
    wintypes.BOOL,
    ctypes.POINTER(SMALL_RECT),
]
_SetConsoleWindowInfo.restype = wintypes.BOOL

_SetConsoleCursorPosition = _kernel32.SetConsoleCursorPosition
_SetConsoleCursorPosition.argtypes = [wintypes.HANDLE, COORD]
_SetConsoleCursorPosition.restype = wintypes.BOOL

_FillConsoleOutputCharacterW = _kernel32.FillConsoleOutputCharacterW
_FillConsoleOutputCharacterW.argtypes = [
    wintypes.HANDLE,
    wintypes.WCHAR,
    wintypes.DWORD,
    COORD,
    ctypes.POINTER(wintypes.DWORD),
]
_FillConsoleOutputCharacterW.restype = wintypes.BOOL

_FillConsoleOutputAttribute = _kernel32.FillConsoleOutputAttribute
_FillConsoleOutputAttribute.argtypes = [
    wintypes.HANDLE,
    wintypes.WORD,
    wintypes.DWORD,
    COORD,
    ctypes.POINTER(wintypes.DWORD),
]
_FillConsoleOutputAttribute.restype = wintypes.BOOL

_ReadConsoleOutputW = _kernel32.ReadConsoleOutputW
_ReadConsoleOutputW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(CHAR_INFO),
    COORD,
    COORD,
    ctypes.POINTER(SMALL_RECT),
]
_ReadConsoleOutputW.restype = wintypes.BOOL

_WriteConsoleOutputW = _kernel32.WriteConsoleOutputW
_WriteConsoleOutputW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(CHAR_INFO),
    COORD,
    COORD,
    ctypes.POINTER(SMALL_RECT),
]
_WriteConsoleOutputW.restype = wintypes.BOOL


def _check(ok: int) -> None:
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


def buffer_info(handle: int) -> CONSOLE_SCREEN_BUFFER_INFO:
    """The size, cursor and window of a screen buffer."""
    info = CONSOLE_SCREEN_BUFFER_INFO()
    _check(_GetConsoleScreenBufferInfo(handle, ctypes.byref(info)))
    return info


def window_size(info: CONSOLE_SCREEN_BUFFER_INFO) -> tuple[int, int]:
    """The visible window's (columns, lines)."""
    window = info.srWindow
    return window.Right - window.Left + 1, window.Bottom - window.Top + 1


@dataclass
class _Chunk:
    """A band of copied rows."""

    top: int
    rows: int
    cells: "ctypes.Array[CHAR_INFO]"


def _copy_rows(handle: int, width: int, rows: int) -> list[_Chunk]:
    """Copy rows ``0`` to ``rows - 1`` of a buffer ``width`` columns wide."""
    chunk_rows = max(1, _CELLS_PER_CHUNK // max(1, width))
    chunks = []
    for top in range(0, rows, chunk_rows):
        count = min(chunk_rows, rows - top)
        cells = (CHAR_INFO * (width * count))()
        region = SMALL_RECT(0, top, width - 1, top + count - 1)
        _check(
            _ReadConsoleOutputW(
                handle, cells, COORD(width, count), COORD(0, 0), ctypes.byref(region)
            )
        )
        chunks.append(_Chunk(top, count, cells))
    return chunks


def _paste_rows(handle: int, width: int, chunks: list[_Chunk]) -> None:
    """Write copied rows back where they came from."""
    for chunk in chunks:
        region = SMALL_RECT(0, chunk.top, width - 1, chunk.top + chunk.rows - 1)
        _check(
            _WriteConsoleOutputW(
                handle,
                chunk.cells,
                COORD(width, chunk.rows),
                COORD(0, 0),
                ctypes.byref(region),
            )
        )


def _blank(handle: int, cells: int, attributes: int) -> None:
    """Clear the first ``cells`` cells of a buffer to spaces in ``attributes``."""
    written = wintypes.DWORD()
    _check(
        _FillConsoleOutputCharacterW(
            handle, " ", cells, COORD(0, 0), ctypes.byref(written)
        )
    )
    _check(
        _FillConsoleOutputAttribute(
            handle, attributes, cells, COORD(0, 0), ctypes.byref(written)
        )
    )


class ScrollBarHider:
    """Fits a console's screen buffer to its window, then puts it all back."""

    def __init__(self, handle: int) -> None:
        self._handle = handle
        self._saved: tuple[CONSOLE_SCREEN_BUFFER_INFO, list[_Chunk]] | None = None

    @property
    def is_active(self) -> bool:
        """Whether the buffer was changed and will be restored."""
        return self._saved is not None

    def hide(self) -> None:
        """Save the buffer and shrink it to the window, if it is larger."""
        info = buffer_info(self._handle)
        columns, lines = window_size(info)
        if info.dwSize.X <= columns and info.dwSize.Y <= lines:
            return  # no scroll bars (e.g. Windows Terminal): nothing to do
        # Only rows up to the cursor or the window's bottom hold anything.
        used_rows = max(info.dwCursorPosition.Y, info.srWindow.Bottom) + 1
        chunks = _copy_rows(self._handle, info.dwSize.X, used_rows)
        self._saved = (info, chunks)
        self.refit()

    def refit(self) -> None:
        """Shrink the buffer to the window again, after a resize. Only the
        main screen buffer is shrunk this way: the console API acts on the
        alternate screen while it is showing, so it must be left first."""
        if self._saved is None:
            return
        info = buffer_info(self._handle)
        columns, lines = window_size(info)
        if (info.dwSize.X, info.dwSize.Y) != (columns, lines):
            _check(_SetConsoleScreenBufferSize(self._handle, COORD(columns, lines)))

    def restore(self) -> None:
        """Put back the original size, contents, cursor and window position."""
        if self._saved is None:
            return
        info, chunks = self._saved
        self._saved = None
        # The window may have grown past the original size while Dasha Framework
        # ran (maximised, or full screen), and a buffer can never be smaller
        # than its window. Shrinking the window instead would take it out of
        # maximised, so the buffer is made at least as large as the window,
        # as the console grows its own buffer when the window grows.
        columns, lines = window_size(buffer_info(self._handle))
        width = max(info.dwSize.X, columns)
        height = max(info.dwSize.Y, lines)
        _check(_SetConsoleScreenBufferSize(self._handle, COORD(width, height)))
        # The console may have rewrapped what it held when the window grew,
        # leaving text beside or below the rows put back: clear it first.
        _blank(self._handle, width * height, info.wAttributes)
        _paste_rows(self._handle, info.dwSize.X, chunks)
        _check(_SetConsoleCursorPosition(self._handle, info.dwCursorPosition))
        # Show the same lines at the bottom of the window as before. The window
        # keeps its current size, which may have changed while Dasha Framework ran.
        bottom = max(info.srWindow.Bottom, lines - 1)
        window = SMALL_RECT(0, bottom - lines + 1, columns - 1, bottom)
        _check(_SetConsoleWindowInfo(self._handle, True, ctypes.byref(window)))
