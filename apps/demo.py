"""Demo: a tour of Dasha Framework's widgets and dialogs.

- The Widgets window: labels, text boxes, buttons, a switch, and a dialog
  of radio buttons and check boxes.
- More widgets: progress and column bars, sliders, a spin box and an
  autocomplete box.
- Files: a two-column list box of made-up files, scrolling sideways, with
  Open and Save as file dialogs and a dialog that picks several files.
- Choose folder...: a dialog of this computer's own folders in a tree, each
  folder's folders found only when it is first expanded, to pick one.
- Explorer: a window split in two, a tree of folders beside a table of
  their files (sorted by a click on a heading, with a context menu), and a
  divider to drag.
- Settings...: a dialog of two pages on tabs: a paragraph of wrapped text
  and group boxes, and a password box with a switch that shows it.
- Help: pages of Markdown in the ``demo_help`` folder, which F1 opens at the
  topic of the widget with the focus, in a dialog too.

Run it on its own with ``python apps/demo.py``, or install it on the desktop
with ``dasha install-app apps/demo.py``.
"""

# Each example application is meant to be read on its own, so they spell
# their menus out alike rather than share code.
# pylint: disable=duplicate-code

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dasha.application import Application
from dasha.canvas import Rect
from dasha.dialog import Dialog, information
from dasha.filedialog import FileDialog, list_drives
from dasha.menu import Menu, MenuItem, separator
from dasha.style import BLACK, WHITE, Style
from dasha.widgets import (
    AutoCompleteBox,
    Button,
    CheckBoxes,
    Collapsible,
    Column,
    ColumnBar,
    GroupBox,
    Grow,
    Label,
    ListBox,
    Paragraph,
    PasswordBox,
    ProgressBar,
    RadioButtons,
    Slider,
    SpinBox,
    Splitter,
    Switch,
    Table,
    Tabs,
    TextBox,
    TreeNode,
    TreeView,
)
from dasha.window import Window

DARK_BODY = Style(foreground=WHITE, background=BLACK)
"""The window's colours with its Dark mode switch on."""

SITES = [
    "example.com",
    "example.org",
    "docs.python.org",
    "python.org",
    "pypi.org",
    "github.com",
    "wikipedia.org",
]
"""What the autocomplete box suggests."""

DEMO_FILES = [
    "autoexec.bat", "build.log", "changes.txt", "command.com", "config.sys",
    "dialogs.py", "draft.doc", "editor.cfg", "fonts.dat", "games.lst",
    "help.txt", "index.htm", "install.exe", "letter.doc", "licence.txt",
    "menus.py", "notes.txt", "palette.dat", "photo.bmp", "plan.txt",
    "readme.txt", "report.doc", "setup.ini", "shell.exe", "sounds.dat",
    "todo.txt", "tools.lst", "turtle.exe", "windows.py", "zip.exe",
]  # fmt: skip
"""Made-up file names for the list boxes."""


