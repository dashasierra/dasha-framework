"""Tests for ``dasha.processes`` with system calls stubbed."""

import ctypes
import os
import signal
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from dasha import processes
from dasha.processes import ProcessTree, is_alive, watch_parent


def fake_process(*, running: bool = True, hangs: bool = False) -> mock.Mock:
    """A stand-in ``subprocess.Popen``.

    :param running: Whether it is running.
    :param hangs: Whether it ignores termination.
    """
    process = mock.Mock(pid=4242, _handle=99)
    process.poll.return_value = None if running else 0
    if hangs:
        process.wait.side_effect = subprocess.TimeoutExpired("app", 2)
    return process


class StartTests(unittest.TestCase):
    """Starting a process tree."""

    def test_elsewhere_a_new_session(self) -> None:
        """Not on Windows: a process group of its own, and no job."""
        process = fake_process()
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(subprocess, "Popen", return_value=process) as popen,
        ):
            tree = ProcessTree.start(["app"], stdin=1)
        popen.assert_called_once_with(["app"], stdin=1, start_new_session=True)
        self.assertIs(tree.process, process)

    def test_windows_resume_fails(self) -> None:
        """A failed resume on Windows kills the process."""
        process = fake_process()
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(subprocess, "Popen", return_value=process),
            mock.patch.object(ProcessTree, "_make_job", return_value=None),
            mock.patch.object(ctypes, "WinDLL", side_effect=OSError, create=True),
        ):
            with self.assertRaises(OSError):
                ProcessTree.start(["app"], creationflags=8)
        process.kill.assert_called_once_with()


class JobTests(unittest.TestCase):
    """Making a Windows job, when Windows will not."""

    def make_job(self, kernel32: mock.Mock) -> int | None:
        """``_make_job`` with a kernel32 stand-in.

        :param kernel32: The stand-in.
        """
        with mock.patch.object(processes, "_kernel32", return_value=kernel32):
            # pylint: disable-next=protected-access
            return ProcessTree._make_job(fake_process())

    def test_no_job(self) -> None:
        """CreateJobObjectW fails: no job."""
        kernel32 = mock.Mock()
        kernel32.CreateJobObjectW.return_value = 0
        self.assertIsNone(self.make_job(kernel32))

    def test_cannot_assign(self) -> None:
        """The process cannot join it: the job is let go of."""
        kernel32 = mock.Mock()
        kernel32.CreateJobObjectW.return_value = 7
        kernel32.SetInformationJobObject.return_value = 1
        kernel32.AssignProcessToJobObject.return_value = 0
        self.assertIsNone(self.make_job(kernel32))
        kernel32.CloseHandle.assert_called_once_with(7)

    def test_made(self) -> None:
        """Everything works: the job's handle."""
        kernel32 = mock.Mock()
        kernel32.CreateJobObjectW.return_value = 7
        self.assertEqual(self.make_job(kernel32), 7)

    def test_no_kernel32(self) -> None:
        """No Windows at all: no job."""
        with mock.patch.object(processes, "_kernel32", side_effect=OSError):
            # pylint: disable-next=protected-access
            self.assertIsNone(ProcessTree._make_job(fake_process()))


class KillTests(unittest.TestCase):
    """Ending a process tree."""

    def test_with_a_job(self) -> None:
        """The job is ended, then waited for; closing it lets it go."""
        kernel32 = mock.Mock()
        kernel32.QueryInformationJobObject.return_value = 0  # nothing to say
        process = fake_process(running=False)
        tree = ProcessTree(process, job=7)
        with mock.patch.object(processes, "_kernel32", return_value=kernel32):
            tree.kill()
            tree.close()
            tree.close()  # once only
        kernel32.TerminateJobObject.assert_called_once_with(7, 1)
        kernel32.CloseHandle.assert_called_once_with(7)
        process.kill.assert_not_called()

    def test_waiting_for_the_job(self) -> None:
        """While processes in the job still run, it waits (a little)."""

        def query(job: int, kind: int, info: object, size: int, _: None) -> int:
            """Report one process still in the job.

            :param job: Job handle.
            :param kind: Query kind.
            :param info: Output structure.
            :param size: Its size.
            :param _: Unused.
            """
            del job, kind, size
            getattr(info, "_obj").ActiveProcesses = 1  # what byref points at
            return 1

        kernel32 = mock.Mock()
        kernel32.QueryInformationJobObject.side_effect = query
        tree = ProcessTree(fake_process(), job=7)
        with (
            mock.patch.object(processes, "_kernel32", return_value=kernel32),
            mock.patch.object(time, "sleep") as sleep,
        ):
            tree._wait_for_job(0.05)  # pylint: disable=protected-access
        self.assertTrue(sleep.called)

    def test_elsewhere_its_group(self) -> None:
        """Elsewhere, the group is killed."""
        process = fake_process(hangs=True)
        tree = ProcessTree(process)
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(os, "killpg", create=True) as killpg,
            mock.patch.object(signal, "SIGKILL", 9, create=True),
        ):
            tree.kill()
        killpg.assert_called_once_with(4242, 9)
        process.kill.assert_called_once_with()

    def test_group_gone_already(self) -> None:
        """A group that has gone already is fine."""
        process = fake_process(running=False)
        tree = ProcessTree(process)
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(
                os, "killpg", side_effect=ProcessLookupError, create=True
            ),
            mock.patch.object(signal, "SIGKILL", 9, create=True),
        ):
            tree.kill()
        process.kill.assert_not_called()


