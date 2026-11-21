"""Tests for dialog boxes: modality, results, and reading their widgets."""

import unittest
from typing import cast

from dasha import __version__
from dasha.canvas import Rect
from dasha.dialog import Dialog, confirm, information
from dasha.events import Event
from dasha.manager import PresentationManager
from dasha.terminal import Terminal
from dasha.widgets import Button, Label
from dasha.window import Window

from tests.support import assert_lines_shown, without_styles
from tests.test_manager import FakeTerminal


class AskingManager(PresentationManager):
    """Opens a dialog on "x" and keeps the answer.

    :param dialog: The dialog.
    :param windows: Windows to start with, if any.
    """

    def __init__(self, dialog: Dialog, windows: list[Window] | None = None) -> None:
        super().__init__(windows=windows or [])
        self.dialog = dialog
        self.answers: list[str | None] = []

    def handle_event(self, event: Event) -> None:
        if event == "x":
            self.answers.append(self.execute(self.dialog))
        else:
            super().handle_event(event)


def ask(inputs: list[str], dialog: Dialog | None = None) -> AskingManager:
    """Run a manager that opens a dialog.

    :param inputs: Input after "x".
    :param dialog: The dialog, if not the default.
    """
    manager = AskingManager(dialog or confirm("Question", "Really?"))
    manager.handle_resize(60, 20)
    terminal = FakeTerminal(["x", *inputs, "\x11", "\r"], sizes=[(60, 20)])
    manager.run(cast(Terminal, terminal))
    return manager


class ConfirmTests(unittest.TestCase):
    """The ready-made OK / Cancel dialog."""

    def test_layout_and_names(self) -> None:
        """A message, OK (default, focused) and Cancel, all named."""
        dialog = confirm("Exit", "Leave now?\nReally?")
        self.assertEqual(
            dialog.values,
            {
                "message": "Leave now?",
                "message2": "Really?",
                "ok": "ok",
                "cancel": "cancel",
            },
        )
        ok = dialog.widget("ok")
        self.assertIs(dialog.focused, ok)
        self.assertIs(dialog.default_button, ok)
        self.assertTrue(dialog.closable)
        self.assertFalse(dialog.resizable)

    def test_centre(self) -> None:
        """centre() puts the dialog in the middle of an area."""
        dialog = Dialog("D", 20, 6)
        dialog.centre(Rect(1, 0, 22, 80))
        self.assertEqual(dialog.rect, Rect(9, 30, 6, 20))


class ExecuteTests(unittest.TestCase):
    """execute() waits for the answer and returns it."""

    def test_enter_answers_ok(self) -> None:
        """Enter presses the focused OK button."""
        self.assertEqual(ask(["\r"]).answers, ["ok"])

    def test_escape_cancels(self) -> None:
        """Escape (after the escape timeout) cancels."""
        self.assertEqual(ask(["\x1b", ""]).answers, ["cancel"])

    def test_tab_then_enter_answers_cancel(self) -> None:
        """Tab moves the focus to Cancel inside the dialog."""
        self.assertEqual(ask(["\t", "\r"]).answers, ["cancel"])

    def test_plain_letter_presses_button(self) -> None:
        """In a dialog, a button's letter works without Alt."""
        self.assertEqual(ask(["c"]).answers, ["cancel"])

    def test_close_button_cancels(self) -> None:
        """The dialog's [■] button cancels it."""
        dialog = confirm("Question", "Really?")
        dialog.centre(Rect(1, 0, 18, 60))  # where execute() will put it
        close = [cells for action, cells in dialog.title_buttons if action == "close"][
            0
        ]
        click = f"\x1b[<0;{close.column + 2};{close.row + 1}M"
        self.assertEqual(ask([click], dialog).answers, ["cancel"])

    def test_dialog_is_removed_but_still_readable(self) -> None:
        """After the answer the dialog leaves the screen; its widgets remain."""
        dialog = confirm("Question", "Really?")
        name_label = dialog.add(Label("Name: Dasha", 2, 2, name="name"))
        manager = ask(["\r"], dialog)
        self.assertNotIn(dialog, manager.windows)
        self.assertEqual(dialog.result, "ok")
        self.assertEqual(dialog.values["name"], "Name: Dasha")
        self.assertIs(dialog.widget("name"), name_label)

    def test_custom_results(self) -> None:
        """A dialog can have any buttons, with any results."""
        dialog = Dialog("Save?", 40, 8)
        dialog.add(Button("&Save", 2, 1, result="save"))
        dialog.add(Button("&Discard", 2, 14, result="discard"))
        dialog.add(Button("Cancel", 2, 27, result="cancel"))
        self.assertEqual(ask(["d"], dialog).answers, ["discard"])

    def test_execute_needs_running_manager(self) -> None:
        """Outside run(), execute() cannot read input and says so."""
        with self.assertRaises(RuntimeError):
            PresentationManager().execute(confirm("Q", "?"))


