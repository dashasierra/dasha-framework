"""Small applications for process tests."""

import time
from pathlib import Path

from dasha.application import Application
from dasha.canvas import Rect
from dasha.menu import Menu, MenuItem
from dasha.shortcuts import Shortcuts
from dasha.widgets import TextBox
from dasha.window import Window


class Hello(Application):
    """One window, with a text box."""

    name = "Hello"

    def start(self) -> None:
        window = Window("Hello", Rect(2, 2, 6, 30), ["Hello"], closable=True)
        window.add(TextBox(2, 1, 20, name="text"))
        self.open(window)


class Helpful(Application):
    """One window with a help topic."""

    name = "Helpful"
    help_folder = Path(__file__).parent / "hosted_help"

    def start(self) -> None:
        window = Window("Helpful", Rect(2, 2, 6, 30), closable=True)
        window.add(TextBox(2, 1, 20, name="text")).help = "text_box"
        self.open(window)


class SlowToStart(Application):
    """Takes its time to start, and then has menus and a window."""

    name = "Slow"

    def start(self) -> None:
        time.sleep(0.5)
        self.menus = [Menu("&File", [MenuItem("E&xit", self.exit)])]
        self.open(Window("Slow", Rect(2, 2, 6, 30), closable=True))


class SlowToBreak(Application):
    """Takes its time to start, and then fails."""

    name = "Slow break"

    def start(self) -> None:
        time.sleep(0.3)
        raise RuntimeError("broken on purpose")


class NeverStarts(Application):
    """Connects to the desktop, and never gets any further."""

    name = "Never"

    def start(self) -> None:
        while True:
            time.sleep(0.05)


class Broken(Application):
    """Fails as it starts."""

    name = "Broken"

    def start(self) -> None:
        raise RuntimeError("broken on purpose")


class _HangingWindow(Window):
    """Hangs, for good, when H is pressed."""

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        if key == "h":
            while True:
                time.sleep(0.05)
        return super().handle_key(key, shortcuts)


class Hangs(Application):
    """An application that stops responding when H is pressed."""

    name = "Hangs"

    def start(self) -> None:
        self.open(_HangingWindow("Hangs", Rect(2, 2, 6, 30), closable=True))
