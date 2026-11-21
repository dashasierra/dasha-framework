"""Tests for the desktop's edges: settings that cannot be kept, windows
added twice, and popups placed near the bottom."""

# pylint: disable=protected-access

import threading
import unittest
from typing import cast
from unittest import mock

from dasha import registry, theme
from dasha.canvas import Rect
from dasha.dialog import Dialog, Popup
from dasha.events import MouseEvent
from dasha.manager import (
    PresentationManager,
    _catch_ending_signals,
    _with_mnemonic,
    drawn_active,
)
from dasha.menu import Menu
from dasha.terminal import Terminal
from dasha.widgets import AutoCompleteBox
from dasha.window import Window
from tests.support import isolated_home


class Showing(PresentationManager):
    """A desktop that can show dialogs, noting each instead."""

    def __init__(self) -> None:
        super().__init__()
        self.shown: list[str] = []
        self._terminal = cast(Terminal, object())

    def execute(self, dialog: Dialog) -> str | None:
        self.shown.append(dialog.title)
        return "ok"


class SettingsProblemTests(unittest.TestCase):
    """Settings that cannot be read or remembered are said."""

    def setUp(self) -> None:
        self.home = isolated_home(self)
        self.manager = Showing()
        self.manager.handle_resize(80, 24)
        self.manager.settings_path = self.home / "settings.toml"
        self.manager.colours_path = self.home / "colours.json"

    def test_no_colours_file(self) -> None:
        """With no colours file, choosing it does nothing."""
        self.manager.colours_path = None
        self.manager._use_colours_file()
        self.assertEqual(self.manager.theme_name, "default")

    def test_a_broken_colours_file(self) -> None:
        """A broken colours file is said, and the theme stays."""
        self.home.joinpath("colours.json").write_text("{not json", "utf-8")
        self.manager._use_colours_file()
        self.assertEqual(self.manager.shown, ["Themes"])
        self.assertEqual(self.manager.theme_name, "default")

    def test_a_theme_that_cannot_be_remembered(self) -> None:
        """The colours are used even when the choice cannot be saved."""
        self.home.joinpath("colours.json").write_text(
            theme.theme_to_json(theme.DARK_THEME, "dark"), "utf-8"
        )
        self.manager.remember_theme = True
        with mock.patch.object(
            registry, "save_theme_setting", side_effect=OSError("read-only")
        ):
            self.manager._use_colours_file()
        self.assertEqual(self.manager.shown, ["Themes"])
        self.assertIsNone(self.manager.theme_name)

    def test_animations_and_mouse_that_cannot_be_remembered(self) -> None:
        """Each is used, and the problem said under its own title."""
        with (
            mock.patch.object(
                registry, "save_animations_setting", side_effect=OSError("read-only")
            ),
            mock.patch.object(
                registry, "save_show_mouse_setting", side_effect=OSError("read-only")
            ),
        ):
            self.manager.set_animations(True, remember=True)
            self.manager.set_show_mouse(True, remember=True)
        self.assertEqual(self.manager.shown, ["Animations", "Show the mouse"])
        self.assertTrue(self.manager.animations)
        self.assertTrue(self.manager.show_mouse)

    def test_an_escape_wait_that_cannot_be_read(self) -> None:
        """A broken saved wait leaves the wait as it was."""
        before = self.manager.escape_timeout
        with mock.patch.object(
            registry,
            "read_escape_timeout_setting",
            side_effect=registry.ManifestError("bad"),
        ):
            self.manager.use_saved_escape_timeout()
        self.assertEqual(self.manager.escape_timeout, before)


