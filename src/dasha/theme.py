"""Colour themes: every colour that Dasha Framework uses, by role, and the user's
overrides.

Each part of the screen has a named role (``"window.frame"``,
``"menu.selected"``, ``"button.face"`` and so on), and a theme maps every
role to a ``Style``. ``apply_theme`` installs a theme by setting the class
attributes that the widgets read when they draw (``Window.frame_style`` and
so on), so a subclass that restyles a widget still keeps its own colours.

There are three built-in themes (``BASES``):

- ``"default"``: Dasha Framework's own colours, with blue windows and grey
  dialogs.
- ``"dark"``: light text on black windows and dark grey dialogs, menus and
  status bar (``DARK_THEME``).
- ``"monochrome"``: no colours at all, only bold, underline and reverse
  video, which every VT100-compatible terminal supports. It is used with
  ``--monochrome``, or when the ``NO_COLOR`` environment variable is set
  (https://no-color.org).

Each file in ``~/.dasha/themes/`` (``THEMES_FOLDER``) adds another
theme, named after the file; ``theme_names`` lists all the themes, and
``load_named_theme`` loads one. The theme can be changed while Dasha Framework is
running (with ``PresentationManager.set_theme``, or the system menu's
Themes).

A user's ``~/.dasha/colours.json``, like a theme file, chooses a base
theme and overrides any roles it wants to::

    {
        "base": "default",
        "colours": {
            "desktop": {"foreground": "yellow"},
            "window.body": {"foreground": "bright white", "background": "black"},
            "window.shadow": null
        }
    }

Each override changes only the parts it names, and the rest come from the
base theme. Colours can be names (``"blue"``, ``"bright white"``), ANSI
numbers from 0 to 255, RGB colours (``"#ff8800"``, or ``"#f80"`` for short),
or ``"default"`` for the terminal's own colour.
``null`` turns a shadow off.

As well as colours, a theme has a few drawing settings, such as
``"button_shadow"``, which is either ``"solid"`` (half blocks, the default)
or ``"outline"`` (single box lines, used by the monochrome theme, where
solid blocks would look like part of the button).
"""

import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path

from dasha.config import ConfigError, read_json_object
from dasha.desktop import Desktop
from dasha.dialog import Dialog
from dasha.help import HelpView, HelpWindow
from dasha.menu import MenuBar
from dasha.statusbar import StatusBar
from dasha.style import (
    BLACK,
    BLUE,
    BRIGHT_BLACK,
    BRIGHT_GREEN,
    BRIGHT_WHITE,
    BRIGHT_YELLOW,
    CYAN,
    GREEN,
    WHITE,
    Colour,
    Rgb,
    Style,
    show_colours,
    terminal_has_colours,
)
from dasha.widgets import (
    SHADOW_SHAPES,
    Button,
    Cluster,
    Collapsible,
    ComboBox,
    GroupBox,
    ListBox,
    ProgressBar,
    ScrollBar,
    Slider,
    SpinBox,
    Splitter,
    Switch,
    Table,
    Tabs,
    TextArea,
    TextBox,
    TreeView,
)
from dasha.window import Window

DEFAULT_PATH = Path.home() / ".dasha" / "colours.json"
"""Where Dasha Framework looks for the user's colours file:
``~/.dasha/colours.json``.

:meta hide-value:
"""

type Theme = dict[str, Style | str | None]
"""Role (or setting) name to ``Style`` (or setting value)."""

