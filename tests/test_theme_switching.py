"""Tests for changing theme while running."""

import json
import os
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from dasha import registry, theme
from dasha.__main__ import main
from dasha.canvas import Canvas, Rect
from dasha.client import ClientManager
from dasha.dialog import Dialog, MenuPopup
from dasha.hosting import AppHost, AppServer
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuItem
from dasha.registry import read_theme_setting, save_theme_setting
from dasha.remote import RemoteWindow
from dasha.settings import SettingsDialog
from dasha.window import Window
from tests.hosted_apps import Hello
from tests.support import hosted, pipe
from tests.test_hosting import WELCOME, drain, of_type
from tests.test_theme import ThemeIsolation
from tests.test_waiting_dialogs import state

OCEAN = {"base": "dark", "colours": {"window.body": {"background": "blue"}}}


class Folder(ThemeIsolation):
    """A themes folder with an ``ocean`` theme, and a settings file."""

    def setUp(self) -> None:
        super().setUp()
        directory = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.folder = self.root / "themes"
        self.folder.mkdir()
        self.write("ocean", OCEAN)
        self.settings = self.root / "settings.toml"

    def write(self, name: str, data: object) -> Path:
        """Write a theme file in the folder.

        :param name: File name.
        :param data: Its JSON contents.
        """
        path = self.folder / f"{name}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def desktop(self) -> PresentationManager:
        """A desktop using the folder and the settings file."""
        manager = PresentationManager()
        manager.handle_resize(80, 24)
        manager.themes_folder = self.folder
        manager.settings_path = self.settings
        manager.colours_path = self.root / "colours.json"
        return manager


class ThemeFilesTests(Folder):
    """Finding themes: built in, in the folder, or at a path."""

    def test_names(self) -> None:
        """Theme names."""
        self.write("default", {})
        self.write("aaa", {})
        self.assertEqual(
            theme.theme_names(self.folder),
            ["default", "dark", "monochrome", "aaa", "ocean"],
        )
        self.assertEqual(theme.theme_names(self.root / "none"), list(theme.BASES))

    def test_loading(self) -> None:
        """Loading themes."""
        self.assertEqual(theme.load_named_theme("dark", self.folder), theme.DARK_THEME)
        ocean = theme.load_named_theme("ocean", self.folder)
        self.assertEqual(ocean["window.body"].background, 4)  # type: ignore[union-attr]
        self.assertEqual(ocean["dialog.body"], theme.DARK_THEME["dialog.body"])
        by_path = theme.load_named_theme(self.folder / "ocean.json")
        self.assertEqual(by_path, ocean)
        self.assertEqual(theme.load_named_theme(str(self.folder / "ocean.json")), ocean)
        with self.assertRaisesRegex(theme.ThemeError, 'no theme "sepia"'):
            theme.load_named_theme("sepia", self.folder)
        self.write("broken", {"colours": {"nope": {}}})
        with self.assertRaisesRegex(theme.ThemeError, "unknown role"):
            theme.load_named_theme("broken", self.folder)

    def test_dark_has_every_role(self) -> None:
        """Dark is a whole theme: light text on black and dark grey."""
        self.assertEqual(set(theme.DARK_THEME), set(theme.DEFAULT_THEME))
        body = theme.DARK_THEME["window.body"]
        self.assertEqual((body.foreground, body.background), (7, 0))  # type: ignore[union-attr]


