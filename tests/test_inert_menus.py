"""Tests for inert menus."""

import unittest
from typing import cast

from dasha.canvas import Canvas, Rect
from dasha.dialog import Dialog, confirm
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuBar, MenuItem
from dasha.terminal import Terminal
from dasha.window import Window
from tests.support import without_styles
from tests.test_application import Notes, Scripted
from tests.test_manager import FakeTerminal

BURGER = PresentationManager.system_menu_title


class MenuBarTests(unittest.TestCase):
    """Inert menus show, but do not open, by any way in."""

    def setUp(self) -> None:
        self.chosen: list[str] = []
        say = self.chosen.append
        self.menu_bar = MenuBar()
        self.first = Menu(
            title="&Apps", items=[MenuItem(label="&Go", action=lambda: say("go"))]
        )
        self.second = Menu(
            title="&File",
            items=[MenuItem(label="&Save", action=lambda: say("save"), shortcut="F2")],
        )
        self.third = Menu(
            title="&Edit", items=[MenuItem(label="&Cut", action=lambda: say("cut"))]
        )
        self.menu_bar.set_menus(
            menus=[self.first, self.second, self.third], inert=[1, 2]
        )

    def test_keys_do_not_open_them(self) -> None:
        """Keys do not open inert menus."""
        self.assertFalse(self.menu_bar.handle_key(key="alt+f"))
        self.assertFalse(self.menu_bar.handle_key(key="f2"))
        self.assertEqual(self.chosen, [])
        self.menu_bar.handle_key(key="f10")
        self.assertIs(self.menu_bar.open_menu, self.first)
        self.menu_bar.handle_key(key="right")
        self.assertIs(self.menu_bar.open_menu, self.first)  # round, past both
        self.menu_bar.handle_key(key="left")
        self.assertIs(self.menu_bar.open_menu, self.first)
        self.menu_bar.handle_key(key="e")  # Edit's letter, with a menu open
        self.assertIs(self.menu_bar.open_menu, self.first)

    def test_right_and_left_keep_the_highlight(self) -> None:
        """Right and Left keep the highlight."""
        say = self.chosen.append
        self.first.items.append(MenuItem(label="&Stop", action=lambda: say("stop")))
        self.menu_bar.handle_key(key="f10")
        self.menu_bar.handle_key(key="down")
        self.menu_bar.handle_key(key="right")
        self.assertIs(self.menu_bar.highlighted, self.first.items[1])
        self.menu_bar.handle_key(key="left")
        self.assertIs(self.menu_bar.highlighted, self.first.items[1])

    def test_clicks_do_not_open_them(self) -> None:
        """A click on an inert title, or moving over one, opens nothing."""
        file_title = self.menu_bar.title_spans[1]
        click = MouseEvent(
            action="press", button="left", row=0, column=file_title.column
        )
        self.assertTrue(self.menu_bar.handle_mouse(event=click, columns=80))
        self.assertFalse(self.menu_bar.is_open)
        self.menu_bar.handle_key(key="f10")
        move = MouseEvent(action="move", button="none", row=0, column=file_title.column)
        self.menu_bar.handle_mouse(event=move, columns=80)
        self.assertIs(self.menu_bar.open_menu, self.first)

    def test_an_open_menu_turning_inert_closes(self) -> None:
        """One that is open when it turns inert closes."""
        self.menu_bar.set_menus(menus=[self.first, self.second, self.third])
        self.menu_bar.handle_key(key="alt+f")
        self.assertIs(self.menu_bar.open_menu, self.second)
        self.menu_bar.set_menus(menus=[self.first, self.second, self.third], inert=[1])
        self.assertFalse(self.menu_bar.is_open)

    def test_all_inert(self) -> None:
        """Nothing to open: F10 opens nothing."""
        self.menu_bar.set_menus(menus=[self.first, self.second], inert=[0, 1])
        self.menu_bar.handle_key(key="f10")
        self.assertFalse(self.menu_bar.is_open)


class BehindADialogTests(unittest.TestCase):
    """The active application's menus stay on the bar behind a dialog."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.handle_resize(columns=80, lines=24)
        self.notes = self.manager.launch(application=Notes)

    def titles(self) -> list[str]:
        """The titles on the menu bar."""
        return [menu.title for menu in self.manager.bar_menus()]

    def test_shown_but_inert(self) -> None:
        """File and Window stay, inert; the system menu still works."""
        self.manager.add(window=confirm(title="Notes", message="Save the changes?"))
        self.assertEqual(self.titles(), [BURGER, "&File", "&Window"])
        self.assertEqual(self.manager.inert_menus(), [1, 2])
        canvas = Canvas(width=80, height=24)
        self.manager.compose(canvas=canvas)
        self.assertTrue(canvas.text(row=0).startswith(f"  {BURGER}  File  Window"))

    def test_a_menu_after_the_window_menu_is_inert_too(self) -> None:
        """The menu after the Window menu waits for the dialog as well."""
        self.notes.menus.append(Menu("&Help", after_window=True))
        self.manager.add(window=confirm(title="Notes", message="Save the changes?"))
        self.assertEqual(self.titles(), [BURGER, "&File", "&Window", "&Help"])
        self.assertEqual(self.manager.inert_menus(), [1, 2, 3])

    def test_standalone_every_menu_inert(self) -> None:
        """With no system menu, the whole bar is the application's: inert."""
        self.manager.show_system_menu = False
        self.manager.add(window=Dialog(title="Q", width=20, height=6))
        self.assertEqual(self.titles(), ["&File", "&Window"])
        self.assertEqual(self.manager.inert_menus(), [0, 1])

    def test_usable_again_after(self) -> None:
        """Once the dialog is gone, the menus can be used again."""
        dialog = Dialog(title="Q", width=20, height=6)
        self.manager.add(window=dialog)
        self.manager.remove(window=dialog)
        self.assertEqual(self.manager.inert_menus(), [])

    def test_a_window_with_menus_of_its_own(self) -> None:
        """Not a dialog: its own menus show, and can be used."""
        self.manager.add(
            window=Window(title="W", rect=Rect(2, 2, 5, 20), menus=[Menu("&Own")])
        )
        self.assertEqual(self.titles(), [BURGER, "&Own"])
        self.assertEqual(self.manager.inert_menus(), [])

    def test_while_execute_waits(self) -> None:
        """Inert behind a waiting dialog."""
        manager = Scripted()
        manager.launch(application=Notes)
        answers: list[object] = []

        def ask() -> None:
            answers.append(
                manager.execute(dialog=confirm(title="Notes", message="Sure?"))
            )

        manager.actions += [ask, manager.quit]
        terminal = FakeTerminal(
            inputs=["x", "\x1b[21~", "\x1bf", "\r", "x"], sizes=[(80, 24)]
        )
        manager.run(terminal=cast(Terminal, terminal))
        self.assertEqual(answers, ["ok"])
        shown = without_styles(terminal.output.getvalue())
        self.assertIn("Sure?", shown)
        self.assertIn("File  Window", shown)


if __name__ == "__main__":
    unittest.main()