ROLES: dict[str, tuple[type, str]] = {
    "desktop": (Desktop, "style"),
    "window.frame": (Window, "frame_style"),
    "window.frame.inactive": (Window, "inactive_frame_style"),
    "window.frame.adjusting": (Window, "adjusting_frame_style"),
    "window.body": (Window, "body_style"),
    "window.buttons": (Window, "button_style"),
    "window.grip": (Window, "resize_grip_style"),
    "window.shadow": (Window, "shadow_style"),
    "window.scrollbar": (Window, "scrollbar_style"),
    "dialog.frame": (Dialog, "frame_style"),
    "dialog.frame.inactive": (Dialog, "inactive_frame_style"),
    "dialog.frame.adjusting": (Dialog, "adjusting_frame_style"),
    "dialog.body": (Dialog, "body_style"),
    "dialog.buttons": (Dialog, "button_style"),
    "dialog.scrollbar": (Dialog, "scrollbar_style"),
    "help.frame": (HelpWindow, "frame_style"),
    "help.frame.inactive": (HelpWindow, "inactive_frame_style"),
    "help.frame.adjusting": (HelpWindow, "adjusting_frame_style"),
    "help.body": (HelpWindow, "body_style"),
    "help.buttons": (HelpWindow, "button_style"),
    "help.grip": (HelpWindow, "resize_grip_style"),
    "help.scrollbar": (HelpWindow, "scrollbar_style"),
    "help.heading": (HelpView, "heading_style"),
    "help.bold": (HelpView, "bold_style"),
    "help.emphasis": (HelpView, "emphasis_style"),
    "help.code": (HelpView, "code_style"),
    "help.link": (HelpView, "link_style"),
    "help.link.focused": (HelpView, "focused_link_style"),
    "help.disabled": (HelpView, "disabled_style"),
    "menu.bar": (MenuBar, "bar_style"),
    "menu.mnemonic": (MenuBar, "mnemonic_style"),
    "menu.selected": (MenuBar, "selected_style"),
    "menu.selected.mnemonic": (MenuBar, "selected_mnemonic_style"),
    "menu.disabled": (MenuBar, "disabled_style"),
    "menu.shadow": (MenuBar, "shadow_style"),
    "status": (StatusBar, "style"),
    "status.keys": (StatusBar, "key_style"),
    "button.face": (Button, "face_style"),
    "button.focused": (Button, "focused_style"),
    "button.mnemonic": (Button, "mnemonic_style"),
    "button.focused.mnemonic": (Button, "focused_mnemonic_style"),
    "button.shadow": (Button, "shadow_style"),
    "cluster": (Cluster, "style"),
    "cluster.selected": (Cluster, "selected_style"),
    "cluster.mnemonic": (Cluster, "mnemonic_style"),
    "cluster.disabled": (Cluster, "disabled_style"),
    "collapsible.arrow": (Collapsible, "arrow_style"),
    "collapsible.label": (Collapsible, "label_style"),
    "collapsible.focused": (Collapsible, "focused_style"),
    "collapsible.mnemonic": (Collapsible, "mnemonic_style"),
    "combobox": (ComboBox, "style"),
    "combobox.focused": (ComboBox, "focused_style"),
    "combobox.button": (ComboBox, "button_style"),
    "groupbox": (GroupBox, "style"),
    "listbox": (ListBox, "style"),
    "listbox.focused": (ListBox, "focused_style"),
    "listbox.selected": (ListBox, "selected_style"),
    "progress.filled": (ProgressBar, "filled_style"),
    "progress.empty": (ProgressBar, "empty_style"),
    "scrollbar": (ScrollBar, "style"),
    "slider": (Slider, "style"),
    "slider.focused": (Slider, "focused_style"),
    "slider.knob": (Slider, "knob_style"),
    "slider.knob.focused": (Slider, "focused_knob_style"),
    "spinbox.arrows": (SpinBox, "arrow_style"),
    "splitter": (Splitter, "style"),
    "splitter.focused": (Splitter, "focused_style"),
    "switch.off": (Switch, "off_style"),
    "switch.on": (Switch, "on_style"),
    "switch.disabled": (Switch, "disabled_style"),
    "table": (Table, "style"),
    "table.header": (Table, "header_style"),
    "table.focused": (Table, "focused_style"),
    "table.selected": (Table, "selected_style"),
    "tabs": (Tabs, "style"),
    "tabs.selected": (Tabs, "selected_style"),
    "tabs.focused": (Tabs, "focused_style"),
    "textarea": (TextArea, "style"),
    "textarea.selected": (TextArea, "selected_style"),
    "textarea.numbers": (TextArea, "number_style"),
    "textbox": (TextBox, "style"),
    "textbox.focused": (TextBox, "focused_style"),
    "textbox.selected": (TextBox, "selected_style"),
    "textbox.arrows": (TextBox, "arrow_style"),
    "tree": (TreeView, "style"),
    "tree.focused": (TreeView, "focused_style"),
    "tree.selected": (TreeView, "selected_style"),
    "tree.lines": (TreeView, "lines_style"),
}
"""Every role, and the class attribute that holds its style."""

