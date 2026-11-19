# Example applications

This folder holds three applications written with Dasha Framework, to try it
out and to read as examples. They are not part of the `dasha` package and
are not installed with it; they are plain scripts kept in the repository.

| Script | Application | What it is |
| --- | --- | --- |
| `notepad.py` | Notepad | A plain text editor with a window for each file. Its File menu has New, Open..., Save, Save as..., Close and Exit, and it reads and writes UTF-8 files. It also has Edit and Insert menus, and a Format menu that turns word wrap and line numbers on and off. The foot of each window shows the cursor position, and a marker while there are unsaved changes. |
| `terminal.py` | Terminal | The user's shell, or another command-line program, in a window: see [Terminal](#terminal) below. Each window holds Dasha Framework's `TerminalView`. |
| `demo.py` | Demo | A tour of the widgets and dialogs: labels, text boxes, buttons, a switch, radio buttons and check boxes; a collapsible area, progress and column bars, sliders, a spin box and an autocomplete box; a list box of files in columns; the file dialogs, including choosing several files at once; a tree of folders to choose one from; an Explorer window of folders and files, split by a divider; a Settings dialog of tabs, group boxes, a paragraph and a password box; and help, which F1 opens from pages of Markdown in `demo_help/`. |

They pass every argument by name (`Label(text="Name:", row=2, column=1)`
rather than `Label("Name:", 2, 1)`), so that they read as a guide to the
framework.

## Running them

With Dasha Framework installed (`python -m pip install -e .` from the repository
root, or `pip install dasha-framework`), each one runs on its own, without the
desktop:

```bash
python apps/notepad.py notes.txt
```

```bash
python apps/demo.py
```

```bash
python apps/terminal.py
```

Alternatively, install them on the desktop, which lists them in its
Applications menu and starts each one in its own process:

```bash
dasha install-app apps/notepad.py
```

```bash
dasha install-app apps/demo.py
```

```bash
dasha install-app apps/terminal.py
```

```bash
dasha desktop
```

`dasha notepad` runs Notepad on its own, without the desktop, just as
`python apps/notepad.py` does, and `dasha-desktop notepad` (or `dasha desktop
notepad`) starts the desktop with Notepad on it.

To remove an application from the desktop again, run
`dasha uninstall-app notepad`.

## Terminal

Each Terminal window runs the user's shell: `SHELL` (or `/bin/sh`) on
Linux and macOS, and `COMSPEC` (or `cmd.exe`) on Windows. Give a command
to run that instead, such as `python apps/terminal.py pwsh` or
`python apps/terminal.py git log`; a window running a command it was given
stays open when the command ends, saying how it ended, while a shell's
window closes. Terminal > New window opens another shell, and on Windows,
New PowerShell window opens PowerShell (`pwsh`, or else `powershell`).
Terminal ends when its last window closes.

The program runs in a pseudo-terminal, so it behaves as it would in a
terminal of its own: prompts, line editing, colours (16, 256 and 24-bit),
Ctrl+C and full-screen programs such as `less` all work, and resizing the
window resizes the terminal. On Linux and macOS this is `os.forkpty`, with
`TERM` set to `xterm-256color`. On Windows it is a pseudoconsole (ConPTY),
which needs Windows 10 version 1809 or later. All of this is Dasha Framework's
own (`dasha.pseudoterminal`, `dasha.vt` and the
`dasha.widgets.TerminalView` widget), so any application can put a
terminal in a window; Terminal adds the windows and menus.

**Keys.** Every key goes to the program, except those the desktop keeps
for itself: by default Ctrl+Q, F5, F6, Shift+F6, F10, Alt+Space, Alt+F3,
Alt+F4, Alt+F7, Ctrl+F5, Alt+F8, Alt+F12 and `` Alt+` ``. Alt+T and Alt+E
open Terminal's own menus, as F10 does, and Alt+W opens the desktop's Window
menu, so those three do not reach the shell. Alt and any other letter (Alt+B,
Alt+F and the rest of the shell's line editing) does, but Alt+T's transpose
words in a shell is lost. To send one of the desktop's keys
to the program, choose it from Terminal > Send key, which lists them as
the shortcuts in use say. To have one reach the program every time, give
its desktop action another key in `~/.dasha/shortcuts.json` (see
`docs/shortcuts.md`).

**The mouse and the clipboard.** The mouse wheel scrolls back through the
lines that went off the top (the last 1000), and the foot of the window
shows how far, as `↑N`; any key comes back down. Dragging with the left
button selects text, which Edit > Copy (or Copy on the right-click menu)
puts on the clipboard. Edit > Paste, and pasting through your terminal
itself, type the clipboard's text into the program, marked as a paste for
a program that asks (so a shell does not run it line by line). Copy and
Paste have no keys by default, as Ctrl+C and Ctrl+V belong to the
program; give them keys with the `terminal_copy` and `terminal_paste`
actions.

**The mouse in full-screen programs.** A program that asks to be told of
the mouse (vim, htop, mc and other full-screen programs) gets clicks,
drags and the mouse wheel instead, and the foot of the window shows
`Mouse` while it does. To select text in such a program, hold Shift while
you drag (where your own terminal passes Shift and the mouse on), or turn
off Terminal > Mouse to programs, which the mouse then selects text in
every window until you turn it on again. The `terminal_mouse` action
gives that a key; it has none by default.

**Limits.** Wide characters (most CJK characters and emoji) take their two
columns but are shown as `?`, as everywhere in Dasha Framework. Moving the mouse
with no button held is not passed on (for programs that follow the pointer
itself), text is not rewrapped when the window is resized, and some of
what editors such as vim ask of a terminal is not done yet.

## Their tests

The applications have their own tests, separate from Dasha Framework's. Run them
from this folder, so that the scripts can be imported:

```bash
cd apps
python -m unittest discover -s tests -v
```

Type-check and lint them from this folder too, with Dasha Framework installed
(or with `src` on `MYPYPATH` and `PYTHONPATH`):

```bash
python -m mypy --strict .
```

pylint only finds `.pylintrc` by itself in the folder it runs from, so name
it explicitly:

```bash
python -m pylint --rcfile=../.pylintrc *.py tests
```
