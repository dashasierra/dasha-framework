"""Tests for Notepad: its windows, files and questions."""

import os
import re
import tempfile
import unittest
from unittest import mock

from dasha.canvas import Canvas
from dasha.menu import MenuBar

from notepad import MODIFIED, Notepad, NotepadWindow
from tests.support import Scripted, run

ALT_F4 = "\x1b[1;3S"


class _Notepad(unittest.TestCase):
    """A folder with a file in it, and a desktop to run Notepad on."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.root = os.path.realpath(folder.name)
        self.notes = self.file("notes.txt", "hello\nworld\n")
        self.manager = Scripted()
        self.manager.handle_resize(80, 24)

    def file(self, name: str, text: str) -> str:
        """Write a file in the test's folder; returns its path."""
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        return path

    def text_of(self, path: str) -> str:
        """A file's text."""
        with open(path, encoding="utf-8", newline="") as file:
            return file.read()

    def launch(self, *paths: str) -> tuple[Notepad, NotepadWindow]:
        """Notepad with these files, and its front window."""
        notepad = self.manager.launch(Notepad(paths))
        assert isinstance(notepad, Notepad)
        window = notepad.windows[-1]
        assert isinstance(window, NotepadWindow)
        return notepad, window


class NotepadTests(_Notepad):
    """Notepad's windows, files and questions."""

    def test_starts_with_a_new_file(self) -> None:
        """With no files, one Untitled window."""
        notepad, window = self.launch()
        self.assertEqual(len(notepad.windows), 1)
        self.assertEqual(
            (window.title, window.path, window.modified), ("Untitled", None, False)
        )
        self.assertEqual(
            [m.title for m in notepad.menus], ["&File", "&Edit", "F&ormat"]
        )
        self.assertEqual(
            [m.title for m in self.manager.bar_menus()][1:],
            ["&File", "&Edit", "F&ormat", "&Window"],
        )

    def test_opens_files(self) -> None:
        """Each file in a window; a name not there yet opens empty."""
        notepad, window = self.launch(self.notes, os.path.join(self.root, "new.txt"))
        first = notepad.windows[0]
        assert isinstance(first, NotepadWindow)
        self.assertEqual(
            (first.title, first.area.text), ("notes.txt", "hello\nworld\n")
        )
        self.assertFalse(first.modified)
        self.assertEqual((window.title, window.area.text), ("new.txt", ""))

    def test_editing_and_saving(self) -> None:
        """Changes mark it modified; Save writes them."""
        _, window = self.launch(self.notes)
        window.area.insert("Oh, ")
        self.assertTrue(window.modified)
        self.assertTrue(window.save())
        self.assertFalse(window.modified)
        self.assertEqual(self.text_of(self.notes), "Oh, hello\nworld\n")

    def test_keeps_line_endings(self) -> None:
        """A file with Windows line endings is saved with them; the text
        area itself only ever has \\n."""
        path = self.file("windows.txt", "one\r\ntwo\r\n")
        _, window = self.launch(path)
        self.assertEqual(window.area.text, "one\ntwo\n")
        window.area.insert("1 ")
        self.assertTrue(window.save())
        self.assertEqual(self.text_of(path), "1 one\r\ntwo\r\n")
        window.load(path=self.notes, text="hello\n")
        self.assertEqual(window.newline, "\n")

    def test_a_file_already_open_comes_to_the_front(self) -> None:
        """Opening it again shows its window rather than a second one."""
        notepad, window = self.launch(self.notes)
        other = notepad.new()
        self.assertIs(notepad.active_window, other)
        self.assertIs(notepad.open_path(self.notes), window)
        self.assertEqual(len(notepad.windows), 2)
        self.assertIs(notepad.active_window, window)

    def test_open_reuses_an_untouched_window(self) -> None:
        """A new, empty, unchanged window takes the file; otherwise a new one."""
        notepad, window = self.launch()
        self.assertIs(notepad.open_path(self.notes), window)
        self.assertEqual(len(notepad.windows), 1)
        other = notepad.open_path(self.file("b.txt", "b"))
        self.assertIsNot(other, window)
        self.assertEqual(len(notepad.windows), 2)

    def test_new_windows_cascade(self) -> None:
        """Each new window a little down and right."""
        notepad, window = self.launch()
        second = notepad.new()
        self.assertEqual(
            (second.rect.row, second.rect.column),
            (window.rect.row + 1, window.rect.column + 2),
        )

    def test_not_utf8(self) -> None:
        """A file that is not UTF-8 is not opened (and nothing breaks)."""
        path = os.path.join(self.root, "binary.dat")
        with open(path, "wb") as file:
            file.write(b"\xff\xfe\x00")
        notepad, _ = self.launch()
        self.assertIsNone(notepad.read(path))
        self.assertIsNone(notepad.open_path(path))

    def test_unreadable_file_named_at_start(self) -> None:
        """A file named on the command line that cannot be read is not
        opened, and says why once the desktop is running."""
        path = os.path.join(self.root, "binary.dat")
        with open(path, "wb") as file:
            file.write(b"\xff\xfe\x00")
        notepad, window = self.launch(path)
        self.assertEqual((len(notepad.windows), window.path), (1, None))
        self.manager.actions.append(self.manager.quit)
        terminal = run(self.manager, ["\r", "x"])  # OK, then stop
        self.assertIn("binary.dat is not UTF-8 text.", terminal.output.getvalue())
        self.assertEqual(terminal.inputs, [])

    def test_close_asks_to_save(self) -> None:
        """Closing with changes asks; Don't save closes without them."""
        notepad, window = self.launch(self.notes)
        window.area.insert("changed ")
        self.manager.actions.append(self.manager.quit)
        run(self.manager, [ALT_F4, "d", "x"])  # D: Don't save
        self.assertEqual(notepad.windows, [])
        self.assertTrue(notepad.is_running)  # runs on, windows or not
        self.assertEqual(self.text_of(self.notes), "hello\nworld\n")

    def test_close_and_save(self) -> None:
        """Saving from the question writes the file."""
        notepad, window = self.launch(self.notes)
        window.area.insert("saved ")
        self.manager.actions.append(self.manager.quit)
        run(self.manager, [ALT_F4, "\r", "x"])  # Save is the default
        self.assertEqual(notepad.windows, [])
        self.assertTrue(notepad.is_running)  # runs on, windows or not
        self.assertEqual(self.text_of(self.notes), "saved hello\nworld\n")

    def test_close_cancelled(self) -> None:
        """Cancel keeps the window and its changes."""
        notepad, window = self.launch(self.notes)
        window.area.insert("kept ")
        self.manager.actions.append(self.manager.quit)
        run(self.manager, [ALT_F4, "\x1b", "", "x"])
        self.assertTrue(notepad.is_running)
        self.assertTrue(window.modified)

    def test_unchanged_closes_without_asking(self) -> None:
        """No changes, no question."""
        notepad, _ = self.launch(self.notes)
        self.manager.actions.append(self.manager.quit)
        run(self.manager, [ALT_F4, "x"])
        self.assertEqual(notepad.windows, [])
        self.assertTrue(notepad.is_running)  # runs on, windows or not

    def test_save_as(self) -> None:
        """Save as: a new name in the file dialog, and the title follows."""
        _, window = self.launch(self.notes)
        self.manager.actions += [window.save_as, self.manager.quit]
        run(self.manager, ["x", "\x01", *"other.txt", "\r", "x"])  # Ctrl+A, type
        other = os.path.join(self.root, "other.txt")
        self.assertEqual((window.path, window.title), (other, "other.txt"))
        self.assertEqual(self.text_of(other), "hello\nworld\n")

    def test_save_as_that_fails_keeps_the_name(self) -> None:
        """If the new file cannot be written, the window is still the file
        it was."""
        _, window = self.launch(self.notes)
        self.manager.actions += [window.save_as, self.manager.quit]
        with mock.patch.object(NotepadWindow, "save", return_value=False):
            run(self.manager, ["x", "\x01", *"other.txt", "\r", "x"])
        self.assertEqual((window.path, window.title), (self.notes, "notes.txt"))

    def test_a_failed_save_keeps_the_file(self) -> None:
        """The disk filling part-way through a save: the file still has its
        old text, the window still has its changes, and it says so."""
        _, window = self.launch(self.notes)
        window.area.insert("changed ")
        full = OSError(28, "No space left on device")
        self.manager.actions += [window.save, self.manager.quit]
        with mock.patch("dasha.config.os.fsync", side_effect=full):
            terminal = run(self.manager, ["x", "\r", "x"])  # Save, OK
        self.assertEqual(self.text_of(self.notes), "hello\nworld\n")
        self.assertTrue(window.modified)
        self.assertIn("No space left on device", terminal.output.getvalue())
        self.assertEqual(sorted(os.listdir(self.root)), ["notes.txt"])

    def test_save_as_replace(self) -> None:
        """Saving over another file asks first."""
        self.file("other.txt", "old")
        _, window = self.launch(self.notes)
        self.manager.actions += [window.save_as, window.save_as, self.manager.quit]
        keys = ["\x01", *"other.txt", "\r"]
        run(self.manager, ["x", *keys, "\x1b", "", "x", *keys, "\r", "x"])
        self.assertEqual(
            self.text_of(os.path.join(self.root, "other.txt")), "hello\nworld\n"
        )

    def test_untitled_save_asks_for_a_name(self) -> None:
        """Save on a new file is Save as; cancelling it saves nothing."""
        _, window = self.launch()
        window.area.insert("text")
        self.manager.actions += [window.save, self.manager.quit]
        run(self.manager, ["x", "\x1b", "", "x"])
        self.assertIsNone(window.path)
        self.assertTrue(window.modified)

    def test_exit_offers_to_save_each(self) -> None:
        """Shutting the desktop down offers to save, and can be stopped."""
        notepad, window = self.launch(self.notes)
        window.area.insert("more ")
        self.manager.actions.append(self.manager.quit)
        # Shutdown, then Cancel the save question: still running; then quit.
        run(self.manager, ["\x11", "\r", "\x1b", "", "x"])
        self.assertTrue(notepad.is_running)
        self.assertTrue(window.modified)

    def test_exit_with_a_minimised_window(self) -> None:
        """A minimised window with unsaved changes comes back to ask about
        them at shutdown; Save keeps them."""
        _, window = self.launch(self.notes)
        window.area.insert("more ")
        self.manager.minimise(window)
        self.manager.actions.append(self.manager.quit)
        run(self.manager, ["\x11", "\r", "s", "x"])  # Shutdown, OK, Save
        self.assertEqual(self.text_of(self.notes), "more hello\nworld\n")
        self.assertFalse(window.modified)

    def test_file_exit(self) -> None:
        """File > Exit offers to save, then ends Notepad."""
        notepad, window = self.launch(self.notes)
        window.area.insert("x")
        self.manager.actions += [notepad.exit, self.manager.quit]
        run(self.manager, ["x", "\r", "x"])  # Exit, then Save
        self.assertFalse(notepad.is_running)
        self.assertEqual(self.text_of(self.notes), "xhello\nworld\n")


