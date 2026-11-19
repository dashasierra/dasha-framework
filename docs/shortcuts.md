# Keyboard shortcuts

Every Dasha Framework shortcut can be changed. This matters most over SSH and in
some terminals, where certain keys never reach Dasha Framework. The Alt key is the
most common problem, and some function keys are another.

- **Alt on macOS.** macOS Terminal and iTerm2 use Option to type special
  characters, unless they are set to "use Option as Meta".
- **F10 in Linux terminals.** GNOME Terminal and some others use F10 to open
  their own menu.
- **Multiplexers and remote tools.** tmux, screen and some remote desktop
  tools take certain key combinations for themselves.

If a shortcut does not work for you, remap it to one that does.

## Changing shortcuts in Settings...

To change shortcuts without editing a file, open the system menu and choose
**Settings...**, then the **Shortcuts** page. It lists every action with its
keys, and says what the highlighted action does.

- **Add key...** (or a double-click on the action) adds a key to the
  action: press the key you want. Every key counts, Escape and Enter
  included, so click Cancel to add none. For `menu_mnemonic_modifiers`,
  choose Alt, Ctrl or Shift instead.
- **Remove keys** takes every key away from the action, and **Default**
  gives it back its default keys. **Reset all** puts every action back to
  its defaults.
- **Load...** and **Save as...** read and write other shortcuts files.

A change works at once, everywhere, including in applications running in
their own processes. A change that would leave no way out by keyboard (see
below) is refused, with the reason. **OK** or **Apply** saves the shortcuts
to the shortcuts file, keeping only the actions that differ from the
defaults, and **Cancel** puts back the shortcuts you had before. Menu items
that an application has already made keep the key hints they were given
until the application makes them again, which it can do as soon as it is
told of the change (`Application.shortcuts_changed`).

## The shortcuts file

When it starts, Dasha Framework reads `~/.dasha/shortcuts.json` if the file
exists. `~` is your home folder, which is `C:\Users\<you>` on Windows. To use
a different file, run Dasha Framework with `--shortcuts FILE`.

To create the file with every default written out, ready to edit, run:

```bash
dasha --init-shortcuts
```

You only need to keep the actions you change; any action you leave out keeps
its default keys. For example, this file makes Dasha Framework usable without Alt
or F10:

```json
{
    "open_menu": ["ctrl+o"],
    "menu_mnemonic_modifiers": []
}
```

## Actions and defaults

This table lists every action and its default keys. It is generated from
`dasha.shortcuts` when the documentation is built, so it always matches
the code.

```{shortcut-actions}
```

`menu_mnemonic_modifiers` lists modifiers rather than keys. With the
default, Alt+F opens a menu titled `&File`. Use `["ctrl"]` to make that
Ctrl+F instead, or `[]` to turn the feature off. Once a menu is open,
pressing an item's underlined letter on its own always chooses it.

`help` (F1) opens the help of the active application, if it has any, at the
topic for whatever has the focus (see Help in the
[architecture](architecture.md)). It is not one of the keys the desktop keeps
for itself, so a widget that uses it comes first: F1 reaches the program
running in a terminal, for example. The other `help_*` actions work inside a
help window, which also scrolls with the `list_*` keys.

The system menu shows the first key bound to `exit` beside Shutdown.

`show_mouse` (`` Alt+` `` by default) and `command_prompt` (Alt+F12) work
wherever the focus is, even in a dialog or an application's window, so a key
bound to either reaches no window. The one exception is Add key... in
Settings..., which takes every key, so that they too can be added. The
system menu shows the first key bound to `command_prompt` beside Command
prompt.

A focused text box receives keys before its window does, so where its
`text_*` keys share a key with the `scroll_*` actions, the text box wins.
Keys bound to `next_widget`, `previous_widget` and `dialog_cancel` always
pass through to the window.

The status bar does not list keys that only edit text (`text_cut`, `text_copy`,
`text_paste`, `text_select_all`, `text_undo`, `text_redo`, `text_clear`,
`area_delete_line`, and those that move and select). They still work and can be
remapped like any other, and an Edit menu or a context menu still shows its
items' keys.

## Key names

Key names are the names that `dasha --key-test` shows. Run it and press
a key, and the name it prints is the one to put in the file. If a key shows
nothing, or shows as "not recognised", it cannot reach Dasha Framework in that
terminal or over that connection, so choose another. Press Ctrl+C to end the
key test.

| Kind | Names |
| --- | --- |
| Characters | `a`, `Q`, `1`, `?` |
| Named keys | `tab`, `enter`, `escape`, `backspace`, `insert`, `delete`, `home`, `end`, `pageup`, `pagedown`, `up`, `down`, `left`, `right`, `f1`–`f12` |
| With modifiers | `shift+tab`, `ctrl+o`, `alt+x`, `ctrl+right`, `shift+f6`, `alt+space` |

- **Modifiers** (`shift`, `alt`, `ctrl`) can be written in any order and
  case: `Ctrl+Alt+X` and `alt+ctrl+x` are the same key.
- **Case** matters only for a letter key, so `alt+X` means Alt+Shift+X.
  Ctrl ignores case, so `ctrl+Q` is the same as `ctrl+q`.
- **Ctrl and a letter** is the most dependable choice over SSH, because the
  terminal sends it as a single ordinary character. A few of these are
  already taken by other keys, though: Ctrl+I is Tab, Ctrl+M is Enter, and
  Ctrl+H is often Backspace.

## Safety checks

Dasha Framework checks the file before it takes over the screen. If anything is
wrong, it lists every problem and does not start. It looks for:

- an action name it does not know,
- a key name it does not know,
- a value that is not a list,
- invalid JSON.

To get going again, fix the file, or move it aside to use the defaults.

Dasha Framework also refuses a set of shortcuts that would leave the
keyboard with no way out of something:

- `exit` and `open_menu` cannot both be empty, because Shutdown is reached
  through the system menu.
- `menu_close` and `open_menu` cannot both be empty, because otherwise
  there would be no key to close a menu.
- `dialog_cancel` and `press_button` cannot both be empty, because
  otherwise there would be no key to answer a dialog box.
- `adjust_accept` and `adjust_cancel` cannot both be empty, because
  otherwise there would be no key to finish moving or resizing a window.
- `area_next_widget` and `area_previous_widget` cannot both be empty,
  because otherwise there would be no key to leave a text area, where Tab
  types a tab.

The mouse always works too: clicking the `≡` menu and choosing Shutdown
quits Dasha Framework, whatever the shortcuts are.

The file can be saved as UTF-8 (with or without a byte order mark) or as
UTF-16, which is what Windows PowerShell 5.1 writes with `>`.

## For developers

The bindings are held in `dasha.shortcuts.Shortcuts`. To use custom
bindings, pass a `Shortcuts` to `PresentationManager(shortcuts=...)`. To
respond to an action, check the key with `shortcuts.matches(action="action", key=key)`
rather than comparing keys directly, so that the user's remapping keeps
working.
