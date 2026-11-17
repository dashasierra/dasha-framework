"""Tests for applications: launching, their menus and windows, the active
application, ending, and the Applications menu."""

import os
import unittest
from collections.abc import Callable
from typing import cast
from unittest import mock

from dasha.application import Application
from dasha.canvas import Canvas, Rect
from dasha.dialog import information
from dasha.events import Event, MouseEvent
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuItem
from dasha.shortcuts import Shortcuts
from dasha.style import Style
from dasha.terminal import Terminal
from dasha.theme import BASES, apply_theme, current_theme
from dasha.window import Window
from tests.support import without_styles
from tests.test_manager import FakeTerminal

ALT_F4 = "\x1b[1;3S"


class Hello(Application):
    """One window, saying hello."""

    name = "Hello"

    def start(self) -> None:
        self.open(Window("Hello", Rect(2, 2, 6, 30), ["Hello"], closable=True))


class Lonely(Hello):
    """Only one at a time."""

    name = "Lonely"
    single_instance = True


class Daemon(Application):
    """No windows."""

    name = "Daemon"


class Stubborn(Hello):
    """Will not let the desktop shut down until allowed to."""

    name = "Stubborn"

    def __init__(self) -> None:
        super().__init__()
        self.allow = False
        self.asked = 0

    def can_close(self) -> bool:
        self.asked += 1
        return self.allow


class Notes(Application):
    """Two windows, and a File menu whose Close needs a window."""

    name = "Notes"

    def start(self) -> None:
        self.menus = [
            Menu(
                "&File",
                [
                    MenuItem(
                        "&Close",
                        lambda: self.close(cast(Window, self.active_window)),
                        enabled=self.has_window,
                    ),
                    MenuItem("E&xit", self.exit),
                ],
            )
        ]
        for title, row in (("First", 2), ("Second", 4)):
            self.open(
                Window(title, Rect(row, 2, 6, 30), minimisable=True, closable=True)
            )


class Scripted(PresentationManager):
    """Runs the next of ``actions`` each time "x" is pressed."""

    def __init__(self) -> None:
        super().__init__()
        self.actions: list[Callable[[], object]] = []

    def handle_event(self, event: Event) -> None:
        if event == "x":
            self.actions.pop(0)()
        else:
            super().handle_event(event)


def run(manager: PresentationManager, inputs: list[str]) -> FakeTerminal:
    """Run a manager on scripted input, all of which must be read."""
    terminal = FakeTerminal(inputs, sizes=[(80, 24)])
    manager.run(cast(Terminal, terminal))
    return terminal


def labels(menu: Menu) -> list[str]:
    """A menu's item labels."""
    return [item.label for item in menu.items]


class Desktop(unittest.TestCase):
    """A desktop, 80 by 24."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.handle_resize(80, 24)

    def menu_bar(self) -> list[str]:
        """The titles on the menu bar."""
        return [menu.title for menu in self.manager.bar_menus()]

    def window_menu(self) -> Menu:
        """The Window menu on the bar."""
        return self.manager.bar_menus()[-1]


class AfterWindowTests(Desktop):
    """A menu that goes after the Window menu."""

    def setUp(self) -> None:
        super().setUp()
        self.app = self.manager.launch(Notes)
        self.help = Menu("&Help", [MenuItem("&Index", print)], after_window=True)
        self.app.menus = [self.help, *self.app.menus]

    def test_after_the_window_menu(self) -> None:
        """It goes last, whatever its place in the application's menus."""
        self.assertEqual(
            self.menu_bar(),
            [PresentationManager.system_menu_title, "&File", "&Window", "&Help"],
        )
        self.assertIs(self.app.menus[0], self.help)

    def test_opens_by_its_letter(self) -> None:
        """Alt and its letter opens it, as for any menu on the bar."""
        self.manager.handle_event("alt+h")
        self.assertIs(self.manager.menu_bar.open_menu, self.help)

    def test_arrows_reach_it(self) -> None:
        """Right from the Window menu goes to it."""
        self.manager.handle_event("alt+w")
        window_menu = self.manager.menu_bar.open_menu
        assert window_menu is not None
        self.assertEqual(window_menu.title, "&Window")
        self.manager.handle_event("right")
        self.assertIs(self.manager.menu_bar.open_menu, self.help)


