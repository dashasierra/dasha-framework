"""Tests for writing files whole or not at all (``config.write_atomically``),
which the settings files and Notepad use, so that a failure part-way never
leaves a file empty or cut short."""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dasha import config, registry
from dasha.config import write_atomically

FULL = OSError(28, "No space left on device")


class WriteTests(unittest.TestCase):
    """Writing into an empty folder."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.path = self.folder / "notes.txt"

    def left_behind(self) -> list[str]:
        """Everything in the folder but the file itself."""
        return sorted(p.name for p in self.folder.iterdir() if p != self.path)

    def test_new_and_replaced(self) -> None:
        """A new file is made; an old one replaced; nothing else is left."""
        write_atomically(self.path, "first\n")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "first\n")
        write_atomically(self.path, "second\n")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "second\n")
        self.assertEqual(self.left_behind(), [])

    def test_line_endings_and_encoding(self) -> None:
        """``newline`` and ``encoding`` are as for ``open``."""
        write_atomically(self.path, "a\r\nb\n", newline="")
        self.assertEqual(self.path.read_bytes(), b"a\r\nb\n")
        write_atomically(self.path, "a\nb\n", newline="\n")
        self.assertEqual(self.path.read_bytes(), b"a\nb\n")
        write_atomically(self.path, "é", encoding="utf-16")
        self.assertEqual(self.path.read_text(encoding="utf-16"), "é")

    def test_a_failure_leaves_the_file_as_it_was(self) -> None:
        """The disk filling part-way: the old text is still there, the
        temporary file is gone, and the error is raised."""
        self.path.write_text("precious\n", encoding="utf-8")
        with mock.patch.object(os, "fsync", side_effect=FULL):
            with self.assertRaises(OSError) as caught:
                write_atomically(self.path, "half of the new text")
        self.assertEqual(caught.exception.errno, 28)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "precious\n")
        self.assertEqual(self.left_behind(), [])

    def test_a_new_file_that_fails_is_not_made(self) -> None:
        """No empty or partial file is left where the new one would be."""
        with mock.patch.object(os, "fsync", side_effect=FULL):
            with self.assertRaises(OSError):
                write_atomically(self.path, "text")
        self.assertFalse(self.path.exists())
        self.assertEqual(self.left_behind(), [])

    def test_a_replace_that_fails(self) -> None:
        """Where it cannot be put in place (and not for Windows' reason),
        the old file stays and the error is raised."""
        self.path.write_text("precious\n", encoding="utf-8")
        refused = PermissionError(13, "Permission denied")
        with (
            mock.patch.object(os, "replace", side_effect=refused),
            mock.patch.object(config, "_WINDOWS", False),
        ):
            with self.assertRaises(PermissionError):
                write_atomically(self.path, "new\n")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "precious\n")
        self.assertEqual(self.left_behind(), [])

    def test_windows_file_held_open(self) -> None:
        """On Windows, a file another program holds open cannot be replaced:
        it is written in place after all, once the text has been written
        safely beside it."""
        self.path.write_text("old\n", encoding="utf-8")
        refused = PermissionError(13, "Access is denied")
        with (
            mock.patch.object(os, "replace", side_effect=refused),
            mock.patch.object(config, "_WINDOWS", True),
        ):
            write_atomically(self.path, "new\n")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "new\n")
        self.assertEqual(self.left_behind(), [])

    @unittest.skipUnless(os.name == "posix", "POSIX permissions")
    def test_permissions_kept(self) -> None:
        """A file only its owner may read stays that way."""
        self.path.write_text("secret\n", encoding="utf-8")
        self.path.chmod(0o600)
        write_atomically(self.path, "still secret\n")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_a_symbolic_link_is_written_through(self) -> None:
        """The file it points to is written, and the link stays a link."""
        real = self.folder / "real.txt"
        real.write_text("old\n", encoding="utf-8")
        link = self.folder / "link.txt"
        try:
            link.symlink_to(real)
        except OSError:
            self.skipTest("symbolic links need privileges here")
        write_atomically(link, "new\n")
        self.assertTrue(link.is_symlink())
        self.assertEqual(real.read_text(encoding="utf-8"), "new\n")


class SettingsTests(unittest.TestCase):
    """The settings files are written the same way."""

    def test_settings_toml(self) -> None:
        """A failed save leaves ``settings.toml`` as it was, rather than
        empty (which would lose every other setting)."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.toml"
            path.write_text('theme = "dark"\nanimations = false\n', encoding="utf-8")
            with mock.patch.object(os, "fsync", side_effect=FULL):
                with self.assertRaises(OSError):
                    registry.save_show_mouse_setting(True, path)
            self.assertEqual(registry.read_theme_setting(path), "dark")
            self.assertFalse(registry.read_animations_setting(path))
            self.assertEqual(os.listdir(folder), ["settings.toml"])


if __name__ == "__main__":
    unittest.main()
