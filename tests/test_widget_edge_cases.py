"""Tests for widget edge cases."""

# pylint: disable=protected-access

import unittest
from types import SimpleNamespace
from typing import Any

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.shortcuts import Shortcuts
from dasha.style import Style
from dasha.widgets import (
    AutoCompleteBox,
    Button,
    CheckBoxes,
    Grow,
    Collapsible,
    Column,
    ComboBox,
    Label,
    ListBox,
    Paragraph,
    ProgressBar,
    ScrollBar,
    Slider,
    SpinBox,
    Splitter,
    Switch,
    Table,
    Tabs,
    TextArea,
    TextBox,
    TreeNode,
    TreeView,
    Widget,
)
from dasha.widgets.editing import UndoHistory
from dasha.window import Window

KEYS = Shortcuts()


def mouse(action: str, row: int, column: int, button: str = "left") -> MouseEvent:
    """A mouse event at a position.

    :param action: Mouse action.
    :param row: Row.
    :param column: Column.
    :param button: Mouse button.
    """
    return MouseEvent(action, button, row, column)


def window(*widgets: Widget, height: int = 20, width: int = 60) -> Window:
    """A window holding these widgets.

    :param widgets: The widgets.
    :param height: Window height.
    :param width: Window width.
    """
    holder = Window("W", Rect(0, 0, height, width))
    for widget in widgets:
        holder.add(widget)
    return holder


def paint(widget: Widget, width: int, height: int, focused: bool = False) -> Canvas:
    """The widget painted on its own canvas.

    :param widget: The widget.
    :param width: Canvas width.
    :param height: Canvas height.
    :param focused: Whether it has the focus.
    """
    canvas = Canvas(width, height)
    widget.paint(canvas, canvas.bounds, focused)
    return canvas


class Plain(Widget):
    """A widget that keeps every default of ``Widget``."""

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        del canvas, origin, focused


class WidgetTests(unittest.TestCase):
    """What every widget does unless it says otherwise."""

    def test_defaults(self) -> None:
        """Defaults."""
        widget = Plain(0, 0, 4)
        self.assertIsNone(widget.value)
        self.assertFalse(widget.handle_mouse(mouse("press", 0, 0), 0, 0))
        widget.on_timer(0.0)


class AutoCompleteTests(unittest.TestCase):
    """Suggestions taken, and pasting."""

    def test_a_suggestion_too_long(self) -> None:
        """A suggestion too long."""
        box = AutoCompleteBox(0, 0, 20, text="ab", max_length=3)

        class Suggesting(PresentationManager):
            """Answers every popup by taking a long suggestion."""

            def suggest(self, *args: Any, **kwargs: Any) -> Any:
                del args, kwargs
                return SimpleNamespace(result="ok", chosen="abcdef", passed_key=None)

        Suggesting(windows=[window(box)])
        box.cursor = 0
        self.assertTrue(box.suggest())
        self.assertEqual((box.text, box.cursor), ("ab", 2))

    def test_paste(self) -> None:
        """Paste."""
        box = window(AutoCompleteBox(0, 0, 20, suggestions=["abc"])).widgets[0]
        assert isinstance(box, AutoCompleteBox)
        self.assertTrue(box.handle_paste("ab"))
        self.assertEqual(box.text, "ab")
        box.max_length = 2
        self.assertFalse(box.handle_paste("c"))


class ButtonTests(unittest.TestCase):
    """The mouse on a button."""

    def test_mouse(self) -> None:
        """Mouse buttons."""
        pressed: list[str] = []
        button = Button("OK", 0, 0, action=lambda b: pressed.append("ok"))
        self.assertFalse(button.handle_mouse(mouse("press", 0, 1, "right"), 0, 1))
        self.assertFalse(button.handle_mouse(mouse("release", 0, 1), 0, 1))
        self.assertTrue(button.handle_mouse(mouse("press", 0, 1), 0, 1))
        self.assertTrue(button.handle_mouse(mouse("drag", 0, 1), 0, 1))
        self.assertTrue(button.handle_mouse(mouse("release", 0, 1), 0, 1))
        self.assertEqual(pressed, ["ok"])

    def test_pressed_alone(self) -> None:
        """With no action and no window, pressing it does nothing."""
        Button("OK", 0, 0).activate()


