"""Tests for the PyInstaller entry point (``frozen/dasha_entry.py``)."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

from dasha.hosting import AppHost, AppServer
from dasha.manager import PresentationManager

ENTRY = Path(__file__).resolve().parent.parent / "frozen" / "dasha_entry.py"


def load_entry() -> ModuleType:
    """The entry script, as a module."""
    spec = importlib.util.spec_from_file_location("dasha_entry", ENTRY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EntryTests(unittest.TestCase):
    """The built program runs applications for the desktop, or dasha."""

    def setUp(self) -> None:
        self.entry = load_entry()

    def test_host(self) -> None:
        """``-m dasha.host TARGET`` runs the application, as Python would,
        with or without ``-P`` before it."""
        for args in (
            ["-m", "dasha.host", "a.b:C"],
            ["-P", "-m", "dasha.host", "a.b:C"],
        ):
            with self.subTest(args=args):
                with mock.patch("dasha.host.main", return_value=7) as host:
                    self.assertEqual(self.entry.main(args), 7)
                host.assert_called_once_with(["a.b:C"])

    def test_what_the_desktop_sends(self) -> None:
        """The very command a desktop starts an application with, when the
        application has no virtual environment (so a built dasha runs it
        itself), runs the application. They are written in two places, and
        once drifted apart: then every such application failed with
        "unrecognised arguments: -P -m"."""
        server = AppServer(PresentationManager())
        self.addCleanup(server.stop_all, 0)
        with tempfile.TemporaryDirectory() as folder:
            server.log_folder = Path(folder)
            host = AppHost(server, "notepad.py", "Notepad")
            with mock.patch("dasha.hosting.ProcessTree.start") as start:
                host.start()
            command = start.call_args.args[0]
        self.assertEqual(Path(command[0]), Path(sys.executable))  # dasha itself
        with mock.patch("dasha.host.main", return_value=0) as run:
            self.assertEqual(self.entry.main(command[1:]), 0)
        run.assert_called_once_with(["notepad.py"])

    def test_p_alone_is_not_the_host(self) -> None:
        """``-P`` before anything but ``-m dasha.host`` is left for the
        dasha command line, which refuses it."""
        with mock.patch("dasha.__main__.main", return_value=2) as dasha:
            self.assertEqual(self.entry.main(["-P", "notepad"]), 2)
        dasha.assert_called_once_with(["-P", "notepad"], desktop=False)

    def test_anything_else_is_dasha(self) -> None:
        """Anything else is the dasha command line."""
        with mock.patch("dasha.__main__.main", return_value=0) as dasha:
            self.assertEqual(self.entry.main(["notepad", "--monochrome"]), 0)
        dasha.assert_called_once_with(["notepad", "--monochrome"], desktop=False)

    def test_dasha_desktop_by_name(self) -> None:
        """A copy of the program called dasha-desktop, in any case and with or
        without an extension, is dasha-desktop; any other name is dasha."""
        for program, desktop in (
            ("C:/Programs/Dasha-Desktop.exe", True),
            ("/usr/local/bin/dasha-desktop", True),
            ("/usr/local/bin/dasha", False),
            ("C:/Programs/dasha-desk.exe", False),
        ):
            with (
                self.subTest(program=program),
                mock.patch("dasha.__main__.main", return_value=0) as dasha,
            ):
                self.assertEqual(self.entry.main(["notepad"], program), 0)
                dasha.assert_called_once_with(["notepad"], desktop=desktop)

    def test_other_modules_are_not_run(self) -> None:
        """Only dasha.host: ``-m`` anything else goes to dasha, which
        refuses it."""
        with mock.patch("dasha.__main__.main", return_value=2) as dasha:
            self.assertEqual(self.entry.main(["-m", "venv", "x"]), 2)
        dasha.assert_called_once_with(["-m", "venv", "x"], desktop=False)


if __name__ == "__main__":
    unittest.main()
