"""Tests for window drop shadows."""

import unittest

from dasha.canvas import Canvas, Rect
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuBar, MenuItem
from dasha.desktop import Desktop
from dasha.style import BLACK, BRIGHT_BLACK, Style
from dasha.window import Window

SHADE = Desktop.pattern
SHADOW = Style(foreground=BRIGHT_BLACK, background=BLACK)


class RestyleTests(unittest.TestCase):
    """Canvas.restyle keeps characters and changes styles."""

    def test_restyle_keeps_characters(self) -> None:
        """Only the style changes, and only inside the (clipped) rectangle."""
        canvas = Canvas(4, 2)
        canvas.write(0, 0, "abcd")
        canvas.restyle(Rect(0, 2, 5, 5), SHADOW)
        self.assertEqual(canvas.text(0), "abcd")
        self.assertEqual(canvas.cell(0, 1)[1], Style())
        self.assertEqual(canvas.cell(0, 2), ("c", SHADOW))
        self.assertEqual(canvas.cell(1, 3), (" ", SHADOW))


class ShadowShapeTests(unittest.TestCase):
    """The shadow's position and look."""

    def setUp(self) -> None:
        # A 3x5 window at row 1, column 1 on a desktop-patterned canvas.
        self.canvas = Canvas(10, 6)
        self.canvas.fill(self.canvas.bounds, SHADE)
        self.window = Window("", Rect(1, 1, 3, 5))
        self.window.paint(self.canvas, active=True)

    def shadowed(self) -> list[str]:
        """The canvas as a map: '#' for shadow cells, '.' otherwise."""
        return [
            "".join(
                "#" if self.canvas.cell(row, column)[1] == SHADOW else "."
                for column in range(self.canvas.width)
            )
            for row in range(self.canvas.height)
        ]

    def test_shadow_is_one_row_below_and_two_columns_right(self) -> None:
        """A square-looking shadow: offset one row down and two columns right."""
        self.assertEqual(
            self.shadowed(),
            [
                "..........",
                "..........",
                "......##..",
                "......##..",
                "...#####..",
                "..........",
            ],
        )

    def test_shadow_keeps_what_is_underneath(self) -> None:
        """Shadowed cells keep their character, in dark grey on black."""
        self.assertEqual(self.canvas.cell(4, 3), (SHADE, SHADOW))
        self.assertEqual(self.canvas.cell(2, 7), (SHADE, SHADOW))

    def test_shadow_can_be_turned_off(self) -> None:
        """A shadow_style of None draws no shadow."""

        class Flat(Window):
            """A window without a shadow."""

            shadow_style = None

        canvas = Canvas(10, 6)
        Flat("", Rect(1, 1, 3, 5)).paint(canvas, active=True)
        self.assertEqual(canvas.cell(4, 3)[1], Style())


class ShadowLayeringTests(unittest.TestCase):
    """Shadows fall on windows behind, but never on the bars."""

    def setUp(self) -> None:
        self.back = Window("Back", Rect(1, 0, 6, 20))
        self.front = Window("Front", Rect(2, 2, 3, 6))
        self.manager = PresentationManager(windows=[self.back, self.front])
        self.manager.handle_resize(30, 8)
        self.canvas = Canvas(30, 8)

    def test_shadow_falls_on_window_behind(self) -> None:
        """The front window's shadow darkens the back window's body."""
        self.manager.compose(self.canvas)
        self.assertEqual(self.canvas.cell(5, 5), (" ", SHADOW))
        self.assertEqual(self.canvas.cell(3, 8), (" ", SHADOW))

    def test_window_in_front_covers_shadow_of_window_behind(self) -> None:
        """A shadow is painted before the windows in front of it."""
        self.manager.bring_to_front(self.back)
        self.manager.compose(self.canvas)
        self.assertNotEqual(self.canvas.cell(5, 5)[1], SHADOW)

    def test_status_bar_is_on_top_of_shadows(self) -> None:
        """A shadow reaching the bottom row leaves the status bar untouched."""
        self.manager.compose(self.canvas)
        bottom_row = self.canvas.height - 1
        status_bar = self.manager.status_bar
        styles = (status_bar.style, status_bar.key_style)
        for column in range(self.canvas.width):  # the bar's own colours only
            self.assertIn(self.canvas.cell(bottom_row, column)[1], styles)
        # The back window's shadow is just above the bar, on the desktop.
        self.assertEqual(self.canvas.cell(bottom_row - 1, 21), (SHADE, SHADOW))

    def test_open_menu_is_on_top_of_shadows(self) -> None:
        """A drop-down covers any shadow beneath it."""
        self.manager.compose(self.canvas)
        self.assertEqual(self.canvas.cell(3, 8)[1], SHADOW)  # front's shadow
        self.manager.handle_event("f10")  # system menu: rows 1-3, columns 0-15
        self.manager.compose(self.canvas)
        self.assertNotEqual(self.canvas.cell(3, 8)[1], SHADOW)