class Demo(Application):
    """Windows of widgets, one with a button that asks a question in a
    dialog box and shows the answer it gets back, and a list of files with
    file dialogs."""

    name = "Demo"
    help_folder = Path(__file__).parent / "demo_help"

    def start(self) -> None:
        def on_files(method: str) -> Callable[[], None]:
            """Run one of the front Files window's methods (``open_file``,
            say)."""

            def action() -> None:
                window = self.active_window
                if isinstance(window, FilesWindow):
                    getattr(window, method)()

            return action

        assert self.manager is not None
        hint = self.manager.shortcuts.hint
        self.menus = [
            Menu(
                title="&File",
                items=[
                    MenuItem(
                        label="&New window",
                        action=self.new_window,
                        status="Another Widgets window",
                    ),
                    MenuItem(
                        label="&More widgets",
                        action=self.more_widgets,
                        status="Bars, sliders, a spin box and suggestions",
                    ),
                    MenuItem(
                        label="&Files",
                        action=self.new_files_window,
                        status="A list of files, with file dialogs",
                    ),
                    separator(),
                    MenuItem(
                        label="&Open...",
                        action=on_files(method="open_file"),
                        shortcut=hint(action="open_file"),
                        status="Picks a file to open (with a Files window in front)",
                        enabled=self.files_in_front,
                    ),
                    MenuItem(
                        label="&Save",
                        action=None,  # greyed out: nothing to save here
                        shortcut=hint(action="save_file"),
                        status="Saves the current file",
                    ),
                    MenuItem(
                        label="Save &as...",
                        action=on_files(method="save_as"),
                        status="Picks where to save (with a Files window in front)",
                        enabled=self.files_in_front,
                    ),
                    separator(),
                    MenuItem(
                        label="&Pick several...",
                        action=on_files(method="pick_several"),
                        status="Picks files (with a Files window in front)",
                        enabled=self.files_in_front,
                    ),
                    MenuItem(
                        label="&Choose folder...",
                        action=self.choose_folder,
                        status="Picks a folder from a tree of this computer's folders",
                    ),
                    separator(),
                    MenuItem(
                        label="&Explorer",
                        action=self.explorer,
                        status="Folders and files, split by a divider to drag",
                    ),
                    MenuItem(
                        label="Se&ttings...",
                        action=self.settings,
                        status="Tabs, group boxes, a paragraph and a password box",
                    ),
                    separator(),
                    MenuItem(label="E&xit", action=self.exit, status="Exits"),
                ],
            ),
            Menu(
                title="&Help",
                items=[
                    MenuItem(
                        label="&Help",
                        action=self.show_help,
                        shortcut=hint(action="help"),
                        status="Help on what has the focus",
                        enabled=self.has_help,
                    ),
                ],
                after_window=True,
            ),
        ]
        self.new_files_window()
        self.more_widgets()
        self.new_window()

    def settings(self) -> None:
        """File > Settings...: a dialog of two pages of settings; say what
        was chosen (of the password, only its length)."""
        assert self.manager is not None
        dialog = settings_dialog()
        if self.manager.execute(dialog=dialog) != "ok":
            return
        values = dialog.values
        name, password = values["name"], values["password"]
        assert isinstance(name, str) and isinstance(password, str)
        self.manager.execute(
            dialog=information(
                title="Settings",
                message=f"Signed in as {name or 'nobody'}, with a password of "
                f"{len(password)} characters.\nVolume {values['volume']}.",
            )
        )

    def choose_folder(self) -> None:
        """File > Choose folder...: pick one of the computer's folders, and
        say which."""
        assert self.manager is not None
        dialog = folder_dialog(directory=os.getcwd())
        if self.manager.execute(dialog=dialog) == "ok":
            tree = dialog.widget(name="folders")
            assert isinstance(tree, TreeView)
            node = tree.selected_node
            if node is not None:
                self.manager.execute(
                    dialog=information(
                        title="Choose folder", message=f"Chose {node.data}"
                    )
                )

    def explorer(self) -> None:
        """File > Explorer: open a window of folders and their files."""
        self.open(window=explorer_window())

    def files_in_front(self) -> bool:
        """Whether the demo's front window is a Files window (the file
        dialogs' menu items are greyed out otherwise)."""
        return isinstance(self.active_window, FilesWindow)

    def new_window(self) -> None:
        """File > New window: open another Widgets window."""
        self.open(window=self.widgets_window())

    def more_widgets(self) -> None:
        """File > More widgets: open a window of the other widgets."""
        self.open(window=more_widgets_window())

    def new_files_window(self) -> None:
        """File > Files: open another list of files."""
        self.open(window=self.files_window())

    def widgets_window(self) -> Window:  # pylint: disable=too-many-locals
        """A Widgets window."""
        assert self.manager is not None
        manager = self.manager
        window = Window(
            title="Widgets",
            rect=Rect(row=3, column=40, height=15, width=38),
            status="Tab moves between the text boxes, buttons and switch",
            closable=True,
            minimisable=True,
        )
        window.help = "widgets"  # F1 on any widget with no topic of its own
        window.add(
            widget=Label(text="Labels, text boxes and buttons:", row=1, column=1)
        )
        window.add(widget=Label(text="Name:", row=3, column=1))
        name = window.add(
            widget=TextBox(
                row=3,
                column=7,
                width=16,
                max_length=40,
                name="name",
                status="Any text, up to 40 characters; it scrolls when it is longer",
            )
        )
        name.help = "name"  # F1 on this box goes to demo_help/name.md
        window.add(widget=Label(text="Age:", row=4, column=1))
        age = window.add(
            widget=TextBox(
                row=4,
                column=7,
                width=5,
                pattern=r"[0-9]*",
                max_length=3,
                name="age",
                status="Digits only (the pattern [0-9]*), at most 3",
            )
        )
        age.help = "age"
        clicks = window.add(
            widget=Label(text="Clicks: 0", row=6, column=1, name="clicks")
        )
        answer = window.add(
            widget=Label(text="Not asked yet", row=7, column=1, name="answer")
        )
        count = [0]

        def click(_button: Button) -> None:
            count[0] += 1
            clicks.text = f"Clicks: {count[0]}"

        def reset(_button: Button) -> None:
            count[0] = 0
            clicks.text = "Clicks: 0"

        def ask(_button: Button) -> None:
            # The dialog pattern: execute() waits for the answer and returns
            # it, and this code reads the dialog's widgets to see what was
            # chosen.
            dialog = survey_dialog()
            if manager.execute(dialog=dialog) != "ok":
                answer.text = "Not asked yet"
                return
            rating = dialog.widget(name="rating")
            tried = dialog.widget(name="tried")
            assert isinstance(rating, RadioButtons) and isinstance(tried, CheckBoxes)
            who = name.text or "You"
            answer.text = f"{who}: {rating.selected_label}, tried {len(tried.value)}"

        window.add(
            widget=Button(
                label="&Click me",
                row=9,
                column=1,
                action=click,
                status="Counts the clicks",
            )
        )
        window.add(
            widget=Button(
                label="&Reset",
                row=9,
                column=15,
                width=8,
                action=reset,
                status="Back to 0",
            )
        )
        window.add(
            widget=Button(
                label="&Ask...",
                row=9,
                column=25,
                width=9,
                action=ask,
                status="Asks in a dialog",
            )
        )

        def dark(switch: Switch) -> None:
            # Set on this window only, so the other windows keep their colours.
            window.body_style = DARK_BODY if switch.on else Window.body_style

        window.add(
            widget=Switch(
                label="&Dark mode",
                row=11,
                column=1,
                on_change=dark,
                name="dark",
                status="A switch: Space, Left/Right, a click or Alt+D flips it",
            )
        )
        return window

    def files_window(self) -> "FilesWindow":  # pylint: disable=too-many-locals
        """A Files window."""
        assert self.manager is not None
        manager = self.manager
        files = FilesWindow(
            title="Files",
            rect=Rect(row=5, column=24, height=11, width=34),
            status="Arrows move, the bar scrolls; File > Open picks a file",
            resizable=True,
            maximisable=True,
            minimisable=True,
            closable=True,
        )
        files.help = "files"
        chosen = Label(text="Selected: autoexec.bat", row=7, column=1, name="chosen")

        def show(box: ListBox) -> None:
            chosen.text = f"Selected: {', '.join(box.selected_items)}"

        def open_one(box: ListBox) -> None:
            chosen.text = f"Opened {', '.join(box.selected_items)}"

        files.add(
            widget=ListBox(
                items=DEMO_FILES,
                row=0,
                column=0,
                width=32,
                height=7,
                columns=2,
                on_change=show,
                on_choose=open_one,
                name="files",
                status="Moving selects; type a name to find it; double-click opens",
            ),
            grow=Grow.ALL,  # fills the window as it is resized or maximised
        )
        files.add(widget=chosen, grow=Grow.STICK_BOTTOM)

        def open_file() -> None:
            dialog = FileDialog(
                title="Open",
                filters=[("Text files", "*.txt;*.md"), ("Python", "*.py")],
                must_exist=True,
                status="Choose a file to open",
            )
            if manager.execute(dialog=dialog) == "ok":
                chosen.text = f"Opened {dialog.path}"

        def save_as() -> None:
            dialog = FileDialog(
                title="Save as",
                name="untitled.txt",
                status="Name of file",
            )
            if manager.execute(dialog=dialog) == "ok":
                chosen.text = f"Saved as {dialog.path}"

        def pick_several() -> None:
            dialog = pick_several_dialog()
            if manager.execute(dialog=dialog) == "ok":
                box = dialog.widget(name="files")
                assert isinstance(box, ListBox)
                count = len(box.selected_items)
                chosen.text = f"Opened {count} file{'' if count == 1 else 's'}"

        files.open_file = open_file
        files.save_as = save_as
        files.pick_several = pick_several
        return files


