"""Tests for one-line text boxes, and the terminal cursor they show."""

import re
import time
import unittest
from typing import cast

from dasha.canvas import Canvas, Rect
from dasha.dialog import Dialog
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.scrollbar import LEFT, RIGHT
from dasha.shortcuts import Shortcuts
from dasha.terminal import Terminal, ansi
from dasha.widgets import Button, SpinBox, TextBox
from dasha.window import Window
from tests.test_manager import FakeTerminal


def type_into(box: TextBox, keys: str | list[str]) -> None:
    """Offer each key to the box.

    :param box: The text box.
    :param keys: The keys.
    """
    shortcuts = Shortcuts()
    for key in keys:
        box.handle_key(key, shortcuts)


def paint(box: TextBox, focused: bool = True) -> Canvas:
    """Paint a box on a canvas of its size.

    :param box: The text box.
    :param focused: Whether it has the focus.
    """
    canvas = Canvas(box.rect.right, box.rect.bottom)
    box.paint(canvas, canvas.bounds, focused)
    return canvas


class EditingTests(unittest.TestCase):
    """Typing, moving the cursor and deleting."""

    def test_typing_inserts_at_the_cursor(self) -> None:
        """Characters, spaces included, go in where the cursor is."""
        box = TextBox(0, 0, 20)
        type_into(box, "helo world")
        type_into(box, ["home", "right", "right", "right", "l"])
        self.assertEqual(box.text, "hello world")
        self.assertEqual(box.cursor, 4)
        self.assertEqual(box.value, "hello world")

    def test_moving_stops_at_the_ends(self) -> None:
        """Moving stops at the ends."""
        box = TextBox(0, 0, 20, text="abc")
        self.assertEqual(box.cursor, 3)
        type_into(box, ["right", "right"])
        self.assertEqual(box.cursor, 3)
        type_into(box, ["left"] * 5)
        self.assertEqual(box.cursor, 0)
        type_into(box, ["end"])
        self.assertEqual(box.cursor, 3)

    def test_backspace_delete_and_clear(self) -> None:
        """Backspace deletes before the cursor, Delete at it, Ctrl+Y all."""
        box = TextBox(0, 0, 20, text="abcdef")
        type_into(box, ["backspace", "home", "delete", "right", "backspace"])
        self.assertEqual(box.text, "cde")
        self.assertEqual(box.cursor, 0)
        type_into(box, ["backspace"])  # nothing before the cursor
        self.assertEqual(box.text, "cde")
        type_into(box, ["ctrl+y"])
        self.assertEqual((box.text, box.cursor), ("", 0))

    def test_keys_it_does_not_use_are_passed_on(self) -> None:
        """Unused keys are passed on."""
        box = TextBox(0, 0, 20)
        shortcuts = Shortcuts()
        for key in ("tab", "shift+tab", "escape", "enter", "f5", "up"):
            self.assertFalse(box.handle_key(key, shortcuts), key)
        self.assertTrue(box.handle_key(" ", shortcuts))
        self.assertTrue(box.handle_key("left", shortcuts))  # even at the start

    def test_remapped_keys(self) -> None:
        """The editing keys come from the shortcuts, so they can be changed."""
        box = TextBox(0, 0, 20, text="abc")
        shortcuts = Shortcuts({"text_home": ["ctrl+a"], "text_clear": []})
        box.handle_key("ctrl+a", shortcuts)
        self.assertEqual(box.cursor, 0)
        self.assertFalse(box.handle_key("ctrl+y", shortcuts))
        self.assertEqual(box.text, "abc")

    def test_on_change(self) -> None:
        """on_change hears about changes, but not refused keys or moves."""
        changes: list[str] = []
        box = TextBox(
            0, 0, 20, max_length=2, on_change=lambda b: changes.append(b.text)
        )
        type_into(box, ["a", "b", "c", "left", "backspace"])
        self.assertEqual(changes, ["a", "ab", "b"])