SETTINGS: dict[str, tuple[type, str, tuple[str, ...]]] = {
    "button_shadow": (Button, "shadow_shape", SHADOW_SHAPES),
}
"""The drawing settings that are not colours: the class attribute that
holds each one, and its allowed values."""

NULLABLE_ROLES = frozenset({"window.shadow", "menu.shadow"})
"""The roles that may be ``None`` (meaning no shadow at all)."""

DESCRIPTIONS: dict[str, str] = {
    "desktop": "The desktop pattern behind the windows",
    "window.frame": "The active window's frame and title",
    "window.frame.inactive": "Other windows' frames and titles",
    "window.frame.adjusting": "A frame while moved or resized, by mouse or keyboard",
    "window.body": "Inside windows, including labels",
    "window.buttons": "The symbols in title bar buttons",
    "window.grip": "The resize grip of the active window",
    "window.shadow": "Drop shadows of windows (null for none)",
    "window.scrollbar": "Scroll bars on window frames",
    "dialog.frame": "The active dialog's frame and title",
    "dialog.frame.inactive": "Other dialogs' frames",
    "dialog.frame.adjusting": "A dialog's frame while moved, by mouse or keyboard",
    "dialog.body": "Inside dialog boxes",
    "dialog.buttons": "The symbols in a dialog's title bar buttons",
    "dialog.scrollbar": "Scroll bars on dialog frames",
    "help.frame": "The active help window's frame and title",
    "help.frame.inactive": "Other help windows' frames and titles",
    "help.frame.adjusting": "A help window's frame while moved or resized",
    "help.body": "Inside help windows, including ordinary text",
    "help.buttons": "The symbols in a help window's title bar buttons",
    "help.grip": "The resize grip of the active help window",
    "help.scrollbar": "Scroll bars in help windows",
    "help.heading": "Headings in help pages",
    "help.bold": "Bold text in help pages",
    "help.emphasis": "Italic text in help pages, and the places of images",
    "help.code": "Code in help pages",
    "help.link": "Links in help pages, and the row of Back, Forward and so on",
    "help.link.focused": "The highlighted link in a help page",
    "help.disabled": "Back or Forward in a help window, with nowhere to go",
    "menu.bar": "The menu bar, and drop-down menus",
    "menu.mnemonic": "Mnemonic letters in menus",
    "menu.selected": "The highlighted menu title or item",
    "menu.selected.mnemonic": "The mnemonic in the highlighted item",
    "menu.disabled": "Menu items that cannot be chosen",
    "menu.shadow": "Drop shadows of drop-down menus (null for none)",
    "status": "The status bar",
    "status.keys": "Key names in the hints on the right of the status bar",
    "button.face": "Push buttons",
    "button.focused": "The push button with the keyboard focus",
    "button.mnemonic": "Mnemonic letters on push buttons",
    "button.focused.mnemonic": "The mnemonic on the focused push button",
    "button.shadow": "Push button shadows (the background is the window's)",
    "cluster": "Check boxes and radio buttons",
    "cluster.selected": "The current check box or radio button, when focused",
    "cluster.mnemonic": "Mnemonic letters of check boxes and radio buttons",
    "cluster.disabled": "Check boxes and radio buttons that cannot be chosen",
    "collapsible.arrow": "The ► or ▼ of a collapsible area (no colour: the window's)",
    "collapsible.label": "A collapsible area's label",
    "collapsible.focused": "The label of the collapsible area with the keyboard focus",
    "collapsible.mnemonic": "The mnemonic letter of a collapsible area's label",
    "combobox": "Combo boxes (a choice, with a list to drop down)",
    "combobox.focused": "The combo box with the keyboard focus",
    "combobox.button": "The ▼ that drops a combo box's list down",
    "groupbox": "Group boxes' frames and titles (no colour: the window's)",
    "listbox": "List boxes",
    "listbox.focused": "The highlighted item of the list box with the focus",
    "listbox.selected": "Selected items in list boxes",
    "progress.filled": "The filled part of progress and column bars, and text on it",
    "progress.empty": "The rest of progress and column bars, and text on it",
    "scrollbar": "Scroll bar widgets, such as a list box's",
    "slider": "A slider's track",
    "slider.focused": "The track of the slider with the keyboard focus",
    "slider.knob": "A slider's knob",
    "slider.knob.focused": "The knob of the slider with the keyboard focus",
    "spinbox.arrows": "The ▼▲ that step a spin box's number",
    "splitter": "A splitter's divider (no colour: the window's)",
    "splitter.focused": "The divider of the splitter with the keyboard focus",
    "switch.off": "A switch's track and knob while it is off",
    "switch.on": "A switch's track and knob while it is on",
    "switch.disabled": "Switches that cannot be changed",
    "table": "Tables' rows",
    "table.header": "Tables' column headings",
    "table.focused": "The highlighted row of the table with the focus",
    "table.selected": "Selected rows in tables",
    "tabs": "Tabs not chosen, and their lines (no colour: the window's)",
    "tabs.selected": "The tab chosen",
    "tabs.focused": "The tab chosen, while the tabs have the keyboard focus",
    "textarea": "Text areas (many lines of text to edit)",
    "textarea.selected": "Selected text in the focused text area",
    "textarea.numbers": "A text area's line numbers, and the bar beside them",
    "textbox": "Text boxes",
    "textbox.focused": "The text box with the keyboard focus",
    "textbox.selected": "Selected text in the focused text box",
    "textbox.arrows": "The arrows showing a text box has more text that way",
    "tree": "Tree views",
    "tree.focused": "The highlighted item of the tree view with the focus",
    "tree.selected": "The highlighted item of tree views without the focus, and "
    "selected items",
    "tree.lines": "The lines joining the items of tree views",
}