def more_widgets_window() -> Window:
    """A window of a collapsible area of options, progress and column bars,
    each driven by a slider, a spin box, and an autocomplete box."""
    window = Window(
        title="More widgets",
        rect=Rect(row=2, column=2, height=17, width=46),
        status="Tab moves between the options, sliders and boxes",
        closable=True,
        minimisable=True,
    )
    window.add(
        widget=Label(text="Bars, sliders, spin and suggest boxes:", row=1, column=1)
    )
    # Laid out as though collapsed: expanding it moves everything below down.
    options = window.add(
        widget=Collapsible(
            label="&Options",
            name="options",
            row=3,
            column=1,
            status="Space, Enter, Right/Left or a click shows or hides the options",
        )
    )
    options.add(
        widget=CheckBoxes(
            labels=["&Bold", "&Italic"],
            row=0,
            column=2,
            columns=2,
            name="style",
            status="Options inside the area: they hide with it",
        )
    )
    options.add(widget=Label(text="Note:", row=1, column=2))
    options.add(
        widget=TextBox(
            row=1, column=8, width=20, name="note", status="Any text: it hides too"
        )
    )
    window.add(widget=Label(text="Progress:", row=5, column=1))
    progress = window.add(
        widget=ProgressBar(row=5, column=11, length=22, value=40, name="progress")
    )
    window.add(widget=Label(text="Slide it:", row=7, column=1))
    window.add(
        widget=Slider(
            row=7,
            column=11,
            length=22,
            value=40,
            on_change=lambda slider: setattr(progress, "value", slider.value),
            name="slider",
            status="Left/Right, PgUp/PgDn, Home/End or the mouse: fills the bar",
        )
    )
    window.add(widget=Label(text="Copies:", row=9, column=1))
    window.add(
        widget=SpinBox(
            row=9,
            column=11,
            width=8,
            minimum=1,
            maximum=99,
            name="copies",
            status="1 to 99: Up/Down, the arrows, or type it (others are undone)",
        )
    )
    window.add(widget=Label(text="Site:", row=11, column=1))
    window.add(
        widget=AutoCompleteBox(
            row=11,
            column=11,
            width=22,
            suggestions=SITES,
            name="site",
            status="Type: suggestions follow, but any text will do (F4 lists them)",
        )
    )
    column = window.add(
        widget=ColumnBar(row=3, column=36, length=10, thickness=1, value=70)
    )
    window.add(
        widget=Slider(
            row=3,
            column=41,
            length=10,
            vertical=True,
            value=70,
            on_change=lambda slider: setattr(column, "value", slider.value),
            name="level",
            status="Up/Down or the mouse: fills the column",
        )
    )
    return window


