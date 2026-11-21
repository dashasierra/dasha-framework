"""Tests for submenus: menus opened from menu items."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.menu import SUBMENU_MARK, Menu, MenuBar, MenuItem
from dasha.window import Window


class SubmenuTests(unittest.TestCase):
    """File > Recent > Older, with letters that overlap on purpose."""

    def setUp(self) -> None:
        self.chosen: list[str] = []
        say = self.chosen.append
        self.older = Menu(
            "Older",
            [
                MenuItem("&Ancient", lambda: say("ancient")),
                MenuItem("&Dusty", lambda: say("dusty"), "Ctrl+D"),
            ],
        )
        self.recent = Menu(
            "Recent",
            [
                MenuItem("&Draft", lambda: say("draft")),
                MenuItem("&Older", submenu=self.older, status="Older files"),
                MenuItem("&Notes", lambda: say("notes")),
            ],
        )
        self.file = Menu(
            "&File",
            [
                MenuItem("&New", lambda: say("new")),
                MenuItem("&Recent", submenu=self.recent),
                MenuItem("&Delete", lambda: say("delete")),
            ],
        )
        self.help = Menu("&Help", [MenuItem("&About", lambda: say("about"))])
        self.menu_bar = MenuBar()
        self.menu_bar.set_menus([self.file, self.help])
        self.menu_bar.lines = 24

    def keys(self, *names: str) -> None:
        """Press keys at the menu bar.

        :param names: The keys.
        """
        for name in names:
            self.menu_bar.handle_key(name)

    # Opening and closing

    def test_item_with_a_submenu_is_enabled_and_marked(self) -> None:
        """An item with a submenu can be chosen, and shows ►."""
        item = self.file.items[1]
        self.assertTrue(item.is_available)
        self.menu_bar.open(0)
        canvas = Canvas(60, 24)
        self.menu_bar.paint(canvas)
        self.assertIn(SUBMENU_MARK, canvas.text(3))

    def test_right_enter_left_and_escape(self) -> None:
        """Right, Enter, Left and Escape."""
        self.keys("f10", "down", "right")
        self.assertEqual(self.menu_bar.open_menus, [self.file, self.recent])
        self.keys("down", "enter")
        self.assertEqual(self.menu_bar.open_menus, [self.file, self.recent, self.older])
        self.keys("left")
        self.assertEqual(self.menu_bar.open_menus, [self.file, self.recent])
        self.keys("escape")
        self.assertEqual(self.menu_bar.open_menus, [self.file])
        self.keys("right", "f10")
        self.assertFalse(self.menu_bar.is_open)
        self.keys("f10", "escape")
        self.assertFalse(self.menu_bar.is_open)

    def test_right_on_a_plain_item_goes_to_the_next_menu(self) -> None:
        """Right on a plain item goes to the next menu."""
        self.keys("f10", "down", "right")  # Recent open, Draft highlighted
        self.keys("right")
        self.assertIs(self.menu_bar.open_menu, self.help)
        self.assertEqual(len(self.menu_bar.open_menus), 1)

    def test_choosing_in_a_submenu(self) -> None:
        """Choosing in a submenu."""
        self.keys("f10", "down", "right", "enter")
        self.assertEqual(self.chosen, ["draft"])
        self.assertFalse(self.menu_bar.is_open)

    def test_status_is_the_innermost_item(self) -> None:
        """The highlighted item is the one in the innermost open menu."""
        self.keys("f10", "down", "right", "down")
        self.assertEqual(self.menu_bar.highlighted, self.recent.items[1])

    # Letters, innermost first

    def test_innermost_open_menu_wins(self) -> None:
        """The innermost open menu wins."""
        self.keys("f10", "r", "o", "d")
        self.assertEqual(self.chosen, ["dusty"])

    def test_then_the_menu_out_from_it(self) -> None:
        """With Recent open, D is Draft; with only File open, Delete."""
        self.keys("f10", "r", "d")
        self.keys("f10", "d")
        self.assertEqual(self.chosen, ["draft", "delete"])

    def test_letters_from_further_out(self) -> None:
        """Letters from further out."""
        self.keys("f10", "r", "o", "n")
        self.keys("f10", "r", "o")
        self.keys("e")  # in no menu: ignored, everything stays open
        self.assertEqual(len(self.menu_bar.open_menus), 3)
        self.keys("h")
        self.assertIs(self.menu_bar.open_menu, self.help)
        self.assertEqual(self.chosen, ["notes"])

    def test_closed_submenus_do_not_count(self) -> None:
        """A letter only in a submenu that is not showing does nothing."""
        self.keys("f10", "a")  # Ancient is in Older, which is not open
        self.assertEqual(self.chosen, [])
        self.assertEqual(self.menu_bar.open_menus, [self.file])

    def test_shortcut_hints_reach_submenus(self) -> None:
        """An item's shortcut works from a submenu too, open or closed."""
        self.assertTrue(self.menu_bar.handle_key("ctrl+d"))
        self.keys("f10", "ctrl+d")
        self.assertEqual(self.chosen, ["dusty", "dusty"])
        self.assertFalse(self.menu_bar.is_open)

    def test_a_menu_inside_itself_is_safe(self) -> None:
        """A submenu that contains its own parent does not loop forever."""
        self.older.items.append(MenuItem("&Back", submenu=self.recent))
        self.assertIsNone(self.menu_bar.item_for_shortcut("ctrl+q"))

    def test_greyed_out_submenu_stays_shut(self) -> None:
        """A greyed-out submenu stays shut."""
        self.file.items[1].enabled = lambda: False  # Recent
        self.assertIsNone(self.menu_bar.item_for_shortcut("ctrl+d"))
        self.keys("f10", "r")
        self.assertEqual(self.menu_bar.open_menus, [self.file])
        self.keys("right")  # nothing to open here: on to the next menu, as ever
        self.assertNotIn(self.recent, self.menu_bar.open_menus)
        self.assertEqual(self.chosen, [])

    def test_shortcut_key_while_its_item_runs(self) -> None:
        """Chosen by its shortcut, an item can see which key: only then."""
        seen: list[object] = []
        self.older.items[1].action = lambda: seen.append(self.menu_bar.shortcut_key)
        self.menu_bar.handle_key("ctrl+d")
        self.keys("f10", "r", "o", "d")  # by letters: no key to pass on
        self.assertEqual(seen, ["ctrl+d", None])
        self.assertIsNone(self.menu_bar.shortcut_key)

    # Placement

    def test_beside_its_item(self) -> None:
        """Beside its item."""
        self.keys("f10", "r", "o")
        drop, recent, older = self.menu_bar.level_rects(80, 24)
        self.assertEqual(recent.row + 1, drop.row + 1 + 1)  # level with Recent
        self.assertEqual(older.row + 1, recent.row + 1 + 1)  # level with Older
        self.assertGreater(recent.column, drop.column)
        self.assertGreater(older.column, recent.column)

    def test_to_the_left_when_there_is_no_room(self) -> None:
        """To the left without room."""
        self.menu_bar.set_menus([self.help, self.file])  # File further along
        self.menu_bar.open(1)
        self.keys("r", "o")
        _, recent, older = self.menu_bar.level_rects(50, 24)
        self.assertLess(older.column, recent.column)
        self.assertEqual(older.right, recent.column + self.menu_bar.frame_padding)

    def test_kept_on_the_screen(self) -> None:
        """Kept on the screen."""
        self.keys("f10", "r", "o")
        for rect in self.menu_bar.level_rects(22, 24):
            self.assertGreaterEqual(rect.column, 0)
            self.assertLessEqual(rect.right, 22)
        rects = self.menu_bar.level_rects(80, 6)
        self.assertLessEqual(rects[-1].bottom, 6)
        self.assertGreaterEqual(rects[-1].row, 1)

    # The mouse

    def move(self, row: int, column: int) -> None:
        """A mouse move with no button.

        :param row: Screen row.
        :param column: Screen column.
        """
        self.menu_bar.handle_mouse(MouseEvent("move", "none", row, column), 80)

    def click(self, row: int, column: int, action: str = "press") -> None:
        """A left-button event.

        :param row: Screen row.
        :param column: Screen column.
        :param action: Mouse action.
        """
        self.menu_bar.handle_mouse(MouseEvent(action, "left", row, column), 80)

    def test_hover_opens_and_closes_submenus(self) -> None:
        """Hovering opens and closes submenus."""
        self.menu_bar.open(0)
        drop = self.menu_bar.level_rects(80)[0]
        self.move(drop.row + 2, drop.column + 4)  # Recent
        self.assertEqual(self.menu_bar.open_menus, [self.file, self.recent])
        self.move(drop.row + 3, drop.column + 4)  # Delete
        self.assertEqual(self.menu_bar.open_menus, [self.file])

    def test_click_in_a_submenu(self) -> None:
        """Clicks in a submenu."""
        self.menu_bar.open(0)
        drop = self.menu_bar.level_rects(80)[0]
        self.click(drop.row + 2, drop.column + 4)  # Recent: opens
        recent = self.menu_bar.level_rects(80)[1]
        self.click(recent.row + 3, recent.column + 4)  # Notes
        self.assertEqual(self.chosen, ["notes"])
        self.menu_bar.open(0)
        self.click(20, 70)
        self.assertFalse(self.menu_bar.is_open)

    def test_release_after_dragging_chooses(self) -> None:
        """Press on the title, drag into a submenu, release on an item."""
        self.click(0, 2)
        drop = self.menu_bar.level_rects(80)[0]
        self.menu_bar.handle_mouse(
            MouseEvent("drag", "left", drop.row + 2, drop.column + 4), 80
        )
        recent = self.menu_bar.level_rects(80)[1]
        row, column = recent.row + 1, recent.column + 4  # Draft
        self.menu_bar.handle_mouse(MouseEvent("drag", "left", row, column), 80)
        self.click(row, column, "release")
        self.assertEqual(self.chosen, ["draft"])

    # Shadows

    def test_submenu_shadow_stays_off_the_status_bar(self) -> None:
        """Submenu shadows stay off the status bar."""
        window = Window("W", Rect(2, 0, 5, 30), menus=[self.file])
        manager = PresentationManager(windows=[window])
        manager.handle_resize(60, 9)
        manager.handle_event("alt+f")
        manager.handle_event("r")
        manager.handle_event("o")
        canvas = Canvas(60, 9)
        manager.compose(canvas)
        status_styles = {canvas.cell(8, column)[1] for column in range(60)}
        self.assertNotIn(manager.menu_bar.shadow_style, status_styles)


if __name__ == "__main__":
    unittest.main()
