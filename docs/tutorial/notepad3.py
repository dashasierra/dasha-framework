"""Notepad, step 3: somewhere to type."""

from dasha.application import Application
from dasha.canvas import Rect
from dasha.menu import Menu, MenuItem
from dasha.widgets import TextArea
from dasha.window import Window


class Notepad(Application):
    """Edit plain text files (UTF-8), each in a window of its own."""

    name = "Notepad"

    def start(self) -> None:
        self.menus = [
            Menu(
                title="&File",
                items=[
                    MenuItem(
                        label="E&xit",
                        action=self.exit,
                        status="Exits Notepad",
                    ),
                ],
            ),
        ]
        window = Window(
            title="Untitled",
            rect=Rect(row=2, column=4, height=15, width=60),
            resizable=True,
            maximisable=True,
            minimisable=True,
            closable=True,
        )
        window.add(widget=TextArea(row=0, column=0, name="text"))
        self.open(window=window)


if __name__ == "__main__":
    raise SystemExit(Notepad().run())
