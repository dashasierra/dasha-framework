"""Tests for what a hosted application's windows and menus tell the desktop."""

from dasha.border import SINGLE, Border
from dasha.canvas import Canvas, Rect
from dasha.client import ClientManager, frame_of
from dasha.dialog import Popup
from dasha.menu import Menu, MenuItem
from dasha.events import MouseEvent
from dasha.protocol import WINDOW_FRAME, ProtocolError, encode_border, send
from dasha.remote import RemoteWindow, decode_frame
from dasha.settings.keys import KeyDialog
from dasha.window import Window
from tests.hosted_apps import Hello
from tests.support import pipe
from tests.test_hosting import WELCOME, ClientCase, DesktopCase, drain, of_type


class ClientWindowTests(ClientCase):
    """What the application sends of its windows and menus."""

    def test_the_minimum_size_is_sent(self) -> None:
        """The window's minimum size goes with its state."""
        self.manager.flush()
        (state,) = of_type(drain(self.desktop), "window")
        self.assertEqual(state["min_size"], [Window.min_width, Window.min_height])
        self.window.min_width, self.window.min_height = 40, 10
        self.manager.flush()
        (state,) = of_type(drain(self.desktop), "window")
        self.assertEqual(state["min_size"], [40, 10])

    def test_nothing_newer_for_version_1(self) -> None:
        """A desktop of version 1 is sent only what it knows."""
        desktop, app_end = pipe()
        manager = ClientManager(app_end, {**WELCOME, "version": 1})
        self.addCleanup(manager.stop_listening)
        manager.launch(Hello)
        manager.flush()
        (state,) = of_type(drain(desktop), "window")
        for name in ("min_size", "frame", "every_key"):
            self.assertNotIn(name, state)

    def test_frame_parts_that_differ_are_sent(self) -> None:
        """Frame parts that differ from the theme go with the state."""
        self.manager.flush()
        (state,) = of_type(drain(self.desktop), "window")
        self.assertEqual(state["frame"], {})
        self.window.border = SINGLE
        self.window.shadow_style = None
        self.window.close_button = "[x]"
        self.window.scroll_step = 3
        self.manager.flush()
        (state,) = of_type(drain(self.desktop), "window")
        self.assertEqual(
            state["frame"],
            {"border": encode_border(SINGLE), "shadow_style": None,
             "close_button": "[x]", "scroll_step": 3},
        )  # fmt: skip
        self.assertEqual(frame_of(Popup("", 10, 4)), {})  # single, as popups are

    def test_a_dialog_that_takes_every_key_says_so(self) -> None:
        """A dialog that takes every key says so."""
        dialog = KeyDialog("help")
        send(self.desktop, "key", id=2, key="f6")  # a key the desktop keeps
        self.assertEqual(self.manager.execute(dialog), "ok")
        self.assertEqual(dialog.key, "f6")
        states = {m["id"]: m for m in of_type(drain(self.desktop), "window")}
        self.assertIs(states[2]["every_key"], True)
        self.assertIs(states[1]["every_key"], False)

    def test_a_menu_is_brought_up_to_date_as_it_opens(self) -> None:
        """The desktop asks for a menu's on_open as it opens."""

        def fill(menu: Menu) -> None:
            menu.items = [MenuItem("&New", print)]

        more = Menu("More", [], on_open=fill)
        self.app.menus = [Menu("&File", [MenuItem("&More", submenu=more)])]
        self.manager.flush()
        (menus,) = of_type(drain(self.desktop), "menus")
        (file_menu,) = menus["menus"]
        self.assertIs(file_menu["on_open"], False)
        self.assertIs(file_menu["items"][0]["submenu"]["on_open"], True)
        for path in ([5], [0, 0, 0], ["x"], [], [0, 9]):
            self.tell("menu_open", path=path)  # nothing there: ignored
        self.assertEqual(more.items, [])
        self.tell("menu_open", path=[0, 0])
        self.manager.flush()
        (menus,) = of_type(drain(self.desktop), "menus")
        (new,) = menus["menus"][0]["items"][0]["submenu"]["items"]
        self.assertEqual(new["label"], "&New")


