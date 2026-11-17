"""The desktop's side of applications that run in their own processes.

``AppServer`` listens for applications, starts them (``start``) and passes
their messages on. Each one is an ``AppHost``: its process, its connection,
and its windows, which the desktop shows as ``RemoteWindow``\\ s. A remote
window is an ordinary window to the presentation manager: it has a frame,
and moves, resizes, minimises and stacks like any other, while what is
inside the frame comes from the application, which is told about every key
and click.

An application that crashes, or stops answering on its connection, affects
only its own windows: the desktop removes them and reports what happened.
"""

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
    """A name in lower case, without spaces, hyphens or underscores."""
    return "".join(name.replace("-", " ").replace("_", " ").split()).casefold()


class AppHost:  # pylint: disable=too-many-instance-attributes
    """One application running in its own process."""

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
        """What it runs: ``MODULE:CLASS``, or a script (``path/app.py``,
        ``path/app.py:CLASS``)."""
        self.venv = venv
        """The virtual environment whose Python runs it, if not this one."""
        self.guessed_name = guessed_name
        """Whether ``name`` was only made up from what it runs (by Run...),
        so the name the application gives itself may replace it. Otherwise
        the desktop's name stands: an application cannot pass itself off as
        another, or as Dasha Framework."""
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
        """The process id the application gave when it connected: the real
        Python's, which a virtual environment's launcher may have started."""
        self.ended = False
        self.said_bye = False
        self.stopping = False
        self.responding = True
        """False once it has left a ping unanswered for ``hang_timeout``."""
        self.started_at = time.monotonic()
        self.last_heard = self.started_at
        self.load_asked_at = self.started_at
        """When it connected, or when the user last chose to wait for it to
        finish loading (``AppServer.slow_to_load``)."""
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
        """Whether it has been started but has nothing to show yet. Until
        then, the desktop goes on as it was: it is not one of the manager's
        applications, and the menu bar, the status bar and the system menu
        take no notice of it (``loaded``)."""
        return not self.ended and not self.application.is_running

    def loaded(self) -> None:
        """Make it the active application, now that it has something to
        show. If the desktop is already asking its applications whether they
        may close, it is asked too, now that it might have work to lose."""
        self.manager.add_application(self.application)
        closing = self.server.closing
        if closing is not None:
            closing.add(self)
            self.send("may_close")

    def start(self) -> None:
        """Start the application's process, which then connects back to the
        desktop."""
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
        """The Python that runs the application: its virtual environment's
        Python, or the desktop's own. Raises ``FileNotFoundError`` for a
        virtual environment without a Python."""
        if self.venv is None:
            return Path(sys.executable)
        python = venv_python(self.venv)
        if not python.exists():
            raise FileNotFoundError(f"no Python in {self.venv}")
        return python

    def environment(self) -> dict[str, str]:
        """The environment variables for the child process: the desktop's own,
        with the address to connect to, and Dasha Framework lent to it. In a
        virtual environment, only Dasha Framework is lent (a copy of Dasha Framework
        alone), and only if the environment has not installed its own;
        nothing else from the desktop's environment leaks in."""
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
        """Record that the application has connected, and start sending it
        whatever is waiting in its outbox."""
        self.connection = connection
        self.last_heard = self.load_asked_at = time.monotonic()
        threading.Thread(target=self._send_all, args=(connection,), daemon=True).start()

    def _send_all(self, connection: Connection) -> None:
        """Send the outbox, in a thread of its own: an application that has
        stopped reading blocks this thread, never the desktop."""
        while (data := self._outbox.get()) is not None:
            try:
                connection.send_bytes(data)
            except CLOSED_UNDER_IT:
                return  # gone (or closed meanwhile); the reader notices

    def send(self, kind: str, **fields: object) -> None:
        """Send a message, if the application is connected. The message goes
        into the outbox, so this never waits for the application."""
        if self.connection is not None and not self.ended:
            self._outbox.put(encode(kind, **fields))

    # Staying alive

    def heard(self) -> None:
        """Record that a message arrived from the application, which shows it
        is alive and handling its messages."""
        self.last_heard = time.monotonic()
        self._ping_sent = None
        if not self.responding:
            self._set_responding(True)

    def _set_responding(self, responding: bool) -> None:
        self.responding = responding
        for window in self.windows.values():
            window.show_title()

    def check(self, now: float) -> None:
        """Ping the application when it has been silent, and notice when it
        stops answering; end it if it never connects."""
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
        """Ask the user whether to end the application, now that it is not
        responding."""
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
        """Ask the user whether to end the application, now that it has been
        connected for ``load_timeout`` with nothing to show. A slow start
        is not a failure, so it is ended only if the user says so; choosing
        to wait asks again after another ``load_timeout``."""
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
        """End the application immediately, together with everything it
        started."""
        self.stopping = True
        if self.tree is not None:
            self.tree.kill()
        self.finish(crashed=False)

    @property
    def can_take_front(self) -> bool:
        """Whether the application's windows may come to the front and take
        the keyboard. This is allowed only while it is the active application
        (the one the user chose most recently), or while the desktop is
        shutting down and has asked it whether it may close, so that it can
        ask about unsaved work. Otherwise, an application in the background
        could open a window while the user is typing in another
        application's window, and capture what they type."""
        if self.application is self.manager.active_application:
            return True
        closing = self.server.closing
        return closing is not None and self in closing

    @property
    def modal_window(self) -> RemoteWindow | None:
        """The application's dialog that is waiting for an answer, if any (the
        most recent one, if there are several)."""
        modal = [window for window in self.windows.values() if window.modal]
        return modal[-1] if modal else None

    def _blocked(self, window: RemoteWindow) -> bool:
        """Whether input to a window must wait for a dialog: if so, the
        dialog is brought forward instead."""
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
        """Pass a key, click or paste on to one of the application's
        windows."""
        if not self._blocked(window):
            self.send(kind, id=window.number, **fields)

    def choose(self, path: Sequence[int]) -> None:
        """Handle the choice of an item in the application's menus. While one
        of its dialogs is waiting for an answer, the dialog comes forward
        instead, and a shortcut's key is sent to the dialog as a key press.
        When the item was chosen with a shortcut, the key is sent along with
        the choice, in case the application has opened a dialog that the
        desktop does not know about yet."""
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
        """Apply the menus sent by the application, so that choosing an item
        tells the application which one was chosen. Raises ``ProtocolError``
        for more than ``MAX_MENU_ITEMS`` items, or for submenus deeper than
        ``MAX_MENU_DEPTH``."""
        reserved = self._reserved_keys()
        count = [0]
        self.application.menus = [
            self._menu(menu, [number], reserved, count)
            for number, menu in enumerate(menus)
        ]

    def _reserved_keys(self) -> set[str]:
        """The desktop's keys, as a menu writes them (``"alt+f4"``): no
        item of an application's may take one as its shortcut, or it could
        keep the user from switching away, closing it or opening the menus."""
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
        """Tell the application what has changed on the desktop: where its
        windows are, how they are scrolled, which one is active, and the
        screen size."""
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
        """Handle one message from the application."""
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
        """Do what its Window menu (or code) asked of the desktop. Only
        minimising and sending a window to the back are done for an
        application in the background (``can_take_front``): everything else
        would take the front, or the keyboard, from the user's work, or ask
        to leave the desktop."""
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
        """Handle the end of the application: take its windows off the
        desktop, and if it ended without saying goodbye, report what
        happened."""
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
        """Once the application has ended, delete its log if it wrote
        nothing to it."""
        if self.log_path is not None:
            logs.drop_if_empty(self.log_path)

    def last_words(self) -> str:
        """The last line the application wrote to its log (its standard
        error), if any, kept to one line of at most ``MAX_TEXT`` characters
        (``logs.last_line``)."""
        if self.log_path is None:
            return ""
        return one_line(logs.last_line(self.log_path))


