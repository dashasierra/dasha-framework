"""Tests for configurable keyboard shortcuts."""

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from dasha.__main__ import main
from dasha.canvas import Rect
from dasha.events import MouseEvent, PasteEvent
from dasha.keytest import describe
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuItem
from dasha.shortcuts import (
    DEFAULTS,
    Shortcuts,
    ShortcutsError,
    key_from_pretty,
    normalise_key,
    pretty_key,
)
from dasha.window import Window
from tests.support import isolated_home


class KeyNameTests(unittest.TestCase):
    """Normalising and displaying key names."""

    def test_normalise(self) -> None:
        """Modifiers are reordered and lower-cased; named keys lower-cased."""
        self.assertEqual(normalise_key("Ctrl+Alt+X"), "alt+ctrl+x")
        self.assertEqual(normalise_key("alt+X"), "alt+X")
        self.assertEqual(normalise_key("F10"), "f10")
        self.assertEqual(normalise_key("Alt+Space"), "alt+space")
        self.assertEqual(normalise_key("ctrl++"), "ctrl++")
        self.assertEqual(normalise_key("q"), "q")

    def test_invalid_names(self) -> None:
        """Unknown keys, unknown or repeated modifiers, and empty names fail."""
        for name in ("", "foo", "hyper+x", "alt+alt+x", "ctrl+", "f13"):
            self.assertIsNone(normalise_key(name), name)

    def test_pretty_read_back(self) -> None:
        """Pretty names read back."""
        for action, keys in DEFAULTS.items():
            if action == "menu_mnemonic_modifiers":
                continue  # modifiers, not keys
            for key in keys:
                with self.subTest(key=key):
                    self.assertEqual(
                        key_from_pretty(pretty_key(key)), normalise_key(key)
                    )
        self.assertEqual(key_from_pretty("PgDn"), "pagedown")
        self.assertEqual(key_from_pretty("Space"), " ")
        self.assertEqual(key_from_pretty("+"), "+")
        for text in ("", "Help", "Ctrl+", "Hyper+X"):
            self.assertIsNone(key_from_pretty(text), text)

    def test_pretty(self) -> None:
        """Key names are shown the way people write them."""
        self.assertEqual(pretty_key("ctrl+q"), "Ctrl+Q")
        self.assertEqual(pretty_key("shift+f6"), "Shift+F6")
        self.assertEqual(pretty_key("escape"), "Esc")
        self.assertEqual(pretty_key("alt+space"), "Alt+Space")


class ShortcutsTests(unittest.TestCase):
    """Defaults, overrides and validation."""

    def test_defaults(self) -> None:
        """With no overrides every action has its default keys."""
        shortcuts = Shortcuts()
        for action, keys in DEFAULTS.items():
            self.assertEqual(shortcuts.keys(action), keys)
        self.assertEqual(shortcuts.hint("exit"), "Ctrl+Q")

    def test_overrides_replace_only_named_actions(self) -> None:
        """An override replaces that action's keys and normalises them."""
        shortcuts = Shortcuts({"open_menu": ["F10", "Ctrl+O"]})
        self.assertEqual(shortcuts.keys("open_menu"), ("f10", "ctrl+o"))
        self.assertTrue(shortcuts.matches("open_menu", "ctrl+o"))
        self.assertEqual(shortcuts.keys("exit"), DEFAULTS["exit"])

    def test_every_problem_is_reported(self) -> None:
        """All mistakes are listed together, not just the first."""
        with self.assertRaises(ShortcutsError) as context:
            Shortcuts(
                {
                    "exitt": ["q"],
                    "next_window": "tab",
                    "previous_window": ["shift+tabb", 7],
                    "menu_mnemonic_modifiers": ["meta"],
                }
            )
        message = str(context.exception)
        self.assertIn('unknown action "exitt"', message)
        self.assertIn('"next_window" must be a list', message)
        self.assertIn('"shift+tabb" is not a key name', message)
        self.assertIn("7 is not a key name", message)
        self.assertIn('"meta" is not one of shift, alt, ctrl', message)

    def test_cannot_remove_every_way_out(self) -> None:
        """Unbinding both exit and the menu key is refused."""
        with self.assertRaises(ShortcutsError) as context:
            Shortcuts({"exit": [], "open_menu": []})
        self.assertIn("no way to leave Dasha Desktop", str(context.exception))
        with self.assertRaises(ShortcutsError) as context:
            Shortcuts({"menu_close": [], "open_menu": []})
        self.assertIn("no way to close a menu", str(context.exception))
        Shortcuts({"exit": []})  # the menu still offers Exit: allowed

    def test_to_json_round_trips(self) -> None:
        """The JSON written by to_json loads back to the same bindings."""
        shortcuts = Shortcuts({"exit": ["ctrl+x"]})
        again = Shortcuts(json.loads(shortcuts.to_json()))
        for action in DEFAULTS:
            self.assertEqual(again.keys(action), shortcuts.keys(action))


