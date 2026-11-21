"""Tests for menu and window animations."""

import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

from dasha.__main__ import _desktop
from dasha.animation import WindowAnimation, between, frame_parts
from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuItem
from dasha.registry import (
    ManifestError,
    read_animations_setting,
    save_animations_setting,
)
from dasha.terminal import Terminal
from dasha.window import Window
from tests.support import isolated_home

COLUMNS, LINES = 40, 12


class _Screen:  # pylint: disable=too-few-public-methods
    """A terminal of a fixed size that keeps nothing."""

    def size(self) -> tuple[int, int]:
        """Always the same size."""
        return (COLUMNS, LINES)

    def write(self, text: str) -> None:
        """Record and drop output.

        :param text: The output.
        """
        del text

    def flush(self) -> None:
        """Nothing to flush."""


def lined(title: str, rect: Rect, count: int = 3) -> Window:
    """A window with numbered lines.

    :param title: Title text.
    :param rect: Position and size.
    :param count: Number of lines.
    """
    lines = [f"line {number}" for number in range(1, count + 1)]
    return Window(title, rect, lines, maximisable=True, minimisable=True)


class Animated(unittest.TestCase):
    """A desktop with animations on, whose frames are kept."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.animations = True
        self.manager.animation_frame_time = 0
        self.manager.handle_resize(COLUMNS, LINES)
        self.terminal = cast(Terminal, _Screen())
        self.frames: list[Canvas] = []
        compose = self.manager.compose

        def kept(canvas: Canvas) -> None:
            compose(canvas)
            self.frames.append(canvas)

        patch = mock.patch.object(self.manager, "compose", kept)
        patch.start()
        self.addCleanup(patch.stop)
        self.draw()  # the screen as it starts, so nothing is new

    def draw(self) -> list[Canvas]:
        """Draw a frame; return every frame drawn."""
        self.frames.clear()
        self.manager._draw_frame(self.terminal)  # pylint: disable=protected-access
        return list(self.frames)


def frame_corners(canvas: Canvas, corner: str) -> list[tuple[int, int]]:
    """Where a frame corner is on a canvas.

    :param canvas: The canvas.
    :param corner: The corner character.
    """
    return [
        (row, column)
        for row in range(canvas.height)
        for column in range(canvas.width)
        if canvas.cell(row, column)[0] == corner
    ]


class GeometryTests(unittest.TestCase):
    """Part-way places."""

    def test_parts(self) -> None:
        """Frames part-way are evenly spaced, the end not among them."""
        self.assertEqual(frame_parts(2), [1 / 3, 2 / 3])
        self.assertEqual(frame_parts(0), [])

    def test_between(self) -> None:
        """Rects between two others."""
        start, end = Rect(2, 4, 6, 10), Rect(1, 0, 10, 40)
        self.assertEqual(between(start, end, 0), start)
        self.assertEqual(between(start, end, 1), end)
        self.assertEqual(between(start, end, 0.5), Rect(2, 2, 8, 25))
        self.assertEqual(between(start, Rect(11, 20, 0, 0), 1), Rect(11, 20, 2, 2))

    def test_copy_from(self) -> None:
        """Another canvas is copied in, clipped."""
        source = Canvas(3, 2)
        source.write(0, 0, "abc")
        source.write(1, 0, "def")
        canvas = Canvas(6, 3)
        canvas.copy_from(source, 1, 4)
        self.assertEqual([canvas.text(1), canvas.text(2)], ["    ab", "    de"])
        canvas = Canvas(6, 3)
        canvas.copy_from(source, -1, -1, clip=Rect(0, 0, 3, 1))
        self.assertEqual(canvas.text(0), "e     ")


class PaintBetweenTests(unittest.TestCase):
    """A window drawn part-way."""

    def test_inside_stays_and_window_is_untouched(self) -> None:
        """The inside is kept and the window untouched."""
        window = lined("W", Rect(1, 1, 6, 12), count=10)
        window.scroll_to(2, 0)
        inside = window.render_interior(True)
        canvas = Canvas(COLUMNS, LINES)
        window.paint_between(canvas, Rect(1, 1, 10, 30), inside, (False, False))
        self.assertEqual(canvas.text(2)[3:9], "line 3")
        self.assertEqual(canvas.text(9)[3:9], "      ")  # blank beyond it
        self.assertEqual(window.rect, Rect(1, 1, 6, 12))
        self.assertEqual(window.scroll_row, 2)

    def test_only_the_scroll_bars_allowed(self) -> None:
        """Only the scroll bars allowed are drawn."""
        window = lined("W", Rect(1, 1, 4, 12), count=10)
        inside = window.render_interior(True)
        without = Canvas(COLUMNS, LINES)
        window.paint_between(without, Rect(1, 1, 6, 20), inside, (False, False))
        with_bar = Canvas(COLUMNS, LINES)
        window.paint_between(with_bar, Rect(1, 1, 6, 20), inside, (True, False))
        right = [without.cell(row, 20)[0] for row in range(2, 6)]
        self.assertEqual(set(right), {window.border.vertical})
        self.assertNotEqual([with_bar.cell(row, 20)[0] for row in range(2, 6)], right)


class WindowAnimationTests(Animated):
    """Windows minimised, restored and maximised."""

    def test_off_draws_one_frame(self) -> None:
        """With animations off, a change is drawn at once."""
        window = lined("W", Rect(2, 2, 6, 16))
        self.manager.add(window)
        self.draw()
        self.manager.animations = False
        self.manager.minimise(window)
        self.assertEqual(len(self.draw()), 1)

    def test_minimise_shrinks_into_the_status_bar(self) -> None:
        """Minimising shrinks into the status bar."""
        window = lined("W", Rect(2, 2, 6, 16))
        self.manager.add(window)
        self.draw()
        self.manager.minimise(window)
        frames = self.draw()
        self.assertEqual(len(frames), 3)
        middle = Rect(LINES - 1, COLUMNS // 2, 0, 0)
        for frame, part in zip(frames, frame_parts(2)):
            rect = between(Rect(2, 2, 6, 16), middle, part)
            top_left = (rect.row, rect.column)
            self.assertIn(top_left, frame_corners(frame, window.border.top_left))
        self.assertEqual(frame_corners(frames[-1], window.border.top_left), [])
        self.assertEqual(len(self.draw()), 1)  # done with

    def test_restore_grows_out_of_the_status_bar(self) -> None:
        """Restoring grows from the status bar."""
        window = lined("W", Rect(2, 2, 6, 16))
        self.manager.add(window)
        self.manager.minimise(window)
        self.draw()
        self.manager.restore(window)
        frames = self.draw()
        self.assertEqual(len(frames), 3)
        middle = Rect(LINES - 1, COLUMNS // 2, 0, 0)
        first = between(middle, Rect(2, 2, 6, 16), 1 / 3)
        corners = frame_corners(frames[0], window.border.top_left)
        self.assertEqual(corners, [(first.row, first.column)])
        self.assertIn((2, 2), frame_corners(frames[-1], window.border.top_left))

    def test_maximise_and_restore_move_between(self) -> None:
        """Maximising and restoring animate."""
        window = lined("W", Rect(3, 4, 6, 16))
        self.manager.add(window)
        self.draw()
        self.manager.maximise(window)
        frames = self.draw()
        self.assertEqual(len(frames), 3)
        first = between(Rect(3, 4, 6, 16), self.manager.workspace, 1 / 3)
        corners = frame_corners(frames[0], window.border.top_left)
        self.assertEqual(corners, [(first.row, first.column)])
        self.manager.restore(window)
        frames = self.draw()
        self.assertEqual(len(frames), 3)
        last = between(self.manager.workspace, Rect(3, 4, 6, 16), 2 / 3)
        corners = frame_corners(frames[1], window.border.top_left)
        self.assertEqual(corners, [(last.row, last.column)])

    def test_maximise_from_minimised_grows_out_of_the_status_bar(self) -> None:
        """Maximised while minimised, it grows from the status bar."""
        window = lined("W", Rect(3, 4, 6, 16))
        self.manager.add(window)
        self.manager.minimise(window)
        self.draw()
        self.manager.maximise(window)
        frames = self.draw()
        middle = Rect(LINES - 1, COLUMNS // 2, 0, 0)
        first = between(middle, self.manager.workspace, 1 / 3)
        corners = frame_corners(frames[0], window.border.top_left)
        self.assertEqual(corners, [(first.row, first.column)])

    def test_no_scroll_bar_on_the_way_to_a_size_without(self) -> None:
        """No scroll bar on the way to a fitting size."""
        window = lined("W", Rect(1, 0, 5, 16), count=8)
        self.manager.add(window)
        self.assertIsNotNone(window.scroll_bars[0])
        self.draw()
        self.manager.maximise(window)
        frames = self.draw()
        for frame in frames[:-1]:
            column = frame_corners(frame, window.border.top_right)[0][1]
            right = {frame.cell(row, column)[0] for row in range(2, 5)}
            self.assertEqual(right, {window.border.vertical})

    def test_inside_stays_as_it_was(self) -> None:
        """The window's text is where it was in every frame part-way."""
        window = lined("W", Rect(3, 4, 6, 16))
        self.manager.add(window)
        self.draw()
        self.manager.maximise(window)
        for frame in self.draw()[:-1]:
            corner = frame_corners(frame, window.border.top_left)[0]
            text = frame.text(corner[0] + 1)
            self.assertEqual(text[corner[1] + 2 : corner[1] + 8], "line 1")

    def test_closed_meanwhile_is_not_drawn(self) -> None:
        """A window closed meanwhile is not drawn."""
        window = lined("W", Rect(2, 2, 6, 16))
        self.manager.add(window)
        self.manager.minimise(window)
        self.draw()
        self.manager.restore(window)
        self.manager.remove(window)
        self.assertEqual(len(self.draw()), 1)

    def test_dragged_out_of_maximised_is_not_animated(self) -> None:
        """Dragging out of maximised is instant."""
        window = lined("W", Rect(3, 4, 6, 16))
        self.manager.add(window)
        self.manager.maximise(window)
        self.draw()
        self.manager.handle_event(MouseEvent("press", "left", 1, 10))
        self.manager.handle_event(MouseEvent("drag", "left", 4, 12))
        self.assertFalse(window.maximised)
        self.assertEqual(len(self.draw()), 1)


