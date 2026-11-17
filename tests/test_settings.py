"""Tests for Settings...: each page changes what the command line and the
settings files configure, shows the change at once, and saves it to the
usual file with OK or Apply; Cancel puts it back."""

# Settings... runs other dialogs (file dialogs, questions, a key to press)
# through its manager, so these tests answer them from a script.
# pylint: disable=protected-access

import json
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import cast
from unittest import mock

from dasha import install, registry, theme
from dasha.client import ClientManager
from dasha.dialog import Dialog
from dasha.filedialog import FileDialog
from dasha.hosting import AppServer
from dasha.manager import PresentationManager
from dasha.registry import AppEntry
from dasha.settings import (
    ColourDialog,
    InstallDialog,
    KeyDialog,
    SettingsDialog,
)
from dasha.shortcuts import DEFAULTS, Shortcuts
from dasha.style import RED, Rgb, Style
from dasha.terminal import Terminal
from dasha.widgets import Button, ComboBox, ListBox
from tests.support import hosted, isolated_home, pipe, without_styles
from tests.test_hosting import WELCOME, drain, of_type
from tests.test_manager import FakeTerminal

type Answer = Callable[[Dialog], str | None]
"""How a test answers a dialog: it may fill the dialog in, and returns the
answer."""


class Answering(PresentationManager):
    """A desktop that answers each dialog it is asked to show with the next
    of ``answers``, noting each dialog's title."""

    def __init__(self) -> None:
        super().__init__()
        self.answers: list[Answer] = []
        self.asked: list[str] = []

    def execute(self, dialog: Dialog) -> str | None:
        self.asked.append(dialog.title)
        return self.answers.pop(0)(dialog)


def press(dialog: Dialog, name: str) -> None:
    """Press one of a dialog's buttons."""
    button = dialog.widget(name)
    assert isinstance(button, Button)
    button.activate()


def choose(dialog: Dialog, name: str, item: str) -> None:
    """Choose an item in one of a dialog's combo boxes, as the user does."""
    box = dialog.widget(name)
    assert isinstance(box, ComboBox)
    box.choose(box.items.index(item))


def file_chosen(path: Path) -> Answer:
    """Answer a file dialog with a file."""

    def answer(dialog: Dialog) -> str:
        assert isinstance(dialog, FileDialog)
        dialog.path = str(path)
        return "ok"

    return answer


def answered(result: str) -> Answer:
    """Answer a dialog with this result, as a button of its would."""
    return lambda dialog: result


class Settings(unittest.TestCase):
    """A desktop whose settings files are in an empty folder."""

    def setUp(self) -> None:
        self.home = isolated_home(self)
        self.manager = Answering()
        self.manager.settings_path = self.home / "settings.toml"
        self.manager.colours_path = self.home / "colours.json"
        self.manager.shortcuts_path = self.home / "shortcuts.json"
        self.manager.themes_folder = self.home / "themes"
        self.manager.handle_resize(80, 24)

    def dialog(self) -> SettingsDialog:
        """Settings..., as it opens."""
        return SettingsDialog(self.manager)

    def settings(self) -> str:
        """What ``settings.toml`` holds."""
        path = self.manager.settings_path
        return path.read_text(encoding="utf-8") if path.exists() else ""


class OpeningTests(Settings):
    """Settings... in the system menu."""

    def test_in_the_system_menu(self) -> None:
        """Below About, opening the dialog."""
        labels = [item.label for item in self.manager.system_menu.items]
        self.assertEqual(labels[:2], ["&About", "S&ettings..."])
        item = self.manager.system_menu.items[1]
        assert item.action is not None
        self.manager.answers = [answered("cancel")]
        with mock.patch.object(Answering, "can_show_dialogs", True):
            item.action()
        self.assertEqual(self.manager.asked, ["Settings"])

    def test_from_the_keyboard(self) -> None:
        """F10 and E open it, Ctrl+PgDn turns to the Shortcuts page, and
        Escape closes it, changing nothing."""
        manager = PresentationManager()
        manager.settings_path = self.manager.settings_path
        keys = ["\x1b[21~", "e", "\x1b[6;5~", "\x1b", "", "\x11", "\r"]
        terminal = FakeTerminal(keys, sizes=[(80, 24)])
        manager.run(cast(Terminal, terminal))
        shown = without_styles(terminal.output.getvalue())
        self.assertIn("Settings", shown)
        self.assertIn("Theme", shown)
        self.assertIn("Action", shown)  # the Shortcuts page's heading
        self.assertEqual(terminal.inputs, [])
        self.assertFalse(manager.settings_path.exists())

    def test_fits_the_smallest_screen(self) -> None:
        """80 by 24: the dialog fits between the menu bar and status bar."""
        dialog = self.dialog()
        self.assertLessEqual(dialog.rect.height, self.manager.workspace.height)
        self.assertLessEqual(dialog.rect.width, 80)


