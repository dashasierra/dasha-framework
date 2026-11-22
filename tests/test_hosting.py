"""Tests for applications in their own processes."""

import os
import stat
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path
from typing import cast
from unittest.mock import patch

from dasha.canvas import Canvas, Rect
from dasha.client import ClientManager, encode_menus
from dasha.clipboard import CLIPBOARD
from dasha.dialog import Dialog, confirm, information
from dasha.widgets import Button, TextBox
from dasha.events import MouseEvent
from dasha.help import DESKTOP_PAGES, HelpDialog
from dasha.hosting import AppHost, AppServer
from dasha.remote import RemoteWindow
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuItem, separator
from dasha.protocol import (
    PROTOCOL_VERSION,
    Message,
    ProtocolError,
    StyleTable,
    decode,
    decode_mouse,
    decode_rect,
    decode_row,
    decode_style,
    encode_mouse,
    encode_rect,
    encode_row,
    encode_style,
    receive,
    send,
)
from dasha.shortcuts import Shortcuts
from dasha.style import BLUE, CYAN, Style
from dasha.terminal import Terminal
from tests.hosted_apps import Broken, Hello, Helpful
from tests.support import hosted, pipe, serving, tests_importable
from tests.test_manager import FakeTerminal

WELCOME: Message = {
    "type": "welcome",
    "version": PROTOCOL_VERSION,
    "size": [80, 24],
    "shortcuts": {},
}


def drain(connection: Connection) -> list[Message]:
    """Every message waiting on a connection.

    :param connection: The connection.
    """
    messages = []
    try:
        while connection.poll(0.1):
            messages.append(receive(connection))
    except (EOFError, OSError):
        pass  # the other end has gone
    return messages


def of_type(messages: list[Message], kind: str) -> list[Message]:
    """The messages of one type.

    :param messages: The messages.
    :param kind: Message type.
    """
    return [message for message in messages if message["type"] == kind]


class ProtocolTests(unittest.TestCase):
    """Encoding values in messages."""

    def test_round_trips(self) -> None:
        """Styles, rects and mouse events survive the trip."""
        style = Style(foreground=BLUE, background=CYAN, bold=True, underline=True)
        self.assertEqual(decode_style(encode_style(style)), style)
        self.assertEqual(decode_rect(encode_rect(Rect(1, 2, 3, 4))), Rect(1, 2, 3, 4))
        event = MouseEvent("press", "left", 3, 4, shift=True, clicks=2)
        self.assertEqual(decode_mouse(encode_mouse(event)), event)

    def test_rows_as_runs(self) -> None:
        """A row is runs of one style; each style is sent once."""
        a, b = Style(foreground=BLUE), Style(background=CYAN)
        cells = [("h", a), ("i", a), (" ", b), ("!", a)]
        table = StyleTable()
        runs = encode_row(cells, table)
        self.assertEqual(runs, [["hi", 0], [" ", 1], ["!", 0]])
        styles = [decode_style(style) for style in table.styles]
        self.assertEqual(decode_row(runs, styles), cells)
        self.assertEqual(encode_row([], table), [])

    def test_bad_messages(self) -> None:
        """Anything but a JSON object with a type is refused."""
        for data in (b"\xff", b"[1]", b'{"no": "type"}', b"{"):
            with self.assertRaises(ProtocolError):
                decode(data)

    def test_send_and_receive(self) -> None:
        """A message arrives as it was sent."""
        here, there = pipe()
        send(here, "key", id=1, key="a")
        self.assertEqual(receive(there), {"type": "key", "id": 1, "key": "a"})


class ClientCase(unittest.TestCase):
    """The application's side, over a pipe instead of the desktop."""

    def setUp(self) -> None:
        self.desktop, app_end = pipe()
        self.manager = ClientManager(app_end, WELCOME)
        self.manager.quit_when_empty = True  # as run_hosted sets it
        self.addCleanup(self.manager.stop_listening)
        self.app = self.manager.launch(Hello)
        self.window = self.app.windows[0]

    def tell(self, kind: str, **fields: object) -> None:
        """Send a message and let it act.

        :param kind: Message type.
        :param fields: Message fields.
        """
        send(self.desktop, kind, **fields)
        self.manager.pump()


