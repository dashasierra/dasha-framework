"""Tests for the presentation manager: Z-order, menus, dragging, the main loop."""

import unittest
from io import StringIO
from typing import cast
from unittest.mock import patch

from dasha.canvas import Canvas, Rect
from dasha.desktop import Desktop
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuItem
from dasha.terminal import Terminal
from dasha.window import DOUBLE, SINGLE, Window

BURGER = "\N{IDENTICAL TO}"


def make_windows() -> list[Window]:
    """Three overlapping windows below the menu bar, back to front: A, B, C."""
    return [
        Window("A", Rect(1, 0, 4, 10)),
        Window("B", Rect(2, 2, 4, 10)),
        Window("C", Rect(3, 4, 4, 10)),
    ]


def titles(manager: PresentationManager) -> str:
    """The window titles in Z-order, back to front."""
    return "".join(window.title for window in manager.windows)


def press(row: int, column: int) -> MouseEvent:
    """A left-button press."""
    return MouseEvent("press", "left", row, column)


def drag(row: int, column: int) -> MouseEvent:
    """Moving with the left button held."""
    return MouseEvent("drag", "left", row, column)


def release(row: int, column: int) -> MouseEvent:
    """A left-button release."""
    return MouseEvent("release", "left", row, column)


class ZOrderTests(unittest.TestCase):
    """Stacking and activating windows."""

    def setUp(self) -> None:
        self.windows = make_windows()
        self.manager = PresentationManager(windows=self.windows)

    def test_last_added_is_active(self) -> None:
        """New windows go on top and become active."""
        self.assertEqual(titles(self.manager), "ABC")
        self.assertIs(self.manager.active_window, self.windows[2])

    def test_bring_to_front_and_send_to_back(self) -> None:
        """Windows can be raised and lowered."""
        self.manager.bring_to_front(self.windows[0])
        self.assertEqual(titles(self.manager), "BCA")
        self.manager.send_to_back(self.windows[0])
        self.assertEqual(titles(self.manager), "ABC")

    def test_next_and_previous_cycle(self) -> None:
        """Next sends the front window to the back; previous undoes it."""
        self.manager.activate_next()
        self.assertEqual(titles(self.manager), "CAB")
        self.manager.activate_previous()
        self.assertEqual(titles(self.manager), "ABC")

    def test_keys_switch_windows_and_quit(self) -> None:
        """The default key bindings drive the Z-order and quitting."""
        self.manager.handle_event("f6")
        self.assertIs(self.manager.active_window, self.windows[1])
        self.manager.handle_event("shift+f6")
        self.assertIs(self.manager.active_window, self.windows[2])
        self.manager.handle_event("tab")  # Tab no longer changes window
        self.assertIs(self.manager.active_window, self.windows[2])
        self.manager._running = True  # pylint: disable=protected-access
        self.manager.handle_event("escape")  # Escape no longer exits
        self.assertTrue(self.manager.is_running)
        self.manager.handle_event("ctrl+q")
        self.assertFalse(self.manager.is_running)

    def test_mouse_events(self) -> None:
        """Left and right presses raise windows (a right one, for its
        context menu); the wheel and releases do not."""
        a, b, _ = self.windows
        self.manager.handle_event(MouseEvent("scroll", "up", 1, 0))
        self.manager.handle_event(MouseEvent("release", "left", 1, 0))
        self.manager.handle_event(MouseEvent("press", "middle", 1, 0))
        self.assertEqual(titles(self.manager), "ABC")
        self.manager.handle_event(MouseEvent("press", "right", 1, 0))
        self.assertEqual(titles(self.manager), "BCA")
        self.manager.handle_event(MouseEvent("press", "right", 0, 0))  # menu bar
        self.assertEqual(titles(self.manager), "BCA")
        self.manager.handle_event(press(2, 11))
        self.assertIs(self.manager.active_window, b)
        self.manager.handle_event(press(1, 0))
        self.assertIs(self.manager.active_window, a)
        self.manager.handle_event(press(7, 19))
        self.assertIs(self.manager.active_window, a)

    def test_window_at_finds_front_most(self) -> None:
        """Hit-testing picks the top window at a point."""
        self.assertIs(self.manager.window_at(3, 5), self.windows[2])
        self.assertIs(self.manager.window_at(1, 0), self.windows[0])
        self.assertIsNone(self.manager.window_at(10, 30))

    def test_adding_twice_is_rejected(self) -> None:
        """A window can only be on the desktop once."""
        with self.assertRaises(ValueError):
            self.manager.add(self.windows[0])

    def test_compose_draws_front_window_on_top(self) -> None:
        """The front window gets the double frame and covers the others."""
        canvas = Canvas(20, 8)
        self.manager.compose(canvas)
        self.assertEqual(canvas.cell(3, 4)[0], DOUBLE.top_left)
        self.assertEqual(canvas.cell(1, 0)[0], SINGLE.top_left)
        self.assertEqual(canvas.cell(6, 19)[0], Desktop.pattern)
        self.assertEqual(canvas.cell(7, 19), (" ", self.manager.status_bar.style))


