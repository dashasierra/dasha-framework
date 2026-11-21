"""Tests for hosted windows' own colours."""

import unittest

from dasha import theme
from dasha.canvas import Canvas, Rect
from dasha.client import ClientManager, colours_of
from dasha.dialog import Dialog
from dasha.hosting import AppHost, AppServer
from dasha.manager import PresentationManager
from dasha.protocol import ProtocolError, encode_style
from dasha.remote import RemoteWindow
from dasha.style import BLACK, BRIGHT_WHITE, RED, Style
from dasha.window import Window
from tests.hosted_apps import Hello
from tests.support import hosted, pipe
from tests.test_hosting import WELCOME, drain, of_type
from tests.test_theme import ThemeIsolation
from tests.test_waiting_dialogs import state

DARK = Style(foreground=BRIGHT_WHITE, background=BLACK)
LOUD = Style(foreground=RED, background=BLACK)


class _DarkWindow(Window):
    """A window whose class chooses its frame and body colours."""

    frame_style = DARK
    body_style = DARK


class ColoursSentTests(unittest.TestCase):
    """What the application tells the desktop."""

    def test_none_unless_chosen(self) -> None:
        """Windows and dialogs in the theme's colours send none."""
        self.assertEqual(colours_of(Window("W", Rect(0, 0, 5, 20))), {})
        self.assertEqual(colours_of(Dialog("D", 20, 5)), {})

    def test_a_class_or_a_window_chooses(self) -> None:
        """From a subclass's attributes, or one window's."""
        self.assertEqual(
            colours_of(_DarkWindow("W", Rect(0, 0, 5, 20))),
            {"frame_style": encode_style(DARK), "body_style": encode_style(DARK)},
        )
        dialog = Dialog("D", 20, 5)
        dialog.button_style = LOUD
        self.assertEqual(colours_of(dialog), {"button_style": encode_style(LOUD)})

    def test_sent_with_the_window_and_as_they_change(self) -> None:
        """They go with the window, and again when they change."""
        desktop, app_end = pipe()
        manager = ClientManager(app_end, WELCOME)
        self.addCleanup(manager.stop_listening)
        window = manager.launch(Hello).windows[0]
        manager.flush()
        self.assertEqual(of_type(drain(desktop), "window")[0]["colours"], {})
        window.frame_style = DARK
        manager.flush()
        self.assertEqual(
            of_type(drain(desktop), "window")[0]["colours"],
            {"frame_style": encode_style(DARK)},
        )


class ColoursShownTests(ThemeIsolation):
    """What the desktop does with them."""

    def setUp(self) -> None:
        super().setUp()
        self.manager = PresentationManager()
        self.manager.handle_resize(80, 24)
        server = AppServer(self.manager)
        self.manager.server = server
        self.addCleanup(server.stop_all)
        self.host: AppHost = hosted(server, "Hello")[0]

    def window(self, **changes: object) -> RemoteWindow:
        """The window after an application message.

        :param changes: Fields to change.
        """
        self.host.handle(state(id=1, **changes))
        window = self.host.windows[1]
        assert isinstance(window, RemoteWindow)
        return window

    def frame(self, window: RemoteWindow) -> Style:
        """The top edge's style, drawn active.

        :param window: The window.
        """
        canvas = Canvas(80, 24)
        window.paint(canvas, True)
        return canvas.cell(window.rect.row, window.rect.column + 6)[1]

    def test_the_frame_is_drawn_in_them(self) -> None:
        """Frame, body and the rest, each only as chosen."""
        window = self.window(colours={"frame_style": encode_style(DARK)})
        self.assertEqual(self.frame(window), DARK)
        self.assertEqual(window.body_style, Window.body_style)

    def test_with_none_sent_the_theme(self) -> None:
        """With none sent, the theme's."""
        window = self.window()
        self.assertEqual(self.frame(window), Window.frame_style)
        self.window(colours={"frame_style": encode_style(DARK)})
        self.window(colours={})
        self.assertEqual(self.frame(window), Window.frame_style)

    def test_a_dialogs_others_stay_a_dialogs(self) -> None:
        """Whatever a dialog does not choose is the theme's for a dialog."""
        window = self.window(
            look="dialog", colours={"button_style": encode_style(LOUD)}
        )
        self.assertEqual(window.button_style, LOUD)
        self.assertEqual(window.frame_style, Dialog.frame_style)

    def test_a_new_theme_changes_only_the_others(self) -> None:
        """Its own colours stay through a change of theme."""
        window = self.window(colours={"frame_style": encode_style(DARK)})
        self.manager.set_theme("dark")
        self.assertEqual(window.frame_style, DARK)
        self.assertEqual(window.body_style, theme.DARK_THEME["window.body"])

    def test_only_the_frames_colours_are_taken(self) -> None:
        """Only frame colours are taken."""
        window = self.window(colours={"modal": encode_style(DARK), "host": "x"})
        self.assertFalse(window.modal)
        self.assertIs(window.host, self.host)

    def test_bad_colours_are_refused(self) -> None:
        """Bad colours are refused."""
        self.window()
        with self.assertRaises(ProtocolError):
            self.window(colours="black")
        with self.assertRaises(ProtocolError):
            self.window(colours={"frame_style": [999, 0, False, False, False]})


if __name__ == "__main__":
    unittest.main()