class LaunchTests(Desktop):
    """Starting applications and their windows."""

    def test_launch_a_class(self) -> None:
        """A class is made into an application, started, and shows its window."""
        app = self.manager.launch(Hello)
        self.assertIsInstance(app, Hello)
        self.assertTrue(app.is_running)
        self.assertIs(app.manager, self.manager)
        self.assertEqual(self.manager.applications, (app,))
        (window,) = app.windows
        self.assertIn(window, self.manager.windows)
        self.assertIs(self.manager.application_of(window), app)
        self.assertIs(self.manager.active_application, app)
        self.assertIs(app.active_window, window)

    def test_launch_an_instance(self) -> None:
        """An application made already is started as it is."""
        app = Hello()
        self.assertIs(self.manager.launch(app), app)
        self.assertEqual(len(self.manager.windows), 1)

    def test_several_instances(self) -> None:
        """Launching again starts another, unless it is single_instance."""
        first, second = self.manager.launch(Hello), self.manager.launch(Hello)
        self.assertIsNot(first, second)
        self.assertEqual(len(self.manager.windows), 2)

    def test_single_instance(self) -> None:
        """A single-instance application is switched to instead."""
        lonely = self.manager.launch(Lonely)
        self.manager.launch(Hello)
        self.assertIs(self.manager.launch(Lonely), lonely)
        self.assertEqual(len(self.manager.applications), 2)
        self.assertIs(self.manager.active_window, lonely.windows[0])
        self.assertIs(self.manager.active_application, lonely)

    def test_single_instance_with_its_window_minimised(self) -> None:
        """Switched to, it stays minimised: its Window menu lists it."""
        lonely = self.manager.launch(Lonely)
        self.manager.launch(Hello)
        self.manager.minimise(lonely.windows[0])
        self.manager.launch(Lonely)
        self.assertIs(self.manager.active_application, lonely)
        self.assertIsNone(self.manager.active_window)
        self.assertIn("&1 Hello (minimised)", labels(self.window_menu()))

    def test_no_windows_keeps_running(self) -> None:
        """An application that opens nothing runs on, its menus showing."""
        app = self.manager.launch(Daemon)
        self.assertTrue(app.is_running)
        self.assertIs(self.manager.active_application, app)
        self.assertEqual(
            self.menu_bar(), [PresentationManager.system_menu_title, "&Window"]
        )

    def test_open_needs_launching(self) -> None:
        """Windows open only once it is launched."""
        with self.assertRaises(RuntimeError):
            Hello().open(Window("W", Rect(0, 0, 4, 10)))

    def test_told_when_the_shortcuts_change(self) -> None:
        """Every running application hears of new shortcuts, which are in
        place by then, so that it can make its menus again."""
        seen: list[str] = []

        class Hinted(Hello):
            """Notes the key its menu would show for exit."""

            def shortcuts_changed(self) -> None:
                assert self.manager is not None
                seen.append(self.manager.shortcuts.hint("exit"))

        self.manager.launch(Hinted)
        self.manager.launch(Hinted)
        self.manager.set_shortcuts(Shortcuts({"exit": ["ctrl+k"]}))
        self.assertEqual(seen, ["Ctrl+K", "Ctrl+K"])