class DisplayTests(_Notepad):
    """What a Notepad window shows: its text, and the cursor's place."""

    def test_escape_sequences_shown_not_sent(self) -> None:
        """A file holding escape sequences shows them as code page 437
        pictures, sends none of them to the terminal, and is saved back
        just as it was."""
        text = "Title\x1b]0;pwned\x07 and \x1b[2Jclear\n"
        path = self.file("escapes.txt", text)
        _, window = self.launch(path)
        canvas = Canvas(80, 24)
        self.manager.compose(canvas)
        # What the terminal is sent, less Dasha Framework's own moves and styles.
        output = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", canvas.render())
        self.assertIn("Title\N{LEFTWARDS ARROW}]0;pwned\N{BULLET} and", output)
        self.assertNotIn("\x1b", output)
        self.assertNotIn("\x07", output)
        window.modified = True
        self.assertTrue(window.save())
        self.assertEqual(self.text_of(path), text)

    def test_cursor_place_at_the_foot(self) -> None:
        """COL:ROW at the foot of the frame, both from 1: a tab counts as
        one character; with word wrap, ROW counts lines, not rows."""
        notepad, window = self.launch()
        self.assertEqual(window.footer_parts(), ["1:1"])
        window.load(path=self.notes, text="\tab\nsecond")
        window.area.cursor = (0, 3)
        self.assertEqual(window.footer_parts(), ["4:1"])
        notepad.toggle_word_wrap()
        window.load(path=self.notes, text="word " * 30 + "\nnext")
        window.area.handle_key("down", self.manager.shortcuts)  # its second row
        line, character = window.area.cursor
        self.assertEqual(line, 0)
        self.assertEqual(window.footer_parts(), [f"{character + 1}:1"])
        edge = self.bottom_edge(window)
        self.assertTrue(edge.startswith(f"╚═ {character + 1}:1 ═"), edge)

    def test_changes_marked_at_the_foot(self) -> None:
        """``☼`` before COL:ROW while there are changes to save, the
        frame's own line between them; saving takes it away."""
        _, window = self.launch(self.notes)
        window.area.insert("x")
        self.assertEqual(window.footer_parts(), [MODIFIED, "2:1"])
        self.assertTrue(self.bottom_edge(window).startswith(f"╚═ {MODIFIED} ═ 2:1 ═"))
        self.assertTrue(window.save())
        self.assertEqual(window.footer_parts(), ["2:1"])

    def bottom_edge(self, window: NotepadWindow) -> str:
        """A window's bottom edge, as the desktop draws it."""
        canvas = Canvas(80, 24)
        self.manager.compose(canvas)
        return canvas.text(window.rect.bottom - 1)[window.rect.column :]


