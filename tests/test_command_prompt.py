"""Tests for the command prompt."""

import os
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from typing import Any, cast
from unittest.mock import patch

from dasha.canvas import Canvas, Rect
from dasha.dialog import information
from dasha.hosting import AppHost
from dasha.manager import PresentationManager
from dasha.protocol import Message, encode_style
from dasha.remote import RemoteWindow
from dasha.settings import KeyDialog
from dasha.shortcuts import DEFAULTS, Shortcuts
from dasha.style import BLUE, Style
from dasha.terminal import Terminal, ansi
from dasha.window import Window
from dasha.shell import SUSPENDED_VARIABLE
from tests.support import isolated_home, pipe, serving, started_desktop
from tests.test_hosting import drain

ALT_F12 = "\x1b[24;3~"
SCRIBBLE = ansi.CLEAR_SCREEN + ansi.move_to(0, 0) + "Another program was here"


class PromptTerminal:
    """A terminal stand-in that can be given back.

    :param manager: The desktop.
    :param inputs: Scripted input; ``None`` ends the desktop.
    :param size: Screen (columns, lines).
    """

    def __init__(
        self,
        manager: PresentationManager,
        inputs: list[str | None],
        size: tuple[int, int] = (80, 24),
    ) -> None:
        self.manager = manager
        self.inputs = inputs
        self.screen_size = size
        self.output = StringIO()
        self.suspensions = 0
        self.frame_before: Canvas | None = None
        self.taken_back_at = 0

    def size(self) -> tuple[int, int]:
        """The screen's size, as a terminal reports it."""
        return self.screen_size

    def write(self, text: str) -> None:
        """Capture output.

        :param text: The output.
        """
        self.output.write(text)

    def flush(self) -> None:
        """Nothing to flush."""

    def read(self, timeout: float | None = None) -> str:
        """The next scripted input.

        :param timeout: Ignored.
        """
        del timeout
        key = self.inputs.pop(0)
        if key is None:
            self.manager.quit()
            return ""
        return key

    @contextmanager
    def suspended(self) -> Iterator[None]:
        """Give the terminal back, then clear the screen."""
        self.suspensions += 1
        self.frame_before = self.manager._on_screen  # pylint: disable=protected-access
        self.write(SCRIBBLE)
        try:
            yield
        finally:
            self.write(ansi.CLEAR_SCREEN)
            self.taken_back_at = len(self.output.getvalue())

    def after(self) -> str:
        """What was written once the terminal was taken back."""
        return self.output.getvalue()[self.taken_back_at :]


def text_of(canvas: Canvas) -> list[str]:
    """A canvas's rows as text.

    :param canvas: The canvas.
    """
    return [canvas.text(row) for row in range(canvas.height)]


