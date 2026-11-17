"""Tests for pseudo-terminals (``dasha.pseudoterminal``), with real
programs running in them."""

import os
import subprocess
import sys
import threading
import time
import unittest

import dasha
from dasha.pseudoterminal import PseudoTerminal, open_pty
from dasha.vt import Screen

PATIENCE = 20.0
"""How long a test waits for a program, at most, before failing."""

SOURCE = os.path.dirname(os.path.dirname(os.path.abspath(dasha.__file__)))
"""The folder dasha is imported from, for a child Python to find it."""


class Session:
    """A program in a pseudo-terminal, with what it wrote so far."""

    def __init__(self, code: str, size: tuple[int, int] = (80, 24)) -> None:
        self.output = bytearray()
        self.exits = 0
        self._lock = threading.Lock()
        self.pty: PseudoTerminal = open_pty()
        self.pty.on_output = self._output
        self.pty.on_exit = self._exited
        self.pty.start([sys.executable, "-c", code], size=size)

    def _output(self, data: bytes) -> None:
        with self._lock:
            self.output += data

    def _exited(self) -> None:
        self.exits += 1

    def text(self) -> str:
        """What the screen shows, so far, as plain text."""
        with self._lock:
            data = bytes(self.output)
        screen = Screen(columns=200, lines=50)
        screen.feed_bytes(data)
        return screen.text(screen.rows)

    def screen(self) -> Screen:
        """The screen, so far."""
        with self._lock:
            data = bytes(self.output)
        screen = Screen(columns=200, lines=50)
        screen.feed_bytes(data)
        return screen

    def wait_for(self, text: str) -> None:
        """Wait until the screen shows ``text``."""
        deadline = time.monotonic() + PATIENCE
        while text not in self.text():
            if time.monotonic() > deadline:
                raise AssertionError(f"{text!r} never came; got {self.text()!r}")
            time.sleep(0.02)


class PseudoTerminalTests(unittest.TestCase):
    """A program sees a terminal, and its output and input go through."""

    def session(self, code: str, size: tuple[int, int] = (80, 24)) -> Session:
        """Start a Python program; it is ended when the test is."""
        session = Session(code, size)
        self.addCleanup(session.pty.wait, PATIENCE)
        self.addCleanup(session.pty.close)
        return session

    def test_output_with_colour(self) -> None:
        """Coloured output arrives, and ends with the program."""
        session = self.session(
            "import sys; print('\\x1b[32mgreen\\x1b[0m plain', sys.stdout.isatty())"
        )
        self.assertTrue(session.pty.wait(PATIENCE))
        self.assertIn("green plain True", session.text())
        rows = session.screen().rows
        found = [cell for row in rows for cell in row if cell[0] == "g"]
        self.assertEqual(found[0][1].foreground, 2)
        self.assertEqual(session.pty.exit_code, 0)
        self.assertEqual(session.exits, 1)
        self.assertFalse(session.pty.is_running)

    def test_input_reaches_the_program(self) -> None:
        """Bytes written arrive as typed input."""
        session = self.session("print('<' + input('name? ')[::-1] + '>')")
        session.wait_for("name?")
        session.pty.write(b"abc\r")
        session.wait_for("<cba>")
        self.assertTrue(session.pty.wait(PATIENCE))

    def test_size_and_resize(self) -> None:
        """The program sees the size given, and a new one after a resize."""
        code = (
            "import os\n"
            "print('first', *os.get_terminal_size())\n"
            "input()\n"
            "print('then', *os.get_terminal_size())\n"
        )
        session = self.session(code, size=(70, 20))
        session.wait_for("first 70 20")
        session.pty.resize(columns=50, lines=10)
        time.sleep(0.2)
        session.pty.write(b"\r")
        session.wait_for("then 50 10")

    def test_exit_code(self) -> None:
        """How the program ended is kept."""
        session = self.session("import sys; sys.exit(3)")
        self.assertTrue(session.pty.wait(PATIENCE))
        self.assertEqual(session.pty.exit_code, 3)
        self.assertEqual(session.exits, 1)

    def test_close_ends_a_running_program(self) -> None:
        """Closing ends a program that would otherwise run on."""
        session = self.session("import time; print('ready'); time.sleep(60)")
        session.wait_for("ready")
        self.assertTrue(session.pty.is_running)
        session.pty.close()
        self.assertTrue(session.pty.wait(PATIENCE))
        self.assertFalse(session.pty.is_running)
        self.assertEqual(session.exits, 1)
        session.pty.write(b"dropped")  # once ended, input goes nowhere
        session.pty.close()  # and closing again does nothing

    def test_missing_program(self) -> None:
        """A program that is not there cannot be started."""
        pty = open_pty()
        with self.assertRaises(FileNotFoundError):
            pty.start(["no-such-program-dasha"])
        self.assertFalse(pty.is_running)
        with self.assertRaises(ValueError):
            pty.start([])

    def test_with_standard_output_redirected(self) -> None:
        """A program run from a process whose own output is redirected (as
        an application's is, run by the desktop) still writes to the
        pseudo-terminal."""
        script = (
            "import sys\n"
            "from dasha.pseudoterminal import open_pty\n"
            "captured = []\n"
            "pty = open_pty()\n"
            "pty.on_output = captured.append\n"
            "pty.start([sys.executable, '-c', 'print(\"via-\" + \"pty\")'])\n"
            "pty.wait(20)\n"
            "sys.stderr.write(repr(b''.join(captured)))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=dict(os.environ, PYTHONPATH=SOURCE),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=PATIENCE,
            check=True,
            text=True,
        )
        self.assertIn("via-pty", result.stderr)

    @unittest.skipIf(sys.platform == "win32", "process groups are POSIX")
    def test_idle_is_not_busy(self) -> None:
        """A program waiting for input, having started nothing, is not
        busy."""
        session = self.session("print('idle'); input()")
        session.wait_for("idle")
        self.assertFalse(session.pty.foreground_busy())


if __name__ == "__main__":
    unittest.main()
