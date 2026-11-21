"""Tests for tables: rows of fields under headings, sorted and resized."""

import unittest

from dasha.canvas import Canvas
from dasha.events import MouseEvent
from dasha.scrollbar import LEFT
from dasha.shortcuts import Shortcuts
from dasha.widgets import Column, Table
from dasha.widgets.table import DOWN_ARROW, UP_ARROW

ROWS = [["b.txt", "10"], ["a.txt", "200"], ["c.txt", "3"]]


def table(**options: object) -> Table:
    """A table of names and sizes.

    :param options: Table options.
    """
    columns = [Column("&Name", 12), Column("Size", 6, align="right", key=int)]
    return Table(columns, 0, 0, 22, 5, rows=ROWS, **options)  # type: ignore[arg-type]


def drawn(widget: Table) -> list[str]:
    """The table's rows as drawn.

    :param widget: The table.
    """
    canvas = Canvas(widget.rect.width, widget.rect.height)
    widget.paint(canvas, canvas.bounds, True)
    return [canvas.text(row) for row in range(widget.rect.height)]


def press(row: int, column: int, action: str = "press", clicks: int = 1) -> MouseEvent:
    """A left button event.

    :param row: Screen row.
    :param column: Screen column.
    :param action: Mouse action.
    :param clicks: Click count.
    """
    return MouseEvent(action, "left", row, column, clicks=clicks)


class TableTests(unittest.TestCase):
    """Drawing, keys and sorting."""

    def setUp(self) -> None:
        self.changes: list[object] = []
        self.chosen: list[object] = []
        self.table = table(
            on_change=lambda t: self.changes.append(t.value),
            on_choose=lambda t: self.chosen.append(t.value),
        )

    def keys(self, *names: str) -> None:
        """Send keys to the table.

        :param names: The keys.
        """
        for name in names:
            self.table.handle_key(name, Shortcuts())

    def test_drawn(self) -> None:
        """Headings, then the rows as given, divided and lined up."""
        rows = drawn(self.table)
        self.assertEqual(rows[0], "Name        │  Size   ")
        self.assertEqual(rows[1], "b.txt       │    10   ")
        self.assertEqual(rows[3], "c.txt       │     3   ")
        canvas = Canvas(22, 5)
        self.table.paint(canvas, canvas.bounds, True)
        self.assertEqual(canvas.cell(0, 0)[1], Table.header_style)
        self.assertEqual(canvas.cell(1, 0)[1], Table.focused_style)

    def test_keys_like_a_list_box(self) -> None:
        """Down, End, Home; typing finds a row by its first field."""
        self.keys("down")
        self.assertEqual(self.table.value, 1)
        self.keys("c")
        self.assertEqual(self.table.value, 2)
        self.keys("home")
        self.assertEqual(self.changes, [1, 2, 0])

    def test_sorting(self) -> None:
        """Sorting."""
        self.keys("down")  # a.txt, row 1 as given
        self.table.sort(1)
        self.assertEqual(self.table.order, [2, 0, 1])
        self.assertEqual(self.table.value, 1)
        self.assertEqual(drawn(self.table)[0], "Name        │Size " + UP_ARROW + "   ")
        self.table.sort(0)  # Name and its arrow fit whole
        self.assertEqual(drawn(self.table)[0][:7], "Name " + UP_ARROW + " ")
        self.table.sort(1, reverse=True)
        self.assertEqual(self.table.order, [1, 0, 2])
        self.assertIn(DOWN_ARROW, drawn(self.table)[0])
        self.assertEqual(self.table.selected_rows, [["a.txt", "200"]])

    def test_click_a_heading_to_sort(self) -> None:
        """Click a heading to sort."""
        self.table.handle_mouse(press(0, 2), 0, 2)
        self.assertEqual((self.table.sorted_by, self.table.reverse), (0, False))
        self.assertEqual(self.table.order, [1, 0, 2])  # a, b, c
        self.table.handle_mouse(press(0, 2), 0, 2)
        self.assertEqual(self.table.reverse, True)
        self.assertTrue(self.table.handle_mouse(press(0, 2, "release"), 0, 2))

    def test_a_long_heading_sorted(self) -> None:
        """A long heading sorted."""
        columns = [Column("Longer name", 6), Column("Size", 4)]
        narrow = Table(columns, 0, 0, 12, 4, rows=ROWS)
        narrow.sort(0)
        self.assertEqual(drawn(narrow)[0][:6], "Longe" + UP_ARROW)

    def test_right_click_highlights_the_row(self) -> None:
        """A right-click highlights the row under it, for its menu."""
        self.table.point_at(3, 2)
        self.assertEqual(self.table.value, 2)
        self.table.point_at(0, 2)  # the headings: no row
        self.assertEqual(self.table.value, 2)

    def test_drag_a_divider_to_resize(self) -> None:
        """Dragging the divider after Name makes the column narrower."""
        self.table.handle_mouse(press(0, 12), 0, 12)
        self.table.handle_mouse(press(0, 8, "drag"), 0, 8)
        self.table.handle_mouse(press(0, 8, "release"), 0, 8)
        self.assertEqual(self.table.table_columns[0].width, 8)
        self.assertEqual(drawn(self.table)[1][:10], "b.txt   │ ")

    def test_clicks_and_choosing(self) -> None:
        """A click highlights a row; a double-click or Enter chooses it."""
        self.table.handle_mouse(press(3, 2), 3, 2)
        self.assertEqual(self.table.value, 2)
        self.table.handle_mouse(press(3, 2, clicks=2), 3, 2)
        self.keys("enter")
        self.assertEqual(self.chosen, [2, 2])
        self.assertIsNone(self.table.index_at(0, 2))  # the headings

    def test_multiple_selection(self) -> None:
        """Space selects, in data order whatever the sorting."""
        many = table(multiple=True)
        many.handle_key(" ", Shortcuts())
        many.handle_key("down", Shortcuts())
        many.handle_key(" ", Shortcuts())
        many.sort(0)
        self.assertEqual(many.value, (0, 1))
        self.assertEqual(many.selected_rows, ROWS[:2])

    def test_set_rows(self) -> None:
        """New rows, sorted as before, short ones filled out."""
        self.table.sort(0)
        self.table.set_rows([["z"], ["y", "1"]])
        self.assertEqual(self.table.order, [1, 0])
        self.assertEqual(self.table.data[0], ["z", ""])
        self.table.set_rows([])
        self.assertIsNone(self.table.value)
        self.assertEqual(self.table.selected_rows, [])

    def test_bad_tables(self) -> None:
        """No columns, or no room; and only known alignments."""
        with self.assertRaises(ValueError):
            Table([], 0, 0, 20, 5, rows=ROWS)
        with self.assertRaises(ValueError):
            Table([Column("A", 3)], 0, 0, 20, 1, rows=ROWS)
        with self.assertRaises(ValueError):
            Column("A", 3, align="middle")
        self.assertEqual(Column("A", 3, align="centre").fit("x"), " x ")


