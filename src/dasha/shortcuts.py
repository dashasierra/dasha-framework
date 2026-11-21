"""Keyboard shortcuts, with JSON overrides."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from dasha.config import ConfigError, read_json_object
from dasha.events import MODIFIERS, NAMED_KEYS

DEFAULT_PATH = Path.home() / ".dasha" / "shortcuts.json"
"""The user's shortcuts file.

:meta hide-value:
"""

DESKTOP_KEYS = (
    "exit",
    "next_window",
    "previous_window",
    "maximise_window",
    "minimise_window",
    "close_window",
    "move_window",
    "resize_window",
)
"""Actions whose keys the desktop keeps."""

DEFAULTS: dict[str, tuple[str, ...]] = {
    "exit": ("ctrl+q",),
    "next_window": ("f6",),
    "previous_window": ("shift+f6",),
    "maximise_window": ("f5",),
    "minimise_window": (),
    "close_window": ("alt+f4", "alt+f3"),
    "move_window": ("alt+f7", "ctrl+f5"),
    "resize_window": ("alt+f8",),
    "show_mouse": ("alt+`",),
    "command_prompt": ("alt+f12",),
    "help": ("f1",),
    "help_follow": ("enter",),
    "help_next_link": ("tab",),
    "help_previous_link": ("shift+tab",),
    "help_back": ("alt+left",),
    "help_forward": ("alt+right",),
    "help_index": ("alt+home",),
    "help_search": ("ctrl+f",),
    "help_close": ("escape",),
    "open_file": ("f3",),
    "save_file": ("f2",),
    "terminal_copy": (),
    "terminal_paste": (),
    "terminal_mouse": (),
    "adjust_left": ("left",),
    "adjust_right": ("right",),
    "adjust_up": ("up",),
    "adjust_down": ("down",),
    "adjust_switch": ("tab",),
    "adjust_accept": ("enter",),
    "adjust_cancel": ("escape",),
    "next_widget": ("tab",),
    "previous_widget": ("shift+tab",),
    "press_button": ("enter", " "),
    "area_up": ("up",),
    "area_down": ("down",),
    "area_page_up": ("pageup",),
    "area_page_down": ("pagedown",),
    "area_top": ("ctrl+home",),
    "area_bottom": ("ctrl+end",),
    "area_select_up": ("shift+up",),
    "area_select_down": ("shift+down",),
    "area_newline": ("enter",),
    "area_delete_line": ("ctrl+y",),
    "area_tab": ("tab",),
    "area_next_widget": ("ctrl+tab",),
    "area_previous_widget": ("shift+ctrl+tab",),
    "list_up": ("up",),
    "list_down": ("down",),
    "list_left": ("left",),
    "list_right": ("right",),
    "list_page_up": ("pageup",),
    "list_page_down": ("pagedown",),
    "list_home": ("home",),
    "list_end": ("end",),
    "list_toggle": (" ",),
    "list_select_all": ("ctrl+a",),
    "combo_open": ("alt+down", "f4"),
    "combo_previous": ("up",),
    "combo_next": ("down",),
    "collapsible_toggle": (" ", "enter"),
    "collapsible_expand": ("right",),
    "collapsible_collapse": ("left",),
    "suggest_open": ("alt+down", "f4"),
    "suggest_up": ("up",),
    "suggest_down": ("down",),
    "suggest_choose": ("enter",),
    "slider_decrease": ("left", "down"),
    "slider_increase": ("right", "up"),
    "slider_page_decrease": ("pagedown",),
    "slider_page_increase": ("pageup",),
    "slider_minimum": ("home",),
    "slider_maximum": ("end",),
    "spin_up": ("up",),
    "spin_down": ("down",),
    "spin_page_up": ("pageup",),
    "spin_page_down": ("pagedown",),
    "tree_expand": ("right",),
    "tree_collapse": ("left",),
    "tree_choose": ("enter",),
    "table_choose": ("enter",),
    "context_menu": ("shift+f10",),
    "tabs_left": ("left",),
    "tabs_right": ("right",),
    "tabs_next": ("ctrl+pagedown",),
    "tabs_previous": ("ctrl+pageup",),
    "splitter_decrease": ("left", "up"),
    "splitter_increase": ("right", "down"),
    "switch_toggle": (" ",),
    "switch_off": ("left",),
    "switch_on": ("right",),
    "option_up": ("up",),
    "option_down": ("down",),
    "option_left": ("left",),
    "option_right": ("right",),
    "option_press": (" ",),
    "dialog_cancel": ("escape",),
    "scroll_up": ("up",),
    "scroll_down": ("down",),
    "scroll_left": ("left",),
    "scroll_right": ("right",),
    "scroll_page_up": ("pageup",),
    "scroll_page_down": ("pagedown",),
    "text_left": ("left",),
    "text_right": ("right",),
    "text_home": ("home",),
    "text_end": ("end",),
    "text_word_left": ("ctrl+left",),
    "text_word_right": ("ctrl+right",),
    "text_select_left": ("shift+left",),
    "text_select_right": ("shift+right",),
    "text_select_home": ("shift+home",),
    "text_select_end": ("shift+end",),
    "text_select_word_left": ("shift+ctrl+left",),
    "text_select_word_right": ("shift+ctrl+right",),
    "text_select_all": ("ctrl+a",),
    "text_cut": ("ctrl+x",),
    "text_copy": ("ctrl+c",),
    "text_paste": ("ctrl+v",),
    "text_undo": ("ctrl+z",),
    "text_redo": ("alt+z", "shift+ctrl+z"),
    "text_backspace": ("backspace",),
    "text_delete": ("delete",),
    "text_clear": ("ctrl+y",),
    "open_menu": ("f10", "alt+space"),
    "menu_close": ("escape",),
    "menu_left": ("left",),
    "menu_right": ("right",),
    "menu_up": ("up",),
    "menu_down": ("down",),
    "menu_choose": ("enter",),
    "menu_mnemonic_modifiers": ("alt",),
}
"""Built-in shortcuts, by action."""

DESCRIPTIONS: dict[str, str] = {
    "exit": "Leave Dasha Desktop (when no menu is open)",
    "next_window": "Bring the next window to the front",
    "previous_window": "Bring the previous window to the front",
    "maximise_window": "Maximise the active window, or restore it",
    "minimise_window": "Minimise the active window (no key by default)",
    "close_window": "Close the active window",
    "move_window": "Move the active window with the keyboard",
    "resize_window": "Resize the active window with the keyboard",
    "show_mouse": "Show or hide where the mouse is, by inverting the cell under it",
    "command_prompt": "Leave for a command prompt (type exit to come back)",
    "help": "Show the help for what has the focus, if there is any; in help, "
    "go to the index",
    "help_follow": "In help: follow the highlighted link",
    "help_next_link": "In help: highlight the next link",
    "help_previous_link": "In help: highlight the previous link",
    "help_back": "In help: go back to the page before",
    "help_forward": "In help: go forward to the page after",
    "help_index": "In help: go to the index",
    "help_search": "In help: search all the topics",
    "help_close": "In help: close it",
    "open_file": "In an application that edits files: open one (File > Open...)",
    "save_file": "In an application that edits files: save it (File > Save)",
    "terminal_copy": "In a terminal: copy the text selected with the mouse "
    "(no key by default)",
    "terminal_paste": "In a terminal: send the clipboard's text to the program "
    "(no key by default)",
    "terminal_mouse": "In a terminal: switch between the mouse going to a program "
    "that asks for it and selecting text (no key by default)",
    "adjust_left": "While moving or resizing: left, or narrower",
    "adjust_right": "While moving or resizing: right, or wider",
    "adjust_up": "While moving or resizing: up, or shorter",
    "adjust_down": "While moving or resizing: down, or taller",
    "adjust_switch": "While moving or resizing: switch between the two",
    "adjust_accept": "While moving or resizing: keep the window there",
    "adjust_cancel": "While moving or resizing: put the window back",
    "next_widget": "Move the focus to the next control in a window",
    "previous_widget": "Move the focus to the previous control",
    "press_button": "Press the focused (or default) button",
    "area_up": "Move the cursor up a line in a text area",
    "area_down": "Move the cursor down a line in a text area",
    "area_page_up": "Move the cursor up a page in a text area",
    "area_page_down": "Move the cursor down a page in a text area",
    "area_top": "Move the cursor to the start of a text area",
    "area_bottom": "Move the cursor to the end of a text area",
    "area_select_up": "Select up a line in a text area",
    "area_select_down": "Select down a line in a text area",
    "area_newline": "Start a new line in a text area",
    "area_delete_line": "Delete the line the cursor is on in a text area",
    "area_tab": "Type a tab in a text area",
    "area_next_widget": "Move the focus to the next control, out of text areas too",
    "area_previous_widget": "Move the focus back a control, out of text areas too",
    "list_up": "Move to the item above in a list box",
    "list_down": "Move to the item below in a list box",
    "list_left": "Move a column left in a list box with columns",
    "list_right": "Move a column right in a list box with columns",
    "list_page_up": "Move a page back in a list box",
    "list_page_down": "Move a page on in a list box",
    "list_home": "Move to the first item in a list box",
    "list_end": "Move to the last item in a list box",
    "list_toggle": "Select or deselect the item in a multiple-selection list box "
    "or tree view",
    "list_select_all": "Select every item in a multiple-selection list box "
    "or tree view, or deselect them all if they all are",
    "combo_open": "Drop the list of a combo box down",
    "combo_previous": "Choose the item before in a combo box",
    "combo_next": "Choose the item after in a combo box",
    "collapsible_toggle": "Expand or collapse the collapsible area with the focus",
    "collapsible_expand": "Expand the collapsible area with the focus",
    "collapsible_collapse": "Collapse the collapsible area with the focus",
    "suggest_open": "Show an autocomplete box's suggestions without typing",
    "suggest_up": "Highlight the suggestion above in an autocomplete box",
    "suggest_down": "Highlight the suggestion below in an autocomplete box",
    "suggest_choose": "Take the highlighted suggestion into an autocomplete box",
    "slider_decrease": "Move a slider's knob a step towards its minimum",
    "slider_increase": "Move a slider's knob a step towards its maximum",
    "slider_page_decrease": "Move a slider's knob a page towards its minimum",
    "slider_page_increase": "Move a slider's knob a page towards its maximum",
    "slider_minimum": "Move a slider's knob to its minimum",
    "slider_maximum": "Move a slider's knob to its maximum",
    "spin_up": "Step the number in a spin box up",
    "spin_down": "Step the number in a spin box down",
    "spin_page_up": "Step the number in a spin box up a page",
    "spin_page_down": "Step the number in a spin box down a page",
    "tree_expand": "Open a tree view's highlighted item, or go to the first under it",
    "tree_collapse": "Close a tree view's highlighted item, or go to the one above it",
    "tree_choose": "Choose a tree view's highlighted item (or open or close it)",
    "table_choose": "Choose a table's highlighted row, if it has something to do",
    "context_menu": "Open the context menu of the focused widget (or its window)",
    "tabs_left": "Choose the tab on the left, on tabs with the focus",
    "tabs_right": "Choose the tab on the right, on tabs with the focus",
    "tabs_next": "Choose the next tab's page, anywhere in its window",
    "tabs_previous": "Choose the previous tab's page, anywhere in its window",
    "splitter_decrease": "Move the focused splitter's divider left (or up)",
    "splitter_increase": "Move the focused splitter's divider right (or down)",
    "switch_toggle": "Flip the switch with the focus",
    "switch_off": "Turn the switch with the focus off (the knob to the left)",
    "switch_on": "Turn the switch with the focus on (the knob to the right)",
    "option_up": "Move to the option above in check boxes or radio buttons",
    "option_down": "Move to the option below in check boxes or radio buttons",
    "option_left": "Move to the column on the left in check boxes or radio buttons",
    "option_right": "Move to the column on the right in check boxes or radio buttons",
    "option_press": "Check or uncheck the current check box; select a radio button",
    "dialog_cancel": "Cancel a dialog box",
    "scroll_up": "Scroll the active window's contents up a line",
    "scroll_down": "Scroll the active window's contents down a line",
    "scroll_left": "Scroll the active window's contents left",
    "scroll_right": "Scroll the active window's contents right",
    "scroll_page_up": "Scroll the active window's contents up a page",
    "scroll_page_down": "Scroll the active window's contents down a page",
    "text_left": "Move the cursor left in a text box or text area",
    "text_right": "Move the cursor right in a text box or text area",
    "text_home": "Move the cursor to the start of a text box, or of the line in a "
    "text area",
    "text_end": "Move the cursor to the end of a text box, or of the line in a "
    "text area",
    "text_word_left": "Move the cursor a word left in a text box or text area",
    "text_word_right": "Move the cursor a word right in a text box or text area",
    "text_select_left": "Select the character to the left in a text box or text "
    "area",
    "text_select_right": "Select the character to the right in a text box or text "
    "area",
    "text_select_home": "Select to the start of a text box, or of the line in a "
    "text area",
    "text_select_end": "Select to the end of a text box, or of the line in a text "
    "area",
    "text_select_word_left": "Select a word left in a text box or text area",
    "text_select_word_right": "Select a word right in a text box or text area",
    "text_select_all": "Select all the text in a text box or text area",
    "text_cut": "Cut the selected text in a text box or text area to the clipboard",
    "text_copy": "Copy the selected text in a text box or text area to the "
    "clipboard",
    "text_paste": "Paste text from the clipboard into a text box or text area",
    "text_undo": "Undo the last change in a text box or text area",
    "text_redo": "Redo the last change undone in a text box or text area",
    "text_backspace": "Delete the selection, or the character before the cursor, "
    "in a text box or text area",
    "text_delete": "Delete the selection, or the character at the cursor, in a "
    "text box or text area",
    "text_clear": "Empty a text box",
    "open_menu": "Open the menu bar's first menu (the system menu, on the "
    "desktop); close an open menu",
    "menu_close": "Close an open menu",
    "menu_left": "Open the menu to the left",
    "menu_right": "Open the menu to the right",
    "menu_up": "Highlight the previous item",
    "menu_down": "Highlight the next item",
    "menu_choose": "Choose the highlighted item",
    "menu_mnemonic_modifiers": "Modifiers that, with a title's letter, open a menu",
}

_PRETTY_NAMES = {
    "escape": "Esc",
    "pageup": "PgUp",
    "pagedown": "PgDn",
    "delete": "Del",
    "insert": "Ins",
}


def _split(name: str) -> tuple[list[str], str]:
    """Split a key name into modifiers and key.

    :param name: The key name.
    """
    if len(name) > 1 and name.endswith("++"):
        prefix, base = name[:-2], "+"
    else:
        prefix, _, base = name.rpartition("+")
    return (prefix.split("+") if prefix else []), base


class ShortcutsError(ValueError):
    """An unusable shortcuts file."""


def normalise_key(name: str) -> str | None:
    """A key name in standard form, or ``None``.

    :param name: The key name.
    """
    if len(name) == 1:
        return name
    prefixes, base = _split(name)
    modifiers = {prefix.lower() for prefix in prefixes}
    if not modifiers <= set(MODIFIERS) or len(modifiers) != len(prefixes):
        return None
    if len(base) != 1:
        base = base.lower()
        if base not in NAMED_KEYS:
            return None
    if base == "space" and not modifiers:
        base = " "
    if "ctrl" in modifiers:
        base = base.lower()  # Ctrl+letter is the same control code either way
    return "".join(f"{label}+" for label in MODIFIERS if label in modifiers) + base


def pretty_key(name: str) -> str:
    """A key name as people write it.

    :param name: The key name.
    """
    modifiers, base = _split(name)
    parts = [modifier.capitalize() for modifier in modifiers]
    if len(base) == 1:
        parts.append("Space" if base == " " else base.upper())
    else:
        parts.append(_PRETTY_NAMES.get(base, base.capitalize()))
    return "+".join(parts)


def key_from_pretty(text: str) -> str | None:
    """The key a pretty name stands for, or ``None``.

    :param text: The pretty name.
    """
    if len(text) == 1:
        return text.lower()
    prefixes, base = _split(text)
    if base == "":
        return None
    named = {pretty.lower(): name for name, pretty in _PRETTY_NAMES.items()}
    if len(base) == 1:
        base = base.lower()
    elif base.lower() not in ("space",):
        base = named.get(base.lower(), base.lower())
    return normalise_key("+".join([*prefixes, base]))


class Shortcuts:
    """The key bindings in effect.

    :param overrides: Keys by action, if any.
    """

    def __init__(self, overrides: Mapping[str, object] | None = None) -> None:
        self._bindings = dict(DEFAULTS)
        problems: list[str] = []
        for action, keys in (overrides or {}).items():
            if action not in DEFAULTS:
                problems.append(f'unknown action "{action}"')
                continue
            if isinstance(keys, str) or not isinstance(keys, Sequence):
                problems.append(f'"{action}" must be a list of key names')
                continue
            self._bindings[action] = self._check_keys(action, keys, problems)
        problems.extend(self._check_escape_routes())
        if problems:
            raise ShortcutsError("\n".join(problems))

    @staticmethod
    def _check_keys(
        action: str, keys: Sequence[object], problems: list[str]
    ) -> tuple[str, ...]:
        checked = []
        for key in keys:
            if not isinstance(key, str):
                problems.append(f'"{action}": {key!r} is not a key name')
            elif action == "menu_mnemonic_modifiers":
                if key.lower() in MODIFIERS:
                    checked.append(key.lower())
                else:
                    problems.append(
                        f'"{action}": "{key}" is not one of {", ".join(MODIFIERS)}'
                    )
            elif (normalised := normalise_key(key)) is not None:
                checked.append(normalised)
            else:
                problems.append(
                    f'"{action}": "{key}" is not a key name '
                    "(run dasha --key-test to see the names keys have)"
                )
        return tuple(checked)

    def _check_escape_routes(self) -> list[str]:
        """Ensure menus and the desktop can always be left."""
        problems = []
        if not self._bindings["exit"] and not self._bindings["open_menu"]:
            problems.append(
                '"exit" and "open_menu" cannot both be empty: '
                "there would be no way to leave Dasha Desktop from the keyboard"
            )
        if not self._bindings["dialog_cancel"] and not self._bindings["press_button"]:
            problems.append(
                '"dialog_cancel" and "press_button" cannot both be empty: '
                "there would be no way to answer a dialog box from the keyboard"
            )
        if not self._bindings["adjust_accept"] and not self._bindings["adjust_cancel"]:
            problems.append(
                '"adjust_accept" and "adjust_cancel" cannot both be empty: '
                "there would be no way to finish moving a window from the keyboard"
            )
        if (
            not self._bindings["area_next_widget"]
            and not self._bindings["area_previous_widget"]
        ):
            problems.append(
                '"area_next_widget" and "area_previous_widget" cannot both be '
                "empty: there would be no way to leave a text area by keyboard"
            )
        if not self._bindings["menu_close"] and not self._bindings["open_menu"]:
            problems.append(
                '"menu_close" and "open_menu" cannot both be empty: '
                "there would be no way to close a menu from the keyboard"
            )
        return problems

    @classmethod
    def load(cls, path: Path) -> "Shortcuts":
        """Load overrides from a JSON file.

        :param path: The shortcuts file.
        """
        try:
            data = read_json_object(path)
        except ConfigError as error:
            raise ShortcutsError(str(error)) from error
        return cls(data or {})

    def keys(self, action: str) -> tuple[str, ...]:
        """An action's keys.

        :param action: The action.
        """
        return self._bindings[action]

    def matches(self, action: str, key: str) -> bool:
        """Whether a key is bound to an action.

        :param action: The action.
        :param key: The key.
        """
        return key in self._bindings[action]

    def hint(self, action: str) -> str:
        """An action's first key, as a menu shows it.

        :param action: The action.
        """
        keys = self._bindings[action]
        return pretty_key(keys[0]) if keys else ""

    @property
    def bindings(self) -> dict[str, tuple[str, ...]]:
        """Every action's keys, as a copy."""
        return dict(self._bindings)

    @property
    def overrides(self) -> dict[str, list[str]]:
        """Bindings that differ from the defaults."""
        return {
            action: list(keys)
            for action, keys in self._bindings.items()
            if keys != DEFAULTS[action]
        }

    def to_json(self) -> str:
        """All the bindings as a JSON document, ready to save and edit."""
        return json.dumps(
            {action: list(keys) for action, keys in self._bindings.items()}, indent=4
        )
