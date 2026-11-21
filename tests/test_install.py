"""Tests for installing and running applications."""

import sys
import tempfile
import unittest
import venv
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import cast
from unittest import mock

from dasha import install, registry
from dasha.__main__ import _startup, main
from dasha.host import find
from dasha.manager import PresentationManager
from dasha.registry import AppEntry, read_manifest, venv_python
from dasha.rundialog import RunDialog
from dasha.terminal import Terminal
from tests.hosted_apps import Hello
from tests.support import HOSTED_APPS, serving, tests_importable
from tests.test_application import Scripted, run
from tests.test_hosting import SlowTerminal

SCRIPT = """from dasha.application import Application
from dasha.canvas import Rect
from dasha.window import Window
import helper


class Script(Application):
    name = "Script"

    def start(self) -> None:
        self.open(Window(helper.TITLE, Rect(2, 2, 6, 30)))


if __name__ == "__main__":
    raise SystemExit("not run as __main__")
"""


class Home(unittest.TestCase):
    """A test with its own ~/.dasha: apps, venvs, lend and settings."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        for name, value in (
            ("MANIFEST_FOLDER", self.root / "apps"),
            ("VENV_FOLDER", self.root / "venvs"),
            ("SETTINGS_PATH", self.root / "settings.toml"),
        ):
            patcher = mock.patch.object(registry, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.script = self.write("scripts/script.py", SCRIPT)
        self.write("scripts/helper.py", 'TITLE = "From a script"\n')

    def write(self, name: str, text: str) -> Path:
        """Write a file; return its path.

        :param name: Relative file name.
        :param text: Its contents.
        """
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def command(self, *args: str) -> tuple[int, str, str]:
        """Run ``dasha``; return exit code, stdout and stderr.

        :param args: Command-line arguments.
        """
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def make_venv(self, name: str = "venv") -> Path:
        """A real virtual environment, without pip.

        :param name: Folder name.
        """
        path = self.root / name
        venv.create(path, with_pip=False)
        return path


class InstallTests(Home):
    """dasha install-app, uninstall-app and list-apps."""

    def test_a_script(self) -> None:
        """A script."""
        code, out, _ = self.command(
            "install-app", str(self.script), "--name", "My Script", "--group", "Games",
            "--single-instance",
        )  # fmt: skip
        self.assertEqual(code, 0)
        self.assertIn("Installed My Script as my-script", out)
        entry = read_manifest(self.root / "apps" / "my-script.toml")
        self.assertEqual(entry.target, str(self.script))
        self.assertEqual((entry.group, entry.single_instance), ("Games", True))

    def test_a_module(self) -> None:
        """A module."""
        code, _, _ = self.command(
            "install-app", "tests.hosted_apps:Hello", "--id", "hi"
        )
        self.assertEqual(code, 0)
        entry = read_manifest(self.root / "apps" / "hi.toml")
        self.assertEqual(
            (entry.name, entry.target), ("Hello", "tests.hosted_apps:Hello")
        )
        code, _, _ = self.command(
            "install-app", "tests.hosted_apps", "--class", "Hello", "--id", "hi2"
        )
        self.assertEqual(code, 0)

    def test_refusals(self) -> None:
        """Each says why, and installs nothing."""
        cases = [
            (("no/such.py",), "no such script"),
            (("missing_module_xyz:App",), "cannot be imported"),
            (("tests.hosted_apps",), "give the module's class"),
            (("a:B", "--class", "C"), "give the class once"),
            ((str(self.script), "--pip", "nltk"), "need --venv"),
            ((str(self.script), "--venv", str(self.root)), "no Python in"),
        ]
        for args, words in cases:
            code, _, err = self.command("install-app", *args)
            self.assertEqual(code, 1, args)
            self.assertIn(words, err, args)
        self.assertFalse((self.root / "apps").exists())

    def test_installed_already(self) -> None:
        """Installed already."""
        self.assertEqual(self.command("install-app", str(self.script))[0], 0)
        code, _, err = self.command("install-app", str(self.script))
        self.assertEqual(code, 1)
        self.assertIn("--force", err)
        self.assertEqual(self.command("install-app", str(self.script), "--force")[0], 0)

    def test_never_called_desktop(self) -> None:
        """No application can be called desktop."""
        for args in (["--id", "desktop"], ["--name", "Desktop", "--force"]):
            with self.subTest(args=args):
                code, _, err = self.command("install-app", str(self.script), *args)
                self.assertEqual(code, 1)
                self.assertIn('"desktop" cannot be an application\'s id', err)
        self.assertFalse((self.root / "apps" / "desktop.toml").exists())

    def test_create_venv_needs_a_python(self) -> None:
        """``--create-venv`` needs a Python."""
        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch("shutil.which", return_value=None),
        ):
            code, _, err = self.command(
                "install-app", str(self.script), "--create-venv"
            )
        self.assertEqual(code, 1)
        self.assertIn("--python", err)

    def test_create_venv_with_a_given_python(self) -> None:
        """--python names the Python that makes it."""
        code, _, err = self.command(
            "install-app", str(self.script), "--create-venv", "--python", sys.executable
        )
        self.assertEqual(code, 0, err)
        self.assertTrue(venv_python(self.root / "venvs" / "script").exists())

    def test_create_venv_and_uninstall(self) -> None:
        """A venv of its own, deleted with --remove-venv."""
        code, out, err = self.command("install-app", str(self.script), "--create-venv")
        self.assertEqual(code, 0, err)
        self.assertIn("Making a virtual environment", out)
        made = self.root / "venvs" / "script"
        self.assertTrue(venv_python(made).exists())
        self.assertEqual(
            read_manifest(self.root / "apps" / "script.toml").venv, str(made)
        )
        code, out, _ = self.command("uninstall-app", "script", "--remove-venv")
        self.assertEqual(code, 0)
        self.assertFalse((self.root / "apps" / "script.toml").exists())
        self.assertFalse(made.exists())

    def test_a_venv_not_made_here_is_kept(self) -> None:
        """A venv not made here is kept."""
        own = self.make_venv()
        self.command("install-app", str(self.script), "--venv", str(own))
        code, out, _ = self.command("uninstall-app", "script", "--remove-venv")
        self.assertEqual(code, 0)
        self.assertIn("Left", out)
        self.assertTrue(own.exists())

    def test_uninstall_unknown(self) -> None:
        """Uninstall unknown."""
        code, _, err = self.command("uninstall-app", "nothing")
        self.assertEqual(code, 1)
        self.assertIn("no installed application", err)

    def test_uninstall_stays_in_its_folder(self) -> None:
        """Uninstall stays in its folder."""
        outside = self.write("notes.toml", 'name = "Notes"\nscript = "n.py"\n')
        code, _, err = self.command("uninstall-app", "../notes")
        self.assertEqual(code, 1)
        self.assertIn("no installed application", err)
        self.assertTrue(outside.exists())

    def test_list(self) -> None:
        """Installed ones, with groups; broken manifests said."""
        self.command("install-app", str(self.script), "--group", "Games")
        self.write("apps/broken.toml", "nonsense")
        code, out, err = self.command("list-apps")
        self.assertEqual(code, 0)
        self.assertIn("Script [Games]", out)
        self.assertIn("broken.toml", err)

    def test_installed_ones_are_known(self) -> None:
        """The installed applications are known."""
        self.assertEqual(install.known_applications(), ({}, []))
        self.write("apps/welcome.toml", 'name = "My welcome"\nscript = "w.py"\n')
        entries, problems = install.known_applications()
        self.assertEqual(problems, [])
        self.assertEqual(list(entries), ["welcome"])
        self.assertEqual(entries["welcome"].name, "My welcome")


class BasePythonTests(unittest.TestCase):
    """The Python that makes virtual environments: never a build of dasha."""

    def test_this_python(self) -> None:
        """Normally, the Python dasha runs on."""
        self.assertEqual(install.base_python(), [sys.executable])

    def test_given_one(self) -> None:
        """One given is used (once it is checked)."""
        self.assertEqual(install.base_python(sys.executable), [sys.executable])

    def test_in_a_build_one_on_path(self) -> None:
        """A build has no Python of its own: one found on PATH."""
        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch(
                "shutil.which",
                side_effect=lambda name: sys.executable if name == "python" else None,
            ),
        ):
            self.assertEqual(install.base_python(), [sys.executable])

    def test_in_a_build_with_none(self) -> None:
        """A build with no Python on PATH says to give one."""
        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch("shutil.which", return_value=None),
        ):
            self.assertIn("--python", install.base_python())

    def test_too_old(self) -> None:
        """One older than dasha needs is refused."""
        old = mock.Mock(returncode=1)
        with mock.patch("subprocess.run", return_value=old):
            problem = install.base_python("python3.8")
        self.assertIsInstance(problem, str)
        self.assertIn("3.12 or newer", str(problem))

    def test_not_there(self) -> None:
        """One that is not there says to give another."""
        self.assertIn("--python", install.base_python("no-such-python-here"))

    def test_in_a_build_the_py_launcher(self) -> None:
        """A build with only the py launcher on PATH asks it for Python 3."""
        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch(
                "shutil.which", side_effect=lambda name: "py" if name == "py" else None
            ),
            mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)),
        ):
            self.assertEqual(install.base_python(), ["py", "-3"])


class VenvAndPipTests(Home):
    """Making virtual environments and installing into them, when it fails."""

    def test_making_a_venv_that_fails(self) -> None:
        """A Python that cannot run, or that fails, is said."""
        target = self.root / "venv"
        with redirect_stdout(StringIO()):
            with mock.patch("subprocess.run", side_effect=OSError("gone")):
                problem = install._make_venv(  # pylint: disable=protected-access
                    target, with_pip=False, python=["python"]
                )
            self.assertIn("gone", str(problem))
            with mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)):
                problem = install._make_venv(  # pylint: disable=protected-access
                    target, with_pip=True, python=["python"]
                )
        self.assertEqual(problem, f"cannot make a virtual environment in {target}")

    def test_install_app_says_the_venv_failed(self) -> None:
        """install-app says why it made no venv, and installs nothing."""
        with mock.patch.object(install, "_make_venv", return_value="no room"):
            code, _, err = self.command(
                "install-app", str(self.script), "--create-venv"
            )
        self.assertEqual((code, "no room" in err), (1, True))
        self.assertFalse((self.root / "apps").exists())

    def test_pip_with_requirements(self) -> None:
        """Packages and a requirements file go to pip; its failure is said."""
        requirements = self.write("requirements.txt", "nltk\n")
        with redirect_stdout(StringIO()):
            with mock.patch(
                "subprocess.run", return_value=mock.Mock(returncode=1)
            ) as run_pip:
                problem = install._pip(  # pylint: disable=protected-access
                    Path(sys.executable),
                    mock.Mock(pip=["nltk"], requirements=str(requirements)),
                )
        self.assertEqual(problem, "pip could not install everything")
        self.assertEqual(
            run_pip.call_args.args[0][-3:], ["nltk", "-r", str(requirements)]
        )

    def test_install_app_says_pip_failed(self) -> None:
        """install-app says pip failed, and installs nothing."""
        own = self.root / "own"
        own.mkdir()
        with (
            mock.patch.object(
                install, "venv_python", return_value=Path(sys.executable)
            ),
            mock.patch.object(install, "_pip", return_value="pip broke"),
        ):
            code, _, err = self.command(
                "install-app", str(self.script), "--venv", str(own), "--pip", "nltk"
            )
        self.assertEqual((code, "pip broke" in err), (1, True))
        self.assertFalse((self.root / "apps").exists())

    def test_module_found(self) -> None:
        """A module, here or in another Python; names that are none."""
        python = Path(sys.executable)
        self.assertTrue(install.module_found("json", python))
        self.assertFalse(install.module_found("no_such_module_xyz", python))
        self.assertFalse(install.module_found("", None))
        self.assertFalse(install.module_found("no_such_package_xyz.inner", None))

    def test_uninstall_a_broken_manifest(self) -> None:
        """A manifest that cannot be read is still uninstalled."""
        manifest = self.write("apps/broken.toml", "nonsense")
        code, out, _ = self.command("uninstall-app", "broken", "--remove-venv")
        self.assertEqual(code, 0)
        self.assertIn("Uninstalled broken", out)
        self.assertFalse(manifest.exists())

    def test_list_shows_a_venv(self) -> None:
        """An application's virtual environment is listed."""
        self.write("apps/tool.toml", 'name = "Tool"\nscript = "t.py"\nvenv = "/v"\n')
        code, out, _ = self.command("list-apps")
        self.assertEqual(code, 0)
        self.assertIn(f"(venv {Path('/v')})", out)