class DesktopWindowTests(DesktopCase):
    """What the desktop does with it."""

    def drag_grip(self, window: RemoteWindow, row: int, column: int) -> None:
        """Drag a window's resize grip.

        :param window: The window.
        :param row: Screen row to drag to.
        :param column: Screen column to drag to.
        """
        grip = window.resize_grip_rect
        assert grip is not None
        self.manager.handle_event(MouseEvent("press", "left", grip.row, grip.column))
        self.manager.handle_event(MouseEvent("drag", "left", row, column))
        self.manager.handle_event(MouseEvent("release", "left", row, column))

    def test_resizing_keeps_to_its_minimum_size(self) -> None:
        """The desktop keeps to the application's minimum size."""
        window = self.open(min_size=[20, 5])
        self.drag_grip(window, 3, 3)
        self.assertEqual(window.rect, Rect(2, 2, 5, 20))
        self.host.handle(self.state(min_size=[25, 6]))  # changed later
        self.drag_grip(window, 3, 3)
        self.assertEqual(window.rect, Rect(2, 2, 6, 25))

    def test_minimum_size_from_an_earlier_version(self) -> None:
        """Without a minimum size, a window keeps the default one."""
        window = self.open()
        self.drag_grip(window, 3, 3)
        self.assertEqual(window.rect, Rect(2, 2, Window.min_height, Window.min_width))

    def test_the_minimum_size_from_the_application(self) -> None:
        """A minimum size set in the application holds on the desktop."""
        desktop_end, app_end = pipe()
        client = ClientManager(app_end, WELCOME)
        self.addCleanup(client.stop_listening)
        hello = client.launch(Hello).windows[0]
        hello.resizable, hello.min_width = True, 24
        client.flush()
        (state,) = of_type(drain(desktop_end), "window")
        self.host.handle(state)
        window = self.host.windows[state["id"]]
        self.drag_grip(window, 3, 3)
        self.assertEqual(window.rect.width, 24)

    def test_frame_parts_from_the_application(self) -> None:
        """The desktop draws the application's frame parts."""
        border = Border("+", "+", "+", "+", "-", "|")
        frame = {
            "border": encode_border(border), "shadow_style": None,
            "close_button": "[x]", "scroll_step": 3,
        }  # fmt: skip
        window = self.open(frame=frame)
        window.theme_changed()  # a new theme keeps them
        self.assertEqual(window.border, border)
        self.assertIsNone(window.shadow_style)
        self.assertEqual(window.scroll_step, 3)
        self.assertEqual(window.inactive_border, Window.inactive_border)
        canvas = Canvas(80, 24)
        window.paint(canvas, active=True)
        self.assertTrue(canvas.text(2)[2:].startswith("+-[x]"))
        self.host.handle(self.state())  # and without them, the theme's
        self.assertEqual(window.border, Window.border)
        self.assertEqual(window.shadow_style, Window.shadow_style)
        self.assertEqual(window.scroll_step, Window.scroll_step)
        self.host.handle(self.state(look="popup"))
        self.assertEqual(window.border, Popup.border)

    def test_frame_parts_are_checked(self) -> None:
        """Frame parts are kept to what can be drawn."""
        every = {
            "border": encode_border(SINGLE), "inactive_border": encode_border(SINGLE),
            "adjusting_border": encode_border(SINGLE), "shadow_style": None,
            "shadow_width": 99, "shadow_height": -1, "resize_grip": "/\x1b/",
            "close_button": "[" + "x" * 20, "minimise_button": "[v]",
            "maximise_button": "[^]", "restore_button": "[=]", "scroll_step": 0,
        }  # fmt: skip
        frame = decode_frame(every)
        self.assertEqual(tuple(frame), WINDOW_FRAME)
        self.assertEqual((frame["shadow_width"], frame["shadow_height"]), (8, 0))
        self.assertEqual(frame["resize_grip"], "//")
        self.assertEqual(frame["close_button"], "[xxxxxxx")
        self.assertEqual(frame["scroll_step"], 1)
        for bad in (
            "frame", {"border": ["+"] * 5}, {"border": ["++"] * 6},
            {"border": ["\x1b"] * 6}, {"close_button": ""}, {"close_button": 5},
        ):  # fmt: skip
            with self.subTest(frame=bad), self.assertRaises(ProtocolError):
                decode_frame(bad)

    def test_a_dialog_that_takes_every_key(self) -> None:
        """A waiting dialog that takes every key gets the desktop's keys too."""
        self.open(look="dialog", modal=True, every_key=True)
        drain(self.app_end)
        for key in ("f6", "f10", "alt+`"):
            self.manager.handle_event(key)
        keys = [m["key"] for m in of_type(drain(self.app_end), "key")]
        self.assertEqual(keys, ["f6", "f10", "alt+`"])
        self.assertFalse(self.manager.menu_bar.is_open)
        self.assertFalse(self.manager.show_mouse)
        self.host.responding = False  # hung: the desktop keeps its keys
        self.manager.handle_event("f10")
        self.assertTrue(self.manager.menu_bar.is_open)

    def test_other_windows_leave_the_desktop_its_keys(self) -> None:
        """Without every_key, or not waiting, the desktop keeps its keys."""
        for changes in ({"modal": True}, {"every_key": True}):
            with self.subTest(changes=changes):
                self.host.handle(self.state(look="dialog", **changes))
                drain(self.app_end)
                self.manager.handle_event("f6")
                self.assertEqual(of_type(drain(self.app_end), "key"), [])

    def menus(self, more: dict[str, object] | None, on_open: bool = True) -> None:
        """Send a File menu.

        :param more: Its More item's submenu, if any.
        :param on_open: Whether the File menu has an on_open.
        """
        item = {"label": "&New", "enabled": True, "shortcut": "", "status": "",
                "separator": False, "submenu": None}  # fmt: skip
        items = [item, {**item, "label": "&More", "submenu": more}]
        self.host.handle({"type": "menus", "menus": [
            {"title": "&File", "on_open": on_open, "items": items}]})  # fmt: skip

    def test_an_open_menu_asks_and_follows(self) -> None:
        """Opening a menu with on_open asks; its new items show at once."""
        self.open()
        self.host.handle({"type": "menus", "menus": [
            {"title": "&File", "on_open": True, "items": []}]})  # fmt: skip
        drain(self.app_end)
        self.manager.handle_event("alt+f")
        menu_bar = self.manager.menu_bar
        self.assertTrue(menu_bar.is_open)
        self.assertEqual(of_type(drain(self.app_end), "menu_open")[0]["path"], [0])
        self.assertIsNone(menu_bar.highlighted)  # nothing in it yet
        self.menus({"title": "More", "on_open": True, "items": []})
        self.assertTrue(menu_bar.is_open)
        assert menu_bar.open_menu is not None
        self.assertEqual([i.label for i in menu_bar.open_menu.items], ["&New", "&More"])
        assert menu_bar.highlighted is not None
        self.assertEqual(menu_bar.highlighted.label, "&New")

    def test_an_open_submenu_follows(self) -> None:
        """An open submenu stays open while it is there, and shuts once not."""
        self.open()
        more: dict[str, object] = {"title": "More", "on_open": True, "items": []}
        self.menus(more, on_open=False)
        self.manager.handle_event("alt+f")
        menu_bar = self.manager.menu_bar
        self.manager.handle_event("down")
        drain(self.app_end)
        self.assertTrue(menu_bar.open_submenu())
        self.assertEqual(
            of_type(drain(self.app_end), "menu_open"),
            [{"type": "menu_open", "path": [0, 1]}],
        )
        self.menus(more, on_open=False)
        self.assertEqual(len(menu_bar.open_menus), 2)
        self.menus(None, on_open=False)  # More is an item of its own now
        self.assertEqual(len(menu_bar.open_menus), 1)
        self.assertTrue(menu_bar.is_open)