COLOUR_NAMES: dict[str, int] = {
    "black": 0,
    "red": 1,
    "green": 2,
    "yellow": 3,
    "blue": 4,
    "magenta": 5,
    "cyan": 6,
    "white": 7,
    "bright black": 8,
    "bright red": 9,
    "bright green": 10,
    "bright yellow": 11,
    "bright blue": 12,
    "bright magenta": 13,
    "bright cyan": 14,
    "bright white": 15,
}
"""The colour names accepted in a colours file. ``"grey"`` also means
bright black, as that colour is usually called."""

_ALIASES = {"grey": 8}

DEFAULT_THEME: Theme = {
    role: getattr(cls, attribute) for role, (cls, attribute) in ROLES.items()
} | {name: getattr(cls, attribute) for name, (cls, attribute, _) in SETTINGS.items()}
"""The colours Dasha Framework comes with, read from the classes before any theme
is applied, so that the classes remain the only place where they are
written down."""

_PLAIN = Style()
_BOLD = Style(bold=True)
_REVERSE = Style(reverse=True)

MONOCHROME_THEME: Theme = {
    "desktop": _PLAIN,
    "window.frame": _BOLD,
    "window.frame.inactive": _PLAIN,
    "window.frame.adjusting": Style(bold=True, reverse=True),
    "window.body": _PLAIN,
    "window.buttons": _BOLD,
    "window.grip": Style(bold=True, reverse=True),
    "window.shadow": _PLAIN,
    "window.scrollbar": _PLAIN,
    "dialog.frame": _BOLD,
    "dialog.frame.inactive": _PLAIN,
    "dialog.frame.adjusting": Style(bold=True, reverse=True),
    "dialog.body": _PLAIN,
    "dialog.buttons": _BOLD,
    "dialog.scrollbar": _PLAIN,
    "help.frame": _BOLD,
    "help.frame.inactive": _PLAIN,
    "help.frame.adjusting": Style(bold=True, reverse=True),
    "help.body": _PLAIN,
    "help.buttons": _BOLD,
    "help.grip": Style(bold=True, reverse=True),
    "help.scrollbar": _PLAIN,
    "help.heading": _BOLD,
    "help.bold": _BOLD,
    "help.emphasis": Style(underline=True),
    "help.code": _REVERSE,
    "help.link": Style(underline=True),
    "help.link.focused": _REVERSE,
    "help.disabled": _PLAIN,
    "menu.bar": _REVERSE,
    "menu.mnemonic": Style(reverse=True, underline=True),
    "menu.selected": _BOLD,
    "menu.selected.mnemonic": Style(bold=True, underline=True),
    "menu.disabled": _REVERSE,
    "menu.shadow": _PLAIN,
    "status": _REVERSE,
    "status.keys": Style(reverse=True, underline=True),
    "button.face": _REVERSE,
    "button.focused": Style(bold=True, reverse=True),
    "button.mnemonic": Style(reverse=True, underline=True),
    "button.focused.mnemonic": Style(bold=True, reverse=True, underline=True),
    "button.shadow": _PLAIN,
    "cluster": _PLAIN,
    "cluster.selected": _REVERSE,
    "cluster.mnemonic": Style(underline=True),
    "cluster.disabled": _PLAIN,
    "collapsible.arrow": _BOLD,
    "collapsible.label": _PLAIN,
    "collapsible.focused": _BOLD,
    "collapsible.mnemonic": Style(underline=True),
    "combobox": _REVERSE,
    "combobox.focused": Style(bold=True, reverse=True),
    "combobox.button": _BOLD,
    "groupbox": _PLAIN,
    "listbox": _PLAIN,
    "listbox.focused": _REVERSE,
    "listbox.selected": Style(bold=True, underline=True),
    "progress.filled": _REVERSE,
    "progress.empty": _PLAIN,
    "scrollbar": _PLAIN,
    "slider": _PLAIN,
    "slider.focused": _BOLD,
    "slider.knob": _PLAIN,
    "slider.knob.focused": _BOLD,
    "spinbox.arrows": _BOLD,
    "splitter": _PLAIN,
    "splitter.focused": _REVERSE,
    "switch.off": _PLAIN,
    "switch.on": _BOLD,
    "switch.disabled": _PLAIN,
    "table": _PLAIN,
    "table.header": _REVERSE,
    "table.focused": _REVERSE,
    "table.selected": Style(bold=True, underline=True),
    "tabs": _PLAIN,
    "tabs.selected": _BOLD,
    "tabs.focused": Style(bold=True, reverse=True),
    "textarea": _PLAIN,
    "textarea.selected": _REVERSE,
    "textarea.numbers": _PLAIN,
    "textbox": _REVERSE,
    "textbox.focused": Style(bold=True, reverse=True),
    "textbox.selected": _PLAIN,
    "textbox.arrows": Style(bold=True, reverse=True),
    "tree": _PLAIN,
    "tree.focused": _REVERSE,
    "tree.selected": Style(bold=True, underline=True),
    "tree.lines": _PLAIN,
    "button_shadow": "outline",
}
"""No colours: only bold, underline and reverse video. The selection in the
reversed menu bar is shown in normal video, as on monochrome PCs."""


