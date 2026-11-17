"""Run...: start a Python script or module as an application, once,
without installing it.

``PresentationManager.run_dialog`` shows the dialog (Run... in the system
menu) and starts whatever it answers with: a script (``path/app.py``) or a
module (``package.module:Class``), optionally with a virtual environment's
Python.

Usually, naming the script is all it takes. The dialog reads the script
(without running it) to find its application classes (``find_classes``),
and looks next to it, or in the folder above, for a virtual environment
(``find_venv``), filling in both.
"""

import ast
import os
from pathlib import Path

from dasha.canvas import Rect
from dasha.dialog import Dialog
from dasha.filedialog import FileDialog
from dasha.registry import AppEntry, is_script, slug, venv_python
from dasha.widgets import (
    AutoCompleteBox,
    Button,
    Collapsible,
    Label,
    TextBox,
    Widget,
)

LARGEST_SCRIPT = 1_000_000
"""The largest number of bytes read from a script to find its classes;
anything larger is not treated as a script."""

VENV_FOLDERS = ("", ".venv", "venv", "env")
"""Where ``find_venv`` looks for a virtual environment in a script's
folder (and then in the folder above): first the folder itself, then these
folders inside it."""


def _read_classes(script: Path) -> tuple[list[str], set[str]]:
    """The classes a script defines at its top level, in order, and which
    of them are applications: a class whose bases include
    ``Application``, or a class of the script's that is one. Read, never
    run: a script that cannot be read, or is not Python, has none."""
    try:
        if script.stat().st_size > LARGEST_SCRIPT:
            return [], set()
        tree = ast.parse(script.read_text(encoding="utf-8"), str(script))
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
        return [], set()
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    bases = {node.name: {_base_name(base) for base in node.bases} for node in classes}
    applications = {"Application"}
    while True:  # until no more are found: a subclass of a subclass, say
        found = {name for name, of in bases.items() if of & applications}
        if found <= applications:
            break
        applications |= found
    return [node.name for node in classes], applications - {"Application"}


def find_classes(script: Path) -> list[str]:
    """The classes that a script defines at its top level: first those that
    are applications (``class Notepad(Application)``, or ``class
    Big(Notepad)`` defined after it), then the rest, each group in the order
    they are written. The script is read, but never run."""
    names, applications = _read_classes(script)
    return [n for n in names if n in applications] + [
        n for n in names if n not in applications
    ]


def likely_class(script: Path) -> str:
    """The class most likely meant to be run: the script's first
    application class, or ``""`` if it has none."""
    names, applications = _read_classes(script)
    return next((name for name in names if name in applications), "")


def _base_name(base: ast.expr) -> str:
    """A base class's name, as written: ``Application`` in both
    ``Application`` and ``dasha.application.Application``."""
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return ""


def find_venv(script: Path) -> Path | None:
    """A virtual environment that is probably the script's own. In the
    script's folder, this is the folder itself if it has a ``pyvenv.cfg``,
    or else a ``.venv``, ``venv`` or ``env`` folder inside it that has one.
    Failing that, the folder above is searched in the same way, as for a
    project that keeps its code in ``src`` and its virtual environment next
    to that. Only an environment with a Python to run counts. Returns
    ``None`` if none is found."""
    script = script.resolve()  # so a relative path has a folder above
    for folder in (script.parent, script.parent.parent):
        for name in VENV_FOLDERS:
            candidate = folder / name if name else folder
            cfg = candidate / "pyvenv.cfg"
            if cfg.is_file() and venv_python(candidate).exists():
                return candidate
    return None