class MenuAnimationTests(Animated):
    """Drop-downs."""

    def setUp(self) -> None:
        super().setUp()
        self.manager.system_menu.items[:] = [
            MenuItem(f"Item &{number}", status="") for number in range(1, 7)
        ]
        self.manager.show_system_menu = True

    def test_opening_drops_down(self) -> None:
        """A new drop-down slides out."""
        self.manager.handle_event("f10")
        frames = self.draw()
        self.assertEqual(len(frames), 3)
        rect = self.manager.menu_bar.dropdown_rect(COLUMNS)
        assert rect is not None
        bottom = self.manager.menu_bar.border.bottom_left
        rows = [
            row
            for frame in frames
            for row in range(1, LINES)
            if bottom in frame.text(row)[rect.column : rect.right]
        ]
        self.assertEqual(rows, [3, 5, rect.bottom - 1])
        for frame in frames:
            self.assertIn("\N{IDENTICAL TO}", frame.text(0))  # the bar stays
        self.assertEqual(len(self.draw()), 1)  # open already: not again

    def test_another_menu_drops_too(self) -> None:
        """Moving along the bar to another menu drops that one down."""
        own = Menu("&File", [MenuItem("&Open")])
        window = Window("W", Rect(2, 2, 6, 16), menus=[own])
        self.manager.add(window)
        self.manager.handle_event("f10")
        self.draw()
        self.manager.handle_event("right")
        self.assertIs(self.manager.menu_bar.open_menu, own)
        self.assertEqual(len(self.draw()), 3)

    def test_off_does_not_drop(self) -> None:
        """With animations off, the drop-down is drawn whole at once."""
        self.manager.animations = False
        self.manager.handle_event("f10")
        self.assertEqual(len(self.draw()), 1)