def _dark() -> Theme:
    """The dark theme: the default's, on black and dark grey."""

    def on(foreground: int, background: int, **flags: bool) -> Style:
        return Style(foreground=foreground, background=background, **flags)

    # Inside windows, black; dialogs, menus and the status bar, dark grey;
    # fields to fill in, blue; buttons and highlights stay green.
    window, panel, field_ = BLACK, BRIGHT_BLACK, BLUE
    changes: Theme = {
        "desktop": on(BRIGHT_BLACK, BLACK),
        "window.frame": on(BRIGHT_WHITE, window, bold=True),
        "window.frame.inactive": on(WHITE, window),
        "window.frame.adjusting": on(BRIGHT_GREEN, window, bold=True),
        "window.body": on(WHITE, window),
        "window.buttons": on(BRIGHT_GREEN, window, bold=True),
        "window.grip": on(BRIGHT_GREEN, window, bold=True),
        "window.scrollbar": on(WHITE, panel),
        "dialog.frame": on(BRIGHT_WHITE, panel, bold=True),
        "dialog.frame.inactive": on(WHITE, panel),
        "dialog.frame.adjusting": on(BRIGHT_GREEN, panel, bold=True),
        "dialog.body": on(WHITE, panel),
        "dialog.buttons": on(BRIGHT_GREEN, panel, bold=True),
        "dialog.scrollbar": on(WHITE, window),
        "menu.bar": on(WHITE, panel),
        "menu.mnemonic": on(BRIGHT_YELLOW, panel),
        "menu.selected": on(BLACK, GREEN),
        "menu.selected.mnemonic": on(BRIGHT_YELLOW, GREEN),
        "menu.disabled": on(BLACK, panel),
        "status": on(WHITE, panel),
        "status.keys": on(BRIGHT_YELLOW, panel),
        # Dark grey would not read on black: the label stays white.
        "collapsible.label": Style(foreground=WHITE),
        "cluster": on(WHITE, field_),
        "cluster.selected": on(BRIGHT_WHITE, field_, bold=True),
        "cluster.mnemonic": on(BRIGHT_YELLOW, field_),
        "cluster.disabled": on(BRIGHT_BLACK, field_),
        "combobox": on(WHITE, field_),
        "combobox.focused": on(BRIGHT_WHITE, field_, bold=True),
        "listbox": on(WHITE, field_),
        "listbox.selected": on(BRIGHT_YELLOW, field_, bold=True),
        "progress.filled": on(BRIGHT_WHITE, CYAN, bold=True),
        "progress.empty": on(BRIGHT_BLACK, window),
        "scrollbar": on(WHITE, panel),
        "slider": on(WHITE, field_),
        "slider.focused": on(BRIGHT_WHITE, field_, bold=True),
        "slider.knob": on(BRIGHT_WHITE, field_),
        "slider.knob.focused": on(BRIGHT_GREEN, field_),
        "switch.off": on(WHITE, panel),
        "switch.disabled": on(BLACK, panel),
        "table": on(WHITE, field_),
        "table.header": on(BRIGHT_WHITE, panel),
        "table.selected": on(BRIGHT_YELLOW, field_, bold=True),
        "textarea": on(WHITE, window),
        "textarea.numbers": on(CYAN, window),
        "textbox": on(WHITE, field_),
        "textbox.focused": on(BRIGHT_WHITE, field_, bold=True),
        "textbox.arrows": on(CYAN, window, bold=True),
        "tree": on(WHITE, field_),
        "tree.selected": on(BRIGHT_YELLOW, field_, bold=True),
        "tree.lines": on(CYAN, field_),
    }
    return DEFAULT_THEME | changes


