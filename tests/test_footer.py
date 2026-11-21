"""Tests for window footers."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.client import ClientManager
from dasha.hosting import AppServer
from dasha.manager import PresentationManager
from dasha.protocol import ProtocolError
from dasha.remote import MAX_FOOTER, MAX_FOOTER_PARTS
from dasha.window import Window
from tests.hosted_apps import Hello
from tests.support import hosted, pipe
from tests.test_hosting import WELCOME, drain, of_type
from tests.test_waiting_dialogs import state

SUN = "\N{WHITE SUN WITH RAYS}"


def bottom(window: Window, active: bool = True) -> str:
    """The window's bottom edge.

    :param window: The window.
    :param active: Whether it is drawn active.
    """
    canvas = Canvas(window.rect.right, window.rect.bottom)
    window.paint(canvas, active)
    return canvas.text(window.rect.bottom - 1)[window.rect.column :]


class _Footed(Window):
    """A window with a computed footer.

    :param rect: Position and size.
    :param lines: Lines of text.
    """

    def __init__(self, rect: Rect, lines: list[str]) -> None:
        super().__init__("W", rect, lines, resizable=True)
        self.place = "1:1"

    def footer_parts(self) -> list[str]:
        return [self.place]


class FooterTests(unittest.TestCase):
    """The footer on the frame."""

    def test_none_by_default(self) -> None:
        """A window has no footer unless given one."""
        window = Window("W", Rect(0, 0, 4, 20), resizable=True)
        self.assertEqual(window.footer, [])
        self.assertEqual(bottom(window), "╚" + "═" * 17 + "─┘")

    def test_shown_at_the_left(self) -> None:
        """``╚═ text ═══─┘``, in the frame's colours."""
        window = Window("W", Rect(0, 0, 4, 20), resizable=True)
        window.footer = ["12:3"]
        self.assertEqual(bottom(window), "╚═ 12:3 " + "═" * 10 + "─┘")

    def test_parts_parted_by_the_frame_line(self) -> None:
        """Parts are separated by the frame line."""
        window = Window("W", Rect(0, 0, 4, 24), resizable=True)
        window.footer = [SUN, "", "1:1"]
        self.assertTrue(bottom(window).startswith(f"╚═ {SUN} ═ 1:1 ═"))
        inactive = window.inactive_border.horizontal
        self.assertTrue(
            bottom(window, active=False).startswith(
                f"{window.inactive_border.bottom_left}{inactive} {SUN} {inactive} 1:1"
            )
        )
        window.adjusting = True
        moving = window.adjusting_border.horizontal
        self.assertIn(f" {SUN} {moving} 1:1 ", bottom(window))
        canvas = Canvas(24, 4)
        window.paint(canvas, True)
        self.assertEqual(canvas.cell(3, 5)[1], window.adjusting_frame_style)

    def test_scroll_bar_after_it(self) -> None:
        """The scroll bar follows the footer."""
        window = Window("W", Rect(0, 0, 4, 26), ["x" * 40], resizable=True)
        window.footer = [SUN, "1:1"]
        edge = bottom(window)
        self.assertTrue(edge.startswith(f"╚═ {SUN} ═ 1:1 ═◄"), edge)
        self.assertTrue(edge.endswith("►─┘"), edge)
        _, horizontal = window.scroll_bars
        assert horizontal is not None
        self.assertEqual(horizontal.column, 12)
        self.assertEqual(window.scroll_bar_at(3, 12), (horizontal, "back"))

    def test_grows_with_its_text(self) -> None:
        """A longer footer takes more of the edge, the bar the rest."""
        window = _Footed(Rect(0, 0, 4, 30), ["x" * 60])
        short = bottom(window)
        window.place = "1000:2000"
        long = bottom(window)
        self.assertTrue(long.startswith("╚═ 1000:2000 ═◄"), long)
        self.assertEqual(len(short), len(long))
        track = "▒■"
        self.assertLess(
            sum(long.count(c) for c in track), sum(short.count(c) for c in track)
        )

    def test_gone_when_too_narrow(self) -> None:
        """The footer goes when too narrow."""
        window = Window("W", Rect(0, 0, 4, 18), ["x" * 40], resizable=True)
        window.footer = [SUN, "123:45"]  # 10 cells: needs 10 + 9 = 19 with a bar
        self.assertEqual(window.shown_footer, [])
        self.assertTrue(bottom(window).startswith("╚═◄"))
        window.resize(19, 4)
        self.assertEqual(window.shown_footer, [SUN, "123:45"])
        alone = Window("W", Rect(0, 0, 4, 16), resizable=True)
        alone.footer = [SUN, "123:45"]  # needs 10 + 7 = 17 without a bar
        self.assertEqual(alone.shown_footer, [])
        alone.resize(17, 4)
        self.assertEqual(bottom(alone), f"╚═ {SUN} ═ 123:45 ═─┘")


class RemoteFooterTests(unittest.TestCase):
    """An application in a process of its own sends its footer."""

    def test_sent_with_the_window(self) -> None:
        """The client sends ``footer_parts``, and again as they change."""
        desktop, app_end = pipe()
        manager = ClientManager(app_end, WELCOME)
        self.addCleanup(manager.stop_listening)
        window = manager.launch(Hello).windows[0]
        window.footer = ["1:1"]
        manager.flush()
        (sent,) = of_type(drain(desktop), "window")
        self.assertEqual(sent["footer"], ["1:1"])
        window.footer = [SUN, "1:1"]
        manager.flush()
        self.assertEqual(of_type(drain(desktop), "window")[0]["footer"], [SUN, "1:1"])

    def test_shown_on_the_desktop(self) -> None:
        """A hosted footer on the desktop."""
        manager = PresentationManager()
        manager.handle_resize(80, 24)
        server = AppServer(manager)
        manager.server = server
        self.addCleanup(server.stop_all)
        host, _ = hosted(server, "Hello")
        parts = ["7:\n9" + "x" * 100] * (MAX_FOOTER_PARTS + 3)
        host.handle({**state(id=1), "footer": parts})
        window = host.windows[1]
        self.assertEqual(
            window.footer, [("7: 9" + "x" * 100)[:MAX_FOOTER]] * MAX_FOOTER_PARTS
        )
        with self.assertRaises(ProtocolError):  # which ends it, as any does
            host.handle({**state(id=1), "footer": "1:1"})


if __name__ == "__main__":
    unittest.main()