class ClientTests(ClientCase):
    """The application's side, over a pipe instead of the desktop."""

    def test_a_change_of_colours_alone_is_sent(self) -> None:
        """A change of colours alone is sent."""
        self.manager.flush()
        drain(self.desktop)
        dark = Style(foreground=CYAN, background=BLUE)
        self.window.body_style = dark
        self.manager.flush()
        paint = of_type(drain(self.desktop), "paint")[0]
        sent = {number for number, _ in paint["rows"]}
        self.assertEqual(sent, set(range(self.window.interior.height)))
        styles = [decode_style(style) for style in paint["styles"]]
        blank = paint["rows"][-1][1]  # the last row: blank, in the body's colours
        self.assertEqual(styles[blank[0][1]], dark)

    def test_window_state_and_contents(self) -> None:
        """The first flush describes the window, its menus and its inside."""
        self.manager.flush()
        messages = drain(self.desktop)
        (state,) = of_type(messages, "window")
        self.assertEqual(state["title"], "Hello")
        self.assertEqual(decode_rect(state["rect"]), Rect(2, 2, 6, 30))
        self.assertEqual(state["look"], "window")
        self.assertEqual(state["flags"], [False, False, False, True])
        (paint,) = of_type(messages, "paint")
        self.assertEqual(paint["size"], [28, 4])
        self.assertEqual(len(paint["rows"]), 4)  # everything, the first time
        first_row = "".join(text for text, _ in paint["rows"][0][1])
        self.assertTrue(first_row.startswith(" Hello"))
        self.manager.flush()
        self.assertEqual(drain(self.desktop), [])  # nothing changed

    def test_keys_reach_the_widgets(self) -> None:
        """Typing changes only the rows it changes, and moves the cursor."""
        self.manager.flush()
        drain(self.desktop)
        number = self.manager.window_id(self.window)
        self.tell("active", id=number)
        self.tell("key", id=number, key="x")
        self.manager.flush()
        paints = of_type(drain(self.desktop), "paint")
        self.assertEqual([row for row, _ in paints[-1]["rows"]], [2])
        self.assertEqual(paints[-1]["cursor"], [2, 3])
        self.assertEqual(self.window.widget("text").value, "x")

    def test_desktop_moves_are_not_sent_back(self) -> None:
        """A move from the desktop is not echoed."""
        self.manager.flush()
        drain(self.desktop)
        number = self.manager.window_id(self.window)
        self.tell("rect", id=number, rect=[5, 6, 8, 40], maximised=False)
        self.assertEqual(self.window.rect, Rect(5, 6, 8, 40))
        self.manager.flush()
        messages = drain(self.desktop)
        self.assertEqual(of_type(messages, "window"), [])
        self.assertEqual(of_type(messages, "paint")[0]["size"], [38, 6])

    def test_window_menu_asks_the_desktop(self) -> None:
        """Window menu items become requests."""
        self.manager.flush()
        drain(self.desktop)
        self.manager.minimise(self.window)
        (request,) = of_type(drain(self.desktop), "request")
        number = self.manager.window_id(self.window)
        self.assertEqual((request["id"], request["op"]), (number, "minimise"))

    def test_menu_choices(self) -> None:
        """Menu choices."""
        chosen: list[str] = []
        sub = Menu("Sub", [MenuItem("&Deep", lambda: chosen.append("deep"))])
        self.app.menus = [
            Menu("&File", [MenuItem("&New", lambda: chosen.append("new")), separator(),
                           MenuItem("&More", submenu=sub),
                           MenuItem("&Off", lambda: chosen.append("off"),
                                    enabled=lambda: False)])  # fmt: skip
        ]
        self.manager.flush()
        (menus,) = of_type(drain(self.desktop), "menus")
        items = menus["menus"][0]["items"]
        self.assertEqual(
            [item["enabled"] for item in items], [True, False, True, False]
        )
        self.tell("menu", path=[0, 0])
        self.tell("menu", path=[0, 2, 0])
        self.tell("menu", path=[0, 3])  # greyed out: ignored
        self.tell("menu", path=[5, 5])  # nothing there: ignored
        self.assertEqual(chosen, ["new", "deep"])

    def test_no_choices_through_a_greyed_out_submenu(self) -> None:
        """No choices through a greyed-out submenu."""
        chosen: list[str] = []
        inner = Menu("Inner", [MenuItem("&Deep", lambda: chosen.append("deep"))])
        self.app.menus = [
            Menu("&Edit", [MenuItem("&More", submenu=inner, enabled=lambda: False)])
        ]
        self.tell("menu", path=[0, 0, 0])
        self.assertEqual(chosen, [])

    def test_menus_as_data(self) -> None:
        """Menus go as labels, shortcuts and enabled flags."""
        menus = [Menu("&File", [MenuItem("&Open", print, "F3", "Opens"), separator(),
                                MenuItem("Off")])]  # fmt: skip
        (data,) = encode_menus(menus)
        self.assertEqual(data["title"], "&File")
        items = cast(list[dict[str, object]], data["items"])
        self.assertEqual(
            [(i["label"], i["enabled"], i["separator"]) for i in items],
            [("&Open", True, False), ("", False, True), ("Off", False, False)],
        )

    def test_execute_waits_for_its_answer(self) -> None:
        """A dialog's answer arrives as input; other windows wait."""
        dialog = confirm("Q", "Sure?")
        dialog_id = 2  # the next window number
        number = self.manager.window_id(self.window)
        send(self.desktop, "key", id=number, key="y")  # to the dialog: no Y there
        send(self.desktop, "key", id=dialog_id, key="enter")
        self.assertEqual(self.manager.execute(dialog), "ok")
        self.assertEqual(self.window.widget("text").value, "")
        messages = drain(self.desktop)
        (state,) = [m for m in of_type(messages, "window") if m["id"] == dialog_id]
        self.assertTrue(state["modal"])
        self.assertEqual(state["look"], "dialog")
        self.assertIn({"type": "close", "id": dialog_id}, messages)

    def test_typing_ahead_reaches_the_dialog(self) -> None:
        """Typing ahead reaches the dialog."""
        dialog = Dialog("Name", 30, 6)
        name = dialog.add(TextBox(1, 1, 20, name="name"))
        dialog.add(Button("&OK", 3, 1, result="ok", default=True))
        number = self.manager.window_id(self.window)
        for key in "hi":
            send(self.desktop, "key", id=number, key=key)
        send(
            self.desktop,
            "mouse",
            id=number,
            event=encode_mouse(MouseEvent("press", "left", 4, 4)),
        )
        send(self.desktop, "key", id=number, key="enter")
        self.assertEqual(self.manager.execute(dialog), "ok")
        self.assertEqual(name.value, "hi")
        self.assertEqual(self.window.widget("text").value, "")

    def test_a_shortcut_goes_to_the_dialog(self) -> None:
        """A shortcut goes to the dialog."""
        chosen: list[str] = []
        self.app.menus = [
            Menu(
                "&Edit",
                [MenuItem("Select &all", lambda: chosen.append("all"), "Ctrl+A")],
            )
        ]
        dialog = Dialog("Name", 30, 6)
        name = dialog.add(TextBox(1, 1, 20, text="untitled.txt", name="name"))
        dialog.add(Button("&OK", 3, 1, result="ok", default=True))
        number = self.manager.window_id(self.window)
        send(self.desktop, "menu", path=[0, 0], key="ctrl+a")
        for key in "new":
            send(self.desktop, "key", id=number, key=key)
        send(self.desktop, "key", id=number, key="enter")
        self.assertEqual(self.manager.execute(dialog), "ok")
        self.assertEqual(name.value, "new")
        self.assertEqual(chosen, [])  # the menu item itself did not run

    def test_a_menu_choice_without_a_key_is_ignored(self) -> None:
        """A menu choice without a key is ignored."""
        chosen: list[str] = []
        self.app.menus = [
            Menu("&Edit", [MenuItem("&All", lambda: chosen.append("all"))])
        ]
        dialog = Dialog("Q", 30, 6)
        dialog.add(Button("&OK", 3, 1, result="ok", default=True))
        send(self.desktop, "menu", path=[0, 0])
        send(self.desktop, "key", id=2, key="enter")
        self.assertEqual(self.manager.execute(dialog), "ok")
        self.assertEqual(chosen, [])

    def test_escape_and_outside(self) -> None:
        """Escape cancels; so does a click outside a drop-down."""
        send(self.desktop, "key", id=2, key="escape")
        self.assertEqual(self.manager.execute(confirm("Q", "?")), "cancel")
        popup = Dialog("P", 10, 4)
        popup.close_on_outside_click = True
        send(self.desktop, "outside", id=3)
        self.assertEqual(self.manager.execute(popup), "cancel")

    def test_close_request(self) -> None:
        """The window closes as it would here; the application runs on."""
        self.manager.flush()
        drain(self.desktop)
        number = self.manager.window_id(self.window)
        self.tell("close_request", id=number)
        self.assertEqual(self.app.windows, [])
        self.assertTrue(self.app.is_running)
        self.assertTrue(self.manager.is_running)
        self.assertIn({"type": "close", "id": number}, drain(self.desktop))

    def test_may_close_and_quit(self) -> None:
        """Asked whether it may close, it answers; quit ends it."""
        self.tell("may_close")
        self.assertEqual(
            drain(self.desktop),
            [{"type": "answer", "question": "may_close", "ok": True}],
        )
        self.tell("quit")
        self.assertFalse(self.app.is_running)
        self.assertFalse(self.manager.is_running)

    def test_clipboard_both_ways(self) -> None:
        """Copies go to the desktop; the desktop's arrive."""
        CLIPBOARD.copy_text("from here")
        self.assertIn({"type": "clipboard", "text": "from here"}, drain(self.desktop))
        self.tell("clipboard", text="from there")
        self.assertEqual(CLIPBOARD.text, "from there")
        self.assertEqual(drain(self.desktop), [])  # not echoed back

    def test_desktop_gone(self) -> None:
        """A closed connection ends the application."""
        self.desktop.close()
        self.manager.pump()
        self.assertFalse(self.manager.is_running)


