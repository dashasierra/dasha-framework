"""Tests for ``TerminalView``: a program's output shown, keys and pastes
sent to it, the scrollback, the selection and its ending."""

import sys
import time
import unittest
from collections.abc import Callable, Mapping, Sequence
from unittest import mock

from dasha.canvas import Rect
from dasha.clipboard import CLIPBOARD
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.menu import Menu
from dasha.shell import shell_command
from dasha.shortcuts import Shortcuts
from dasha.style import BLACK, DEFAULT, RED, WHITE, Style
from dasha.widgets import Grow, TerminalView
from dasha.window import Window

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


class _View(unittest.TestCase):
    """A window on a desktop, holding a terminal whose program is faked."""

    def setUp(self) -> None:
        self.manager = desktop()
        self.pty = FakePty()
        patcher = mock.patch(
            "dasha.widgets.terminalview.open_pty", return_value=self.pty
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.outputs = 0
        self.ended: list[int | None] = []
        self.window = Window(title="Terminal", rect=Rect(1, 0, 26, 82), resizable=True)
        self.view = self.window.add(
            widget=TerminalView(
                row=0,
                column=0,
                width=80,
                height=24,
                on_output=self._output_shown,
                on_exit=lambda view: self.ended.append(view.exit_code),
            ),
            grow=Grow.ALL,
        )
        self.manager.add(self.window)
        self.view.start()

    def _output_shown(self, view: TerminalView) -> None:
        del view
        self.outputs += 1

    def output(self, text: str) -> None:
        """The program writes ``text``, and the desktop shows it."""
        self.pty.output(text)
        pump(self.manager)

    def shown(self) -> list[str]:
        """What the window shows inside its frame, row by row."""
        canvas = self.window.render_interior(active=True)
        return [canvas.text(row).rstrip() for row in range(canvas.height)]

    def key(self, key: str) -> bool:
        """Press a key in the window."""
        return self.window.handle_key(key, self.manager.shortcuts)

    def at(self, row: int, column: int) -> tuple[int, int]:
        """A place in the view, on the screen."""
        interior = self.window.interior
        return interior.row + row, interior.column + column


class ProgramTests(_View):
    """Starting the program, its output, and its ending."""

    def test_starts_the_shell_at_its_size(self) -> None:
        """With no command, it runs the user's shell, at the view's size."""
        self.assertEqual(self.pty.started, shell_command())
        self.assertEqual(self.pty.sizes, [(80, 24)])
        self.assertTrue(self.view.is_running)

    def test_shows_output(self) -> None:
        """Output is shown, coloured, with the cursor where it is."""
        self.output("\x1b]0;My shell\x07\x1b[31mhello\x1b[0m\r\n$ ")
        self.assertEqual(self.shown()[:2], ["hello", "$"])
        canvas = self.window.render_interior(active=True)
        self.assertEqual(canvas.cell(0, 0)[1].foreground, 1)
        self.assertEqual(canvas.cursor, (1, 2))
        self.assertEqual(self.view.screen.title, "My shell")
        self.assertEqual(self.outputs, 1)

    def test_output_in_one_go_is_shown_once(self) -> None:
        """Pieces arriving before the desktop comes round are shown
        together."""
        self.pty.output("one ")
        self.pty.output("two")
        pump(self.manager)
        self.assertEqual(self.shown()[0], "one two")
        self.assertEqual(self.outputs, 1)

    def test_answers_questions(self) -> None:
        """Where the cursor is goes back to the program."""
        self.output("ab\x1b[6n")
        self.assertEqual(bytes(self.pty.sent), b"\x1b[1;3R")

    def test_ending(self) -> None:
        """Its ending is reported after the rest of its output is shown; the
        cursor goes."""
        self.pty.output("last words")
        self.pty.end(3)
        pump(self.manager, lambda: bool(self.ended))
        self.assertEqual(self.ended, [3])
        self.assertEqual(self.shown()[0], "last words")
        self.assertIsNone(self.window.render_interior(active=True).cursor)

    def test_resizing_follows_the_window(self) -> None:
        """The terminal takes the view's new size."""
        self.window.resize(width=42, height=12)
        screen = self.view.screen
        self.assertEqual((screen.columns, screen.lines), (40, 10))
        self.assertEqual(self.pty.sizes[-1], (40, 10))

    def test_close(self) -> None:
        """Closing ends the program."""
        self.view.close()
        self.assertTrue(self.pty.closed)

    def test_cannot_start(self) -> None:
        """A program that cannot start raises ``OSError``."""
        self.pty.fail = FileNotFoundError(2, "No such program", "nope")
        view = TerminalView(row=0, column=0, width=10, height=5, command=["nope"])
        with self.assertRaises(FileNotFoundError):
            view.start()


class DefaultStyleTests(_View):
    """The view's colours for what a program leaves in its default colours."""

    def cell_style(self, row: int, column: int) -> Style:
        """The style of a cell inside the window."""
        return self.window.render_interior(active=True).cell(row, column)[1]

    def test_the_terminals_own_by_default(self) -> None:
        """No colours, so the terminal Dasha Framework runs in chooses."""
        self.assertEqual(self.cell_style(5, 5), DEFAULT)

    def test_blank_cells_and_plain_text(self) -> None:
        """Whatever has no colours takes the view's."""
        self.view.default_style = Style(foreground=WHITE, background=BLACK)
        self.output("hi")
        for row, column in ((0, 0), (5, 5)):
            self.assertEqual(
                self.cell_style(row, column), Style(foreground=WHITE, background=BLACK)
            )

    def test_the_programs_colours_win(self) -> None:
        """A colour the program asks for stays, and the other is the view's;
        its bold stays too."""
        self.view.default_style = Style(foreground=WHITE, background=BLACK)
        self.output("\x1b[1;31mred")
        self.assertEqual(
            self.cell_style(0, 0), Style(foreground=RED, background=BLACK, bold=True)
        )

    def test_selected_text_is_still_reversed(self) -> None:
        """The selection reverses the view's colours like any others."""
        self.view.default_style = Style(foreground=WHITE, background=BLACK)
        self.output("hello")
        self.view.selection = (0, 0, 0, 5)
        self.assertEqual(
            self.cell_style(0, 0),
            Style(foreground=WHITE, background=BLACK, reverse=True),
        )


class KeyTests(_View):
    """Keys and pastes go to the program; the desktop's keys do not."""

    def test_keys_go_to_the_program(self) -> None:
        """Keys are sent as a terminal sends them."""
        for key in ("l", "s", "enter", "ctrl+c", "up", "tab", "alt+b", "escape"):
            self.assertTrue(self.key(key), key)
        self.assertEqual(bytes(self.pty.sent), b"ls\r\x03\x1b[A\t\x1bb\x1b")

    def test_application_cursor_keys(self) -> None:
        """A program that asks gets the application form of the arrows."""
        self.output("\x1b[?1h")
        self.key("up")
        self.assertEqual(bytes(self.pty.sent), b"\x1bOA")

    def test_desktop_keys_are_declined(self) -> None:
        """The desktop's own keys are not sent, even on a desktop of its
        own."""
        shortcuts = self.manager.shortcuts
        for key in ("ctrl+q", "f6", "f5", "f10", "alt+f4", "alt+f12"):
            self.assertFalse(self.view.handle_key(key, shortcuts), key)
        self.assertEqual(bytes(self.pty.sent), b"")

    def test_paste(self) -> None:
        """A paste is sent as typed, with Enter for each line break, and
        marked as a paste for a program that asked."""
        self.window.handle_paste("a\nb\r\n")
        self.assertEqual(bytes(self.pty.sent), b"a\rb\r")
        self.pty.sent.clear()
        self.output("\x1b[?2004h")
        self.window.handle_paste("x\x1b[201~y")
        self.assertEqual(bytes(self.pty.sent), b"\x1b[200~xy\x1b[201~")

    def test_copy_and_paste_keys(self) -> None:
        """``terminal_copy`` and ``terminal_paste``, given keys, copy and
        paste instead of being sent."""
        shortcuts = Shortcuts({"terminal_copy": ["f7"], "terminal_paste": ["f8"]})
        self.output("word")
        self.view.select_all()
        self.assertTrue(self.view.handle_key("f7", shortcuts))
        item = CLIPBOARD.item
        assert item is not None
        self.assertEqual(item.data, "word")
        self.assertTrue(self.view.handle_key("f8", shortcuts))
        self.assertEqual(bytes(self.pty.sent), b"word")


class MouseTests(_View):
    """The mouse, for a program that asks to be told of it."""

    def setUp(self) -> None:
        super().setUp()
        self.output("\x1b[?1000h\x1b[?1002h\x1b[?1006h")

    def mouse(
        self, action: str, button: str, row: int, column: int, **held: bool
    ) -> None:
        """Mouse activity at a place in the view."""
        self.window.handle_mouse(
            MouseEvent(action, button, *self.at(row, column), **held)
        )

    def test_clicks_and_drags_go_to_the_program(self) -> None:
        """A press, a drag and a release are reported, and select
        nothing."""
        self.assertTrue(self.view.is_mouse_for_program)
        self.mouse("press", "left", 2, 5)
        self.mouse("drag", "left", 3, 7)
        self.mouse("release", "left", 3, 7)
        self.assertEqual(bytes(self.pty.sent), b"\x1b[<0;6;3M\x1b[<32;8;4M\x1b[<0;8;4m")
        self.assertIsNone(self.view.selection)

    def test_wheel_and_right_click(self) -> None:
        """The wheel goes to the program, not the scrollback, and so does a
        right-click, with no menu popping up."""
        self.mouse("scroll", "down", 0, 0)
        self.mouse("press", "right", 1, 1)
        self.assertEqual(bytes(self.pty.sent), b"\x1b[<65;1;1M\x1b[<2;2;2M")
        self.assertEqual(self.view.back, 0)
        self.assertIsNone(self.view.popup_menu(self.manager.shortcuts))

    def test_shift_selects(self) -> None:
        """With Shift held down, dragging selects text as usual."""
        self.output("hello")
        self.mouse("press", "left", 0, 0, shift=True)
        self.mouse("drag", "left", 0, 3, shift=True)
        self.mouse("release", "left", 0, 3, shift=True)
        self.assertEqual(bytes(self.pty.sent), b"")
        self.assertEqual(self.view.selected_text(), "hell")

    def test_turned_off(self) -> None:
        """With ``send_mouse`` off, the mouse selects text as usual."""
        self.view.send_mouse = False
        self.assertFalse(self.view.is_mouse_for_program)
        self.output("hello")
        self.mouse("press", "left", 0, 1)
        self.mouse("release", "left", 0, 2)
        self.assertEqual(bytes(self.pty.sent), b"")
        self.assertEqual(self.view.selected_text(), "el")

    def test_a_drag_ends_where_it_started(self) -> None:
        """A release goes where its press went, even if the switch changed
        in between."""
        self.mouse("press", "left", 0, 0)
        self.view.send_mouse = False
        self.mouse("release", "left", 0, 0)
        self.assertEqual(bytes(self.pty.sent), b"\x1b[<0;1;1M\x1b[<0;1;1m")

    def test_not_once_it_stops_asking(self) -> None:
        """A program that turns tracking off gets no more reports."""
        self.output("\x1b[?1000l\x1b[?1002l")
        self.assertFalse(self.view.is_mouse_for_program)
        self.mouse("scroll", "up", 0, 0)
        self.assertEqual(bytes(self.pty.sent), b"")


class ScrollAndCopyTests(_View):
    """The scrollback, the selection and the clipboard."""

    def test_wheel_scrolls_back(self) -> None:
        """The wheel scrolls back, and stays put as output arrives; a key
        brings it back down."""
        self.output("\r\n".join(f"line {n}" for n in range(34)))
        self.window.handle_mouse(MouseEvent("scroll", "up", *self.at(1, 0)))
        self.assertEqual(self.view.back, 3)
        first = self.shown()[0]
        self.output("\r\nmore")
        self.assertEqual(self.shown()[0], first)
        self.key("a")
        self.assertEqual(self.view.back, 0)
        self.view.scroll_back(5)
        self.view.clear_scrollback()
        self.assertEqual((self.view.back, len(self.view.screen.scrollback)), (0, 0))

    def test_select_and_copy(self) -> None:
        """Dragging selects, drawn reversed; copying puts it on the
        clipboard."""
        self.output("hello world\r\nsecond line")
        self.window.handle_mouse(MouseEvent("press", "left", *self.at(0, 6)))
        self.window.handle_mouse(MouseEvent("drag", "left", *self.at(1, 5)))
        self.window.handle_mouse(MouseEvent("release", "left", *self.at(1, 5)))
        canvas = self.window.render_interior(active=True)
        self.assertTrue(canvas.cell(0, 6)[1].reverse)
        self.assertFalse(canvas.cell(0, 5)[1].reverse)
        self.view.copy()
        item = CLIPBOARD.item
        assert item is not None
        self.assertEqual(item.data, "world\nsecond")
        self.key("x")
        self.assertIsNone(self.view.selection)

    def test_paste_from_the_clipboard(self) -> None:
        """``paste`` sends the clipboard's text."""
        CLIPBOARD.copy_text("echo hi")
        self.view.paste()
        self.assertEqual(bytes(self.pty.sent), b"echo hi")

    def test_context_menu(self) -> None:
        """A right-click offers Copy and Paste."""
        menu = self.view.popup_menu(self.manager.shortcuts)
        assert isinstance(menu, Menu)
        self.assertEqual([item.label for item in menu.items], ["&Copy", "&Paste"])
        self.assertFalse(menu.items[0].is_available)


class RealProgramTests(unittest.TestCase):
    """A real program in a real pseudo-terminal."""

    def test_runs_a_real_program(self) -> None:
        """A program's output is shown, and its ending reported."""
        manager = desktop()
        ended: list[int | None] = []
        code = "print('\\x1b[32mreal output\\x1b[0m')"
        window = Window(title="Real", rect=Rect(1, 0, 12, 52))
        view = window.add(
            widget=TerminalView(
                row=0,
                column=0,
                width=50,
                height=10,
                command=[sys.executable, "-c", code],
                on_exit=lambda view: ended.append(view.exit_code),
            )
        )
        manager.add(window)
        view.start()
        self.addCleanup(view.close)
        pump(manager, lambda: bool(ended))
        self.assertEqual(ended, [0])
        self.assertIn("real output", view.screen.text(view.screen.rows))


if __name__ == "__main__":
    unittest.main()
