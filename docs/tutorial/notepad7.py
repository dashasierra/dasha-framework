"""Notepad, step 7: not losing work."""

import os
import sys
from collections.abc import Callable, Sequence
from typing import Protocol

from dasha.application import Application
from dasha.canvas import Rect
from dasha.config import write_atomically
from dasha.dialog import confirm, information, question
from dasha.filedialog import FileDialog
from dasha.menu import Menu, MenuItem, separator
from dasha.widgets import TextArea
from dasha.window import Window

FILTERS = [("Text files", "*.txt;*.md;*.log;*.ini;*.cfg"), ("Python", "*.py")]
"""The file types Notepad's Open and Save as dialogs offer."""


def line_ending(text: str) -> str:
    """A text's line ending.

    :param text: The text.
    """
    return "\r\n" if "\r\n" in text else "\n"


class NotepadWindow(Window):
    """One file being edited.

    :param notepad: The application.
    :param rect: Position and size.
    :param path: The file, if any.
    :param text: The file's text.
    """

    def __init__(
        self,
        notepad: "Notepad",
        rect: Rect,
        path: str | None = None,
        text: str = "",
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
        self.path = path
        """The file it was opened from or saved to; ``None`` until saved."""
        self.newline = line_ending(text=text)
        """The file's line ending."""
        self.area = self.add(
            widget=TextArea(
                row=0,
                column=0,
                text=text,
                on_change=self._changed,
                name="text",
            )
        )
        self.modified = False
        """Whether there are changes since it was opened or saved."""
        self._show_title()

    @property
    def file_name(self) -> str:
        """The file's name, or "Untitled"."""
        return os.path.basename(self.path) if self.path else "Untitled"

    def _show_title(self) -> None:
        self.title = self.file_name

    def _changed(self, area: TextArea) -> None:
        del area
        self.modified = True

    def load(self, path: str, text: str) -> None:
        """Show a file's text.

        :param path: The file.
        :param text: Its text.
        """
        self.path = path
        self.newline = line_ending(text=text)
        self.area.text = text
        self.modified = False
        self._show_title()

    # Saving

    def save(self) -> bool:
        """Save; return whether saved."""
        if self.path is None:
            return self.save_as()
        try:
            # Whole or not at all: a failed save leaves the file as it was.
            write_atomically(
                path=self.path,
                text=self.area.text.replace("\n", self.newline),
                newline="",
            )
        except OSError as error:
            self.notepad.tell(
                title="Save",
                message=f"Cannot save {self.file_name}:\n{error.strerror}",
            )
            return False
        self.modified = False
        return True

    def save_as(self) -> bool:
        """Save under a new name; return whether saved."""
        manager = self.notepad.manager
        if manager is None or not manager.is_running:
            return False
        dialog = FileDialog(
            title="Save as",
            directory=os.path.dirname(self.path) if self.path else ".",
            filters=FILTERS,
            name=self.file_name if self.path else "untitled.txt",
        )
        if manager.execute(dialog=dialog) != "ok":
            return False
        if os.path.exists(dialog.path) and dialog.path != self.path:
            ask = confirm(
                title="Save as",
                message=f"{dialog.name} already exists.\nReplace it?",
                ok_label="&Replace",
            )
            if manager.execute(dialog=ask) != "ok":
                return False
        before, self.path = self.path, dialog.path
        if not self.save():
            self.path = before  # not saved: still the file it was
            return False
        self._show_title()
        return True

    def offer_to_save(self) -> bool:
        """Offer to save changes; return whether to go on."""
        manager = self.notepad.manager
        if not self.modified or manager is None or not manager.is_running:
            return True
        if self.manager is manager:
            manager.bring_to_front(window=self)
        dialog = question(
            title="Notepad",
            message=f"Save the changes to {self.file_name}?",
            answers=[
                ("&Save", "save"),
                ("&Don't save", "discard"),
                ("&Cancel", "cancel"),
            ],
            status="Save the changes first, close without them, or carry on",
        )
        answer = manager.execute(dialog=dialog)
        if answer == "save":
            return self.save()
        if answer == "discard":
            self.modified = False
            return True
        return False

    def request_close(self) -> bool:
        return self.offer_to_save()


class WindowAction(Protocol):  # pylint: disable=too-few-public-methods
    """Something to do with a Notepad window, given as ``window=``."""

    def __call__(self, *, window: NotepadWindow) -> object: ...


class Notepad(Application):
    """Edit plain text files, each in its own window.

    :param paths: Files to open at start.
    """

    name = "Notepad"

    def __init__(self, paths: Sequence[str] = ()) -> None:
        super().__init__()
        self.paths = list(paths)
        """Files to open at start."""

    def start(self) -> None:
        self.menus = self._menus()
        for path in self.paths:
            self.open_path(path=path)
        if not self.windows:
            self.new()

    def _place(self) -> Rect:
        """Where the next window goes."""
        step = len(self.windows) % 6
        return Rect(row=2 + step, column=4 + 2 * step, height=15, width=60)

    def new(self, path: str | None = None, text: str = "") -> NotepadWindow:
        """Open a window for a new file.

        :param path: The file, if any.
        :param text: Initial text.
        """
        window = NotepadWindow(notepad=self, rect=self._place(), path=path, text=text)
        self.open(window=window)
        return window

    def show(self, window: NotepadWindow) -> None:
        """Bring a window to the front.

        :param window: The window.
        """
        if self.manager is not None:
            self.manager.show_window(window=window)

    def tell(self, title: str, message: str) -> None:
        """Show a message, once running.

        :param title: Title text.
        :param message: The message.
        """
        manager = self.manager
        if manager is None:
            return
        dialog = information(title=title, message=message)
        manager.call_when_running(callback=lambda: manager.execute(dialog=dialog))

    # Opening

    def read(self, path: str) -> str | None:
        """A file's text, or ``None`` after saying why not.

        :param path: The file.
        """
        try:
            with open(path, encoding="utf-8", newline="") as file:
                return file.read()
        except UnicodeDecodeError:
            self.tell(
                title="Open",
                message=f"{os.path.basename(path)} is not UTF-8 text.",
            )
        except OSError as error:
            self.tell(
                title="Open",
                message=f"Cannot open {os.path.basename(path)}:\n{error.strerror}",
            )
        return None

    def open_path(self, path: str) -> NotepadWindow | None:
        """Open a file.

        :param path: The file.
        """
        path = os.path.abspath(path)
        for window in self.windows:
            if isinstance(window, NotepadWindow) and window.path == path:
                self.show(window=window)
                return window
        text = "" if not os.path.exists(path) else self.read(path=path)
        if text is None:
            return None
        front = self._front()
        if (
            front is not None
            and front.path is None
            and not front.modified
            and not front.area.text
        ):
            front.load(path=path, text=text)
            return front
        return self.new(path=path, text=text)

    def open_file(self) -> None:
        """Choose a file to open (File > Open...)."""
        manager = self.manager
        if manager is None or not manager.is_running:
            return
        front = self._front()
        start = os.path.dirname(front.path) if front and front.path else "."
        dialog = FileDialog(
            title="Open",
            directory=start,
            filters=FILTERS,
            must_exist=True,
        )
        if manager.execute(dialog=dialog) == "ok":
            self.open_path(path=dialog.path)

    def _front(self) -> NotepadWindow | None:
        """The front window."""
        window = self.active_window
        return window if isinstance(window, NotepadWindow) else None

    def _on_front(self, act: WindowAction) -> Callable[[], None]:
        """Run an action on the front window.

        :param act: The action.
        """

        def action() -> None:
            window = self._front()
            if window is not None:
                act(window=window)

        return action

    # Closing

    def can_close(self) -> bool:
        return all(
            window.offer_to_save()
            for window in self.windows
            if isinstance(window, NotepadWindow)
        )

    # Menus

    def _menus(self) -> list[Menu]:
        """Notepad's menu bar."""
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
            MenuItem(
                label="&Open...",
                action=self.open_file,
                shortcut=hint(action="open_file"),
                status="Opens a file",
            ),
            MenuItem(
                label="&Save",
                action=self._on_front(act=lambda window: window.save()),
                shortcut=hint(action="save_file"),
                status="Saves this file",
                enabled=self.has_window,
            ),
            MenuItem(
                label="Save &as...",
                action=self._on_front(act=lambda window: window.save_as()),
                status="Saves under a new name",
                enabled=self.has_window,
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
                status="Exits, offering to save each changed file",
            ),
        ]


if __name__ == "__main__":
    raise SystemExit(Notepad(paths=sys.argv[1:]).run())