class MenuTests(unittest.TestCase):
    """The menu bar: system menu plus the active window's menus."""

    def setUp(self) -> None:
        self.chosen: list[str] = []
        self.edit = Menu(
            "&Edit", [MenuItem("&Copy", lambda: self.chosen.append("copy"))]
        )
        self.view = Menu(
            "&View", [MenuItem("&Zoom", lambda: self.chosen.append("zoom"))]
        )
        self.a = Window("A", Rect(1, 0, 4, 10), menus=[self.edit])
        self.b = Window("B", Rect(2, 30, 4, 10), menus=[self.view])
        self.manager = PresentationManager(windows=[self.a, self.b])

    def menu_titles(self) -> list[str]:
        """Titles currently on the menu bar."""
        return [menu.title for menu in self.manager.bar_menus()]

    def test_bar_follows_active_window(self) -> None:
        """The system menu always comes first, then the active window's menus."""
        self.assertEqual(self.menu_titles(), [BURGER, "&View"])
        self.manager.bring_to_front(self.a)
        self.assertEqual(self.menu_titles(), [BURGER, "&Edit"])
        self.manager.remove(self.a)
        self.manager.remove(self.b)
        self.assertEqual(self.menu_titles(), [BURGER])

    def test_bar_is_painted_on_top_row(self) -> None:
        """The burger and window menu titles are drawn on row 0."""
        canvas = Canvas(30, 6)
        self.manager.compose(canvas)
        self.assertEqual(canvas.text(0), "  " + BURGER + "  View " + " " * 20)

    def test_exit_from_system_menu_by_keyboard(self) -> None:
        """F10 opens the system menu; Shutdown's letter, S, quits."""
        self.manager._running = True  # pylint: disable=protected-access
        self.manager.handle_event("f10")
        self.assertIs(self.manager.menu_bar.open_menu, self.manager.system_menu)
        self.manager.handle_event("s")
        self.assertFalse(self.manager.is_running)
        self.assertFalse(self.manager.menu_bar.is_open)

    def test_exit_from_system_menu_by_mouse(self) -> None:
        """Click the burger, then click Exit (below About, Settings...,
        Themes, Animations, Command prompt and a separator)."""
        self.manager._running = True  # pylint: disable=protected-access
        self.manager.handle_event(press(0, 1))
        self.assertTrue(self.manager.menu_bar.is_open)
        self.manager.handle_event(press(8, 3))
        self.assertFalse(self.manager.is_running)

    def test_escape_closes_menu_before_quitting(self) -> None:
        """With a menu open, Escape closes it; it does not quit Dasha Framework."""
        self.manager._running = True  # pylint: disable=protected-access
        self.manager.handle_event("alt+v")
        self.assertIs(self.manager.menu_bar.open_menu, self.view)
        self.manager.handle_event("escape")
        self.assertFalse(self.manager.menu_bar.is_open)
        self.assertTrue(self.manager.is_running)
        self.manager.handle_event("escape")
        self.assertTrue(self.manager.is_running)
        self.manager.handle_event("ctrl+q")
        self.assertFalse(self.manager.is_running)

    def test_window_menu_item_runs_action(self) -> None:
        """Choosing an item of the active window's menu runs its action."""
        self.manager.handle_event("alt+v")
        self.manager.handle_event("z")
        self.assertEqual(self.chosen, ["zoom"])

    def test_open_menu_takes_input(self) -> None:
        """While a menu is open, Tab and clicks do not reach the windows."""
        self.manager.handle_event("f10")
        self.manager.handle_event("tab")
        self.assertIs(self.manager.active_window, self.b)
        self.manager.handle_event(press(1, 0))  # the drop-down's own frame
        self.assertTrue(self.manager.menu_bar.is_open)
        self.manager.handle_event(press(6, 45))  # outside: closes the menu
        self.assertFalse(self.manager.menu_bar.is_open)
        self.assertIs(self.manager.active_window, self.b)

    def test_switching_windows_closes_open_menu(self) -> None:
        """If the menus change while one is open, it closes."""
        self.manager.handle_event("alt+v")
        self.manager.bring_to_front(self.a)
        self.manager.handle_event("down")  # menus re-synced first
        self.assertFalse(self.manager.menu_bar.is_open)

    def test_system_menu_can_be_extended(self) -> None:
        """Applications can add items to the system menu."""
        self.manager.system_menu.items.insert(
            0, MenuItem("&About", lambda: self.chosen.append("about"))
        )
        self.manager.handle_event("f10")
        self.manager.handle_event("a")
        self.assertEqual(self.chosen, ["about"])