class LimitTests(unittest.TestCase):
    """max_length and pattern."""

    def test_max_length(self) -> None:
        """Typing stops at the limit, wherever the cursor is."""
        box = TextBox(0, 0, 10, max_length=3)
        type_into(box, ["a", "b", "c", "d", "home", "x"])
        self.assertEqual(box.text, "abc")

    def test_pattern_refuses_what_does_not_match(self) -> None:
        """Only edits that leave the whole text matching are made."""
        box = TextBox(0, 0, 10, pattern=r"-?[0-9]*")
        type_into(box, "1a2-3")
        self.assertEqual(box.text, "123")
        type_into(box, ["home", "-"])
        self.assertEqual(box.text, "-123")

    def test_compiled_pattern(self) -> None:
        """A compiled pattern, with its flags, works too."""
        box = TextBox(0, 0, 10, pattern=re.compile("[a-c]*", re.IGNORECASE))
        type_into(box, "AbxC")
        self.assertEqual(box.text, "AbC")

    def test_empty_is_always_allowed(self) -> None:
        """A pattern that needs a character still lets the box be emptied."""
        box = TextBox(0, 0, 10, text="7", pattern=r"[0-9]+")
        type_into(box, ["backspace"])
        self.assertEqual(box.text, "")
        self.assertTrue(box.accepts(""))

    def test_setting_text_checks_it(self) -> None:
        """Text the box would not accept from the keyboard is refused."""
        box = TextBox(0, 0, 10, max_length=4, pattern=r"[a-z]*")
        box.text = "abcd"
        self.assertEqual(box.cursor, 4)
        for bad in ("abcde", "ab1", "a\nb", "a\tb"):
            with self.assertRaises(ValueError):
                box.text = bad
        self.assertEqual(box.text, "abcd")
        with self.assertRaises(ValueError):
            TextBox(0, 0, 10, text="toolong", max_length=3)

    def test_bad_sizes(self) -> None:
        """Too narrow for the arrows and a character, or a negative limit."""
        with self.assertRaises(ValueError):
            TextBox(0, 0, 2)
        with self.assertRaises(ValueError):
            TextBox(0, 0, 5, max_length=-1)


class DrawingTests(unittest.TestCase):
    """What shows, the arrows, and the cursor."""

    def test_short_text_has_no_arrows(self) -> None:
        """Text that fits shows between two blank arrow columns."""
        box = TextBox(0, 0, 8, text="abc")
        canvas = paint(box)
        self.assertEqual(canvas.text(0), " abc    ")
        self.assertEqual(canvas.cell(0, 1)[1], box.focused_style)
        self.assertEqual(canvas.cursor, (0, 4))
        self.assertEqual(paint(box, focused=False).cell(0, 1)[1], box.style)

    def test_unfocused_box_shows_no_cursor(self) -> None:
        """Only the focused box shows the cursor."""
        self.assertIsNone(paint(TextBox(0, 0, 8, text="abc"), focused=False).cursor)

    def test_arrows_show_only_where_there_is_more(self) -> None:
        """Arrows show only where there is more."""
        box = TextBox(0, 0, 6, text="abcdefghij")  # 4 characters show
        canvas = paint(box)  # the cursor is at the end: the text ends in view
        self.assertEqual(canvas.text(0), LEFT + "ghij ")
        self.assertEqual(canvas.cell(0, 0)[1], box.arrow_style)
        self.assertEqual(canvas.cursor, (0, 5))  # in the blank arrow column
        type_into(box, ["home"])
        self.assertEqual(paint(box).text(0), " abcd" + RIGHT)
        type_into(box, ["right"] * 6)  # the cursor at g scrolls the text
        self.assertEqual(paint(box).text(0), LEFT + "defg" + RIGHT)
        self.assertEqual(paint(box).cursor, (0, 4))

    def test_text_exactly_filling_the_box(self) -> None:
        """Text exactly filling the box."""
        box = TextBox(0, 0, 6, text="abcd", max_length=4)
        canvas = paint(box)
        self.assertEqual(canvas.text(0), " abcd ")
        self.assertEqual(canvas.cursor, (0, 5))
        type_into(box, ["home"])
        self.assertEqual(paint(box).text(0), " abcd ")
        self.assertEqual(paint(box).cursor, (0, 1))

    def test_drawn_inside_a_scrolled_window(self) -> None:
        """Drawn inside a scrolled window."""
        window = Window("W", Rect(0, 0, 4, 12))
        box = window.add(TextBox(0, 6, 20, text="x"))
        window.scroll_to(0, 9)  # the box starts left of the frame
        box.cursor = 0
        canvas = Canvas(12, 4)
        window.paint(canvas, active=True)
        self.assertIsNone(canvas.cursor)  # the cursor is past the frame
        box.cursor = 1
        window.scroll_to(0, 0)
        canvas = Canvas(12, 4)
        window.paint(canvas, active=True)
        self.assertEqual(canvas.cursor, (1, 1 + 6 + 2))


