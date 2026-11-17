"""Tests for what keeps one application from harming the desktop, or another
application: what it sends is checked, it cannot take the keyboard, the
clipboard or another's name, and it cannot hold the desktop up."""

# These tests play the desktop's side of the connection, so they reach into
# the server's own workings (its queue, its greeting) to do it.
# pylint: disable=protected-access

import io
import os
import tempfile
import threading
import time
import unittest
from multiprocessing.connection import Client, Connection
from pathlib import Path
from typing import Any
from unittest import mock

from dasha import hosting, protocol
from dasha.canvas import UNSHOWABLE, Canvas, shown
from dasha.clipboard import CLIPBOARD
from dasha.hosting import AppHost, AppServer
from dasha.logs import LOG_KEEP
from dasha.manager import PresentationManager
from dasha.protocol import (
    MINIMUM_VERSION,
    PROTOCOL_VERSION,
    Message,
    ProtocolError,
    agree_version,
    decode_colour,
    encode,
)
from dasha.remote import MAX_MENU_DEPTH, MAX_TEXT, MAX_WINDOWS, application_name
from dasha.terminal import Terminal
from tests.support import hosted, pipe, serving
from tests.test_hosting import drain, of_type
from tests.test_waiting_dialogs import state


def item(label: str, shortcut: str = "", submenu: Any = None) -> dict[str, Any]:
    """A menu item as an application sends it."""
    return {
        "separator": False,
        "submenu": submenu,
        "label": label,
        "enabled": True,
        "shortcut": shortcut,
        "status": "",
    }


