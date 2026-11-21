"""Tests for the ``dasha`` command when settings or the terminal fail."""

import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from dasha import registry, style, theme
from dasha.__main__ import _desktop, main
from tests.support import isolated_home, started_desktop


class ProblemTests(unittest.TestCase):
    """Each problem is said, and most stop the desktop starting."""

    def setUp(self) -> None:
        self.home = isolated_home(self)
        for patcher in (
            mock.patch.object(style, "terminal_has_colours", return_value=True),
            mock.patch.object(theme, "no_colour_set", return_value=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_file_that_cannot_be_written(self) -> None:
        """A default file that cannot be written is said."""
        blocker = self.home / "blocker"
        blocker.write_text("", "utf-8")
        errors = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(errors):
            code = main(["--init-shortcuts", "--shortcuts", str(blocker / "keys.json")])
        self.assertEqual(code, 1)
        self.assertIn("cannot write", errors.getvalue())

    def test_a_colours_file_that_is_not_there(self) -> None:
        """A colours file named but missing stops it."""
        missing = self.home / "missing.json"
        code, desktop, err = started_desktop("--colours", str(missing))
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)
        desktop.assert_not_called()

    def test_a_theme_setting_that_cannot_be_read(self) -> None:
        """A broken theme setting stops it."""
        with mock.patch.object(
            registry,
            "read_theme_setting",
            side_effect=registry.ManifestError("theme is not a string"),
        ):
            code, desktop, err = started_desktop()
        self.assertEqual(code, 1)
        self.assertIn("theme is not a string", err)
        desktop.assert_not_called()

    def test_options_that_cannot_be_remembered(self) -> None:
        """Options that cannot be saved are said; the desktop still starts."""
        with mock.patch.object(
            registry, "save_show_mouse_setting", side_effect=OSError("read-only")
        ):
            code, desktop, err = started_desktop("--show-mouse")
        self.assertEqual(code, 0)
        self.assertIn("the settings could not be saved", err)
        desktop.assert_called_once()

    def test_a_terminal_that_cannot_be_used(self) -> None:
        """A terminal that cannot be taken over is said."""
        terminal = mock.MagicMock()
        terminal.isatty.return_value = True
        errors = StringIO()
        with (
            mock.patch("dasha.__main__.Terminal", side_effect=OSError("no console")),
            mock.patch.object(sys, "stdin", terminal),
            mock.patch.object(sys, "stdout", terminal),
            redirect_stderr(errors),
        ):
            code = main(["desktop"])
        self.assertEqual(code, 1)
        self.assertIn("no console", errors.getvalue())

    def test_errors_in_the_desktop_fail_the_command(self) -> None:
        """Errors the desktop survived make the exit code 1."""
        with mock.patch("dasha.__main__._report_errors", return_value=True):
            code, _, _ = started_desktop()
        self.assertEqual(code, 1)

    def test_files_given_are_the_desktops(self) -> None:
        """The shortcuts and colours files given are the ones Settings uses."""
        paths = (Path("keys.json"), Path("colours.json"))
        manager = _desktop(None, [], processes=False, entries={}, paths=paths)
        self.assertEqual((manager.shortcuts_path, manager.colours_path), paths)


if __name__ == "__main__":
    unittest.main()