class ClusterTests(unittest.TestCase):
    """Check boxes laid out in columns."""

    def setUp(self) -> None:
        self.boxes = CheckBoxes(["&One", "&Two", "T&hree"], 0, 0, columns=2)

    def test_enabling_moves_off_a_disabled_option(self) -> None:
        """With the current option disabled, enabling another moves to it."""
        self.boxes.disabled.add(0)
        self.boxes.enable(1)
        self.assertEqual(self.boxes.current, 1)

    def test_size_and_positions(self) -> None:
        """Size and positions."""
        rect = self.boxes.rect
        self.assertEqual(self.boxes.min_size(), (rect.width, rect.height))
        self.assertIsNone(self.boxes.index_at(-1, 0))
        self.assertIsNone(self.boxes.index_at(0, 500))
        self.assertIsNone(self.boxes.index_at(1, self.boxes.rect.width - 1))

    def test_a_disabled_option_is_not_pressed(self) -> None:
        """Space on a disabled option is used up, changing nothing."""
        self.boxes.disabled.add(0)
        self.assertTrue(self.boxes.handle_key(" ", KEYS))
        self.assertEqual(self.boxes.checked, [False, False, False])

    def test_mouse(self) -> None:
        """Only the left button presses an option, and only a press."""
        self.assertFalse(self.boxes.handle_mouse(mouse("press", 0, 0, "right"), 0, 0))
        self.boxes.handle_mouse(mouse("drag", 0, 0), 0, 0)
        self.assertEqual(self.boxes.checked, [False, False, False])


class CollapsibleTests(unittest.TestCase):
    """An area that opens and closes."""

    def test_without_a_window(self) -> None:
        """Without a window."""
        area = Collapsible("&More", 0, 0, 20)
        area.expanded = True
        area.expanded = True
        self.assertTrue(area.expanded)

    def test_mouse(self) -> None:
        """A release on its own is used up but does not toggle."""
        area = Collapsible("&More", 0, 0, 20)
        self.assertTrue(area.handle_mouse(mouse("release", 0, 0), 0, 0))
        self.assertFalse(area.expanded)


class ComboBoxTests(unittest.TestCase):
    """A box that drops down a list."""

    def test_too_narrow(self) -> None:
        """Refused."""
        with self.assertRaises(ValueError):
            ComboBox(["a"], 0, 0, 1)

    def test_empty(self) -> None:
        """Choosing from no items does nothing."""
        box = ComboBox([], 0, 0, 10)
        box.choose(3)
        self.assertEqual(box.items, [])
        self.assertEqual(box.min_size(), (box.min_width, 1))

    def test_mouse(self) -> None:
        """Only the left button; a drag is used up without dropping down."""
        box = ComboBox(["a", "b"], 0, 0, 10)
        self.assertFalse(box.handle_mouse(mouse("press", 0, 0, "right"), 0, 0))
        self.assertTrue(box.handle_mouse(mouse("drag", 0, 0), 0, 0))


class UndoHistoryTests(unittest.TestCase):
    """The steps behind Undo and Redo."""

    def test_redo_and_replace(self) -> None:
        """Nothing to redo at first; replacing with no steps keeps none."""
        history: UndoHistory[str] = UndoHistory()
        self.assertFalse(history.can_redo)
        history.replace_last("a")
        self.assertIsNone(history.pop())


class LabelTests(unittest.TestCase):
    """A label with colours of its own."""

    def test_its_own_style(self) -> None:
        """Drawn in it, without a window."""
        style = Style(bold=True)
        canvas = paint(Label("Hi", 0, 0, style=style), 4, 1)
        self.assertEqual(canvas.cell(0, 0), ("H", style))


