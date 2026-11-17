"""Tests for context menus: popped up by a right-click or Shift+F10."""

import unittest
from typing import cast

from dasha.canvas import Canvas, Rect
from dasha.client import ClientManager
from dasha.clipboard import Clipboard
from dasha.dialog import Dialog, MenuPopup
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuBar, MenuItem, separator
from dasha.protocol import encode_mouse, send
from dasha.shortcuts import Shortcuts
from dasha.terminal import Terminal
from dasha.widgets import Label, ListBox, PasswordBox, TextArea, TextBox
from dasha.window import Window
from tests.hosted_apps import Hello
from tests.test_hosting import WELCOME, drain
from tests.support import pipe
from tests.test_manager import FakeTerminal

DOWN, ESCAPE, SHIFT_F10 = "\x1b[B", "\x1b", "\x1b[21;2~"


def right_click(row: int, column: int) -> list[str]:
    """A right button press and release at a screen position."""
    return [f"\x1b[<2;{column + 1};{row + 1}M", f"\x1b[<2;{column + 1};{row + 1}m"]


def left_click(row: int, column: int) -> list[str]:
    """A left button press and release at a screen position."""
    return [f"\x1b[<0;{column + 1};{row + 1}M", f"\x1b[<0;{column + 1};{row + 1}m"]


class Recording(PresentationManager):
    """Notes each popup it shows."""

    def __init__(self, windows: list[Window]) -> None:
        super().__init__(windows=windows)
        self.popups: list[MenuPopup] = []

    def execute(self, dialog: Dialog) -> str | None:
        if isinstance(dialog, MenuPopup):
            self.popups.append(dialog)
        return super().execute(dialog)