DARK_THEME: Theme = _dark()
"""Light text on black windows, with dark grey dialogs, menus and status
bar, and blue fields to fill in; buttons and highlights stay green."""

BASES: dict[str, Theme] = {
    "default": DEFAULT_THEME,
    "dark": DARK_THEME,
    "monochrome": MONOCHROME_THEME,
}
"""The names of the built-in themes, ``"default"``, ``"dark"`` and
``"monochrome"``, which a colours file or theme file can start from
(``"base"``), and which are always offered."""

THEMES_FOLDER = Path.home() / ".dasha" / "themes"
"""The folder where theme files are kept, each holding one theme:
``~/.dasha/themes``. A theme file has the same format as the colours
file (see ``DEFAULT_PATH``), and is named after its theme, so ``ocean.json``
is the theme ``ocean``.

:meta hide-value:
"""


class ThemeError(ValueError):
    """A colours file could not be used; the message lists every
    problem."""


def apply_theme(theme: Mapping[str, Style | str | None]) -> None:
    """Install a theme, by setting the class attribute of every role and
    setting. If it leaves no colours in use, or the terminal has none, none
    are drawn, even from a style written with them (``style.show_colours``)."""
    for name, value in theme.items():
        cls, attribute = ROLES[name] if name in ROLES else SETTINGS[name][:2]
        setattr(cls, attribute, value)
    show_colours(has_colours() and terminal_has_colours())