class ToggleTests(unittest.TestCase):
    """The system menu's Animations, and the setting."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(directory.cleanup)
        self.settings = Path(directory.name) / "settings.toml"

    def test_system_menu_toggles(self) -> None:
        """The system menu toggles animations."""
        manager = PresentationManager()
        manager.settings_path = self.settings
        item = next(i for i in manager.system_menu.items if "nimations" in i.label)
        self.assertEqual(item.label, "A&nimations: Off")
        assert item.action is not None
        item.action()
        self.assertTrue(manager.animations)
        manager.bar_menus()
        self.assertEqual(item.label, "A&nimations: On")
        self.assertFalse(self.settings.exists())  # not remembered unless asked

    def test_remembered_when_asked(self) -> None:
        """A desktop remembers animations turned off, and on again."""
        manager = PresentationManager()
        manager.settings_path = self.settings
        manager.remember_animations = True
        manager.set_animations(False)
        self.assertFalse(read_animations_setting(self.settings))
        manager.set_animations(True)
        self.assertTrue(read_animations_setting(self.settings))
        self.assertEqual(self.settings.read_text(encoding="utf-8"), "")

    def test_setting(self) -> None:
        """On unless the settings say otherwise; other settings kept."""
        self.assertTrue(read_animations_setting(self.settings))
        self.settings.write_text('theme = "dark"\n', encoding="utf-8")
        save_animations_setting(False, self.settings)
        self.assertFalse(read_animations_setting(self.settings))
        self.assertIn('theme = "dark"', self.settings.read_text(encoding="utf-8"))
        self.settings.write_text("animations = 1\n", encoding="utf-8")
        with self.assertRaises(ManifestError):
            read_animations_setting(self.settings)

    def test_saved_setting_used(self) -> None:
        """The saved setting is used."""
        manager = PresentationManager()
        manager.settings_path = self.settings
        manager.use_saved_animations()
        self.assertTrue(manager.animations)
        save_animations_setting(False, self.settings)
        manager.use_saved_animations()
        self.assertFalse(manager.animations)
        self.settings.write_text("animations = [\n", encoding="utf-8")
        manager.use_saved_animations()
        self.assertFalse(manager.animations)

    def test_desktop_animates_and_remembers(self) -> None:
        """The desktop remembers the setting."""
        isolated_home(self)
        manager = _desktop(None, [], processes=False)
        self.assertTrue(manager.animations)
        self.assertTrue(manager.remember_animations)
        self.assertFalse(
            _desktop(None, [], processes=False, animations=False).animations
        )

    def test_window_animation_of(self) -> None:
        """An animation starts where the window is, with what is inside."""
        window = lined("W", Rect(2, 2, 6, 16))
        animation = WindowAnimation.of(window)
        self.assertEqual((animation.start, animation.end), (window.rect, window.rect))
        self.assertEqual(animation.inside.text(0)[1:7], "line 1")


if __name__ == "__main__":
    unittest.main()
