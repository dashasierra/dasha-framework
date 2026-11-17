"""Settings...' Appearance page: the theme, and the colours of each part of
the screen.

Choosing a theme, or changing a colour, shows on the screen at once.
Colours changed here are saved to the colours file when the settings are
kept, so that the desktop starts with them; a theme chosen unchanged is
remembered by name instead, as the system menu's Themes does. Load... and
Save as... read and write theme files, such as those in
``~/.dasha/themes/``, which the Themes menu offers.
"""

import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

from dasha import registry, theme
from dasha.filedialog import FileDialog
from dasha.style import Colour, Rgb, Style
from dasha.widgets import Button, CheckBoxes, ComboBox, Label, ListBox
from dasha.widgets.button import SHADOW_SHAPES
from dasha.widgets.tabs import TabPage
from dasha.settings.colours import ColourDialog
from dasha.settings.lists import stay_open

if TYPE_CHECKING:
    from dasha.settings import SettingsDialog

COLOUR_CHOICES = ["default", *theme.COLOUR_NAMES]
"""The colours offered for a foreground or background: the terminal's own
(``default``), then the sixteen with names."""

CUSTOM = "Custom..."
"""The last colour offered, which asks for an RGB colour."""

COLOURS_FILE = "Colours file"
"""How the theme box shows the colours file, as the Themes menu does."""

THEME_FILES = [("Themes", "*.json")]


def colour_items(colour: Colour | None) -> tuple[list[str], int]:
    """The colours to offer for one that is in use, and which of them it
    is: a colour numbered above 15, which has no name, or an RGB colour, is
    added after the named ones. ``CUSTOM`` always comes last."""
    items = list(COLOUR_CHOICES)
    if colour is None:
        index = 0
    elif isinstance(colour, int) and colour < len(theme.COLOUR_NAMES):
        index = colour + 1
    else:
        items.append(str(colour))
        index = len(items) - 1
    return [*items, CUSTOM], index


def chosen_colour(box: ComboBox) -> Colour | None:
    """The colour chosen in a box offering ``colour_items``."""
    text = box.selected_item
    return theme.parse_colour(int(text) if text.isdigit() else text)


