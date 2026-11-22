"""The application side of a hosted application."""

import json
import os
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from multiprocessing.connection import Client, Connection, Pipe, wait
from pathlib import Path
from typing import Any, cast

from dasha import theme
from dasha.application import Application
from dasha.border import Border
from dasha.clipboard import CLIPBOARD, TEXT, Clipboard, ClipboardItem
from dasha.dialog import Dialog, Popup
from dasha.manager import PresentationManager, drawn_active
from dasha.menu import Menu
from dasha.printing import say
from dasha.processes import DESKTOP_PID_VARIABLE, watch_parent
from dasha.protocol import (
    ADDRESS_VARIABLE,
    MINIMUM_VERSION,
    PROTOCOL_VERSION,
    WINDOW_FRAME,
    WINDOW_STYLES,
    Message,
    StyleTable,
    decode_mouse,
    decode_rect,
    encode_border,
    encode_rect,
    encode_row,
    encode_style,
    receive,
    send,
)
from dasha.shortcuts import Shortcuts
from dasha.statusbar import status_text
from dasha.style import Style
from dasha.widgets import Widget
from dasha.window import Window


def encode_menus(menus: Sequence[Menu]) -> list[dict[str, object]]:
    """Menus encoded for the desktop.

    :param menus: The menus.
    """

    def items(menu: Menu) -> list[dict[str, object]]:
        return [
            {
                "label": item.label,
                "shortcut": item.shortcut,
                "status": item.status,
                "separator": item.is_separator,
                "enabled": item.is_available,
                "submenu": (
                    None if item.submenu is None else encode_menus([item.submenu])[0]
                ),
            }
            for item in menu.items
        ]

    return [
        {
            "title": menu.title,
            "after_window": menu.after_window,
            "on_open": menu.on_open is not None,
            "items": items(menu),
        }
        for menu in menus
    ]


def menu_at(menus: Sequence[Menu], path: Sequence[Any]) -> Menu | None:
    """The menu or submenu at a path, if any.

    :param menus: The menus.
    :param path: Menu index, then item indexes.
    """
    try:
        menu = menus[int(path[0])]
        for step in path[1:]:
            submenu = menu.items[int(step)].submenu
            if submenu is None:
                return None
            menu = submenu
    except (IndexError, TypeError, ValueError):
        return None
    return menu


def look_of(window: Window) -> str:
    """A window's frame look.

    :param window: The window.
    """
    if isinstance(window, Popup):
        return "popup"
    return "dialog" if isinstance(window, Dialog) else "window"


def colours_of(window: Window) -> dict[str, list[object]]:
    """A window's colours that differ from the theme.

    :param window: The window.
    """
    theme_class = Dialog if isinstance(window, Dialog) else Window
    return {
        name: encode_style(getattr(window, name))
        for name in WINDOW_STYLES
        if getattr(window, name) != getattr(theme_class, name)
    }


def frame_of(window: Window) -> dict[str, object]:
    """A window's frame parts that differ from the theme.

    :param window: The window.
    """
    if isinstance(window, Popup):
        theme_class: type[Window] = Popup
    else:
        theme_class = Dialog if isinstance(window, Dialog) else Window
    frame: dict[str, object] = {}
    for name in WINDOW_FRAME:
        value = getattr(window, name)
        if value == getattr(theme_class, name):
            continue
        if isinstance(value, Border):
            frame[name] = encode_border(value)
        elif isinstance(value, Style):
            frame[name] = encode_style(value)
        else:
            frame[name] = value
    return frame


@dataclass
class _Sent:
    """What the desktop last knew of a window."""

    state: dict[str, object] = field(default_factory=dict)
    rows: list[list[list[object]]] = field(default_factory=list)
    cursor: tuple[int, int] | None = None


class _Waker:
    """Wake-ups for an application's loop."""

    def __init__(self) -> None:
        self.reader, self._writer = Pipe(duplex=False)
        """What the loop waits on (with ``wait``)."""
        self._lock = threading.Lock()
        self._sent = False

    def wake(self) -> None:
        """End the loop's wait; thread-safe."""
        with self._lock:
            if self._sent or self._writer.closed:
                return
            try:
                self._writer.send_bytes(b"!")
            except OSError:
                return
            self._sent = True

    def take(self) -> None:
        """Clear the pending wake-up."""
        with self._lock:
            self._sent = False
            while self.reader.poll():
                self.reader.recv_bytes()

    def close(self) -> None:
        """Close the pipe; waking does nothing after this."""
        with self._lock:
            self.reader.close()
            self._writer.close()


