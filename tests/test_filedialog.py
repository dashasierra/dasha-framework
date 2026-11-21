"""Tests for the file dialog."""

import os
import tempfile
import unittest
from unittest import mock

from dasha import filedialog
from dasha.filedialog import FileDialog, list_drives
from tests.test_dialog import ask

S = os.sep
TEXT = [("Text files", "*.txt")]


class FileDialogTests(unittest.TestCase):
    """Listing, filtering and answering, in a folder made for the test."""

    def setUp(self) -> None:
        patcher = mock.patch.object(FileDialog, "show_drives", False)
        patcher.start()
        self.addCleanup(patcher.stop)
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.root = os.path.realpath(folder.name)
        for name in ("b_dir", "A_dir"):
            os.mkdir(os.path.join(self.root, name))
        for name, text in (("z.txt", "hello"), ("a.py", ""), ("B.txt", "x")):
            with open(os.path.join(self.root, name), "w", encoding="utf-8") as file:
                file.write(text)
        with open(os.path.join(self.root, "A_dir", "inner.txt"), "w", encoding="utf-8"):
            pass

    def dialog(self, **options: object) -> FileDialog:
        """A file dialog on the test's folder.

        :param options: Dialog options.
        """
        return FileDialog("Open", directory=self.root, **options)  # type: ignore[arg-type]

    def enter(self, dialog: FileDialog, typed: str) -> None:
        """Type into the Name box and press OK.

        :param dialog: The dialog.
        :param typed: Text to type.
        """
        dialog.name_box.text = typed
        dialog.accept()

    def test_listing(self) -> None:
        """.., then folders marked with os.sep, then files, ignoring case."""
        dialog = self.dialog()
        self.assertEqual(
            dialog.files.items,
            [f"..{S}", f"A_dir{S}", f"b_dir{S}", "a.py", "B.txt", "z.txt"],
        )
        self.assertEqual(dialog.directory, self.root)
        shown = dialog.path_label.text
        if shown != self.root:  # too long for the label (macOS): its end
            self.assertTrue(shown.startswith("..."), shown)
            self.assertTrue(self.root.endswith(shown[3:]), shown)
        self.assertEqual(dialog.type_box.items, ["All files (*)"])

    def test_no_parent_at_the_top(self) -> None:
        """At the top of a drive there is no ``..``."""
        dialog = FileDialog("Open", directory=os.path.abspath(os.sep))
        self.assertNotIn(f"..{S}", dialog.files.items)

    def test_the_type_filters(self) -> None:
        """The first type is used; choosing another lists again."""
        dialog = self.dialog(filters=TEXT)
        self.assertEqual(dialog.type_box.items, ["Text files (*.txt)", "All files (*)"])
        self.assertEqual(dialog.files.items[3:], ["B.txt", "z.txt"])
        dialog.type_box.choose(1)
        self.assertIn("a.py", dialog.files.items)

    def test_several_patterns(self) -> None:
        """A pattern can join several with ;."""
        dialog = self.dialog(filters=[("Mine", "*.py; z.*")])
        self.assertEqual(dialog.files.items[3:], ["a.py", "z.txt"])

    def test_typed_wildcard(self) -> None:
        """A typed wildcard becomes the filter."""
        dialog = self.dialog(filters=TEXT)
        self.enter(dialog, "*.py")
        self.assertEqual(dialog.files.items[3:], ["a.py"])
        self.assertIsNone(dialog.result)
        dialog.type_box.choose(1)
        self.assertEqual(len(dialog.files.items), 6)

    def test_folders(self) -> None:
        """Opening folders."""
        dialog = self.dialog()
        self.enter(dialog, f"A_dir{S}")
        self.assertEqual(dialog.directory, os.path.join(self.root, "A_dir"))
        self.assertEqual(dialog.files.items, [f"..{S}", "inner.txt"])
        self.assertEqual(dialog.name_box.text, "")
        self.enter(dialog, f"..{S}")
        self.assertEqual(dialog.directory, self.root)
        self.assertEqual(dialog.files.value, 1)

    def test_highlighting(self) -> None:
        """Moving the highlight fills the Name box and the bottom line."""
        dialog = self.dialog(name="kept.txt")
        self.assertEqual(dialog.name_box.text, "kept.txt")  # not the list's
        dialog.files.move_to(5)
        self.assertEqual(dialog.name_box.text, "z.txt")
        self.assertTrue(dialog.info_label.text.startswith("z.txt  5 bytes  "))
        dialog.files.move_to(4)
        self.assertTrue(dialog.info_label.text.startswith("B.txt  1 byte  "))
        dialog.files.move_to(1)
        self.assertEqual(
            (dialog.name_box.text, dialog.info_label.text), (f"A_dir{S}", "Folder")
        )

    def test_choosing_a_file(self) -> None:
        """OK on a file answers, with its path, folder and name."""
        dialog = self.dialog()
        self.enter(dialog, "z.txt")
        self.assertEqual(dialog.result, "ok")
        self.assertEqual(dialog.path, os.path.join(self.root, "z.txt"))
        self.assertEqual((dialog.directory, dialog.name), (self.root, "z.txt"))

    def test_typed_paths(self) -> None:
        """Relative to the folder shown, or absolute."""
        dialog = self.dialog()
        self.enter(dialog, os.path.join("A_dir", "inner.txt"))
        self.assertEqual(dialog.path, os.path.join(self.root, "A_dir", "inner.txt"))
        absolute = os.path.join(self.root, "b_dir", "new.txt")
        dialog = self.dialog()
        self.enter(dialog, absolute)
        self.assertEqual((dialog.result, dialog.path), ("ok", absolute))

    def test_must_exist(self) -> None:
        """A new name is fine for saving, but not with must_exist."""
        dialog = self.dialog(must_exist=True)
        self.enter(dialog, "new.txt")
        self.assertIsNone(dialog.result)
        self.assertEqual(dialog.info_label.text, "No such file")
        dialog = self.dialog()
        self.enter(dialog, "new.txt")
        self.assertEqual(dialog.result, "ok")

    def test_no_such_folder(self) -> None:
        """A file in a folder that is not there cannot be chosen."""
        dialog = self.dialog()
        self.enter(dialog, os.path.join("missing", "x.txt"))
        self.assertIsNone(dialog.result)
        self.assertEqual(dialog.info_label.text, "No such folder")

    def test_empty_name_does_nothing(self) -> None:
        """OK with nothing in the Name box does nothing."""
        dialog = self.dialog()
        self.enter(dialog, "  ")
        self.assertIsNone(dialog.result)

    def test_enter_on_the_list(self) -> None:
        """Enter on the list."""
        dialog = self.dialog()
        self.enter(dialog, "A_dir")
        dialog.focus(dialog.files)
        dialog.accept()
        self.assertEqual(dialog.directory, self.root)

    def test_unreadable_folder(self) -> None:
        """A folder that cannot be read leaves the list as it was."""
        dialog = self.dialog()
        with mock.patch("os.scandir", side_effect=PermissionError):
            self.assertFalse(dialog.change_directory(os.path.join(self.root, "A_dir")))
        self.assertEqual(dialog.directory, self.root)
        self.assertEqual(len(dialog.files.items), 6)
        self.assertEqual(dialog.info_label.text, "Cannot read this folder")

    def test_double_click_chooses(self) -> None:
        """The list's on_choose (a double-click) is OK on that item."""
        dialog = self.dialog()
        dialog.files.move_to(5)
        dialog.files.choose()
        self.assertEqual(dialog.path, os.path.join(self.root, "z.txt"))

    def run_dialog(self, inputs: list[str], **options: object) -> FileDialog:
        """Run the dialog on scripted input.

        :param inputs: Input to read.
        :param options: Dialog options.
        """
        dialog = self.dialog(**options)
        manager = ask(inputs, dialog)
        self.assertEqual(manager.answers, [dialog.result])
        return dialog

    def test_run_type_a_name(self) -> None:
        """The Name box has the focus; Enter is OK."""
        dialog = self.run_dialog(["z", ".", "t", "x", "t", "\r"])
        self.assertEqual(dialog.result, "ok")
        self.assertEqual(dialog.name, "z.txt")

    def test_run_escape(self) -> None:
        """Escape cancels."""
        dialog = self.run_dialog(["\x1b", ""])
        self.assertEqual(dialog.result, "cancel")


