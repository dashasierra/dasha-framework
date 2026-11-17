"""Tests that text from outside (a file's contents, a file's name, an
application's title, a manifest) can never send an escape sequence, or any
other control character, to the terminal: on the screen, every widget,
title, menu and bar shows control characters as their code page 437
pictures, and the messages printed on the terminal itself do the same."""

import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from dasha.__main__ import _report_unsaid, main
from dasha.canvas import Canvas, Rect
from dasha.dialog import information
from dasha.hosting import AppServer
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuItem
from dasha.printing import printable, say
from dasha.widgets import (
    Button,
    CheckBoxes,
    Collapsible,
    Column,
    ComboBox,
    GroupBox,
    Label,
    ListBox,
    Paragraph,
    RadioButtons,
    Table,
    Tabs,
    TextArea,
    TextBox,
    TreeNode,
    TreeView,
)
from dasha.window import Window
from tests.support import isolated_home

PAYLOAD = "a\x1b]0;pwned\x07\x1b[2J\x9b31m\r\x08\x00\u202eb"
"""Hostile text: sets the terminal's title (OSC), clears the screen, a C1
CSI, a carriage return, backspace, NUL and a right-to-left override."""

SHOWN = "a\N{LEFTWARDS ARROW}]0;pwned\N{BULLET}\N{LEFTWARDS ARROW}[2J?31m"
"""How the screen shows the start of it: its pictures, in its place."""

_OWN = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
"""The sequences Dasha Framework itself sends: cursor moves, styles, showing and
hiding the cursor."""

_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def without_own_sequences(output: str) -> str:
    """Terminal output with Dasha Framework's own sequences taken out: what is
    left must be text alone."""
    return _OWN.sub("", output)


class ScreenTests(unittest.TestCase):
    """Nothing on the screen sends a control character."""

    def assert_safe(self, output: str, *, shows: bool = True) -> None:
        """No control character but Dasha Framework's own sequences, and (with
        ``shows``) the payload shown as pictures."""
        text = without_own_sequences(output)
        self.assertIsNone(_CONTROL.search(text), repr(_CONTROL.findall(text)))
        if shows:
            self.assertIn(SHOWN, text)

    def render(self, manager: PresentationManager) -> str:
        """The whole screen, as the terminal is sent it."""
        manager.handle_resize(100, 40)
        canvas = Canvas(100, 40)
        manager.compose(canvas)
        return canvas.render()

    def test_every_widget(self) -> None:
        """Each widget showing the payload as its text, label or items."""
        window = Window(PAYLOAD, Rect(1, 0, 38, 100), [PAYLOAD], status=PAYLOAD)
        widgets = [
            Label(PAYLOAD, 1, 1),
            Button(PAYLOAD, 2, 1),
            CheckBoxes([PAYLOAD], 4, 1),
            RadioButtons([PAYLOAD], 5, 1),
            Collapsible(PAYLOAD, 6, 1),
            ComboBox([PAYLOAD], 7, 1, 40),
            ListBox([PAYLOAD], 8, 1, 40, 2),
            Paragraph(PAYLOAD, 10, 1, 40),
            Table([Column(PAYLOAD, 30)], 12, 1, 40, 3, rows=[[PAYLOAD]]),
            TreeView([TreeNode(PAYLOAD)], 15, 1, 40, 2),
            TextBox(17, 1, 40, text=PAYLOAD.replace("\r", "")),  # one line
            TextArea(18, 1, 40, 2, text=PAYLOAD),
            GroupBox(PAYLOAD, 21, 1, 40, 3),
        ]
        tabs = Tabs(25, 1, 40, 4)
        tabs.add_page(PAYLOAD)
        for widget in [*widgets, tabs]:
            with self.subTest(widget=type(widget).__name__):
                manager = PresentationManager()
                shown = Window(PAYLOAD, Rect(1, 0, 38, 100))
                shown.add(widget)
                manager.add(shown)
                self.assert_safe(self.render(manager))
        manager = PresentationManager()
        manager.add(window)
        self.assert_safe(self.render(manager))  # title, lines, status bar

    def test_text_area_wrapped_and_numbered(self) -> None:
        """A text area wrapping, with line numbers, and a selection."""
        manager = PresentationManager()
        window = Window("W", Rect(1, 0, 20, 60))
        area = window.add(
            TextArea(0, 0, text=PAYLOAD * 4, word_wrap=True, line_numbers=True)
        )
        manager.add(window)
        area.select((0, 0), (0, 40))
        self.assert_safe(self.render(manager))

    def test_menus_and_dialogs(self) -> None:
        """A menu's title and items, open, and a dialog's message."""
        manager = PresentationManager()
        menu = Menu(PAYLOAD, [MenuItem(PAYLOAD, status=PAYLOAD)])
        manager.add(Window("W", Rect(1, 0, 10, 60), menus=[menu]))
        manager.add(information(PAYLOAD, PAYLOAD))
        self.assert_safe(self.render(manager))
        manager.remove(manager.windows[-1])
        manager.menu_bar.set_menus(manager.bar_menus())
        manager.menu_bar.open(1)
        self.assert_safe(self.render(manager))

    def test_text_typed_and_pasted(self) -> None:
        """Pasted into a text box or a text area, the payload stays as it
        is, and is shown as pictures."""
        box = TextBox(0, 0, 40)
        self.assertTrue(box.handle_paste(PAYLOAD.replace("\r", "")))
        self.assertIn("\x1b", box.text)
        self.assertFalse(box.accepts("one\ntwo"))  # still one line
        area = TextArea(0, 0, 40, 2)
        area.handle_paste(PAYLOAD)
        self.assertIn("\x1b]0;pwned", area.text)


