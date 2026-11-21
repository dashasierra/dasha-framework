"""More tests for the application side of the desktop."""

import json
import os
import sys
import threading
import unittest
from io import StringIO
from multiprocessing.connection import Connection
from unittest import mock

from dasha import client, theme
from dasha.canvas import Rect
from dasha.client import ClientManager, look_of, run_hosted
from dasha.dialog import Dialog, ListPopup
from dasha.events import MouseEvent
from dasha.processes import DESKTOP_PID_VARIABLE
from dasha.protocol import (
    ADDRESS_VARIABLE,
    MINIMUM_VERSION,
    PROTOCOL_VERSION,
    Message,
    encode_mouse,
    receive,
    send,
)
from dasha.widgets import TextBox, Widget
from dasha.window import Window
from tests.hosted_apps import Hello
from tests.test_hosting import WELCOME, drain, of_type
from tests.support import pipe


class Client(unittest.TestCase):
    """A client manager running Hello, over a pipe instead of the desktop."""

    def setUp(self) -> None:
        self.desktop, self.app_end = pipe()
        self.manager = ClientManager(self.app_end, WELCOME)
        self.manager.quit_when_empty = True
        self.addCleanup(self.manager.stop_listening)
        self.app = self.manager.launch(Hello)
        self.window = self.app.windows[0]
        self.manager.flush()
        drain(self.desktop)

    def tell(self, kind: str, **fields: object) -> None:
        """Send a message and let it act.

        :param kind: Message type.
        :param fields: Message fields.
        """
        send(self.desktop, kind, **fields)
        self.manager.pump()

    def number(self, window: Window) -> int:
        """The desktop's id for a window.

        :param window: The window.
        """
        return self.manager.window_id(window)


class RequestTests(Client):
    """What the application asks the desktop to do with its windows."""

    def test_window_requests(self) -> None:
        """Each window operation is a request for the desktop."""
        manager, window = self.manager, self.window
        manager.send_to_back(window)
        manager.maximise(window)
        manager.minimise(window)
        manager.restore(window)
        manager.toggle_maximise(window)
        manager.start_moving(window)
        manager.start_resizing(window)
        manager.start_moving()
        manager.activate_next()
        manager.activate_previous()
        manager.request_exit()
        requests = [(m["id"], m["op"]) for m in of_type(drain(self.desktop), "request")]
        number = self.number(window)
        self.assertEqual(
            requests,
            [
                (number, "send_to_back"),
                (number, "maximise"),
                (number, "minimise"),
                (number, "restore"),
                (number, "toggle_maximise"),
                (number, "move"),
                (number, "resize"),
                (None, "move"),
                (None, "next_window"),
                (None, "previous_window"),
                (None, "exit"),
            ],
        )

    def test_unsent_window_closes_quietly(self) -> None:
        """A window the desktop never heard of goes without a close message."""
        other = Window("Other", Rect(1, 1, 5, 20))
        self.manager.add(other)
        self.manager.remove(other)
        self.assertEqual(of_type(drain(self.desktop), "close"), [])

    def test_looks(self) -> None:
        """A window, a dialog, and a drop-down popup."""
        self.assertEqual(look_of(self.window), "window")
        self.assertEqual(look_of(Dialog("D", 20, 5)), "dialog")
        self.assertEqual(look_of(ListPopup(["a"], 0, 10, 1)), "popup")