def settings_dialog() -> Dialog:  # pylint: disable=too-many-locals
    """A dialog of two pages of settings, on tabs: General, with a paragraph
    and two group boxes, and Account, with a password box and a switch that
    shows the password."""
    dialog = Dialog(
        title="Settings",
        width=56,
        height=20,
        status="Ctrl+PgDn and Ctrl+PgUp change page",
    )
    tabs = dialog.add(
        widget=Tabs(
            row=1,
            column=2,
            width=50,
            height=13,
            status="Left/Right, a click or a letter chooses a page",
        )
    )
    general = tabs.add_page(label="&General")
    account = tabs.add_page(label="Accou&nt")
    general.add(
        widget=Paragraph(
            text="Settings for show: nothing here is saved, or sent anywhere.",
            row=0,
            column=1,
            width=46,
        )
    )
    display = general.add(
        widget=GroupBox(title="&Display", row=2, column=1, width=24, height=5)
    )
    display.add(
        widget=CheckBoxes(
            labels=["&Window shadows", "Show &time"],
            row=0,
            column=1,
            checked=[0],
            name="display",
        )
    )
    sound = general.add(
        widget=GroupBox(title="&Sound", row=2, column=26, width=22, height=5)
    )
    sound.add(widget=Label(text="Volume:", row=0, column=1))
    sound.add(
        widget=Slider(
            row=1,
            column=1,
            length=18,
            value=60,
            name="volume",
            status="Left/Right, PgUp/PgDn, Home/End or the mouse",
        )
    )
    group = account.add(
        widget=GroupBox(title="&Account", row=0, column=1, width=46, height=6)
    )
    group.add(widget=Label(text="Name:", row=0, column=1))
    group.add(widget=TextBox(row=0, column=11, width=30, name="name"))
    group.add(widget=Label(text="Password:", row=1, column=1))
    password = group.add(
        widget=PasswordBox(
            row=1,
            column=11,
            width=30,
            name="password",
            status="Bullets only; Ctrl+C copies nothing",
        )
    )

    def show(switch: Switch) -> None:
        password.revealed = switch.on

    group.add(
        widget=Switch(
            label="S&how password",
            row=2,
            column=1,
            on_change=show,
            name="show",
            status="Shows the password as it is, or as bullets",
        )
    )
    dialog.add(
        widget=Button(
            label="&OK", row=15, column=14, result="ok", default=True, name="ok"
        )
    )
    dialog.add(
        widget=Button(
            label="&Cancel", row=15, column=30, result="cancel", name="cancel"
        )
    )
    return dialog