class AliveTests(unittest.TestCase):
    """Whether a process is running, from /proc or by asking."""

    def test_from_proc(self) -> None:
        """Running, or a zombie (not reaped yet: gone all the same)."""
        with mock.patch.object(Path, "read_text", return_value="12 (py (x)) S 1"):
            self.assertTrue(is_alive(12))
        with mock.patch.object(Path, "read_text", return_value="12 (py) Z 1"):
            self.assertFalse(is_alive(12))

    def test_by_asking(self) -> None:
        """No /proc, and nothing better: os.kill with signal 0 says."""
        with (
            mock.patch.object(Path, "read_text", side_effect=OSError),
            mock.patch.object(processes, "_macos_running", return_value=None),
            mock.patch.object(os, "kill") as kill,
        ):
            self.assertTrue(is_alive(12))
            kill.side_effect = ProcessLookupError
            self.assertFalse(is_alive(12))
            kill.side_effect = PermissionError  # someone else's
            self.assertTrue(is_alive(12))
        kill.assert_called_with(12, 0)

    def test_on_macos(self) -> None:
        """On macOS, the kernel record decides."""
        with (
            mock.patch.object(Path, "read_text", side_effect=OSError),
            mock.patch.object(sys, "platform", "darwin"),
            mock.patch.object(processes, "_macos_running") as running,
            mock.patch.object(os, "kill") as kill,
        ):
            running.return_value = False  # a zombie, or gone
            self.assertFalse(is_alive(12))
            kill.assert_not_called()
            running.return_value = True
            self.assertTrue(is_alive(12))
            running.return_value = None  # cannot be told
            self.assertTrue(is_alive(12))
            kill.assert_called_once_with(12, 0)

    @unittest.skipUnless(sys.platform == "darwin", "sysctl's kinfo_proc is macOS's")
    def test_macos_kernel_record(self) -> None:
        """The real macOS kernel record."""
        # pylint: disable=protected-access
        self.assertTrue(processes._macos_running(os.getpid()))
        # pylint: disable-next=consider-using-with
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        deadline = time.monotonic() + 30
        while processes._macos_running(child.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(processes._macos_running(child.pid))  # a zombie
        child.wait()
        self.assertFalse(processes._macos_running(child.pid))  # gone


class WatchParentTests(unittest.TestCase):
    """Ending once the desktop has gone."""

    def setUp(self) -> None:
        self.watched: int | None = None  # the process id watched

    def watch(self, parent: int | None, lives: list[bool]) -> mock.Mock:
        """Watch with scripted liveness; return ``os._exit``.

        :param parent: Desktop process id, if any.
        :param lives: Liveness at each check.
        """
        with (
            mock.patch.object(os, "name", "posix"),
            mock.patch.object(os, "getppid", return_value=77),
            mock.patch.object(processes, "is_alive", side_effect=lives) as looked,
            mock.patch.object(time, "sleep"),
            mock.patch.object(os, "_exit") as exit_,
            mock.patch.object(threading, "Thread") as thread,
        ):
            watch_parent(parent, interval=0)
            target = thread.call_args.kwargs["target"]
            target()
        self.watched = looked.call_args.args[0]
        return exit_

    def test_ends_when_the_desktop_goes(self) -> None:
        """Alive, alive, gone: this process ends, with 1."""
        exit_ = self.watch(5, [True, True, False])
        exit_.assert_called_once_with(1)
        self.assertEqual(self.watched, 5)

    def test_its_parent_by_default(self) -> None:
        """With no desktop given, the process that started this one."""
        self.watch(None, [False])
        self.assertEqual(self.watched, 77)

    def test_not_on_windows(self) -> None:
        """Windows ends applications with their desktop's job instead."""
        with (
            mock.patch.object(os, "name", "nt"),
            mock.patch.object(threading, "Thread") as thread,
        ):
            watch_parent(5)
        thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