def current_theme() -> Theme:
    """The styles and settings currently in use (to restore them later, for
    example)."""
    styles = {role: getattr(cls, attribute) for role, (cls, attribute) in ROLES.items()}
    settings = {
        name: getattr(cls, attribute) for name, (cls, attribute, _) in SETTINGS.items()
    }
    return styles | settings


def has_colours() -> bool:
    """Whether the theme in use has any colours: not the Monochrome theme,
    unless the user has added some to it. A widget with colours of its own
    can look at this, to choose how it looks without them."""
    return any(
        isinstance(style, Style)
        and (style.foreground is not None or style.background is not None)
        for style in current_theme().values()
    )


def parse_colour(value: object) -> Colour | None:
    """A colour from the colours file: a name, a number from 0 to 255, an
    RGB colour such as "#ff8800", or "default".

    Raises ``ValueError`` for anything else.
    """
    if isinstance(value, bool):
        raise ValueError(f"{value!r} is not a colour")
    if isinstance(value, int):
        if 0 <= value <= 255:
            return value
        raise ValueError(f"{value} is not a colour number (0-255)")
    if isinstance(value, str):
        name = " ".join(value.lower().replace("_", " ").replace("-", " ").split())
        if name == "default":
            return None
        if name in COLOUR_NAMES:
            return COLOUR_NAMES[name]
        if name in _ALIASES:
            return _ALIASES[name]
        if name.startswith("#"):
            return Rgb.parse(name)
    raise ValueError(f"{value!r} is not a colour name, number or #rrggbb")


def _colour_name(colour: Colour | None) -> str | int:
    if colour is None:
        return "default"
    if isinstance(colour, Rgb):
        return colour.hex
    for name, number in COLOUR_NAMES.items():
        if number == colour:
            return name
    return colour


def _override(
    role: str, base: Style | None, data: object, problems: list[str]
) -> Style | None:
    """Apply one role's override from the colours file to its base style."""
    if data is None:
        if role in NULLABLE_ROLES:
            return None
        problems.append(f'"{role}" cannot be null (only shadows can be turned off)')
        return base
    if not isinstance(data, dict):
        problems.append(f'"{role}" must be an object such as {{"foreground": "red"}}')
        return base
    changes: dict[str, object] = {}
    for key, value in data.items():
        if key in ("foreground", "background"):
            try:
                changes[key] = parse_colour(value)
            except ValueError as error:
                problems.append(f'"{role}" {key}: {error}')
        elif key in ("bold", "underline", "reverse"):
            if isinstance(value, bool):
                changes[key] = value
            else:
                problems.append(f'"{role}" {key} must be true or false')
        else:
            problems.append(
                f'"{role}": unknown setting "{key}" (use foreground, background, '
                "bold, underline or reverse)"
            )
    return dataclasses.replace(base or Style(), **changes)  # type: ignore[arg-type]


