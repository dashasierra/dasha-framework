"""Notepad, step 4: a window class, and more windows."""

from collections.abc import Callable
from typing import Protocol

from dasha.application import Application
from dasha.canvas import Rect
from dasha.menu import Menu, MenuItem, separator
from dasha.widgets import TextArea
from dasha.window import Window


class NotepadWindow(Window):
    """One file being edited: a window holding nothing but a text area."""

    def __init__(
        self,
        notepad: "Notepad",
        rect: Rect,
    ) -> None:
        super().__init__(
            title="Untitled",
            rect=rect,
            resizable=True,
            maximisable=True,
            minimisable=True,
            closable=True,
        )
        self.notepad = notepad
        self.area = self.add(
            widget=TextArea(
                row=0,
                column=0,
                name="text",
            )
        )


class WindowAction(Protocol):  # pylint: disable=too-few-public-methods
    """Something to do with a Notepad window, given as ``window=``."""

    def __call__(self, *, window: NotepadWindow) -> object: ...


class Notepad(Application):
    """Edit plain text files (UTF-8), each in a window of its own."""

    name = "Notepad"

    def start(self) -> None:
        self.menus = self._menus()
        self.new()

    def _place(self) -> Rect:
        """Where the next window goes: each a little down and right of the
        one before."""
        step = len(self.windows) % 6
        return Rect(row=2 + step, column=4 + 2 * step, height=15, width=60)

    def new(self) -> NotepadWindow:
        """Open a window for a new file."""
        window = NotepadWindow(notepad=self, rect=self._place())
        self.open(window=window)
        return window

    def _front(self) -> NotepadWindow | None:
        """Its window nearest the front of the desktop: the file its menus
        act on."""
        window = self.active_window
        return window if isinstance(window, NotepadWindow) else None

    def _on_front(self, act: WindowAction) -> Callable[[], None]:
        """A menu action: ``act(window=...)`` on the front window, if there
        is one by the time the item is chosen."""

        def action() -> None:
            window = self._front()
            if window is not None:
                act(window=window)

        return action

    # Menus

    def _menus(self) -> list[Menu]:
        """Notepad's menu bar. Items that need a file are greyed out while
        no window is open."""
        return [
            Menu(title="&File", items=self._file_items()),
        ]

    def _file_items(self) -> list[MenuItem]:
        assert self.manager is not None
        hint = self.manager.shortcuts.hint
        return [
            MenuItem(
                label="&New",
                action=self.new,
                status="Starts a new file in a new window",
            ),
            separator(),
            MenuItem(
                label="&Close",
                action=self._on_front(act=lambda window: self.close(window=window)),
                shortcut=hint(action="close_window"),
                status="Closes this file",
                enabled=self.has_window,
            ),
            MenuItem(
                label="E&xit",
                action=self.exit,
                status="Exits Notepad",
            ),
        ]


if __name__ == "__main__":
    raise SystemExit(Notepad().run())