FOLDERS = {
    "Documents": [n for n in DEMO_FILES if n.endswith((".doc", ".txt", ".htm"))],
    "Programs": [n for n in DEMO_FILES if n.endswith((".exe", ".com", ".bat", ".py"))],
    "Settings": [n for n in DEMO_FILES if n.endswith((".ini", ".cfg", ".sys"))],
    "Other": [
        n
        for n in DEMO_FILES
        if not n.endswith(
            (
                ".doc",
                ".txt",
                ".htm",
                ".exe",
                ".com",
                ".bat",
                ".py",
                ".ini",
                ".cfg",
                ".sys",
            )
        )
    ],
}
"""The made-up files, in made-up folders, for the Explorer window."""


KINDS = {
    ".bat": "Batch",
    ".cfg": "Settings",
    ".com": "Program",
    ".dat": "Data",
    ".doc": "Document",
    ".exe": "Program",
    ".htm": "Web page",
    ".ini": "Settings",
    ".log": "Log",
    ".lst": "List",
    ".py": "Python",
    ".sys": "System",
    ".txt": "Text",
    ".bmp": "Picture",
}
"""What kind of file each ending is, for the Explorer's Type column."""


def file_row(name: str) -> list[str]:
    """A file's row in the Explorer's table: its name, kind and a made-up
    size in kilobytes."""
    ending = name[name.rfind(".") :]
    size = sum(ord(char) for char in name) * 7 % 900 + 1
    return [name, KINDS.get(ending, "File"), str(size)]


def folder_tree() -> list[TreeNode]:
    """The made-up folders: Programs has one inside it, found only when it
    is first opened (as a real folder's would be)."""

    def tools(_node: TreeNode) -> list[TreeNode]:
        return [TreeNode(label="Tools", data=["install.exe", "zip.exe"])]

    folders = [
        TreeNode(label=name, data=files, load=tools if name == "Programs" else None)
        for name, files in FOLDERS.items()
    ]
    return [TreeNode(label="C:", children=folders, expanded=True, data=[])]


def folder_nodes(path: str) -> list[TreeNode]:
    """The folders in a folder, in order of name, as items of a tree. Each
    one's ``data`` is its path, and its own folders are found only when it is
    first expanded. A folder that cannot be read has none."""

    def load(node: TreeNode) -> list[TreeNode]:
        return folder_nodes(path=node.data)

    try:
        with os.scandir(path) as entries:
            names = [entry.name for entry in entries if entry.is_dir()]
    except OSError:
        return []
    names.sort(key=str.casefold)
    return [
        TreeNode(label=name, data=os.path.join(path, name), load=load) for name in names
    ]


