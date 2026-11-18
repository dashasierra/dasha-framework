"""Tests for Terminal: its windows, titles, endings and menus. The terminal
itself (``dasha.widgets.TerminalView``) has tests of its own, with
Dasha Framework's."""

import sys
import time
import unittest
from collections.abc import Callable, Mapping, Sequence
from unittest import mock

from dasha.canvas import Canvas
from dasha.client import colours_of
from dasha.clipboard import CLIPBOARD
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuBar, MenuItem
from dasha.shell import shell_command
from dasha.shortcuts import Shortcuts
from dasha.style import BLACK

from terminal import Terminal, TerminalWindow, program_name

PATIENCE = 20.0
"""How long a test waits for a real program, at most."""


class FakePty:  # pylint: disable=too-many-instance-attributes
    """Stands in for a ``PseudoTerminal``, with no program: it records what
    it is sent, and the test gives it output and its ending."""

    def __init__(self) -> None:
        self.on_output: Callable[[bytes], None] = lambda data: None
        self.on_exit: Callable[[], None] = lambda: None
        self.pid: int | None = None
        self.exit_code: int | None = None
        self.sent = bytearray()
        self.sizes: list[tuple[int, int]] = []
        self.closed = False
        self.fail: OSError | None = None
        self.started: list[str] = []

    @property
    def is_running(self) -> bool:
        """Whether it has started and not ended."""
        return self.pid is not None and self.exit_code is None

    def start(
        self,
        argv: Sequence[str],
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        size: tuple[int, int] = (80, 24),
    ) -> None:
        """Start, or fail to, as the test says."""
        del cwd, env
        if self.fail is not None:
            raise self.fail
        self.started = list(argv)
        self.sizes.append(size)
        self.pid = 1

    def write(self, data: bytes) -> None:
        """Record input."""
        self.sent += data

    def resize(self, columns: int, lines: int) -> None:
        """Record a size."""
        self.sizes.append((columns, lines))

    def close(self) -> None:
        """Record being closed."""
        self.closed = True

    def foreground_busy(self) -> bool:
        """Never busy."""
        return False

    def output(self, text: str) -> None:
        """The program writes ``text``."""
        self.on_output(text.encode())

    def end(self, code: int) -> None:
        """The program ends."""
        self.exit_code = code
        self.on_exit()


def desktop() -> PresentationManager:
    """A desktop, as though running (so that what other threads ask of it
    is done), whose loop the tests turn by hand (``pump``)."""
    manager = PresentationManager()
    manager.handle_resize(100, 30)
    manager._running = True  # pylint: disable=protected-access
    return manager


def pump(
    manager: PresentationManager, until: Callable[[], bool] = lambda: True
) -> None:
    """Call what other threads asked the desktop to, until ``until()``."""
    deadline = time.monotonic() + PATIENCE
    while True:
        manager._call_from_threads()  # pylint: disable=protected-access
        if until():
            return
        if time.monotonic() > deadline:
            raise AssertionError("it never happened")
        time.sleep(0.01)


def item(menu: Menu, label: str) -> MenuItem:
    """A menu's item, by its label."""
    return next(entry for entry in menu.items if entry.label == label)


def choose(menu: Menu, label: str) -> None:
    """Choose a menu's item."""
    action = item(menu, label).action
    assert action is not None
    action()