class ClientManager(PresentationManager):
    """Presentation manager for a hosted application.

    :param connection: Connection to the desktop.
    :param welcome: The desktop's welcome message.
    """

    def __init__(self, connection: Connection, welcome: Message) -> None:
        super().__init__(shortcuts=Shortcuts(welcome.get("shortcuts") or {}))
        self.connection = connection
        self.version: int = welcome.get("version", PROTOCOL_VERSION)
        """The protocol version agreed with the desktop."""
        columns, lines = welcome["size"]
        self._size = (int(columns), int(lines))
        self._running = True
        self._ids: dict[int, Window] = {}
        self._window_ids: dict[Window, int] = {}
        self._next_id = 1
        self._sent: dict[int, _Sent] = {}
        self._active: int | None = None
        self._modal: list[Dialog] = []
        self._quiet_clipboard = False
        self._sent_menus = ""
        self._waker = _Waker()
        CLIPBOARD.listeners.append(self._clipboard_changed)
        name = welcome.get("theme_name")
        self.theme_name = name if isinstance(name, str) else None
        if isinstance(welcome.get("clipboard"), str):
            self._clipboard_arrived({"type": "clipboard", "text": welcome["clipboard"]})

    @property
    def can_show_dialogs(self) -> bool:
        return self._running

    # Windows

    def window_id(self, window: Window) -> int:
        """The desktop's id for a window.

        :param window: The window.
        """
        number = self._window_ids.get(window)
        if number is None:
            number = self._window_ids[window] = self._next_id
            self._ids[number] = window
            self._next_id += 1
        return number

    def add(self, window: Window) -> None:
        super().add(window)
        self.window_id(window)  # told to the desktop with the next flush

    def remove(self, window: Window) -> None:
        number = self._window_ids.pop(window, None)
        if number is not None:
            del self._ids[number]
            if self._sent.pop(number, None) is not None:
                self._send("close", id=number)
        super().remove(window)

    def bring_to_front(self, window: Window) -> None:
        super().bring_to_front(window)
        self._request(window, "front")

    def send_to_back(self, window: Window) -> None:
        self._request(window, "send_to_back")

    def activate_next(self) -> None:
        self._send("request", id=None, op="next_window")

    def activate_previous(self) -> None:
        self._send("request", id=None, op="previous_window")

    def maximise(self, window: Window) -> None:
        self._request(window, "maximise")

    def minimise(self, window: Window) -> None:
        self._request(window, "minimise")

    def restore(self, window: Window) -> None:
        self._request(window, "restore")

    def toggle_maximise(self, window: Window) -> None:
        self._request(window, "toggle_maximise")

    def start_moving(self, window: Window | None = None) -> None:
        self._request(window, "move")

    def start_resizing(self, window: Window | None = None) -> None:
        self._request(window, "resize")

    def request_exit(self) -> None:
        self._send("request", id=None, op="exit")

    def set_theme(self, name: str | Path, *, remember: bool | None = None) -> bool:
        """Ask the desktop to change theme; always ``True``.

        :param name: Theme name or file path.
        :param remember: Whether to remember the choice, if specified.
        """
        del remember  # the desktop's to decide
        text = str(name)
        if isinstance(name, Path) or any(m in text for m in ("/", "\\", ".json")):
            text = str(Path(text).expanduser().resolve())
        self._send("theme", name=text)
        return True

    def _request(self, window: Window | None, op: str) -> None:
        self.flush()  # so the desktop knows the window first
        number = self._window_ids.get(window) if window is not None else None
        self._send("request", id=number, op=op)

    # Dialogs

    @property
    def answering_dialog(self) -> Dialog | None:
        return self._modal[-1] if self._modal else None

    def execute(self, dialog: Dialog) -> str | None:
        """Show a dialog and wait for its answer.

        :param dialog: The dialog.
        """
        dialog.result = None
        if dialog.centred:
            dialog.centre(self.workspace)
        self._modal.append(dialog)
        try:
            if dialog not in self._windows:
                self.add(dialog)
            self.bring_to_front(dialog)
            while dialog.result is None and self._running:
                self.pump()
        finally:
            self._modal.remove(dialog)
            if dialog in self._windows:
                self.remove(dialog)
        return dialog.result if self._running else None

    # The loop

    def serve(self) -> None:
        """Handle messages until the application ends."""
        try:
            self._now_running()
            while self._running:
                self.pump()
        finally:
            self.stop_listening()
            if not self.connection.closed:
                self._send("bye")
                self.connection.close()
            self._waker.close()

    def pump(self) -> None:
        """Update the desktop and handle one message."""
        wakes = [wake for w in self._widgets() if (wake := w.wake_time()) is not None]
        timeout = max(0.0, min(wakes) - time.monotonic()) if wakes else None
        if self._from_threads:
            timeout = 0.0
        try:
            if not self.connection.poll(0):
                self.flush()
            if self._running:
                ready = wait([self.connection, self._waker.reader], timeout)
                if self._waker.reader in ready:
                    self._waker.take()
                if self.connection in ready:
                    self.handle(receive(self.connection))
        except (EOFError, OSError):
            self._running = False  # the desktop has gone
            return
        self.run_timers(time.monotonic())
        self._call_from_threads()

    def wake(self) -> None:
        """Interrupt the wait for a message; thread-safe."""
        self._waker.wake()

    def _send(self, kind: str, **fields: object) -> None:
        if self.connection.closed:
            return
        try:
            send(self.connection, kind, **fields)
        except OSError:
            self._running = False

    # Telling the desktop

    def flush(self) -> None:
        """Send changed menus and windows."""
        menus = json.dumps(
            encode_menus([menu for app in self._applications for menu in app.menus])
        )
        if menus != self._sent_menus:
            self._send("menus", menus=json.loads(menus))
            self._sent_menus = menus
        for window in list(self._windows):
            self._flush_window(window)

    def _state(self, window: Window) -> dict[str, object]:
        focused = window.focused
        width, height = window.content_size
        state: dict[str, object] = {
            "title": window.title,
            "footer": window.footer_parts(),
            "rect": encode_rect(window.rect),
            "maximised": window.maximised,
            "flags": [
                window.resizable,
                window.maximisable,
                window.minimisable,
                window.closable,
            ],
            "look": look_of(window),
            "colours": colours_of(window),
            "modal": window in self._modal,
            "outside": window.close_on_outside_click,
            "status": status_text(focused) or status_text(window),
            "hints": [] if focused is None else focused.key_help(self.shortcuts),
            "content": [width, height],
            "scroll": [window.scroll_row, window.scroll_column],
        }
        if self.version >= 2:  # version 1 has neither
            state["min_size"] = [window.min_width, window.min_height]
            state["frame"] = frame_of(window)
            state["every_key"] = isinstance(window, Dialog) and window.takes_every_key
        return state

    def _flush_window(self, window: Window) -> None:
        number = self.window_id(window)
        sent = self._sent.setdefault(number, _Sent())
        state = self._state(window)
        if state != sent.state:
            self._send("window", id=number, **state)
            sent.state = state
        canvas = window.render_interior(self.looks_active(window))
        table = StyleTable()
        rows = [
            encode_row([canvas.cell(row, c) for c in range(canvas.width)], table)
            for row in range(canvas.height)
        ]
        # Compared by their colours, not their numbers in this message's
        # table: a row whose colours alone change (a window's body colours,
        # say) keeps the same numbers, but must be sent again.
        shown = [
            [[text, table.styles[cast(int, style)]] for text, style in runs]
            for runs in rows
        ]
        size_changed = len(shown) != len(sent.rows)
        changed = [
            [number_, runs]
            for number_, runs in enumerate(rows)
            if size_changed or shown[number_] != sent.rows[number_]
        ]
        if changed or canvas.cursor != sent.cursor or size_changed:
            self._send(
                "paint",
                id=number,
                size=[canvas.width, canvas.height],
                rows=changed,
                styles=table.styles,
                cursor=canvas.cursor,
            )
            sent.rows, sent.cursor = shown, canvas.cursor

    def _told(self, window: Window, **changes: object) -> None:
        """Record what the desktop knows.

        :param window: The window.
        :param changes: Known values.
        """
        sent = self._sent.get(self.window_id(window))
        if sent is not None:
            sent.state.update(changes)

    # Hearing from the desktop

    def handle(self, message: Message) -> None:
        """Handle a message from the desktop.

        :param message: The message.
        """
        handlers: dict[str, Callable[[Message], None]] = {
            "quit": self._quit_message,
            "ping": lambda _: self._send("pong"),
            "may_close": self._may_close,
            "size": self._resized,
            "clipboard": self._clipboard_arrived,
            "theme": self._theme_arrived,
            "shortcuts": lambda m: self.set_shortcuts(Shortcuts(m["shortcuts"])),
            "active": lambda m: self._activated(m.get("id")),
            "menu": self._menu_message,
            "menu_open": self._menu_opening,
            "help": lambda _: self.press_help(),
        }
        handler = handlers.get(message["type"])
        if handler is not None:
            handler(message)
            return
        window = self._ids.get(message.get("id", -1))
        if window is not None:
            self._window_message(window, message["type"], message)

    def _quit_message(self, message: Message) -> None:
        del message
        for application in list(self._applications):
            application.quit()
        self._running = False

    def _theme_arrived(self, message: Message) -> None:
        """Apply the desktop's new theme.

        :param message: The theme message.
        """
        colours = theme.build_theme(json.loads(str(message["theme"])))
        name = message.get("name")
        self.use_theme(colours, name if isinstance(name, str) else None)

    def _may_close(self, message: Message) -> None:
        del message
        ok = all(application.can_close() for application in self.applications)
        self._send("answer", question="may_close", ok=ok)

    def _resized(self, message: Message) -> None:
        self._size = (int(message["columns"]), int(message["lines"]))

    def _menu_message(self, message: Message) -> None:
        """Handle a chosen menu item.

        :param message: The menu message.
        """
        if not self._modal:
            menus = [menu for app in self._applications for menu in app.menus]
            self._menu_chosen(menus, message["path"])
        elif isinstance(key := message.get("key"), str):
            self._input(self._modal[-1], "key", {"type": "key", "key": key})

    def _menu_opening(self, message: Message) -> None:
        """Bring a menu up to date as it opens.

        :param message: The menu_open message.
        """
        menus = [menu for app in self._applications for menu in app.menus]
        menu = menu_at(menus, message["path"])
        if menu is not None and menu.on_open is not None:
            menu.on_open(menu)

    def looks_active(self, window: Window) -> bool:
        """Whether a window looks active.

        :param window: The window.
        """
        number = self._active
        active = self._ids.get(number) if number is not None else None
        return drawn_active(window, active, self._windows)

    def _activated(self, number: object) -> None:
        self._active = number if isinstance(number, int) else None
        window = self._ids.get(self._active) if self._active is not None else None
        if window is not None and window in self._windows:
            super().bring_to_front(window)  # keep this side's order the same

    def _blocked(self, window: Window) -> bool:
        """Whether a dialog elsewhere blocks a window.

        :param window: The window.
        """
        return bool(self._modal) and window is not self._modal[-1]

    def _window_message(self, window: Window, kind: str, message: Message) -> None:
        if kind == "rect":
            rect = decode_rect(message["rect"])
            window.maximised = bool(message["maximised"])
            window.rect = rect
            self._told(window, rect=encode_rect(rect), maximised=window.maximised)
        elif kind == "scroll":
            window.scroll_to(int(message["row"]), int(message["column"]))
            self._told(window, scroll=[window.scroll_row, window.scroll_column])
        elif kind == "outside":
            if isinstance(window, Dialog) and window.close_on_outside_click:
                window.cancel()
        elif self._blocked(window):
            # A dialog of this application's is waiting for an answer. Typing
            # sent before the desktop knew of it goes to it, as it would in
            # one process; clicks and the rest are for the window: ignored.
            if kind in ("key", "release", "paste"):
                self._input(self._modal[-1], kind, message)
        elif kind == "close_request":
            self.close(window)
        else:
            self._input(window, kind, message)

    def _input(self, window: Window, kind: str, message: Message) -> None:
        if kind == "key":
            key = str(message["key"])
            if not window.handle_key(key, self.shortcuts):
                if self.shortcuts.matches("help", key):
                    self.press_help()
                elif isinstance(window, Dialog) and self.shortcuts.matches(
                    "dialog_cancel", key
                ):
                    window.cancel()
        elif kind == "release":
            window.handle_key_release(str(message["key"]))
        elif kind == "paste":
            window.handle_paste(str(message["text"]))
        elif kind == "mouse":
            event = decode_mouse(message["event"])
            if window.handle_mouse(event) or event.action != "scroll":
                return
            notch = 3  # the wheel, where no widget took it: the window scrolls
            amount = -notch if event.button in ("up", "left") else notch
            if event.button in ("left", "right") or event.shift:
                window.scroll_by(0, amount)
            else:
                window.scroll_by(amount, 0)

    @staticmethod
    def _menu_chosen(menus: Sequence[Menu], path: Sequence[Any]) -> None:
        """Run the menu item at a path.

        :param menus: The menus.
        :param path: Menu and item indexes.
        """
        if not path:
            return
        try:
            menu = menus[int(path[0])]
            item = menu.items[int(path[1])]
            for step in path[2:]:
                assert item.submenu is not None and item.is_available
                item = item.submenu.items[int(step)]
        except (IndexError, AssertionError, ValueError):
            return
        if item.is_available and item.action is not None:
            item.action()

    # The clipboard, shared through the desktop

    def stop_listening(self) -> None:
        """Stop sending clipboard changes."""
        if self._clipboard_changed in CLIPBOARD.listeners:
            CLIPBOARD.listeners.remove(self._clipboard_changed)

    def _clipboard_changed(self, clipboard: Clipboard) -> None:
        item = clipboard.item
        if self._quiet_clipboard or item is None or item.type != TEXT:
            return
        self._send("clipboard", text=item.data)

    def _clipboard_arrived(self, message: Message) -> None:
        self._quiet_clipboard = True
        try:
            CLIPBOARD.copy(ClipboardItem(TEXT, str(message["text"])))
        finally:
            self._quiet_clipboard = False