class SwitchingTests(Folder):
    """``set_theme`` while running: everything takes it on at once."""

    def test_every_window_takes_it_on(self) -> None:
        """Windows, and the whole screen drawn afresh."""
        manager = self.desktop()
        manager.add(Window("W", Rect(2, 2, 6, 30)))
        canvas = Canvas(80, 24)
        manager.compose(canvas)
        self.assertTrue(manager.set_theme("dark"))
        self.assertEqual(Window.body_style, theme.DARK_THEME["window.body"])
        self.assertEqual(manager.theme_name, "dark")
        manager.compose(canvas)
        self.assertEqual(canvas.cell(3, 5)[1], theme.DARK_THEME["window.body"])
        self.assertIsNone(manager._on_screen)  # pylint: disable=protected-access

    def test_a_theme_that_is_not_there(self) -> None:
        """Nothing changes; it says no."""
        manager = self.desktop()
        before = theme.current_theme()
        self.assertFalse(manager.set_theme("sepia"))
        self.assertEqual(theme.current_theme(), before)
        self.assertEqual(manager.theme_name, "default")

    def test_copies_of_styles_follow(self) -> None:
        """Copies of styles follow."""
        manager = self.desktop()
        server = AppServer(manager)
        self.addCleanup(server.stop_all, 0)
        manager.server = server
        host = AppHost(server, "x:Y", "App")
        server.hosts.append(host)  # so that stop_all ends it
        _, desktop_end = pipe()
        host.connected(desktop_end)
        host.handle(state(look="dialog", modal=True))
        remote = host.windows[1]
        assert isinstance(remote, RemoteWindow)
        popup = MenuPopup(Menu("M", [MenuItem("&A", lambda: None)]))
        manager.add(popup)
        manager.set_theme("dark")
        self.assertEqual(remote.body_style, Dialog.body_style)
        self.assertEqual(remote.body_style, theme.DARK_THEME["dialog.body"])
        self.assertEqual(popup.body_style, theme.DARK_THEME["menu.bar"])

    def test_from_an_application(self) -> None:
        """From an application."""
        manager = self.desktop()
        app = manager.launch(Hello)
        self.assertTrue(app.set_theme("dark"))
        self.assertEqual(manager.theme_name, "dark")
        self.assertFalse(Hello().set_theme("dark"))

    def test_remembered_only_when_asked(self) -> None:
        """Remembered only when asked."""
        manager = self.desktop()
        manager.set_theme("dark")
        self.assertFalse(self.settings.exists())
        manager.remember_theme = True
        manager.set_theme("ocean")
        self.assertEqual(read_theme_setting(self.settings), "ocean")
        manager.set_theme("dark", remember=False)
        self.assertEqual(read_theme_setting(self.settings), "ocean")


class MenuTests(Folder):
    """The system menu's Themes."""

    def themes(self, manager: PresentationManager) -> Menu:
        """The Themes submenu, as opened.

        :param manager: The desktop.
        """
        item = next(i for i in manager.system_menu.items if i.label == "&Themes")
        assert item.submenu is not None and item.submenu.on_open is not None
        item.submenu.on_open(item.submenu)
        return item.submenu

    def test_lists_and_marks(self) -> None:
        """Lists and marks."""
        manager = self.desktop()
        labels = [item.label for item in self.themes(manager).items]
        self.assertEqual(
            labels, ["\N{SQUARE ROOT} &Default", "  D&ark", "  &Monochrome", "  ocean"]
        )
        self.write("forest", {})
        manager.set_theme("ocean")
        labels = [item.label for item in self.themes(manager).items]
        self.assertEqual(labels[3:], ["  forest", "\N{SQUARE ROOT} ocean"])

    def test_choosing_one(self) -> None:
        """Choosing an item changes the theme, through the menu bar too."""
        manager = self.desktop()
        menu = self.themes(manager)
        dark = next(item for item in menu.items if "D&ark" in item.label)
        assert dark.action is not None
        dark.action()
        self.assertEqual(manager.theme_name, "dark")
        manager.handle_event("f10")
        for key in ("down", "down", "right"):  # Themes, opened by the menu bar
            manager.handle_event(key)
        self.assertIn("\N{SQUARE ROOT} D&ark", [i.label for i in menu.items])

    def test_each_has_a_letter_of_its_own(self) -> None:
        """Each has a letter of its own."""
        manager = self.desktop()
        assert manager.colours_path is not None
        manager.colours_path.write_text(json.dumps(OCEAN), encoding="utf-8")
        self.write("&a", {})
        menu = self.themes(manager)
        menu.check_mnemonics()
        self.assertEqual(menu.mnemonics(), ["d", "a", "m", None, None, None, "c"])
        self.assertEqual(menu.items[3].label, "  &&a")

    def test_the_colours_file(self) -> None:
        """The colours file."""
        manager = self.desktop()
        manager.remember_theme = True
        self.assertNotIn(
            "&Colours file", str([i.label for i in self.themes(manager).items])
        )
        assert manager.colours_path is not None
        manager.colours_path.write_text(json.dumps(OCEAN), encoding="utf-8")
        manager.set_theme("dark")
        item = self.themes(manager).items[-1]
        self.assertEqual(item.label, "  &Colours file")
        assert item.action is not None
        item.action()
        self.assertIsNone(manager.theme_name)
        self.assertEqual(Window.body_style.background, 4)
        self.assertIsNone(read_theme_setting(self.settings))