def build_theme(
    settings: Mapping[str, object] | None, *, monochrome: bool = False
) -> Theme:
    """A theme built from the contents of a colours file (``None`` when
    there is no file).

    The base theme is ``"monochrome"`` when ``monochrome`` is true (because
    of the ``--monochrome`` option, or ``NO_COLOR`` when the file names no
    base), otherwise the file's ``"base"``, and otherwise ``"default"``.
    Raises ``ThemeError``, listing every problem.
    """
    settings = settings or {}
    problems: list[str] = []
    allowed = ("base", "colours", *SETTINGS)
    for key in settings:
        if key not in allowed:
            problems.append(
                f'unknown setting "{key}" (use {", ".join(map(repr, allowed))})'
            )
    base_name = settings.get("base", "default")
    if monochrome:
        base_name = "monochrome"
    if not isinstance(base_name, str) or base_name not in BASES:
        problems.append(f'"base" must be one of {", ".join(BASES)}, not {base_name!r}')
        base_name = "default"
    theme = dict(BASES[str(base_name)])
    colours = settings.get("colours", {})
    if not isinstance(colours, dict):
        problems.append('"colours" must be an object of roles')
        colours = {}
    for role, data in colours.items():
        if role not in ROLES:
            problems.append(f'unknown role "{role}" (dasha --init-colours lists them)')
            continue
        base = theme[role]
        theme[role] = _override(
            role, base if isinstance(base, Style) else None, data, problems
        )
    for name, (_, _, values) in SETTINGS.items():
        if name in settings:
            value = settings[name]
            if value in values:
                theme[name] = str(value)
            else:
                problems.append(f'"{name}" must be one of {", ".join(values)}')
    if problems:
        raise ThemeError("\n".join(problems))
    return theme


def load_theme(
    path: Path, *, monochrome: bool = False, no_colour: bool = False
) -> Theme:
    """Read the colours file at ``path`` (which need not exist) and build a
    theme from it.

    ``monochrome`` forces the monochrome base theme (``--monochrome``), and
    ``no_colour`` (the ``NO_COLOR`` environment variable) chooses it unless
    the file names a base itself. Raises ``ThemeError`` if the file cannot be
    used.
    """
    try:
        settings = read_json_object(path)
    except ConfigError as error:
        raise ThemeError(str(error)) from error
    use_monochrome = monochrome or (no_colour and "base" not in (settings or {}))
    return build_theme(settings, monochrome=use_monochrome)


def theme_names(folder: Path | None = None) -> list[str]:
    """The themes available to choose from: the built-in ones (``BASES``),
    then each theme file in ``folder`` (``THEMES_FOLDER`` by default), by
    name, in alphabetical order. A file with the same name as a built-in
    theme is left out, because that name always means the built-in theme."""
    folder = THEMES_FOLDER if folder is None else folder
    names = list(BASES)
    try:
        files = sorted(folder.glob("*.json"))
    except OSError:
        files = []
    names += [path.stem for path in files if path.stem not in BASES]
    return names


def load_named_theme(
    name: str | Path, folder: Path | None = None, *, monochrome: bool = False
) -> Theme:
    """The theme called ``name``: a built-in one (``"dark"``), one in
    ``folder`` (``THEMES_FOLDER`` by default, where ``"ocean"`` is
    ``ocean.json``), or the theme file at a path (a ``Path``, or a name that
    includes a folder or ``.json``). ``monochrome`` uses the monochrome base
    instead of the file's. Raises ``ThemeError`` if there is no such theme,
    or it cannot be used."""
    folder = THEMES_FOLDER if folder is None else folder
    text = str(name)
    if isinstance(name, str) and name in BASES:
        return dict(BASES["monochrome" if monochrome else name])
    is_path = isinstance(name, Path) or any(
        mark in text for mark in ("/", "\\", ".json")
    )
    path = Path(text).expanduser() if is_path else folder / f"{text}.json"
    if not path.is_file():
        raise ThemeError(f'no theme "{text}" ({path} is not there)')
    return load_theme(path, monochrome=monochrome)


def theme_to_json(
    theme: Mapping[str, Style | str | None], base: str = "default"
) -> str:
    """A theme written out as a colours file, with every role included,
    ready to edit."""
    colours: dict[str, object] = {}
    for role in ROLES:
        style = theme[role]
        if not isinstance(style, Style):
            colours[role] = None
            continue
        entry: dict[str, object] = {
            "foreground": _colour_name(style.foreground),
            "background": _colour_name(style.background),
        }
        for flag in ("bold", "underline", "reverse"):
            if getattr(style, flag):
                entry[flag] = True
        colours[role] = entry
    settings = {name: theme[name] for name in SETTINGS}
    return json.dumps({"base": base, **settings, "colours": colours}, indent=4)
