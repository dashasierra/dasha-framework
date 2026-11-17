"""Tests for the menu bar while an application in its own process is loading:
it becomes the active application once it has something to show, so no frame
shows a Window menu with nothing else of it. Until then the bar stays as it
was, or, on a desktop with no system menu, the desktop's pattern shows through
it."""

# These tests play the application's side of the connection, starting from
# the server's own greeting, so they reach into its workings to do it.
# pylint: disable=protected-access

import tempfile
import unittest
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path
from typing import cast

from dasha import theme
from dasha.application import Application
from dasha.canvas import Canvas
from dasha.client import encode_menus
from dasha.desktop import Desktop
from dasha.events import MouseEvent
from dasha.hosting import AppHost
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuItem
from dasha.protocol import PROTOCOL_VERSION, Message
from dasha.registry import AppEntry
from dasha.terminal import Terminal
from tests.hosted_apps import (
    Broken,
    Hello,
    NeverStarts,
    SlowToBreak,
    SlowToStart,
)
from tests.support import hosted, pipe, serving, tests_importable
from tests.test_hosting import drain, of_type
from tests.test_robustness import StepTerminal
from tests.test_waiting_dialogs import state

SYSTEM = "≡"
"""The system menu's title."""
PATTERN = Desktop.pattern * 80
"""The menu bar's row, drawn in the desktop's pattern."""

type Step = tuple[Callable[[], bool], list[str]]
"""A condition to wait for, and the keys to press once it is true."""


def cells_of(canvas: Canvas) -> str:
    """A canvas's top row, without the space around it."""
    return "".join(canvas.cell(0, c)[0] for c in range(canvas.width)).strip()


def top_row(manager: PresentationManager) -> str:
    """The top row of the screen, as a frame would draw it now."""
    canvas = Canvas(80, 24)
    manager.compose(canvas)
    return cells_of(canvas)


def menus_message(*titles: str) -> Message:
    """The message giving an application's menus, with these titles."""
    menus = [Menu(title, [MenuItem("&Item", lambda: None)]) for title in titles]
    return {"type": "menus", "menus": encode_menus(menus)}


class Loading(unittest.TestCase):
    """A desktop with applications at the end of pipes, greeted as real ones
    are."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.confirm_exit = False
        self.server = serving(self, self.manager)

    def started(self, name: str = "Slow") -> AppHost:
        """An application that has been started, and has not connected."""
        host = AppHost(self.server, "x:Y", name)
        self.server.hosts.append(host)
        self.server._by_token[host.token] = host
        return host

    def greeted(self, name: str = "Slow") -> tuple[AppHost, Connection, Connection]:
        """An application that has said hello, and has sent nothing else:
        its host, its end of the pipe, and the desktop's end."""
        host = self.started(name)
        app_end, desktop_end = pipe()
        self.addCleanup(app_end.close)
        hello = {
            "type": "hello",
            "version": PROTOCOL_VERSION,
            "token": host.token,
            "name": name,
        }
        self.server._greet(desktop_end, hello)
        return host, app_end, desktop_end

    def active_other(self) -> AppHost:
        """Another application, active, with an Edit menu."""
        other, _ = hosted(self.server, "Other")
        other.set_menus(menus_message("&Edit")["menus"])
        return other

    def run_steps(self, *steps: Step) -> None:
        """Run the desktop through ``steps``; fail if it times out."""
        terminal = StepTerminal(self.manager, list(steps))
        self.manager.run(cast(Terminal, terminal))
        self.assertFalse(terminal.timed_out, "timed out")

    def titles(self) -> list[str]:
        """The windows' titles, back to front."""
        return [window.title for window in self.manager.windows]


