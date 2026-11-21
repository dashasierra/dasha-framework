"""Tests for the Run dialog's Browse and Cancel."""

import os
import tempfile
import unittest
from pathlib import Path

from dasha.dialog import Dialog
from dasha.filedialog import FileDialog
from dasha.manager import PresentationManager
from dasha.registry import venv_python
from dasha.rundialog import RunDialog, find_classes, find_venv, likely_class
from dasha.shortcuts import Shortcuts
from dasha.widgets import Button


class Picking(PresentationManager):
    """Answers file dialogs from a list.

    :param answers: Paths, or ``None`` for Cancel.
    """

    def __init__(self, answers: list[str | None]) -> None:
        super().__init__()
        self.answers = answers
        self.started_in: list[str] = []
        self.titles: list[str] = []

    def execute(self, dialog: Dialog) -> str | None:
        assert isinstance(dialog, FileDialog)
        self.started_in.append(dialog.directory)
        self.titles.append(dialog.title)
        answer = self.answers.pop(0)
        if answer is None:
            return "cancel"
        dialog.path = answer
        return "ok"


class BrowseTests(unittest.TestCase):
    """Browse... beside the program and the virtual environment."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.root = Path(os.path.realpath(folder.name))
        self.script = self.root / "hello.py"
        self.script.write_text("", encoding="utf-8")

    def press(self, dialog: RunDialog, name: str) -> None:
        """Press a dialog button.

        :param dialog: The dialog.
        :param name: Button name.
        """
        button = dialog.widget(name)
        assert isinstance(button, Button)
        button.activate()

    def test_browse_for_a_script(self) -> None:
        """Browse for a script."""
        dialog = RunDialog(program=str(self.script))
        manager = Picking([str(self.root / "other.py")])
        dialog.manager = manager
        self.press(dialog, "browse")
        self.assertEqual(dialog.program.text, str(self.root / "other.py"))
        self.assertEqual(manager.started_in, [str(self.root)])
        self.assertEqual(manager.titles, ["Choose a script"])

    def test_browse_for_a_venv(self) -> None:
        """Its pyvenv.cfg is chosen, and its folder goes in the box."""
        dialog = RunDialog(venv=str(self.root))
        manager = Picking([str(self.root / "venv" / "pyvenv.cfg")])
        dialog.manager = manager
        self.press(dialog, "browse_venv")
        self.assertEqual(dialog.venv.text, str(self.root / "venv"))
        self.assertEqual(manager.started_in, [str(self.root)])

    def test_cancelled_browsing_changes_nothing(self) -> None:
        """Cancelled browsing changes nothing."""
        dialog = RunDialog(program="pkg.mod:App")
        manager = Picking([None, None])
        dialog.manager = manager
        self.press(dialog, "browse")
        self.press(dialog, "browse_venv")
        self.assertEqual((dialog.program.text, dialog.venv.text), ("pkg.mod:App", ""))
        self.assertEqual(manager.started_in, [os.path.abspath(".")] * 2)

    def test_browse_without_a_manager(self) -> None:
        """Not on a desktop, Browse... does nothing."""
        dialog = RunDialog()
        self.press(dialog, "browse")
        self.assertEqual(dialog.program.text, "")

    def test_cancel(self) -> None:
        """Cancel answers "cancel", with nothing to start."""
        dialog = RunDialog(program=str(self.script))
        self.press(dialog, "cancel")
        self.assertEqual((dialog.result, dialog.entry), ("cancel", None))


NOTEPAD = """
from dasha.application import Application
import dasha.application


class Helper:
    pass


class Notepad(Application):
    pass


class Big(Notepad):
    pass


class Other(dasha.application.Application):
    pass
"""


def make_venv(folder: Path) -> Path:
    """A folder that looks like a virtual environment.

    :param folder: The folder.
    """
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    python = venv_python(folder)
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("", encoding="utf-8")
    return folder


class Script(unittest.TestCase):
    """A script, ``notepad.py``, in a folder of its own."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.root = Path(os.path.realpath(folder.name))
        self.script = self.root / "notepad.py"
        self.script.write_text(NOTEPAD, encoding="utf-8")