class MenuTests(_Notepad):
    """Notepad's Edit and Format menus."""

    def test_no_letter_is_repeated(self) -> None:
        """No two menus on the bar, and no two items of a menu, share a
        letter."""
        self.launch(self.notes)
        menu_bar = MenuBar()
        menu_bar.set_menus(self.manager.bar_menus())
        menu_bar.check_mnemonics()

    def test_insert_needs_a_window(self) -> None:
        """Edit > Insert, and everything in it, greyed out with no file open."""
        notepad, window = self.launch()
        insert = next(i for i in notepad.menus[1].items if i.label == "&Insert")
        assert insert.submenu is not None
        box = next(i for i in insert.submenu.items if i.label == "&Box")
        assert box.submenu is not None
        everything = [insert, *insert.submenu.items, *box.submenu.items]
        self.assertTrue(all(item.is_available for item in everything))
        self.manager.close(window)
        self.assertEqual([item.label for item in everything if item.is_available], [])

    def test_menus_act_on_the_front_window(self) -> None:
        """Edit acts on the file in front, and is greyed out with none."""
        notepad, first = self.launch(self.notes)
        second = notepad.new()
        edit = notepad.menus[1]
        select_all = next(i for i in edit.items if i.label == "Select &all")
        cut = next(i for i in edit.items if i.label == "Cu&t")
        assert select_all.action is not None and cut.action is not None
        self.manager.bring_to_front(first)
        select_all.action()
        cut.action()
        self.assertEqual((first.area.text, second.area.text), ("", ""))
        self.assertTrue(first.modified)
        first.modified = False
        for window in list(notepad.windows):
            self.manager.close(window)
        self.assertFalse(cut.is_available)
        save = next(i for i in notepad.menus[0].items if i.label == "&Save")
        self.assertFalse(save.is_available)
        self.assertTrue(notepad.is_running)

    def test_word_wrap(self) -> None:
        """Format > Word wrap, off to begin with, wraps every window, and
        those opened later; it is marked while on, and turns off again."""
        notepad, first = self.launch(self.notes)
        wrap = notepad.menus[2].items[0]
        self.assertEqual(wrap.label, "  &Word wrap")
        self.assertFalse(first.area.word_wrap)
        assert wrap.action is not None
        wrap.action()
        self.assertEqual(wrap.label, "\N{SQUARE ROOT} &Word wrap")
        second = notepad.new()
        self.assertTrue(first.area.word_wrap and second.area.word_wrap)
        wrap.action()
        self.assertFalse(first.area.word_wrap or second.area.word_wrap)
        self.assertEqual(wrap.label, "  &Word wrap")

    def test_line_numbers(self) -> None:
        """Format > Line numbers, off to begin with, numbers every window's
        lines, and those opened later; marked while on, it turns off again."""
        notepad, first = self.launch(self.notes)
        numbers = notepad.menus[2].items[1]
        self.assertEqual(numbers.label, "  &Line numbers")
        self.assertFalse(first.area.line_numbers)
        assert numbers.action is not None
        numbers.action()
        self.assertEqual(numbers.label, "\N{SQUARE ROOT} &Line numbers")
        second = notepad.new()
        self.assertTrue(first.area.line_numbers and second.area.line_numbers)
        self.assertFalse(first.area.word_wrap)  # the other stays as it was
        numbers.action()
        self.assertFalse(first.area.line_numbers or second.area.line_numbers)
        self.assertEqual(numbers.label, "  &Line numbers")

    def test_line_numbers_from_the_keyboard(self) -> None:
        """Alt+O, L numbers the lines."""
        notepad, window = self.launch(self.notes)
        self.manager.actions.append(self.manager.quit)
        run(self.manager, ["\x1bo", "l", "x"])
        self.assertTrue(notepad.line_numbers and window.area.line_numbers)

    def test_word_wrap_from_the_keyboard(self) -> None:
        """Alt+O, W turns it on; a long line then goes on below."""
        notepad, window = self.launch()
        self.manager.actions.append(self.manager.quit)
        run(self.manager, ["\x1bo", "w", "word " * 20, "x"])
        self.assertTrue(notepad.word_wrap)
        self.assertEqual(window.area.rect.width, window.interior.width)
        self.assertEqual(window.area.lines, ["word " * 20])


if __name__ == "__main__":
    unittest.main()