class _Terminal(unittest.TestCase):
    """A desktop with Terminal on it, its programs faked."""

    def setUp(self) -> None:
        self.manager = desktop()
        self.ptys: list[FakePty] = []
        self.failure: OSError | None = None

        def fake() -> FakePty:
            pty = FakePty()
            pty.fail = self.failure
            self.ptys.append(pty)
            return pty

        patcher = mock.patch("dasha.widgets.terminalview.open_pty", side_effect=fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def launch(self, command: Sequence[str] = ()) -> tuple[Terminal, TerminalWindow]:
        """Terminal, and its first window."""
        app = self.manager.launch(Terminal(command=command))
        assert isinstance(app, Terminal)
        window = app.windows[-1]
        assert isinstance(window, TerminalWindow)
        return app, window

    def output(self, index: int, text: str) -> None:
        """A window's program writes ``text``, and the desktop shows it."""
        self.ptys[index].on_output(text.encode())
        pump(self.manager)

    def shown(self, window: TerminalWindow) -> list[str]:
        """What the window shows inside its frame, row by row."""
        canvas = window.render_interior(active=True)
        return [canvas.text(row).rstrip() for row in range(canvas.height)]


class WindowTests(_Terminal):
    """Windows, titles and endings."""

    def test_runs_the_shell_in_a_window(self) -> None:
        """The first window runs the user's shell, 80 by 25 where that
        fits."""
        app, window = self.launch()
        self.assertEqual([m.title for m in app.menus], ["&Terminal", "&Edit"])
        self.assertEqual(self.ptys[0].started, shell_command())
        interior = window.interior
        self.assertEqual((interior.width, interior.height), (80, 25))
        self.assertEqual(self.ptys[0].sizes, [(80, 25)])
        self.assertEqual(window.footer_parts(), ["80x25"])

    def test_black_frame_and_inside(self) -> None:
        """Frame and inside are black, and the window tells the desktop so,
        which draws the frame of an application in its own process."""
        _, window = self.launch()
        canvas = Canvas(window.rect.right, window.rect.bottom)
        window.paint(canvas, active=True)
        frame = canvas.cell(window.rect.row, window.rect.column + 8)[1]
        inside = canvas.cell(window.interior.row, window.interior.column)[1]
        self.assertEqual(frame.background, BLACK)
        self.assertEqual(inside.background, BLACK)
        self.assertIn("frame_style", colours_of(window))

    def test_title_and_footer(self) -> None:
        """The title is the one the program asks for; the footer shows how
        far the view is scrolled back."""
        _, window = self.launch()
        self.assertEqual(window.title, program_name(shell_command()))
        self.output(0, "\x1b]0;My shell\x07" + "\r\n" * 30)
        self.assertEqual(window.title, "My shell")
        interior = window.interior
        wheel = MouseEvent("scroll", "up", interior.row, interior.column)
        window.handle_mouse(wheel)
        self.assertEqual(window.footer_parts(), ["80x25", "\N{UPWARDS ARROW}3"])

    def test_closes_when_the_shell_ends(self) -> None:
        """The shell's window closes when it ends, and Terminal with the
        last."""
        app, window = self.launch()
        app.new_window()
        self.assertEqual(len(app.windows), 2)
        self.ptys[0].end(0)
        pump(self.manager, lambda: window not in app.windows)
        self.assertTrue(app.is_running)
        self.ptys[1].end(0)
        pump(self.manager, lambda: not app.is_running)

    def test_a_command_given_stays(self) -> None:
        """A window running a command it was given stays, saying how it
        ended."""
        app, window = self.launch(command=["make"])
        self.assertEqual(self.ptys[0].started, ["make"])
        self.assertEqual(window.title, "make")
        self.output(0, "done")
        self.ptys[0].end(2)
        pump(self.manager, lambda: window.view.exit_code is not None)
        self.assertIn(window, app.windows)
        self.assertEqual(window.title, "make (ended)")
        self.assertEqual(self.shown(window)[:2], ["done", "[Ended: exit code 2]"])

    def test_cannot_start(self) -> None:
        """A program that cannot start leaves no window, and says why
        before Terminal ends."""
        self.failure = FileNotFoundError(2, "No such program", "nope")
        told: list[str] = []
        with mock.patch.object(
            self.manager, "execute", side_effect=lambda dialog: told.append("told")
        ):
            app = self.manager.launch(Terminal(command=["nope"]))
            assert isinstance(app, Terminal)
            self.assertEqual(app.windows, [])
            self.assertTrue(app.is_running)  # until the message is seen
            self.manager._now_running()  # pylint: disable=protected-access
        self.assertEqual(told, ["told"])
        self.assertFalse(app.is_running)

    def test_closing_ends_the_program(self) -> None:
        """Closing a window ends its program, and Terminal with the last."""
        app, window = self.launch()
        choose(app.menus[0], "&Close")
        self.assertNotIn(window, app.windows)
        self.assertTrue(self.ptys[0].closed)
        self.assertFalse(app.is_running)


class MenuTests(_Terminal):
    """Send key and the Edit menu."""

    def test_no_letter_is_repeated(self) -> None:
        """No two menus on the bar, and no two items of a menu, share a
        letter."""
        self.launch()
        bar = MenuBar()
        bar.set_menus(self.manager.bar_menus())
        bar.check_mnemonics()

    def test_alt_and_a_letter(self) -> None:
        """Alt+T and Alt+E open the menus, rather than reaching the shell,
        as Alt and any other letter still does."""
        self.launch()
        for key in ("alt+t", "alt+e"):
            self.manager.handle_event(key)
            self.assertTrue(self.manager.menu_bar.is_open, key)
            self.manager.handle_event("escape")
        self.assertEqual(bytes(self.ptys[0].sent), b"")
        self.manager.handle_event("alt+b")
        self.assertFalse(self.manager.menu_bar.is_open)
        self.assertEqual(bytes(self.ptys[0].sent), b"\x1bb")

    def test_mouse_to_programs(self) -> None:
        """Terminal > Mouse to programs turns the mouse going to programs
        off and on, in every window, new ones too; the footer says while it
        goes to one."""
        app, window = self.launch()
        self.output(0, "\x1b[?1000h")
        self.assertEqual(window.footer_parts(), ["80x25", "Mouse"])
        terminal_menu = app.menus[0]
        self.assertEqual(
            item(terminal_menu, "\N{SQUARE ROOT} &Mouse to programs").shortcut, ""
        )
        choose(terminal_menu, "\N{SQUARE ROOT} &Mouse to programs")
        self.assertFalse(window.view.send_mouse)
        self.assertEqual(window.footer_parts(), ["80x25"])
        other = app.new_window()
        assert other is not None
        self.assertFalse(other.view.send_mouse)
        choose(app.menus[0], "  &Mouse to programs")
        self.assertTrue(window.view.send_mouse and other.view.send_mouse)

    def test_send_key(self) -> None:
        """Terminal > Send key sends the keys the desktop keeps."""
        app, _ = self.launch()
        labels = [entry.label for entry in app.send_keys.items]
        self.assertIn("Ctrl+Q", labels)
        self.assertIn("F10", labels)
        choose(app.send_keys, "Ctrl+Q")
        self.assertEqual(bytes(self.ptys[0].sent), b"\x11")

    def test_menus_follow_the_shortcuts(self) -> None:
        """Remapped shortcuts change what Send key offers, and the Edit
        menu's hints."""
        app, _ = self.launch()
        self.assertEqual(item(app.menus[1], "&Copy").shortcut, "")
        self.manager.set_shortcuts(
            Shortcuts({"exit": ["ctrl+k"], "terminal_copy": ["f7"]})
        )
        labels = [entry.label for entry in app.send_keys.items]
        self.assertIn("Ctrl+K", labels)
        self.assertNotIn("Ctrl+Q", labels)
        self.assertEqual(item(app.menus[1], "&Copy").shortcut, "F7")

    def test_edit_menu(self) -> None:
        """Select all and Copy put the text on the clipboard; Paste sends
        the clipboard's text."""
        app, _ = self.launch()
        self.output(0, "hello")
        edit = app.menus[1]
        choose(edit, "Select &all")
        choose(edit, "&Copy")
        clipped = CLIPBOARD.item
        assert clipped is not None
        self.assertEqual(clipped.data, "hello")
        CLIPBOARD.copy_text("echo hi")
        choose(edit, "&Paste")
        self.assertEqual(bytes(self.ptys[0].sent), b"echo hi")


class RealProgramTests(unittest.TestCase):
    """Terminal with a real program in a real pseudo-terminal."""

    def test_runs_a_real_program(self) -> None:
        """A program's output is shown, and the window says when it
        ended."""
        manager = desktop()
        code = "print('\\x1b[32mreal output\\x1b[0m')"
        app = manager.launch(Terminal(command=[sys.executable, "-c", code]))
        assert isinstance(app, Terminal)
        window = app.windows[0]
        assert isinstance(window, TerminalWindow)
        pump(manager, lambda: window.view.exit_code is not None)
        screen = window.view.screen
        text = screen.text(screen.rows)
        self.assertIn("real output", text)
        self.assertIn("[Ended: exit code 0]", text)


if __name__ == "__main__":
    unittest.main()
