"""Notepad, step 1: a desktop, with a way out."""

from dasha.application import Application
from dasha.menu import Menu, MenuItem


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


if __name__ == "__main__":
    raise SystemExit(Notepad().run())