class WindowEdgeTests(unittest.TestCase):
    """Adding, minimising and scrolling windows."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.handle_resize(80, 24)
        self.window = Window("W", Rect(2, 2, 8, 30))

    def test_a_window_added_twice(self) -> None:
        """A window already on the desktop cannot be added again, behind."""
        self.manager.add(self.window)
        with self.assertRaises(ValueError):
            self.manager.add_behind(self.window)

    def test_maximised_windows_fill_this_workspace(self) -> None:
        """A window maximised elsewhere fills this desktop's workspace."""
        behind = Window("B", Rect(2, 2, 8, 30))
        for window in (self.window, behind):
            window.maximise(Rect(0, 0, 5, 20))
        self.manager.add(self.window)
        self.manager.add_behind(behind)
        workspace = self.manager.workspace
        self.assertEqual(self.window.rect, workspace)
        self.assertEqual(behind.rect, workspace)

    def test_minimise_twice_or_alone(self) -> None:
        """Minimising a minimised window does nothing; nor does minimising
        the only window when there is no system menu to get it back."""
        self.manager.add(self.window)
        self.manager.add(Window("Other", Rect(3, 3, 8, 30)))
        self.manager.minimise(self.window)
        self.manager.minimise(self.window)
        self.assertEqual(self.manager.minimised, (self.window,))
        alone = PresentationManager()
        alone.handle_resize(80, 24)
        alone.show_system_menu = False
        only = Window("Only", Rect(2, 2, 8, 30))
        alone.add(only)
        alone.minimise(only)
        self.assertEqual(alone.minimised, ())

    def test_the_wheel_outside_and_sideways(self) -> None:
        """The wheel on the menu bar does nothing; sideways scrolls across."""
        self.manager.add(self.window)
        with mock.patch.object(self.window, "scroll_by") as scroll_by:
            self.manager._mouse_wheel(MouseEvent("scroll", "down", 0, 5))
            scroll_by.assert_not_called()
            self.manager._mouse_wheel(MouseEvent("scroll", "right", 4, 5))
        scroll_by.assert_called_once_with(0, 3)

    def test_window_menu(self) -> None:
        """Each window has a Window menu."""
        self.assertIsInstance(self.manager.window_menu(self.window), Menu)


class SmallPartsTests(unittest.TestCase):
    """The desktop's helpers, at their edges."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.handle_resize(80, 24)

    def test_a_window_behind_an_open_popup(self) -> None:
        """A window not on the desktop is not drawn active behind a popup."""
        popup = Popup("", 10, 5)
        self.assertFalse(drawn_active(Window("W", Rect(2, 2, 5, 20)), popup, []))

    def test_no_letter_left(self) -> None:
        """A label whose letters are all taken gets no mnemonic."""
        self.assertEqual(_with_mnemonic("ab", {"a", "b"}), "ab")

    def test_ending_signals(self) -> None:
        """Only the main thread catches them; ones it cannot catch are
        skipped."""
        caught: list[dict[int, object]] = []
        thread = threading.Thread(target=lambda: caught.append(_catch_ending_signals()))
        thread.start()
        thread.join()
        self.assertEqual(caught, [{}])
        with mock.patch("signal.signal", side_effect=ValueError):
            self.assertEqual(_catch_ending_signals(), {})

    def test_minimised_windows_in_a_lone_windows_menu(self) -> None:
        """Without a system menu, a window's own Window menu lists the
        minimised windows."""
        self.manager.show_system_menu = False
        menu = Menu("Window", lists_minimised=True)
        front = Window("Front", Rect(2, 2, 8, 30), menus=[menu])
        hidden = Window("Hidden", Rect(3, 3, 8, 30))
        self.manager.add(hidden)
        self.manager.add(front)
        self.manager.minimise(hidden)
        self.manager.bar_menus()
        self.assertIn("Hidden", " ".join(item.label for item in menu.items))

    def test_actions_with_nothing_to_act_on(self) -> None:
        """A right-click off the workspace, resizing with no window, keeping
        a maximised window reachable, and calls after the desktop stopped
        do nothing."""
        self.manager._right_press(MouseEvent("press", "right", 0, 0))
        self.manager.start_resizing()
        self.assertIsNone(self.manager._adjust)
        window = Window("W", Rect(2, 2, 8, 30))
        window.maximise(Rect(40, 40, 5, 5))
        self.manager.keep_reachable(window)
        self.assertEqual(window.rect, Rect(40, 40, 5, 5))
        called: list[str] = []
        self.manager.call_from_thread(lambda: called.append("late"))
        self.manager._call_from_threads()
        self.assertEqual(called, [])


class PopupPlacementTests(unittest.TestCase):
    """Popups near the edges of the screen."""

    def test_near_the_bottom_it_opens_upwards(self) -> None:
        """A popup that would go off the bottom ends at the row asked for."""
        manager = PresentationManager()
        manager.handle_resize(80, 24)
        popup = Dialog("P", 10, 5)
        manager.place_popup(popup, 20, 5)
        self.assertEqual(popup.rect.bottom, 21)

    def test_no_room_for_suggestions(self) -> None:
        """With no row free above or below the box, nothing is suggested."""
        manager = Showing()
        manager.handle_resize(40, 5)
        window = Window("W", Rect(0, 0, 5, 40))
        box = window.add(AutoCompleteBox(0, 2, 20, suggestions=["alpha", "alps"]))
        manager.add(window)
        box.text = "al"
        self.assertIsNone(manager.suggest(box, box.matches()))
        self.assertEqual(manager.shown, [])


if __name__ == "__main__":
    unittest.main()