class EndingTests(Desktop):
    """Applications end when they quit, not when their windows close."""

    def test_closing_every_window_leaves_it_running(self) -> None:
        """Its menu bar stays, its window items greyed out."""
        app = self.manager.launch(Notes)
        for window in list(app.windows):
            self.manager.close(window)
        self.assertTrue(app.is_running)
        self.assertEqual(app.windows, [])
        self.assertIs(self.manager.active_application, app)
        self.assertEqual(
            self.menu_bar(), [PresentationManager.system_menu_title, "&File", "&Window"]
        )
        close, exit_ = app.menus[0].items
        self.assertFalse(close.is_available)
        self.assertTrue(exit_.is_available)
        self.assertFalse(any(item.is_available for item in self.window_menu().items))

    def test_exit(self) -> None:
        """File > Exit ends it, if can_close agrees."""
        app = self.manager.launch(Stubborn)
        app.exit()
        self.assertTrue(app.is_running)
        app.allow = True
        app.exit()
        self.assertFalse(app.is_running)
        self.assertEqual(self.manager.windows, ())

    def test_quit_takes_its_windows(self) -> None:
        """quit() removes every window, minimised ones too, and no others."""
        app = self.manager.launch(Hello)
        other = self.manager.launch(Hello)
        app.open(Window("More", Rect(4, 4, 6, 20)))
        self.manager.minimise(app.windows[1])
        app.quit()
        self.assertEqual(self.manager.windows, tuple(other.windows))
        self.assertEqual(self.manager.minimised, ())
        self.assertEqual(app.windows, [])
        self.assertIs(self.manager.active_application, other)
        app.quit()  # twice is harmless

    def test_the_last_one_ending(self) -> None:
        """With no application left, only the system menu."""
        self.manager.launch(Hello).quit()
        self.assertIsNone(self.manager.active_application)
        self.assertEqual(self.menu_bar(), [PresentationManager.system_menu_title])

    def test_dialogs_are_not_the_applications(self) -> None:
        """A window added straight to the manager belongs to no application."""
        window = Window("Plain", Rect(2, 2, 4, 10))
        self.manager.add(window)
        self.assertIsNone(self.manager.application_of(window))


class ActiveApplicationTests(Desktop):
    """Which application's menus show, and which window has the keyboard."""

    def setUp(self) -> None:
        super().setUp()
        self.notes = self.manager.launch(Notes)
        self.hello = self.manager.launch(Hello)

    def test_follows_the_front_window(self) -> None:
        """The front window's application is the active one."""
        self.assertIs(self.manager.active_application, self.hello)
        self.manager.bring_to_front(self.notes.windows[0])
        self.assertIs(self.manager.active_application, self.notes)
        self.manager.activate_next()
        self.assertIs(self.manager.active_application, self.hello)

    def test_switching_to_one_without_windows(self) -> None:
        """Its menus show; no other application's window has the keyboard."""
        daemon = self.manager.launch(Daemon)
        self.manager.switch_to(daemon)
        self.assertIs(self.manager.active_application, daemon)
        self.assertIsNone(self.manager.active_window)
        self.manager.bring_to_front(self.notes.windows[0])
        self.assertIs(self.manager.active_application, self.notes)

    def test_closing_brings_its_next_window(self) -> None:
        """Its own next window comes forward, past others' in between."""
        first, second = self.notes.windows
        self.manager.bring_to_front(first)
        self.manager.bring_to_front(self.hello.windows[0])
        self.manager.bring_to_front(second)
        self.manager.close(second)
        self.assertIs(self.manager.active_window, first)
        self.manager.minimise(first)
        self.assertIs(self.manager.active_application, self.notes)
        self.assertIsNone(self.manager.active_window)

    def test_a_dialog_shows_its_own_menus(self) -> None:
        """A window of no application's in front: its menus, not the app's."""
        dialog = Window("Dialog", Rect(5, 5, 5, 20), menus=[Menu("&Own")])
        self.manager.add(dialog)
        self.assertEqual(
            self.menu_bar(), [PresentationManager.system_menu_title, "&Own"]
        )
        self.assertIs(self.manager.active_window, dialog)
        self.assertIs(self.manager.active_application, self.hello)