class DesktopCase(unittest.TestCase):
    """RemoteWindow and AppHost, with the application at the end of a pipe."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.handle_resize(80, 24)
        self.server = serving(self, self.manager)
        self.host = AppHost(self.server, "tests.hosted_apps:Hello", "Hello")
        self.app_end, desktop_end = pipe()
        self.host.connected(desktop_end)
        self.server.hosts.append(self.host)
        self.manager.add_application(self.host.application)

    def state(self, **changes: object) -> Message:
        """A window message, with changes.

        :param changes: Fields to change.
        """
        state: Message = {
            "type": "window", "id": 1, "title": "Hello", "rect": [2, 2, 6, 30],
            "maximised": False, "flags": [True, True, True, True], "look": "window",
            "modal": False, "outside": False, "status": "Hi", "hints": [["F1", "Help"]],
            "footer": [], "content": [28, 4], "scroll": [0, 0],
        }  # fmt: skip
        state.update(changes)
        return state

    def open(self, **changes: object) -> RemoteWindow:
        """Show a window from the application.

        :param changes: Fields to change.
        """
        self.host.handle(self.state(**changes))
        window = self.host.windows[int(cast(int, changes.get("id", 1)))]
        return window


class DesktopSideTests(DesktopCase):
    """RemoteWindow and AppHost, with the application at the end of a pipe."""

    def test_a_window_appears(self) -> None:
        """A window message puts a window on the desktop."""
        window = self.open()
        self.assertIs(self.manager.active_window, window)
        self.assertEqual(window.rect, Rect(2, 2, 6, 30))
        self.assertIn(window, self.host.application.windows)
        self.assertEqual(self.manager.status(), "Hi")
        self.assertEqual(self.manager.key_hints(), [("F10", "Menu"), ("F1", "Help")])

    def test_contents_are_drawn_in_the_frame(self) -> None:
        """Rows sent are drawn inside the frame."""
        window = self.open()
        style = Style(foreground=BLUE)
        self.host.handle(
            {"type": "paint", "id": 1, "size": [28, 4], "styles": [encode_style(style)],
             "rows": [[1, [["Hi there", 0]]]], "cursor": [1, 2]}  # fmt: skip
        )
        canvas = Canvas(80, 24)
        window.paint(canvas, True)
        self.assertEqual(canvas.text(4)[3:11], "Hi there")
        self.assertEqual(canvas.cell(4, 3)[1], style)
        self.assertEqual(canvas.cursor, (4, 5))
        self.assertEqual(canvas.text(2)[2], "╔")

    def test_the_help_key_goes_to_its_window(self) -> None:
        """The help key goes to its window."""
        window = self.open()
        self.manager.handle_event("f1")
        self.assertEqual(
            of_type(drain(self.app_end), "key"),
            [{"type": "key", "id": window.number, "key": "f1"}],
        )

    def test_the_help_key_reaches_it_past_the_desktops_own_help(self) -> None:
        """The system menu's Help must not take the key from its window."""
        window = self.open()
        self.manager.use_own_help()
        self.manager.handle_event("f1")
        self.assertEqual(
            of_type(drain(self.app_end), "key"),
            [{"type": "key", "id": window.number, "key": "f1"}],
        )
        self.assertEqual(self.manager.windows, (window,))

    def test_the_help_key_with_no_window_is_a_message(self) -> None:
        """An application with no window has none to send the key to."""
        self.manager.handle_event("f1")
        self.assertEqual(of_type(drain(self.app_end), "help"), [{"type": "help"}])

    def test_an_application_with_no_window_is_not_given_the_desktops_help(self) -> None:
        """An application with no window is not given the desktops help."""
        self.manager.help_folder = DESKTOP_PAGES
        self.manager.handle_event("f1")
        self.assertEqual(self.manager.windows, ())

    def test_the_desktops_dialog_has_the_desktops_help(self) -> None:
        """The desktop's dialog has the desktop's help."""
        self.open()
        self.manager.help_folder = DESKTOP_PAGES
        dialog = information("About", "Dasha Framework")
        self.manager.add(dialog)
        dialog.modal = True
        seen: list[Dialog] = []
        with (
            patch.object(self.manager, "execute", seen.append),
            patch.object(PresentationManager, "can_show_dialogs", True),
        ):
            self.manager.handle_modal_event(dialog, "f1")
        self.assertEqual([type(shown) for shown in seen], [HelpDialog])
        self.assertEqual(of_type(drain(self.app_end), "help"), [])

    def test_keys_go_on_except_the_desktops(self) -> None:
        """Keys go on, except the desktop's own."""
        window = self.open()
        shortcuts = Shortcuts()
        self.assertTrue(window.handle_key("a", shortcuts))
        self.assertFalse(window.handle_key("f6", shortcuts))  # next window
        self.assertFalse(window.handle_key("ctrl+q", shortcuts))
        window.handle_mouse(MouseEvent("press", "left", 4, 5))
        window.handle_paste("pasted")
        messages = drain(self.app_end)
        self.assertEqual([m["type"] for m in messages], ["key", "mouse", "paste"])

    def test_a_message_it_cannot_act_on_ends_it_alone(self) -> None:
        """A bad message ends only that application."""
        for bad in (
            {"type": "paint", "id": 1, "size": [28, 4], "styles": [],
             "rows": [[0, [["Hi", 5]]]], "cursor": None},
            {"type": "request", "id": None},
        ):  # fmt: skip
            with self.subTest(bad=bad["type"]):
                self.setUp()
                window = self.open()
                connection = cast(Connection, self.host.connection)
                # As _greet does for a connection it welcomes.
                # pylint: disable-next=protected-access
                self.server._by_connection[id(connection)] = self.host
                # pylint: disable-next=protected-access
                self.server._dispatch(connection, bad)
                self.assertTrue(self.host.ended)
                self.assertNotIn(window, self.manager.windows)
                self.assertNotIn(self.host, self.server.hosts)
                self.assertEqual(
                    self.server.notices,
                    [
                        (
                            "Application stopped",
                            "Hello sent something that could not be "
                            "understood, so it was ended.",
                        )
                    ],
                )

    def test_close_asks_the_application(self) -> None:
        """Closing asks; the application closes it."""
        window = self.open()
        self.manager.close(window)
        self.assertIn(window, self.manager.windows)
        self.assertEqual(drain(self.app_end), [{"type": "close_request", "id": 1}])
        self.host.handle({"type": "close", "id": 1})
        self.assertNotIn(window, self.manager.windows)

    def test_menus_stay_behind_its_dialog(self) -> None:
        """Menus stay behind its dialog."""
        self.open()
        self.host.set_menus(encode_menus([Menu("&File", [MenuItem("&New", print)])]))
        self.open(id=2, title="Q", look="dialog", modal=True)
        titles = [menu.title for menu in self.manager.bar_menus()]
        self.assertEqual(titles[1:], ["&File", "&Window"])
        self.assertEqual(self.manager.inert_menus(), [1, 2])

    def test_a_shortcut_with_its_dialog_known(self) -> None:
        """A shortcut with its dialog known."""
        main = self.open()
        self.host.set_menus(
            encode_menus([Menu("&Edit", [MenuItem("&All", print, "Ctrl+A")])])
        )
        dialog = self.open(id=2, title="Q", look="dialog", modal=True)
        self.manager.bring_to_front(main)
        drain(self.app_end)
        self.manager.menu_bar.shortcut_key = "ctrl+a"  # as while a shortcut runs
        try:
            self.host.choose([0, 0])
        finally:
            self.manager.menu_bar.shortcut_key = None
        self.assertIs(self.manager.active_window, dialog)
        self.assertEqual(
            drain(self.app_end), [{"type": "key", "id": 2, "key": "ctrl+a"}]
        )

    def test_the_key_goes_with_a_shortcut(self) -> None:
        """No dialog known: a shortcut's choice carries its key."""
        self.open()
        self.host.set_menus(
            encode_menus([Menu("&Edit", [MenuItem("&All", print, "Ctrl+A")])])
        )
        drain(self.app_end)
        self.manager.handle_event("ctrl+a")
        self.assertEqual(
            drain(self.app_end), [{"type": "menu", "path": [0, 0], "key": "ctrl+a"}]
        )

    def test_a_dialog_blocks_its_own_windows(self) -> None:
        """A dialog blocks its own windows."""
        main = self.open()
        self.host.set_menus(encode_menus([Menu("&File", [MenuItem("&New", print)])]))
        dialog = self.open(id=2, title="Q", look="dialog", modal=True)
        self.assertEqual(dialog.frame_style, Dialog.frame_style)
        self.assertIsNone(dialog.application)
        self.assertEqual(self.host.application.windows, [main])
        self.manager.bring_to_front(main)
        main.handle_key("a", Shortcuts())
        self.assertIs(self.manager.active_window, dialog)
        self.manager.bring_to_front(main)
        action = self.host.application.menus[0].items[0].action
        assert action is not None
        action()
        self.assertIs(self.manager.active_window, dialog)
        self.assertEqual(drain(self.app_end), [])

    def test_greyed_out_submenus_stay_greyed(self) -> None:
        """Greyed-out submenus stay greyed."""
        self.open()
        inner = Menu("Inner", [MenuItem("&Deep", print)])
        greyed = MenuItem("&More", submenu=inner, enabled=lambda: False)
        self.host.set_menus(encode_menus([Menu("&Edit", [greyed])]))
        (item,) = self.host.application.menus[0].items
        self.assertIsNotNone(item.submenu)
        self.assertFalse(item.is_available)

    def test_a_menu_after_the_window_menu(self) -> None:
        """A menu after the Window menu."""
        self.open()
        self.host.handle(
            {"type": "menus", "menus": encode_menus(
                [Menu("&Help", [MenuItem("&Index", print)], after_window=True),
                 Menu("&File", [MenuItem("&New", print)])])}
        )  # fmt: skip
        menus = self.manager.bar_menus()[1:]
        self.assertEqual([m.title for m in menus], ["&File", "&Window", "&Help"])
        action = menus[-1].items[0].action
        assert action is not None
        action()
        self.assertEqual(drain(self.app_end), [{"type": "menu", "path": [0, 0]}])

    def test_menus_from_an_earlier_version(self) -> None:
        """Menus from an earlier version."""
        self.open()
        self.host.handle(
            {"type": "menus", "menus": [
                {"title": "&File", "items": []},
                {"title": "&Edit", "items": [], "after_window": "yes"}]}
        )  # fmt: skip
        self.assertEqual(
            [menu.title for menu in self.manager.bar_menus()][1:],
            ["&File", "&Edit", "&Window"],
        )

    def test_menu_choices_go_back(self) -> None:
        """Menu choices go back."""
        self.open()
        self.host.handle(
            {"type": "menus", "menus": encode_menus(
                [Menu("&File", [MenuItem("&New", print), MenuItem("Off")])])}
        )  # fmt: skip
        self.assertEqual(
            [menu.title for menu in self.manager.bar_menus()][1:], ["&File", "&Window"]
        )
        file_menu = self.host.application.menus[0]
        action = file_menu.items[0].action
        assert action is not None
        self.assertIsNone(file_menu.items[1].action)
        action()
        self.assertEqual(drain(self.app_end), [{"type": "menu", "path": [0, 0]}])

    def test_flush_tells_what_changed(self) -> None:
        """Active window, size and moves go to it."""
        window = self.open()
        self.server.flush()
        messages = drain(self.app_end)
        self.assertIn({"type": "active", "id": 1}, messages)
        self.assertIn({"type": "size", "columns": 80, "lines": 24}, messages)
        self.assertEqual(of_type(messages, "rect"), [])
        window.move_to(5, 5)
        self.server.flush()
        moved = drain(self.app_end)[-1]
        self.assertEqual((moved["type"], moved["rect"]), ("rect", [5, 5, 6, 30]))

    def test_outside_press_closes_a_drop_down(self) -> None:
        """A press outside closes a drop-down."""
        self.open(look="popup", modal=True, outside=True)
        self.assertTrue(self.server.outside_press(MouseEvent("press", "left", 20, 70)))
        self.assertFalse(self.server.outside_press(MouseEvent("press", "left", 3, 3)))
        self.assertEqual(drain(self.app_end), [{"type": "outside", "id": 1}])

    def test_asking_to_close(self) -> None:
        """No stops shutting down; yes from all goes on."""
        closed: list[bool] = []
        self.server.ask_to_close(lambda: closed.append(True))
        self.assertEqual(drain(self.app_end), [{"type": "may_close"}])
        self.server.answered(self.host, False)
        self.assertEqual(closed, [])
        self.server.ask_to_close(lambda: closed.append(True))
        self.server.answered(self.host, True)
        self.assertEqual(closed, [True])

    def other_application(self) -> tuple[AppHost, Connection]:
        """A second application, in the background behind Hello."""
        other = AppHost(self.server, "x:Y", "Other")
        other_end, other_desktop_end = pipe()
        other.connected(other_desktop_end)
        self.server.hosts.append(other)
        self.manager.add_application(other.application)
        self.manager.switch_to(self.host.application)
        return other, other_end

    def test_it_cannot_put_its_window_off_screen(self) -> None:
        """It cannot put its window off screen."""
        window = self.open()
        drain(self.app_end)
        self.host.handle(self.state(rect=[2, 9000, 6, 30]))
        self.assertEqual(window.rect.column, 80 - 4)
        self.host.flush()
        self.assertIn("rect", [m["type"] for m in drain(self.app_end)])

    def test_a_click_on_its_hint_presses_the_key(self) -> None:
        """A click on its hint presses the key."""
        self.open()
        drain(self.app_end)
        places = self.manager.status_bar.hint_places(
            80, self.manager.key_hints(), self.manager.status_owner
        )
        begin = next(begin for begin, _, (key, _) in places if key == "F1")
        self.manager.handle_event(MouseEvent("press", "left", 23, begin + 1))
        self.assertIn({"type": "key", "id": 1, "key": "f1"}, drain(self.app_end))

    def test_shared_clipboard(self) -> None:
        """The shared clipboard."""
        other, other_end = self.other_application()
        self.host.handle({"type": "clipboard", "text": "shared"})
        self.assertEqual(CLIPBOARD.text, "shared")
        other.handle(self.state(title="Other"))  # opens behind Hello's work
        self.server.flush()
        self.assertNotIn("clipboard", [m["type"] for m in drain(other_end)])
        # No echo of its own copy.
        self.assertNotIn("clipboard", [m["type"] for m in drain(self.app_end)])
        self.manager.switch_to(other.application)
        self.server.flush()
        self.assertIn({"type": "clipboard", "text": "shared"}, drain(other_end))

    def test_background_application_cannot_set_the_clipboard(self) -> None:
        """A background application cannot set the clipboard."""
        other, _ = self.other_application()
        CLIPBOARD.copy_text("mine")
        other.handle({"type": "clipboard", "text": "rm -rf ~"})
        self.assertEqual(CLIPBOARD.text, "mine")

    def test_crash(self) -> None:
        """Ending without a goodbye: its windows go, and it is reported."""
        self.open()
        self.host.finish(crashed=True)
        self.assertEqual(self.manager.windows, ())
        self.assertEqual(self.manager.applications, ())
        self.assertEqual(
            self.server.notices,
            [("Application stopped", "Hello stopped unexpectedly.")],
        )

    def test_a_goodbye_is_no_crash(self) -> None:
        """An application that says goodbye did not crash."""
        self.open()
        self.host.handle({"type": "bye"})
        self.app_end.close()
        self.server.poll()  # nothing queued: the reader thread is not running
        self.host.finish(crashed=not self.host.said_bye)
        self.assertEqual(self.server.notices, [])


