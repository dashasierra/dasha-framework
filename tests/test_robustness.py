"""Tests for shutting down and staying up."""

import ctypes
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import cast

from dasha.hosting import AppHost, AppServer
from dasha.remote import RemoteWindow
from dasha.manager import PresentationManager
from dasha.processes import ProcessTree
from dasha.processes import is_alive as processes_is_alive
from dasha.terminal import Terminal
from tests.hosted_apps import Hangs, Hello
from tests.support import pipe, tests_importable
from tests.test_application import Scripted, run
from tests.test_hosting import drain
from tests.test_manager import FakeTerminal

ALT_F4 = "\x1b[1;3S"


def is_alive(pid: int) -> bool:
    """Whether a process is running.

    :param pid: Process id.
    """
    if os.name == "nt":
        kernel32 = getattr(ctypes, "WinDLL")("kernel32")
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        state = (
            Path(f"/proc/{pid}/stat").read_text("ascii").rsplit(")", 1)[1].split()[0]
        )
        return state not in ("Z", "X")
    except (OSError, IndexError):
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


def eventually(condition: Callable[[], bool], seconds: float = 30) -> bool:
    """Whether a condition comes true in time.

    :param condition: The condition.
    :param seconds: Time allowed.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


STEP_TIMEOUT = 30.0
"""Seconds a step may take."""


class StepTerminal(FakeTerminal):
    """Runs steps: waits for each condition, then types.

    :param manager: The desktop.
    :param steps: (condition, keys) pairs.
    """

    def __init__(
        self,
        manager: PresentationManager,
        steps: list[tuple[Callable[[], bool], list[str]]],
    ) -> None:
        super().__init__([], sizes=[(80, 24)])
        self.manager = manager
        self.steps = list(steps)
        self.deadline = time.monotonic() + STEP_TIMEOUT
        self.timed_out = False

    def read(self, timeout: float | None = None) -> str:
        """Raise SIGTERM while waiting.

        :param timeout: Ignored.
        """
        if self.inputs:
            return self.inputs.pop(0)
        if time.monotonic() > self.deadline:
            self.timed_out = True
            self.manager.quit()
        elif not self.steps:
            self.manager.quit()
        elif self.steps[0][0]():
            self.inputs.extend(self.steps.pop(0)[1])
            self.deadline = time.monotonic() + STEP_TIMEOUT
        time.sleep(0.02)
        return ""


class Desktop(unittest.TestCase):
    """A desktop running applications in processes, with short timeouts."""

    def setUp(self) -> None:
        # Windows can hold a log a moment after its process ends.
        folder = tempfile.TemporaryDirectory(  # pylint: disable=consider-using-with
            ignore_cleanup_errors=True
        )
        self.addCleanup(folder.cleanup)
        tests_importable(self)
        self.manager = PresentationManager()
        self.manager.use_processes = True
        self.manager.confirm_exit = False
        self.server = AppServer(self.manager)
        self.addCleanup(self.server.stop_all, 0)
        self.server.log_folder = Path(folder.name)
        self.server.ping_interval = 0.1
        self.server.hang_timeout = 0.5
        self.manager.server = self.server

    def titles(self) -> list[str]:
        """The windows' titles, back to front."""
        return [window.title for window in self.manager.windows]

    def run_steps(self, *steps: tuple[Callable[[], bool], list[str]]) -> None:
        """Run the desktop through steps.

        :param steps: (condition, keys) pairs.
        """
        terminal = StepTerminal(self.manager, list(steps))
        self.manager.run(cast(Terminal, terminal))
        self.assertFalse(terminal.timed_out, f"timed out with {self.titles()}")