class ModalTests(unittest.TestCase):
    """While a dialog waits, nothing else responds."""

    def test_other_windows_and_menus_do_not_respond(self) -> None:
        """Clicks outside, Tab between windows and F10 are all ignored."""
        back = Window("Back", Rect(1, 0, 6, 20))
        manager = AskingManager(confirm("Question", "Really?"), windows=[back])
        manager.handle_resize(60, 20)
        terminal = FakeTerminal(
            ["x", "\x1b[<0;2;3M\x1b[<0;2;3m", "\x1b[21~", "\r", "\x11", "\r"],
            sizes=[(60, 20)],
        )
        manager.run(cast(Terminal, terminal))
        self.assertEqual(manager.answers, ["ok"])  # F10 did not open a menu
        self.assertIs(manager.active_window, back)  # nothing else was raised


class ExitConfirmationTests(unittest.TestCase):
    """Leaving Dasha Framework asks first."""

    def run_manager(self, inputs: list[str], confirm_exit: bool = True) -> FakeTerminal:
        """Run a manager on scripted input.

        :param inputs: Input to read.
        :param confirm_exit: Whether exit asks first.
        """
        manager = PresentationManager()
        manager.confirm_exit = confirm_exit
        terminal = FakeTerminal(inputs, sizes=[(60, 20)])
        manager.run(cast(Terminal, terminal))
        self.assertFalse(manager.is_running)
        return terminal

    def test_ok_leaves(self) -> None:
        """OK leaves."""
        terminal = self.run_manager(["\x11", "\r", "never read"])
        self.assertEqual(terminal.inputs, ["never read"])

    def test_cancel_stays(self) -> None:
        """Cancel stays."""
        terminal = self.run_manager(["\x11", "c", "\x11", "s", "never read"])
        self.assertEqual(terminal.inputs, ["never read"])

    def test_exit_dialog_shows_on_screen(self) -> None:
        """The exit dialog is drawn."""
        terminal = self.run_manager(["\x11", "\r"])
        output = terminal.output.getvalue()
        assert_lines_shown(self, PresentationManager.exit_message, output)
        # Without colour changes (a button's letter has its own colour).
        for text in (" Exit ", "Shutdown", "Cancel"):
            self.assertIn(text, without_styles(output))

    def test_without_confirmation(self) -> None:
        """With confirm_exit off, Ctrl+Q leaves at once."""
        terminal = self.run_manager(["\x11", "never read"], confirm_exit=False)
        self.assertEqual(terminal.inputs, ["never read"])


class InformationTests(unittest.TestCase):
    """The ready-made OK-only dialog."""

    def test_layout_and_names(self) -> None:
        """A message and one OK button, the default, focused and named."""
        dialog = information("Done", "Saved.\nAll good.")
        self.assertEqual(
            dialog.values, {"message": "Saved.", "message2": "All good.", "ok": "ok"}
        )
        ok = dialog.widget("ok")
        self.assertIs(dialog.focused, ok)
        assert isinstance(ok, Button)
        self.assertTrue(ok.default)
        self.assertEqual(sum(isinstance(w, Button) for w in dialog.widgets), 1)

    def test_answers(self) -> None:
        """Enter answers "ok"; Escape cancels, as with any dialog."""
        self.assertEqual(ask(["\r"], information("Done", "Saved.")).answers, ["ok"])
        cancelled = ask(["\x1b", ""], information("Done", "Saved."))
        self.assertEqual(cancelled.answers, ["cancel"])


class AboutTests(unittest.TestCase):
    """About, in the system menu."""

    def test_about_shows_the_message(self) -> None:
        """F10, then A: the About box, with the version; Enter closes it."""
        manager = PresentationManager()
        terminal = FakeTerminal(["\x1b[21~", "a", "\r", "\x11", "\r"], sizes=[(60, 20)])
        manager.run(cast(Terminal, terminal))
        output = terminal.output.getvalue()
        assert_lines_shown(self, manager.about_title, output)
        assert_lines_shown(self, manager.about_message, output)  # every line
        self.assertIn(__version__, manager.about_message)
        self.assertEqual(terminal.inputs, [])

    def test_about_outside_a_run_does_nothing(self) -> None:
        """About outside a run does nothing."""
        PresentationManager().about_box()


if __name__ == "__main__":
    unittest.main()
