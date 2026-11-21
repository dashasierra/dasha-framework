"""The desktop side of applications in other processes."""

# pylint: disable=too-many-lines

import json
import os
import queue
import re
import secrets
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Sequence
from functools import partial
from multiprocessing import AuthenticationError
from multiprocessing.connection import (
    Client,
    Connection,
    Listener,
    answer_challenge,
    deliver_challenge,
)
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import dasha
from dasha import logs, theme
from dasha.inbox import Inbox
from dasha.clipboard import CLIPBOARD
from dasha.dialog import question
from dasha.processes import DESKTOP_PID_VARIABLE, ProcessTree
from dasha.events import MouseEvent
from dasha.menu import Menu, MenuItem, separator
from dasha.registry import LEND_FOLDER, lend_folder, venv_has_dasha, venv_python
from dasha.remote import (
    MAX_MENU_DEPTH,
    MAX_MENU_ITEMS,
    MAX_WINDOWS,
    RemoteApplication,
    RemoteWindow,
    application_name,
    never_enabled,
    one_line,
)
from dasha.protocol import (
    ADDRESS_VARIABLE,
    MAX_MESSAGE,
    CLOSED_UNDER_IT,
    MINIMUM_VERSION,
    PROTOCOL_VERSION,
    TimedConnection,
    Message,
    ProtocolError,
    agree_version,
    close as close_connection,
    encode,
    encode_rect,
    refuse,
)
from dasha.shortcuts import DESKTOP_KEYS, pretty_key
from dasha.widgets import Widget

if TYPE_CHECKING:
    from dasha.manager import PresentationManager


def _squeezed(name: str) -> str:
    """A name lowercased without spaces, hyphens or underscores.

    :param name: The name.
    """
    return "".join(name.replace("-", " ").replace("_", " ").split()).casefold()