class ListBoxTests(unittest.TestCase):
    """Lists with nothing in them, or one selection."""

    def test_single_selection(self) -> None:
        """Ranges and Ctrl+A are for multiple selection only."""
        box = ListBox(["a", "b", "c"], 0, 0, 10, 3)
        box.select_range(0, 2)
        box.toggle_all()
        self.assertEqual(box.selected, set())

    def test_a_range_already_selected(self) -> None:
        """Changes nothing, and says nothing."""
        changes: list[object] = []
        box = ListBox(["a", "b"], 0, 0, 10, 3, multiple=True, on_change=changes.append)
        box.select_range(0, 1)
        box.select_range(1, 0)
        self.assertEqual(len(changes), 1)

    def test_empty(self) -> None:
        """Empty."""
        box = ListBox([], 0, 0, 10, 3, multiple=True)
        box.toggle_all()
        box.move_to(2)
        box.choose()
        self.assertEqual(box.cursor, 0)
        wheel = MouseEvent("scroll", "down", 0, 0)
        self.assertFalse(box.handle_mouse(wheel, 0, 0))

    def test_positions(self) -> None:
        """Positions."""
        box = ListBox(["a", "b", "c", "d"], 0, 0, 10, 2, columns=2)
        self.assertIsNone(box.index_at(-1, 0))
        self.assertIsNone(box.index_at(5, 0))
        self.assertEqual(box._shown_column(500), box.columns - 1)

    def test_mouse(self) -> None:
        """Mouse use."""
        box = ListBox(["a"], 0, 0, 10, 3)
        self.assertFalse(box.handle_mouse(mouse("press", 0, 0, "right"), 0, 0))
        self.assertTrue(box.handle_mouse(mouse("press", 2, 0), 2, 0))
        self.assertTrue(box.handle_mouse(mouse("drag", 0, 0), 0, 0))
        self.assertEqual(box.cursor, 0)


class ParagraphTests(unittest.TestCase):
    """Wrapped text."""

    def test_text(self) -> None:
        """Read back as it was given."""
        self.assertEqual(Paragraph("Hello there", 0, 0, 20).text, "Hello there")


class ProgressBarTests(unittest.TestCase):
    """A bar that fills."""

    def test_no_cells(self) -> None:
        """Refused."""
        with self.assertRaises(ValueError):
            ProgressBar(0, 0, 0)
        with self.assertRaises(ValueError):
            ProgressBar(0, 0, 5, 0)

    def test_size(self) -> None:
        """One cell at least."""
        self.assertEqual(ProgressBar(0, 0, 5).min_size(), (1, 1))


class ScrollBarTests(unittest.TestCase):
    """A bar on its own."""

    def test_size_and_range(self) -> None:
        """Size and range."""
        scroll = ScrollBar(0, 0, 10, maximum=20, page=5)
        self.assertEqual(scroll.min_size(), (1, 2))
        self.assertEqual(ScrollBar(0, 0, 10, vertical=False).min_size(), (2, 1))
        scroll.set_range(30)
        self.assertEqual(scroll.page, 5)

    def test_mouse(self) -> None:
        """Only the left button; a plain move is not used."""
        scroll = ScrollBar(0, 0, 10, maximum=20)
        self.assertFalse(scroll.handle_mouse(mouse("press", 1, 0, "right"), 1, 0))
        self.assertFalse(scroll.handle_mouse(mouse("move", 1, 0, "none"), 1, 0))
        # Any other action of the left button (terminals report none).
        self.assertFalse(scroll.handle_mouse(mouse("move", 1, 0), 1, 0))