class DoubleClickTests(Settings):
    """A double-click on an item in a list chooses it, which in a dialog
    otherwise presses OK; in Settings... it must not close the dialog."""

    def test_the_lists_keep_it_open(self) -> None:
        """Roles, start-up applications and installed applications: the
        dialog stays open, unanswered."""
        self.manager.register(AppEntry(id="notepad", name="Notepad", target="n.py"))
        dialog = self.dialog()
        for name in ("roles", "autostart", "applications"):
            with self.subTest(name=name):
                box = dialog.widget(name)
                assert isinstance(box, ListBox)
                box.choose()
                self.assertIsNone(dialog.result)
        self.assertEqual(self.manager.asked, [])

    def test_an_action_adds_a_key(self) -> None:
        """On the Shortcuts page, choosing an action asks for a key to add."""
        dialog = self.dialog()
        self.manager.answers = [answered("cancel")]
        dialog.shortcuts.table.choose()
        self.assertEqual(self.manager.asked, ["Add a key"])
        self.assertIsNone(dialog.result)


class AppearanceTests(Settings):
    """The theme, and the colours of each part of the screen."""

    def test_a_theme_shows_at_once(self) -> None:
        """Choosing Dark changes the colours at once; Cancel puts them back."""
        before = theme.current_theme()
        dialog = self.dialog()
        choose(dialog, "theme", "Dark")
        self.assertEqual(theme.current_theme(), theme.DARK_THEME)
        self.assertEqual(self.manager.theme_name, "dark")
        dialog.cancel()
        self.assertEqual(theme.current_theme(), before)
        self.assertEqual(self.manager.theme_name, "default")
        self.assertEqual(self.settings(), "")

    def test_ok_remembers_the_theme(self) -> None:
        """A theme chosen unchanged is remembered by name."""
        dialog = self.dialog()
        choose(dialog, "theme", "Dark")
        press(dialog, "ok")
        self.assertEqual(dialog.result, "ok")
        self.assertEqual(
            registry.read_theme_setting(self.manager.settings_path), "dark"
        )
        self.assertFalse(self.manager.colours_path.exists())  # type: ignore[union-attr]

    def test_a_colour_changed(self) -> None:
        """A role's colour changes at once, and OK keeps the colours in the
        colours file, which the desktop then starts with."""
        dialog = self.dialog()
        dialog.appearance.roles.move_to(list(theme.ROLES).index("window.body"))
        choose(dialog, "foreground", "red")
        style = theme.current_theme()["window.body"]
        assert isinstance(style, Style)
        self.assertEqual(style.foreground, RED)
        self.assertIn("Changed", dialog.appearance.note.text)
        press(dialog, "apply")
        saved = json.loads(self.home.joinpath("colours.json").read_text("utf-8"))
        self.assertEqual(saved["colours"]["window.body"]["foreground"], "red")
        self.assertIsNone(registry.read_theme_setting(self.manager.settings_path))
        self.assertIsNone(self.manager.theme_name)
        self.assertEqual(dialog.appearance.theme_box.selected_item, "Colours file")

    def test_no_shadow(self) -> None:
        """Only a shadow can be turned off."""
        dialog = self.dialog()
        roles = list(theme.ROLES)
        dialog.appearance.roles.move_to(roles.index("desktop"))
        self.assertFalse(dialog.appearance.no_shadow.is_enabled(0))
        dialog.appearance.roles.move_to(roles.index("window.shadow"))
        dialog.appearance.no_shadow.press(0)
        self.assertIsNone(theme.current_theme()["window.shadow"])

    def test_save_as_a_theme(self) -> None:
        """Saved in the themes folder, it is offered, and chosen, by name."""
        dialog = self.dialog()
        dialog.appearance.roles.move_to(list(theme.ROLES).index("desktop"))
        choose(dialog, "background", "blue")
        path = self.home / "themes" / "ocean.json"
        self.manager.answers = [file_chosen(path)]
        press(dialog, "save_theme")
        self.assertTrue(path.exists())
        self.assertEqual(dialog.appearance.choice, "ocean")
        self.assertFalse(dialog.appearance.edited)
        self.assertIn("ocean", dialog.appearance.theme_box.items)

    def test_load_a_theme(self) -> None:
        """A theme file from elsewhere: its colours, to keep as changed
        colours."""
        path = self.home / "elsewhere.json"
        path.write_text(theme.theme_to_json(theme.DARK_THEME, "dark"), "utf-8")
        dialog = self.dialog()
        self.manager.answers = [file_chosen(path)]
        press(dialog, "load_theme")
        self.assertEqual(theme.current_theme(), theme.DARK_THEME)
        self.assertTrue(dialog.appearance.edited)

    def test_a_theme_that_cannot_be_used(self) -> None:
        """Said, and the colours stay as they were."""
        path = self.home / "broken.json"
        path.write_text("{not json", "utf-8")
        before = theme.current_theme()
        dialog = self.dialog()
        self.manager.answers = [file_chosen(path), answered("ok")]
        press(dialog, "load_theme")
        self.assertEqual(self.manager.asked, ["Load a theme", "Themes"])
        self.assertEqual(theme.current_theme(), before)