class OnTheDesktopTests(Loading):
    """Started from the desktop, as the Applications menu does."""

    def test_the_bar_stays_as_it_was(self) -> None:
        """Having said hello, it changes nothing: not the other application's
        menus, nor the name on the status bar, nor the system menu's list."""
        other = self.active_other()
        host, _, _ = self.greeted()
        self.assertEqual(top_row(self.manager), f"{SYSTEM}  Edit  Window")
        self.assertIs(self.manager.active_application, other.application)
        self.assertEqual(self.manager.status_owner, "Other")
        self.assertEqual(self.manager.applications, (other.application,))
        self.assertTrue(host.is_loading)

    def test_the_old_menus_still_work(self) -> None:
        """The application that is still active can still be used."""
        other, other_end = hosted(self.server, "Other")
        other.set_menus(menus_message("&Edit")["menus"])
        self.greeted()
        self.manager.handle_event("alt+e")
        menu = self.manager.menu_bar.open_menu
        assert menu is not None
        self.assertEqual(menu.title, "&Edit")
        self.manager.handle_event("enter")
        self.assertEqual(of_type(drain(other_end), "menu")[0]["path"], [0, 0])

    def test_its_menus_change_everything_together(self) -> None:
        """Its menus arrive, and the bar, the status bar and the system menu
        all change to it at once."""
        self.active_other()
        host, _, _ = self.greeted()
        host.handle(menus_message("&File"))
        self.assertEqual(top_row(self.manager), f"{SYSTEM}  File  Window")
        self.assertIs(self.manager.active_application, host.application)
        self.assertEqual(self.manager.status_owner, "Slow")
        self.assertIn(host.application, self.manager.applications)
        self.assertFalse(host.is_loading)

    def test_with_nothing_else_open(self) -> None:
        """Nothing else is open: the system menu alone stays, and works."""
        host, _, _ = self.greeted()
        self.assertEqual(top_row(self.manager), SYSTEM)
        self.manager.handle_event("f10")
        self.assertIs(self.manager.menu_bar.open_menu, self.manager.system_menu)
        self.manager.handle_event("escape")
        host.handle(menus_message("&File"))
        self.assertEqual(top_row(self.manager), f"{SYSTEM}  File  Window")

    def test_with_no_menus_of_its_own(self) -> None:
        """An application with no menus says so, and has just a Window menu
        once it has loaded."""
        host, _, _ = self.greeted()
        host.handle(menus_message())
        self.assertEqual(top_row(self.manager), f"{SYSTEM}  Window")
        self.assertIs(self.manager.active_application, host.application)

    def test_a_window_without_menus(self) -> None:
        """One that sends a window first has something to show too, and the
        window comes to the front."""
        host, _, _ = self.greeted()
        host.handle(state(title="Slow"))
        self.assertIs(self.manager.active_application, host.application)
        self.assertEqual(self.titles(), ["Slow"])
        self.assertIs(self.manager.active_window, host.windows[1])

    def test_what_shows_nothing_does_not_count(self) -> None:
        """Answering a ping, which a slow start leaves waiting when it ends,
        comes before anything else; nor does saying goodbye show anything."""
        host, _, _ = self.greeted()
        for kind in ("pong", "answer", "bye"):
            host.handle({"type": kind})
        self.assertTrue(host.is_loading)
        self.assertEqual(top_row(self.manager), SYSTEM)

    def test_a_theme_asked_for_as_it_starts(self) -> None:
        """What it does as it starts is still done: it is the application
        the user has just started, so it may change the theme."""
        self.addCleanup(theme.apply_theme, theme.current_theme())
        host, _, _ = self.greeted()
        host.handle({"type": "theme", "name": "dark"})
        self.assertEqual(self.manager.theme_name, "dark")
        self.assertIs(self.manager.active_application, host.application)

    def test_a_second_start_of_a_single_instance(self) -> None:
        """Started again while still loading, it is not switched to: there
        is nothing to show of it yet."""
        target = "tests.hosted_apps:Hello"
        host = self.started("Single")
        host.target = target
        self.manager.start(AppEntry("single", "Single", target, single_instance=True))
        self.assertIsNone(self.manager.active_application)
        self.assertEqual(top_row(self.manager), SYSTEM)
        self.assertEqual(self.server.hosts, [host])