class SliderTests(unittest.TestCase):
    """A slider on its own."""

    def test_refused(self) -> None:
        """Too short, upside down, or with no step."""
        for options in (
            {"length": 1},
            {"length": 5, "minimum": 10, "maximum": 0},
            {"length": 5, "step": 0},
        ):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    Slider(0, 0, **options)  # type: ignore[arg-type]

    def test_size(self) -> None:
        """Two cells along it at least."""
        self.assertEqual(Slider(0, 0, 5).min_size(), (2, 1))
        self.assertEqual(Slider(0, 0, 5, vertical=True).min_size(), (1, 2))

    def test_other_keys_and_buttons(self) -> None:
        """Left for the window; so are other buttons and plain moves."""
        slider = Slider(0, 0, 5)
        self.assertFalse(slider.handle_key("x", KEYS))
        self.assertFalse(slider.handle_mouse(mouse("press", 0, 0, "right"), 0, 0))
        self.assertFalse(slider.handle_mouse(mouse("move", 0, 0, "none"), 0, 0))
        self.assertFalse(slider.handle_mouse(mouse("move", 0, 0), 0, 0))


class SpinBoxTests(unittest.TestCase):
    """The arrows held down."""

    def test_a_plain_move_while_repeating(self) -> None:
        """Not used up, and the repeat goes on."""
        box = SpinBox(0, 0, 8, minimum=0, maximum=9)
        window(box)
        up = box.rect.right - 1
        self.assertTrue(box.handle_mouse(mouse("press", 0, up), 0, up))
        self.assertFalse(box.handle_mouse(mouse("move", 0, up), 0, up))


class SplitterTests(unittest.TestCase):
    """A splitter before it is in a window, and the mouse."""

    def test_without_a_window(self) -> None:
        """The divider moves; there are no widgets to move with it."""
        splitter = Splitter(0, 0, 20, 5, position=5)
        splitter.move_divider(8)
        self.assertEqual(splitter.position, 8)

    def test_a_pane_left_as_it_was(self) -> None:
        """A pane left as it was."""
        holder = window(height=12, width=44)
        splitter = holder.add(Splitter(0, 0, 40, 8, position=15), grow=Grow.ALL)
        label = splitter.first.add(Label("left", 1, 2))
        rect = holder.rect
        holder.rect = Rect(rect.row, rect.column, rect.height, rect.width + 6)
        self.assertEqual((label.rect.row, label.rect.column), (1, 2))
        self.assertEqual(splitter.pane_rect(True).width, 30)

    def test_a_splitter_in_a_pane(self) -> None:
        """A splitter in a pane."""
        outer = window(Splitter(0, 0, 40, 8, position=20), height=12, width=44)
        splitter = outer.widgets[0]
        assert isinstance(splitter, Splitter)
        inner = splitter.first.add(Splitter(0, 0, 20, 8, position=10))
        inner.grow = Grow.ALL
        label = inner.first.add(Label("deep", 1, 1))
        width = label.rect.width
        splitter.position = 25
        self.assertEqual(label.rect.width, width)

    def test_other_actions_while_dragging(self) -> None:
        """Other actions while dragging."""
        splitter = Splitter(0, 0, 20, 5, position=5)
        window(splitter)
        self.assertTrue(splitter.handle_mouse(mouse("press", 0, 5), 0, 5))
        self.assertFalse(splitter.handle_mouse(mouse("move", 0, 6), 0, 6))
        self.assertTrue(splitter.handle_mouse(mouse("release", 0, 6), 0, 6))


class SwitchTests(unittest.TestCase):
    """A switch."""

    def test_disabled(self) -> None:
        """Pressing it changes nothing."""
        switch = Switch("&On", 0, 0, disabled=True)
        switch.activate()
        self.assertFalse(switch.on)
        self.assertEqual(switch.min_size(), (switch.rect.width, 2))

    def test_a_press_on_its_shadow(self) -> None:
        """The row below the track is used up, but switches nothing."""
        switch = Switch("&On", 0, 0)
        self.assertTrue(switch.handle_mouse(mouse("press", 1, 1), 1, 1))
        self.assertFalse(switch.on)