class StartupTests(Home):
    """What the desktop starts with."""

    def test_autostart_or_names(self) -> None:
        """Autostart or named applications."""
        self.write("apps/welcome.toml", 'name = "Welcome"\nscript = "w.py"\n')
        self.write("apps/notepad.toml", 'name = "Notepad"\nscript = "n.py"\n')
        self.write("settings.toml", 'autostart = ["welcome"]\n')
        named, desktop = _startup(["notepad"]), _startup([], desktop=True)
        assert named is not None and desktop is not None
        self.assertEqual((named[1], desktop[1]), (["notepad"], ["welcome"]))
        both = _startup(["notepad"], desktop=True)
        assert both is not None
        self.assertEqual(both[1], ["welcome", "notepad"])

    def test_problems(self) -> None:
        """An unknown name, or settings that cannot be read, stop it."""
        err = StringIO()
        with redirect_stderr(err):
            self.assertIsNone(_startup(["nothing"]))
            self.write("settings.toml", "autostart = 1\n")
            self.assertIsNone(_startup([], desktop=True))
            self.write("settings.toml", "")
            self.write("apps/bad.toml", "nonsense")
            self.assertIsNotNone(_startup([], desktop=True))
        self.assertIn("(left out)", err.getvalue())


class MenuTests(unittest.TestCase):
    """Groups in the Applications menu, and Run...."""

    def test_groups(self) -> None:
        """Grouped entries are listed in submenus, after the rest."""
        manager = PresentationManager()
        manager.register(
            [
                AppEntry("b", "Beta", "b:B"),
                AppEntry("s", "Snake", "s.py", group="Games"),
                AppEntry("a", "Alpha", "a:A"),
                AppEntry("c", "Chess", "c.py", group="Games"),
                AppEntry("x", "Calc", "x:X", group="Tools"),
            ]
        )
        submenu = manager.system_menu.items[1].submenu
        assert submenu is not None
        labels = [item.label for item in submenu.items]
        self.assertEqual(labels, ["&Alpha", "&Beta", "", "&Games", "&Tools"])
        games = submenu.items[3].submenu
        assert games is not None
        self.assertEqual([item.label for item in games.items], ["&Chess", "&Snake"])

    def test_run_dialog_starts_what_it_answers(self) -> None:
        """Run dialog starts what it answers."""
        manager = Scripted()
        started: list[object] = []
        manager.start = started.append  # type: ignore[method-assign,assignment]
        manager.register(Hello)
        manager.actions += [manager.run_dialog, manager.quit]
        run(manager, ["x", *"tests.hosted_apps:Hello", "\r", "x"])
        self.assertEqual(len(started), 1)
        entry = started[0]
        assert isinstance(entry, AppEntry)
        self.assertEqual(
            (entry.target, entry.name, entry.venv),
            ("tests.hosted_apps:Hello", "Hello", None),
        )

    def test_run_dialog_needs_the_desktop_running(self) -> None:
        """Run dialog needs the desktop running."""
        PresentationManager().run_dialog()  # nothing to show it on: nothing


