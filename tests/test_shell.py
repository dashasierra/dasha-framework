"""Tests for running the user's shell for the command prompt
(``dasha.shell``)."""

# pylint: disable=protected-access  # its signal handling is the point

import os
import signal
import subprocess
import sys
import threading
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from dasha import shell
import tests.support  # pylint: disable=unused-import  # cleans the environment

# Not on Windows, where the tests using it are skipped.
SIGTTOU: int = getattr(signal, "SIGTTOU", 0)


def quiet_signals() -> list[int]:
    """The signals the shell's keys send that exist here."""
    numbers = (getattr(signal, name, None) for name in shell._QUIET_SIGNALS)
    return [number for number in numbers if number is not None]


class ShellCommandTests(unittest.TestCase):
    """Which shell is run."""

    def test_windows(self) -> None:
        """COMSPEC, or cmd.exe."""
        with patch("sys.platform", "win32"):
            with patch.dict(os.environ, {"COMSPEC": r"C:\Windows\cmd.exe"}):
                self.assertEqual(shell.shell_command(), [r"C:\Windows\cmd.exe"])
            with patch.dict(os.environ, {"COMSPEC": ""}):
                self.assertEqual(shell.shell_command(), ["cmd.exe"])

    def test_elsewhere(self) -> None:
        """SHELL, or /bin/sh."""
        with patch("sys.platform", "linux"):
            with patch.dict(os.environ, {"SHELL": "/bin/zsh"}):
                self.assertEqual(shell.shell_command(), ["/bin/zsh"])
            with patch.dict(os.environ, {"SHELL": ""}):
                self.assertEqual(shell.shell_command(), ["/bin/sh"])


class RunTests(unittest.TestCase):
    """Running it."""

    def test_runs_and_says_how_to_come_back(self) -> None:
        """The shell runs with DASHA_SUSPENDED set, after the user is
        told how to come back; its exit code is returned."""
        stream = StringIO()
        code = shell.run_shell(
            [
                sys.executable,
                "-c",
                "import os, sys; "
                "sys.exit(7 if os.environ.get('DASHA_SUSPENDED') == '1' else 1)",
            ],
            stream,
        )
        self.assertEqual(code, 7)
        self.assertIn("Dasha Desktop is still running. Type exit", stream.getvalue())
        stream = StringIO()
        shell.run_shell([sys.executable, "-c", ""], stream, name="Hello")
        self.assertIn("Hello is still running", stream.getvalue())
        self.assertNotIn("Dasha Framework", stream.getvalue())
        self.assertNotIn(shell.SUSPENDED_VARIABLE, os.environ)

    def test_signals_are_caught_meanwhile(self) -> None:
        """While the shell runs, the signals its keys send are caught and do
        nothing (caught, not ignored, so the shell gets them as usual); the
        handlers before are put back afterwards, even when it fails."""

        def handler(number: int, frame: object) -> None:
            del number, frame

        for number in quiet_signals():
            self.addCleanup(signal.signal, number, signal.signal(number, handler))
        before = {number: signal.getsignal(number) for number in quiet_signals()}
        self.assertEqual(set(before.values()), {handler})
        during = {}

        def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            del args, kwargs
            during.update({number: signal.getsignal(number) for number in before})
            return subprocess.CompletedProcess(["sh"], 0)

        with patch("subprocess.run", side_effect=run):
            shell.run_shell(["sh"], StringIO())
        self.assertTrue(before)
        self.assertEqual(set(during.values()), {shell._do_nothing})
        self.assertNotIn(signal.SIG_IGN, during.values())
        after = {number: signal.getsignal(number) for number in before}
        self.assertEqual(after, before)
        with self.assertRaises(OSError):
            shell.run_shell(["no-such-shell-for-dasha-tests"], StringIO())
        after = {number: signal.getsignal(number) for number in before}
        self.assertEqual(after, before)
        shell._do_nothing(signal.SIGINT, None)  # and it does nothing

    def test_not_on_the_main_thread(self) -> None:
        """Signal handlers can only be set on the main thread; elsewhere
        they are left alone."""
        seen: list[object] = []

        def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            del args, kwargs
            seen.append(signal.getsignal(signal.SIGINT))
            return subprocess.CompletedProcess(["sh"], 0)

        with patch("subprocess.run", side_effect=run):
            thread = threading.Thread(target=shell.run_shell, args=(["sh"], StringIO()))
            thread.start()
            thread.join()
        self.assertEqual(seen, [signal.getsignal(signal.SIGINT)])


@unittest.skipIf(sys.platform == "win32", "process groups are not Windows'")
class TakeBackTests(unittest.TestCase):
    """Taking the terminal back from a shell that kept it."""

    def take_back(self, owner: int | Exception) -> MagicMock:
        """Take it back from ``owner`` (or with reading the owner failing);
        what was asked of ``tcsetpgrp``."""
        stdin = MagicMock()
        stdin.fileno.return_value = 0
        before = signal.getsignal(SIGTTOU)
        get = MagicMock(side_effect=owner) if isinstance(owner, Exception) else None
        with (
            patch("sys.stdin", stdin),
            patch("os.getpgrp", return_value=456),
            patch("os.tcgetpgrp", get or MagicMock(return_value=owner)),
            patch("os.tcsetpgrp") as tcsetpgrp,
        ):
            shell._take_back_terminal()
        self.assertEqual(signal.getsignal(SIGTTOU), before)
        return tcsetpgrp

    def test_taken_back(self) -> None:
        """From another group, it is taken back."""
        self.take_back(123).assert_called_once_with(0, 456)

    def test_left_alone(self) -> None:
        """Already the desktop's, or not a terminal: nothing is done."""
        self.take_back(456).assert_not_called()
        self.take_back(OSError("not a terminal")).assert_not_called()


if __name__ == "__main__":
    unittest.main()
