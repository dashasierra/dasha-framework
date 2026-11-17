"""Tests for changing theme while Dasha Framework runs: the built-in themes and
those in the themes folder, the system menu's Themes, applications asking
for one, remembering the choice, and starting with it."""

import json
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
        """A theme file in the folder."""
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
        """The built-in ones first, then the folder's; a file named after a
        built-in one is left out."""
        self.write("default", {})
        self.write("aaa", {})
        self.assertEqual(
            theme.theme_names(self.folder),
            ["default", "dark", "monochrome", "aaa", "ocean"],
        )
        self.assertEqual(theme.theme_names(self.root / "none"), list(theme.BASES))

    def test_loading(self) -> None:
        """By built-in name, by file name, or by path; a file can start from
        the dark theme."""
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
        """A remote dialog's frame, and a context menu's body, which keep
        copies of styles, take the new ones too."""
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
        """An application on its own changes its desktop's theme; one not
        launched yet cannot."""
        manager = self.desktop()
        app = manager.launch(Hello)
        self.assertTrue(app.set_theme("dark"))
        self.assertEqual(manager.theme_name, "dark")
        self.assertFalse(Hello().set_theme("dark"))

    def test_remembered_only_when_asked(self) -> None:
        """A desktop remembers it; an application on its own, or a test,
        does not, unless told to."""
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
        """The Themes submenu, as it is when opened."""
        item = next(i for i in manager.system_menu.items if i.label == "&Themes")
        assert item.submenu is not None and item.submenu.on_open is not None
        item.submenu.on_open(item.submenu)
        return item.submenu

    def test_lists_and_marks(self) -> None:
        """Every theme, the one in use marked; a file added since shows next
        time it opens."""
        manager = self.desktop()
        labels = [item.label for item in self.themes(manager).items]
        self.assertEqual(
            labels, ["\N{SQUARE ROOT} &Default", "  &Dark", "  &Monochrome", "  ocean"]
        )
        self.write("forest", {})
        manager.set_theme("ocean")
        labels = [item.label for item in self.themes(manager).items]
        self.assertEqual(labels[3:], ["  forest", "\N{SQUARE ROOT} ocean"])

    def test_choosing_one(self) -> None:
        """Choosing an item changes the theme, through the menu bar too."""
        manager = self.desktop()
        menu = self.themes(manager)
        dark = next(item for item in menu.items if "Dark" in item.label)
        assert dark.action is not None
        dark.action()
        self.assertEqual(manager.theme_name, "dark")
        manager.handle_event("f10")
        for key in ("down", "down", "right"):  # Themes, opened by the menu bar
            manager.handle_event(key)
        self.assertIn("\N{SQUARE ROOT} &Dark", [i.label for i in menu.items])

    def test_the_colours_file(self) -> None:
        """Offered while there is one: choosing it uses it, and forgets the
        remembered theme, so the desktop starts with it again."""
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


class ClientTests(ThemeIsolation):
    """The application's side."""

    def setUp(self) -> None:
        super().setUp()
        self.desktop, app_end = pipe()
        self.manager = ClientManager(app_end, {**WELCOME, "theme_name": "dark"})
        self.addCleanup(self.manager.stop_listening)
        self.manager.launch(Hello)

    def test_asks_the_desktop(self) -> None:
        """By name as given; a path, made whole for the desktop to find."""
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
        """A theme that is not a name is a problem in the file."""
        self.settings.write_text("theme = 3\n", encoding="utf-8")
        with self.assertRaises(registry.ManifestError):
            read_theme_setting(self.settings)


class StartingTests(Folder):
    """Starting with the theme chosen last."""

    def run_main(self, *args: str) -> tuple[int, str, str]:
        """Run main with the folder and settings, returning the exit code,
        stdout and stderr."""
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

    def test_a_remembered_theme_gone(self) -> None:
        """Said before the screen is taken, with what to do about it."""
        save_theme_setting("sepia", self.settings)
        code, _, err = self.run_main("--key-test")
        self.assertEqual(code, 1)
        self.assertIn('the theme "sepia"', err)
        self.assertIn("Themes", err)

    def test_init_theme(self) -> None:
        """Writes a theme file to edit, by a name fit for a file."""
        code, out, _ = self.run_main("--init-theme", "Deep Sea")
        self.assertEqual(code, 0)
        self.assertIn("deep-sea", out)
        self.assertIn("deep-sea", theme.theme_names(self.folder))