class TableTests(unittest.TestCase):
    """Tables with nothing in them, and their corners."""

    def setUp(self) -> None:
        columns = [Column("Name", 8), Column("Size", 4)]
        self.table = Table(columns, 0, 0, 20, 5)

    def test_empty(self) -> None:
        """Sorting no rows; the size it needs."""
        self.table.sort(1)
        self.assertEqual(self.table.min_size(), (3, 2))
        self.assertEqual(self.table._column_widths(), [self.table._room()])

    def test_columns_at(self) -> None:
        """A divider, and past the last column, are no column."""
        self.assertEqual(self.table.column_at(0), 0)
        self.assertIsNone(self.table.column_at(8))
        self.assertIsNone(self.table.column_at(500))
        self.assertTrue(self.table.handle_mouse(mouse("press", 0, 15), 0, 15))
        self.assertIsNone(self.table.sorted_by)

    def test_the_side_bar_held(self) -> None:
        """The side bar held."""
        columns = [Column("Name", 10), Column("Kind", 10), Column("Size", 10)]
        rows = [[f"file{n}", "text", str(n)] for n in range(20)]
        table = Table(columns, 0, 0, 20, 6, rows=rows)
        self.assertFalse(table.handle_key("f12", KEYS))
        table.handle_mouse(mouse("press", 5, 18), 5, 18)
        wake = table.wake_time()
        assert wake is not None
        before = table._left
        table.on_timer(wake + 10)
        self.assertGreater(table._left, before)


class TabsTests(unittest.TestCase):
    """Tabs before they are in a window, and in too little room."""

    def setUp(self) -> None:
        self.tabs = Tabs(0, 0, 30, 6)
        self.tabs.add_page("&General")
        self.tabs.add_page("&Advanced")
        self.tabs.add_page("&Colours")

    def test_without_a_window(self) -> None:
        """Pages are chosen; a letter of no page chooses none."""
        self.tabs.select(1)
        self.tabs.activate_mnemonic("z")
        self.assertEqual(self.tabs.value, 1)

    def test_too_narrow(self) -> None:
        """Tabs that do not fit are cut off, the chosen one too."""
        for width in (3, 10, 12, 21):
            for chosen in range(3):
                with self.subTest(width=width, chosen=chosen):
                    self.tabs.select(chosen)
                    self.tabs.rect = Rect(0, 0, 6, width)
                    canvas = paint(self.tabs, width, 6)
                    self.assertEqual(len(canvas.text(1)), width)

    def test_mouse(self) -> None:
        """Only the left button, and only on the tabs' row."""
        self.assertFalse(self.tabs.handle_mouse(mouse("press", 0, 3, "right"), 0, 3))
        self.assertFalse(self.tabs.handle_mouse(mouse("press", 3, 3), 3, 3))


class TextAreaTests(unittest.TestCase):
    """A text area's corners."""

    def test_inserting_nothing(self) -> None:
        """Nothing, with nothing selected, changes nothing."""
        self.assertFalse(TextArea(0, 0, 10, 3, text="ab").insert(""))

    def test_a_new_tab_size(self) -> None:
        """Lines are measured again."""
        area = TextArea(0, 0, 10, 3, text="\tab")
        window(area)
        area.tab_size = 2
        area.fit()
        self.assertEqual(area._widths_tab_size, 2)

    def test_without_a_window(self) -> None:
        """Drawn as far as it reaches."""
        canvas = paint(TextArea(0, 0, 10, 2, text="one\ntwo"), 10, 2)
        self.assertEqual(canvas.text(0)[:3], "one")

    def test_the_cursor_under_the_numbers(self) -> None:
        """The cursor under the line numbers."""
        area = TextArea(0, 0, 60, 3, text="x" * 80, line_numbers=True)
        holder = window(area, height=6, width=20)
        area.cursor = (0, 0)
        holder.scroll_to(0, 20)
        canvas = Canvas(holder.rect.right, holder.rect.bottom)
        holder.paint(canvas, active=True)
        self.assertIsNone(canvas.cursor)

    def test_next_among_others(self) -> None:
        """With another widget to go to, the hints offer Next."""
        area = TextArea(0, 0, 10, 3)
        window(area, TextBox(5, 0, 10))
        labels = [label for _, label in area.key_help(KEYS)]
        self.assertIn("Next", labels)


