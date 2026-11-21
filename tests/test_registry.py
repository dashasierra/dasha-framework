"""Tests for manifests, settings, virtual environments and lending."""

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import dasha

from dasha.registry import (
    AppEntry,
    ManifestError,
    is_script,
    lend_folder,
    load_manifests,
    manifest_text,
    read_autostart,
    read_manifest,
    slug,
    split_script,
    venv_has_dasha,
    venv_python,
    write_manifest,
)
from tests.hosted_apps import Broken, Hello


class Folder(unittest.TestCase):
    """A test with a temporary folder of its own, ``self.root``."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def write(self, name: str, text: str) -> Path:
        """Write a file; return its path.

        :param name: File name.
        :param text: Its contents.
        """
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class NamesTests(unittest.TestCase):
    """Ids and targets."""

    def test_slug(self) -> None:
        """Slug."""
        self.assertEqual(slug("Widget Gallery"), "widget-gallery")
        self.assertEqual(slug("  C++ & Co!  "), "c-co")
        self.assertEqual(slug("!!!"), "app")

    def test_scripts(self) -> None:
        """A script, with or without a class; Windows drive letters too."""
        self.assertTrue(is_script("app.py"))
        self.assertTrue(is_script(r"C:\apps\app.py:Hello"))
        self.assertFalse(is_script("package.module:Class"))
        self.assertEqual(split_script("app.py"), ("app.py", None))
        self.assertEqual(
            split_script(r"C:\apps\app.py:Hello"), (r"C:\apps\app.py", "Hello")
        )

    def test_entry_of_a_class(self) -> None:
        """Entry of a class."""
        entry = AppEntry.of(Hello)
        self.assertEqual(
            (entry.id, entry.name, entry.target, entry.single_instance),
            ("hello", "Hello", "tests.hosted_apps:Hello", False),
        )
        self.assertIs(entry.application, Hello)
        self.assertEqual(AppEntry.of(Broken, "np").id, "np")


class ManifestTests(Folder):
    """Reading and writing manifests."""

    def test_module(self) -> None:
        """Module."""
        path = self.write(
            "stats.toml",
            'name = "Text Stats"\nmodule = "stats.app"\nclass = "Stats"\n'
            'venv = "~/venvs/stats"\ngroup = "Tools"\nsingle_instance = true\n',
        )
        entry = read_manifest(path)
        self.assertEqual(
            (entry.id, entry.name, entry.target, entry.group, entry.single_instance),
            ("stats", "Text Stats", "stats.app:Stats", "Tools", True),
        )
        self.assertEqual(entry.venv, str(Path("~/venvs/stats").expanduser()))
        self.assertEqual(entry.manifest, path)
        self.assertIsNone(entry.application)

    def test_script(self) -> None:
        """Script."""
        entry = read_manifest(self.write("s.toml", 'name = "S"\nscript = "a/s.py"\n'))
        self.assertEqual(entry.target, str(Path("a/s.py")))
        self.assertTrue(entry.is_script)
        entry = read_manifest(
            self.write("t.toml", 'name = "T"\nscript = "t.py"\nclass = "T"\n')
        )
        self.assertEqual(entry.target, "t.py:T")

    def test_problems_are_all_listed(self) -> None:
        """Problems are all listed."""
        path = self.write(
            "bad.toml", 'colour = "red"\nmodule = "m"\nscript = "s.py"\ngroup = 3\n'
        )
        with self.assertRaises(ManifestError) as raised:
            read_manifest(path)
        problems = str(raised.exception).splitlines()
        self.assertEqual(len(problems), 4)
        self.assertTrue(all(p.startswith("bad.toml: ") for p in problems))
        for words in (
            'unknown setting "colour"',
            '"group" must be',
            '"name" is',
            "not both",
        ):
            self.assertTrue(any(words in p for p in problems), words)

    def test_module_needs_a_class(self) -> None:
        """Module needs a class."""
        with self.assertRaisesRegex(ManifestError, "needs a"):
            read_manifest(self.write("m.toml", 'name = "M"\nmodule = "m"\n'))

    def test_not_toml(self) -> None:
        """Not toml."""
        with self.assertRaises(ManifestError):
            read_manifest(self.write("x.toml", "name = \n"))

    def test_load_skips_the_broken(self) -> None:
        """Load skips the broken."""
        self.write("apps/good.toml", 'name = "Good"\nscript = "g.py"\n')
        self.write("apps/bad.toml", "nonsense")
        entries, problems = load_manifests(self.root / "apps")
        self.assertEqual([entry.id for entry in entries], ["good"])
        self.assertEqual(len(problems), 1)
        self.assertEqual(load_manifests(self.root / "none"), ([], []))

    def test_written_and_read_back(self) -> None:
        """Every setting, and awkward characters, survive."""
        entry = AppEntry(
            id="odd",
            name='Say "hi" \\ there',
            target=r"C:\apps\odd app.py:Odd",
            venv=r"C:\venvs\odd",
            single_instance=True,
            group="Games",
        )
        path = write_manifest(entry, self.root / "apps")
        self.assertEqual(path, self.root / "apps" / "odd.toml")
        self.assertEqual(
            read_manifest(path), entry.__class__(**{**vars(entry), "manifest": path})
        )
        module = AppEntry(id="m", name="M", target="pkg.mod:M")
        self.assertEqual(
            manifest_text(module), 'name = "M"\nmodule = "pkg.mod"\nclass = "M"\n'
        )


class AutostartTests(Folder):
    """settings.toml."""

    def test_autostart(self) -> None:
        """Autostart."""
        self.assertEqual(read_autostart(self.root / "none.toml"), [])
        path = self.write("settings.toml", 'autostart = ["notepad", "welcome"]\n')
        self.assertEqual(read_autostart(path), ["notepad", "welcome"])

    def test_bad_settings(self) -> None:
        """Bad settings."""
        for text in (
            'autostart = "notepad"\n',
            "autostart = [1]\n",
            "other = 1\n",
            "[",
        ):
            with self.assertRaises(ManifestError, msg=text):
                read_autostart(self.write("settings.toml", text))


class VenvTests(Folder):
    """Virtual environments, and lending dasha to them."""

    def test_python(self) -> None:
        """Python."""
        python = venv_python(self.root)
        if os.name == "nt":
            self.assertEqual(python, self.root / "Scripts" / "python.exe")
        else:
            self.assertEqual(python, self.root / "bin" / "python")

    def test_has_dasha(self) -> None:
        """Its own dasha, installed or editable, on either layout."""
        self.assertFalse(venv_has_dasha(self.root))
        windows = self.root / "win"
        (windows / "Lib" / "site-packages" / "requests").mkdir(parents=True)
        self.assertFalse(venv_has_dasha(windows))
        (windows / "Lib" / "site-packages" / "dasha").mkdir()
        self.assertTrue(venv_has_dasha(windows))
        posix = self.root / "posix"
        (posix / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
        self.write(
            "posix/lib/python3.12/site-packages/__editable__.dasha_framework-0.1.pth",
            "",
        )
        self.assertTrue(venv_has_dasha(posix))

    def test_lend_folder(self) -> None:
        """A copy of dasha alone, made once."""
        folder = lend_folder(self.root)
        self.assertTrue((folder / "dasha" / "__init__.py").is_file())
        self.assertTrue((folder / "dasha" / "widgets" / "listbox.py").is_file())
        self.assertEqual([p.name for p in folder.iterdir()], ["dasha"])
        self.assertFalse(list(folder.rglob("__pycache__")))
        self.assertEqual(lend_folder(self.root), folder)
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_lend_folder_follows_contents(self) -> None:
        """The lend folder follows the contents."""
        package = self.root / "unpacked" / "dasha"
        shutil.copytree(
            Path(dasha.__file__).parent,
            package,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        lend = self.root / "lend"
        with mock.patch.object(dasha, "__file__", str(package / "__init__.py")):
            first = lend_folder(lend)
            later = time.time() + 100
            for path in package.rglob("*.py"):
                os.utime(path, (later, later))
            self.assertEqual(lend_folder(lend), first)
            (package / "style.py").write_text("# changed\n", encoding="utf-8")
            self.assertNotEqual(lend_folder(lend), first)


if __name__ == "__main__":
    unittest.main()