class DragTests(unittest.TestCase):
    """Moving windows by dragging the title bar."""

    def setUp(self) -> None:
        self.windows = make_windows()
        self.manager = PresentationManager(windows=self.windows)

    def drag_path(self, *events: MouseEvent) -> None:
        """Send a series of mouse events."""
        for event in events:
            self.manager.handle_event(event)

    def test_drag_title_bar_moves_window(self) -> None:
        """The window follows the pointer, keeping the grab point."""
        c = self.windows[2]  # at row 3, column 4
        self.drag_path(press(3, 7), drag(4, 8), drag(10, 20))
        self.assertIs(self.manager.dragging, c)
        self.assertEqual((c.rect.row, c.rect.column), (10, 17))
        self.drag_path(release(10, 20), drag(5, 5))
        self.assertIsNone(self.manager.dragging)
        self.assertEqual((c.rect.row, c.rect.column), (10, 17))

    def test_dragging_back_window_raises_it_first(self) -> None:
        """Grabbing a back window's title bar brings it forward and moves it."""
        a = self.windows[0]  # title bar row 1, columns 0-9, uncovered there
        self.drag_path(press(1, 1), drag(5, 31), release(5, 31))
        self.assertIs(self.manager.active_window, a)
        self.assertEqual((a.rect.row, a.rect.column), (5, 30))

    def test_cannot_drag_under_menu_bar(self) -> None:
        """The title bar stops just below the menu bar."""
        c = self.windows[2]
        self.drag_path(press(3, 7), drag(0, 7), release(0, 7))
        self.assertEqual((c.rect.row, c.rect.column), (1, 4))

    def test_pressing_body_does_not_drag(self) -> None:
        """Only the top row starts a drag."""
        c = self.windows[2]
        self.drag_path(press(4, 7), drag(10, 20))
        self.assertIsNone(self.manager.dragging)
        self.assertEqual(c.rect, Rect(3, 4, 4, 10))

    def test_other_buttons_do_not_drag(self) -> None:
        """Right-button drags are ignored."""
        self.manager.handle_event(MouseEvent("press", "right", 3, 7))
        self.assertIsNone(self.manager.dragging)

    def test_window_can_be_dragged_partly_off_screen(self) -> None:
        """A window dragged past the edge stays there."""
        c = self.windows[2]
        self.drag_path(press(3, 13), drag(5, 0), release(5, 0))
        self.assertEqual((c.rect.row, c.rect.column), (5, -9))
        self.manager.handle_resize(80, 24)  # still visible: left alone
        self.assertEqual((c.rect.row, c.rect.column), (5, -9))

    def test_removing_dragged_window_ends_drag(self) -> None:
        """A window taken away mid-drag is no longer dragged."""
        self.drag_path(press(3, 7))
        self.manager.remove(self.windows[2])
        self.assertIsNone(self.manager.dragging)


