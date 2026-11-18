"""A dialog for choosing a file, to open or to save.

The dialog only chooses a path: whether the file is to be opened or saved
depends on the dialog's title, and on what the calling code does with the
answer::

    dialog = FileDialog(
        title="Open", filters=[("Text files", "*.txt")], must_exist=True
    )
    if manager.execute(dialog=dialog) == "ok":
        load(path=dialog.path)

    dialog = FileDialog(title="Save as", name="notes.txt")
    if manager.execute(dialog=dialog) == "ok":
        save(path=dialog.path)  # ask about overwriting with confirm(), if wanted
"""

import fnmatch
import ntpath
import os
import string
import time
from collections.abc import Sequence

from dasha.dialog import Dialog
from dasha.widgets import Button, ComboBox, Label, ListBox, TextBox, Widget

ALL_FILES = ("All files", "*")
"""The filter used when none are given, and offered after any that are
given."""


def list_drives() -> list[str]:
    """The drives on this computer, as roots (``C:\\``), on Windows, or an
    empty list on other systems. Uses ``os.listdrives`` where Python has
    it."""
    if os.name != "nt":
        return []
    listdrives = getattr(os, "listdrives", None)
    if listdrives is not None:
        try:
            return [str(drive) for drive in listdrives()]
        except OSError:
            pass
    roots = (f"{letter}:{os.sep}" for letter in string.ascii_uppercase)
    return [root for root in roots if os.path.exists(root)]


def _drive_of(path: str) -> str:
    """A path's drive, as the drive list shows it (``C:``), or ""."""
    return ntpath.splitdrive(path)[0].upper()  # drives are Windows's alone


def _size_text(size: int) -> str:
    return f"{size:,} byte" + ("" if size == 1 else "s")