class SlowTerminal(FakeTerminal):
    """A terminal that waits for real until done.

    :param manager: The desktop.
    :param done: Returns whether to stop.
    """

    def __init__(self, manager: PresentationManager, done: Callable[[], bool]) -> None:
        super().__init__([], sizes=[(80, 24)])
        self.manager = manager
        self.done = done
        self.deadline = time.monotonic() + 30  # as long as it has to connect

    def read(self, timeout: float | None = None) -> str:
        if self.done() or time.monotonic() > self.deadline:
            self.manager.quit()
        time.sleep(0.02)
        return ""


class ProcessTests(unittest.TestCase):
    """Real application processes."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        tests_importable(self)
        self.manager = PresentationManager()
        self.manager.use_processes = True
        self.server = serving(self, self.manager)
        self.server.log_folder = Path(folder.name)

    def run_until(self, done: Callable[[], bool]) -> None:
        """Run the desktop until done.

        :param done: Returns whether to stop.
        """
        self.manager.run(cast(Terminal, SlowTerminal(self.manager, done)))

    def test_an_application_in_its_own_process(self) -> None:
        """It starts, connects and shows."""
        self.manager.start(Hello)
        self.run_until(lambda: bool(self.manager.windows))
        self.assertEqual([w.title for w in self.manager.windows], ["Hello"])
        self.assertEqual(self.server.hosts, [])  # stopped with the desktop
        self.assertEqual(self.server.notices, [])

    def test_help_in_its_own_process(self) -> None:
        """Help in its own process."""
        self.manager.start(Helpful)
        seen: dict[str, object] = {}

        def helped() -> bool:
            front = self.manager.windows[-1] if self.manager.windows else None
            if not isinstance(front, RemoteWindow):
                return False
            if "pressed" not in seen:
                seen["pressed"] = True
                self.manager.handle_event("f1")
            elif front.title == "Helpful Help" and "body" not in seen:
                # pylint: disable-next=protected-access
                rows = front._runs
                cells = "".join(text for runs in rows for text, _ in runs)
                if not cells.strip():
                    return False  # its rows come in a message after its frame
                seen["body"] = front.body_style.background
                seen["hints"] = self.manager.key_hints()
                seen["cells"] = cells
                self.manager.handle_event("escape")
            elif "body" in seen:
                return front.title == "Helpful"
            return False

        self.run_until(helped)
        self.assertEqual(seen["body"], CYAN)
        self.assertIn(("Esc", "Close"), cast(list[tuple[str, str]], seen["hints"]))
        self.assertIn("The text box", cast(str, seen["cells"]))
        self.assertEqual(self.server.notices, [])

    def test_a_crash_is_reported(self) -> None:
        """The desktop says which application stopped, and its last words."""
        said: list[object] = []

        def reported() -> bool:
            for window in self.manager.windows:
                if window.title == "Application stopped":
                    said.extend(window.values.values())
            return bool(said)

        self.manager.start(Broken)
        self.run_until(reported)
        self.assertIn("Broken stopped unexpectedly.", said)
        self.assertIn("RuntimeError: broken on purpose", said)

    def test_its_log_is_private(self) -> None:
        """Its log is private."""
        self.server.log_folder = self.server.log_folder / "logs"
        self.manager.start(Hello)
        host = self.server.hosts[0]
        modes: list[int] = []

        def running() -> bool:
            """While Hello runs (its log, empty, goes once it has ended)."""
            if not self.manager.windows:
                return False
            assert host.log_path is not None
            modes.append(stat.S_IMODE(host.log_path.stat().st_mode))
            modes.append(stat.S_IMODE(self.server.log_folder.stat().st_mode))
            return True

        self.run_until(running)
        assert host.log_path is not None
        self.assertNotIn(host.token[:6], host.log_path.name)
        if os.name == "posix":
            self.assertEqual(modes, [0o600, 0o700])
        self.assertFalse(host.log_path.exists())  # Hello wrote nothing

    def test_protocol_version(self) -> None:
        """There is a version to check."""
        self.assertIsInstance(PROTOCOL_VERSION, int)


def own_threads() -> list[str]:
    """The desktop's running threads."""
    return [
        thread.name
        for thread in threading.enumerate()
        if thread.is_alive()
        and ("_send_all" in thread.name or "_accept_all" in thread.name)
    ]