class AppServer:  # pylint: disable=too-many-instance-attributes
    """Starts applications in their own processes, and passes messages
    between them and the presentation manager."""

    poll_interval: float = 0.02
    """The longest time, in seconds, that the desktop waits for input while
    applications are running, before checking whether they have sent
    anything."""
    ping_interval: float = 1.0
    """How many seconds an application can be silent before it is
    pinged."""
    hang_timeout: float = 5.0
    """How many seconds a ping may go unanswered before the application
    counts as not responding."""
    start_timeout: float = 30.0
    """How many seconds an application has to connect once it has been
    started."""
    load_timeout: float = 30.0
    """How many seconds an application can be connected with nothing to show
    before the user is asked whether to end it or wait for it, and how long
    each wait lasts (``slow_to_load``)."""
    handshake_timeout: float = 10.0
    """How many seconds a new connection has to prove that it knows the
    key. A connection that stops part-way is dropped, and cannot hold up
    others that are connecting."""
    close_timeout: float = 10.0
    """How many seconds an application has, when the desktop shuts down, to
    say whether it may close, unless it is asking the user (because one of
    its dialogs is open). After that, the user is asked whether to end
    it."""
    max_messages: int = 1000
    """The largest number of messages handled on each pass of the desktop's
    loop, so that a flood of messages from one application cannot stop the
    screen being drawn or the keyboard being read."""

    def __init__(self, manager: "PresentationManager") -> None:
        self.manager = manager
        self.authkey = secrets.token_bytes(32)
        self.log_folder = logs.LOG_FOLDER
        self.hosts: list[AppHost] = []
        self.lend_folder = LEND_FOLDER
        self.notices: list[tuple[str, str]] = []
        """What the desktop should tell the user, as (title, message): an
        application that ended without saying goodbye (with the last line
        of its log), or one that could not start."""
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
        """While the desktop is shutting down, the applications it has asked
        whether they may close, and has not yet heard back from."""
        return self._closing

    @property
    def address(self) -> str:
        """The address that applications connect to, once the server is
        listening."""
        return "" if self._listener is None else str(self._listener.address)

    @property
    def is_busy(self) -> bool:
        """Whether any application is starting or running."""
        return bool(self.hosts)

    @property
    def is_loading(self) -> bool:
        """Whether any application has been started but has nothing to show
        yet (``AppHost.is_loading``)."""
        return any(host.is_loading for host in self.hosts)

    def slow_to_load(self) -> AppHost | None:
        """An application that has been connected for ``load_timeout`` with
        nothing to show, since the user last chose to wait for it, if any.
        One that has not connected has ``start_timeout`` instead."""
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
        """Whether a new connection knows the key, as ``Listener`` would
        check it, within ``handshake_timeout``: one that does not answer in
        time fails."""
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
        """Start an application (a ``MODULE:CLASS`` or a script) in its own
        process, using a virtual environment's Python if one is given.
        Returns ``None`` if it cannot start, after recording why for the
        desktop to report. ``guessed_name`` means that ``name`` was only made
        up from the target, so the application's own name may replace it
        (``AppHost.guessed_name``)."""
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
        """A running (or starting) application of this kind, if there is
        one."""
        return next((host for host in self.hosts if host.target == target), None)

    def poll(self) -> None:
        """Handle the waiting messages (up to ``max_messages``, leaving the
        rest for next time), and notice applications that ended before they
        connected."""
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
        """Act on a message from an application (``None``: it has gone).
        One that cannot be acted on (a field missing or of the wrong kind)
        ends that application alone; the desktop and the rest carry on."""
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
        """An application introducing itself: welcome it, or refuse."""
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
            theme=theme.theme_to_json(theme.current_theme()),
            theme_name=self.manager.theme_name,
            shortcuts=json.loads(self.manager.shortcuts.to_json()),
            key_releases=Widget.key_releases,
        )

    def _reserved_name(self, name: str) -> bool:
        """Whether a name is the desktop's own (``Dasha Desktop``, or
        whatever the manager calls itself), which no application may take,
        in any case and however it is spaced (``dasha-desktop`` too)."""
        return _squeezed(name) == _squeezed(self.manager.no_application)

    def prune_logs(self) -> None:
        """Delete the oldest logs, keeping the newest ``logs.LOG_KEEP``."""
        logs.prune(self.log_folder)

    def flush(self) -> None:
        """Tell every application what has changed on the desktop."""
        for host in list(self.hosts):
            host.flush()

    def ended(self, host: AppHost, crashed: bool) -> None:
        """Called by an ``AppHost`` once it has ended."""
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
        """Handle a press outside a waiting drop-down list by closing the list
        (and using up the press, as a list in this process would)."""
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
        """Send the desktop's new theme to every application, which takes it
        on at once and redraws its windows."""
        colours = theme.theme_to_json(theme.current_theme())
        for host in self.hosts:
            host.send("theme", theme=colours, name=self.manager.theme_name)

    def share_clipboard(self, source: AppHost, text: str) -> None:
        """Handle text cut or copied in an application. The desktop's
        clipboard takes it, and other applications receive it when one of
        their windows next becomes active (``AppHost.flush``), but not
        before, so that an application in the background cannot read what is
        copied elsewhere. Only the active application may change the
        clipboard, because only it can have been told to by the user."""
        if source.application is not self.manager.active_application:
            return
        source.told_clipboard = text
        CLIPBOARD.copy_text(text)

    # Shutting down

    def ask_to_close(self, then: Callable[[], object]) -> None:
        """Ask every application whether it may close (each may ask about
        unsaved work first), and call ``then`` once they have all agreed. Any
        application that answers no stops the shutdown. One still loading has
        no work to lose, and may be too busy to answer: it is not asked unless
        it finishes loading first (``AppHost.loaded``), and ``stop_all`` ends
        it."""
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
        """While shutting down, an application that is not responding, or that
        has not said whether it may close within ``close_timeout`` while
        asking the user nothing, and that the user has not been asked about
        within the last ``hang_timeout``."""
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
        """While shutting down, ask the user about an application that is not
        responding: whether to end it, wait longer, or stop shutting
        down."""
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
        """Record an application's answer to ``ask_to_close``."""
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
        """End every application: ask each to quit, wait a little, and then end
        any that are still running. Also stops listening for
        connections."""
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