class FileDialog(Dialog):  # pylint: disable=too-many-instance-attributes
    """Choose a file::

        ╔═[■]═══════════════════ Open ═══════════════════════╗
        ║ Name                                               ║
        ║  notes.txt                            OK        ▄  ║
        ║ Files                                  ▀▀▀▀▀▀▀▀▀▀  ║
        ║  ..\\              │ notes.txt        Cancel    ▄  ║
        ║  docs\\            │ readme.txt        ▀▀▀▀▀▀▀▀▀▀  ║
        ║  ...                                               ║
        ║ Type  All files (*)         ▼  Drive  C:   ▼       ║
        ║ C:\\GitHub\\dasha                                  ║
        ║ notes.txt  1,204 bytes  17 Oct 2026 10:30          ║
        ╚════════════════════════════════════════════════════╝

    The list shows ``..`` (except at the top of a drive), then the
    folders, marked with ``os.sep``, and then the files that match the
    chosen type, with each group sorted alphabetically, ignoring case.
    Highlighting an item puts its name in the Name box and its details on the
    bottom line.

    OK (or Enter) reads the Name box. A folder (``..``, ``docs\\``, or a
    typed path to a folder) is opened; a name containing ``*`` or ``?``
    becomes the filter; and anything else is the answer, so the dialog
    answers ``"ok"``. With ``must_exist``, the file must already exist
    (otherwise the dialog says "No such file"). A double-click on an item is
    the same as choosing it and pressing OK. Typed paths can be absolute, or
    relative to the folder shown.

    ``filters`` is a list of (label, pattern) pairs, and a pattern can
    combine several with ``;`` (``"*.py;*.pyw"``). "All files" is added
    unless one of the filters already matches everything. On Windows, a
    Drive box offers the other drives.

    Afterwards, ``path`` is the full path of the chosen file, ``directory``
    is its folder, and ``name`` is its name.
    """

    list_rows: int = 8
    """How many rows of names the file list shows at once."""
    show_drives: bool = os.name == "nt"
    """Whether the dialog has a Drive box (which it does on Windows)."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        title: str,
        *,
        directory: str = ".",
        filters: Sequence[tuple[str, str]] = (),
        name: str = "",
        must_exist: bool = False,
        status: str = "",
    ) -> None:
        width = 54
        super().__init__(title, width, self.list_rows + 8, status=status)
        self.must_exist = must_exist
        self.filters = list(filters)
        if not any(pattern == "*" for _, pattern in self.filters):
            self.filters.append(ALL_FILES)
        self.directory = os.path.abspath(directory)
        """The folder shown (and, once answered, the chosen file's folder)."""
        self.name = name
        """The chosen file's name, once answered."""
        self.path = ""
        """The chosen file in full, once answered ``"ok"``."""
        self._typed_filter: str | None = None
        self._entries: list[tuple[str, bool]] = []  # (name, is a folder)
        self._refreshing = False
        self._text_width = width - 4
        self._build(name)
        if not self.refresh():
            self.directory = os.path.abspath(os.sep)
            self.refresh()

    def _build(self, name: str) -> None:
        """Lay the widgets out, in the order Tab visits them."""
        rows, field = self.list_rows, 36
        self.add(Label("Name", 0, 1))
        self.name_box = self.add(TextBox(1, 1, field, text=name, name="name"))
        self.add(Label("Files", 2, 1))
        self.files = self.add(
            ListBox(
                [],
                3,
                1,
                field,
                rows,
                columns=2,
                on_change=self._highlighted,
                on_choose=self._chosen,
                name="files",
            )
        )
        bottom = rows + 3
        self.add(Label("Type", bottom, 1))
        self.type_box = self.add(
            ComboBox(
                [f"{label} ({pattern})" for label, pattern in self.filters],
                bottom,
                7,
                26 if self.show_drives else field - 6,
                on_change=self._type_changed,
                name="type",
            )
        )
        self.drive_box: ComboBox | None = None
        if self.show_drives:
            self.add(Label("Drive", bottom, 35))
            self.drive_box = self.add(
                ComboBox(
                    [_drive_of(root) for root in list_drives()] or ["C:"],
                    bottom,
                    41,
                    8,
                    on_change=self._drive_changed,
                    name="drive",
                )
            )
        self.add(Button("&OK", 1, 39, result="ok", default=True, name="ok"))
        self.add(Button("&Cancel", 4, 39, result="cancel", name="cancel"))
        self.path_label = self.add(Label("", bottom + 1, 1, name="directory"))
        self.info_label = self.add(Label("", bottom + 2, 1, name="info"))

    # The list

    @property
    def pattern(self) -> str:
        """The filter in use: one typed into the Name box, or else the selected
        type's."""
        if self._typed_filter is not None:
            return self._typed_filter
        return self.filters[self.type_box.value][1]

    def matches(self, name: str) -> bool:
        """Whether a file's name matches the filter."""
        patterns = [part.strip() for part in self.pattern.split(";")]
        return any(fnmatch.fnmatch(name, part) for part in patterns if part)

    def refresh(self, highlight: str | None = None) -> bool:
        """Read the folder shown again, highlighting the item named
        ``highlight`` if it is there. Returns whether the folder could be
        read; if it could not, the list is left as it was, and the bottom
        line says so."""
        try:
            with os.scandir(self.directory) as scan:
                found = [(entry.name, entry.is_dir()) for entry in scan]
        except OSError:
            self.say("Cannot read this folder")
            return False
        folders = sorted((n for n, d in found if d), key=str.casefold)
        files = sorted(
            (n for n, d in found if not d and self.matches(n)), key=str.casefold
        )
        self._entries = [(name, True) for name in folders]
        self._entries += [(name, False) for name in files]
        if os.path.dirname(self.directory) != self.directory:
            self._entries.insert(0, (os.pardir, True))
        self.files.set_items(self._shown(entry) for entry in self._entries)
        names = [entry_name for entry_name, _ in self._entries]
        self._refreshing = True  # the Name box keeps what it holds
        self.files.move_to(names.index(highlight) if highlight in names else 0)
        self._refreshing = False
        self._show_directory()
        self.say("")
        return True

    @staticmethod
    def _shown(entry: tuple[str, bool]) -> str:
        name, folder = entry
        return name + os.sep if folder else name

    def _show_directory(self) -> None:
        text = self.directory
        if len(text) > self._text_width:
            text = "..." + text[-(self._text_width - 3) :]
        self.path_label.text = text
        if self.drive_box is not None:
            drive = _drive_of(self.directory)
            if drive in self.drive_box.items:
                self.drive_box.set_items(
                    self.drive_box.items, self.drive_box.items.index(drive)
                )

    def say(self, text: str) -> None:
        """Show a line of details (or a problem) at the bottom of the
        dialog."""
        self.info_label.text = text[: self._text_width]

    def change_directory(self, directory: str, highlight: str | None = None) -> bool:
        """Show another folder, and return whether it could be read (if it
        could not, the folder shown stays as it was)."""
        before = self.directory
        self.directory = os.path.abspath(directory)
        if self.refresh(highlight):
            return True
        self.directory = before
        return False

    # Answering

    def _highlighted(self, box: ListBox) -> None:
        """The highlight moved: put the item in the Name box and describe it."""
        index = box.value
        if not isinstance(index, int) or not self._entries or self._refreshing:
            return
        name, folder = self._entries[index]
        self.name_box.text = self._shown(self._entries[index])
        if folder:
            self.say("Folder")
            return
        try:
            info = os.stat(os.path.join(self.directory, name))
        except OSError:
            self.say(name)
            return
        when = time.strftime("%d %b %Y %H:%M", time.localtime(info.st_mtime))
        self.say(f"{name}  {_size_text(info.st_size)}  {when}")

    def _chosen(self, box: ListBox) -> None:
        """A double-click: OK on that item."""
        self._highlighted(box)
        self.accept()

    def _type_changed(self, box: ComboBox) -> None:
        del box
        self._typed_filter = None
        self.refresh()

    def _drive_changed(self, box: ComboBox) -> None:
        drive = box.selected_item
        if not self.change_directory(drive + os.sep):
            self._show_directory()  # back to the drive it was on

    def button_pressed(self, button: Widget) -> None:
        """Pressing OK ends the dialog only once the Name box holds a file."""
        if button.name == "ok":
            self.accept()
        else:
            super().button_pressed(button)

    def accept(self) -> None:
        """Act on what the Name box holds: open a folder, set the filter, or
        answer ``"ok"`` with the file."""
        typed = self.name_box.text.strip()
        if not typed and self.focused is self.files and self.files.items:
            typed = self.files.items[self.files.cursor]  # Enter on the list
        if not typed:
            return
        if "*" in typed or "?" in typed:
            self._typed_filter = typed
            self.refresh()
            return
        path = os.path.normpath(os.path.join(self.directory, os.path.expanduser(typed)))
        if os.path.isdir(path):
            came_from = os.path.basename(self.directory)
            going_up = os.path.normpath(typed.rstrip("\\/")) == os.pardir
            if self.change_directory(path, came_from if going_up else None):
                self.name_box.text = ""
            return
        if self.must_exist and not os.path.isfile(path):
            self.say("No such file")
            return
        if not os.path.isdir(os.path.dirname(path)):
            self.say("No such folder")
            return
        self.path = path
        self.directory, self.name = os.path.split(path)
        self.result = "ok"