class AppHost:  # pylint: disable=too-many-instance-attributes
    """One application in its own process.

    :param server: The application server.
    :param target: ``MODULE:CLASS`` or a script.
    :param name: Application name.
    :param venv: Virtual environment folder, if any.
    :param guessed_name: Whether the name was made up.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        server: "AppServer",
        target: str,
        name: str,
        venv: str | None = None,
        *,
        guessed_name: bool = False,
    ) -> None:
        self.server = server
        self.manager = server.manager
        self.target = target
        """What it runs."""
        self.venv = venv
        """The virtual environment whose Python runs it, if not this one."""
        self.guessed_name = guessed_name
        """Whether the name was made up."""
        self.token = secrets.token_hex(16)
        self.application = RemoteApplication(self, name)
        self.windows: dict[int, RemoteWindow] = {}
        self.connection: Connection | None = None
        self.process: "subprocess.Popen[bytes] | None" = None
        self.log_path: Path | None = None
        self.tree: ProcessTree | None = None
        self.version = PROTOCOL_VERSION
        """The protocol version agreed with the application."""
        self.pid: int | None = None
        """The application's process id."""
        self.ended = False
        self.said_bye = False
        self.stopping = False
        self.responding = True
        """False once it has left a ping unanswered for ``hang_timeout``."""
        self.started_at = time.monotonic()
        self.last_heard = self.started_at
        self.load_asked_at = self.started_at
        """When the load wait last started."""
        self._ping_sent: float | None = None
        self._outbox: "queue.Queue[bytes | None]" = queue.Queue()
        self._told_active: int | None = None
        self._told_size: tuple[int, int] | None = None
        self.told_clipboard: str | None = None
        """The clipboard's text as this application last had it."""

    @property
    def name(self) -> str:
        """The application's name."""
        return self.application.name

    @property
    def is_loading(self) -> bool:
        """Whether it has started but shows nothing yet."""
        return not self.ended and not self.application.is_running

    def loaded(self) -> None:
        """Make it the active application once loaded."""
        self.manager.add_application(self.application)
        closing = self.server.closing
        if closing is not None:
            closing.add(self)
            self.send("may_close")

    def start(self) -> None:
        """Start the process."""
        server = self.server
        safe = re.sub(r"[^A-Za-z0-9]+", "-", self.name).strip("-").lower() or "app"
        folder = server.log_folder
        # Only this user may read the logs (on POSIX; Windows ignores modes).
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        server.prune_logs()
        # Unique, but not part of the token, which stays secret.
        unique = secrets.token_hex(3)
        self.log_path = folder / f"{safe}-{time.strftime('%Y%m%d-%H%M%S')}-{unique}.log"
        python = self.python()
        environment = self.environment()
        options: dict[str, Any] = {}
        if os.name == "nt":
            options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
        with open(os.open(self.log_path, flags, 0o600), "ab") as log:
            # Its own job (Windows) or process group (elsewhere): out of the
            # terminal's way, and ended together with whatever it starts.
            # -P: the folder the desktop runs in does not go first on the
            # import path, as -m would put it, so a json.py (say) planted
            # there is not imported in place of the real one.
            self.tree = ProcessTree.start(
                [str(python), "-P", "-m", "dasha.host", self.target],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=log,
                env=environment,
                **options,
            )
        self.process = self.tree.process
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(f"{server.authkey.hex()} {self.token}\n".encode())
            self.process.stdin.close()
        except OSError:
            pass  # it has gone already; poll() notices

    def python(self) -> Path:
        """The Python that runs the application."""
        if self.venv is None:
            return Path(sys.executable)
        python = venv_python(self.venv)
        if not python.exists():
            raise FileNotFoundError(f"no Python in {self.venv}")
        return python

    def environment(self) -> dict[str, str]:
        """Environment variables for the child process."""
        environment = dict(os.environ)
        environment[ADDRESS_VARIABLE] = self.server.address
        environment[DESKTOP_PID_VARIABLE] = str(os.getpid())
        if self.venv is None:
            package_root = str(Path(dasha.__file__).resolve().parent.parent)
            paths = [package_root, environment.get("PYTHONPATH", "")]
        else:
            for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
                environment.pop(name, None)
            environment["VIRTUAL_ENV"] = self.venv
            scripts = str(venv_python(self.venv).parent)
            environment["PATH"] = os.pathsep.join(
                [scripts, environment.get("PATH", "")]
            )
            lend = not venv_has_dasha(self.venv)
            paths = [str(lend_folder(self.server.lend_folder))] if lend else []
        if any(paths):
            environment["PYTHONPATH"] = os.pathsep.join(path for path in paths if path)
        return environment

    # Talking to it

    def connected(self, connection: Connection) -> None:
        """Record the connection and start sending.

        :param connection: The connection.
        """
        self.connection = connection
        self.last_heard = self.load_asked_at = time.monotonic()
        threading.Thread(target=self._send_all, args=(connection,), daemon=True).start()

    def _send_all(self, connection: Connection) -> None:
        """Send the outbox on its own thread.

        :param connection: The connection.
        """
        while (data := self._outbox.get()) is not None:
            try:
                connection.send_bytes(data)
            except CLOSED_UNDER_IT:
                return  # gone (or closed meanwhile); the reader notices

    def send(self, kind: str, **fields: object) -> None:
        """Queue a message, if connected.

        :param kind: Message kind.
        :param fields: Message fields.
        """
        if self.connection is not None and not self.ended:
            self._outbox.put(encode(kind, **fields))

    # Staying alive

    def heard(self) -> None:
        """Record that a message arrived."""
        self.last_heard = time.monotonic()
        self._ping_sent = None
        if not self.responding:
            self._set_responding(True)

    def _set_responding(self, responding: bool) -> None:
        self.responding = responding
        for window in self.windows.values():
            window.show_title()

    def check(self, now: float) -> None:
        """Ping, detect hangs, or end if never connected.

        :param now: The current ``time.monotonic``.
        """
        server = self.server
        if self.connection is None:
            if now - self.started_at > server.start_timeout:
                self.stopping = True
                self.end_now()
                server.notices.append(
                    ("Cannot start", f"{self.name} did not start in time.")
                )
            return
        if self._ping_sent is None:
            if now - self.last_heard >= server.ping_interval:
                self._ping_sent = now
                self.send("ping")
        elif self.responding and now - self._ping_sent >= server.hang_timeout:
            self._set_responding(False)

    def offer_to_end(self) -> None:
        """Offer to end an unresponsive application."""
        manager = self.manager
        if not manager.can_show_dialogs:
            return
        dialog = question(
            self.name,
            f"{self.name} is not responding.\n\n"
            "End it now (losing unsaved work), or wait for it?",
            [("&End now", "end"), ("&Wait", "wait")],
            status="End the application, or give it more time",
        )
        if manager.execute(dialog) == "end" and not self.responding:
            self.end_now()

    def ask_about_loading(self) -> None:
        """Offer to end a slow-loading application."""
        self.load_asked_at = time.monotonic()
        dialog = question(
            self.name,
            f"{self.name} has not finished starting.\n\nEnd it now, or wait for it?",
            [("&End now", "end"), ("&Wait", "wait")],
            status="End the application, or give it more time",
        )
        answer = self.manager.execute(dialog)
        self.load_asked_at = time.monotonic()
        if answer == "end" and self.is_loading:  # not if it started meanwhile
            self.end_now()

    def end_now(self) -> None:
        """End the application and its children now."""
        self.stopping = True
        if self.tree is not None:
            self.tree.kill()
        self.finish(crashed=False)

    @property
    def can_take_front(self) -> bool:
        """Whether its windows may come to the front."""
        if self.application is self.manager.active_application:
            return True
        closing = self.server.closing
        return closing is not None and self in closing

    @property
    def modal_window(self) -> RemoteWindow | None:
        """Its waiting dialog, if any."""
        modal = [window for window in self.windows.values() if window.modal]
        return modal[-1] if modal else None

    def _blocked(self, window: RemoteWindow) -> bool:
        """Whether a dialog blocks input to a window.

        :param window: The window.
        """
        modal = self.modal_window
        if modal is None or modal is window:
            return False
        self._show(modal)
        return True

    def _show(self, window: RemoteWindow) -> None:
        if window in self.manager.minimised:
            self.manager.restore(window)
        elif window.manager is self.manager:
            self.manager.bring_to_front(window)

    def input(self, window: RemoteWindow, kind: str, **fields: object) -> None:
        """Pass input to a window.

        :param window: The window.
        :param kind: Input kind.
        :param fields: Input fields.
        """
        if not self._blocked(window):
            self.send(kind, id=window.number, **fields)

    def choose(self, path: Sequence[int]) -> None:
        """Handle a chosen menu item.

        :param path: Menu and item indexes.
        """
        key = self.manager.menu_bar.shortcut_key
        modal = self.modal_window
        if modal is not None:
            self._show(modal)
            if key is not None:
                self.send("key", id=modal.number, key=key)
        elif key is not None:
            self.send("menu", path=list(path), key=key)
        else:
            self.send("menu", path=list(path))

    def set_menus(self, menus: Sequence[Any]) -> None:
        """Apply the application's menus.

        :param menus: The encoded menus.
        """
        reserved = self._reserved_keys()
        count = [0]
        self.application.menus = [
            self._menu(menu, [number], reserved, count)
            for number, menu in enumerate(menus)
        ]

    def _reserved_keys(self) -> set[str]:
        """The desktop's reserved keys."""
        shortcuts = self.manager.shortcuts
        return {
            pretty_key(key).lower()
            for action in (*DESKTOP_KEYS, "open_menu")
            for key in shortcuts.keys(action)
        }

    def _menu(
        self, data: Any, path: list[int], reserved: set[str], count: list[int]
    ) -> Menu:
        if len(path) > MAX_MENU_DEPTH:
            raise ProtocolError(f"submenus deeper than {MAX_MENU_DEPTH}")
        items: list[MenuItem] = []
        for number, item in enumerate(data["items"]):
            count[0] += 1
            if count[0] > MAX_MENU_ITEMS:
                raise ProtocolError(f"more than {MAX_MENU_ITEMS} menu items")
            where = [*path, number]
            if item["separator"]:
                items.append(separator())
            elif item["submenu"] is not None:
                submenu = self._menu(item["submenu"], where, reserved, count)
                items.append(
                    MenuItem(
                        one_line(item["label"]),
                        status=one_line(item["status"]),
                        submenu=submenu,
                        # Greyed out in the application: its submenu stays shut.
                        enabled=None if item["enabled"] else never_enabled,
                    )
                )
            else:
                action = partial(self.choose, where)
                shortcut = one_line(item["shortcut"] or "")
                if shortcut.lower() in reserved:
                    shortcut = ""  # the desktop's own key
                items.append(
                    MenuItem(
                        one_line(item["label"]),
                        action if item["enabled"] else None,
                        shortcut,
                        one_line(item["status"]),
                    )
                )
        # An application of an earlier version does not send after_window.
        after_window = data.get("after_window") is True
        return Menu(one_line(data["title"]), items, after_window=after_window)

    def flush(self) -> None:
        """Tell the application what changed."""
        if self.connection is None:
            return
        for window in self.windows.values():
            where = (window.rect, window.maximised)
            if where != window.told_rect:
                window.told_rect = where
                self.send(
                    "rect",
                    id=window.number,
                    rect=encode_rect(window.rect),
                    maximised=window.maximised,
                )
            scroll = (window.scroll_row, window.scroll_column)
            if scroll != window.told_scroll:
                window.told_scroll = scroll
                self.send("scroll", id=window.number, row=scroll[0], column=scroll[1])
        active = self.manager.active_window
        mine = (
            active.number
            if isinstance(active, RemoteWindow) and active.host is self
            else None
        )
        if mine is not None:
            # The clipboard goes to an application once its window is the
            # active one, ready to paste: never to those in the background.
            text = CLIPBOARD.text
            if text is not None and text != self.told_clipboard:
                self.told_clipboard = text
                self.send("clipboard", text=text)
        if mine != self._told_active:
            self._told_active = mine
            self.send("active", id=mine)
        size = self.manager.screen_size
        if size != self._told_size:
            self._told_size = size
            self.send("size", columns=size[0], lines=size[1])

    # Hearing from it

    def handle(self, message: Message) -> None:  # pylint: disable=too-many-branches
        """Handle a message from the application.

        :param message: The message.
        """
        self.heard()
        kind = message["type"]
        # Its first flush comes as soon as it has started, with its menus
        # even if it has none. These can come before that: a ping waiting
        # when start() ends is answered before anything is flushed.
        if self.is_loading and kind not in ("pong", "answer", "bye"):
            self.loaded()
        number = message.get("id")
        window = self.windows.get(number) if isinstance(number, int) else None
        manager = self.manager
        if kind == "window" and isinstance(number, int):
            if window is None:
                if len(self.windows) >= MAX_WINDOWS:
                    raise ProtocolError(f"more than {MAX_WINDOWS} windows")
                window = self.windows[number] = RemoteWindow(self, number, message)
                if window.application is not None:
                    self.application.windows.append(window)
                if manager.must_wait(window):
                    # Another application's dialog is waiting for an answer:
                    # this one waits behind it, not taking the keyboard.
                    manager.add_waiting(window)
                elif not self.can_take_front:
                    # In the background: behind what the user is doing.
                    manager.add_behind(window)
                else:
                    manager.add(window)
            else:
                window.apply(message)
                if window.manager is manager:
                    manager.keep_reachable(window)  # not moved off the screen
        elif kind == "paint" and window is not None:
            window.apply_paint(message)
        elif kind == "menus":
            self.set_menus(message["menus"])
        elif kind == "close" and window is not None:
            del self.windows[window.number]
            if window.manager is manager:
                manager.remove(window)
        elif kind == "request":
            self._request(window, str(message["op"]))
        elif kind == "clipboard":
            self.server.share_clipboard(self, str(message["text"]))
        elif kind == "theme":
            # A theme for the whole desktop: asked by the application the
            # user is working in, as only it can have been told to.
            if self.can_take_front:
                manager.set_theme(one_line(message["name"]))
        elif kind == "answer":
            self.server.answered(self, bool(message.get("ok")))
        elif kind == "bye":
            self.said_bye = True

    def _request(self, window: RemoteWindow | None, op: str) -> None:
        """Do a window request from the application.

        :param window: The window, if any.
        :param op: The request.
        """
        manager = self.manager
        if op not in ("minimise", "send_to_back") and not self.can_take_front:
            return
        if op == "exit":
            manager.request_exit()
        elif op == "next_window":
            manager.activate_next()
        elif op == "previous_window":
            manager.activate_previous()
        elif window is None:
            return
        elif op == "front":
            if not manager.must_wait(window):  # not past another's dialog
                self._show(window)
        elif op == "move":
            manager.start_moving(window)
        elif op == "resize":
            manager.start_resizing(window)
        elif op in (
            "send_to_back",
            "maximise",
            "minimise",
            "restore",
            "toggle_maximise",
        ):
            if window.manager is manager:
                getattr(manager, op)(window)

    # Ending

    def stop(self) -> None:
        """Ask the application to end, which also removes its windows."""
        self.stopping = True
        if self.connection is None:
            self.finish(crashed=False)
        else:
            self.send("quit")

    def finish(self, crashed: bool) -> None:
        """Handle the application's end.

        :param crashed: Whether it ended without saying goodbye.
        """
        if self.ended:
            return
        self.ended = True
        manager = self.manager
        for window in list(self.windows.values()):
            if window.manager is manager:
                manager.remove(window)
        self.windows.clear()
        self.application.windows.clear()
        self.application.is_running = False
        manager.application_ended(self.application)
        self._outbox.put(None)  # the writer stops
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                if self.tree is not None:
                    self.tree.kill()
        if self.tree is not None:
            self.tree.close()
        if self.connection is not None:
            close_connection(self.connection)
        self.drop_empty_log()
        self.server.ended(self, crashed and not self.stopping)

    def drop_empty_log(self) -> None:
        """Delete the log if empty."""
        if self.log_path is not None:
            logs.drop_if_empty(self.log_path)

    def last_words(self) -> str:
        """The last line of its log, if any."""
        if self.log_path is None:
            return ""
        return one_line(logs.last_line(self.log_path))