class Desktop(unittest.TestCase):
    """A desktop with an Editor (active) and a Sneaky application in the
    background, each at the end of a pipe."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.handle_resize(80, 24)
        self.server = serving(self, self.manager)
        self.sneaky, self.sneaky_end = self.host("Sneaky")
        self.editor, self.editor_end = self.host("Editor")
        self.editor.handle(state(title="Editor"))
        self.addCleanup(CLIPBOARD.clear)

    def host(self, name: str) -> tuple[AppHost, Connection]:
        """An application at the end of a pipe, made the active one."""
        return hosted(self.server, name)

    def dispatch(self, host: AppHost, message: Message) -> None:
        """A message from an application, as the desktop takes it: one it
        cannot act on ends that application."""
        connection = host.connection
        assert connection is not None

        self.server._by_connection[id(connection)] = host
        self.server._dispatch(connection, message)

    def front(self) -> str:
        """The title of the window in front."""
        return self.manager.windows[-1].title


class CheckedMessagesTests(Desktop):
    """What an application sends is checked before the desktop keeps it."""

    def test_a_colour_that_is_not_one_ends_the_application(self) -> None:
        """Out of range, or not a number: the application is ended, and the
        desktop goes on drawing."""
        for colour in (300, -1, "red", [1], True, 2.5):
            with self.subTest(colour=colour):
                self.assertRaises(ProtocolError, decode_colour, colour)
        paint = {"type": "paint", "id": 1, "styles": [[300, None, 0, 0, 0]],
                 "size": [10, 2], "rows": [[0, [["boom", 0]]]]}  # fmt: skip
        self.dispatch(self.editor, paint)
        self.assertNotIn(self.editor, self.server.hosts)
        canvas = Canvas(80, 24)
        self.manager.compose(canvas)
        canvas.render()  # nothing left to fail
        self.assertEqual(decode_colour(None), None)
        self.assertEqual(decode_colour(255), 255)

    def test_text_is_one_line_and_not_too_long(self) -> None:
        """Titles, status lines and hints: line breaks become spaces, and
        they stop at MAX_TEXT characters."""
        self.editor.handle(
            state(
                title="A\nB" + "x" * 5000, status="one\r\ntwo", hints=[["F1", "a\nb"]]
            )
        )
        window = self.editor.windows[1]
        assert window.focused is not None
        self.assertTrue(window.title.startswith("A B"))
        self.assertEqual(len(window.title), MAX_TEXT)
        self.assertEqual(window.status, "one two")
        self.assertEqual(
            window.focused.key_help(self.manager.shortcuts), [("F1", "a b")]
        )

    def test_too_many_windows_ends_it(self) -> None:
        """An application that opens window after window is ended."""
        for number in range(2, MAX_WINDOWS + 2):
            self.dispatch(self.editor, state(id=number))
        self.assertNotIn(self.editor, self.server.hosts)
        self.assertEqual(self.server.notices[-1][0], "Application stopped")

    def test_menus_too_deep_end_it(self) -> None:
        """Submenus nested deeper than MAX_MENU_DEPTH end the application."""
        menu: dict[str, Any] = {"title": "Deep", "items": []}
        for _ in range(MAX_MENU_DEPTH + 2):
            menu = {"title": "Deep", "items": [item("&Down", submenu=menu)]}
        self.dispatch(self.editor, {"type": "menus", "menus": [menu]})
        self.assertNotIn(self.editor, self.server.hosts)

    def test_a_message_too_long_ends_the_connection(self) -> None:
        """Longer than MAX_MESSAGE: the connection is dropped, as though the
        application had gone, before the desktop takes it all in."""
        app_end, desktop_end = pipe()
        with mock.patch.object(hosting, "MAX_MESSAGE", 64):
            reader = threading.Thread(
                target=self.server._read_all,
                args=(desktop_end,),
                daemon=True,
            )
            with mock.patch.object(self.server, "_authenticate", return_value=True):
                reader.start()
                app_end.send_bytes(encode("menus", menus=[], padding="x" * 200))
                reader.join(5)

        self.assertEqual(self.server.inbox.get(), (desktop_end, None))


class NamesTests(Desktop):
    """An application cannot pass itself off as another, or as Dasha Framework."""

    def greet(self, host_name: str, given: object, guessed: bool) -> str:
        """The name a starting application ends up with, having said its
        name is ``given``."""
        host = AppHost(self.server, "x:Y", host_name, guessed_name=guessed)
        self.server.hosts.append(host)
        self.server._by_token[host.token] = host
        app_end, desktop_end = pipe()
        hello = {"type": "hello", "version": PROTOCOL_VERSION, "token": host.token}

        self.server._greet(desktop_end, {**hello, "name": given})
        self.assertEqual(drain(app_end)[0]["type"], "welcome")
        return host.application.name

    def test_the_desktops_name_stands(self) -> None:
        """Installed, or built in: what it calls itself makes no difference."""
        self.assertEqual(self.greet("Notepad", "Editor", guessed=False), "Notepad")

    def test_a_guessed_name_gives_way(self) -> None:
        """Started by Run..., named after its script: its own name is used,
        on one line and not too long."""
        self.assertEqual(self.greet("app", "Text Stats", guessed=True), "Text Stats")
        self.assertEqual(self.greet("app", "Two\nLines", guessed=True), "Two Lines")
        self.assertEqual(len(self.greet("app", "x" * 500, guessed=True)), 40)

    def test_never_dasha(self) -> None:
        """No application may call itself what the desktop calls itself."""
        self.assertEqual(self.greet("app", "Dasha Desktop", guessed=True), "app")
        self.assertEqual(self.greet("app", "dasha-desktop", guessed=True), "app")
        self.assertEqual(self.greet("app", " \x1b\n ", guessed=True), "app")
        self.assertEqual(application_name(42), "42")


class VersionTests(Desktop):
    """A desktop and an application agree on the highest protocol version
    that both speak, and only one with none in common is refused."""

    def greet(self, hello: Message) -> tuple[AppHost, Message]:
        """A starting application's host, and the answer to its ``hello``."""
        host = AppHost(self.server, "x:Y", "Versioned", guessed_name=False)
        self.server.hosts.append(host)
        self.server._by_token[host.token] = host
        app_end, desktop_end = pipe()
        self.server._greet(desktop_end, {"type": "hello", "token": host.token, **hello})
        return host, drain(app_end)[0]

    def test_the_same_version(self) -> None:
        """The usual case: both ends are of the same release."""
        host, answer = self.greet({"versions": [MINIMUM_VERSION, PROTOCOL_VERSION]})
        self.assertEqual(answer["type"], "welcome")
        self.assertEqual(answer["version"], PROTOCOL_VERSION)
        self.assertEqual(host.version, PROTOCOL_VERSION)

    def test_a_single_version(self) -> None:
        """Without a range, an application speaks its one version."""
        self.assertEqual(
            self.greet({"version": PROTOCOL_VERSION})[1]["type"], "welcome"
        )

    def test_a_newer_application(self) -> None:
        """One that also speaks this desktop's version is welcomed with it."""
        _, answer = self.greet({"versions": [MINIMUM_VERSION, PROTOCOL_VERSION + 5]})
        self.assertEqual(answer["version"], PROTOCOL_VERSION)

    def test_none_in_common(self) -> None:
        """Too new, too old, or nonsense: refused, saying why."""
        for hello in (
            {"versions": [PROTOCOL_VERSION + 1, PROTOCOL_VERSION + 2]},
            {"versions": [MINIMUM_VERSION - 2, MINIMUM_VERSION - 1]},
            {"version": "1"},
            {"versions": [True, True]},
            {"versions": [PROTOCOL_VERSION]},
            {},
        ):
            with self.subTest(hello=hello):
                answer = self.greet(hello)[1]
                self.assertEqual(answer["type"], "refuse")
                self.assertIn("no protocol version in common", answer["reason"])

    def test_a_newer_desktop_speaks_down(self) -> None:
        """A later release that still speaks an older version agrees on it."""
        with (
            mock.patch.object(protocol, "PROTOCOL_VERSION", 3),
            mock.patch.object(protocol, "MINIMUM_VERSION", 1),
        ):
            self.assertEqual(agree_version({"versions": [1, 1]}), 1)
            self.assertEqual(agree_version({"versions": [1, 2]}), 2)
            self.assertEqual(agree_version({"versions": [2, 9]}), 3)
            self.assertIsNone(agree_version({"versions": [4, 9]}))
            self.assertIsNone(agree_version({"versions": [2, 1]}))


