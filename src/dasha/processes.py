"""Ending an application's process reliably, together with any processes it
started, however the desktop itself ends.

On Windows, each application is placed in a job object of its own, set to
end everything in it when the job is closed. ``kill`` ends the whole job,
and if the desktop dies without tidying up, Windows closes the job, which
ends its applications too. (On Windows, a virtual environment's
``python.exe`` starts the real Python as a child process, so ending only
the first process would not be enough.) On other systems, each application
leads a process group of its own (``start_new_session``), and ``kill`` ends
the group; each application also watches for its desktop going away
(``watch_parent``).
"""

import ctypes
import os
import signal
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

_CREATE_SUSPENDED = 0x4
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class _BasicLimits(ctypes.Structure):  # pylint: disable=too-few-public-methods
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):  # pylint: disable=too-few-public-methods
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _Accounting(ctypes.Structure):  # pylint: disable=too-few-public-methods
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _ExtendedLimits(ctypes.Structure):  # pylint: disable=too-few-public-methods
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32() -> Any:
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel32


class ProcessTree:
    """An application's process and any processes it starts, which are ended
    together."""

    def __init__(
        self, process: "subprocess.Popen[bytes]", job: int | None = None
    ) -> None:
        self.process = process
        self._job = job

    @classmethod
    def start(cls, command: list[str], **options: Any) -> "ProcessTree":
        """Start a process, given ``subprocess.Popen`` arguments. On Windows,
        it starts suspended, joins its job, and only then runs, so that
        nothing it starts can escape the job. On other systems, it leads a
        new process group."""
        # if/else (not an early return) lets mypy skip the other platform's branch.
        if sys.platform != "win32":  # pylint: disable=no-else-return
            options["start_new_session"] = True
            # pylint: disable-next=consider-using-with
            return cls(subprocess.Popen(command, **options))
        else:
            return cls._start_in_job(command, options)

    @classmethod
    def _start_in_job(
        cls, command: list[str], options: dict[str, Any]
    ) -> "ProcessTree":
        """Windows: start the process suspended, put it in a job of its own,
        then let it run."""
        flags = int(options.pop("creationflags", 0))
        process = subprocess.Popen(  # pylint: disable=consider-using-with
            command, creationflags=flags | _CREATE_SUSPENDED, **options
        )
        job = cls._make_job(process)
        try:
            ntdll = getattr(ctypes, "WinDLL")("ntdll")
            ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
            ntdll.NtResumeProcess(int(getattr(process, "_handle")))
        except (OSError, AttributeError):
            process.kill()
            raise
        return cls(process, job)

    @staticmethod
    def _make_job(process: "subprocess.Popen[bytes]") -> int | None:
        """A job that holds the process, and ends everything in it when it
        is closed; ``None`` if Windows will not make one."""
        try:
            kernel32 = _kernel32()
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                return None
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = (
                _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            set_up = kernel32.SetInformationJobObject(
                job,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            )
            handle = int(getattr(process, "_handle"))
            if not set_up or not kernel32.AssignProcessToJobObject(job, handle):
                kernel32.CloseHandle(job)
                return None
            return int(job)
        except (OSError, AttributeError):
            return None

    def kill(self) -> None:
        """End the process and everything it started, immediately."""
        process = self.process
        if self._job is not None:
            _kernel32().TerminateJobObject(self._job, 1)
            self._wait_for_job(2.0)
        elif sys.platform != "win32":
            try:
                os.killpg(process.pid, signal.SIGKILL)  # pylint: disable=no-member
            except OSError:
                pass  # gone already
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass

    def _wait_for_job(self, seconds: float) -> None:
        """Wait (a little) until nothing in the job is running, so ended
        means ended: files let go of, and so on."""
        kernel32 = _kernel32()
        accounting = _Accounting()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            known = kernel32.QueryInformationJobObject(
                self._job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
            )
            if not known or accounting.ActiveProcesses == 0:
                return
            time.sleep(0.01)

    def close(self) -> None:
        """Release the job, which ends anything still running in it."""
        if self._job is not None:
            _kernel32().CloseHandle(self._job)
            self._job = None


DESKTOP_PID_VARIABLE = "DASHA_DESKTOP_PID"
"""The environment variable that gives an application its desktop's
process id, so that it can tell if the desktop ended before it started
watching."""


_SZOMB = 5
"""``p_stat`` of a macOS process that has ended but is waiting to be
reaped."""


def _macos_running(pid: int) -> bool | None:
    """On macOS, whether a process is running, from its ``kinfo_proc``
    (``sysctl`` with ``KERN_PROC_PID``, as ``ps`` reads it): ``False`` if
    it is gone or a zombie, and ``None`` if it cannot be told."""
    sysctl = ctypes.CDLL(None, use_errno=True).sysctl
    sysctl.argtypes = [
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    mib = (ctypes.c_int * 4)(1, 14, 1, pid)  # CTL_KERN, KERN_PROC, KERN_PROC_PID
    info = ctypes.create_string_buffer(1024)  # a kinfo_proc is 648 bytes
    size = ctypes.c_size_t(len(info))
    if sysctl(mib, 4, info, ctypes.byref(size), None, 0) != 0:
        return None
    if size.value == 0:
        return False  # no such process
    # kinfo_proc starts with extern_proc: a union of two pointers, two more
    # pointers, the int p_flag, then the char p_stat.
    offset = 4 * ctypes.sizeof(ctypes.c_void_p) + ctypes.sizeof(ctypes.c_int)
    return info.raw[offset] != _SZOMB


def is_alive(pid: int) -> bool:
    """Whether a process is running (neither ended, nor merely waiting to
    be reaped). Not available on Windows."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text("ascii").rsplit(")", 1)[1].split()
        return state[0] not in ("Z", "X")
    except (OSError, IndexError):
        pass  # no /proc (macOS), or gone
    if sys.platform == "darwin":  # a zombie answers os.kill too
        running = _macos_running(pid)
        if running is not None:
            return running
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # someone else's, but there
    return True


def watch_parent(parent: int | None = None, interval: float = 1.0) -> None:
    """End this process once ``parent`` (the desktop; by default, the
    process that started this one) has gone, because a hung application
    could not notice for itself that its desktop had gone. Ends immediately
    if the parent has already gone. It watches that process itself rather
    than this process's parent, because in a one-file build of dasha there is
    a launcher process between the two. (On Windows, applications end with
    their desktop's job instead.)"""
    if os.name == "nt":
        return
    if parent is None:
        parent = os.getppid()
    watched = parent

    def watch() -> None:
        while is_alive(watched):
            time.sleep(interval)
        os._exit(1)  # pylint: disable=protected-access

    threading.Thread(target=watch, daemon=True, name="dasha-watch-parent").start()
