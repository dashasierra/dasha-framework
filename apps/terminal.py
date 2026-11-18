"""Terminal: the user's shell, or another command-line program, in a window.

Run it on its own with ``python apps/terminal.py [COMMAND ...]``, or
install it on the desktop with ``dasha install-app apps/terminal.py``.
Each window holds a ``TerminalView`` (``dasha.widgets``), running a
shell of its own (``COMSPEC`` on Windows, ``SHELL`` elsewhere), or COMMAND
if one is given.

Every key goes to the shell, except those the desktop keeps for itself
(Ctrl+Q, F5, F6, F10, Alt+F4 and the other window keys). Terminal > Send
key sends those. Alt+T and Alt+E open the menus, as F10 does, so those two
do not reach the shell; Alt and any other letter does.

A program that asks to be told of the mouse (an editor, say) gets clicks,
drags and the wheel; Terminal > Mouse to programs turns that off, so that
the mouse selects text instead, in every window.

Like the other example applications, it passes arguments by name, so it
reads as a guide to the framework.
"""

import os
import shutil
import sys
from collections.abc import Callable, Sequence
from typing import Protocol

from dasha.application import Application
from dasha.canvas import Rect
from dasha.dialog import confirm, information
from dasha.menu import Menu, MenuItem, separator
from dasha.shortcuts import pretty_key
from dasha.style import BLACK, BRIGHT_GREEN, BRIGHT_WHITE, WHITE, Style
from dasha.vt import encode_key
from dasha.widgets import Grow, TerminalView
from dasha.widgets.terminalview import RESERVED_ACTIONS
from dasha.window import Window

SCROLLED_BACK = "\N{UPWARDS ARROW}"
"""In the footer, before the number of lines scrolled back: ``↑``, code
page 437 glyph 24."""

MOUSE_TO_PROGRAM = "Mouse"
"""In the footer while the mouse goes to the program, not to selecting
text."""


def marked(label: str, on: bool) -> str:
    """A menu item's label, marked ``√`` while what it turns on is on."""
    mark = "\N{SQUARE ROOT}" if on else " "
    return f"{mark} {label}"


def powershell() -> str | None:
    """The PowerShell on ``PATH`` (the newer ``pwsh`` first), if any."""
    return shutil.which("pwsh") or shutil.which("powershell")


def program_name(argv: Sequence[str]) -> str:
    """A command's name, for a title: ``bash`` for ``/bin/bash -l``."""
    return os.path.basename(argv[0]) if argv else "Terminal"


class ViewAction(Protocol):  # pylint: disable=too-few-public-methods
    """Something to do with a window's terminal, given as ``view=``."""

    def __call__(self, *, view: TerminalView) -> object: ...


class TerminalWindow(Window):
    """A window holding nothing but a terminal, whose title is the one its
    program asks for, black whatever the theme."""

    frame_style = Style(foreground=BRIGHT_WHITE, background=BLACK, bold=True)
    inactive_frame_style = Style(foreground=WHITE, background=BLACK)
    adjusting_frame_style = Style(foreground=BRIGHT_GREEN, background=BLACK, bold=True)
    body_style = Style(foreground=WHITE, background=BLACK)
    button_style = Style(foreground=BRIGHT_GREEN, background=BLACK, bold=True)
    resize_grip_style = Style(foreground=BRIGHT_GREEN, background=BLACK, bold=True)

    def __init__(
        self,
        app: "Terminal",
        rect: Rect,
        command: Sequence[str] | None = None,
    ) -> None:
        super().__init__(
            title="Terminal",
            rect=rect,
            closable=True,
            minimisable=True,
            maximisable=True,
            resizable=True,
        )
        self.app = app
        self.keep_open = bool(command)
        """Whether the window stays open once its program ends (showing how
        it ended), which it does for a command it was given; one running
        the shell closes."""
        interior = self.interior
        self.view = self.add(
            widget=TerminalView(
                row=0,
                column=0,
                width=interior.width,
                height=interior.height,
                command=command,
                on_output=self._shown,
                on_exit=self._ended,
                send_mouse=app.send_mouse,
                name="terminal",
            ),
            grow=Grow.ALL,
        )
        self.view.default_style = self.body_style
        self._show_title()

    def _shown(self, view: TerminalView) -> None:
        del view
        self._show_title()

    def _ended(self, view: TerminalView) -> None:
        """The program has ended: close, or (for a command given) say how it
        ended."""
        if not self.keep_open:
            self.app.close(window=self)
            return
        view.screen.feed(text=f"\r\n[Ended: exit code {view.exit_code}]")
        self._show_title()

    def _show_title(self) -> None:
        view = self.view
        title = view.screen.title or program_name(argv=view.command)
        self.title = f"{title} (ended)" if view.exit_code is not None else title

    def footer_parts(self) -> list[str]:
        """At the foot of the frame: the terminal's size, as COLSxLINES,
        while scrolled back, ``↑`` and how far, and ``Mouse`` while the
        mouse goes to the program."""
        screen = self.view.screen
        parts = [f"{screen.columns}x{screen.lines}"]
        if self.view.back:
            parts.append(f"{SCROLLED_BACK}{self.view.back}")
        if self.view.is_mouse_for_program:
            parts.append(MOUSE_TO_PROGRAM)
        return parts

    def request_close(self) -> bool:
        """Close, ending the program; but first ask, where it can be told,
        if the shell is running a command."""
        if self.view.is_running and self.view.pty.foreground_busy():
            manager = self.manager
            if manager is not None and manager.is_running:
                dialog = confirm(
                    title="Terminal",
                    message="A program is still running in this terminal.\n"
                    "Close it anyway?",
                    ok_label="&Close",
                )
                if manager.execute(dialog=dialog) != "ok":
                    return False
        self.view.close()
        return True