class DriveTests(unittest.TestCase):
    """The drive list, on Windows."""

    def test_listdrives(self) -> None:
        """os.listdrives is used where Python has it."""
        with (
            mock.patch.object(os, "name", "nt"),
            mock.patch.object(
                os, "listdrives", create=True, return_value=["C:\\", "D:\\"]
            ),
        ):
            self.assertEqual(list_drives(), ["C:\\", "D:\\"])

    def test_fallback(self) -> None:
        """Without os.listdrives, each letter is tried."""
        with (
            mock.patch.object(os, "name", "nt"),
            mock.patch.object(os, "listdrives", None, create=True),
            mock.patch.object(os.path, "exists", side_effect=lambda p: p[0] in "CE"),
        ):
            self.assertEqual(list_drives(), [f"C:{S}", f"E:{S}"])

    def test_not_windows(self) -> None:
        """Elsewhere there are no drives."""
        with mock.patch.object(os, "name", "posix"):
            self.assertEqual(list_drives(), [])

    def test_drive_box(self) -> None:
        """The drive shown follows the folder; choosing one goes to its top."""
        with (
            mock.patch.object(FileDialog, "show_drives", True),
            mock.patch.object(filedialog, "list_drives", return_value=["C:\\", "Q:\\"]),
        ):
            dialog = FileDialog("Open", directory=os.path.abspath(os.sep))
            assert dialog.drive_box is not None
            self.assertEqual(dialog.drive_box.items, ["C:", "Q:"])
            with mock.patch.object(dialog, "change_directory", return_value=True) as go:
                dialog.drive_box.choose(1)
            go.assert_called_once_with("Q:" + S)


if __name__ == "__main__":
    unittest.main()