class MouseTests(unittest.TestCase):
    """Clicking in a text box."""

    def click(self, box: TextBox, column: int, action: str = "press") -> bool:
        """A left press at an interior column.

        :param box: The text box.
        :param column: Interior column.
        :param action: Mouse action.
        """
        return box.handle_mouse(MouseEvent(action, "left", 0, column), 0, column)

    def test_click_places_the_cursor(self) -> None:
        """A click places the cursor."""
        box = TextBox(0, 2, 10, text="abc")
        self.assertTrue(self.click(box, 4))  # on b
        self.assertEqual(box.cursor, 1)
        self.click(box, 9)
        self.assertEqual(box.cursor, 3)
        self.assertTrue(self.click(box, 9, "release"))
        self.assertFalse(box.handle_mouse(MouseEvent("press", "right", 0, 3), 0, 3))

    def test_clicking_the_arrows_scrolls(self) -> None:
        """A click on ◄ or ► moves one past what shows, scrolling."""
        box = TextBox(0, 0, 6, text="abcdefghij")
        box.cursor = 0
        self.click(box, 5)  # ►
        self.assertEqual(box.cursor, 4)
        self.assertEqual(box.first_visible, 1)
        self.click(box, 0)  # ◄
        self.assertEqual(box.cursor, 0)
        self.assertFalse(box.has_more_left)


class WindowAndDialogTests(unittest.TestCase):
    """Text boxes among other widgets."""

    def test_tab_moves_on_and_letters_are_typed(self) -> None:
        """Tab moves on and letters are typed."""
        dialog = Dialog("Name", 30, 8)
        box = dialog.add(TextBox(1, 2, 20, name="name"))
        ok = dialog.add(Button("&OK", 3, 2, result="ok", default=True, name="ok"))
        shortcuts = Shortcuts()
        for key in "Bob O":
            dialog.handle_key(key, shortcuts)
        self.assertIsNone(dialog.result)
        self.assertEqual(dialog.values["name"], "Bob O")
        dialog.handle_key("tab", shortcuts)
        self.assertIs(dialog.focused, ok)
        dialog.handle_key("shift+tab", shortcuts)
        self.assertIs(dialog.focused, box)
        dialog.handle_key("enter", shortcuts)
        self.assertEqual(dialog.result, "ok")

    def test_clicking_focuses(self) -> None:
        """Clicking focuses."""
        window = Window("W", Rect(0, 0, 6, 30))
        window.add(Button("&Go", 3, 1))
        box = window.add(TextBox(1, 1, 10, text="hello"))
        window.handle_mouse(MouseEvent("press", "left", 2, 4))
        self.assertIs(window.focused, box)
        self.assertEqual(box.cursor, 1)


