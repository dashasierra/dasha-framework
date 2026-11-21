"""The Shortcuts settings page."""

import json
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

from dasha.dialog import Dialog, question
from dasha.filedialog import FileDialog
from dasha.shortcuts import (
    DEFAULTS,
    DESCRIPTIONS,
    Shortcuts,
    ShortcutsError,
    pretty_key,
)
from dasha.widgets import Button, Column, Label, Table
from dasha.widgets.tabs import TabPage

if TYPE_CHECKING:
    from dasha.settings import SettingsDialog

SHORTCUT_FILES = [("Shortcuts files", "*.json")]

ABOUT_WIDTH = 70
"""How much of an action's description is shown below the table."""

MODIFIER_ACTION = "menu_mnemonic_modifiers"
"""The action whose keys are modifiers."""


def shortcuts_json(shortcuts: Shortcuts) -> str:
    """A shortcuts file of non-default bindings.

    :param shortcuts: The bindings.
    """
    return json.dumps(shortcuts.overrides, indent=4) + "\n"


class KeyDialog(Dialog):
    """Asks for a key by having it pressed.

    :param action: The action being bound.
    """

    takes_every_key = True

    def __init__(self, action: str) -> None:
        super().__init__("Add a key", 52, 8, status="Press the key, or click Cancel")
        self.key: str | None = None
        """The key pressed."""
        self.add(Label(f"Press the key to add to {action}."[:48], 1, 2))
        self.add(Label("Every key counts: click Cancel to add none.", 2, 2))
        self.add(Button("Cancel", 4, 20, result="cancel", name="cancel"))

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        del shortcuts
        self.key = key
        self.result = "ok"
        return True


class ShortcutsPage:
    """Actions and their keys.

    :param dialog: The settings dialog.
    :param page: Its tab page.
    """

    def __init__(self, dialog: "SettingsDialog", page: TabPage) -> None:
        self.dialog = dialog
        self.manager = dialog.desktop_manager
        self.bindings = self.manager.shortcuts.bindings
        """Every action's keys, as they are being changed."""
        self._saved = dict(self.bindings)
        self.table = page.add(
            Table(
                [Column("Action", 26), Column("Keys", 43)],
                0,
                0,
                72,
                10,
                rows=self._rows(),
                on_change=lambda table: self._describe(),
                on_choose=lambda table: self._add_key(None),
                name="shortcuts",
                status="Each action, and the keys that do it",
            )
        )
        self.about = page.add(Label("", 10, 1, name="action_about"))
        page.add(Button("Add &key...", 11, 1, action=self._add_key, name="add_key"))
        page.add(
            Button("&Remove keys", 11, 18, action=self._remove_keys, name="remove_keys")
        )
        page.add(Button("De&fault", 11, 36, action=self._default, name="default"))
        page.add(Button("R&eset all", 13, 1, action=self._reset_all, name="reset_all"))
        page.add(Button("&Load...", 13, 18, action=self._load, name="load_shortcuts"))
        page.add(
            Button("Sa&ve as...", 13, 36, action=self._save_as, name="save_shortcuts")
        )
        self._describe()

    def _describe(self) -> None:
        """Describe the highlighted action."""
        about = DESCRIPTIONS.get(self.action, "")
        self.about.text = textwrap.shorten(about, ABOUT_WIDTH, placeholder="...")

    def _rows(self) -> list[list[str]]:
        return [
            [action, ", ".join(map(pretty_key, keys)) or "(none)"]
            for action, keys in self.bindings.items()
        ]

    @property
    def action(self) -> str:
        """The action highlighted."""
        index = self.table.value
        assert isinstance(index, int)
        return list(self.bindings)[index]

    def _change(self, bindings: dict[str, tuple[str, ...]]) -> None:
        """Use bindings if allowed.

        :param bindings: Keys by action.
        """
        try:
            shortcuts = Shortcuts(
                {action: list(keys) for action, keys in bindings.items()}
            )
        except ShortcutsError as error:
            self.dialog.problem("Shortcuts", str(error))
            return
        self.bindings = shortcuts.bindings
        self.manager.set_shortcuts(shortcuts)
        cursor = self.table.cursor
        self.table.set_rows(self._rows())
        self.table.move_to(cursor)
        self._describe()

    def _with(self, action: str, keys: tuple[str, ...]) -> None:
        self._change({**self.bindings, action: keys})

    def _add_key(self, button: Button | None) -> None:
        """Add a key to the highlighted action.

        :param button: The button pressed, if any.
        """
        del button
        action = self.action
        if action == MODIFIER_ACTION:
            answer = self.dialog.ask(
                question(
                    "Add a key",
                    "Which key, held with a menu's letter, opens the menu?",
                    [
                        ("&Alt", "alt"),
                        ("C&trl", "ctrl"),
                        ("&Shift", "shift"),
                        ("&Cancel", "cancel"),
                    ],
                )
            )
            key = answer if answer in ("alt", "ctrl", "shift") else None
        else:
            dialog = KeyDialog(action)
            key = dialog.key if self.dialog.ask(dialog) == "ok" else None
        if key is not None and key not in self.bindings[action]:
            self._with(action, (*self.bindings[action], key))

    def _remove_keys(self, button: Button) -> None:
        del button
        self._with(self.action, ())

    def _default(self, button: Button) -> None:
        del button
        self._with(self.action, DEFAULTS[self.action])

    def _reset_all(self, button: Button) -> None:
        del button
        self._change(dict(DEFAULTS))

    def _folder(self) -> Path:
        folder = self.manager.shortcuts_path.parent
        return folder if folder.is_dir() else Path.home()

    def _load(self, button: Button) -> None:
        del button
        dialog = FileDialog(
            "Load shortcuts",
            directory=str(self._folder()),
            filters=SHORTCUT_FILES,
            must_exist=True,
        )
        if self.dialog.ask(dialog) != "ok":
            return
        try:
            loaded = Shortcuts.load(Path(dialog.path))
        except ShortcutsError as error:
            self.dialog.problem("Shortcuts", str(error))
            return
        self._change(loaded.bindings)

    def _save_as(self, button: Button) -> None:
        del button
        dialog = FileDialog(
            "Save the shortcuts as",
            directory=str(self._folder()),
            filters=SHORTCUT_FILES,
            name=self.manager.shortcuts_path.name,
        )
        if self.dialog.ask(dialog) == "ok":
            self.dialog.write(
                Path(dialog.path), shortcuts_json(self.manager.shortcuts), "Shortcuts"
            )

    def save(self) -> bool:
        """Save the shortcuts; return whether all went well."""
        if self.bindings == self._saved:
            return True
        path = self.manager.shortcuts_path
        if not self.dialog.write(
            path, shortcuts_json(self.manager.shortcuts), "Shortcuts", ask=False
        ):
            return False
        self._saved = dict(self.bindings)
        return True
