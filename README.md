# Dasha Framework

**Dasha Framework** is a text-mode application framework for terminals, both local and
over SSH.

Dasha Framework has **no third-party dependencies**. It is built entirely on the
Python standard library, using `ctypes` and similar modules to talk to the
terminal directly.

## Features

**The desktop**

- Overlapping windows that can be moved, resized, maximised, minimised and
  closed with the mouse or the keyboard, each with a drop shadow and with
  scroll bars on its frame when needed.
- A menu bar with drop-down menus, submenus, mnemonics and shortcut keys;
  context menus; and a status bar showing help and clickable key hints.
- Several applications side by side, each in its own process, so one that
  crashes or hangs affects only its own windows.
- Themes (Default, Dark, Monochrome, or your own) and animations, both of
  which can be changed while Dasha Framework is running and are remembered.
- Settings... in the system menu changes everything that the command line
  and the settings files do: the theme and every colour, the keyboard
  shortcuts, animations, the applications to start with the desktop, and
  the installed applications. It saves to the same files.
- A command prompt (Alt+F12) for running commands without shutting
  Dasha Framework down: your own shell, until you type `exit`.

**For applications**

- An `Application` class that runs unchanged either on the desktop or on
  its own in a terminal.
- Widgets: labels, buttons, text boxes and text areas (with undo, the
  clipboard, word wrap and line numbers), check boxes, radio buttons,
  switches, list boxes, combo boxes, autocomplete boxes, spin boxes,
  sliders, progress bars, tables, tree views (picking one item or several,
  with items loaded as they are expanded), tabs, splitters, group boxes and
  collapsible areas.
- Dialog boxes, ready-made questions and a file dialog.
- Help windows, opened with F1: an application's own pages of Markdown, with
  links between them, history and search, going straight to the topic for
  the widget with the focus. Dasha Framework has help of its own for the desktop.
- Installed applications can have their own virtual environments, for
  libraries that Dasha Framework does not include.

**Standards and safety**

- **Pure Python 3.12 or newer, using only the standard library**, with no
  third-party runtime dependencies. The package is fully typed (PEP 561,
  `py.typed`).
- **Windows, Linux and macOS**, locally or over SSH, using ANSI/VT (ECMA-48)
  escape sequences. Dasha Framework uses the alternate screen, xterm SGR mouse
  reporting (mode 1006) and bracketed paste, as well as the kitty keyboard
  protocol and xterm's "modifyOtherKeys" where a terminal supports them.