class StandAloneTests(Loading):
    """With no system menu, as ``dasha APP`` runs."""

    def setUp(self) -> None:
        super().setUp()
        self.manager.stand_alone("Slow")
        self.manager._running = True  # so that it can be seen to stop

    def test_the_desktop_shows_through_the_bar(self) -> None:
        """No menus yet, from before it connects until it sends them."""
        self.started()
        self.assertEqual(top_row(self.manager), PATTERN)

    def test_until_its_menus_arrive(self) -> None:
        """There is no moment of a Window menu alone."""
        host, _, _ = self.greeted()
        self.assertEqual(top_row(self.manager), PATTERN)
        host.handle(menus_message("&File"))
        self.assertEqual(top_row(self.manager), "File  Window")

    def test_in_the_desktops_colours(self) -> None:
        """The row looks like the desktop, not like a bar."""
        self.greeted()
        canvas = Canvas(80, 24)
        self.manager.compose(canvas)
        self.assertEqual(canvas.cell(0, 5), canvas.cell(5, 5))
        self.assertEqual(canvas.cell(0, 5)[1], self.manager.desktop.style)

    def test_a_desktop_of_its_own_pattern(self) -> None:
        """Whatever pattern the desktop has, the row follows it."""
        self.manager.desktop = Desktop(pattern="ab")
        self.greeted()
        self.assertEqual(top_row(self.manager), "ab" * 40)

    def test_with_no_menus_of_its_own(self) -> None:
        """Once it has loaded, an application with no menus has a Window
        menu, which it needs."""
        host, _, _ = self.greeted()
        host.handle(menus_message())
        self.assertEqual(top_row(self.manager), "Window")

    def test_the_row_does_nothing(self) -> None:
        """No key opens a menu, nothing offers to, and a click is harmless."""
        self.greeted()
        top_row(self.manager)
        self.assertEqual(self.manager.key_hints(), [])
        self.manager.handle_event("f10")
        self.manager.handle_event(MouseEvent("press", "left", 0, 3))
        self.assertFalse(self.manager.menu_bar.is_open)
        self.assertEqual(top_row(self.manager), PATTERN)

    def test_only_while_loading(self) -> None:
        """A desktop with no menus and nothing loading keeps its bar."""
        self.assertEqual(top_row(self.manager), "")

    def test_ending_before_it_connects(self) -> None:
        """It could not start: the desktop stops, with something to say."""
        self.started().finish(crashed=True)
        self.assertFalse(self.manager.is_running)
        self.assertEqual(self.server.notices[0][0], "Application stopped")

    def test_ending_after_it_connects(self) -> None:
        """It breaks in ``start``: the same."""
        _, _, desktop_end = self.greeted()
        self.server._dispatch(desktop_end, None)
        self.assertFalse(self.manager.is_running)
        self.assertEqual(self.server.notices[0][0], "Application stopped")

    def test_the_last_one_ending_while_another_loads(self) -> None:
        """``dasha a b``: the desktop stays for one that is still coming,
        and the bar goes back to the pattern, not to nothing."""
        first, _, _ = self.greeted("First")
        first.handle(menus_message("&File"))
        second, _, _ = self.greeted("Second")
        first.finish(crashed=False)
        self.assertTrue(self.manager.is_running)
        self.assertEqual(top_row(self.manager), PATTERN)
        second.finish(crashed=False)
        self.assertFalse(self.manager.is_running)


class FailingTests(Loading):
    """An application that goes wrong before it has anything to show."""

    def test_ending_before_it_connects(self) -> None:
        """The bar is as it was, and the user is told."""
        other = self.active_other()
        self.started().finish(crashed=True)
        self.assertEqual(top_row(self.manager), f"{SYSTEM}  Edit  Window")
        self.assertIs(self.manager.active_application, other.application)
        self.assertEqual(self.server.notices[0][0], "Application stopped")

    def test_ending_after_it_connects(self) -> None:
        """It breaks in ``start``: the bar never changed, and the user is
        told."""
        other = self.active_other()
        _, _, desktop_end = self.greeted()
        self.server._dispatch(desktop_end, None)
        self.assertEqual(top_row(self.manager), f"{SYSTEM}  Edit  Window")
        self.assertIs(self.manager.active_application, other.application)
        self.assertEqual(self.server.hosts, [other])
        self.assertEqual(self.server.notices[0][0], "Application stopped")

    def test_nothing_is_left_loading(self) -> None:
        """One that has ended is not still loading."""
        host = self.started()
        self.assertTrue(self.server.is_loading)
        host.finish(crashed=False)
        self.assertFalse(host.is_loading)
        self.assertFalse(self.server.is_loading)