class MessageTests(Client):
    """Messages from the desktop about windows."""

    def big_window(self) -> Window:
        """A window with more lines than fit, sideways and down."""
        lines = ["x" * 80 for _ in range(40)]
        window = Window("Big", Rect(1, 1, 8, 20), lines)
        self.manager.add(window)
        self.manager.flush()
        drain(self.desktop)
        return window

    def test_scroll(self) -> None:
        """The desktop's scroll bars scroll the window."""
        window = self.big_window()
        self.tell("scroll", id=self.number(window), row=5, column=3)
        self.assertEqual((window.scroll_row, window.scroll_column), (5, 3))

    def test_wheel_where_no_widget_takes_it(self) -> None:
        """The wheel scrolls the window: down, and sideways with Shift."""
        window = self.big_window()
        number = self.number(window)
        down = MouseEvent("scroll", "down", 3, 3)
        self.tell("mouse", id=number, event=encode_mouse(down))
        self.assertEqual(window.scroll_row, 3)
        sideways = MouseEvent("scroll", "down", 3, 3, shift=True)
        self.tell("mouse", id=number, event=encode_mouse(sideways))
        self.assertEqual(window.scroll_column, 3)
        left = MouseEvent("scroll", "left", 3, 3)
        self.tell("mouse", id=number, event=encode_mouse(left))
        self.assertEqual(window.scroll_column, 0)

    def test_paste_and_release(self) -> None:
        """Pasted text goes to the focused widget; a release is heard."""
        number = self.number(self.window)
        self.tell("paste", id=number, text="pasted")
        box = self.window.widget("text")
        assert isinstance(box, TextBox)
        self.assertEqual(box.text, "pasted")
        self.tell("release", id=number, key=" ")  # nothing to do, nothing breaks

    def test_outside_a_popup_cancels_it(self) -> None:
        """A click outside a drop-down list closes it; outside a window, no."""
        popup = ListPopup(["a", "b"], 0, 10, 2)
        self.manager.add(popup)
        self.tell("outside", id=self.number(self.window))
        self.tell("outside", id=self.number(popup))
        self.assertEqual(popup.result, "cancel")

    def test_empty_menu_path(self) -> None:
        """A menu choice with no path does nothing."""
        self.tell("menu", path=[])
        self.assertTrue(self.app.is_running)

    def test_unknown_window(self) -> None:
        """A message for a window that has gone is let be."""
        self.tell("key", id=999, key="a")
        self.assertTrue(self.app.is_running)