class LoadTests(unittest.TestCase):
    """Reading shortcuts files."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "shortcuts.json"

    def test_missing_file_means_defaults(self) -> None:
        """No file is not an error."""
        self.assertEqual(Shortcuts.load(self.path).keys("exit"), DEFAULTS["exit"])

    def test_utf8_with_bom_and_utf16(self) -> None:
        """Files saved by Windows tools (BOM, UTF-16) load."""
        text = '{"exit": ["ctrl+x"]}'
        for encoding in ("utf-8-sig", "utf-16"):
            self.path.write_bytes(text.encode(encoding))
            self.assertEqual(Shortcuts.load(self.path).keys("exit"), ("ctrl+x",))

    def test_bad_json(self) -> None:
        """Broken JSON and non-objects are explained."""
        self.path.write_text('{"exit": [', encoding="utf-8")
        with self.assertRaisesRegex(ShortcutsError, "not valid JSON"):
            Shortcuts.load(self.path)
        self.path.write_text('["exit"]', encoding="utf-8")
        with self.assertRaisesRegex(ShortcutsError, "JSON object"):
            Shortcuts.load(self.path)


class RemappedInputTests(unittest.TestCase):
    """The manager and menu bar follow the shortcuts they are given."""

    def setUp(self) -> None:
        self.window = Window(
            "W", Rect(2, 2, 4, 10), menus=[Menu("&Edit", [MenuItem("&Copy", print)])]
        )

    def manager(self, overrides: dict[str, list[str]]) -> PresentationManager:
        """A manager with overrides.

        :param overrides: Keys by action.
        """
        return PresentationManager(
            windows=[self.window], shortcuts=Shortcuts(overrides)
        )

    def test_remapped_menu_keys(self) -> None:
        """Without Alt, Ctrl+O can open the menus and arrows still work."""
        manager = self.manager({"open_menu": ["ctrl+o"], "menu_mnemonic_modifiers": []})
        manager.handle_event("alt+e")
        self.assertFalse(manager.menu_bar.is_open)
        manager.handle_event("f10")
        self.assertFalse(manager.menu_bar.is_open)
        manager.handle_event("ctrl+o")
        self.assertIs(manager.menu_bar.open_menu, manager.system_menu)
        manager.handle_event("right")
        self.assertEqual(manager.menu_bar.open_menu, self.window.menus[0])
        manager.handle_event("ctrl+o")
        self.assertFalse(manager.menu_bar.is_open)

    def test_remapped_exit_and_hint(self) -> None:
        """Exit follows its binding, and the system menu shows it."""
        manager = self.manager({"exit": ["ctrl+x"]})
        exit_item = next(i for i in manager.system_menu.items if i.label == "&Shutdown")
        self.assertEqual(exit_item.shortcut, "Ctrl+X")
        manager._running = True  # pylint: disable=protected-access
        manager.handle_event("escape")
        self.assertTrue(manager.is_running)
        manager.handle_event("ctrl+x")
        self.assertFalse(manager.is_running)

    def test_ctrl_mnemonics(self) -> None:
        """Mnemonics can use Ctrl instead of Alt."""
        manager = self.manager({"menu_mnemonic_modifiers": ["ctrl"]})
        manager.handle_event("ctrl+e")
        self.assertEqual(manager.menu_bar.open_menu, self.window.menus[0])


class KeyTestTests(unittest.TestCase):
    """The --key-test descriptions."""

    def test_describe(self) -> None:
        """Keys show their name for the file and the friendly form."""
        self.assertEqual(describe("ctrl+q"), '"ctrl+q"  (Ctrl+Q)')
        self.assertIn("not recognised", describe("unknown(99~)"))
        self.assertEqual(
            describe(MouseEvent("press", "left", 3, 7, ctrl=True)),
            "mouse  ctrl+left press at row 3, column 7",
        )
        self.assertEqual(describe(PasteEvent("12\r")), "paste  3 characters: '12\\r'")
        self.assertEqual(describe(PasteEvent("x")), "paste  1 character: 'x'")
        self.assertEqual(
            describe(PasteEvent("y" * 50)), f"paste  50 characters: '{'y' * 40}'..."
        )


class CommandLineTests(unittest.TestCase):
    """--init-shortcuts and loading problems, before the screen is touched."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "sub" / "shortcuts.json"
        isolated_home(self)  # not the user's own settings, theme included

    def run_main(self, *args: str) -> tuple[int, str, str]:
        """Run main; return exit code, stdout and stderr.

        :param args: Command-line arguments.
        """
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_init_writes_defaults_once(self) -> None:
        """--init-shortcuts writes an editable file but never overwrites."""
        code, out, _ = self.run_main("--init-shortcuts", "--shortcuts", str(self.path))
        self.assertEqual(code, 0)
        self.assertIn(str(self.path), out)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["exit"], list(DEFAULTS["exit"]))
        code, _, err = self.run_main("--init-shortcuts", "--shortcuts", str(self.path))
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)

    def test_bad_file_is_reported_before_starting(self) -> None:
        """A broken file stops Dasha Framework with every problem listed."""
        self.path.parent.mkdir()
        self.path.write_text('{"exit": ["nope"], "bogus": []}', encoding="utf-8")
        code, _, err = self.run_main("desktop", "--shortcuts", str(self.path))
        self.assertEqual(code, 1)
        self.assertIn('"nope" is not a key name', err)
        self.assertIn('unknown action "bogus"', err)
        self.assertIn("move it aside", err)

    def test_explicit_missing_file(self) -> None:
        """Naming a file that does not exist is an error."""
        code, _, err = self.run_main("desktop", "--shortcuts", str(self.path))
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)


if __name__ == "__main__":
    unittest.main()