class SlowToLoadTests(Loading):
    """An application that connects, and then has nothing to show for a
    long time."""

    def asking(self) -> bool:
        """Whether the question is on the screen."""
        return "Slow" in self.titles()

    def test_not_before_its_time(self) -> None:
        """It has ``load_timeout`` before anyone is asked."""
        self.greeted()
        self.assertIsNone(self.server.slow_to_load())

    def test_only_once_connected(self) -> None:
        """Not having connected is ``start_timeout``'s business, which ends
        it without asking."""
        self.started()
        self.server.load_timeout = 0
        self.assertIsNone(self.server.slow_to_load())

    def test_not_once_loaded(self) -> None:
        """Having sent something, it has loaded, however long it took."""
        host, _, _ = self.greeted()
        host.handle(menus_message("&File"))
        self.server.load_timeout = 0
        self.assertIsNone(self.server.slow_to_load())

    def test_end_now(self) -> None:
        """The user may end it, and is not then told that it stopped."""
        host, _, _ = self.greeted()
        self.server.load_timeout = 0
        ended: list[bool] = []

        def gone() -> bool:
            ended.append(host.ended)
            return host.ended

        self.run_steps((self.asking, ["e"]), (gone, []))
        self.assertTrue(ended[-1])
        self.assertEqual(self.server.notices, [])

    def test_wait(self) -> None:
        """The user may wait for it, and is asked again later."""
        host, _, _ = self.greeted()
        self.server.load_timeout = 0
        due: list[AppHost | None] = []

        def answered() -> bool:
            self.server.load_timeout = 60
            if self.titles():
                return False
            due.append(self.server.slow_to_load())  # not yet: it just waited
            self.server.load_timeout = 0
            due.append(self.server.slow_to_load())  # and again, later
            self.server.load_timeout = 60
            return True

        self.run_steps((self.asking, ["w"]), (answered, []))
        self.assertFalse(host.ended)
        self.assertEqual(due, [None, host])

    def test_starting_while_being_asked(self) -> None:
        """It loads while the question is open: End now no longer applies."""
        host, _, _ = self.greeted()
        self.server.load_timeout = 0

        def load() -> bool:
            if not self.asking():
                return False
            host.handle(menus_message("&File"))
            return True

        self.run_steps((load, ["e"]), (lambda: not self.asking(), []))
        self.assertFalse(host.ended)
        self.assertIs(self.manager.active_application, host.application)


class ShuttingDownTests(Loading):
    """Leaving the desktop while an application is loading."""

    def test_it_is_not_waited_for(self) -> None:
        """Too busy to answer, and with no work to lose: the desktop leaves
        without asking it."""
        _, app_end, _ = self.greeted()
        left: list[bool] = []
        self.server.ask_to_close(lambda: left.append(True))
        self.assertEqual(left, [True])
        self.assertEqual(of_type(drain(app_end), "may_close"), [])

    def test_loading_while_others_are_asked(self) -> None:
        """It finishes loading while another keeps the desktop waiting, and
        might have work to lose by then: it is asked as well."""
        other, _ = hosted(self.server, "Other")
        host, app_end, _ = self.greeted()
        left: list[bool] = []
        self.server.ask_to_close(lambda: left.append(True))
        host.handle(menus_message("&File"))
        self.assertEqual(len(of_type(drain(app_end), "may_close")), 1)
        self.server.answered(other, True)
        self.assertEqual(left, [])
        self.server.answered(host, True)
        self.assertEqual(left, [True])


class Recording(PresentationManager):
    """A desktop that keeps every different top row it has drawn."""

    def __init__(self) -> None:
        super().__init__()
        self.bars: list[str] = []

    def compose(self, canvas: Canvas) -> None:
        super().compose(canvas)
        top = cells_of(canvas)
        if not self.bars or self.bars[-1] != top:
            self.bars.append(top)