class FindingTests(Script):
    """What a script is found to hold, and what is beside it."""

    def test_applications_first(self) -> None:
        """Applications first."""
        self.assertEqual(
            find_classes(self.script), ["Notepad", "Big", "Other", "Helper"]
        )
        self.assertEqual(likely_class(self.script), "Notepad")

    def test_never_run(self) -> None:
        """Read, not run: a script that would do something does not."""
        self.script.write_text(
            "raise SystemExit('ran')\nclass App(Application): pass\n", encoding="utf-8"
        )
        self.assertEqual(find_classes(self.script), ["App"])

    def test_nothing_to_find(self) -> None:
        """No application, not Python, not there: nothing likely."""
        self.script.write_text("class Plain: pass\n", encoding="utf-8")
        self.assertEqual(
            (find_classes(self.script), likely_class(self.script)), (["Plain"], "")
        )
        self.script.write_text("def (:\n", encoding="utf-8")
        self.assertEqual(find_classes(self.script), [])
        self.assertEqual(find_classes(self.root / "missing.py"), [])

    def test_a_venv_beside_it(self) -> None:
        """A venv beside it."""
        self.assertIsNone(find_venv(self.script))
        (self.root / "venv").mkdir()
        (self.root / "venv" / "pyvenv.cfg").write_text("", encoding="utf-8")
        self.assertIsNone(find_venv(self.script))  # no Python in it
        made = make_venv(self.root / ".venv")
        self.assertEqual(find_venv(self.script), made)
        make_venv(self.root)
        self.assertEqual(find_venv(self.script), self.root)

    def test_a_venv_one_folder_up(self) -> None:
        """A venv one folder up."""
        src = self.root / "project" / "src"
        src.mkdir(parents=True)
        script = src / "app.py"
        script.write_text("", encoding="utf-8")
        self.assertIsNone(find_venv(script))
        make_venv(self.root / ".venv")  # two folders up
        self.assertIsNone(find_venv(script))
        root_venv = make_venv(self.root / "project" / ".venv")
        self.assertEqual(find_venv(script), root_venv)
        beside = make_venv(src / "venv")
        self.assertEqual(find_venv(script), beside)


class FillingInTests(Script):
    """The dialog fills in what it finds."""

    def test_naming_the_script_is_enough(self) -> None:
        """The class and the venv filled in, and said under the program."""
        make_venv(self.root / ".venv")
        dialog = RunDialog(program=str(self.script))
        self.assertEqual(dialog.class_box.text, "Notepad")
        self.assertEqual(
            dialog.class_box.suggestions, ["Notepad", "Big", "Other", "Helper"]
        )
        self.assertEqual(dialog.venv.text, str(self.root / ".venv"))
        self.assertEqual(
            dialog.summary.text, "Runs Notepad, with the virtual environment .venv"
        )
        dialog.accept()
        assert dialog.entry is not None
        self.assertEqual(dialog.entry.target, f"{self.script.resolve()}:Notepad")
        self.assertEqual(dialog.entry.venv, str((self.root / ".venv").resolve()))

    def test_typed_in(self) -> None:
        """Typed in."""
        dialog = RunDialog()
        for char in str(self.script):
            dialog.program.handle_key(char, Shortcuts())
        self.assertEqual(dialog.class_box.text, "Notepad")
        dialog.class_box.text = "Big"  # the user's choice
        other = self.root / "other.py"
        other.write_text("class Clock(Application): pass\n", encoding="utf-8")
        dialog.program.text = str(other)
        dialog._program_changed()  # pylint: disable=protected-access
        self.assertEqual(dialog.class_box.text, "Big")
        self.assertEqual(dialog.class_box.suggestions, ["Clock"])

    def test_a_module_after_a_script(self) -> None:
        """A module after a script."""
        make_venv(self.root / ".venv")
        dialog = RunDialog(program=str(self.script))
        dialog.program.text = "pkg.mod"
        dialog._program_changed()  # pylint: disable=protected-access
        self.assertEqual((dialog.class_box.text, dialog.venv.text), ("", ""))

    def test_the_options_open_and_close(self) -> None:
        """The options open and close."""
        dialog = RunDialog(program=str(self.script))
        self.assertFalse(dialog.options.expanded)
        self.assertFalse(dialog.class_box.is_shown)
        height = dialog.rect.height
        dialog.options.expand()
        self.assertTrue(dialog.class_box.is_shown and dialog.venv.is_shown)
        self.assertEqual(dialog.rect.height, height + RunDialog.OPTIONS_HEIGHT)
        ok = dialog.widget("ok")
        assert ok is not None
        self.assertLessEqual(ok.rect.bottom, dialog.interior.height)  # shadow too
        dialog.options.collapse()
        self.assertEqual(dialog.rect.height, height)

    def test_a_module_or_nothing(self) -> None:
        """For a module, nothing to read; with nothing named, nothing said."""
        dialog = RunDialog(program="pkg.mod:App")
        self.assertEqual(dialog.summary.text, "Runs pkg.mod:App")
        self.assertEqual(RunDialog().summary.text, "")
        missing = RunDialog(program=str(self.root / "missing.py"))
        self.assertEqual(missing.summary.text, "No such script")


if __name__ == "__main__":
    unittest.main()
