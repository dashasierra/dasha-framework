"""Tests for tree views: outlines of items that open and close."""

import unittest

from dasha.canvas import Canvas
from dasha.events import MouseEvent
from dasha.scrollbar import DOWN, RIGHT
from dasha.shortcuts import Shortcuts
from dasha.widgets import TreeNode, TreeView


def outline() -> list[TreeNode]:
    """A sample outline with lazy loading."""
    return [
        TreeNode(
            "src",
            [
                TreeNode("dasha", [TreeNode("widgets"), TreeNode("apps")]),
                TreeNode("README.md"),
            ],
            expanded=True,
        ),
        TreeNode(
            "tests", load=lambda node: [TreeNode("test_a.py"), TreeNode("test_b.py")]
        ),
    ]


def drawn(tree: TreeView) -> list[str]:
    """The rows as drawn, trimmed.

    :param tree: The tree view.
    """
    canvas = Canvas(tree.rect.width, tree.rect.height)
    tree.paint(canvas, canvas.bounds, True)
    return [canvas.text(row).rstrip() for row in range(tree.rect.height)]


class TreeTests(unittest.TestCase):
    """A tree of the outline, 24 wide and 8 tall."""

    def setUp(self) -> None:
        self.changes: list[str] = []
        self.opened: list[str] = []
        self.chosen: list[str] = []
        self.tree = TreeView(
            outline(),
            0,
            0,
            24,
            8,
            on_change=lambda t: self.changes.append(
                t.selected_node.label if t.selected_node else ""
            ),
            on_expand=lambda t, node: self.opened.append(node.label),
        )

    def keys(self, *names: str) -> None:
        """Send keys to the tree.

        :param names: The keys.
        """
        for name in names:
            self.tree.handle_key(name, Shortcuts())

    def test_drawn(self) -> None:
        """Drawn."""
        self.assertEqual(
            drawn(self.tree)[:4],
            [f"{DOWN} src", f"├─{RIGHT} dasha", "└─  README.md", f"{RIGHT} tests"],
        )
        canvas = Canvas(24, 8)
        self.tree.paint(canvas, canvas.bounds, True)
        self.assertEqual(canvas.cell(1, 0)[1], TreeView.lines_style)
        self.assertEqual(canvas.cell(0, 0)[1], TreeView.focused_style)

    def test_right_opens_then_goes_in(self) -> None:
        """Right opens, then goes in."""
        self.keys("down", "right")
        self.assertEqual(drawn(self.tree)[2], "│ ├─  widgets")
        self.assertEqual(self.opened, ["dasha"])
        self.keys("right")
        self.assertEqual(
            self.tree.selected_node.label if self.tree.selected_node else "", "widgets"
        )
        self.assertEqual(
            self.tree.selected_node.path if self.tree.selected_node else [],
            ["src", "dasha", "widgets"],
        )

    def test_left_goes_out_then_closes(self) -> None:
        """Left goes out, then closes."""
        self.keys("down", "down")  # README.md
        self.keys("left")
        self.assertEqual(self.tree.value, self.tree.roots[0])
        self.keys("left")
        self.assertEqual(drawn(self.tree)[:2], [f"{RIGHT} src", f"{RIGHT} tests"])

    def test_closing_moves_the_highlight_out(self) -> None:
        """Closing moves the highlight out."""
        self.keys("down", "down")  # README.md
        self.tree.collapse(self.tree.roots[0])
        self.assertEqual(self.tree.value, self.tree.roots[0])

    def test_loaded_when_first_opened(self) -> None:
        """tests finds its items as it first opens, once."""
        tests = self.tree.roots[1]
        self.assertTrue(tests.has_children)
        self.tree.expand(tests)
        self.assertEqual(
            [child.label for child in tests.children], ["test_a.py", "test_b.py"]
        )
        self.tree.collapse(tests)
        self.tree.expand(tests)
        self.assertEqual(len(tests.children), 2)

    def test_typing_finds_an_item(self) -> None:
        """A letter goes to the next showing item starting with it."""
        self.keys("t")
        self.assertEqual(self.tree.value, self.tree.roots[1])

    def test_enter(self) -> None:
        """Enter."""
        self.keys("down", "enter")
        self.assertTrue(self.tree.roots[0].children[0].expanded)
        self.keys("enter")
        self.assertFalse(self.tree.roots[0].children[0].expanded)
        self.keys("end")
        self.tree.move_to(2)  # README.md, a leaf
        self.assertFalse(self.tree.handle_key("enter", Shortcuts()))
        self.tree.on_choose = lambda _: self.chosen.append(
            self.tree.selected_node.label if self.tree.selected_node else ""
        )
        self.keys("enter")
        self.assertEqual(self.chosen, ["README.md"])

    def test_clicks(self) -> None:
        """Clicks."""
        self.tree.handle_mouse(MouseEvent("press", "left", 1, 2), 1, 2)  # ►
        self.assertTrue(self.tree.roots[0].children[0].expanded)
        self.tree.handle_mouse(MouseEvent("press", "left", 5, 3), 5, 3)
        self.assertEqual(self.tree.value, self.tree.roots[1])
        self.tree.handle_mouse(MouseEvent("press", "left", 5, 3, clicks=2), 5, 3)
        self.assertTrue(self.tree.roots[1].expanded)

    def test_select_opens_the_way(self) -> None:
        """Selecting an item inside closed ones opens them so it shows."""
        tree = TreeView(outline(), 0, 0, 24, 8)
        tree.collapse(tree.roots[0])
        widgets = tree.roots[0].children[0].children[0]
        tree.select(widgets)
        self.assertEqual(tree.value, widgets)
        self.assertEqual(repr(widgets), "TreeNode('widgets')")
        self.assertEqual(widgets.depth, 2)

    def test_refresh_after_changes(self) -> None:
        """Items added from code show once refreshed."""
        self.tree.roots[0].add(TreeNode("setup.py"))
        self.tree.refresh()
        self.assertIn("└─  setup.py", drawn(self.tree))

    def test_empty(self) -> None:
        """No items: nothing highlighted, keys do nothing."""
        tree = TreeView([], 0, 0, 10, 3)
        self.assertIsNone(tree.value)
        tree.expand()
        tree.collapse()
        self.assertFalse(tree.handle_key("right", Shortcuts()))

    def test_single_selection(self) -> None:
        """Single selection."""
        self.keys("down", "down")
        self.assertEqual(self.tree.selected_nodes, [self.tree.roots[0].children[1]])
        self.assertEqual(self.changes, ["dasha", "README.md"])
        self.keys(" ")  # Space selects nothing more
        self.assertEqual(len(self.tree.selected_nodes), 1)
        self.tree.set_selected_nodes(self.tree.roots)  # only for multiple
        self.assertEqual(self.tree.value, self.tree.roots[0].children[1])

    def test_selected_at_the_start(self) -> None:
        """Selected at the start."""
        roots = outline()
        dasha = roots[0].children[0]
        widgets = dasha.children[0]
        roots[0].expanded = False
        changes: list[TreeView] = []
        tree = TreeView(roots, 0, 0, 24, 8, selected=widgets, on_change=changes.append)
        self.assertEqual(tree.value, widgets)
        self.assertTrue(roots[0].expanded and dasha.expanded)
        self.assertEqual(changes, [])

    def test_remapped_keys(self) -> None:
        """Expanding, collapsing and choosing follow the shortcuts."""
        shortcuts = Shortcuts(
            {"tree_expand": ["ctrl+right"], "tree_collapse": ["ctrl+left"]}
        )
        self.tree.move_to(1)  # dasha
        self.assertFalse(self.tree.handle_key("right", shortcuts))
        self.assertFalse(self.tree.roots[0].children[0].expanded)
        self.assertTrue(self.tree.handle_key("ctrl+right", shortcuts))
        self.assertTrue(self.tree.roots[0].children[0].expanded)
        self.assertTrue(self.tree.handle_key("ctrl+left", shortcuts))
        self.assertFalse(self.tree.roots[0].children[0].expanded)

    def test_lazy_loading_waits(self) -> None:
        """Lazy loading waits."""
        calls: list[TreeNode] = []

        def load(node: TreeNode) -> list[TreeNode]:
            calls.append(node)
            return []

        empty = TreeNode("empty", load=load)
        tree = TreeView([empty, TreeNode("other")], 0, 0, 12, 3)
        tree.handle_key("down", Shortcuts())
        tree.handle_key("up", Shortcuts())
        self.assertEqual(calls, [])
        self.assertEqual(drawn(tree)[0], f"{RIGHT} empty")
        tree.handle_key("right", Shortcuts())
        self.assertEqual(calls, [empty])
        self.assertEqual(drawn(tree)[0], "  empty")
        self.assertFalse(empty.has_children)

    def test_scrolls_to_the_highlight(self) -> None:
        """Scrolls to the highlight."""
        tree = TreeView([TreeNode(f"item {n}") for n in range(10)], 0, 0, 12, 3)
        tree.handle_key("end", Shortcuts())
        self.assertEqual(tree.first_visible, 7)
        self.assertEqual(drawn(tree)[2][:8], "  item 9")
        self.assertEqual(len(drawn(tree)[0]), 12)  # the scroll bar

    def test_unfocused_highlight(self) -> None:
        """The unfocused highlight."""
        canvas = Canvas(24, 8)
        self.tree.move_to(1)
        self.tree.paint(canvas, canvas.bounds, False)
        self.assertEqual(canvas.cell(1, 0)[1], TreeView.selected_style)
        self.assertEqual(canvas.cell(1, 4)[1], TreeView.selected_style)
        self.assertEqual(canvas.cell(2, 0)[1], TreeView.lines_style)
        self.assertEqual(canvas.cell(2, 4)[1], TreeView.style)