def folder_roots() -> list[TreeNode]:
    """The tops of the tree of folders: the drives on Windows, or ``/``."""
    tops = list_drives() or [os.sep]
    return [
        TreeNode(label=top, data=top, load=lambda node: folder_nodes(path=node.data))
        for top in tops
    ]


def find_folder(roots: list[TreeNode], directory: str) -> TreeNode | None:
    """The item of a folder in the tree, finding the folders on the way to
    it, or if it cannot be found, the nearest folder above it that can
    (``None`` if none can). The tree holds folders' real names, so the
    path is resolved first: a Windows short name (``RUNNER~1``) or a link
    (macOS's ``/var``) would otherwise find only the folders above it."""
    target = os.path.normcase(os.path.realpath(directory))
    nodes, found = roots, None
    while True:
        for node in nodes:
            path = os.path.normcase(node.data)
            if target == path or target.startswith(path.rstrip(os.sep) + os.sep):
                found = node
                break
        else:
            return found
        assert found is not None
        if os.path.normcase(found.data) == target:
            return found
        found.loaded()
        nodes = found.children


def folder_dialog(directory: str) -> Dialog:
    """A dialog of a tree of the computer's folders, to pick one, starting at
    ``directory``. The ``folders`` tree view's highlighted item is the folder
    picked, and its ``data`` is the folder's path."""
    dialog = Dialog(
        title="Choose folder",
        width=52,
        height=18,
        status="OK chooses the highlighted folder",
    )
    roots = folder_roots()
    path = Label(text="", row=12, column=2, name="path")

    def show(tree: TreeView) -> None:
        node = tree.selected_node
        text = str(node.data) if node is not None else ""
        path.text = text if len(text) <= 46 else "..." + text[-43:]

    dialog.add(widget=Label(text="Folders:", row=1, column=2))
    tree = dialog.add(
        widget=TreeView(
            roots=roots,
            row=2,
            column=2,
            width=46,
            height=10,
            selected=find_folder(roots=roots, directory=directory),
            on_change=show,
            name="folders",
            status="Right/Left or a click on the marker expand and collapse; "
            "type to find a folder",
        )
    )
    show(tree=tree)
    dialog.add(widget=path)
    dialog.add(widget=Button(label="&OK", row=14, column=12, result="ok", default=True))
    dialog.add(widget=Button(label="&Cancel", row=14, column=26, result="cancel"))
    return dialog


def explorer_window() -> Window:  # pylint: disable=too-many-locals
    """A window split in two: a tree of folders on the left, a table of the
    highlighted folder's files on the right, with a context menu, and the
    divider between them to drag."""
    window = Window(
        title="Explorer",
        rect=Rect(row=4, column=8, height=14, width=64),
        status="Drag the divider, or Tab to it and use Left/Right",
        resizable=True,
        maximisable=True,
        minimisable=True,
        closable=True,
    )
    splitter = window.add(
        widget=Splitter(
            row=0,
            column=0,
            width=62,
            height=12,
            position=18,
            minimum=10,
            name="splitter",
            status="Left/Right move the divider",
        ),
        grow=Grow.ALL,  # fills the window; the right pane takes what it gains
    )
    files = Table(
        columns=[
            Column(title="Name", width=14),
            Column(title="Type", width=9),
            Column(title="Size K", width=7, align="right", key=int),
        ],
        rows=[],
        row=0,
        column=0,
        width=43,
        height=12,
        name="files",
        status="Double-click or Enter opens; click a heading to sort; "
        "right-click for a menu",
    )

    def show(tree: TreeView) -> None:
        node = tree.selected_node
        files.set_rows(
            rows=[file_row(name=name) for name in (node.data if node else [])]
        )

    folders = splitter.first.add(
        widget=TreeView(
            roots=folder_tree(),
            row=0,
            column=0,
            width=18,
            height=12,
            on_change=show,
            name="folders",
            status="Right/Left open and close folders; moving shows their files",
        )
    )
    folders.grow = Grow.ALL  # fills its pane, however the divider moves
    splitter.second.add(widget=files)
    files.grow = Grow.ALL

    def say(message: str) -> None:
        if window.manager is not None:
            window.manager.execute(
                dialog=information(title="Explorer", message=message)
            )

    def open_file() -> None:
        rows = files.selected_rows
        if rows:
            say(message=f"Opened {rows[0][0]} (not really).")

    def delete_file() -> None:
        index = files.value
        if isinstance(index, int):
            files.set_rows(rows=[row for n, row in enumerate(files.data) if n != index])

    files.on_choose = lambda _table: open_file()  # a double-click, or Enter
    files.context_menu = Menu(
        title="File",
        items=[
            MenuItem(
                label="&Open",
                action=open_file,
                shortcut="Enter",
                status="Opens the file (so does a double-click)",
            ),
            separator(),
            MenuItem(label="&Rename", action=None, status="Not here yet"),
            MenuItem(
                label="&Delete", action=delete_file, status="Takes it off the list"
            ),
        ],
    )
    window.focus(widget=folders)  # rather than the divider, added first
    folders.move_to(index=1)  # Documents, so the table has files to show
    return window