class ResizeTests(unittest.TestCase):
    """Keeping windows reachable when the terminal shrinks."""

    def resized(self, rect: Rect, columns: int, lines: int) -> Rect:
        """Where a window at ``rect`` ends up after a resize."""
        window = Window("w", rect)
        PresentationManager(windows=[window]).handle_resize(columns, lines)
        return window.rect

    def test_visible_windows_are_left_alone(self) -> None:
        """Partly visible windows do not move."""
        self.assertEqual(
            self.resized(Rect(20, 70, 10, 30), 80, 24), Rect(20, 70, 10, 30)
        )

    def test_window_off_the_right_is_pulled_back(self) -> None:
        """A window past the right edge shows its left end."""
        self.assertEqual(self.resized(Rect(5, 70, 10, 30), 40, 24), Rect(5, 36, 10, 30))

    def test_window_below_the_bottom_is_pulled_up(self) -> None:
        """A window below the screen ends up just above the status bar."""
        self.assertEqual(
            self.resized(Rect(30, 10, 10, 30), 80, 24), Rect(22, 10, 10, 30)
        )

    def test_window_off_bottom_right_corner(self) -> None:
        """Off both edges: pulled back in both directions."""
        self.assertEqual(
            self.resized(Rect(30, 90, 10, 30), 80, 24), Rect(22, 76, 10, 30)
        )

    def test_window_off_the_left_is_pulled_back(self) -> None:
        """A window past the left edge shows its right end."""
        self.assertEqual(
            self.resized(Rect(5, -40, 10, 30), 80, 24), Rect(5, -26, 10, 30)
        )

    def test_narrow_window_is_fully_shown(self) -> None:
        """A window narrower than the margin is pulled fully on screen."""
        self.assertEqual(self.resized(Rect(5, 100, 4, 3), 80, 24), Rect(5, 77, 4, 3))

    def test_title_bar_under_menu_bar_is_moved_down(self) -> None:
        """A window whose title bar is hidden by the menu bar moves below it."""
        self.assertEqual(self.resized(Rect(0, 5, 4, 10), 80, 24), Rect(1, 5, 4, 10))


class FakeTerminal:
    """Stands in for Terminal: scripted sizes and input, captured output."""

    def __init__(
        self, inputs: list[str], sizes: list[tuple[int, int]] | None = None
    ) -> None:
        self.inputs = inputs
        self.output = StringIO()
        self.sizes = sizes if sizes is not None else [(20, 8)]

    def size(self) -> tuple[int, int]:
        """The current size; each read moves on to the next scripted size."""
        return self.sizes[0]

    def write(self, text: str) -> None:
        """Capture output."""
        self.output.write(text)

    def flush(self) -> None:
        """Nothing to flush."""

    def read(self, timeout: float | None = None) -> str:
        """Return the next scripted input; ``""`` in the script is a timeout."""
        del timeout
        if len(self.sizes) > 1:
            self.sizes.pop(0)
        return self.inputs.pop(0)