class FocusTests(Desktop):
    """An application in the background cannot take the keyboard."""

    def test_a_window_from_the_background_opens_behind(self) -> None:
        """What the user types still goes to the window they were typing in."""
        self.sneaky.handle(state(title="Editor", id=7))
        self.assertEqual(self.manager.windows[-1], self.editor.windows[1])
        drain(self.sneaky_end)
        self.manager.handle_event("s")
        self.assertEqual(of_type(drain(self.sneaky_end), "key"), [])
        self.assertIn({"type": "key", "id": 1, "key": "s"}, drain(self.editor_end))

    def test_its_requests_are_refused(self) -> None:
        """Coming to the front, moving or resizing (which takes the keys),
        switching windows or leaving the desktop: not from the background.
        Minimising its own window: yes."""
        self.sneaky.handle(state(title="Sneaky", id=7))
        with mock.patch.object(self.manager, "request_exit") as exit_:
            for op in ("front", "move", "resize", "restore", "maximise",
                       "toggle_maximise", "next_window", "previous_window",
                       "exit"):  # fmt: skip
                self.sneaky.handle({"type": "request", "id": 7, "op": op})
                self.assertIs(self.manager.active_window, self.editor.windows[1], op)
            exit_.assert_not_called()
        self.sneaky.handle({"type": "request", "id": 7, "op": "minimise"})
        self.assertIn(self.sneaky.windows[7], self.manager.minimised)

    def test_the_active_application_may(self) -> None:
        """The application the user is working in comes forward as asked."""
        self.editor.handle(state(title="Second", id=2))
        self.manager.bring_to_front(self.editor.windows[1])
        self.editor.handle({"type": "request", "id": 2, "op": "front"})
        self.assertEqual(self.front(), "Second")

    def test_while_shutting_down_it_may_ask(self) -> None:
        """Asked whether it may close, an application in the background may
        put its question in front, to offer to save its work."""
        self.server.ask_to_close(lambda: None)
        self.sneaky.handle(
            state(title="Save changes?", id=8, look="dialog", modal=True)
        )
        self.assertEqual(self.front(), "Save changes?")


class ShortcutsTests(Desktop):
    """An application's menus cannot take the desktop's own keys."""

    def test_desktop_keys_are_not_shortcuts(self) -> None:
        """F6, Alt+F4 and the like are taken off its items; its own keys stay."""
        items = [item("&Grab", "F6"), item("&Close", "Alt+F4"), item("&Open", "F3")]
        self.editor.handle(
            {"type": "menus", "menus": [{"title": "&File", "items": items}]}
        )
        shortcuts = [i.shortcut for i in self.editor.application.menus[0].items]
        self.assertEqual(shortcuts, ["", "", "F3"])
        drain(self.editor_end)
        self.manager.handle_event("f6")
        self.assertEqual(of_type(drain(self.editor_end), "menu"), [])