class ShortcutsTests(Settings):
    """The keys of every action."""

    def select(self, dialog: SettingsDialog, action: str) -> None:
        """Highlight an action."""
        dialog.shortcuts.table.move_to(list(DEFAULTS).index(action))

    def test_a_key_added_works_at_once(self) -> None:
        """The key pressed is added, and works straight away."""
        dialog = self.dialog()
        self.select(dialog, "next_window")

        def press_f7(key_dialog: Dialog) -> str:
            assert isinstance(key_dialog, KeyDialog)
            key_dialog.handle_key("f7", self.manager.shortcuts)
            return str(key_dialog.result)

        self.manager.answers = [press_f7]
        press(dialog, "add_key")
        self.assertEqual(self.manager.shortcuts.keys("next_window"), ("f6", "f7"))
        self.assertEqual(self.manager.menu_bar.shortcuts, self.manager.shortcuts)
        press(dialog, "ok")
        saved = json.loads(self.home.joinpath("shortcuts.json").read_text("utf-8"))
        self.assertEqual(saved, {"next_window": ["f6", "f7"]})

    def test_every_key_counts(self) -> None:
        """Escape and Enter are keys to add, not answers."""
        key_dialog = KeyDialog("exit")
        self.assertTrue(key_dialog.handle_key("escape", Shortcuts()))
        self.assertEqual((key_dialog.key, key_dialog.result), ("escape", "ok"))

    def test_no_way_out_is_refused(self) -> None:
        """Taking every key from both exit and open_menu is refused, saying
        why."""
        dialog = self.dialog()
        self.select(dialog, "exit")
        press(dialog, "remove_keys")
        self.assertEqual(self.manager.shortcuts.keys("exit"), ())
        self.select(dialog, "open_menu")
        self.manager.answers = [answered("ok")]
        press(dialog, "remove_keys")
        self.assertEqual(self.manager.asked, ["Shortcuts"])
        self.assertEqual(
            self.manager.shortcuts.keys("open_menu"), DEFAULTS["open_menu"]
        )

    def test_default_and_reset_all(self) -> None:
        """Default puts one action's keys back, and Reset all every one's."""
        dialog = self.dialog()
        self.select(dialog, "exit")
        press(dialog, "remove_keys")
        press(dialog, "default")
        self.assertEqual(self.manager.shortcuts.keys("exit"), ("ctrl+q",))
        press(dialog, "remove_keys")
        press(dialog, "reset_all")
        self.assertEqual(self.manager.shortcuts.bindings, DEFAULTS)

    def test_cancel_puts_them_back(self) -> None:
        """Cancel puts the keys back, and saves nothing."""
        before = self.manager.shortcuts
        dialog = self.dialog()
        self.select(dialog, "exit")
        press(dialog, "remove_keys")
        press(dialog, "cancel")
        self.assertEqual(dialog.result, "cancel")
        self.assertIs(self.manager.shortcuts, before)
        self.assertFalse(self.home.joinpath("shortcuts.json").exists())

    def test_menu_modifiers_are_chosen(self) -> None:
        """A modifier for the menus' letters is chosen, not pressed."""
        dialog = self.dialog()
        self.select(dialog, "menu_mnemonic_modifiers")
        self.manager.answers = [answered("ctrl")]
        press(dialog, "add_key")
        self.assertIn("ctrl", self.manager.shortcuts.keys("menu_mnemonic_modifiers"))

    def test_save_as_and_load(self) -> None:
        """Saved elsewhere, a file holds only what differs from the
        defaults, and loading it brings the keys back."""
        dialog = self.dialog()
        self.select(dialog, "exit")
        press(dialog, "remove_keys")
        path = self.home / "mine.json"
        self.manager.answers = [file_chosen(path)]
        press(dialog, "save_shortcuts")
        self.assertEqual(json.loads(path.read_text("utf-8")), {"exit": []})
        press(dialog, "reset_all")
        self.manager.answers = [file_chosen(path)]
        press(dialog, "load_shortcuts")
        self.assertEqual(self.manager.shortcuts.keys("exit"), ())

    def test_applications_are_told(self) -> None:
        """An application in its own process takes the new keys at once."""
        self.manager.server = AppServer(self.manager)
        self.addCleanup(self.manager.server.stop_all, 0)
        _, app_end = hosted(self.manager.server, "Editor")
        client_end, desktop_end = pipe()
        self.addCleanup(desktop_end.close)
        client = ClientManager(client_end, WELCOME)
        dialog = self.dialog()
        self.select(dialog, "exit")
        press(dialog, "remove_keys")
        message = of_type(drain(app_end), "shortcuts")[-1]
        client.handle(message)
        self.assertEqual(client.shortcuts.keys("exit"), ())
        self.assertEqual(client.menu_bar.shortcuts.keys("exit"), ())