class RunTests(unittest.TestCase):
    """The main loop."""

    def test_run_redraws_until_quit(self) -> None:
        """Run draws, handles keys, and ignores keys after the exit key."""
        manager = PresentationManager(windows=make_windows())
        terminal = FakeTerminal(["\x1b[17~", "\x11", "\r", "never read"])  # F6
        with patch.object(manager, "compose", wraps=manager.compose) as compose:
            manager.run(cast(Terminal, terminal))
        self.assertEqual(compose.call_count, 3)  # the last frame shows the exit dialog
        self.assertEqual(titles(manager), "CAB")
        self.assertEqual(terminal.inputs, ["never read"])
        self.assertFalse(manager.is_running)

    def test_escape_sequence_split_across_reads(self) -> None:
        """A sequence cut in two (slow SSH) is joined, not taken as Escape."""
        manager = PresentationManager(windows=make_windows())
        # Shift+F6 arrives as ESC, then [17;2~; then a real Escape quits.
        terminal = FakeTerminal(["\x1b", "[17;2~", "\x11", "\r"])
        manager.run(cast(Terminal, terminal))
        self.assertEqual(titles(manager), "BCA")

    def test_click_brings_window_to_front(self) -> None:
        """Clicking a window behind others brings it to the front."""
        manager = PresentationManager(windows=make_windows())
        # Press and release at 1-based column 1, row 2: inside window A only.
        terminal = FakeTerminal(["\x1b[<0;1;2M\x1b[<0;1;2m", "\x11", "\r"])
        manager.run(cast(Terminal, terminal))
        self.assertEqual(titles(manager), "BCA")

    def test_exit_through_menu_with_mouse(self) -> None:
        """Clicking the burger and then Exit ends the main loop."""
        manager = PresentationManager(windows=make_windows())
        # The burger, then Exit: row 9 (counting from 1), under About,
        # Settings..., Themes, Animations and Command prompt.
        terminal = FakeTerminal(["\x1b[<0;2;1M", "\x1b[<0;4;9M", "\r", "never read"])
        manager.run(cast(Terminal, terminal))
        self.assertFalse(manager.is_running)
        self.assertEqual(terminal.inputs, ["never read"])

    def test_resize_rescues_window_and_redraws(self) -> None:
        """A resize with no other input redraws at the new size."""
        window = Window("w", Rect(2, 60, 4, 10))
        manager = PresentationManager(windows=[window])
        # The first read is a resize wake-up ("" with no input).
        terminal = FakeTerminal(["", "\x11", "\r"], sizes=[(80, 24), (40, 10)])
        with patch.object(manager, "compose", wraps=manager.compose) as compose:
            manager.run(cast(Terminal, terminal))
        self.assertEqual(compose.call_count, 3)  # the last frame shows the exit dialog
        self.assertEqual(window.rect, Rect(2, 36, 4, 10))

    def test_screen_cleared_by_the_terminal_is_drawn_again(self) -> None:
        """When the terminal clears the screen by itself (entering the
        alternate screen afresh after a resize), every cell is drawn again,
        even though the size has not changed."""

        class ClearingTerminal(FakeTerminal):
            """Clears the screen on its first read; keeps each frame."""

            def __init__(self) -> None:
                super().__init__(["", "\x11", "\r"], sizes=[(80, 24)])
                self.frames: list[str] = []
                self.cleared = False

            def flush(self) -> None:
                """Keep what was written since the last flush."""
                self.frames.append(self.output.getvalue())
                self.output = StringIO()

            def read(self, timeout: float | None = None) -> str:
                """Clear the screen on the first read, a resize wake-up."""
                self.cleared = len(self.frames) == 1
                return super().read(timeout)

            def take_cleared(self) -> bool:
                """Whether the screen was cleared since last asked."""
                cleared, self.cleared = self.cleared, False
                return cleared

        terminal = ClearingTerminal()
        PresentationManager(windows=make_windows()).run(cast(Terminal, terminal))
        self.assertGreater(len(terminal.frames), 2)
        self.assertEqual(terminal.frames[1], terminal.frames[0])  # all of it
        self.assertLess(len(terminal.frames[2]), len(terminal.frames[0]))

    def test_drag_through_run(self) -> None:
        """Mouse reports drive a drag through the main loop."""
        window = Window("w", Rect(1, 0, 4, 10))
        manager = PresentationManager(windows=[window])
        terminal = FakeTerminal(
            ["\x1b[<0;3;2M", "\x1b[<32;8;5M\x1b[<0;8;5m", "\x11", "\r"]
        )
        manager.run(cast(Terminal, terminal))
        self.assertEqual(window.rect, Rect(4, 5, 4, 10))

    def test_second_frame_only_sends_changes(self) -> None:
        """After the first frame, only changed cells are redrawn."""
        manager = PresentationManager(windows=make_windows())
        terminal = FakeTerminal(["x", "\x11", "\r"])
        manager.run(cast(Terminal, terminal))
        # "x" changes nothing, so the second frame sends no cells at all and
        # each visible desktop cell is drawn exactly once.
        canvas = Canvas(20, 8)
        manager.compose(canvas)
        shade = Desktop.pattern
        visible = sum(canvas.text(row).count(shade) for row in range(8))
        self.assertEqual(terminal.output.getvalue().count(shade), visible)


if __name__ == "__main__":
    unittest.main()