class LoopTests(Client):
    """The application's loop, dialogs, and the desktop going."""

    def test_can_show_dialogs_until_quit(self) -> None:
        """While running; not once told to quit."""
        self.assertTrue(self.manager.can_show_dialogs)
        self.tell("quit")
        self.assertFalse(self.manager.can_show_dialogs)

    def test_dialog_ended_by_quitting(self) -> None:
        """Quitting answers a waiting dialog with None."""
        dialog = Dialog("Question", 20, 6)
        send(self.desktop, "quit")
        self.assertIsNone(self.manager.execute(dialog))
        self.assertNotIn(dialog, self.manager.windows)
        self.assertEqual(dialog.rect.column, (80 - 20) // 2)

    def test_serve_says_goodbye(self) -> None:
        """Serving until told to quit, then bye, and the connection closed."""
        send(self.desktop, "quit")
        self.manager.serve()
        self.assertIn("bye", [m["type"] for m in drain(self.desktop)])
        self.assertTrue(self.app_end.closed)

    def test_call_when_running(self) -> None:
        """``call_when_running`` waits for serving."""
        called: list[str] = []
        self.manager.call_when_running(lambda: called.append("held"))
        self.assertEqual(called, [])

        def serving() -> None:
            called.append("serving")
            self.manager.call_when_running(lambda: called.append("at once"))
            send(self.desktop, "quit")

        self.manager.call_when_running(serving)
        self.manager.serve()
        self.assertEqual(called, ["held", "serving", "at once"])

    def test_the_desktop_going(self) -> None:
        """The other end closing ends the loop."""
        self.desktop.close()
        self.manager.pump()
        self.assertFalse(self.manager.can_show_dialogs)

    def test_cannot_send(self) -> None:
        """A failed send ends the client."""
        with mock.patch.object(client, "send", side_effect=OSError):
            self.manager.request_exit()
        self.assertFalse(self.manager.can_show_dialogs)
        self.app_end.close()
        self.manager.request_exit()  # closed: quietly nothing


class RunHostedTests(unittest.TestCase):
    """Starting up: reaching the desktop, and being welcomed or not."""

    def setUp(self) -> None:
        saved = theme.current_theme()
        self.addCleanup(theme.apply_theme, saved)
        self.err = StringIO()
        quiet = mock.patch.object(sys, "stderr", self.err)
        quiet.start()
        self.addCleanup(quiet.stop)
        watching = mock.patch.object(client, "watch_parent")
        self.watch = watching.start()
        self.addCleanup(watching.stop)

    def run_with(self, *answers: Message, close: bool = False) -> int:
        """Run Hello hosted against a scripted desktop.

        :param answers: Messages the desktop sends.
        :param close: Whether the desktop is gone before it starts.
        """
        desktop, app_end = pipe()
        self.sent: list[Message] = []  # pylint: disable=attribute-defined-outside-init
        thread = threading.Thread(
            target=self._desktop, args=(desktop, answers), daemon=True
        )
        if close:
            desktop.close()
        else:
            thread.start()
        with mock.patch.object(client, "connect", return_value=(app_end, "token")):
            code = run_hosted(Hello())
        if not close:
            app_end.close()
            thread.join(timeout=5)
        return code

    def _desktop(self, desktop: Connection, answers: tuple[Message, ...]) -> None:
        """Send the answers and read everything sent.

        :param desktop: The desktop's connection end.
        :param answers: Messages to send.
        """
        for answer in answers:
            fields = {k: v for k, v in answer.items() if k != "type"}
            try:
                send(desktop, str(answer["type"]), **fields)
            except OSError:
                break
        try:
            while True:
                self.sent.append(receive(desktop))
        except (EOFError, OSError):
            pass

    def test_cannot_reach_the_desktop(self) -> None:
        """A bad key on standard input: said, and exit 1."""
        with (
            mock.patch.dict(os.environ, {ADDRESS_VARIABLE: "nowhere"}),
            mock.patch.object(sys, "stdin", StringIO("not-hex token\n")),
        ):
            self.assertEqual(run_hosted(Hello()), 1)
        self.assertIn("cannot reach the desktop", self.err.getvalue())

    def test_refused(self) -> None:
        """The desktop refuses it: said why, exit 1."""
        self.assertEqual(self.run_with({"type": "refuse", "reason": "too old"}), 1)
        self.assertIn("refused: too old", self.err.getvalue())
        hello = of_type(self.sent, "hello")[0]
        self.assertEqual((hello["name"], hello["token"]), ("Hello", "token"))

    def test_an_unknown_version(self) -> None:
        """Welcomed with a version it does not speak: said, exit 1."""
        welcome = dict(WELCOME, version=PROTOCOL_VERSION + 1)
        self.assertEqual(self.run_with(welcome, {"type": "quit"}), 1)
        self.assertIn("protocol version", self.err.getvalue())
        hello = of_type(self.sent, "hello")[0]
        self.assertEqual(hello["versions"], [MINIMUM_VERSION, PROTOCOL_VERSION])

    def test_desktop_went_away(self) -> None:
        """No welcome at all: said, exit 1."""
        self.assertEqual(self.run_with(close=True), 1)
        self.assertIn("went away", self.err.getvalue())

    def test_welcomed_with_a_theme(self) -> None:
        """Welcomed with a theme, it runs until told to quit."""
        colours = theme.theme_to_json(theme.MONOCHROME_THEME, base="monochrome")
        welcome = dict(WELCOME, theme=colours, key_releases=True)
        with mock.patch.dict(os.environ, {DESKTOP_PID_VARIABLE: "321"}):
            code = self.run_with(welcome, {"type": "quit"})
        self.assertEqual(code, 0)
        self.assertEqual(Window.frame_style, theme.MONOCHROME_THEME["window.frame"])
        self.watch.assert_called_once_with(321)
        self.assertIn("bye", [m["type"] for m in self.sent])
        json.loads(colours)  # what was sent was a colours file
        # Key releases were reported while it ran, and are not left on.
        self.assertFalse(Widget.key_releases)


if __name__ == "__main__":
    unittest.main()