def shadow_map(canvas: Canvas) -> list[str]:
    """The canvas as a map: '#' for shadow cells, '.' otherwise."""
    return [
        "".join(
            "#" if canvas.cell(row, column)[1] == SHADOW else "."
            for column in range(canvas.width)
        )
        for row in range(canvas.height)
    ]


class MenuShadowTests(unittest.TestCase):
    """Drop-down menus cast the same shadow as windows; the bar casts none."""

    def setUp(self) -> None:
        self.menu_bar = MenuBar()
        self.menu_bar.set_menus(
            [Menu("&File", [MenuItem("&Open", print), MenuItem("&Save", print)])]
        )
        self.canvas = Canvas(14, 7)
        self.canvas.fill(self.canvas.bounds, SHADE)

    def paint(self) -> None:
        """Paint the shadow and then the bar, as the manager does."""
        self.menu_bar.paint_shadow(self.canvas)
        self.menu_bar.paint(self.canvas)

    def test_open_menu_shadow_shape(self) -> None:
        """One row below and two columns right of the drop-down."""
        self.menu_bar.open(0)
        self.paint()
        rect = self.menu_bar.dropdown_rect(14)
        self.assertEqual(rect, Rect(1, 0, 4, 10))  # with its blank side columns
        self.assertEqual(
            shadow_map(self.canvas),
            [
                "..............",  # the bar: no shadow
                "..............",
                "..........##..",
                "..........##..",
                "..........##..",
                "..##########..",
                "..............",
            ],
        )
        self.assertEqual(self.canvas.cell(5, 4), (SHADE, SHADOW))

    def test_closed_menu_casts_no_shadow(self) -> None:
        """With no drop-down open there is nothing to cast a shadow."""
        self.paint()
        self.assertNotIn("#", "".join(shadow_map(self.canvas)))

    def test_menu_shadow_can_be_turned_off(self) -> None:
        """shadow_style = None on a subclass removes the shadow."""

        class FlatMenuBar(MenuBar):
            """A menu bar without drop-down shadows."""

            shadow_style = None

        self.menu_bar = FlatMenuBar()
        self.menu_bar.set_menus([Menu("&File", [MenuItem("&Open", print)])])
        self.menu_bar.open(0)
        self.paint()
        self.assertNotIn("#", "".join(shadow_map(self.canvas)))


class MenuShadowLayeringTests(unittest.TestCase):
    """The drop-down's shadow falls on windows but never on the status bar."""

    def test_shadow_on_window_but_not_status_bar(self) -> None:
        """On a short screen the shadow stops at the status bar."""
        window = Window("W", Rect(1, 0, 5, 40))
        manager = PresentationManager(windows=[window])
        manager.handle_resize(40, 11)
        # The system menu (About, Settings..., Themes, Animations, Command
        # prompt, -, Shutdown): rows 1-9.
        manager.handle_event("f10")
        rect = manager.menu_bar.dropdown_rect(40)
        assert rect is not None
        canvas = Canvas(40, 11)
        manager.compose(canvas)
        # The right-hand strip darkens the window's body...
        self.assertEqual(canvas.cell(2, rect.right)[1], SHADOW)
        # ...but the bottom strip would be on the status bar row: untouched.
        status_row = 10
        self.assertEqual(rect.bottom, status_row)
        for column in range(40):
            self.assertEqual(
                canvas.cell(status_row, column)[1], manager.status_bar.style
            )


if __name__ == "__main__":
    unittest.main()