class RunDialog(Dialog):  # pylint: disable=too-many-instance-attributes
    """Ask what to run::

        Program: a .py script, or module:Class
         C:\\apps\\notepad.py                    Browse...
        Runs Notepad, with the virtual environment .venv
        ► Options

    Usually, naming a script (with Browse... or by typing it) is all
    that is needed. The dialog reads the script to find its application
    classes, looks next to it for a virtual environment, and describes what
    will run on the line below. Options shows the class (an autocomplete box
    offering the script's classes, with the most likely application first)
    and the virtual environment (whose Browse... button chooses a
    ``pyvenv.cfg``), for when the guess is not what is wanted; the dialog
    grows to show them. A field is filled in automatically only while the
    user has not typed in it.

    OK checks what was entered and answers ``"ok"`` with ``entry`` set;
    otherwise, the problem is shown on the line above the buttons.
    """

    help = "running"

    def __init__(self, program: str = "", venv: str = "") -> None:
        super().__init__(
            "Run", 60, self.HEIGHT, status="Run a script or module as an application"
        )
        self.entry: AppEntry | None = None
        """What to start, once answered ``"ok"``."""
        self._guessed_class = ""
        self._guessed_venv = ""
        self._read: Path | None = None  # the script last read for classes
        self.add(Label("Program: a .py script, or module:Class", 0, 1))
        self.program = self.add(
            TextBox(
                1,
                1,
                40,
                text=program,
                name="program",
                status="A script or module",
                on_change=lambda box: self._program_changed(),
            )
        )
        self.add(
            Button("&Browse...", 1, 43, action=self._browse_program, name="browse")
        )
        self.summary = self.add(Label("", 2, 1, name="summary"))
        self.options = self.add(
            Collapsible(
                label="&Options",
                row=3,
                column=1,
                on_change=self._fit,
                name="options",
                status="The class to run, and a virtual environment",
            )
        )
        self.options.add(Label("Class", 0, 2))
        self.class_box = self.options.add(
            AutoCompleteBox(
                0,
                24,
                24,
                name="class",
                status="The Application class to run (Alt+Down lists the script's)",
                on_change=lambda box: self._describe(),
            )
        )
        self.options.add(Label("Virtual environment", 2, 2))
        self.venv = self.options.add(
            TextBox(
                3,
                2,
                38,
                text=venv,
                name="venv",
                status="Runs with its Python",
                on_change=lambda box: self._describe(),
            )
        )
        self.options.add(
            Button("Bro&wse...", 3, 42, action=self._browse_venv, name="browse_venv")
        )
        self.info = self.add(Label("", 4, 1, name="info"))
        self.add(Button("&OK", 5, 14, result="ok", default=True, name="ok"))
        self.add(Button("&Cancel", 5, 30, result="cancel", name="cancel"))
        self._program_changed()

    HEIGHT = 9
    """The dialog's height, with its options closed."""
    OPTIONS_HEIGHT = 5
    """How many rows the options take up when they are open."""

    def say(self, text: str) -> None:
        """Show what is wrong, on the line above the buttons."""
        self.info.text = text[:54]

    # What the script is, as far as can be told

    def _script(self) -> Path | None:
        """The script named, if the program is one that is there."""
        program = self.program.text.strip()
        if not program.endswith(".py"):
            return None
        path = Path(program).expanduser()
        return path if path.is_file() else None

    def _program_changed(self) -> None:
        """A new program: read it for its classes and look beside it for a
        virtual environment, filling in what the user has not."""
        script = self._script()
        if script is not None and script.resolve() != self._read:
            self._read = script.resolve()
            self.class_box.suggestions = find_classes(script)
            likely = likely_class(script)
            if self.class_box.text in ("", self._guessed_class):
                self.class_box.text = self._guessed_class = likely
            venv = find_venv(script)
            found = str(venv) if venv is not None else ""
            if self.venv.text in ("", self._guessed_venv):
                self.venv.text = self._guessed_venv = found
        elif script is None:
            # Not a script (yet): no class or venv of one is guessed.
            self._read = None
            self.class_box.suggestions = []
            if self._guessed_class and self.class_box.text == self._guessed_class:
                self.class_box.text = self._guessed_class = ""
            if self._guessed_venv and self.venv.text == self._guessed_venv:
                self.venv.text = self._guessed_venv = ""
        self._describe()

    def _describe(self) -> None:
        """Say what will run, under the program, so the options need not be
        opened to see it."""
        program = self.program.text.strip()
        class_name = self.class_box.text.strip()
        venv = self.venv.text.strip()
        if not program:
            text = ""
        elif program.endswith(".py") and self._script() is None:
            text = "No such script"
        else:
            what = class_name or (Path(program).stem if is_script(program) else program)
            text = f"Runs {what}"
            if venv:
                text += f", with the virtual environment {Path(venv).name}"
        self.summary.text = text[:56]

    def _fit(self, options: Collapsible) -> None:
        """Grow to show the options while they are open, and shrink back."""
        rect = self.rect
        height = self.HEIGHT + (self.OPTIONS_HEIGHT if options.expanded else 0)
        self.rect = Rect(rect.row, rect.column, height, rect.width)
        if self.manager is not None:
            self.manager.keep_reachable(self)

    # Browsing

    def _pick(
        self, title: str, filters: list[tuple[str, str]], start: str
    ) -> str | None:
        manager = self.manager
        if manager is None:
            return None
        directory = start if start and os.path.isdir(start) else "."
        dialog = FileDialog(
            title, directory=directory, filters=filters, must_exist=True
        )
        return dialog.path if manager.execute(dialog) == "ok" else None

    def _browse_program(self, button: Button) -> None:
        del button
        current = self.program.text.strip()
        start = os.path.dirname(current) if is_script(current) else ""
        path = self._pick("Choose a script", [("Python scripts", "*.py")], start)
        if path is not None:
            self.program.text = path
            self._program_changed()

    def _browse_venv(self, button: Button) -> None:
        del button
        path = self._pick(
            "Choose a virtual environment's pyvenv.cfg",
            [("Virtual environments", "pyvenv.cfg")],
            self.venv.text.strip(),
        )
        if path is not None:
            self.venv.text = os.path.dirname(path)
            self._describe()

    # Answering

    def button_pressed(self, button: Widget) -> None:
        """Pressing OK ends the dialog only once there is something to run."""
        if button.name == "ok":
            self.accept()
        else:
            super().button_pressed(button)

    def accept(self) -> None:
        """Check what was entered, and either answer ``"ok"`` with ``entry``
        set, or show what is wrong."""
        program = self.program.text.strip()
        class_name = self.class_box.text.strip()
        venv = self.venv.text.strip()
        if not program:
            self.say("Name a script, or a module and its class")
            return
        if program.endswith(".py"):
            path = Path(program).expanduser().resolve()
            if not path.is_file():
                self.say("No such script")
                return
            target = str(path) + (f":{class_name}" if class_name else "")
            name = class_name or path.stem
        else:
            module, _, from_module = program.partition(":")
            class_name = from_module or class_name
            if not module or not class_name.isidentifier():
                self.say("Give a module and its class: package.module:Class")
                return
            target, name = f"{module}:{class_name}", class_name
        if venv:
            venv = str(Path(venv).expanduser().resolve())
            if not venv_python(venv).exists():
                self.say("No Python in that virtual environment")
                return
        self.entry = AppEntry(
            id=slug(name), name=name, target=target, venv=venv or None
        )
        self.result = "ok"