class ContextMenuTests(unittest.TestCase):
    """A window with a text box of "hello" (inside on screen row 3, from
    column 2), a label with a menu of its own, and a menu for the window."""

    def setUp(self) -> None:
        self.done: list[str] = []
        self.window = Window("W", Rect(1, 0, 12, 40))
        self.box = self.window.add(TextBox(1, 1, 20, text="hello"))
        self.box.clipboard = Clipboard()
        self.label = self.window.add(Label("label", 4, 1))
        self.label.context_menu = Menu(
            "Label",
            [
                MenuItem("&First", lambda: self.done.append("first"), status="First"),
                separator(),
                MenuItem("&Greyed"),
                MenuItem(
                    "&More",
                    submenu=Menu(
                        "More", [MenuItem("&Inner", lambda: self.done.append("inner"))]
                    ),
                ),
            ],
        )
        self.window.context_menu = Menu(
            "Window", [MenuItem("&Window item", lambda: self.done.append("window"))]
        )
        self.manager = Recording([self.window])

    def run_with(self, inputs: list[str]) -> None:
        """Run on scripted input, then Ctrl+Q and Shutdown."""
        terminal = FakeTerminal([*inputs, "\x11", "\r"], sizes=[(60, 20)])
        self.manager.run(cast(Terminal, terminal))
        self.assertEqual(terminal.inputs, [])

    def labels(self, number: int = 0) -> list[str]:
        """The labels of a popup shown."""
        return [item.label for item in self.manager.popups[number].menu.items]

    def test_a_text_box_has_one_of_its_own(self) -> None:
        """Right-click: Undo, Cut, Copy, Paste and Select all; A selects all."""
        self.run_with([*right_click(3, 4), "a"])
        self.assertEqual(
            [label for label in self.labels() if label],
            ["&Undo", "Cu&t", "&Copy", "&Paste", "Select &all"],
        )
        self.assertEqual(self.box.selection, (0, 5))

    def test_greyed_out_items_are_skipped(self) -> None:
        """Nothing to undo or paste and nothing selected: only Select all
        can be chosen, so Enter chooses it."""
        self.run_with([*right_click(3, 4), "\r"])
        popup = self.manager.popups[0]
        self.assertEqual(popup.items.highlight, len(popup.menu.items) - 1)
        self.assertEqual(self.box.selection, (0, 5))

    def test_cut_and_paste(self) -> None:
        """With a selection, Cut is there; then Paste."""
        self.box.select_all()
        self.run_with([*right_click(3, 4), "t", *right_click(3, 4), "p"])
        self.assertEqual(self.box.text, "hello")
        self.assertEqual(self.box.clipboard.text, "hello")

    def test_a_widget_of_its_own(self) -> None:
        """The label's menu; its action runs once the menu has closed."""
        self.run_with([*right_click(6, 3), "f"])
        self.assertEqual(self.done, ["first"])

    def test_submenus(self) -> None:
        """Right opens a submenu beside the item; Enter chooses in it."""
        self.run_with([*right_click(6, 3), "m", "\r"])
        self.assertEqual(self.done, ["inner"])
        self.assertEqual(len(self.manager.popups), 2)
        self.assertTrue(self.manager.popups[1].submenu)

    def test_left_closes_a_submenu(self) -> None:
        """Down goes past the separator and the greyed item to More; Right
        opens its submenu, Left closes it only, and Escape the menu; Up
        from the first item goes round to the last."""
        self.run_with(
            [
                *right_click(6, 3),
                DOWN,
                "\x1b[C",
                "\x1b[D",
                "\x1b[A",
                "\x1b[A",
                ESCAPE,
                "",
            ]
        )
        self.assertEqual(self.done, [])
        self.assertEqual(len(self.manager.popups), 2)  # the submenu opened
        self.assertEqual(self.manager.popups[0].items.highlight, 3)  # back on More

    def test_a_lists_row_is_highlighted_first(self) -> None:
        """A right-click on a list's item highlights it before its menu
        pops up, so the menu acts on what was clicked."""
        window = Window("W", Rect(1, 0, 10, 30))
        items = window.add(ListBox(["a", "b", "c"], 0, 0, 10, 3))
        chosen: list[str] = []
        items.context_menu = Menu(
            "Items", [MenuItem("&Show", lambda: chosen.append(items.selected_items[0]))]
        )
        manager = Recording([window])
        terminal = FakeTerminal(
            [*right_click(4, 2), "s", "\x11", "\r"], sizes=[(60, 20)]
        )
        manager.run(cast(Terminal, terminal))
        self.assertEqual(chosen, ["c"])

    def test_the_window_has_one(self) -> None:
        """Right-click where no widget has a menu: the window's."""
        self.run_with([*right_click(9, 20), "w"])
        self.assertEqual(self.done, ["window"])

    def test_shift_f10(self) -> None:
        """Shift+F10 pops up the focused widget's menu (the text box's) under
        it; Enter takes its one item that can be chosen, Select all."""
        self.run_with([SHIFT_F10, "\r"])
        self.assertEqual(self.box.selection, (0, 5))
        popup = self.manager.popups[0]
        self.assertEqual(popup.rect.row, self.window.screen_rect(self.box).row + 1)

    def test_shift_f10_without_a_widget_menu(self) -> None:
        """No widget's menu: the window's, at the top left of its inside."""
        window = Window("W", Rect(1, 0, 8, 30))
        window.context_menu = Menu(
            "W", [MenuItem("&Go", lambda: self.done.append("go"))]
        )
        manager = Recording([window])
        terminal = FakeTerminal([SHIFT_F10, "g", "\x11", "\r"], sizes=[(60, 20)])
        manager.run(cast(Terminal, terminal))
        self.assertEqual(self.done, ["go"])

    def test_mouse_in_the_menu(self) -> None:
        """A click on an item chooses it; one on the separator or a greyed
        item does nothing; one outside closes the menu."""
        clicks = [*left_click(8, 4), *left_click(9, 4)]  # separator, greyed
        self.run_with([*right_click(6, 3), *clicks, ESCAPE, ""])
        self.assertEqual(self.done, [])
        self.run_with([*right_click(6, 3), *left_click(7, 4)])
        self.assertEqual(self.done, ["first"])
        self.run_with([*right_click(6, 3), *left_click(18, 50)])
        self.assertEqual(self.done, ["first"])

    def test_drawn(self) -> None:
        """Items in the menu bar's colours, greyed where they cannot be
        chosen, ► for a submenu, ─ for a separator."""
        popup = MenuPopup(self.label.popup_menu(Shortcuts()) or Menu("", []))
        popup.move_to(0, 0)
        canvas = Canvas(30, 8)
        popup.paint(canvas, active=True)
        self.assertEqual(canvas.text(1)[1:12], " First     ")
        self.assertEqual(canvas.text(2)[1:4], "───")
        self.assertEqual(canvas.cell(3, 2)[1], MenuBar.disabled_style)
        self.assertIn("►", canvas.text(4))
        self.assertEqual(popup.status, "First")
        popup.status = "ignored"
        self.assertEqual(popup.status, "First")

    def test_not_running(self) -> None:
        """With no running manager, nothing pops up."""
        manager = PresentationManager()
        manager.context_menu(Menu("M", [MenuItem("x", lambda: None)]), 0, 0)
        window = Window("W", Rect(0, 0, 5, 20))
        self.assertFalse(window.handle_key("shift+f10", Shortcuts()))


class DefaultMenuTests(unittest.TestCase):
    """The menus text boxes and text areas have of their own."""

    def labels(self, menu: Menu | None) -> list[str]:
        """A menu's labels, without separators."""
        assert menu is not None
        return [item.label for item in menu.items if item.label]

    def test_password_box_copies_nothing_out(self) -> None:
        """No Cut or Copy in a password box's menu."""
        box = PasswordBox(0, 0, 10)
        self.assertEqual(
            self.labels(box.popup_menu(Shortcuts())), ["&Undo", "&Paste", "Select &all"]
        )

    def test_text_area(self) -> None:
        """A text area's menu, its items greyed out while they would do
        nothing; Undo once there is something to undo."""
        area = TextArea(0, 0, text="abc")
        area.clipboard = Clipboard()
        menu = area.popup_menu(Shortcuts())
        assert menu is not None
        items = {item.label: item for item in menu.items}
        self.assertFalse(items["&Undo"].is_available or items["&Copy"].is_available)
        self.assertEqual(items["&Undo"].shortcut, "Ctrl+Z")
        area.insert("x")
        area.select_all()
        self.assertTrue(items["&Undo"].is_available and items["Cu&t"].is_available)

    def test_one_given_wins(self) -> None:
        """A menu given to a text box is used instead."""
        box = TextBox(0, 0, 10)
        box.context_menu = Menu("Mine", [MenuItem("&Mine", lambda: None)])
        self.assertIs(box.popup_menu(Shortcuts()), box.context_menu)
        area = TextArea(0, 0)
        area.context_menu = box.context_menu
        self.assertIs(area.popup_menu(Shortcuts()), box.context_menu)


