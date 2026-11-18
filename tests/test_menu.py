"""Tests for menus and the menu bar."""

import unittest

from dasha.border import SINGLE
from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.menu import (
    SEPARATOR_LEFT,
    DuplicateMnemonicError,
    Menu,
    MenuBar,
    MenuItem,
    mnemonic_key,
    separator,
    split_mnemonic,
    unique_mnemonics,
)
from dasha.window import Window
from tests.hosted_apps import Hello, Helpful


class MnemonicTests(unittest.TestCase):
    """The ``&`` marker in labels."""

    def test_split(self) -> None:
        """The marker is removed and its position reported."""
        self.assertEqual(split_mnemonic("&File"), ("File", 0))
        self.assertEqual(split_mnemonic("E&xit"), ("Exit", 1))
        self.assertEqual(split_mnemonic("Plain"), ("Plain", None))
        self.assertEqual(split_mnemonic("Save && &Quit"), ("Save & Quit", 7))

    def test_key(self) -> None:
        """The mnemonic letter is lower-cased."""
        self.assertEqual(mnemonic_key("E&Xit"), "x")
        self.assertIsNone(mnemonic_key("Exit"))


class DuplicateMnemonicTests(unittest.TestCase):
    """Two items, or two menu titles, marking the same letter: the first
    keeps it, and the others are treated as having none."""

    def setUp(self) -> None:
        self.chosen: list[str] = []
        self.themes = Menu(
            "&Themes",
            [
                MenuItem("&Default", lambda: self.chosen.append("default")),
                MenuItem("&Dark", lambda: self.chosen.append("dark")),
                separator(),
                MenuItem("&Monochrome", lambda: self.chosen.append("mono")),
            ],
        )
        self.menu_bar = MenuBar()
        self.menu_bar.set_menus([self.themes])

    def test_first_label_keeps_the_letter(self) -> None:
        """In either case; labels without one, and separators, stay without."""
        self.assertEqual(
            unique_mnemonics(["&Default", "&dark", "", "Plain", "&Monochrome"]),
            [0, None, None, None, 0],
        )
        self.assertEqual(self.themes.mnemonics(), ["d", None, None, "m"])

    def test_strict(self) -> None:
        """Strictly, a repeated letter is an error naming both labels."""
        with self.assertRaisesRegex(DuplicateMnemonicError, "'&Dark'.*'&Default'"):
            unique_mnemonics(["&Default", "&Dark"], strict=True)
        self.assertIsInstance(DuplicateMnemonicError(), ValueError)
        self.assertEqual(unique_mnemonics(["&A", "&B"], strict=True), [0, 0])

    def test_check_mnemonics(self) -> None:
        """A menu checks its own items and, separately, its submenus'."""
        with self.assertRaises(DuplicateMnemonicError):
            self.themes.check_mnemonics()
        submenu = Menu("Sub", [MenuItem("&One", print), MenuItem("&Other", print)])
        menu = Menu("&Menu", [MenuItem("&Open", submenu=submenu)])
        with self.assertRaises(DuplicateMnemonicError):
            menu.check_mnemonics()
        submenu.items[1].label = "O&ther"
        menu.check_mnemonics()  # O in the menu and in its submenu is fine
        submenu.items.append(MenuItem("&Back", submenu=menu))
        menu.check_mnemonics()  # a menu that is its own submenu, somewhere

    def test_the_letter_chooses_the_first(self) -> None:
        """D chooses Default, never Dark."""
        self.menu_bar.open(0)
        self.menu_bar.handle_key("d")
        self.assertEqual(self.chosen, ["default"])

    def test_a_disabled_first_does_not_pass_it_on(self) -> None:
        """With the first greyed out, the letter does nothing, rather than
        choosing the later item whose letter is not shown."""
        self.themes.items[0].action = None
        self.menu_bar.open(0)
        self.menu_bar.handle_key("d")
        self.assertEqual(self.chosen, [])
        self.assertTrue(self.menu_bar.is_open)

    def test_only_the_first_letter_is_highlighted(self) -> None:
        """D is lit in Default, and not in Dark."""
        canvas = Canvas(30, 8)
        self.menu_bar.open(0)
        self.menu_bar.handle_key("down")  # Dark highlighted, Default not
        self.menu_bar.paint(canvas)
        self.assertEqual(canvas.cell(2, 3), ("D", self.menu_bar.mnemonic_style))
        self.assertEqual(canvas.cell(3, 3), ("D", self.menu_bar.selected_style))
        self.assertEqual(canvas.cell(5, 3), ("M", self.menu_bar.mnemonic_style))

    def test_check_the_bar(self) -> None:
        """The bar checks its titles, and each menu's items, filled in by
        ``on_open`` first."""
        self.menu_bar.set_menus([Menu("&File"), Menu("&Format")])
        with self.assertRaisesRegex(DuplicateMnemonicError, "&Format"):
            self.menu_bar.check_mnemonics()

        def fill(menu: Menu) -> None:
            menu.items = [MenuItem("&Default", print), MenuItem("&Dark", print)]

        self.menu_bar.set_menus([Menu("&Themes", on_open=fill)])
        with self.assertRaisesRegex(DuplicateMnemonicError, "&Dark"):
            self.menu_bar.check_mnemonics()

    def test_menu_titles(self) -> None:
        """On the bar too: Alt+F opens the first F menu, and only its F is
        lit, even with that menu inert."""
        file, form = Menu("&File", [MenuItem("&New", print)]), Menu("&Format")
        self.menu_bar.set_menus([file, form])
        self.menu_bar.handle_key("alt+f")
        self.assertIs(self.menu_bar.open_menu, file)
        canvas = Canvas(30, 8)
        self.menu_bar.paint(canvas)
        self.assertEqual(canvas.cell(0, 8), ("F", self.menu_bar.bar_style))
        self.menu_bar.handle_key("escape")
        self.menu_bar.set_menus([file, form], inert=[0])
        self.assertFalse(self.menu_bar.handle_key("alt+f"))
        self.assertFalse(self.menu_bar.is_open)