class AppServer:  # pylint: disable=too-many-instance-attributes
    """Starts applications and relays their messages.

    :param manager: The presentation manager.
    """

    poll_interval: float = 0.02
    """Longest input wait, in seconds, while applications run."""
    ping_interval: float = 1.0
    """Seconds of silence before a ping."""
    hang_timeout: float = 5.0
    """Seconds before an unanswered ping means hung."""
    start_timeout: float = 30.0
    """Seconds to connect after starting."""
    load_timeout: float = 30.0
    """Seconds with nothing shown before asking."""
    handshake_timeout: float = 10.0
    """Seconds to finish the handshake."""
    close_timeout: float = 10.0
    """Seconds to answer whether it may close."""
    max_messages: int = 1000
    """Most messages handled per loop pass."""

    def __init__(self, manager: "PresentationManager") -> None:
        self.manager = manager
        self.authkey = secrets.token_bytes(32)
        self.log_folder = logs.LOG_FOLDER
        self.hosts: list[AppHost] = []
        self.lend_folder = LEND_FOLDER
        self.notices: list[tuple[str, str]] = []
        """Messages for the user, as (title, message)."""
        self._listener: Listener | None = None
        self._by_token: dict[str, AppHost] = {}
        self._by_connection: dict[int, AppHost] = {}
        self.inbox = Inbox()
        """The messages waiting to be handled, counted and capped."""
        self._closing: set[AppHost] | None = None
        self._then: Callable[[], object] | None = None
        self._asked_at: dict[AppHost, float] = {}
        self._close_asked_at = 0.0

    @property
    def closing(self) -> set[AppHost] | None:
        """Applications yet to answer a close request."""
        return self._closing

    @property
    def address(self) -> str:
        """The address applications connect to."""
        return "" if self._listener is None else str(self._listener.address)

    @property
    def is_busy(self) -> bool:
        """Whether any application is starting or running."""
        return bool(self.hosts)

    @property
    def is_loading(self) -> bool:
        """Whether any application is still loading."""
        return any(host.is_loading for host in self.hosts)

    def slow_to_load(self) -> AppHost | None:
        """A slow-loading application, if any."""
        now = time.monotonic()
        for host in self.hosts:
            if (
                host.is_loading
                and host.connection is not None
                and now - host.load_asked_at >= self.load_timeout
            ):
                return host
        return None

    def _listen(self) -> None:
        if self._listener is not None:
            return
        # No key here: the handshake is done in each connection's own
        # thread (_read_all), so one that stalls holds up nothing else.
        self._listener = Listener(backlog=16)
        threading.Thread(target=self._accept_all, daemon=True).start()

    def _accept_all(self) -> None:
        listener = self._listener
        while listener is not None:
            try:
                connection = listener.accept()
            except OSError:
                if self._listener is None:
                    return  # closed
                time.sleep(0.1)  # again, but not flat out if it keeps failing
                continue
            if self._listener is None:  # woken by stop_all, to end
                close_connection(connection)
                return
            threading.Thread(
                target=self._read_all, args=(connection,), daemon=True
            ).start()

    def _authenticate(self, connection: Connection) -> bool:
        """Whether a connection knows the key.

        :param connection: The connection.
        """
        timed = cast(Connection, TimedConnection(connection, self.handshake_timeout))
        try:
            deliver_challenge(timed, self.authkey)
            answer_challenge(timed, self.authkey)
            return True
        except (AuthenticationError, EOFError, OSError, ValueError):
            return False

    def _read_all(self, connection: Connection) -> None:
        if not self._authenticate(connection):
            close_connection(connection)
            return
        while True:  # waiting in put while this application has too much waiting
            try:
                data: bytes | None = connection.recv_bytes(MAX_MESSAGE)
            except (EOFError, OSError):
                data = None
            self.inbox.put(connection, data)
            if data is None:
                return

    def start(
        self,
        target: str,
        name: str,
        venv: str | None = None,
        *,
        guessed_name: bool = False,
    ) -> AppHost | None:
        """Start an application, or return ``None``.

        :param target: ``MODULE:CLASS`` or a script.
        :param name: Application name.
        :param venv: Virtual environment folder, if any.
        :param guessed_name: Whether the name was made up.
        """
        self._listen()
        host = AppHost(self, target, name, venv, guessed_name=guessed_name)
        try:
            host.start()
        except OSError as error:
            reason = error.strerror or str(error)
            if isinstance(error, FileNotFoundError) and not error.filename:
                reason = str(error)
            self.notices.append(("Cannot start", f"Cannot start {name}:\n{reason}"))
            return None
        self.hosts.append(host)
        self._by_token[host.token] = host
        return host

    def running(self, target: str) -> AppHost | None:
        """A running application of this kind, if any.

        :param target: ``MODULE:CLASS`` or a script.
        """
        return next((host for host in self.hosts if host.target == target), None)

    def poll(self) -> None:
        """Handle waiting messages."""
        for _ in range(self.max_messages):
            if (waiting := self.inbox.get()) is None:
                break
            self._dispatch(*waiting)
        now = time.monotonic()
        for host in list(self.hosts):
            process = host.process
            if host.connection is None and process is not None:
                if process.poll() is not None:
                    host.finish(crashed=True)
                    continue
            host.check(now)

    def _dispatch(self, connection: Connection, message: Message | None) -> None:
        """Act on a message, or a disconnect.

        :param connection: The connection.
        :param message: The message, or ``None`` if gone.
        """
        host = self._by_connection.get(id(connection))
        if host is None:
            if message is not None:
                self._greet(connection, message)
            return
        if message is None:
            host.finish(crashed=not host.said_bye)
            return
        try:
            host.handle(message)
        except (LookupError, TypeError, ValueError, ArithmeticError, RecursionError):
            host.end_now()
            self.notices.append(
                (
                    "Application stopped",
                    f"{host.name} sent something that could not be "
                    "understood, so it was ended.",
                )
            )

    def _greet(self, connection: Connection, message: Message) -> None:
        """Welcome or refuse an application.

        :param connection: The connection.
        :param message: The hello message.
        """
        host = self._by_token.get(str(message.get("token")))
        reason = ""
        agreed = agree_version(message)
        if message["type"] != "hello":
            reason = "expected hello"
        elif agreed is None:
            reason = (
                "no protocol version in common: this dasha speaks "
                f"{MINIMUM_VERSION} to {PROTOCOL_VERSION}"
            )
        elif host is None or host.connection is not None:
            reason = "not started by this desktop"
        if reason or host is None or agreed is None:
            # In a thread of its own: one that never reads cannot hold up
            # the desktop while the reply waits to be sent.
            threading.Thread(
                target=refuse, args=(connection, reason), daemon=True
            ).start()
            return
        host.version = agreed
        host.connected(connection)
        self._by_connection[id(connection)] = host
        if isinstance(message.get("pid"), int):
            host.pid = message["pid"]
        name = application_name(message.get("name", ""))
        if host.guessed_name and name and not self._reserved_name(name):
            host.application.name = name
        columns, lines = self.manager.screen_size
        # Through its outbox, as every message to it is, so the desktop
        # never waits for an application to read. The clipboard follows
        # once one of its windows is active (AppHost.flush).
        host.send(
            "welcome",
            version=agreed,
            size=[columns, lines],
            theme=theme.theme_to_json(theme.current_theme(), version=agreed),
            theme_name=self.manager.theme_name,
            shortcuts=json.loads(self.manager.shortcuts.to_json()),
            key_releases=Widget.key_releases,
        )

    def _reserved_name(self, name: str) -> bool:
        """Whether a name is the desktop's own.

        :param name: The name.
        """
        return _squeezed(name) == _squeezed(self.manager.no_application)

    def prune_logs(self) -> None:
        """Delete the oldest logs, keeping the newest ``logs.LOG_KEEP``."""
        logs.prune(self.log_folder)

    def flush(self) -> None:
        """Tell every application what has changed on the desktop."""
        for host in list(self.hosts):
            host.flush()

    def ended(self, host: AppHost, crashed: bool) -> None:
        """Called once an application has ended.

        :param host: The application.
        :param crashed: Whether it crashed.
        """
        if host in self.hosts:
            self.hosts.remove(host)
        self._by_token.pop(host.token, None)
        if host.connection is not None:
            self._by_connection.pop(id(host.connection), None)
        if crashed:
            message = f"{host.name} stopped unexpectedly."
            if last_words := host.last_words():
                # Wrapped, not cut: the useful part often follows a long path.
                # Labelled as the application's own words, which they are.
                lines = textwrap.wrap(last_words, 60, max_lines=4, placeholder=" ...")
                message += "\n\nThe last line of its log:\n" + "\n".join(lines)
            self.notices.append(("Application stopped", message))
        if self._closing is not None and host in self._closing:
            self.answered(host, True)

    def outside_press(self, event: MouseEvent) -> bool:
        """Close a waiting drop-down list on an outside press.

        :param event: The mouse event.
        """
        active = self.manager.active_window
        if (
            isinstance(active, RemoteWindow)
            and active.close_on_outside_click
            and event.action == "press"
            and not active.rect.contains(event.row, event.column)
        ):
            active.host.send("outside", id=active.number)
            return True
        return False

    def share_theme(self) -> None:
        """Send the theme to every application."""
        current = theme.current_theme()
        written: dict[int, str] = {}
        for host in self.hosts:
            if host.version not in written:
                written[host.version] = theme.theme_to_json(
                    current, version=host.version
                )
            host.send(
                "theme", theme=written[host.version], name=self.manager.theme_name
            )

    def share_clipboard(self, source: AppHost, text: str) -> None:
        """Take text cut or copied in an application.

        :param source: The application.
        :param text: The text.
        """
        if source.application is not self.manager.active_application:
            return
        source.told_clipboard = text
        CLIPBOARD.copy_text(text)

    # Shutting down

    def ask_to_close(self, then: Callable[[], object]) -> None:
        """Ask every application whether it may close.

        :param then: Called once all agree.
        """
        asking = {
            host
            for host in self.hosts
            if host.connection is not None and not host.is_loading
        }
        if not asking:
            then()
            return
        self._closing, self._then = asking, then
        self._asked_at = {}
        self._close_asked_at = time.monotonic()
        for host in asking:
            host.send("may_close")

    def stuck(self) -> AppHost | None:
        """A stuck application during shutdown, if any."""
        if self._closing is None:
            return None
        now = time.monotonic()
        overdue = now - self._close_asked_at >= self.close_timeout
        for host in self._closing:
            asked = self._asked_at.get(host)
            silent = overdue and host.modal_window is None
            if (not host.responding or silent) and (
                asked is None or now - asked >= self.hang_timeout
            ):
                return host
        return None

    def ask_about(self, host: AppHost) -> None:
        """Ask the user about a stuck application.

        :param host: The application.
        """
        self._asked_at[host] = time.monotonic()
        state = (
            "is not responding"
            if not host.responding
            else "has not said whether it can close"
        )
        dialog = question(
            "Shutting down",
            f"{host.name} {state}.\n\n"
            "End it now (losing unsaved work), wait for it, or cancel?",
            [("&End now", "end"), ("&Wait", "wait"), ("&Cancel", "cancel")],
            status="Waiting for an application to close",
        )
        answer = self.manager.execute(dialog)
        if answer == "end" and not host.ended:
            host.end_now()
        elif answer == "cancel":
            self._closing = self._then = None

    def answered(self, host: AppHost, ok: bool) -> None:
        """Record an answer to ``ask_to_close``.

        :param host: The application.
        :param ok: Whether it may close.
        """
        closing, then = self._closing, self._then
        if closing is None or host not in closing:
            return
        if not ok:
            self._closing = self._then = None
            return
        closing.discard(host)
        if not closing:
            self._closing = self._then = None
            if then is not None:
                then()

    def stop_all(self, wait: float = 2.0) -> None:
        """End every application.

        :param wait: Seconds to wait before forcing.
        """
        for host in list(self.hosts):
            host.stopping = True
            host.send("quit")
        deadline = time.monotonic() + wait
        for host in list(self.hosts):  # each one, with a process or without
            process = host.process
            try:
                if process is not None:
                    process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                if host.tree is not None:
                    host.tree.kill()
            host._outbox.put(None)  # pylint: disable=protected-access
            if host.tree is not None:
                host.tree.close()
            if host.connection is not None:
                close_connection(host.connection)
            host.drop_empty_log()
        self.hosts.clear()
        self.inbox.stop()
        listener, self._listener = self._listener, None
        if listener is not None:
            try:  # connecting wakes an accept() that is waiting, to end it
                Client(listener.address).close()
            except OSError:
                pass  # nothing waiting
            listener.close()