class ClipboardTests(Desktop):
    """Covered with the rest of hosting in test_hosting; here, the desktop
    never hands the clipboard to an application in the background."""

    def test_background_application_is_not_told(self) -> None:
        """A copy in the Editor stays with the Editor and the desktop."""
        drain(self.sneaky_end)
        self.editor.handle({"type": "clipboard", "text": "password"})
        self.server.flush()
        self.assertEqual(of_type(drain(self.sneaky_end), "clipboard"), [])


class HoldingUpTests(Desktop):
    """An application cannot hold up the desktop, or other applications."""

    def test_the_welcome_does_not_wait_for_it(self) -> None:
        """One that never reads: the welcome waits in its outbox, and the
        desktop carries on."""
        host = AppHost(self.server, "x:Y", "Quiet")
        self.server.hosts.append(host)
        self.server._by_token[host.token] = host
        _, desktop_end = pipe()
        done = threading.Event()
        hello = {"type": "hello", "version": PROTOCOL_VERSION, "token": host.token}
        big = "x" * 4_000_000  # far more than a pipe holds unread

        def greet() -> None:
            with mock.patch("dasha.theme.theme_to_json", return_value=big):
                self.server._greet(desktop_end, hello)
            done.set()

        threading.Thread(target=greet, daemon=True).start()
        self.assertTrue(done.wait(5))

    def test_a_stalled_handshake_holds_up_no_one(self) -> None:
        """A connection that never proves it knows the key is dropped after
        handshake_timeout, and others connect meanwhile."""
        self.server.handshake_timeout = 1.0
        self.server._listen()
        address = self.server.address
        stalled = Client(address)  # no key: it never answers the challenge
        self.addCleanup(stalled.close)
        connected = threading.Event()

        def connect() -> None:
            Client(address, authkey=self.server.authkey).close()
            connected.set()

        threading.Thread(target=connect, daemon=True).start()
        self.assertTrue(connected.wait(5))
        started = time.monotonic()
        with self.assertRaises((EOFError, OSError)):  # dropped: the end
            while time.monotonic() - started < 5:
                if stalled.poll(0.2):
                    stalled.recv_bytes()  # the challenge, at first
            self.fail("the stalled connection was not dropped")
        self.addCleanup(self.server.stop_all, 0)

    def test_shutting_down_asks_about_one_that_never_answers(self) -> None:
        """Answering pings but never saying whether it may close: after
        close_timeout the user is asked about it, unless it is asking the
        user something itself."""
        self.server.ask_to_close(lambda: None)
        self.assertIsNone(self.server.stuck())
        self.server._close_asked_at -= self.server.close_timeout
        self.assertIn(self.server.stuck(), (self.editor, self.sneaky))
        for host in (self.editor, self.sneaky):
            host.handle(state(id=9, look="dialog", modal=True))
        self.assertIsNone(self.server.stuck())

    def test_a_flood_of_messages_is_taken_a_little_at_a_time(self) -> None:
        """Each time round, at most max_messages, so the screen is still
        drawn and the keyboard still read."""
        self.server.max_messages = 10
        connection = self.editor.connection
        assert connection is not None
        for _ in range(25):
            self.server.inbox.put(connection, encode("ping"))
        self.server.poll()
        self.assertEqual(len(self.server.inbox), 15)