class CustomColourTests(Settings):
    """Custom... in the foreground and background boxes: an RGB colour."""

    def body(self) -> Style:
        """The window body's colours, as they are now."""
        found = theme.current_theme()["window.body"]
        assert isinstance(found, Style)
        return found

    def test_a_custom_colour(self) -> None:
        """Typed in, it is used at once, offered in the box, and kept in the
        colours file as #rrggbb."""
        dialog = self.dialog()
        dialog.appearance.roles.move_to(list(theme.ROLES).index("window.body"))

        def typed(asked: Dialog) -> str:
            assert isinstance(asked, ColourDialog)
            asked.text.text = "#FF8800"
            asked._typed()
            self.assertEqual([box.value for box in asked.parts], [255, 136, 0])
            press(asked, "ok")
            return asked.result or ""

        self.manager.answers = [typed]
        choose(dialog, "background", "Custom...")
        self.assertEqual(self.manager.asked, ["Custom colour"])
        self.assertEqual(self.body().background, Rgb(255, 136, 0))
        box = dialog.appearance.background
        self.assertEqual(box.selected_item, "#ff8800")
        self.assertEqual(box.items[-1], "Custom...")
        press(dialog, "ok")
        saved = json.loads(self.home.joinpath("colours.json").read_text("utf-8"))
        self.assertEqual(saved["colours"]["window.body"]["background"], "#ff8800")

    def test_cancelled(self) -> None:
        """Cancel leaves the colour as it was."""
        dialog = self.dialog()
        before = self.body()
        dialog.appearance.roles.move_to(list(theme.ROLES).index("window.body"))
        shown = dialog.appearance.foreground.selected_item
        self.manager.answers = [answered("cancel")]
        choose(dialog, "foreground", "Custom...")
        self.assertEqual(self.body(), before)
        self.assertEqual(dialog.appearance.foreground.selected_item, shown)
        self.assertFalse(dialog.appearance.edited)

    def test_the_parts_set_the_text(self) -> None:
        """Red, green and blue make the #rrggbb, and OK refuses text that
        is not a colour, saying why."""
        asked = ColourDialog(Rgb(1, 2, 3))
        self.assertEqual(asked.text.text, "#010203")
        asked.parts[0].set(255)
        self.assertEqual(asked.text.text, "#ff0203")
        self.assertEqual(asked.swatch.style, Style(foreground=Rgb(255, 2, 3)))
        asked.text.text = "#ff02"
        press(asked, "ok")
        self.assertIsNone(asked.result)
        self.assertIn("six digits", asked.problem.text)