- **Code page 437** for everything it draws, so that any terminal font can
  display it, in the 16 standard colours, the 256-colour palette, or 24-bit
  RGB colour (drawn as the nearest of the 256, or of the 16, where a
  terminal cannot show it).
  Dasha Framework honours [`NO_COLOR`](https://no-color.org).
- **Every key can be remapped, and every colour is a theme role**, set in
  Settings... or in a JSON file of your own.
- **Nothing reaches the terminal unchecked.** Control characters in a file,
  a title or any other text are displayed as their code page 437 pictures,
  and are never sent to the terminal to act on. Applications talk to the
  desktop through a versioned JSON protocol, and every message is checked
  when it arrives, so no application can harm the desktop or impersonate
  another.
- Releases follow [Semantic Versioning](https://semver.org), and changes
  are recorded in the [changelog](https://github.com/dashasierra/dasha-framework/blob/HEAD/CHANGELOG.md)
  in the [Keep a Changelog](https://keepachangelog.com) format. Dasha Framework is
  licensed under the Apache License 2.0.

## Requirements

- Python 3.12 or newer
- Windows, Linux or macOS

## Quick start

```bash
python -m venv .venv
```

Activate the environment (`.venv\Scripts\activate` on Windows,
`source .venv/bin/activate` elsewhere), then install Dasha Framework:

```bash
python -m pip install dasha-framework
```

Or, from a copy of this repository, install it in editable mode:

```bash
python -m pip install -e .
```

Then start the desktop:

```bash
dasha desktop
```

or, for short:

```bash
dasha-desktop
```

Run on its own, `dasha` only shows its usage: it needs `desktop`, or an
application to run. The desktop starts empty. The Applications submenu of the
system menu (`≡`) lists the installed applications. None come with the
package, but the repository's `apps/` folder has three to try: Notepad, a
Demo of the widgets, and Terminal, which runs your shell in a window (see [apps/README.md](https://github.com/dashasierra/dasha-framework/blob/HEAD/apps/README.md)).
Install them with:

```bash
dasha install-app apps/notepad.py
```

```bash
dasha install-app apps/demo.py
```

```bash
dasha install-app apps/terminal.py
```

Then start the desktop (`dasha desktop`) and choose them from the
Applications menu, or name them to start them on it straight away:

```bash
dasha-desktop notepad
```

(`dasha desktop notepad` is the same.) You can also name an application to
run it on its own, without the desktop, exactly as running its script
would:

```bash
dasha notepad
```

## Writing an application

An application is a class with a `start` method, which sets up its menus
and opens its windows. It keeps running until it exits (File > Exit, here),
not merely until its windows are closed. It can run on its own, with no
desktop to set up:

```python
from dasha.application import Application
from dasha.canvas import Rect
from dasha.menu import Menu, MenuItem
from dasha.window import Window


class Hello(Application):
    name = "Hello"

    def start(self) -> None:
        self.menus = [
            Menu(title="&File", items=[MenuItem(label="E&xit", action=self.exit)])
        ]
        self.open(
            window=Window(
                title="Hello",
                rect=Rect(row=2, column=2, height=6, width=30),
                lines=["Hello, world"],
                closable=True,
            )
        )


if __name__ == "__main__":
    raise SystemExit(Hello().run())
```

The same class also runs on the Dasha Desktop, in its own process. To
list it in the Applications menu, install it. If it needs libraries that
Dasha Framework does not include, it can have a virtual environment of its own:

```bash
dasha install-app hello.py
```

```bash
dasha install-app hello.py --create-venv --pip "nltk==3.8.1"
```

`dasha list-apps` lists the installed applications, and `dasha
hello` runs this one on its own, just as `python hello.py` does. For more,
see [Applications](https://github.com/dashasierra/dasha-framework/blob/HEAD/docs/architecture.md#applications-dashaapplication)
and [Installing applications](https://github.com/dashasierra/dasha-framework/blob/HEAD/docs/architecture.md#installing-applications-dasharegistry-dashainstall)
in the architecture guide, and the example applications in `apps/`.

### Command-line options

`dasha --help` lists these too.

| Option | What it does |
| --- | --- |
| `-h`, `--help` | List the options, and the application commands |
| `-v`, `--version` | Show Dasha Framework's version |
| `-s FILE`, `--shortcuts FILE` | Use this keyboard shortcuts file (default `~/.dasha/shortcuts.json`) |
| `--init-shortcuts` | Write the default shortcuts to the shortcuts file, ready to edit |
| `-c FILE`, `--colours FILE` | Use this colours file (default `~/.dasha/colours.json`) |
| `--init-colours` | Write the default colours to the colours file, ready to edit |
| `--init-theme NAME` | Write a new theme, `NAME`, to edit, in `~/.dasha/themes/` |
| `--monochrome` | Use the Monochrome theme: no colours, only bold, underline and reverse video |
| `-d DEPTH`, `--colour-depth DEPTH` | Draw colours at `24bit`, `256` or `16` colours, or `auto` (the default); remembered for next time |
| `-m`, `--show-mouse` | Invert the cell under the mouse, for terminals that show no pointer; remembered for next time |
| `-k`, `--key-test` | Show the name of each key as you press it (Ctrl+C to finish) |
| `desktop [APP ...]` | Start the desktop, with these applications on it (as `dasha-desktop [APP ...]` does) |
| `APP ...` | Run just these applications, by id or name, without the desktop |

An application can be named by its id (`dasha notepad`) or by its name, in
any case (`dasha Notepad`): an application with the id `dasha-github`, called
Git, starts with `dasha git` too. An id comes first, and a name that more
than one application has is refused, with their ids to choose from.
`dasha list-apps` shows each one's id and name.

One of the last two is needed, except with `--init-shortcuts`,
`--init-colours`, `--init-theme` or `--key-test`: `dasha` with nothing to
run shows its usage and an error.

`-d` and `-m` are kept in `~/.dasha/settings.toml`, as Settings...
keeps them, so you need give them only once: `dasha desktop -d 16` starts in
16 colours from then on. `-d auto` goes back to letting Dasha Framework decide,
and `` Alt+` `` or Settings... stops showing the mouse.

If something goes wrong inside Dasha Framework itself, it writes the details to a
log in `~/.dasha/logs/`, tells you where, and carries on, so that your
applications and their work are not lost. If it says so, save your work and
restart Dasha Framework, and please report the log.

If arrow keys or function keys sometimes act as Escape over a slow SSH
connection, raise how long Escape waits for the rest of a key (Settings...,
the Desktop page; 100 ms by default). If a shortcut does not work in your
terminal or over SSH (Alt keys often do not), you can remap it: see [docs/shortcuts.md](https://github.com/dashasierra/dasha-framework/blob/HEAD/docs/shortcuts.md).
To see exactly what your terminal sends for each key, run:

```bash
dasha --key-test
```

For a terminal without colour, run `dasha desktop --monochrome`, or set
`NO_COLOR` to keep colour out altogether (the themes cannot be changed until
it is removed). To change the colours while Dasha Framework is running, choose a
theme from the system menu's Themes: Default, Dark, Monochrome, or one of
your own in `~/.dasha/themes/` (see [docs/colours.md](https://github.com/dashasierra/dasha-framework/blob/HEAD/docs/colours.md)).
Menus drop down, and windows zoom as they are minimised, maximised and
restored. To turn these animations off, or back on, choose Animations from
the system menu.

If your terminal shows no mouse pointer, press `` Alt+` `` (or run
`dasha desktop -m`) to show where the mouse is: the cell under it is
inverted. Press `` Alt+` `` again to stop. Dasha Framework remembers the choice.

To run commands without shutting Dasha Framework down, press Alt+F12 or choose
Command prompt from the system menu. Your own screen and shell come back:
`cmd.exe` on Windows (`COMSPEC`), or `$SHELL` elsewhere. Type `exit` to
return to the desktop exactly as you left it. Your applications keep
running meanwhile.

Everything above can also be changed from within Dasha Framework: choose
Settings... from the system menu. Its pages cover the theme and each part of
the screen's colours (RGB colours included), the keyboard shortcuts,
animations, how colours are drawn, showing the mouse and the
applications to start with the desktop, and installing and uninstalling
applications. Changes show at once; OK or Apply saves them to the usual
files (the colours file, the shortcuts file and `settings.toml`), and Cancel
puts them back.

## Development

See [docs/development.md](https://github.com/dashasierra/dasha-framework/blob/HEAD/docs/development.md).

## Documentation

To build the documentation, run this from the repository root with the
virtual environment activated:

```bash
python -m sphinx -W --keep-going -E -b html docs docs/_build/html
```

The built pages are written to `docs/_build/html`.

## Project layout

```
src/dasha/      the package (src layout, so tests run against the installed code)
frozen/        the entry point of a PyInstaller build of dasha (dasha.spec)
tests/         unittest test suite
apps/          example applications and their tests (not in the package)
docs/          project documentation
```

## Licence

Copyright 2026 - Dasha Sierra

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this software except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Apache License 2.0 - see [LICENSE](https://github.com/dashasierra/dasha-framework/blob/HEAD/LICENSE).
