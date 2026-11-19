# Dasha Framework

Dasha Framework is a text-mode desktop and application framework for local and
SSH terminals. It provides overlapping windows, menus, dialog boxes and a
full set of widgets, all drawn with code page 437 characters. It is written
in pure Python with **no third-party dependencies**: everything is built on
the standard library, using `termios` (on Linux and macOS) and `ctypes` (on
Windows) to talk to the terminal directly.

Applications can run on the Dasha Desktop, each in its own process, or
on their own in a terminal.

## Installing

Dasha Framework needs Python 3.12 or newer, on Windows, Linux or macOS:

```bash
python -m pip install dasha-framework
```

Or, from a copy of the repository:

```bash
python -m pip install .
```

Then start the desktop:

```bash
dasha desktop
```

(`dasha-desktop` is the same.) `dasha notepad` would run an installed application
on its own instead, and `dasha-desktop notepad` starts the desktop with it.

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

Once installed, the same class also runs on the desktop:

```bash
dasha install-app hello.py
```

The [tutorial](tutorial.md) builds a complete application, a text editor,
step by step. See also [Applications](architecture.md#applications-dashaapplication)
in the architecture guide, and {py:mod}`dasha.application` and
{py:mod}`dasha.widgets` in the API reference.

## Stability

The
[changelog](https://github.com/dashasierra/dasha-framework/blob/HEAD/CHANGELOG.md)
records what changes in each release. Everything in the API reference is available for you
to use. Names that start with an underscore (`_like_this`) are internal to
Dasha Framework, and may change in any release.

## Contents

```{toctree}
:maxdepth: 2

architecture
colours
development
shortcuts
tutorial
api
```