class DesktopTests(Settings):
    """Animations, and the applications to start with the desktop."""

    def setUp(self) -> None:
        super().setUp()
        self.manager.register(
            [
                AppEntry(id="notepad", name="Notepad", target="notepad.py"),
                AppEntry(id="demo", name="Demo", target="demo.py"),
            ]
        )

    def test_animations(self) -> None:
        """On or off at once; OK keeps the choice."""
        self.manager.animations = True
        dialog = self.dialog()
        dialog.desktop.animations.set(False)
        self.assertFalse(self.manager.animations)
        press(dialog, "ok")
        self.assertIn("animations = false", self.settings())

    def test_autostart(self) -> None:
        """The applications chosen start with the desktop next time."""
        dialog = self.dialog()
        self.assertEqual(dialog.desktop.autostart.items, ["Demo", "Notepad"])
        dialog.desktop.autostart.toggle(1)
        press(dialog, "ok")
        self.assertEqual(
            registry.read_autostart(self.manager.settings_path), ["notepad"]
        )
        dialog = self.dialog()
        self.assertEqual(dialog.desktop.chosen, ["notepad"])
        dialog.desktop.autostart.toggle(1)
        press(dialog, "ok")
        self.assertNotIn("autostart", self.settings())

    def test_colour_depth(self) -> None:
        """Changes how colours are drawn at once; OK keeps it, and Cancel
        puts it back."""
        dialog = self.dialog()
        self.assertEqual(dialog.desktop.depth.selected_item, "Automatic")
        choose(dialog, "colour_depth", "16 colours (CGA)")
        self.assertEqual(self.manager.colour_depth, "16")
        self.assertEqual(Style(foreground=200).sgr(), "\x1b[0;95m")
        choose(dialog, "colour_depth", "256 colours")
        self.assertEqual(self.manager.colour_depth, "256")
        self.assertIn(";5;", Style(foreground=Rgb(255, 0, 0)).sgr())
        dialog.cancel()
        self.assertEqual(self.manager.colour_depth, "auto")
        dialog = self.dialog()
        choose(dialog, "colour_depth", "24-bit colour")
        self.assertIn(";2;", Style(foreground=Rgb(255, 0, 0)).sgr())
        press(dialog, "ok")
        self.assertIn('colour_depth = "24bit"', self.settings())

    def test_escape_wait(self) -> None:
        """How long Escape waits for a key changes at once; OK keeps it,
        and Cancel puts it back."""
        dialog = self.dialog()
        self.assertEqual(dialog.desktop.escape_wait.value, 100)
        dialog.desktop.escape_wait.set(300)
        self.assertEqual(self.manager.escape_timeout, 0.3)
        dialog.cancel()
        self.assertEqual(self.manager.escape_timeout, 0.1)
        self.assertEqual(self.settings(), "")
        dialog = self.dialog()
        dialog.desktop.escape_wait.set(300)
        press(dialog, "ok")
        self.assertIn("escape_timeout = 300", self.settings())

    def test_show_the_mouse(self) -> None:
        """On or off at once; OK keeps it, and Cancel puts it back."""
        dialog = self.dialog()
        self.assertFalse(dialog.desktop.show_mouse.on)
        dialog.desktop.show_mouse.set(True)
        self.assertTrue(self.manager.show_mouse)
        dialog.cancel()
        self.assertFalse(self.manager.show_mouse)
        self.assertEqual(self.settings(), "")
        dialog = self.dialog()
        dialog.desktop.show_mouse.set(True)
        press(dialog, "ok")
        self.assertIn("show_mouse = true", self.settings())

    def test_nothing_changed_writes_nothing(self) -> None:
        """OK with nothing changed leaves the settings file alone."""
        press(self.dialog(), "ok")
        self.assertFalse(self.manager.settings_path.exists())