class CursorTests(unittest.TestCase):
    """Showing the terminal's cursor for the focused text box."""

    def test_render_shows_moves_and_hides_the_cursor(self) -> None:
        """Render shows, moves and hides the cursor."""
        first = Canvas(10, 3)
        first.place_cursor(1, 4)
        output = first.render()
        self.assertTrue(output.endswith(ansi.move_to(1, 4) + ansi.SHOW_CURSOR))
        same = Canvas(10, 3)
        same.place_cursor(1, 4)
        self.assertEqual(same.render(first), "")  # nothing changed at all
        drawn = Canvas(10, 3)
        drawn.write(0, 0, "x")
        drawn.place_cursor(1, 4)
        self.assertTrue(drawn.render(same).endswith(ansi.move_to(1, 4)))
        hidden = Canvas(10, 3)
        hidden.write(0, 0, "x")
        self.assertEqual(hidden.render(drawn), ansi.HIDE_CURSOR)
        self.assertEqual(Canvas(10, 3).render(Canvas(10, 3)), "")

    def test_place_cursor_respects_the_clip(self) -> None:
        """Outside the canvas or the clip, the cursor stays hidden."""
        canvas = Canvas(10, 3)
        canvas.place_cursor(5, 5)
        with canvas.clipped(Rect(0, 0, 1, 3)):
            canvas.place_cursor(0, 4)
        self.assertIsNone(canvas.cursor)

    def test_open_menu_hides_the_cursor(self) -> None:
        """An open menu hides the cursor."""
        window = Window("W", Rect(2, 0, 5, 30))
        window.add(TextBox(0, 1, 10))
        manager = PresentationManager(windows=[window])
        manager.handle_resize(40, 12)
        canvas = Canvas(40, 12)
        manager.compose(canvas)
        self.assertEqual(canvas.cursor, (3, 3))  # past the arrow column
        manager.handle_event("f10")
        canvas = Canvas(40, 12)
        manager.compose(canvas)
        self.assertIsNone(canvas.cursor)

    def test_cursor_hides_under_the_bars(self) -> None:
        """A box under the status bar shows no cursor there."""
        window = Window(
            "W", Rect(8, 0, 5, 30)
        )  # the box lands on row 11, the status bar
        window.add(TextBox(2, 1, 10))
        manager = PresentationManager(windows=[window])
        manager.handle_resize(40, 12)
        canvas = Canvas(40, 12)
        manager.compose(canvas)
        self.assertIsNone(canvas.cursor)


def mouse(
    box: TextBox, action: str, column: int, shift: bool = False, clicks: int = 1
) -> bool:
    """A left-button event at an interior column.

    :param box: The text box.
    :param action: Mouse action.
    :param column: Interior column.
    :param shift: Whether Shift is held.
    :param clicks: Click count.
    """
    event = MouseEvent(action, "left", 0, column, shift=shift, clicks=clicks)
    return box.handle_mouse(event, 0, column)


class KeyboardSelectionTests(unittest.TestCase):
    """Selecting with the keyboard."""

    def test_shift_keys_select(self) -> None:
        """Shift+Left/Right/Home/End select from where the cursor was."""
        box = TextBox(0, 0, 20, text="hello world")
        type_into(box, ["shift+left", "shift+left"])
        self.assertEqual(box.selection, (9, 11))
        self.assertEqual(box.selected_text, "ld")
        type_into(box, ["shift+home"])
        self.assertEqual(box.selected_text, "hello world")
        type_into(box, ["shift+right"] * 6)
        self.assertEqual(box.selected_text, "world")
        type_into(box, ["shift+end"])
        self.assertIsNone(box.selection)  # back where it started

    def test_ctrl_a_selects_all(self) -> None:
        """Ctrl+A selects everything, and can be remapped."""
        box = TextBox(0, 0, 20, text="hello")
        box.cursor = 2
        type_into(box, ["ctrl+a"])
        self.assertEqual((box.selection, box.cursor), ((0, 5), 5))
        type_into(box, "X")
        self.assertEqual(box.text, "X")
        shortcuts = Shortcuts({"text_select_all": ["alt+a"]})
        self.assertTrue(box.handle_key("alt+a", shortcuts))
        self.assertEqual(box.selected_text, "X")
        box.cursor = 0
        self.assertFalse(box.handle_key("ctrl+a", shortcuts))
        self.assertIsNone(box.selection)

    def test_moving_clears_the_selection(self) -> None:
        """Moving clears the selection."""
        box = TextBox(0, 0, 20, text="abcdef")
        box.select(1, 4)
        type_into(box, ["left"])
        self.assertEqual((box.cursor, box.selection), (1, None))
        box.select(4, 1)
        type_into(box, ["right"])
        self.assertEqual((box.cursor, box.selection), (4, None))
        box.select(1, 4)
        type_into(box, ["end"])
        self.assertEqual((box.cursor, box.selection), (6, None))

    def test_typing_replaces_the_selection(self) -> None:
        """A character replaces what is selected."""
        box = TextBox(0, 0, 20, text="hello world")
        box.select(6, 11)
        type_into(box, "X")
        self.assertEqual(box.text, "hello X")
        self.assertEqual((box.cursor, box.selection), (7, None))

    def test_typing_the_same_over_the_selection(self) -> None:
        """Typing the same over the selection."""
        box = TextBox(0, 0, 20, text="1")
        box.select_all()
        type_into(box, "15")
        self.assertEqual((box.text, box.cursor, box.selection), ("15", 2, None))

    def test_backspace_and_delete_delete_the_selection(self) -> None:
        """Backspace and Delete both take just the selection."""
        box = TextBox(0, 0, 20, text="abcdef")
        box.select(1, 3)
        type_into(box, ["backspace"])
        self.assertEqual((box.text, box.cursor), ("adef", 1))
        box.select(3, 1)
        type_into(box, ["delete"])
        self.assertEqual((box.text, box.cursor), ("af", 1))

    def test_refused_replacement_keeps_the_selection(self) -> None:
        """A key the pattern refuses changes nothing, selection included."""
        box = TextBox(0, 0, 20, text="123", pattern=r"[0-9]*")
        box.select_all()
        type_into(box, "x")
        self.assertEqual((box.text, box.selection), ("123", (0, 3)))
        type_into(box, "9")  # a digit does replace it
        self.assertEqual(box.text, "9")

    def test_replacing_at_max_length(self) -> None:
        """A full box still takes a key that replaces a selection."""
        box = TextBox(0, 0, 10, text="abc", max_length=3)
        box.select(0, 1)
        type_into(box, "z")
        self.assertEqual(box.text, "zbc")

    def test_setting_text_or_cursor_deselects(self) -> None:
        """Code that sets the text or the cursor clears the selection."""
        box = TextBox(0, 0, 20, text="abcdef")
        box.select_all()
        box.cursor = 2
        self.assertIsNone(box.selection)
        box.select_all()
        box.text = "new"
        self.assertIsNone(box.selection)

    def test_selection_is_drawn_when_focused(self) -> None:
        """Selected characters, the visible part of them, show highlighted."""
        box = TextBox(0, 0, 6, text="abcdefghij")
        box.select(2, 9)  # the cursor on j: g-j show, with g-i selected
        canvas = paint(box)
        self.assertEqual(canvas.text(0), LEFT + "ghij ")
        styles = [canvas.cell(0, column)[1] for column in range(1, 5)]
        self.assertEqual(styles, [box.selected_style] * 3 + [box.focused_style])
        unfocused = paint(box, focused=False)
        self.assertEqual(unfocused.cell(0, 1)[1], box.style)