class UnderAPopupTests(unittest.TestCase):
    """The window a context menu comes from still looks active under it, so
    the text it would cut or copy stays selected on screen."""

    def setUp(self) -> None:
        self.window = Window("W", Rect(1, 0, 8, 30))
        self.area = self.window.add(TextArea(0, 0, text="hello world"))
        self.area.select((0, 0), (0, 5))  # "hello"
        self.manager = PresentationManager(windows=[self.window])
        self.manager.handle_resize(40, 12)

    def screen(self) -> Canvas:
        """The desktop as drawn now."""
        canvas = Canvas(40, 12)
        self.manager.compose(canvas)
        return canvas

    def test_the_selection_stays_while_the_menu_is_up(self) -> None:
        """Under a context menu: still selected, still a double frame, and
        no cursor (that is the menu's)."""
        popup = MenuPopup(self.area.popup_menu(Shortcuts()) or Menu("", []))
        popup.move_to(4, 10)
        self.manager.add(popup)
        canvas = self.screen()
        selected = [canvas.cell(2, column)[1] for column in range(1, 6)]
        self.assertEqual(selected, [TextArea.selected_style] * 5)
        self.assertEqual(canvas.cell(1, 0)[0], "╔")
        self.assertIsNone(canvas.cursor)
        self.assertTrue(self.manager.looks_active(self.window))

    def test_a_dialog_still_makes_it_inactive(self) -> None:
        """An ordinary dialog in front is another matter: the window behind
        it looks inactive, its selection hidden."""
        dialog = Dialog("Question", 20, 5)
        dialog.move_to(5, 15)  # clear of the window's corner and its text
        self.manager.add(dialog)
        canvas = self.screen()
        self.assertNotEqual(canvas.cell(2, 1)[1], TextArea.selected_style)
        self.assertEqual(canvas.cell(1, 0)[0], "┌")
        self.assertFalse(self.manager.looks_active(self.window))

    def test_only_the_window_right_behind_the_popups(self) -> None:
        """Popups in front of popups (a submenu) still leave the window they
        came from looking active, and only that one."""
        back = Window("Back", Rect(2, 2, 5, 10))
        self.manager.add(back)
        self.manager.bring_to_front(self.window)
        for _ in range(2):
            self.manager.add(MenuPopup(Menu("M", [MenuItem("x", lambda: None)])))
        self.assertTrue(self.manager.looks_active(self.window))
        self.assertFalse(self.manager.looks_active(back))

    def test_hosted(self) -> None:
        """An application in a process of its own draws its window as
        active under its own popup, going by the window the desktop says is
        active; not when the desktop says another application's is."""
        _, app_end = pipe()
        manager = ClientManager(app_end, WELCOME)
        self.addCleanup(manager.stop_listening)
        window = manager.launch(Hello).windows[0]
        popup = MenuPopup(Menu("M", [MenuItem("x", lambda: None)]))
        manager.add(popup)
        manager.handle({"type": "active", "id": manager.window_id(popup)})
        self.assertTrue(manager.looks_active(window))
        manager.handle({"type": "active", "id": None})  # another application's
        self.assertFalse(manager.looks_active(window))


class HostedTests(unittest.TestCase):
    """A context menu in an application run by a desktop, over a pipe."""

    def test_right_click_in_a_hosted_window(self) -> None:
        """The application pops the menu up itself (a popup window the
        desktop is told of), and its keys, sent to the window, reach it."""
        desktop, app_end = pipe()
        manager = ClientManager(app_end, WELCOME)
        self.addCleanup(manager.stop_listening)
        app = manager.launch(Hello)
        window = app.windows[0]
        box = window.widget("text")
        assert isinstance(box, TextBox)
        box.text = "hosted"
        manager.flush()
        drain(desktop)
        number = manager.window_id(window)
        at = window.screen_rect(box)
        click = MouseEvent("press", "right", at.row, at.column + 2)
        send(desktop, "mouse", id=number, event=encode_mouse(click))
        send(desktop, "key", id=number, key="a")  # Select all, in the menu
        manager.pump()
        self.assertEqual(box.selection, (0, 6))
        looks = [m.get("look") for m in drain(desktop) if m["type"] == "window"]
        self.assertIn("popup", looks)


if __name__ == "__main__":
    unittest.main()