class RedrawTests(unittest.TestCase):
    """Leaving for the shell and coming back, with the desktop running."""

    def setUp(self) -> None:
        self.manager = PresentationManager(
            windows=[Window("Notes", Rect(3, 40, 8, 30))]
        )
        self.manager.handle_resize(80, 24)
        server = serving(self, self.manager)
        self.host = AppHost(server, "tests.hosted_apps:Hello", "Hello")
        self.app_end, desktop_end = pipe()
        self.host.connected(desktop_end)
        server.hosts.append(self.host)
        self.manager.add_application(self.host.application)

    def open_hosted(self) -> RemoteWindow:
        """Show a hosted application's window."""
        state: Message = {
            "type": "window", "id": 1, "title": "Hello", "rect": [2, 2, 6, 30],
            "maximised": False, "flags": [True, True, True, True], "look": "window",
            "modal": False, "outside": False, "status": "Hi", "hints": [],
            "footer": [], "content": [28, 4], "scroll": [0, 0],
        }  # fmt: skip
        self.host.handle(state)
        self.host.handle(
            {"type": "paint", "id": 1, "size": [28, 4],
             "styles": [encode_style(Style(foreground=BLUE))],
             "rows": [[1, [["Hi there", 0]]]], "cursor": None}  # fmt: skip
        )
        return self.host.windows[1]

    def run_desktop(self, terminal: PromptTerminal, **shell: Any) -> None:
        """Run the desktop with the shell patched.

        :param terminal: The terminal stand-in.
        :param shell: Patches for ``run_shell``.
        """
        with patch("dasha.shell.run_shell", **shell) as run_shell:
            self.manager.run(cast(Terminal, terminal))
        self.assertEqual(run_shell.call_count, terminal.suspensions)

    def test_every_cell_is_drawn_again(self) -> None:
        """Every cell is drawn again."""
        self.open_hosted()
        for survive_errors in (False, True):
            with self.subTest(survive_errors=survive_errors):
                self.manager.survive_errors = survive_errors
                terminal = PromptTerminal(self.manager, [ALT_F12, None])
                self.run_desktop(terminal, return_value=0)
                self.assertEqual(terminal.suspensions, 1)
                before = terminal.frame_before
                assert before is not None
                self.assertIn("Hi there", before.text(4))
                self.assertIn("Notes", before.text(3))
                after = self.manager._on_screen  # pylint: disable=protected-access
                assert after is not None
                self.assertEqual(text_of(after), text_of(before))
                self.assertEqual(terminal.after(), before.render(None))

    def test_a_new_size(self) -> None:
        """A new size is used."""
        terminal = PromptTerminal(self.manager, [ALT_F12, None])

        def resized(**_: str) -> int:
            terminal.screen_size = (100, 30)
            return 0

        self.run_desktop(terminal, side_effect=resized)
        after = self.manager._on_screen  # pylint: disable=protected-access
        assert after is not None
        self.assertEqual((after.width, after.height), (100, 30))
        self.assertEqual(terminal.after(), after.render(None))

    def test_the_mouse_is_forgotten(self) -> None:
        """The mouse position is forgotten."""
        self.manager.show_mouse = True
        self.manager._mouse_at = (5, 10)  # pylint: disable=protected-access
        terminal = PromptTerminal(self.manager, [ALT_F12, None])
        self.run_desktop(terminal, return_value=0)
        self.assertIsNone(self.manager._mouse_at)  # pylint: disable=protected-access

    def test_a_shell_that_cannot_start(self) -> None:
        """The user is told why, once the screen is back."""
        terminal = PromptTerminal(self.manager, [ALT_F12, "\r", None])
        self.run_desktop(terminal, side_effect=FileNotFoundError("no such shell"))
        self.assertIn("no such shell", terminal.after())
        self.assertFalse(self.manager.is_running)

    def test_the_key_is_the_desktops(self) -> None:
        """The key belongs to the desktop."""
        window = self.open_hosted()
        self.assertIs(self.manager.active_window, window)
        with patch.object(self.manager, "command_prompt") as command_prompt:
            self.manager.handle_event("alt+f12")
            self.manager.handle_event("a")
        command_prompt.assert_called_once_with()
        keys = [m.get("key") for m in drain(self.app_end) if m["type"] == "key"]
        self.assertEqual(keys, ["a"])


class KeyAndMenuTests(unittest.TestCase):
    """How the command prompt is reached."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.handle_resize(80, 24)

    def test_the_key(self) -> None:
        """The default key."""
        self.assertEqual(DEFAULTS["command_prompt"], ("alt+f12",))
        with patch.object(self.manager, "command_prompt") as command_prompt:
            self.manager.handle_event("alt+f12")
            self.manager.handle_modal_event(information("Note", "Hello"), "alt+f12")
            asking = KeyDialog("exit")
            self.manager.handle_modal_event(asking, "alt+f12")
        self.assertEqual(command_prompt.call_count, 2)
        self.assertEqual(asking.key, "alt+f12")

    def test_the_menu_item(self) -> None:
        """The system menu item."""
        item = next(
            item
            for item in self.manager.system_menu.items
            if item.label == "&Command prompt"
        )
        self.assertEqual(item.shortcut, "Alt+F12")
        self.assertEqual(item.action, self.manager.command_prompt)
        self.manager.set_shortcuts(Shortcuts({"command_prompt": ["ctrl+f12"]}))
        self.assertEqual(item.shortcut, "Ctrl+F12")

    def test_only_on_a_terminal_that_can_be_given_back(self) -> None:
        """Only on a terminal that can be given back."""
        with patch("dasha.shell.run_shell") as run_shell:
            self.manager.command_prompt()
            # pylint: disable-next=protected-access
            self.manager._terminal = cast(Terminal, object())
            self.manager.command_prompt()
        run_shell.assert_not_called()


class NestedTests(unittest.TestCase):
    """Not a desktop inside the command prompt of another."""

    def setUp(self) -> None:
        isolated_home(self)

    def test_refused(self) -> None:
        """The command line says why, and starts no desktop."""
        with patch.dict(os.environ, {SUSPENDED_VARIABLE: "1"}):
            code, desktop, said = started_desktop()
        self.assertEqual(code, 1)
        desktop.assert_not_called()
        self.assertIn("already running in this terminal", said)
        self.assertIn("type exit", said)

    def test_otherwise_started(self) -> None:
        """Outside one, and for the key test inside one, it starts."""
        self.assertNotIn(SUSPENDED_VARIABLE, os.environ)
        self.assertEqual(started_desktop()[0], 0)
        with (
            patch.dict(os.environ, {SUSPENDED_VARIABLE: "1"}),
            patch("dasha.keytest.run") as key_test,
        ):
            code, desktop, _ = started_desktop("-k")
        self.assertEqual(code, 0)
        key_test.assert_called_once()
        desktop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