class ConsoleTests(unittest.TestCase):
    """Messages printed on the terminal itself."""

    def test_printable(self) -> None:
        """Control characters become pictures; line breaks and tabs stay;
        what would print as nothing, or reorder the line, becomes ?."""
        self.assertEqual(printable("plain text"), "plain text")
        self.assertEqual(printable("a\nb\tc"), "a\nb\tc")
        self.assertEqual(
            printable("\x1b[2J\x07\r\x9b\u202e\udcff"),
            "\N{LEFTWARDS ARROW}[2J\N{BULLET}\N{EIGHTH NOTE}???",
        )

    def test_say(self) -> None:
        """``say`` prints as ``print`` does, made safe."""
        out = StringIO()
        with redirect_stdout(out):
            say("name:", PAYLOAD)
        self.assertEqual(out.getvalue().count("\n"), 1)
        self.assertIsNone(_CONTROL.search(out.getvalue().rstrip("\n")))
        err = StringIO()
        say(PAYLOAD, file=err)
        self.assertIn(SHOWN, err.getvalue())

    def test_crash_reported_after_the_screen(self) -> None:
        """What the desktop could not say before it ended, such as an
        application's last words in its log, is printed made safe."""
        manager = PresentationManager()
        server = AppServer(manager)
        self.addCleanup(server.stop_all, 0)
        manager.server = server
        server.notices.append((PAYLOAD, PAYLOAD))
        err = StringIO()
        with redirect_stderr(err):
            _report_unsaid(manager)
        self.assertIsNone(_CONTROL.search(err.getvalue().rstrip("\n")))
        server.stop_all()

    def test_manifest_listed(self) -> None:
        """An installed application's name from its manifest, as list-apps
        prints it."""
        home = isolated_home(self)
        (home / "apps").mkdir()
        (home / "apps" / "evil.toml").write_text(
            'name = "Evil\\u001b]0;pwned\\u0007"\nscript = "evil.py"\n',
            encoding="utf-8",
        )
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["list-apps"]), 0)
        self.assertIn("Evil\N{LEFTWARDS ARROW}]0;pwned", out.getvalue())
        self.assertIsNone(_CONTROL.search(out.getvalue().replace("\n", "")))


if __name__ == "__main__":
    unittest.main()