class LogTests(unittest.TestCase):
    """An application's log after it crashes."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.server = AppServer(PresentationManager())
        self.addCleanup(self.server.stop_all, 0)
        self.server.log_folder = self.folder

    def test_only_the_end_is_read(self) -> None:
        """However much it wrote, only the end of its log is read."""
        host = AppHost(self.server, "x:Y", "Chatty")
        host.log_path = self.folder / "chatty.log"
        host.log_path.write_bytes(b"x" * 5_000_000 + b"\nthe end\n")
        with mock.patch.object(Path, "read_text", side_effect=AssertionError):
            self.assertEqual(host.last_words(), "the end")

    def test_an_empty_log_is_dropped(self) -> None:
        """A log the application wrote nothing to goes once it has ended;
        one it wrote to stays, for its last words."""
        quiet, chatty = AppHost(self.server, "x:Y", "Quiet"), AppHost(
            self.server, "x:Y", "Chatty"
        )
        quiet.log_path = self.folder / "quiet.log"
        quiet.log_path.write_text("")
        chatty.log_path = self.folder / "chatty.log"
        chatty.log_path.write_text("Traceback ...\n")
        for host in (quiet, chatty):
            host.finish(crashed=False)
        self.assertEqual(
            [path.name for path in self.folder.glob("*.log")], ["chatty.log"]
        )

    def test_old_logs_are_deleted(self) -> None:
        """Only the newest LOG_KEEP are kept."""
        for number in range(LOG_KEEP + 5):
            path = self.folder / f"app-{number:03}.log"
            path.write_text("")
            os.utime(path, (number, number))
        self.server.prune_logs()
        kept = sorted(path.name for path in self.folder.glob("*.log"))
        self.assertEqual(len(kept), LOG_KEEP)
        self.assertEqual(kept[0], "app-005.log")

    def test_the_crash_message_says_whose_words(self) -> None:
        """The last line of its log is labelled as such, in the desktop's
        message, not passed off as the desktop's own words."""
        host = AppHost(self.server, "x:Y", "Crashy")
        host.log_path = self.folder / "crashy.log"
        host.log_path.write_text("Enter your password to continue\n")
        self.server.ended(host, crashed=True)
        self.assertIn("The last line of its log:\nEnter", self.server.notices[-1][1])


class StartingTests(unittest.TestCase):
    """How an application's process is started."""

    def test_the_desktops_folder_is_not_on_its_path(self) -> None:
        """Python runs it with -P, so a module planted in the folder the
        desktop runs in is not imported in place of the real one."""
        server = AppServer(PresentationManager())
        self.addCleanup(server.stop_all, 0)
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        server.log_folder = Path(folder.name)
        host = AppHost(server, "x:Y", "App")
        with mock.patch("dasha.hosting.ProcessTree.start") as start:
            start.return_value.process.stdin = io.BytesIO()
            host.start()
        command = start.call_args.args[0]
        self.assertEqual(command[1:4], ["-P", "-m", "dasha.host"])


class ScreenTests(unittest.TestCase):
    """Text that would not take exactly one cell, or cannot be sent at all."""

    def test_shown(self) -> None:
        """Code page 437 as it is; surrogates, wide and zero-width
        characters as UNSHOWABLE; control characters as pictures."""
        cp437 = bytes(range(256)).decode("cp437")
        self.assertEqual("".join(shown(c) for c in cp437[0x20:0x7F]), cp437[0x20:0x7F])
        self.assertTrue(all(shown(c) != UNSHOWABLE for c in cp437[0x80:]))
        odd = (
            "\udcff",  # a surrogate, as a file name that is not UTF-8 becomes
            "\N{CJK UNIFIED IDEOGRAPH-5BEC}",
            "\N{GRINNING FACE}",
            "\N{COMBINING ACUTE ACCENT}",
            "\N{RIGHT-TO-LEFT OVERRIDE}",
            "\N{ZERO WIDTH SPACE}",
            "ab",
        )
        for char in odd:
            with self.subTest(char=ascii(char)):
                self.assertEqual(shown(char), UNSHOWABLE)
        self.assertEqual(shown("\x1b"), "\N{LEFTWARDS ARROW}")

    def test_every_row_stays_its_width(self) -> None:
        """Rendered, a row of odd characters still fills exactly its width."""
        canvas = Canvas(12, 1)
        canvas.write(
            0,
            0,
            "a\N{CJK UNIFIED IDEOGRAPH-5BEC}\N{COMBINING ACUTE ACCENT}b\udcff"
            "\N{RIGHT-TO-LEFT OVERRIDE}\N{GRINNING FACE}z",
        )
        output = canvas.render()
        output.encode("utf-8")  # no surrogates left
        self.assertIn("a??b???z", output)

    def test_a_terminal_that_cannot_hold_a_character(self) -> None:
        """Writing what the terminal's encoding has no room for sends ?
        rather than stopping Dasha Framework."""
        sent = io.BytesIO()
        stream = io.TextIOWrapper(sent, encoding="ascii")
        terminal = Terminal(stream=stream)
        terminal.write("\N{FULL BLOCK}ok")
        stream.flush()
        self.assertEqual(sent.getvalue(), b"?ok")


if __name__ == "__main__":
    unittest.main()