def survey_dialog() -> Dialog:
    """A dialog of radio buttons (pick one) and check boxes (pick any), the
    check boxes in two columns with one option greyed out."""
    dialog = Dialog(
        title="Question", width=62, height=12, status="Tab between the groups"
    )
    dialog.help = "survey"
    dialog.add(widget=Label(text="Do you like Dasha Framework?", row=1, column=2))
    rating = dialog.add(
        widget=RadioButtons(
            labels=["&Yes", "&Mostly", "&Not yet"],
            row=2,
            column=2,
            width=17,
            name="rating",
            status="Pick one: Up and Down, or a click, or its letter",
        )
    )
    rating.help = "survey#do-you-like-dasha-framework"  # a heading on the page
    dialog.add(widget=Label(text="What have you tried?", row=1, column=32))
    tried = dialog.add(
        widget=CheckBoxes(
            labels=["&Windows", "M&enus", "Mo&use", "&Dialogs", "&Themes", "&Plugins"],
            row=2,
            column=32,  # clear of "Do you like Dasha Framework?" on the left
            columns=2,
            checked=[3],
            disabled=[5],  # Plugins: not there yet
            name="tried",
            status="Pick any: Space checks the current one; Left and Right "
            "change column",
        )
    )
    tried.help = "survey#what-have-you-tried"
    dialog.add(
        widget=Button(
            label="&OK", row=7, column=17, result="ok", default=True, name="ok"
        )
    )
    dialog.add(
        widget=Button(label="&Cancel", row=7, column=32, result="cancel", name="cancel")
    )
    return dialog


class FilesWindow(Window):
    """A list of files, and what the demo's File menu does with it. It takes
    the same keyword arguments as ``Window``."""

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.open_file: Callable[[], None] = lambda: None
        """File > Open...: say which file was chosen."""
        self.save_as: Callable[[], None] = lambda: None
        """File > Save as...: say where it would be saved."""
        self.pick_several: Callable[[], None] = lambda: None
        """File > Pick several...: say how many were picked."""


def pick_several_dialog() -> Dialog:
    """A dialog of a list box of files, any number of them to pick."""
    dialog = Dialog(
        title="Pick several",
        width=40,
        height=16,
        status="Space selects; Enter opens",
    )
    dialog.add(widget=Label(text="Files (Space selects several):", row=1, column=2))
    dialog.add(
        widget=ListBox(
            items=DEMO_FILES,
            row=2,
            column=2,
            width=34,
            height=8,
            multiple=True,
            name="files",
            status="Space or a click selects; Shift+click a range; "
            "double-click opens",
        )
    )
    dialog.add(widget=Button(label="&OK", row=11, column=7, result="ok", default=True))
    dialog.add(widget=Button(label="&Cancel", row=11, column=21, result="cancel"))
    return dialog


if __name__ == "__main__":
    raise SystemExit(Demo().run())