class AppearancePage:  # pylint: disable=too-many-instance-attributes
    """The theme, with Load... and Save as..., above the roles (each part of
    the screen) and the colours and attributes of the one highlighted."""

    def __init__(self, dialog: "SettingsDialog", page: TabPage) -> None:
        self.dialog = dialog
        self.manager = manager = dialog.desktop_manager
        self.colours: theme.Theme = theme.current_theme()
        """The colours shown, as they are being changed."""
        self.choice: str | None = manager.theme_name
        """The theme chosen (``None``: the colours file's colours)."""
        self.edited = False
        """Whether the colours have been changed from the theme chosen's."""
        self._saved_choice = self.choice
        self._choices: list[str | None] = []
        page.add(Label("Theme", 0, 1))
        self.theme_box = page.add(
            ComboBox(
                [],
                0,
                8,
                26,
                on_change=self._theme_chosen,
                name="theme",
                status="The theme to start from",
            )
        )
        page.add(Button("&Load...", 0, 36, action=self._load, name="load_theme"))
        page.add(Button("Sa&ve as...", 0, 50, action=self._save_as, name="save_theme"))
        self.note = page.add(Label("", 2, 1, name="theme_note"))
        self.roles = page.add(
            ListBox(
                list(theme.ROLES),
                3,
                1,
                30,
                12,
                on_change=lambda box: self._show_role(),
                on_choose=stay_open,
                name="roles",
                status="The part of the screen to colour",
            )
        )
        self.about = [page.add(Label("", 3 + row, 33)) for row in range(2)]
        page.add(Label("Foreground", 6, 33))
        self.foreground = page.add(
            ComboBox(
                COLOUR_CHOICES,
                6,
                46,
                22,
                on_change=self._colour_chosen,
                name="foreground",
            )
        )
        page.add(Label("Background", 8, 33))
        self.background = page.add(
            ComboBox(
                COLOUR_CHOICES,
                8,
                46,
                22,
                on_change=self._colour_chosen,
                name="background",
            )
        )
        self.flags = page.add(
            CheckBoxes(
                ["&Bold", "&Underline", "&Reverse"],
                10,
                33,
                columns=3,
                on_change=self._edit,
                name="flags",
            )
        )
        self.no_shadow = page.add(
            CheckBoxes(["No s&hadow"], 12, 33, on_change=self._edit, name="no_shadow")
        )
        page.add(Label("Button shadows", 14, 33))
        self.shadow_shape = page.add(
            ComboBox(
                SHADOW_SHAPES,
                14,
                50,
                18,
                on_change=self._shape_chosen,
                name="button_shadow",
            )
        )
        self._fill_themes()
        self._show_role()

    # The theme

    def _fill_themes(self) -> None:
        """Offer the themes there are now, with the one chosen selected."""
        folder = self.manager.themes_folder
        names: list[str | None] = list(theme.theme_names(folder))
        colours_path = self.manager.colours_path
        if colours_path is not None and colours_path.is_file():
            names.append(None)
        if self.choice not in names:
            names.append(self.choice)  # colours set in some other way
        self._choices = names
        items = [
            (
                COLOURS_FILE
                if name is None
                else name.capitalize() if name in theme.BASES else name
            )
            for name in names
        ]
        self.theme_box.set_items(items, names.index(self.choice))
        self.note.text = (
            "Changed: kept in the colours file, with OK or Apply" if self.edited else ""
        )

    def _theme_chosen(self, box: ComboBox) -> None:
        name = self._choices[box.value]
        try:
            if name is None:
                path = self.manager.colours_path or theme.DEFAULT_PATH
                colours = theme.load_theme(path)
            else:
                colours = theme.load_named_theme(name, self.manager.themes_folder)
        except theme.ThemeError as error:
            self.dialog.problem("Themes", str(error))
            self._fill_themes()
            return
        self.colours, self.choice, self.edited = colours, name, False
        self._changed()

    def _changed(self) -> None:
        """Show the colours on the screen, and in the page."""
        self.manager.use_theme(dict(self.colours), None if self.edited else self.choice)
        self._fill_themes()
        self._show_role()

    def _load(self, button: Button) -> None:
        del button
        folder = self.manager.themes_folder
        dialog = FileDialog(
            "Load a theme",
            directory=str(folder if folder.is_dir() else Path.home()),
            filters=THEME_FILES,
            must_exist=True,
        )
        if self.dialog.ask(dialog) != "ok":
            return
        path = Path(dialog.path)
        try:
            self.colours = theme.load_named_theme(path)
        except theme.ThemeError as error:
            self.dialog.problem("Themes", str(error))
            return
        self._loaded_from(path)
        self._changed()

    def _loaded_from(self, path: Path) -> None:
        """The colours shown are a theme file's: one the Themes menu offers
        is chosen by its name, and any other's are changed colours."""
        folder = self.manager.themes_folder
        offered = path.suffix == ".json" and path.stem not in theme.BASES
        if offered and path.resolve().parent == folder.resolve():
            self.choice, self.edited = path.stem, False
        else:
            self.edited = True

    def _save_as(self, button: Button) -> None:
        del button
        folder = self.manager.themes_folder
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            folder = Path.home()
        stem = self.choice if self.choice and self.choice not in theme.BASES else "mine"
        dialog = FileDialog(
            "Save the theme as",
            directory=str(folder),
            filters=THEME_FILES,
            name=f"{Path(stem).stem}.json",
        )
        if self.dialog.ask(dialog) != "ok":
            return
        path = Path(dialog.path)
        if not path.suffix:
            path = path.with_suffix(".json")
        if not self.dialog.write(path, self._theme_json(), "Themes"):
            return
        self._loaded_from(path)
        self._changed()

    def _theme_json(self) -> str:
        base = self.choice if self.choice in theme.BASES else "default"
        return theme.theme_to_json(self.colours, base=str(base))

    # The roles

    @property
    def role(self) -> str:
        """The role highlighted."""
        return self.roles.items[self.roles.cursor]

    def _show_role(self) -> None:
        """Show the highlighted role's description, colours and
        attributes."""
        role = self.role
        style = self.colours[role]
        shown = style if isinstance(style, Style) else Style()
        lines = textwrap.wrap(theme.DESCRIPTIONS.get(role, ""), 38)[:2]
        for label, line in zip(self.about, [*lines, "", ""]):
            label.text = line
        self.foreground.set_items(*colour_items(shown.foreground))
        self.background.set_items(*colour_items(shown.background))
        self.flags.checked = [shown.bold, shown.underline, shown.reverse]
        self.no_shadow.checked = [style is None]
        if role in theme.NULLABLE_ROLES:
            self.no_shadow.enable(0)
        else:
            self.no_shadow.disable(0)
        shape = self.colours.get("button_shadow")
        self.shadow_shape.set_items(
            SHADOW_SHAPES,
            SHADOW_SHAPES.index(str(shape)) if shape in SHADOW_SHAPES else 0,
        )

    def _edit(self, widget: object) -> None:
        """A colour or attribute changed: the highlighted role takes it."""
        del widget
        role = self.role
        style: Style | None = None
        if not (role in theme.NULLABLE_ROLES and self.no_shadow.checked[0]):
            bold, underline, reverse = self.flags.checked
            style = Style(
                foreground=chosen_colour(self.foreground),
                background=chosen_colour(self.background),
                bold=bold,
                underline=underline,
                reverse=reverse,
            )
        if style != self.colours[role]:
            self.colours[role] = style
            self.edited = True
            self._changed()

    def _colour_chosen(self, box: ComboBox) -> None:
        """A colour was chosen for the foreground or background; Custom...
        asks which, and Cancel there leaves the colour as it was."""
        if box.selected_item != CUSTOM:
            self._edit(box)
            return
        style = self.colours[self.role]
        shown = getattr(style if isinstance(style, Style) else Style(), box.name or "")
        asked = ColourDialog(shown if isinstance(shown, Rgb) else None)
        if self.dialog.ask(asked) == "ok":
            box.set_items(*colour_items(asked.colour))
            self._edit(box)
        else:
            box.set_items(*colour_items(shown))

    def _shape_chosen(self, box: ComboBox) -> None:
        if self.colours.get("button_shadow") != box.selected_item:
            self.colours["button_shadow"] = box.selected_item
            self.edited = True
            self._changed()

    # Keeping the settings

    def save(self) -> bool:
        """Keep the colours for next time: changed colours in the colours
        file, or else the theme chosen, by name. Returns whether all went
        well (a problem has been shown if not)."""
        manager = self.manager
        if self.edited:
            path = manager.colours_path or theme.DEFAULT_PATH
            if not self.dialog.write(path, self._theme_json(), "Themes", ask=False):
                return False
            self.choice, self.edited = None, False
            manager.use_theme(dict(self.colours), None)
            self._fill_themes()
        if self.choice == self._saved_choice:
            return True
        try:
            registry.save_theme_setting(self.choice, manager.settings_path)
        except OSError as error:
            self.dialog.problem(
                "Themes", f"The theme could not be remembered:\n{error}"
            )
            return False
        self._saved_choice = self.choice
        return True
