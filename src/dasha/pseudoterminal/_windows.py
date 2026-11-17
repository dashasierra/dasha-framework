"""The Windows pseudo-terminal: a pseudoconsole (ConPTY), through ctypes,
which needs Windows 10 version 1809 or later."""

import ctypes
import os
import subprocess
import sys
import threading
from collections.abc import Mapping
from ctypes import wintypes

assert sys.platform == "win32"  # lets mypy skip this module on other platforms

# After the platform check, so other platforms never import it.
# pylint: disable-next=wrong-import-position
from dasha.pseudoterminal.base import READ_SIZE, PseudoTerminal, find_program

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _Coord(ctypes.Structure):  # pylint: disable=too-few-public-methods
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class _StartupInfo(ctypes.Structure):  # pylint: disable=too-few-public-methods
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):  # pylint: disable=too-few-public-methods
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", ctypes.c_void_p)]


class _ProcessInformation(ctypes.Structure):  # pylint: disable=too-few-public-methods
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _function(
    name: str, argtypes: list[object], restype: object = wintypes.BOOL
) -> "ctypes._NamedFuncPointer":
    found = getattr(_kernel32, name)
    found.argtypes = argtypes
    found.restype = restype
    return found  # type: ignore[no-any-return]


_HANDLE_P = ctypes.POINTER(wintypes.HANDLE)
_CreatePipe = _function(
    "CreatePipe", [_HANDLE_P, _HANDLE_P, ctypes.c_void_p, wintypes.DWORD]
)
_CloseHandle = _function("CloseHandle", [wintypes.HANDLE])
_ReadFile = _function(
    "ReadFile",
    [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ],
)
_WriteFile = _function(
    "WriteFile",
    [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ],
)
_InitializeProcThreadAttributeList = _function(
    "InitializeProcThreadAttributeList",
    [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ],
)
_UpdateProcThreadAttribute = _function(
    "UpdateProcThreadAttribute",
    [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ],
)
_DeleteProcThreadAttributeList = _function(
    "DeleteProcThreadAttributeList", [ctypes.c_void_p], None
)
_CreateProcessW = _function(
    "CreateProcessW",
    [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfoEx),
        ctypes.POINTER(_ProcessInformation),
    ],
)
_WaitForSingleObject = _function(
    "WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD
)
_GetExitCodeProcess = _function(
    "GetExitCodeProcess", [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
)
_TerminateProcess = _function("TerminateProcess", [wintypes.HANDLE, wintypes.UINT])

try:
    _CreatePseudoConsole = _function(
        "CreatePseudoConsole",
        [_Coord, wintypes.HANDLE, wintypes.HANDLE, wintypes.DWORD, _HANDLE_P],
        ctypes.c_long,
    )
    _ResizePseudoConsole = _function(
        "ResizePseudoConsole", [wintypes.HANDLE, _Coord], ctypes.c_long
    )
    _ClosePseudoConsole = _function("ClosePseudoConsole", [wintypes.HANDLE], None)
    HAS_CONPTY = True
    """Whether this Windows has pseudoconsoles (1809 or later)."""
except AttributeError:
    HAS_CONPTY = False

_PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_STARTF_USESTDHANDLES = 0x00000100
_INFINITE = 0xFFFFFFFF
_ERROR_BROKEN_PIPE = 109


def _check(succeeded: object) -> None:
    if not succeeded:
        raise ctypes.WinError(ctypes.get_last_error())


def _environment_block(env: Mapping[str, str]) -> ctypes.Array[ctypes.c_wchar]:
    """An environment as CreateProcessW wants it: ``NAME=value`` for
    each, sorted, each ended by a NUL, then one more."""
    entries = sorted(env.items(), key=lambda item: item[0].upper())
    text = "".join(f"{name}={value}\0" for name, value in entries) + "\0"
    return ctypes.create_unicode_buffer(text, len(text))


class WindowsConPty(PseudoTerminal):  # pylint: disable=too-many-instance-attributes
    """A pseudo-terminal on Windows: a pseudoconsole (ConPTY), which
    turns what console programs do into terminal output, and terminal
    input into what they read. Needs Windows 10 version 1809 or
    later."""

    def __init__(self) -> None:
        super().__init__()
        self._console: int | None = None
        self._process: int | None = None
        self._input: int | None = None
        self._output: int | None = None
        self._waiter: threading.Thread | None = None

    def _spawn(
        self,
        argv: list[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        size: tuple[int, int],
    ) -> None:
        if not HAS_CONPTY:
            raise OSError("The terminal needs Windows 10 version 1809 or later.")
        find_program(argv, env)
        if cwd is not None and not os.path.isdir(cwd):
            raise NotADirectoryError(20, "Not a folder", cwd)
        # Ours: what we write, and what we read. Its: the other ends.
        its_input, our_input = wintypes.HANDLE(), wintypes.HANDLE()
        our_output, its_output = wintypes.HANDLE(), wintypes.HANDLE()
        _check(_CreatePipe(ctypes.byref(its_input), ctypes.byref(our_input), None, 0))
        _check(_CreatePipe(ctypes.byref(our_output), ctypes.byref(its_output), None, 0))
        self._input, self._output = our_input.value, our_output.value
        console = wintypes.HANDLE()
        try:
            result = _CreatePseudoConsole(
                _Coord(size[0], size[1]),
                its_input,
                its_output,
                0,
                ctypes.byref(console),
            )
            if result < 0:
                raise OSError(
                    f"Cannot make a pseudoconsole (error {result & 0xFFFFFFFF:#x})"
                )
            self._console = console.value
            self._create_process(argv, cwd, env)
        except BaseException:
            self._close_everything()
            raise
        finally:
            # The pseudoconsole has its own copies of these.
            _CloseHandle(its_input)
            _CloseHandle(its_output)
        self._waiter = threading.Thread(target=self._wait_for_end, daemon=True)
        self._waiter.start()

    def _create_process(
        self, argv: list[str], cwd: str | None, env: Mapping[str, str] | None
    ) -> None:
        size = ctypes.c_size_t()
        _InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attributes = ctypes.create_string_buffer(size.value)
        _check(_InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)))
        try:
            _check(
                _UpdateProcThreadAttribute(
                    attributes,
                    0,
                    _PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                    self._console,
                    ctypes.sizeof(wintypes.HANDLE),
                    None,
                    None,
                )
            )
            startup = _StartupInfoEx(
                StartupInfo=_StartupInfo(
                    cb=ctypes.sizeof(_StartupInfoEx),
                    # Without this, a child of a process whose own
                    # standard handles are redirected (as an
                    # application's are, run by the desktop) would
                    # write to those, not to the pseudoconsole.
                    dwFlags=_STARTF_USESTDHANDLES,
                ),
                lpAttributeList=ctypes.cast(attributes, ctypes.c_void_p),
            )
            information = _ProcessInformation()
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            block = None if env is None else _environment_block(env)
            _check(
                _CreateProcessW(
                    None,
                    command,
                    None,
                    None,
                    False,
                    _EXTENDED_STARTUPINFO_PRESENT | _CREATE_UNICODE_ENVIRONMENT,
                    block,
                    cwd,
                    ctypes.byref(startup),
                    ctypes.byref(information),
                )
            )
        finally:
            _DeleteProcThreadAttributeList(attributes)
        _CloseHandle(information.hThread)
        self._process = information.hProcess
        self.pid = information.dwProcessId

    def _wait_for_end(self) -> None:
        """The waiting thread: once the program ends, close the
        pseudoconsole, which ends its output (and the reading thread's
        wait for more)."""
        assert self._process is not None
        _WaitForSingleObject(self._process, _INFINITE)
        code = wintypes.DWORD()
        if _GetExitCodeProcess(self._process, ctypes.byref(code)):
            self.exit_code = code.value
        # The reading thread carries on reading meanwhile: on some
        # versions of Windows this waits for the output to be read.
        with self._lock:
            console, self._console = self._console, None
        if console is not None:
            _ClosePseudoConsole(console)

    def _read(self) -> bytes:
        assert self._output is not None
        buffer = ctypes.create_string_buffer(READ_SIZE)
        count = wintypes.DWORD()
        if not _ReadFile(self._output, buffer, READ_SIZE, ctypes.byref(count), None):
            error = ctypes.get_last_error()
            if error == _ERROR_BROKEN_PIPE:
                return b""
            raise ctypes.WinError(error)
        return buffer.raw[: count.value]

    def _write(self, data: bytes) -> None:
        assert self._input is not None
        written = wintypes.DWORD()
        while data:
            _check(
                _WriteFile(self._input, data, len(data), ctypes.byref(written), None)
            )
            data = data[written.value :]

    def _reap(self) -> int | None:
        if self._waiter is not None:
            self._waiter.join()
        return self.exit_code

    def _release(self) -> None:
        self._close_everything()

    def _close_everything(self) -> None:
        console, self._console = self._console, None
        if console is not None:
            _ClosePseudoConsole(console)
        for name in ("_input", "_output", "_process"):
            handle = getattr(self, name)
            if handle is not None:
                _CloseHandle(handle)
                setattr(self, name, None)

    def resize(self, columns: int, lines: int) -> None:
        with self._lock:
            if self._console is not None:
                _ResizePseudoConsole(
                    self._console, _Coord(max(1, columns), max(1, lines))
                )

    def close(self) -> None:
        with self._lock:
            if self._process is not None and self.is_running:
                _TerminateProcess(self._process, 1)
