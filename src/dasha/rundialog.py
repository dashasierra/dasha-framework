"""The Run dialog for starting a script or module."""

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
"""Largest script read, in bytes."""

VENV_FOLDERS = ("", ".venv", "venv", "env")
"""Folders searched for a virtual environment."""


def _read_classes(script: Path) -> tuple[list[str], set[str]]:
    """A script's top-level classes and which are applications.

    :param script: The script.
    """
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
    """A script's top-level classes, applications first.

    :param script: The script.
    """
    names, applications = _read_classes(script)
    return [n for n in names if n in applications] + [
        n for n in names if n not in applications
    ]


def likely_class(script: Path) -> str:
    """The class most likely meant, or "".

    :param script: The script.
    """
    names, applications = _read_classes(script)
    return next((name for name in names if name in applications), "")


def _base_name(base: ast.expr) -> str:
    """A base class's name.

    :param base: The base expression.
    """
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return ""


def find_venv(script: Path) -> Path | None:
    """A script's likely virtual environment, or ``None``.

    :param script: The script.
    """
    script = script.resolve()  # so a relative path has a folder above
    for folder in (script.parent, script.parent.parent):
        for name in VENV_FOLDERS:
            candidate = folder / name if name else folder
            cfg = candidate / "pyvenv.cfg"
            if cfg.is_file() and venv_python(candidate).exists():
                return candidate
    return None


class RunDialog(Dialog):  # pylint: disable=too-many-instance-attributes
    """Asks what to run.

    :param program: Starting program.
    :param venv: Starting virtual environment.
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
        """Show a problem above the buttons.

        :param text: The problem.
        """
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
        """Fill in the class and environment for a new program."""
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
        """Describe what will run."""
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
        """Grow or shrink for the options.

        :param options: The options area.
        """
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
        """End only once there is something to run.

        :param button: The button pressed.
        """
        if button.name == "ok":
            self.accept()
        else:
            super().button_pressed(button)

    def accept(self) -> None:
        """Check the entry and answer, or show a problem."""
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