def connect() -> tuple[Connection, str] | None:
    """Connect to the desktop, or ``None``."""
    address = os.environ.pop(ADDRESS_VARIABLE, "")
    secret, _, token = sys.stdin.readline().strip().partition(" ")
    try:
        client = Client(address, authkey=bytes.fromhex(secret))
        # Needed on Windows only, where Client may give a PipeConnection.
        connection = cast(Connection, client)  # type: ignore[redundant-cast,unused-ignore]
    except (OSError, ValueError) as error:
        say(f"dasha: cannot reach the desktop: {error}", file=sys.stderr)
        return None
    return connection, token


def run_hosted(application: Application) -> int:
    """Run an application on the desktop.

    :param application: The application.
    """
    connected = connect()
    if connected is None:
        return 1
    connection, token = connected
    desktop = os.environ.pop(DESKTOP_PID_VARIABLE, "")
    # If the desktop goes, so does this, hung or not.
    watch_parent(int(desktop) if desktop.isdigit() else None)
    try:
        send(
            connection,
            "hello",
            version=PROTOCOL_VERSION,
            versions=[MINIMUM_VERSION, PROTOCOL_VERSION],
            token=token,
            name=application.name,
            pid=os.getpid(),
        )
        welcome = receive(connection)
    except (EOFError, OSError):
        say("dasha: the desktop went away", file=sys.stderr)
        return 1
    if welcome["type"] != "welcome":
        say(f"dasha: refused: {welcome.get('reason', '?')}", file=sys.stderr)
        return 1
    if welcome.get("version") not in range(MINIMUM_VERSION, PROTOCOL_VERSION + 1):
        say(
            "dasha: the desktop chose a protocol version this does not speak",
            file=sys.stderr,
        )
        return 1
    if welcome.get("theme"):
        theme.apply_theme(theme.build_theme(json.loads(str(welcome["theme"]))))
    Widget.key_releases = bool(welcome.get("key_releases"))
    try:
        manager = ClientManager(connection, welcome)
        manager.quit_when_empty = True
        manager.launch(application)
        manager.serve()
    finally:
        Widget.key_releases = False  # as the desktop's own run leaves it
    return 0