class TextBoxTests(unittest.TestCase):
    """A text box's corners."""

    def test_undo_tells(self) -> None:
        """Undo calls ``on_change``."""
        changes: list[str] = []
        box = TextBox(0, 0, 10, on_change=lambda b: changes.append(b.text))
        box.handle_key("a", KEYS)
        box.handle_key("ctrl+z", KEYS)
        self.assertEqual(changes, ["a", ""])

    def test_a_selection_scrolled_away(self) -> None:
        """Not drawn, if none of it shows."""
        box = TextBox(0, 0, 6, text="abcdefghijklmnop")
        box.cursor = len(box.text)
        first = box.first_visible
        box._cursor, box._anchor = first, 0  # selected up to the first shown
        canvas = paint(box, 6, 1, focused=True)
        self.assertEqual(canvas.cell(0, 1)[1], box.focused_style)

    def test_mouse(self) -> None:
        """Mouse use."""
        box = TextBox(0, 0, 6, text="abc")
        self.assertFalse(box.handle_mouse(mouse("move", 0, 1, "none"), 0, 1))
        self.assertFalse(box.handle_mouse(mouse("move", 0, 1), 0, 1))
        box.on_timer(0.0)


class TreeViewTests(unittest.TestCase):
    """Trees' corners."""

    def setUp(self) -> None:
        self.leaf = TreeNode("leaf")
        self.empty = TreeNode("empty", expanded=True)
        self.root = TreeNode("root", [self.leaf, self.empty], expanded=True)
        self.tree = TreeView([self.root], 0, 0, 20, 3)

    def test_select_what_shows(self) -> None:
        """Selecting an item already showing opens nothing."""
        self.tree.select(self.leaf)
        self.assertIs(self.tree.selected_node, self.leaf)

    def test_select_what_is_not_there(self) -> None:
        """An item of another tree is not highlighted."""
        self.tree.select(TreeNode("stranger"))
        self.assertIs(self.tree.selected_node, self.root)

    def test_expand_without_on_expand(self) -> None:
        """Expanded, telling no one."""
        closed = TreeNode("closed", [TreeNode("inside")])
        tree = TreeView([closed], 0, 0, 20, 3)
        tree.expand(closed)
        self.assertTrue(closed.expanded)

    def test_a_scroll_bar(self) -> None:
        """Drawn when the items do not fit."""
        nodes = [TreeNode(f"item {n}") for n in range(10)]
        tree = TreeView(nodes, 0, 0, 20, 3)
        window(tree)
        canvas = paint(tree, 20, 3)
        self.assertNotEqual(canvas.text(0)[-1], " ")

    def test_keys_with_nowhere_to_go(self) -> None:
        """Keys with nowhere to go."""
        self.tree.select(self.empty)
        self.assertTrue(self.tree.handle_key("right", KEYS))
        self.assertIs(self.tree.selected_node, self.empty)
        tree = TreeView([TreeNode("top")], 0, 0, 20, 3)
        self.assertTrue(tree.handle_key("left", KEYS))

    def test_a_press_below_the_items(self) -> None:
        """Highlights nothing new."""
        tree = TreeView([TreeNode("only")], 0, 0, 20, 3)
        tree.handle_mouse(mouse("press", 2, 0), 2, 0)
        self.assertEqual(tree.cursor, 0)


if __name__ == "__main__":
    unittest.main()