class ApplicationsTests(Folder):
    """Applications in processes of their own."""

    def setUp(self) -> None:
        super().setUp()
        self.manager = self.desktop()
        self.server = AppServer(self.manager)
        self.addCleanup(self.server.stop_all, 0)
        self.manager.server = self.server
        self.hosts = [hosted(self.server, "Back"), hosted(self.server, "Front")]

    def test_every_application_is_given_it(self) -> None:
        """The theme, and its name, to each."""
        self.manager.set_theme("dark")
        for _, end in self.hosts:
            sent = of_type(drain(end), "theme")
            self.assertEqual(sent[0]["name"], "dark")
            colours = theme.build_theme(json.loads(sent[0]["theme"]))
            self.assertEqual(colours, theme.DARK_THEME)

    def test_the_active_application_may_ask(self) -> None:
        """Only the one the user is working in."""
        (back, _), (front, _) = self.hosts
        back.handle({"type": "theme", "name": "dark"})
        self.assertEqual(self.manager.theme_name, "default")
        front.handle({"type": "theme", "name": str(self.folder / "ocean.json")})
        self.assertEqual(self.manager.theme_name, str(self.folder / "ocean.json"))


class NoColourTests(Folder):
    """With ``NO_COLOR`` set."""

    def setUp(self) -> None:
        super().setUp()
        patch = mock.patch.dict(os.environ, {"NO_COLOR": "1"})
        patch.start()
        self.addCleanup(patch.stop)
        self.manager = self.desktop()
        self.manager.remember_theme = True
        save_theme_setting("ocean", self.settings)
        self.manager.use_starting_theme()

    def themes_item(self) -> MenuItem:
        """The system menu's Themes."""
        return next(i for i in self.manager.system_menu.items if i.label == "&Themes")

    def test_it_starts_and_stays_monochrome(self) -> None:
        """It starts and stays monochrome."""
        manager = self.manager
        self.assertTrue(manager.colours_locked)
        self.assertEqual(manager.theme_name, "monochrome")
        self.assertFalse(manager.set_theme("dark"))
        self.assertFalse(manager.set_theme(self.folder / "ocean.json"))
        self.assertEqual(theme.current_theme(), theme.MONOCHROME_THEME)
        self.assertFalse(theme.has_colours())
        self.assertTrue(manager.set_theme("monochrome"))
        self.assertEqual(read_theme_setting(self.settings), "ocean")

    def test_nor_any_colours_put_on_the_screen(self) -> None:
        """No colours put on the screen."""
        self.manager.use_theme(theme.DARK_THEME, "dark")
        self.assertEqual(theme.current_theme(), theme.MONOCHROME_THEME)
        self.assertEqual(self.manager.theme_name, "monochrome")

    def test_the_themes_menu_is_greyed_out(self) -> None:
        """Themes cannot be opened while NO_COLOR is set, and can after."""
        self.assertFalse(self.themes_item().is_available)
        with mock.patch.dict(os.environ, {"NO_COLOR": ""}):
            self.assertTrue(self.themes_item().is_available)

    def test_an_application_cannot_change_it(self) -> None:
        """An application cannot change it."""
        app = self.manager.launch(Hello)
        self.assertFalse(app.set_theme("dark"))
        server = AppServer(self.manager)
        self.addCleanup(server.stop_all, 0)
        self.manager.server = server
        host, _ = hosted(server, "Front")
        host.handle({"type": "theme", "name": "dark"})
        self.assertEqual(self.manager.theme_name, "monochrome")
        self.assertFalse(theme.has_colours())
        with mock.patch.dict(os.environ, {"NO_COLOR": ""}):
            host.handle({"type": "theme", "name": "dark"})  # as it would
        self.assertEqual(self.manager.theme_name, "dark")

    def test_settings_appearance_page_cannot_be_chosen(self) -> None:
        """Settings... opens on Shortcuts, with Appearance greyed out."""
        dialog = SettingsDialog(self.manager)
        tabs = dialog.tabs
        self.assertFalse(tabs.is_enabled(0))
        self.assertEqual(tabs.selected, 1)
        tabs.select(0)
        tabs.activate_mnemonic("a")
        self.assertEqual(tabs.selected, 1)
        with mock.patch.dict(os.environ, {"NO_COLOR": ""}):
            self.assertTrue(SettingsDialog(self.manager).tabs.is_enabled(0))

    def test_monochrome_alone_holds_nothing(self) -> None:
        """Monochrome alone holds nothing."""
        with mock.patch.dict(os.environ, {"NO_COLOR": ""}):
            self.assertTrue(self.manager.set_theme("monochrome"))
            self.assertFalse(self.manager.colours_locked)
            self.assertTrue(self.themes_item().is_available)
            self.assertTrue(self.manager.set_theme("dark"))
            self.assertEqual(theme.current_theme(), theme.DARK_THEME)