class MultipleSelectionTests(unittest.TestCase):
    """A tree of the outline with multiple selection."""

    def setUp(self) -> None:
        self.changes: list[list[str]] = []
        self.tree = TreeView(
            outline(),
            0,
            0,
            24,
            8,
            multiple=True,
            on_change=lambda t: self.changes.append(
                [node.label for node in t.selected_nodes]
            ),
        )

    def keys(self, *names: str) -> None:
        """Send keys to the tree.

        :param names: The keys.
        """
        for name in names:
            self.tree.handle_key(name, Shortcuts())

    def labels(self) -> list[str]:
        """The selected items' labels."""
        return [node.label for node in self.tree.selected_nodes]

    def test_moving_selects_nothing(self) -> None:
        """Moving only moves the highlight."""
        self.keys("down", "down")
        self.assertEqual(self.tree.value, ())
        self.assertEqual(self.changes, [])
        self.assertEqual(self.tree.selected_node, self.tree.roots[0].children[1])

    def test_space_toggles(self) -> None:
        """Space toggles."""
        self.keys("end", " ", "home", " ")
        self.assertEqual(self.labels(), ["src", "tests"])
        self.assertEqual(self.tree.value, (self.tree.roots[0], self.tree.roots[1]))
        self.keys(" ")
        self.assertEqual(self.labels(), ["tests"])
        self.assertEqual(self.changes, [["tests"], ["src", "tests"], ["tests"]])

    def test_kept_while_collapsed(self) -> None:
        """Kept while collapsed."""
        self.keys("down", "right", "down", " ")  # widgets
        self.assertEqual(self.labels(), ["widgets"])
        self.tree.collapse(self.tree.roots[0])
        self.assertEqual(self.labels(), ["widgets"])
        self.assertEqual(self.tree.selected, set())  # not showing
        self.keys("down", " ")  # tests, now in row 1
        self.assertEqual(self.labels(), ["widgets", "tests"])
        self.tree.expand(self.tree.roots[0])
        self.assertEqual(self.tree.selected, {2, 5})
        drawn_rows = drawn(self.tree)
        self.assertEqual(drawn_rows[5], f"{RIGHT} tests")

    def test_select_all(self) -> None:
        """Ctrl+A selects every item showing; again, deselects them."""
        self.keys("ctrl+a")
        self.assertEqual(self.labels(), ["src", "dasha", "README.md", "tests"])
        self.keys("ctrl+a")
        self.assertEqual(self.labels(), [])

    def test_clicks(self) -> None:
        """Clicks with multiple selection."""
        self.tree.handle_mouse(MouseEvent("press", "left", 0, 3), 0, 3)  # src
        self.assertEqual(self.labels(), ["src"])
        self.tree.handle_mouse(MouseEvent("press", "left", 1, 2), 1, 2)  # ►
        self.assertTrue(self.tree.roots[0].children[0].expanded)
        self.assertEqual(self.labels(), ["src"])
        self.tree.handle_mouse(
            MouseEvent("press", "left", 3, 6, shift=True), 3, 6
        )  # apps
        self.assertEqual(self.labels(), ["src", "dasha", "widgets", "apps"])
        self.tree.handle_mouse(MouseEvent("press", "left", 2, 6), 2, 6)
        self.assertEqual(self.labels(), ["src", "dasha", "apps"])

    def test_set_selected_nodes(self) -> None:
        """``set_selected_nodes``."""
        widgets = self.tree.roots[0].children[0].children[0]
        self.tree.set_selected_nodes([widgets, self.tree.roots[1]])
        self.assertEqual(self.labels(), ["widgets", "tests"])
        self.assertEqual(self.tree.selected, {3})
        self.tree.set_selected_nodes([self.tree.roots[1], widgets])
        self.assertEqual(len(self.changes), 1)

    def test_selected_at_the_start(self) -> None:
        """selected= picks the items selected to begin with."""
        roots = outline()
        tree = TreeView(roots, 0, 0, 24, 8, multiple=True, selected=roots)
        self.assertEqual(tree.value, tuple(roots))
        self.assertEqual(tree.selected, {0, 3})

    def test_drawn(self) -> None:
        """Drawn with multiple selection."""
        self.keys(" ", "down", "down", "down", " ", "up")
        canvas = Canvas(24, 8)
        self.tree.paint(canvas, canvas.bounds, True)
        self.assertEqual(canvas.cell(0, 2)[1], TreeView.selected_style)
        self.assertEqual(canvas.cell(3, 2)[1], TreeView.selected_style)
        self.assertEqual(canvas.cell(2, 4)[1], TreeView.focused_style)
        self.assertEqual(canvas.cell(1, 4)[1], TreeView.style)
        self.keys("down")
        self.tree.paint(canvas, canvas.bounds, True)
        style = canvas.cell(3, 2)[1]
        self.assertEqual(style.foreground, TreeView.selected_style.foreground)
        self.assertEqual(style.background, TreeView.focused_style.background)


if __name__ == "__main__":
    unittest.main()