class RealProcessTests(unittest.TestCase):
    """Real application processes, watching every frame."""

    def setUp(self) -> None:
        # Windows can hold a log a moment after its process ends.
        folder = tempfile.TemporaryDirectory(  # pylint: disable=consider-using-with
            ignore_cleanup_errors=True
        )
        self.addCleanup(folder.cleanup)
        tests_importable(self)
        self.manager = Recording()
        self.manager.use_processes = True
        self.manager.confirm_exit = False
        self.server = serving(self, self.manager)
        self.server.log_folder = Path(folder.name)
        # Short: a ping waits when start() ends, and is answered first.
        self.server.ping_interval = 0.1

    def run_until(self, *steps: Step) -> None:
        """Run the desktop through ``steps``; fail if it times out."""
        terminal = StepTerminal(self.manager, list(steps))
        self.manager.run(cast(Terminal, terminal))
        self.assertFalse(terminal.timed_out, f"timed out: {self.manager.bars}")

    def has_windows(self) -> bool:
        """Whether a window has arrived."""
        return bool(self.manager.windows)

    def breaks(self, application: type[Application]) -> None:
        """It breaks as it starts: the bar never changes, and the user is
        told."""
        told: list[str] = []

        def telling() -> bool:
            told.extend(window.title for window in self.manager.windows)
            return bool(told)

        self.manager.start(application)
        self.run_until((telling, ["\r"]))
        self.assertEqual(told, ["Application stopped"])
        self.assertEqual(self.manager.bars, [SYSTEM])

    def test_slow_to_start_on_the_desktop(self) -> None:
        """Just the system menu, and then everything."""
        self.manager.start(SlowToStart)
        self.run_until((self.has_windows, []))
        self.assertEqual(self.manager.bars, [SYSTEM, f"{SYSTEM}  File  Window"])

    def test_slow_to_start_on_its_own(self) -> None:
        """Just the desktop's pattern, and then everything."""
        self.manager.stand_alone("Slow")
        self.manager.start(SlowToStart)
        self.run_until((self.has_windows, []))
        self.assertEqual(self.manager.bars, [PATTERN, "File  Window"])

    def test_slow_to_start_over_another(self) -> None:
        """The other application's menus stay until the new one's come."""
        other, _ = hosted(self.server, "Other")
        other.set_menus(menus_message("&Edit")["menus"])
        self.manager.start(SlowToStart)
        self.run_until((self.has_windows, []))
        self.assertEqual(
            self.manager.bars, [f"{SYSTEM}  Edit  Window", f"{SYSTEM}  File  Window"]
        )

    def test_no_menus_of_its_own(self) -> None:
        """Once it has loaded, it looks as it should."""
        self.manager.start(Hello)
        self.run_until((self.has_windows, []))
        self.assertEqual(self.manager.bars, [SYSTEM, f"{SYSTEM}  Window"])

    def test_breaking_at_once(self) -> None:
        """It breaks as soon as it starts."""
        self.breaks(Broken)

    def test_breaking_after_a_while(self) -> None:
        """It breaks once it has been connected for a while."""
        self.breaks(SlowToBreak)

    def test_breaking_on_its_own(self) -> None:
        """With nothing else to show, the desktop stops, and what it had to
        say is left for the terminal."""
        self.manager.stand_alone("Slow break")
        self.manager.start(SlowToBreak)
        self.run_until((lambda: False, []))
        self.assertEqual(self.manager.bars, [PATTERN])
        self.assertIn("Slow break stopped", self.server.notices[0][1])

    def test_never_starting_can_be_ended(self) -> None:
        """Connected, and never any further: the user is asked, and it goes.
        On its own, the desktop goes with it."""
        self.manager.stand_alone("Never")
        self.server.load_timeout = 0.3
        self.manager.start(NeverStarts)
        self.run_until((self.has_windows, ["e"]), (lambda: False, []))
        self.assertEqual(self.manager.bars, [PATTERN])
        self.assertEqual(self.server.hosts, [])

    def test_never_starting_can_be_left(self) -> None:
        """The exit key works throughout, and the desktop does not wait for
        an application that is too busy to answer it."""
        self.manager.stand_alone("Never")
        self.manager.start(NeverStarts)
        host = self.server.hosts[0]
        self.run_until(
            (lambda: host.connection is not None, ["\x11"]), (lambda: False, [])
        )
        self.assertIsNone(self.server.closing)
        self.assertEqual(self.manager.bars, [PATTERN])