class Terminal(Application):
    """Command-line programs (the user's shell, by default), each in a
    window of its own."""

    name = "Terminal"

    def __init__(self, command: Sequence[str] = ()) -> None:
        super().__init__()
        self.command = list(command)
        """The command the first window runs; the user's shell if empty."""
        self.send_keys = Menu(title="Send key", items=[], on_open=self._fill_send_keys)
        """Terminal > Send key: the keys the desktop keeps, to send to the
        program in the front window."""
        self.send_mouse = True
        """Whether the mouse goes to a program that asks to be told of it,
        in every window (Terminal > Mouse to programs), rather than
        selecting text."""
        self._telling = 0  # messages waiting to be seen, before ending

    def start(self) -> None:
        self.menus = self._menus()
        self.new_window(command=self.command or None)

    def shortcuts_changed(self) -> None:
        """The shortcuts have changed: the menus' key hints, and the keys
        Send key offers, follow them."""
        self.menus = self._menus()

    def _place(self) -> Rect:
        """Where the next window goes: as big as fits, up to 80 by 25
        inside, each a little down and right of the one before."""
        assert self.manager is not None
        workspace = self.manager.workspace
        step = len(self.windows) % 6
        width = max(20, min(82, workspace.width - 2 * step - 2))
        height = max(6, min(27, workspace.height - step - 1))
        return Rect(
            row=workspace.row + step, column=2 * step, height=height, width=width
        )

    def new_window(self, command: Sequence[str] | None = None) -> TerminalWindow | None:
        """Open a window running ``command`` (the user's shell, if
        ``None``). If it cannot be started, say why."""
        window = TerminalWindow(app=self, rect=self._place(), command=command)
        self.open(window=window)
        try:
            window.view.start()
        except OSError as error:
            self._cannot_start(name=program_name(argv=window.view.command), error=error)
            self.close(window=window)
            return None
        return window

    def _cannot_start(self, name: str, error: OSError) -> None:
        """Say why a program could not be started: once the desktop is
        running, which it may not be yet, as Terminal starts. Terminal
        carries on until the message has been seen, even with no window."""
        manager = self.manager
        if manager is None:
            return
        reason = error.strerror or str(error)
        dialog = information(
            title="Terminal", message=f"Cannot start {name}:\n{reason}"
        )
        self._telling += 1

        def tell() -> None:
            manager.execute(dialog=dialog)
            self._telling -= 1
            self._end_if_empty()

        manager.call_when_running(callback=tell)

    def _front(self) -> TerminalWindow | None:
        window = self.active_window
        return window if isinstance(window, TerminalWindow) else None

    def _on_front(self, act: ViewAction) -> Callable[[], None]:
        """A menu action on the front window's terminal, if there is one."""

        def action() -> None:
            window = self._front()
            if window is not None:
                act(view=window.view)

        return action

    # Ending

    def window_closed(self, window: Window) -> None:
        """A window has closed: its program ends; and with the last of them,
        so does Terminal."""
        super().window_closed(window=window)
        if isinstance(window, TerminalWindow):
            window.view.close()
        self._end_if_empty()

    def _end_if_empty(self) -> None:
        """End once the last window has closed (and any message saying why
        a program could not start has been seen)."""
        if not self.windows and not self._telling and self.is_running:
            self.quit()

    def can_close(self) -> bool:
        busy = [
            window
            for window in self.windows
            if isinstance(window, TerminalWindow)
            and window.view.is_running
            and window.view.pty.foreground_busy()
        ]
        manager = self.manager
        if not busy or manager is None or not manager.is_running:
            return True
        dialog = confirm(
            title="Terminal",
            message="Programs are still running in Terminal.\nEnd them?",
            ok_label="&End them",
        )
        return manager.execute(dialog=dialog) == "ok"

    def quit(self) -> None:
        for window in self.windows:
            if isinstance(window, TerminalWindow):
                window.view.close()
        super().quit()

    # Menus

    def _menus(self) -> list[Menu]:
        """Terminal's menu bar, opened with F10, Alt+T or Alt+E."""
        return [
            Menu(title="&Terminal", items=self._terminal_items()),
            Menu(title="&Edit", items=self._edit_items()),
        ]

    def _terminal_items(self) -> list[MenuItem]:
        assert self.manager is not None
        hint = self.manager.shortcuts.hint
        items = [
            MenuItem(
                label="&New window",
                action=self.new_window,
                status="Opens another window, with a shell of its own",
            )
        ]
        found = powershell() if sys.platform == "win32" else None
        if found is not None:
            items.append(
                MenuItem(
                    label="New &PowerShell window",
                    action=lambda: self.new_window(command=[found]),
                    status="Opens a window running PowerShell",
                )
            )
        self._fill_send_keys(menu=self.send_keys)
        items += [
            MenuItem(
                label="Send &key",
                submenu=self.send_keys,
                status="Sends one of the keys the desktop keeps to the program",
                enabled=self.has_window,
            ),
            MenuItem(
                label=marked(label="&Mouse to programs", on=self.send_mouse),
                action=self.toggle_mouse,
                shortcut=hint(action="terminal_mouse"),
                status="Clicks go to a program that asks for them, or select text",
            ),
            separator(),
            MenuItem(
                label="&Close",
                action=self._close_front,
                shortcut=hint(action="close_window"),
                status="Closes this window, ending its program",
                enabled=self.has_window,
            ),
            MenuItem(
                label="E&xit",
                action=self.exit,
                status="Closes every window, ending their programs",
            ),
        ]
        return items

    def toggle_mouse(self) -> None:
        """Have the mouse go to programs that ask for it, in every window,
        or select text instead (Terminal > Mouse to programs)."""
        self.send_mouse = not self.send_mouse
        for window in self.windows:
            if isinstance(window, TerminalWindow):
                window.view.send_mouse = self.send_mouse
        self.menus = self._menus()

    def _close_front(self) -> None:
        window = self._front()
        if window is not None:
            self.close(window=window)

    def _edit_items(self) -> list[MenuItem]:
        assert self.manager is not None
        hint = self.manager.shortcuts.hint
        return [
            MenuItem(
                label="&Copy",
                action=self._on_front(act=lambda view: view.copy()),
                shortcut=hint(action="terminal_copy"),
                status="Copies the text selected with the mouse",
                enabled=self.has_window,
            ),
            MenuItem(
                label="&Paste",
                action=self._on_front(act=lambda view: view.paste()),
                shortcut=hint(action="terminal_paste"),
                status="Sends the clipboard's text to the program, as typed",
                enabled=self.has_window,
            ),
            MenuItem(
                label="Select &all",
                action=self._on_front(act=lambda view: view.select_all()),
                status="Selects everything, the scrollback too",
                enabled=self.has_window,
            ),
            separator(),
            MenuItem(
                label="Clear &scrollback",
                action=self._on_front(act=lambda view: view.clear_scrollback()),
                status="Forgets the lines scrolled off the top",
                enabled=self.has_window,
            ),
        ]

    def reserved_keys(self) -> list[str]:
        """The keys the desktop keeps, as the shortcuts in use say, each
        once: the ones Send key offers."""
        assert self.manager is not None
        shortcuts = self.manager.shortcuts
        keys: list[str] = []
        for action in RESERVED_ACTIONS:
            for key in shortcuts.keys(action=action):
                if key not in keys and encode_key(key=key) is not None:
                    keys.append(key)
        return keys

    def _fill_send_keys(self, menu: Menu) -> None:
        menu.items[:] = [
            MenuItem(
                label=pretty_key(name=key),
                action=self._on_front(act=self._sender(key=key)),
                status=f"Sends {pretty_key(name=key)} to the program",
                enabled=self.has_window,
            )
            for key in self.reserved_keys()
        ]

    @staticmethod
    def _sender(key: str) -> ViewAction:
        """What sends ``key`` to a terminal's program."""

        def send(*, view: TerminalView) -> None:
            data = encode_key(key=key, app_cursor_keys=view.screen.app_cursor_keys)
            if data is not None:
                view.send(data=data)

        return send


if __name__ == "__main__":
    raise SystemExit(Terminal(command=sys.argv[1:]).run())