class ListenerTests(unittest.TestCase):
    """Accepting connections."""

    def test_stop_all_ends_its_threads(self) -> None:
        """``stop_all`` ends its threads."""
        # pylint: disable=protected-access
        before = own_threads()
        server = AppServer(PresentationManager())
        hosted(server, "One")
        hosted(server, "Two")
        server._listen()
        self.assertGreater(len(own_threads()), len(before))
        server.stop_all(0)
        deadline = time.monotonic() + 30  # a busy machine; they do end
        while own_threads() != before and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(own_threads(), before)

    def test_accept_failing_over_and_over(self) -> None:
        """A failing accept backs off."""
        # pylint: disable=protected-access
        server = AppServer(PresentationManager())
        self.addCleanup(server.stop_all, 0)
        tries = []

        class Failing:  # pylint: disable=too-few-public-methods
            """A listener whose every accept fails."""

            def accept(self) -> None:
                """Fail, noting when."""
                tries.append(time.monotonic())
                raise OSError("no handles left")

        server._listener = Failing()  # type: ignore[assignment]
        thread = threading.Thread(target=server._accept_all, daemon=True)
        thread.start()
        time.sleep(0.5)
        server._listener = None
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertGreaterEqual(len(tries), 2)
        self.assertLessEqual(len(tries), 8)


if __name__ == "__main__":
    unittest.main()