class ClientTests(ThemeIsolation):
    """The application's side."""

    def setUp(self) -> None:
        super().setUp()
        self.desktop, app_end = pipe()
        self.manager = ClientManager(app_end, {**WELCOME, "theme_name": "dark"})
        self.addCleanup(self.manager.stop_listening)
        self.manager.launch(Hello)

    def test_asks_the_desktop(self) -> None:
        """Asks the desktop."""
        self.assertEqual(self.manager.theme_name, "dark")
        self.manager.set_theme("ocean")
        self.manager.set_theme(Path("themes/ocean.json"))
        sent = of_type(drain(self.desktop), "theme")
        self.assertEqual(sent[0]["name"], "ocean")
        self.assertEqual(Path(sent[1]["name"]), Path("themes/ocean.json").resolve())

    def test_takes_the_desktops(self) -> None:
        """A theme from the desktop is put on at once."""
        colours = theme.theme_to_json(theme.DARK_THEME)
        self.manager.handle({"type": "theme", "theme": colours, "name": "dark"})
        self.assertEqual(Window.body_style, theme.DARK_THEME["window.body"])


class SettingsTests(Folder):
    """``theme`` in ``settings.toml``."""

    def test_only_its_line_changes(self) -> None:
        """Comments and other settings stay; forgetting takes the line out."""
        self.settings.write_text('# mine\nautostart = ["notepad"]\n', encoding="utf-8")
        save_theme_setting("dark", self.settings)
        save_theme_setting("ocean", self.settings)
        text = self.settings.read_text(encoding="utf-8")
        self.assertIn("# mine", text)
        self.assertEqual(text.count("theme ="), 1)
        self.assertEqual(read_theme_setting(self.settings), "ocean")
        self.assertEqual(registry.read_autostart(self.settings), ["notepad"])
        save_theme_setting(None, self.settings)
        self.assertIsNone(read_theme_setting(self.settings))
        self.assertEqual(registry.read_autostart(self.settings), ["notepad"])

    def test_not_a_name(self) -> None:
        """Not a name."""
        self.settings.write_text("theme = 3\n", encoding="utf-8")
        with self.assertRaises(registry.ManifestError):
            read_theme_setting(self.settings)


class StartingTests(Folder):
    """Starting with the theme chosen last."""

    def run_main(self, *args: str) -> tuple[int, str, str]:
        """Run main; return exit code, stdout and stderr.

        :param args: Command-line arguments.
        """
        out, err = StringIO(), StringIO()
        with (
            mock.patch.object(registry, "SETTINGS_PATH", self.settings),
            mock.patch.object(theme, "THEMES_FOLDER", self.folder),
            mock.patch.object(theme, "DEFAULT_PATH", self.root / "colours.json"),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_the_remembered_theme(self) -> None:
        """Used to start with, unless --colours or --monochrome say otherwise."""
        save_theme_setting("ocean", self.settings)
        self.run_main("--key-test")
        self.assertEqual(Window.body_style.background, 4)
        (self.root / "mine.json").write_text("{}", encoding="utf-8")
        self.run_main("--colours", str(self.root / "mine.json"), "--key-test")
        self.assertEqual(theme.current_theme(), theme.DEFAULT_THEME)
        self.run_main("--monochrome", "--key-test")
        self.assertEqual(theme.current_theme(), theme.MONOCHROME_THEME)

    def test_no_colour_comes_before_the_remembered_theme(self) -> None:
        """``NO_COLOR`` comes before the remembered theme."""
        save_theme_setting("ocean", self.settings)
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.run_main("--key-test")
        self.assertEqual(theme.current_theme(), theme.MONOCHROME_THEME)
        self.assertEqual(read_theme_setting(self.settings), "ocean")

    def test_no_colour_comes_before_any_colours_file(self) -> None:
        """``NO_COLOR`` comes before any colours file."""
        mine = self.root / "mine.json"
        mine.write_text('{"base": "dark"}', encoding="utf-8")
        (self.root / "colours.json").write_text('{"base": "dark"}', encoding="utf-8")
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.run_main("--colours", str(mine), "--key-test")
            self.assertEqual(theme.current_theme(), theme.MONOCHROME_THEME)
            self.run_main("--key-test")
            self.assertEqual(theme.current_theme(), theme.MONOCHROME_THEME)

    def test_a_remembered_theme_gone(self) -> None:
        """Said before the screen is taken, with what to do about it."""
        save_theme_setting("sepia", self.settings)
        code, _, err = self.run_main("--key-test")
        self.assertEqual(code, 1)
        self.assertIn('the theme "sepia"', err)
        self.assertIn("Themes", err)

    def test_init_theme(self) -> None:
        """``--init-theme``."""
        code, out, _ = self.run_main("--init-theme", "Deep Sea")
        self.assertEqual(code, 0)
        self.assertIn("deep-sea", out)
        self.assertIn("deep-sea", theme.theme_names(self.folder))