class HangTests(Desktop):
    """An application that stops responding, in a real process."""

    def test_end_now_from_the_close_button(self) -> None:
        """Hung, it is marked; closing offers to end it; End now does."""
        self.manager.start(Hangs)
        hosts: list[AppHost] = []

        def window_shown() -> bool:
            hosts[:] = list(self.server.hosts)
            return self.titles() == ["Hangs"]

        self.run_steps(
            (window_shown, ["h"]),
            (lambda: self.titles() == ["Hangs (Not responding)"], [ALT_F4]),
            (lambda: "Hangs" in self.titles(), ["e"]),  # the dialog: End now
            (lambda: not self.titles(), []),
        )
        self.assertEqual(len(hosts), 1)
        host = hosts[0]
        assert host.pid is not None
        self.assertTrue(eventually(lambda: not is_alive(cast(int, host.pid))))
        self.assertEqual(self.server.notices, [])  # ended on purpose: no report

    def test_wait_keeps_it(self) -> None:
        """Wait leaves the application running, marked."""
        self.manager.start(Hangs)
        self.run_steps(
            (lambda: self.titles() == ["Hangs"], ["h"]),
            (lambda: self.titles() == ["Hangs (Not responding)"], [ALT_F4]),
            (lambda: "Hangs" in self.titles(), ["w"]),  # Wait
            (lambda: self.titles() == ["Hangs (Not responding)"], []),
        )

    def test_shutting_down_with_a_hung_application(self) -> None:
        """Shutting down with a hung application."""
        self.manager.start(Hello)

        def start_hangs() -> bool:
            self.manager.start(Hangs)
            return True

        self.run_steps(
            (lambda: self.titles() == ["Hello"], []),
            (start_hangs, []),
            (lambda: self.titles() == ["Hello", "Hangs"], ["h"]),
            (lambda: "Hangs (Not responding)" in self.titles(), ["\x11"]),  # Ctrl+Q
            (lambda: "Shutting down" in self.titles(), ["\r"]),  # End now
        )
        self.assertFalse(self.manager.is_running)
        self.assertEqual(self.server.hosts, [])

    def test_cancel_shutting_down(self) -> None:
        """Cancel stops shutting down; the desktop stays."""
        self.manager.start(Hangs)
        self.run_steps(
            (lambda: self.titles() == ["Hangs"], ["h"]),
            (lambda: "Hangs (Not responding)" in self.titles(), ["\x11"]),
            (lambda: "Shutting down" in self.titles(), ["c"]),  # Cancel
            (lambda: self.titles() == ["Hangs (Not responding)"], []),
        )
        self.assertEqual(len(self.server.hosts), 0)  # ended with the desktop

    def test_responding_again(self) -> None:
        """Busy for a while, then answering: the mark goes."""
        host = AppHost(self.server, "x:Y", "Busy")
        app_end, desktop_end = pipe()
        host.connected(desktop_end)
        self.server.hosts.append(host)
        self.manager.add_application(host.application)
        state = {
            "type": "window", "id": 1, "title": "Busy", "rect": [2, 2, 6, 30],
            "maximised": False, "flags": [True, True, True, True], "look": "window",
            "modal": False, "outside": False, "status": "", "hints": [], "footer": [],
            "content": [0, 0], "scroll": [0, 0],
        }  # fmt: skip
        host.handle(state)
        start = time.monotonic()
        host.check(start + 0.2)  # quiet for longer than ping_interval
        self.assertEqual(drain(app_end), [{"type": "ping"}])
        host.check(start + 0.3)
        self.assertTrue(host.responding)  # not yet hang_timeout
        host.check(start + 1.0)
        self.assertFalse(host.responding)
        window = host.windows[1]
        self.assertEqual(window.title, "Busy (Not responding)")
        host.handle({"type": "pong"})
        self.assertTrue(host.responding)
        self.assertEqual(window.title, "Busy")
        host.handle({**state, "title": "Renamed"})
        self.assertEqual(window.title, "Renamed")

    def test_start_timeout(self) -> None:
        """An application that never connects is ended and reported."""
        host = AppHost(self.server, "x:Y", "Slow")
        self.server.hosts.append(host)
        host.check(host.started_at + self.server.start_timeout + 1)
        self.assertTrue(host.ended)
        self.assertEqual(
            self.server.notices, [("Cannot start", "Slow did not start in time.")]
        )

    def test_hung_application_never_blocks_the_desktop(self) -> None:
        """A hung application never blocks the desktop."""
        host = AppHost(self.server, "x:Y", "Deaf")
        _, desktop_end = pipe()  # nobody reads the other end
        host.connected(desktop_end)
        started = time.monotonic()
        for _ in range(200):
            host.send("paint", rows="x" * 50_000)
        self.assertLess(time.monotonic() - started, 2)
        host.finish(crashed=False)