class WindowMenuTests(Desktop):
    """The Window menu Dasha Framework gives every application."""

    def setUp(self) -> None:
        super().setUp()
        self.app = self.manager.launch(Notes)
        self.first, self.second = self.app.windows

    def test_items_then_windows(self) -> None:
        """Window items, greyed where the window cannot, then its windows."""
        self.assertEqual(
            labels(self.window_menu()),
            ["Ma&ximise / restore", "Mi&nimise", "&Move", "&Size", "",
             "Send to &back", "&Next window", "", "&Close", "",
             "&1 First", "&2 Second"],
        )  # fmt: skip
        maximise, minimise, move, size = self.window_menu().items[:4]
        self.assertFalse(maximise.is_available)  # not maximisable
        self.assertFalse(size.is_available)  # not resizable
        self.assertTrue(minimise.is_available and move.is_available)

    def test_minimised_windows_are_listed_and_restored(self) -> None:
        """Minimised ones are marked, and come back."""
        self.manager.minimise(self.first)
        self.assertEqual(
            labels(self.window_menu())[-2:], ["&1 First (minimised)", "&2 Second"]
        )
        action = self.window_menu().items[-2].action
        assert action is not None
        action()
        self.assertIs(self.manager.active_window, self.first)

    def test_the_last_window_can_be_minimised(self) -> None:
        """The menu bar stays, so it can be restored from the Window menu."""
        self.manager.minimise(self.first)
        self.manager.minimise(self.second)
        self.assertEqual(self.manager.windows, ())
        self.assertEqual(self.menu_bar()[-1], "&Window")

    def test_same_menu_each_time(self) -> None:
        """Rebuilt in place, so an open menu stays open."""
        self.assertIs(self.manager.bar_menus()[-1], self.manager.bar_menus()[-1])

    def test_close_acts_on_the_active_window(self) -> None:
        """Close closes the application's front window."""
        close = self.window_menu().items[8]
        assert close.action is not None
        close.action()
        self.assertEqual(self.app.windows, [self.first])


class SystemMenuTests(Desktop):
    """The system menu lists the applications, to switch between them."""

    def test_applications_listed_and_switched_to(self) -> None:
        """Running applications, the active one marked."""
        notes = self.manager.launch(Notes)
        self.manager.launch(Hello)
        self.manager.launch(Hello)
        self.manager.bar_menus()
        items = self.manager.system_menu.items
        self.assertEqual(
            labels(self.manager.system_menu)[:4],
            ["  &1 Notes", "  &2 Hello", "\N{SQUARE ROOT} &3 Hello (2)", ""],
        )
        action = items[0].action
        assert action is not None
        action()
        self.assertIs(self.manager.active_application, notes)
        self.manager.bar_menus()
        self.assertTrue(
            labels(self.manager.system_menu)[0].startswith("\N{SQUARE ROOT}")
        )

    def test_only_loose_minimised_windows_in_the_system_menu(self) -> None:
        """An application's minimised windows are in its Window menu."""
        app = self.manager.launch(Notes)
        loose = Window("Loose", Rect(3, 3, 5, 20), minimisable=True)
        self.manager.add(loose)
        self.manager.minimise(loose)
        self.manager.minimise(app.windows[0])
        system = labels(self.manager.system_menu)
        self.assertIn("&1 Loose", system)
        self.assertFalse(any("First" in label for label in system))


class ApplicationsMenuTests(unittest.TestCase):
    """The system menu's Applications submenu."""

    def test_only_once_registered(self) -> None:
        """The submenu appears once, after About, in order."""
        manager = PresentationManager()
        names = [item.label for item in manager.system_menu.items]
        self.assertNotIn("A&pplications", names)
        manager.register(Hello)
        manager.register({"Lonely one": Lonely, "a daemon": Daemon})
        items = manager.system_menu.items
        self.assertEqual(
            [item.label for item in items[:4]],
            ["&About", "A&pplications", "&Run...", "S&ettings..."],
        )
        submenu = items[1].submenu
        assert submenu is not None
        self.assertEqual(
            [item.label for item in submenu.items],
            ["&a daemon", "&Hello", "&Lonely one"],
        )
        self.assertEqual(len([i for i in items if i.label == "A&pplications"]), 1)

    def test_choosing_launches(self) -> None:
        """Choosing an item starts that application."""
        manager = PresentationManager()
        manager.handle_resize(80, 24)
        manager.register(Hello)
        submenu = manager.system_menu.items[1].submenu
        assert submenu is not None and submenu.items[0].action is not None
        submenu.items[0].action()
        self.assertIsInstance(manager.applications[0], Hello)


