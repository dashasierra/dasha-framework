"""Tests for showing the mouse: with ``show_mouse`` on, the cell under the
mouse is drawn inverted. Its key (Alt+` by default) turns it on and off
wherever the focus is, and the choice is remembered in ``settings.toml``."""

import unittest

from dasha import registry
from dasha.canvas import Canvas
from dasha.dialog import information
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.registry import (
    ManifestError,
    read_show_mouse_setting,
    save_show_mouse_setting,
)
from dasha.settings import KeyDialog
from dasha.shortcuts import DEFAULTS
from tests.support import isolated_home, started_desktop


def moved(row: int, column: int) -> MouseEvent:
    """The mouse moving there, with no button held down."""
    return MouseEvent(action="move", button="none", row=row, column=column)


class ShownTests(unittest.TestCase):
    """The cell under the mouse, on the screen."""

    def setUp(self) -> None:
        self.home = isolated_home(self)
        self.manager = PresentationManager()
        self.manager.settings_path = self.home / "settings.toml"
        self.manager.handle_resize(80, 24)

    def screen(self) -> Canvas:
        """The screen as the desktop draws it now."""
        canvas = Canvas(80, 24)
        self.manager.compose(canvas)
        return canvas

    def test_off_by_default(self) -> None:
        """Nothing is inverted."""
        before = self.screen().cell(5, 10)
        self.manager.handle_event(moved(5, 10))
        self.assertFalse(self.manager.show_mouse)
        self.assertEqual(self.screen().cell(5, 10), before)

    def test_inverted(self) -> None:
        """The cell under the mouse, and only that cell, is inverted; it
        follows the mouse."""
        plain = self.screen()
        self.manager.show_mouse = True
        self.manager.handle_event(moved(5, 10))
        shown = self.screen()
        char, style = shown.cell(5, 10)
        self.assertEqual(char, plain.cell(5, 10)[0])
        self.assertEqual(style.reverse, not plain.cell(5, 10)[1].reverse)
        self.assertEqual(shown.cell(5, 11), plain.cell(5, 11))
        self.manager.handle_event(moved(0, 0))  # over the menu bar too
        shown = self.screen()
        self.assertEqual(shown.cell(5, 10), plain.cell(5, 10))
        self.assertNotEqual(shown.cell(0, 0), plain.cell(0, 0))

    def test_the_key(self) -> None:
        """Alt+` turns it on and off, remembering the choice."""
        self.assertEqual(DEFAULTS["show_mouse"], ("alt+`",))
        self.manager.remember_show_mouse = True
        self.manager.handle_event("alt+`")
        self.assertTrue(self.manager.show_mouse)
        self.assertTrue(read_show_mouse_setting(self.manager.settings_path))
        self.manager.handle_event("alt+`")
        self.assertFalse(self.manager.show_mouse)
        self.assertFalse(read_show_mouse_setting(self.manager.settings_path))

    def test_in_a_dialog(self) -> None:
        """The key works while a dialog waits for an answer, and the mouse
        is followed there too, but a dialog asking for a key gets it."""
        dialog = information("Note", "Hello")
        self.manager.handle_modal_event(dialog, moved(3, 4))
        self.manager.handle_modal_event(dialog, "alt+`")
        self.assertTrue(self.manager.show_mouse)
        at = self.manager._mouse_at  # pylint: disable=protected-access
        self.assertEqual(at, (3, 4))
        asking = KeyDialog("exit")
        self.manager.handle_modal_event(asking, "alt+`")
        self.assertTrue(self.manager.show_mouse)
        self.assertEqual(asking.key, "alt+`")


class SettingTests(unittest.TestCase):
    """``show_mouse`` in ``settings.toml``, and ``--show-mouse``."""

    def setUp(self) -> None:
        self.home = isolated_home(self)
        self.path = self.home / "settings.toml"

    def test_read_and_saved(self) -> None:
        """Off unless the file says otherwise; off is never written."""
        self.assertFalse(read_show_mouse_setting(self.path))
        save_show_mouse_setting(True, self.path)
        self.assertEqual(self.path.read_text("utf-8"), "show_mouse = true\n")
        self.assertTrue(read_show_mouse_setting(self.path))
        save_show_mouse_setting(False, self.path)
        self.assertEqual(self.path.read_text("utf-8"), "")

    def test_refused(self) -> None:
        """Only true or false."""
        self.path.write_text('show_mouse = "yes"\n', encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "show_mouse"):
            read_show_mouse_setting(self.path)

    def started_with(self, *arguments: str) -> bool:
        """Whether the desktop started by the command line shows the
        mouse."""
        code, desktop, _ = started_desktop(*arguments)
        self.assertEqual(code, 0)
        return bool(desktop.call_args.kwargs["show_mouse"])

    def test_the_command_line(self) -> None:
        """--show-mouse, or settings.toml, turns it on."""
        self.assertFalse(self.started_with())
        save_show_mouse_setting(True, registry.SETTINGS_PATH)
        self.assertTrue(self.started_with())
        save_show_mouse_setting(False, registry.SETTINGS_PATH)
        self.assertTrue(self.started_with("--show-mouse"))

    def test_the_command_line_is_remembered(self) -> None:
        """-m (--show-mouse) is kept in settings.toml for next time; the
        key, or Settings..., turns it off again."""
        self.assertTrue(self.started_with("-m"))
        self.assertTrue(read_show_mouse_setting(registry.SETTINGS_PATH))
        self.assertTrue(self.started_with())

    def test_the_desktop_remembers(self) -> None:
        """The desktop the command line makes remembers the key's choice."""
        # pylint: disable=import-outside-toplevel
        from dasha.__main__ import _desktop

        manager = _desktop(None, [], processes=False, entries={})
        manager.settings_path = self.path
        self.assertFalse(manager.show_mouse)
        manager.handle_event("alt+`")
        self.assertTrue(read_show_mouse_setting(self.path))


if __name__ == "__main__":
    unittest.main()