class ApplicationsTests(Settings):
    """Installing and uninstalling, at once."""

    def install(
        self, dialog: SettingsDialog, script: Path, name: str, *then: Answer
    ) -> None:
        """Install a script, with a name, through Install..., answering any
        dialogs that follow with ``then``."""

        def fill(asked: Dialog) -> str | None:
            assert isinstance(asked, InstallDialog)
            asked.program.text = str(script)
            asked.name_box.text = name
            asked.group_box.text = "Games"
            asked.accept()
            return asked.result

        self.manager.answers = [fill, *then]
        press(dialog, "install")

    def test_install_and_uninstall(self) -> None:
        """Installed: its manifest written, offered in the Applications
        menu and to start with the desktop; uninstalled: all of that
        undone."""
        script = self.home / "snake.py"
        script.write_text("", "utf-8")
        dialog = self.dialog()
        self.install(dialog, script, "Snake")
        manifest = self.home / "apps" / "snake.toml"
        entry = registry.read_manifest(manifest)
        self.assertEqual((entry.name, entry.group), ("Snake", "Games"))
        self.assertIn("snake", self.manager.registry)
        self.assertEqual(
            dialog.applications.table.data[0][:3], ["snake", "Snake", "Games"]
        )
        self.assertEqual(dialog.desktop.autostart.items, ["Snake"])
        self.manager.answers = [answered("uninstall")]
        press(dialog, "uninstall")
        self.assertFalse(manifest.exists())
        self.assertNotIn("snake", self.manager.registry)
        self.assertEqual(dialog.applications.table.data, [])

    def test_replacing_asks_first(self) -> None:
        """An application of the same id is replaced only once agreed."""
        script = self.home / "snake.py"
        script.write_text("", "utf-8")
        dialog = self.dialog()
        self.install(dialog, script, "Snake")
        manifest = self.home / "apps" / "snake.toml"
        kept = "# kept\n"
        manifest.write_text(manifest.read_text("utf-8") + kept, "utf-8")
        self.install(dialog, script, "Snake", answered("cancel"))
        self.assertEqual(self.manager.asked, ["Install", "Install", "Install"])
        self.assertTrue(manifest.read_text("utf-8").endswith(kept))
        self.install(dialog, script, "Snake", answered("ok"))
        self.assertFalse(manifest.read_text("utf-8").endswith(kept))

    def test_a_module_that_cannot_be_imported(self) -> None:
        """Said, and nothing installed."""
        dialog = self.dialog()

        def fill(asked: Dialog) -> str | None:
            assert isinstance(asked, InstallDialog)
            asked.program.text = "no_such_module_here:App"
            asked.accept()
            return asked.result

        self.manager.answers = [fill, answered("ok")]
        press(dialog, "install")
        self.assertEqual(self.manager.asked, ["Install", "Install"])
        self.assertFalse((self.home / "apps").exists())

    def test_never_called_desktop(self) -> None:
        """A name that would make the id desktop, which dasha desktop means,
        is said to be refused, and nothing installed."""
        script = self.home / "desktop.py"
        script.write_text("", "utf-8")
        dialog = self.dialog()
        self.install(dialog, script, "Desktop", answered("ok"))
        self.assertEqual(self.manager.asked, ["Install", "Install"])
        self.assertFalse((self.home / "apps").exists())
        self.assertNotIn("desktop", self.manager.registry)


class RemoveApplicationTests(Settings):
    """install.remove_application, shared with dasha uninstall-app."""

    def test_unknown(self) -> None:
        """An id that is not installed, or not an id at all."""
        with self.assertRaises(registry.ManifestError):
            install.remove_application("../outside")


if __name__ == "__main__":
    unittest.main()