class ClosingWithoutTheDesktopTests(unittest.TestCase):
    """The not-responding questions need the desktop running."""

    def test_offer_needs_the_desktop(self) -> None:
        """Without the desktop running, nothing is asked."""
        manager = PresentationManager()
        server = AppServer(manager)
        self.addCleanup(server.stop_all, 0)
        host = AppHost(server, "x:Y", "Hung")
        host.responding = False
        host.offer_to_end()  # nothing to show it on: nothing happens
        self.assertFalse(host.ended)

    def test_close_on_a_hung_window_asks(self) -> None:
        """Closing a hung window offers to end it."""
        manager = Scripted()
        server = AppServer(manager)
        self.addCleanup(server.stop_all, 0)
        manager.server = server
        host = AppHost(server, "x:Y", "Hung")
        app_end, desktop_end = pipe()
        host.connected(desktop_end)
        server.hosts.append(host)
        manager.add_application(host.application)
        host.handle(
            {"type": "window", "id": 1, "title": "Hung", "rect": [2, 2, 6, 30],
             "maximised": False, "flags": [True, True, True, True], "look": "window",
             "modal": False, "outside": False, "status": "", "hints": [], "footer": [],
             "content": [0, 0], "scroll": [0, 0]}  # fmt: skip
        )
        host.responding = False
        window = host.windows[1]
        self.assertIsInstance(window, RemoteWindow)
        manager.actions.append(manager.quit)
        run(manager, [ALT_F4, "e", "x"])
        self.assertTrue(host.ended)
        self.assertEqual(manager.windows, ())
        self.assertNotIn({"type": "close_request", "id": 1}, drain(app_end))