class RunDialogTests(Home):
    """Checking what Run... was given."""

    def answer(
        self, program: str, class_name: str = "", venv_path: str = ""
    ) -> RunDialog:
        """Answer the Run dialog.

        :param program: The program.
        :param class_name: The class.
        :param venv_path: The virtual environment.
        """
        dialog = RunDialog(program, venv_path)
        dialog.class_box.text = class_name
        dialog.accept()
        return dialog

    def test_scripts(self) -> None:
        """A script, with or without a class named."""
        dialog = self.answer(str(self.script))
        assert dialog.entry is not None
        self.assertEqual(
            (dialog.result, dialog.entry.target, dialog.entry.name),
            ("ok", str(self.script), "script"),
        )
        dialog = self.answer(str(self.script), "Script")
        assert dialog.entry is not None
        self.assertEqual(dialog.entry.target, f"{self.script}:Script")

    def test_modules(self) -> None:
        """module:Class, or the module with the class beside it."""
        for program, class_name in (("pkg.mod:App", ""), ("pkg.mod", "App")):
            dialog = self.answer(program, class_name)
            assert dialog.entry is not None
            self.assertEqual(dialog.entry.target, "pkg.mod:App")

    def test_complaints(self) -> None:
        """What is wrong is said, and nothing is answered."""
        for program, class_name, venv_path, words in (
            ("", "", "", "Name a script"),
            ("nowhere.py", "", "", "No such script"),
            ("pkg.mod", "", "", "Give a module"),
            ("pkg.mod:App", "", str(self.root), "No Python"),
        ):
            dialog = self.answer(program, class_name, venv_path)
            self.assertIsNone(dialog.result)
            self.assertIn(words, dialog.info.text)

    def test_a_venv(self) -> None:
        """A venv."""
        made = self.make_venv()
        dialog = self.answer("pkg.mod:App", "", str(made))
        assert dialog.entry is not None
        self.assertEqual(dialog.entry.venv, str(made.resolve()))