class MouseSelectionTests(unittest.TestCase):
    """Selecting by dragging, and scrolling while held over an arrow."""

    def setUp(self) -> None:
        # Four characters show between the arrows, in columns 1-4.
        self.box = TextBox(0, 0, 6, text="abcdefghij")
        self.box.cursor = 0

    def test_drag_selects(self) -> None:
        """Dragging selects."""
        box = self.box
        mouse(box, "press", 2)  # on b
        self.assertIsNone(box.selection)
        mouse(box, "drag", 4)
        self.assertEqual(box.selected_text, "bc")
        mouse(box, "drag", 1)
        self.assertEqual(box.selected_text, "a")
        mouse(box, "release", 1)
        self.assertEqual(box.selected_text, "a")

    def test_double_click_selects_all(self) -> None:
        """A double-click selects all."""
        box = self.box
        for clicks in (2, 3):
            with self.subTest(clicks=clicks):
                box.cursor = 0
                self.assertTrue(mouse(box, "press", 2, clicks=clicks))
                self.assertEqual(box.selected_text, "abcdefghij")
                self.assertEqual(box.cursor, len("abcdefghij"))
                mouse(box, "release", 2)
                self.assertEqual(box.selected_text, "abcdefghij")

    def test_a_single_click_selects_nothing(self) -> None:
        """A single click selects nothing."""
        mouse(self.box, "press", 2)
        self.assertIsNone(self.box.selection)
        empty = TextBox(0, 0, 6)
        mouse(empty, "press", 2, clicks=2)
        self.assertIsNone(empty.selection)

    def test_double_click_on_the_desktop(self) -> None:
        """A double-click on the desktop."""
        window = Window("W", Rect(0, 0, 8, 30))
        box = window.add(TextBox(1, 2, 12, text="hello world"))
        spin = window.add(SpinBox(3, 2, 8, minimum=0, maximum=999, value=250))
        manager = PresentationManager(windows=[window])
        manager.handle_resize(80, 24)  # the window moves below the menu bar
        inside = window.interior
        for target, widget in ((box, box), (spin.field, spin)):
            with self.subTest(target=target.text):
                row = inside.row + widget.rect.row
                column = inside.column + widget.rect.column + 2
                for _ in range(2):
                    manager.handle_event(MouseEvent("press", "left", row, column))
                    manager.handle_event(MouseEvent("release", "left", row, column))
                self.assertEqual(target.selected_text, target.text)

    def test_click_deselects_and_shift_click_extends(self) -> None:
        """A plain click clears the selection; Shift+click selects to it."""
        box = self.box
        box.select(0, 2)
        mouse(box, "press", 4)
        self.assertIsNone(box.selection)
        mouse(box, "press", 1, shift=True)
        self.assertEqual(box.selection, (0, 3))

    def test_drag_onto_arrow_keeps_selecting(self) -> None:
        """Dragging onto an arrow keeps selecting."""
        box = self.box
        box.scroll_delay = 0.25
        mouse(box, "press", 1)
        mouse(box, "drag", 5)  # ►
        self.assertEqual((box.cursor, box.first_visible), (4, 1))
        wake = box.wake_time()
        assert wake is not None
        box.on_timer(wake)
        self.assertEqual(box.cursor, 5)
        self.assertAlmostEqual(box.wake_time() or 0, wake + 0.25)
        mouse(box, "drag", 6)  # further over: no extra step, same timer
        self.assertEqual(box.cursor, 5)
        for _ in range(10):
            next_wake = box.wake_time()
            if next_wake is None:
                break
            box.on_timer(next_wake)
        self.assertEqual(box.selected_text, "abcdefghij")
        self.assertIsNone(box.wake_time())  # stopped at the end

    def test_moving_back_or_releasing_stops_scrolling(self) -> None:
        """Back over the text, or letting go, stops the scrolling."""
        box = self.box
        mouse(box, "press", 1)
        mouse(box, "drag", 5)
        self.assertIsNotNone(box.wake_time())
        mouse(box, "drag", 3)
        self.assertIsNone(box.wake_time())
        mouse(box, "drag", 5)
        mouse(box, "release", 5)
        self.assertIsNone(box.wake_time())

    def test_drag_left_onto_arrow(self) -> None:
        """◄ works the same way, back to the start."""
        box = self.box
        box.cursor = 10
        mouse(box, "press", 5)  # the blank column after j
        mouse(box, "drag", 0)  # ◄
        while (wake := box.wake_time()) is not None:
            box.on_timer(wake)
        self.assertEqual(box.selection, (0, 10))
        self.assertFalse(box.has_more_left)

    def test_no_scrolling_without_more_text(self) -> None:
        """Over a blank arrow column, a drag just selects to the end."""
        box = TextBox(0, 0, 10, text="abc")
        box.cursor = 0
        mouse(box, "press", 1)
        mouse(box, "drag", 9)
        self.assertIsNone(box.wake_time())
        self.assertEqual(box.selected_text, "abc")


class TimerTests(unittest.TestCase):
    """The presentation manager's widget timers."""

    def test_wait_uses_the_next_wake_time(self) -> None:
        """The wait uses the next wake time."""
        timeouts: list[float | None] = []

        class Timing(FakeTerminal):
            """Records each read's timeout."""

            def read(self, timeout: float | None = None) -> str:
                timeouts.append(timeout)
                return super().read(timeout)

        woken: list[float] = []
        due = time.monotonic()

        class Sleeper(Button):
            """Wants waking once, straight away."""

            def wake_time(self) -> float | None:
                return None if woken else due

            def on_timer(self, now: float) -> None:
                woken.append(now)

        window = Window("W", Rect(1, 0, 6, 20))
        window.add(Sleeper("&Z", 1, 1))
        manager = PresentationManager(windows=[window])
        manager.run(cast(Terminal, Timing(["", "\x11", "\r"], sizes=[(40, 12)])))
        self.assertEqual(len(woken), 1)
        first = timeouts[0]
        assert first is not None
        self.assertLess(first, 0.5)
        self.assertIsNone(timeouts[1])  # nothing wants waking any more


if __name__ == "__main__":
    unittest.main()