class ScrollingTests(unittest.TestCase):
    """More rows, and wider columns, than fit."""

    def setUp(self) -> None:
        columns = [Column("Name", 10), Column("Kind", 10), Column("Size", 10)]
        rows = [[f"file{n}", "text", str(n)] for n in range(20)]
        self.table = Table(columns, 0, 0, 20, 6, rows=rows)

    def test_scroll_bars(self) -> None:
        """Scroll bars."""
        self.assertEqual(self.table.rows, 4)
        rows = drawn(self.table)
        self.assertEqual(rows[5][0], LEFT)

    def test_sideways(self) -> None:
        """Right scrolls sideways, a few columns at a time."""
        self.table.handle_key("right", Shortcuts())
        self.assertEqual(drawn(self.table)[1][:7], "0     │")
        self.table.handle_key("left", Shortcuts())
        self.assertEqual(drawn(self.table)[1][:5], "file0")

    def test_bottom_bar_and_wheel(self) -> None:
        """The bottom bar's arrows scroll sideways; the wheel scrolls rows."""
        self.table.handle_mouse(press(5, 18), 5, 18)  # the bottom bar's ►
        self.table.handle_mouse(press(5, 18, "release"), 5, 18)
        self.assertIn("file0"[1:], drawn(self.table)[1])
        wheel = MouseEvent("scroll", "down", 2, 2)
        self.table.handle_mouse(wheel, 2, 2)
        self.assertEqual(self.table.first_visible, 3)
        self.assertIsNone(self.table.wake_time())
        self.table.on_timer(0)


if __name__ == "__main__":
    unittest.main()