class HostScriptTests(Home):
    """``python -m dasha.host`` with a script."""

    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(lambda: sys.modules.pop("helper", None))
        self.addCleanup(lambda: sys.modules.pop("dasha_script", None))
        # Loading the script puts its folder on sys.path, once each time.
        self.addCleanup(setattr, sys, "path", list(sys.path))

    def test_the_only_application(self) -> None:
        """Its folder is importable, and its __main__ part does not run."""
        application = find(str(self.script))
        self.assertEqual(application.name, "Script")
        self.assertEqual(find(f"{self.script}:Script").__qualname__, "Script")

    def test_problems(self) -> None:
        """Script problems."""
        two = self.write(
            "scripts/two.py",
            "from tests.hosted_apps import Hello\n"
            "from dasha.application import Application\n"
            "class A(Application): pass\n"
            "class B(Application): pass\n",
        )
        with self.assertRaisesRegex(ValueError, "several"):
            find(str(two))
        with self.assertRaisesRegex(ValueError, "no Application"):
            find(str(self.write("scripts/none.py", "x = 1\n")))
        with self.assertRaises(ImportError):
            find(str(self.root / "missing.py"))
        with self.assertRaisesRegex(ValueError, "not an Application"):
            find(f"{two}:x")

    def forget_modules(self, *names: str) -> None:
        """Forget imported modules after the test.

        :param names: Module names.
        """
        for name in names:
            self.addCleanup(sys.modules.pop, name, None)

    def test_in_a_package(self) -> None:
        """A script inside a package."""
        self.forget_modules("scriptpkg", "scriptpkg.helper", "scriptpkg.app")
        self.write("project/scriptpkg/__init__.py", "")
        self.write("project/scriptpkg/helper.py", 'TITLE = "From a package"\n')
        script = self.write(
            "project/scriptpkg/app.py",
            "from dasha.application import Application\n"
            "from scriptpkg.helper import TITLE\n"
            "class Packaged(Application):\n"
            "    name = TITLE\n"
            "if __name__ == '__main__':\n"
            "    raise SystemExit('the __main__ part ran')\n",
        )
        application = find(str(script))
        self.assertEqual(application.name, "From a package")
        self.assertEqual(application.__module__, "scriptpkg.app")
        self.assertIs(application, sys.modules["scriptpkg.app"].Packaged)

    def test_in_a_nested_package(self) -> None:
        """The folder above the outermost package goes on sys.path."""
        self.forget_modules("outerpkg", "outerpkg.inner", "outerpkg.inner.app")
        self.write("project/outerpkg/__init__.py", "")
        self.write("project/outerpkg/inner/__init__.py", "")
        script = self.write(
            "project/outerpkg/inner/app.py",
            "from dasha.application import Application\n"
            "class Nested(Application): pass\n",
        )
        self.assertEqual(find(f"{script}:Nested").__module__, "outerpkg.inner.app")
        self.assertIn(str(self.root / "project"), sys.path)