class BuiltInMenusTests(unittest.TestCase):
    """Dasha Framework's own menus never repeat a letter."""

    def test_the_desktops_menus(self) -> None:
        """The system menu (with Themes, and running applications listed),
        an application's Window menu, and the bar with a window of no
        application's in front."""
        manager = PresentationManager()
        manager.handle_resize(80, 24)
        manager.launch(Hello)
        manager.launch(Helpful)
        bar = MenuBar()
        bar.set_menus(manager.bar_menus())
        self.assertIn("&Window", [menu.title for menu in bar.menus])
        bar.check_mnemonics()
        lone = PresentationManager()
        lone.handle_resize(80, 24)
        lone.add(Window("Lone", Rect(2, 2, 6, 20)))
        bar.set_menus(lone.bar_menus())
        bar.check_mnemonics()


class MenuBarTests(unittest.TestCase):
    """Keyboard and mouse handling, and drawing."""

    def setUp(self) -> None:
        self.chosen: list[str] = []
        self.file = Menu(
            "&File",
            [
                MenuItem("&New", lambda: self.chosen.append("new"), "Ctrl+N"),
                MenuItem("&Open", None, "F3"),
                separator(),
                MenuItem("E&xit", lambda: self.chosen.append("exit")),
            ],
        )
        self.help = Menu(
            "&Help", [MenuItem("&About", lambda: self.chosen.append("about"))]
        )
        self.menu_bar = MenuBar()
        self.menu_bar.set_menus([self.file, self.help])

    def test_closed_bar_ignores_ordinary_keys(self) -> None:
        """Keys the bar does not own pass through while it is closed."""
        self.assertFalse(self.menu_bar.handle_key("tab"))
        self.assertFalse(self.menu_bar.handle_key("alt+q"))
        self.assertFalse(self.menu_bar.is_open)

    def test_alt_mnemonic_and_f10_open_menus(self) -> None:
        """Alt+letter opens that menu; F10 opens the first."""
        self.assertTrue(self.menu_bar.handle_key("alt+h"))
        self.assertIs(self.menu_bar.open_menu, self.help)
        self.menu_bar.handle_key("f10")
        self.assertFalse(self.menu_bar.is_open)
        self.menu_bar.handle_key("f10")
        self.assertIs(self.menu_bar.open_menu, self.file)

    def test_arrows_move_and_skip_separators(self) -> None:
        """Up and down wrap, skipping separators and disabled items; left and
        right switch menus."""
        self.menu_bar.open(0)
        self.assertEqual(self.menu_bar.highlighted, self.file.items[0])
        self.menu_bar.handle_key("down")  # past disabled Open and the separator
        self.assertEqual(self.menu_bar.highlighted, self.file.items[3])
        self.menu_bar.handle_key("down")
        self.assertEqual(self.menu_bar.highlighted, self.file.items[0])
        self.menu_bar.handle_key("up")
        self.assertEqual(self.menu_bar.highlighted, self.file.items[3])
        self.menu_bar.handle_key("right")
        self.assertIs(self.menu_bar.open_menu, self.help)
        self.menu_bar.handle_key("right")
        self.assertIs(self.menu_bar.open_menu, self.file)
        self.menu_bar.handle_key("left")
        self.assertIs(self.menu_bar.open_menu, self.help)

    def test_enter_and_mnemonic_choose_items(self) -> None:
        """Enter chooses the highlighted item; a letter chooses by mnemonic."""
        self.menu_bar.open(0)
        self.menu_bar.handle_key("enter")
        self.assertEqual(self.chosen, ["new"])
        self.assertFalse(self.menu_bar.is_open)
        self.menu_bar.open(0)
        self.menu_bar.handle_key("X")
        self.assertEqual(self.chosen, ["new", "exit"])

    def test_letter_opens_another_menu(self) -> None:
        """In an open menu, a letter no item here uses opens the menu on the
        bar with that mnemonic; the open menu's own letter does nothing."""
        self.menu_bar.open(0)
        self.assertTrue(self.menu_bar.handle_key("h"))
        self.assertIs(self.menu_bar.open_menu, self.help)
        self.menu_bar.handle_key("H")
        self.assertIs(self.menu_bar.open_menu, self.help)
        self.menu_bar.handle_key("F")
        self.assertIs(self.menu_bar.open_menu, self.file)
        self.assertEqual(self.chosen, [])

    def test_item_letter_beats_menu_letter_only_when_enabled(self) -> None:
        """An enabled item with the letter is chosen rather than opening the
        menu with it; a disabled one does not claim the letter."""
        window = Menu("&Window", [MenuItem("&Tile", print)])
        file = Menu(
            "&File",
            [
                MenuItem("&Write", lambda: self.chosen.append("write")),
                MenuItem("&Help topics"),  # disabled
            ],
        )
        self.menu_bar.set_menus([file, window, self.help])
        self.menu_bar.open(0)
        self.menu_bar.handle_key("w")
        self.assertEqual(self.chosen, ["write"])
        self.assertFalse(self.menu_bar.is_open)
        self.menu_bar.open(0)
        self.menu_bar.handle_key("h")
        self.assertIs(self.menu_bar.open_menu, self.help)
        self.assertEqual(self.chosen, ["write"])

    def test_disabled_items_cannot_be_chosen(self) -> None:
        """An item without an action ignores its letter and a click."""
        self.menu_bar.open(0)
        self.menu_bar.handle_key("o")
        self.click(3, 4)
        self.assertEqual(self.chosen, [])
        self.assertTrue(self.menu_bar.is_open)

    def test_disabled_items_are_never_highlighted(self) -> None:
        """Hovering over a disabled item leaves the highlight where it was."""
        self.menu_bar.open(0)
        self.menu_bar.handle_key("down")  # Exit
        self.menu_bar.handle_mouse(MouseEvent("move", "none", 3, 4), 40)  # Open
        self.assertEqual(self.menu_bar.highlighted, self.file.items[3])
        canvas = Canvas(40, 8)
        self.menu_bar.paint(canvas)
        self.assertEqual(canvas.cell(3, 3), ("O", self.menu_bar.disabled_style))
        self.assertEqual(canvas.cell(5, 3)[1], self.menu_bar.selected_style)

    def test_menu_with_nothing_enabled(self) -> None:
        """A menu of disabled items opens with nothing highlighted, all of it
        greyed out, shortcuts included; keys and the mouse change nothing."""
        dead = Menu(
            "&Edit",
            [MenuItem("&Cut", None, "Ctrl+X"), separator(), MenuItem("&Paste")],
        )
        self.menu_bar.set_menus([self.file, dead])
        self.menu_bar.open(1)
        self.assertIsNone(self.menu_bar.highlighted)
        for key in ("down", "up", "enter", "c"):
            self.menu_bar.handle_key(key)
        rect = self.menu_bar.dropdown_rect(40)
        assert rect is not None
        self.menu_bar.handle_mouse(
            MouseEvent("move", "none", rect.row + 1, rect.column + 3), 40
        )
        self.assertIsNone(self.menu_bar.highlighted)
        self.assertTrue(self.menu_bar.is_open)
        canvas = Canvas(40, 8)
        self.menu_bar.paint(canvas)
        inside = rect.column + self.menu_bar.frame_padding + 1
        for row in (rect.row + 1, rect.row + 3):
            for column in range(inside, inside + rect.width - 4):
                self.assertEqual(
                    canvas.cell(row, column)[1], self.menu_bar.disabled_style
                )
        self.assertIn("Ctrl+X", canvas.text(rect.row + 1))

    def test_open_menu_swallows_other_keys(self) -> None:
        """While open, unrelated keys are consumed; Escape closes."""
        self.menu_bar.open(0)
        self.assertTrue(self.menu_bar.handle_key("tab"))
        self.assertTrue(self.menu_bar.is_open)
        self.assertTrue(self.menu_bar.handle_key("escape"))
        self.assertFalse(self.menu_bar.is_open)

    def test_paint_bar_and_dropdown(self) -> None:
        """Titles on row 0; a framed drop-down with shortcuts and a separator."""
        canvas = Canvas(40, 8)
        self.menu_bar.open(0)
        self.menu_bar.paint(canvas)
        self.assertEqual(canvas.text(0).rstrip(), "  File  Help")
        self.assertEqual(
            canvas.cell(0, 2), ("F", self.menu_bar.selected_mnemonic_style)
        )
        self.assertEqual(canvas.cell(0, 8), ("H", self.menu_bar.mnemonic_style))
        rect = self.menu_bar.dropdown_rect(40)
        assert rect is not None
        self.assertEqual((rect.row, rect.column, rect.height), (1, 0, 6))
        # A blank column each side of the frame.
        self.assertEqual(canvas.text(1)[:2], " " + SINGLE.top_left)
        self.assertEqual(
            canvas.text(2)[: rect.width],
            " " + SINGLE.vertical + " New   Ctrl+N " + SINGLE.vertical + " ",
        )
        self.assertEqual(canvas.cell(2, 0)[1], self.menu_bar.bar_style)  # padding
        self.assertEqual(canvas.cell(2, 2)[1], self.menu_bar.selected_style)
        self.assertEqual(canvas.cell(3, 3), ("O", self.menu_bar.disabled_style))
        self.assertEqual(canvas.cell(4, 1)[0], SEPARATOR_LEFT)
        self.assertEqual(
            canvas.text(rect.bottom - 1)[rect.width - 2 : rect.width],
            SINGLE.bottom_right + " ",
        )

    def test_dropdown_stays_on_screen(self) -> None:
        """A drop-down near the right edge is shifted left to fit."""
        self.menu_bar.open(1)
        rect = self.menu_bar.dropdown_rect(12)
        assert rect is not None
        self.assertEqual(rect.right, 12)

    def click(self, row: int, column: int) -> bool:
        """Left-click at a position on a 40-column screen."""
        return self.menu_bar.handle_mouse(MouseEvent("press", "left", row, column), 40)

    def test_mouse_opens_toggles_and_chooses(self) -> None:
        """Click a title to open or close it; click an item to choose it."""
        click = self.click
        self.assertTrue(click(0, 8))
        self.assertIs(self.menu_bar.open_menu, self.help)
        click(0, 8)
        self.assertFalse(self.menu_bar.is_open)
        click(0, 3)
        self.assertIs(self.menu_bar.open_menu, self.file)
        click(3, 4)  # disabled "Open": nothing happens
        self.assertTrue(self.menu_bar.is_open)
        click(5, 4)  # "Exit"
        self.assertEqual(self.chosen, ["exit"])
        self.assertFalse(self.menu_bar.is_open)

    def test_mouse_outside_closes(self) -> None:
        """Clicking away from an open menu closes it; closed, it is ignored."""
        self.menu_bar.open(0)
        self.assertTrue(
            self.menu_bar.handle_mouse(MouseEvent("press", "left", 7, 30), 40)
        )
        self.assertFalse(self.menu_bar.is_open)
        self.assertFalse(
            self.menu_bar.handle_mouse(MouseEvent("press", "left", 7, 30), 40)
        )

    def test_shortcut_hint_chooses_item_when_closed(self) -> None:
        """The key a hint shows chooses its item with every menu closed;
        a disabled item's key passes on."""
        self.assertTrue(self.menu_bar.handle_key("ctrl+n"))
        self.assertEqual(self.chosen, ["new"])
        self.assertFalse(self.menu_bar.handle_key("f3"))  # Open is disabled
        self.assertFalse(self.menu_bar.handle_key("ctrl+m"))

    def test_shortcut_hint_chooses_item_when_open(self) -> None:
        """With a menu open, even another one, the hinted key still works,
        and closes the menu."""
        self.menu_bar.open(1)  # Help
        self.assertTrue(self.menu_bar.handle_key("ctrl+n"))
        self.assertEqual(self.chosen, ["new"])
        self.assertFalse(self.menu_bar.is_open)

    def test_plain_character_hints_do_nothing(self) -> None:
        """A hint of a single character would steal typing, so it is ignored."""
        self.file.items.append(MenuItem("&Quit", lambda: self.chosen.append("q"), "Q"))
        self.assertFalse(self.menu_bar.handle_key("q"))
        self.assertFalse(self.menu_bar.handle_key("Q"))
        self.assertEqual(self.chosen, [])

    def test_alt_f3_closes_window_with_menu_open(self) -> None:
        """The reported bug: Window > Close shows Alt+F3, and Alt+F3 works
        with that menu showing."""
        window = Window("W", Rect(2, 2, 5, 20), closable=True)
        manager = PresentationManager(windows=[window])
        window.menus = [
            Menu(
                "&Window",
                [MenuItem("&Close", lambda: manager.close(window), "Alt+F3")],
            )
        ]
        manager.handle_resize(40, 12)
        manager.handle_event("alt+w")
        self.assertTrue(manager.menu_bar.is_open)
        manager.handle_event("alt+f3")
        self.assertEqual(manager.windows, ())
        self.assertFalse(manager.menu_bar.is_open)

    def test_changing_menus_closes_open_menu(self) -> None:
        """A different list of menus closes the open one; the same list does not."""
        self.menu_bar.open(1)
        self.menu_bar.set_menus([self.file, self.help])
        self.assertTrue(self.menu_bar.is_open)
        self.menu_bar.set_menus([self.file])
        self.assertFalse(self.menu_bar.is_open)


if __name__ == "__main__":
    unittest.main()