class ExitTests(unittest.TestCase):
    """Shutting the desktop down asks each application first."""

    def test_an_application_can_object(self) -> None:
        """can_close() saying no keeps the desktop running."""
        manager = Scripted()
        stubborn = manager.launch(Stubborn)

        def allow() -> None:
            stubborn.allow = True
            manager.request_exit()

        manager.actions.append(allow)
        run(manager, ["\x11", "\r", "x", "\r"])  # refused; then allowed
        self.assertEqual(stubborn.asked, 2)
        self.assertFalse(manager.is_running)

    def test_not_asked_if_cancelled(self) -> None:
        """Cancelling the exit dialog asks no one."""
        manager = Scripted()
        stubborn = manager.launch(Stubborn)
        manager.actions.append(manager.quit)
        run(manager, ["\x11", "\x1b", "", "x"])
        self.assertEqual(stubborn.asked, 0)


class StandaloneTests(unittest.TestCase):
    """Application.run(): a desktop of its own."""

    def test_runs_on_without_windows(self) -> None:
        """Closing its window (Alt+F4) leaves it running; Ctrl+Q ends it."""
        app = Hello()
        terminal = FakeTerminal([ALT_F4, "\x11", "\r"], sizes=[(80, 24)])
        self.assertEqual(app.run(cast(Terminal, terminal)), 0)
        # Had it ended with its window, the run would have stopped before
        # reading Ctrl+Q.
        self.assertEqual(terminal.inputs, [])

    def test_exit_ends_the_run(self) -> None:
        """Its own File > Exit ends the run, with no question."""
        app = Notes()
        terminal = FakeTerminal(["\x1b[21~", "x", "never read"], sizes=[(80, 24)])
        self.assertEqual(app.run(cast(Terminal, terminal)), 0)
        self.assertEqual(terminal.inputs, ["never read"])

    def test_nothing_to_show(self) -> None:
        """An application that opens no window still runs, its menus
        showing, until it is left."""
        terminal = FakeTerminal(["\x11", "\r"], sizes=[(80, 24)])
        self.assertEqual(Application().run(cast(Terminal, terminal)), 0)
        self.assertEqual(terminal.inputs, [])

    def test_sized_to_the_screen_from_the_start(self) -> None:
        """``start`` sees the screen's real size, so that it can fit its
        windows to it."""
        seen: list[Rect] = []

        class Measuring(Application):
            """Notes the work area as it starts."""

            def start(self) -> None:
                assert self.manager is not None
                seen.append(self.manager.workspace)

        terminal = FakeTerminal(["\x11", "\r"], sizes=[(120, 40)])
        self.assertEqual(Measuring().run(cast(Terminal, terminal)), 0)
        self.assertEqual(seen, [Rect(1, 0, 38, 120)])

    def frame_style_with(self, no_colour: str, *, starts_dark: bool = False) -> Style:
        """The window frame's style as an application starts, run with this
        value of ``NO_COLOR``, having chosen the Dark theme itself, if asked."""
        self.addCleanup(apply_theme, current_theme())
        seen: list[Style] = []

        class Looking(Application):
            """Notes the theme as it starts."""

            def start(self) -> None:
                if starts_dark:
                    self.set_theme("dark")
                seen.append(Window.frame_style)

        terminal = FakeTerminal(["\x11", "\r"], sizes=[(80, 24)])
        with mock.patch.dict(os.environ, {"NO_COLOR": no_colour}):
            Looking().run(cast(Terminal, terminal))
        return seen[0]

    def test_no_colour_means_monochrome(self) -> None:
        """With ``NO_COLOR`` set, it starts in the Monochrome theme."""
        self.assertEqual(
            self.frame_style_with("1"), BASES["monochrome"]["window.frame"]
        )

    def test_empty_no_colour_does_not_count(self) -> None:
        """``NO_COLOR`` set to nothing leaves the colours as they are."""
        before = Window.frame_style
        self.assertEqual(self.frame_style_with(""), before)

    def test_an_application_can_choose_its_own_theme(self) -> None:
        """A theme it chooses as it starts comes after ``NO_COLOR``."""
        self.assertEqual(
            self.frame_style_with("1", starts_dark=True), BASES["dark"]["window.frame"]
        )

    def test_no_system_menu_and_its_own_exit(self) -> None:
        """No ≡; Ctrl+Q asks to close the application, not Dasha Framework."""
        terminal = FakeTerminal(["\x11", "\r"], sizes=[(80, 24)])
        Hello().run(cast(Terminal, terminal))
        shown = without_styles(terminal.output.getvalue())
        self.assertNotIn(PresentationManager.system_menu_title, shown)
        self.assertIn("Close Hello?", shown)
        self.assertNotIn("Shutting down", shown)

    def test_menu_bar(self) -> None:
        """Its menus and the Window menu, and no system menu."""
        manager = PresentationManager()
        manager.show_system_menu = False
        manager.handle_resize(80, 24)
        manager.launch(Notes)
        self.assertEqual(
            [menu.title for menu in manager.bar_menus()], ["&File", "&Window"]
        )
        canvas = Canvas(80, 24)
        manager.compose(canvas)
        self.assertNotIn(PresentationManager.system_menu_title, canvas.text(0))
        event = MouseEvent("press", "left", 0, 2, clicks=2)
        # pylint: disable-next=protected-access
        self.assertFalse(manager._is_system_menu_double_click(event))

    def test_f10_opens_the_window_menu(self) -> None:
        """An application with no menus of its own still has the Window menu."""
        terminal = FakeTerminal(
            ["\x1b[21~", "\x1b", "", "\x11", "\r"], sizes=[(80, 24)]
        )
        self.assertEqual(Hello().run(cast(Terminal, terminal)), 0)
        self.assertEqual(terminal.inputs, [])