class ProcessTests(Home):
    """Scripts and virtual environments in real processes."""

    def setUp(self) -> None:
        super().setUp()
        tests_importable(self)
        self.manager = PresentationManager()
        self.manager.use_processes = True
        self.server = serving(self, self.manager)
        self.server.log_folder = self.root / "logs"
        self.server.lend_folder = self.root / "lend"

    def run_until(self, done: Callable[[], bool]) -> None:
        """Run until done.

        :param done: Returns whether to stop.
        """
        self.manager.run(cast(Terminal, SlowTerminal(self.manager, done)))

    def run_until_said(self, words: str) -> str:
        """Run until a message shows; return everything said.

        :param words: Words to wait for.
        """
        said: list[str] = []

        def shown() -> bool:
            for window in self.manager.windows:
                said.extend(str(value) for value in window.values.values())
            return words in " ".join(said)

        self.run_until(shown)
        return " ".join(said)

    def titles(self) -> list[str]:
        """Titles."""
        return [window.title for window in self.manager.windows]

    def test_a_script(self) -> None:
        """A script."""
        self.manager.start(AppEntry("s", "Script", str(self.script)))
        self.run_until(lambda: bool(self.titles()))
        self.assertEqual(self.titles(), ["From a script"])

    def test_in_a_venv_with_dasha_lent(self) -> None:
        """In a venv with dasha lent."""
        made = self.make_venv()
        self.manager.start(
            AppEntry("h", "Hello", f"{HOSTED_APPS}:Hello", venv=str(made))
        )
        self.run_until(lambda: bool(self.titles()))
        self.assertEqual(self.titles(), ["Hello"])
        self.assertTrue(any((self.root / "lend").iterdir()))

    def test_nothing_else_is_lent(self) -> None:
        """Nothing else is lent."""
        made = self.make_venv()
        site = next(made.rglob("site-packages"))
        (site / "dasha_framework-0.0.dist-info").mkdir()
        self.manager.start(
            AppEntry("h", "Hello", "tests.hosted_apps:Hello", venv=str(made))
        )
        said = self.run_until_said("stopped unexpectedly")
        self.assertIn("No module named", said)

    def test_a_venv_without_python(self) -> None:
        """A venv without python."""
        self.manager.start(AppEntry("h", "Hello", "x:Y", venv=str(self.root)))
        self.assertIn("no Python in", self.run_until_said("Cannot start"))


if __name__ == "__main__":
    unittest.main()
