"""Tests for the keys each widget lists on the status bar: those that do
something particular to it, and never those that only edit text, which still
work."""

import unittest

import dasha.widgets
from dasha.canvas import Rect
from dasha.client import ClientManager
from dasha.shortcuts import Shortcuts
from dasha.widgets import (
    AutoCompleteBox,
    Button,
    CheckBoxes,
    Cluster,
    Collapsible,
    Column,
    ColumnBar,
    ComboBox,
    GroupBox,
    Label,
    ListBox,
    Paragraph,
    PasswordBox,
    ProgressBar,
    RadioButtons,
    ScrollBar,
    Slider,
    SpinBox,
    Splitter,
    Switch,
    Table,
    Tabs,
    TerminalView,
    TextArea,
    TextBox,
    TreeNode,
    TreeView,
    Widget,
)
from dasha.window import Window
from tests.hosted_apps import Hello
from tests.support import pipe
from tests.test_hosting import WELCOME, drain, of_type

KEYS = Shortcuts()

EDITING = (
    "text_cut",
    "text_copy",
    "text_paste",
    "text_select_all",
    "text_undo",
    "text_redo",
    "text_clear",
    "area_delete_line",
)
"""The actions that only edit text, so that no hint shows them."""

STEP = ("Up/Down", "Step")

WIDGETS: list[tuple[Widget, list[tuple[str, str]]]] = [
    (TextBox(0, 0, 10), []),
    (PasswordBox(0, 0, 10), []),
    (AutoCompleteBox(0, 0, 10), []),
    (TextArea(0, 0, 10, 3), []),
    (SpinBox(0, 0, 8, minimum=0, maximum=9), [STEP]),
    (ComboBox(["a"], 0, 0, 10), []),
    (ListBox(["a"], 0, 0, 10, 3), []),
    (Table([Column("A", 5)], 0, 0, 10, 3), []),
    (TreeView([TreeNode("a")], 0, 0, 10, 3), []),
    (TerminalView(0, 0, 10, 3), []),
    (Button("OK", 0, 0), []),
    (CheckBoxes(["a"], 0, 0), []),
    (RadioButtons(["a"], 0, 0), []),
    (Cluster(["a"], 0, 0), []),
    (Collapsible("a", 0, 0), []),
    (GroupBox("a", 0, 0, 10, 3), []),
    (Label("a", 0, 0), []),
    (Paragraph("a", 0, 0, 10), []),
    (ProgressBar(0, 0, 10), []),
    (ColumnBar(0, 0, 10), []),
    (ScrollBar(0, 0, 10), []),
    (Slider(0, 0, 10), []),
    (Splitter(0, 0, 10, 3), []),
    (Switch("a", 0, 0), []),
    (Tabs(0, 0, 10, 3), []),
]


class WidgetHintTests(unittest.TestCase):
    """What each widget offers the status bar."""

    def test_each_widgets_hints(self) -> None:
        """Exactly the keys that do more than edit text."""
        for widget, hints in WIDGETS:
            with self.subTest(type(widget).__name__):
                self.assertEqual(widget.key_help(KEYS), hints)

    def test_no_editing_keys(self) -> None:
        """Bound to keys of their own, those keys are still never listed."""
        shortcuts = Shortcuts({action: ["f12"] for action in EDITING})
        for widget, _ in WIDGETS:
            with self.subTest(type(widget).__name__):
                keys = [key for key, _ in widget.key_help(shortcuts)]
                self.assertNotIn("F12", keys)

    def test_every_widget_is_here(self) -> None:
        """A new widget gets its hints decided, too."""
        tested = {type(widget) for widget, _ in WIDGETS}
        for name in dasha.widgets.__all__:
            kind = getattr(dasha.widgets, name)
            if isinstance(kind, type) and issubclass(kind, Widget):
                if kind is not Widget:
                    self.assertIn(kind, tested, name)

    def test_next_needs_somewhere_to_go(self) -> None:
        """A text area offers its way out only with another widget to go to,
        since Tab types a tab in it."""
        window = Window("E", Rect(1, 0, 10, 40))
        area = window.add(TextArea(0, 0, 10, 3))
        self.assertNotIn(("Ctrl+Tab", "Next"), area.key_help(KEYS))
        window.add(TextBox(5, 0, 10))
        self.assertIn(("Ctrl+Tab", "Next"), area.key_help(KEYS))

    def test_hints_follow_the_bindings(self) -> None:
        """Remapped, the key shown is the new one; with no keys, no hint."""
        window = Window("E", Rect(1, 0, 10, 40))
        area = window.add(TextArea(0, 0, 10, 3))
        window.add(TextBox(5, 0, 10))
        remapped = Shortcuts({"area_next_widget": ["alt+n"]})
        self.assertEqual(area.key_help(remapped), [("Alt+N", "Next")])
        # The way back stays bound, as a text area must keep a way out.
        unbound = Shortcuts({"area_next_widget": []})
        self.assertEqual(area.key_help(unbound), [])


class EditingKeysStillWorkTests(unittest.TestCase):
    """The keys left off the status bar work as ever, and can be remapped."""

    def test_in_a_text_box(self) -> None:
        """Select all, cut, paste, undo and redo, by their default keys."""
        box = TextBox(0, 0, 20, text="hello")
        box.handle_key("ctrl+a", KEYS)
        self.assertEqual(box.selection, (0, 5))
        box.handle_key("ctrl+x", KEYS)
        self.assertEqual(box.text, "")
        box.handle_key("ctrl+v", KEYS)
        self.assertEqual(box.text, "hello")
        box.handle_key("ctrl+z", KEYS)
        self.assertEqual(box.text, "")
        box.handle_key("alt+z", KEYS)
        self.assertEqual(box.text, "hello")

    def test_clear_and_delete_line(self) -> None:
        """Ctrl+Y empties a text box, and deletes a text area's line."""
        box = TextBox(0, 0, 20, text="hello")
        box.handle_key("ctrl+y", KEYS)
        self.assertEqual(box.text, "")
        area = TextArea(0, 0, 20, 3, text="one\ntwo")
        area.handle_key("ctrl+y", KEYS)
        self.assertEqual(area.text, "two")

    def test_remapped(self) -> None:
        """Undo on a key of the user's own, in a text area."""
        shortcuts = Shortcuts({"text_undo": ["alt+backspace"]})
        area = TextArea(0, 0, 20, 3)
        area.handle_key("a", shortcuts)
        area.handle_key("alt+backspace", shortcuts)
        self.assertEqual(area.text, "")


class HostedHintTests(unittest.TestCase):
    """An application in a process of its own sends the same hints."""

    def sent_hints(self, widget: Widget) -> list[tuple[str, ...]]:
        """The hints sent to the desktop while ``widget`` has the focus."""
        desktop, app_end = pipe()
        manager = ClientManager(app_end, WELCOME)
        self.addCleanup(manager.stop_listening)
        window = manager.launch(Hello).windows[0]
        window.add(widget)
        window.focus(widget)
        manager.flush()
        (sent,) = of_type(drain(desktop), "window")
        return [tuple(hint) for hint in sent["hints"]]

    def test_a_text_box_sends_none(self) -> None:
        """Its editing keys do not reach the desktop's status bar."""
        self.assertEqual(self.sent_hints(TextBox(0, 0, 10)), [])

    def test_a_spin_box_sends_its_step(self) -> None:
        """A key that does more than edit text does."""
        box = SpinBox(0, 0, 8, minimum=0, maximum=9)
        self.assertEqual(self.sent_hints(box), [STEP])


if __name__ == "__main__":
    unittest.main()