class ProcessTreeTests(unittest.TestCase):
    """Ending a process with the ones it started."""

    def setUp(self) -> None:
        # Windows can hold a log a moment after its process ends.
        folder = tempfile.TemporaryDirectory(  # pylint: disable=consider-using-with
            ignore_cleanup_errors=True
        )
        self.addCleanup(folder.cleanup)
        self.pid_file = Path(folder.name) / "grandchild.pid"

    def _pid_written(self) -> bool:
        """Whether the grandchild's pid has been written."""
        return self.pid_file.exists() and bool(self.pid_file.read_text("ascii"))

    def start_parent(self) -> tuple[ProcessTree, int]:
        """A child that starts a grandchild, which sleeps; both pids."""
        code = textwrap.dedent(f"""
            import subprocess, sys, time
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            open({str(self.pid_file)!r}, "w").write(str(child.pid))
            time.sleep(60)
            """)
        tree = ProcessTree.start([sys.executable, "-c", code])
        self.assertTrue(eventually(self._pid_written))
        return tree, int(self.pid_file.read_text())

    def test_kill_ends_the_whole_tree(self) -> None:
        """Killing a tree ends its grandchildren too."""
        tree, grandchild = self.start_parent()
        self.assertTrue(is_alive(grandchild))
        tree.kill()
        tree.close()
        self.assertIsNotNone(tree.process.poll())
        self.assertTrue(eventually(lambda: not is_alive(grandchild)))

    @unittest.skipUnless(os.name == "nt", "job objects are Windows's")
    def test_closing_the_job_ends_it(self) -> None:
        """What happens when the desktop dies: Windows closes its jobs."""
        tree, grandchild = self.start_parent()
        tree.close()
        self.assertTrue(eventually(lambda: tree.process.poll() is not None))
        self.assertTrue(eventually(lambda: not is_alive(grandchild)))

    @unittest.skipIf(os.name == "nt", "Windows ends applications with their job")
    def test_watch_the_desktop_not_the_parent(self) -> None:
        """Watch the desktop, not the parent."""
        # pylint: disable-next=consider-using-with
        desktop = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        code = (
            "from dasha.processes import watch_parent; import sys, time; "
            "watch_parent(int(sys.argv[1]), 0.05); time.sleep(60)"
        )
        # pylint: disable-next=consider-using-with
        watcher = subprocess.Popen([sys.executable, "-c", code, str(desktop.pid)])
        try:
            time.sleep(1.0)
            self.assertIsNone(watcher.poll())  # its parent is not the desktop
            desktop.kill()
            desktop.wait()
            self.assertEqual(watcher.wait(timeout=10), 1)
        finally:
            for process in (desktop, watcher):
                if process.poll() is None:
                    process.kill()
                    process.wait()

    @unittest.skipIf(os.name == "nt", "Windows ends applications with their job")
    def test_alive(self) -> None:
        """Running, or not (gone, or waiting to be reaped)."""
        self.assertTrue(processes_is_alive(os.getpid()))
        # pylint: disable-next=consider-using-with
        done = subprocess.Popen([sys.executable, "-c", "pass"])
        self.assertTrue(eventually(lambda: not processes_is_alive(done.pid)))
        done.wait()
        self.assertFalse(processes_is_alive(done.pid))

    @unittest.skipIf(os.name == "nt", "Windows ends applications with their job")
    def test_watch_parent(self) -> None:
        """An application whose desktop is killed ends itself."""
        code = textwrap.dedent(f"""
            import os, subprocess, sys
            child = subprocess.Popen([sys.executable, "-c",
                "from dasha.processes import watch_parent; import sys, time; "
                "watch_parent(int(sys.argv[1]), 0.05); time.sleep(60)",
                str(os.getpid())])
            open({str(self.pid_file)!r}, "w").write(str(child.pid))
            child.wait()
            """)
        # pylint: disable-next=consider-using-with
        parent = subprocess.Popen(
            [sys.executable, "-c", code]
        )  # pylint: disable=consider-using-with
        self.assertTrue(eventually(self._pid_written))
        watcher = int(self.pid_file.read_text())
        self.assertTrue(is_alive(watcher))
        parent.kill()
        parent.wait()
        self.assertTrue(eventually(lambda: not is_alive(watcher)))


class SignalTests(unittest.TestCase):
    """SIGTERM ends the desktop as Exit would, putting things back."""

    def test_sigterm(self) -> None:
        """SIGTERM leaves run(), with the handlers put back."""
        manager = PresentationManager()
        before = signal.getsignal(signal.SIGTERM)

        class Raising(FakeTerminal):
            """Sends the signal as it reads."""

            def read(self, timeout: float | None = None) -> str:
                signal.raise_signal(signal.SIGTERM)
                return ""

        with self.assertRaises(SystemExit) as raised:
            manager.run(cast(Terminal, Raising([], sizes=[(80, 24)])))
        self.assertEqual(raised.exception.code, 128 + signal.SIGTERM)
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)


class PongTests(unittest.TestCase):
    """The application answers pings."""

    def test_pong(self) -> None:
        """A ping gets a pong."""
        # pylint: disable-next=import-outside-toplevel
        from tests.test_hosting import ClientTests

        case = ClientTests("test_desktop_gone")
        case.setUp()
        try:
            case.tell("ping")
            self.assertEqual(drain(case.desktop), [{"type": "pong"}])
        finally:
            case.doCleanups()


if __name__ == "__main__":
    unittest.main()