class Greeter(Hello):
    """Says hello in a dialog as it starts."""

    name = "Greeter"

    def start(self) -> None:
        super().start()
        manager = cast(PresentationManager, self.manager)
        manager.call_when_running(
            lambda: manager.execute(information("Greeter", "Good morning"))
        )


class WhenRunningTests(unittest.TestCase):
    """call_when_running: what waits for the desktop to be running."""

    def test_a_dialog_as_it_starts(self) -> None:
        """Standalone, a dialog asked for in start shows once running."""
        terminal = FakeTerminal(["\r", "\x11", "\r"], sizes=[(80, 24)])
        self.assertEqual(Greeter().run(cast(Terminal, terminal)), 0)
        self.assertIn("Good morning", without_styles(terminal.output.getvalue()))
        self.assertEqual(terminal.inputs, [])

    def test_held_until_run(self) -> None:
        """Held until run starts, then called in order, before any input."""
        manager = Scripted()
        called: list[str] = []
        manager.call_when_running(lambda: called.append("first"))
        manager.call_when_running(lambda: called.append("second"))
        self.assertEqual(called, [])
        manager.actions.append(manager.quit)
        run(manager, ["x"])
        self.assertEqual(called, ["first", "second"])

    def test_straight_away_while_running(self) -> None:
        """While run is going, called straight away."""
        manager = Scripted()
        called: list[bool] = []

        def action() -> None:
            manager.call_when_running(lambda: called.append(manager.is_running))
            self.assertEqual(called, [True])
            manager.quit()

        manager.actions.append(action)
        run(manager, ["x"])
        self.assertEqual(called, [True])

    def test_held_again_once_run_ends(self) -> None:
        """After run ends, held for the next run."""
        manager = Scripted()
        manager.actions.append(manager.quit)
        run(manager, ["x"])
        called: list[str] = []
        manager.call_when_running(lambda: called.append("later"))
        self.assertEqual(called, [])
        manager.actions.append(manager.quit)
        run(manager, ["x"])
        self.assertEqual(called, ["later"])

    def test_not_called_once_stopped(self) -> None:
        """One that stops the desktop: the rest are not called."""
        manager = Scripted()
        called: list[str] = []
        manager.call_when_running(manager.quit)
        manager.call_when_running(lambda: called.append("too late"))
        run(manager, [])
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
