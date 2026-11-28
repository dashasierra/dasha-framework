"""Tree views."""

# A tree view and a table are both list boxes underneath, and hand their
# options on to it alike.
# pylint: disable=duplicate-code

from collections.abc import Callable, Iterable
from typing import Any

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.scrollbar import DOWN, RIGHT
from dasha.shortcuts import Shortcuts
from dasha.style import BLACK, BLUE, BRIGHT_WHITE, BRIGHT_YELLOW, CYAN, Style
from dasha.widgets.listbox import ListBox

BRANCH = "\N{BOX DRAWINGS LIGHT VERTICAL AND RIGHT}\N{BOX DRAWINGS LIGHT HORIZONTAL}"
LAST = "\N{BOX DRAWINGS LIGHT UP AND RIGHT}\N{BOX DRAWINGS LIGHT HORIZONTAL}"
GOING_ON = "\N{BOX DRAWINGS LIGHT VERTICAL} "
"""Tree line characters."""


class TreeNode:
    """One item of a tree, with its children.

    :param label: Item text.
    :param children: Items below it.
    :param expanded: Whether it starts expanded.
    :param data: Anything to keep with the item.
    :param load: Returns the children on first expansion, if given.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        label: str,
        children: Iterable["TreeNode"] = (),
        *,
        expanded: bool = False,
        data: Any = None,
        load: Callable[["TreeNode"], Iterable["TreeNode"]] | None = None,
    ) -> None:
        self.label = label
        self.data = data
        self.load = load
        self.parent: TreeNode | None = None
        """The item it is under (``None`` at the top)."""
        self.children: list[TreeNode] = []
        self.expanded = expanded
        """Whether the items under it show."""
        for child in children:
            self.add(child)

    def add(self, child: "TreeNode") -> "TreeNode":
        """Add a child and return it.

        :param child: The child item.
        """
        child.parent = self
        self.children.append(child)
        return child

    @property
    def has_children(self) -> bool:
        """Whether the item has or may have children."""
        return bool(self.children) or self.load is not None

    def loaded(self) -> None:
        """Find the item's children, if ``load`` has not been called yet."""
        if self.load is not None:
            load, self.load = self.load, None
            for child in load(self):
                self.add(child)

    @property
    def depth(self) -> int:
        """How many levels of items this item is below."""
        depth, node = 0, self.parent
        while node is not None:
            depth, node = depth + 1, node.parent
        return depth

    @property
    def path(self) -> list[str]:
        """The labels of the items from the top down to this one."""
        labels: list[str] = []
        node: TreeNode | None = self
        while node is not None:
            labels.append(node.label)
            node = node.parent
        return labels[::-1]

    def __repr__(self) -> str:
        return f"TreeNode({self.label!r})"


class TreeView(ListBox):  # pylint: disable=too-many-instance-attributes
    """An expandable outline of items.

    :param roots: Top-level items.
    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param height: Height in rows.
    :param multiple: Whether several items can be selected.
    :param selected: Initially selected item or items.
    :param on_change: Called with the tree when the selection changes.
    :param on_choose: Called with the tree when an item is chosen.
    :param on_expand: Called with the tree and item when expanded.
    :param name: Widget name.
    :param status: Status bar text.
    """

    style: Style = Style(foreground=BLACK, background=CYAN)
    """The style of the items."""
    focused_style: Style = Style(foreground=BRIGHT_WHITE, background=BLUE, bold=True)
    """Highlighted item style while focused."""
    selected_style: Style = Style(foreground=BRIGHT_YELLOW, background=CYAN, bold=True)
    """Selected item style."""
    lines_style: Style = Style(foreground=BLUE, background=CYAN)
    """The style of the lines joining the items."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        roots: Iterable[TreeNode],
        row: int,
        column: int,
        width: int,
        height: int,
        *,
        multiple: bool = False,
        selected: TreeNode | Iterable[TreeNode] | None = None,
        on_change: Callable[["TreeView"], object] | None = None,
        on_choose: Callable[["TreeView"], object] | None = None,
        on_expand: Callable[["TreeView", TreeNode], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        self.roots: list[TreeNode] = list(roots)
        self.on_expand = on_expand
        self.visible_nodes: list[TreeNode] = []
        """The items showing (those under closed items are not), in order."""
        self._selected_nodes: set[TreeNode] = set()  # with multiple selection
        super().__init__(
            [],
            row,
            column,
            width,
            height,
            multiple=multiple,
            on_change=on_change,  # type: ignore[arg-type]
            on_choose=on_choose,  # type: ignore[arg-type]
            name=name,
            status=status,
        )
        if isinstance(selected, TreeNode):
            self._reveal(selected)
        elif multiple and selected is not None:
            self._selected_nodes = set(selected)
        self.refresh()
        if isinstance(selected, TreeNode) and selected in self.visible_nodes:
            self.cursor = self.visible_nodes.index(selected)
            self._scroll_to_cursor()

    # The items showing

    def refresh(self) -> None:
        """Recompute the visible items."""
        current = self.selected_node
        shown: list[TreeNode] = []

        def walk(nodes: list[TreeNode]) -> None:
            for node in nodes:
                shown.append(node)
                if node.expanded:
                    node.loaded()
                    walk(node.children)

        walk(self.roots)
        self.visible_nodes = shown
        self.set_items(node.label for node in shown)
        if self.multiple:
            self.selected = {
                index
                for index, node in enumerate(shown)
                if node in self._selected_nodes
            }
            self._anchor = min(self._anchor, max(0, len(shown) - 1))
        if current in shown:
            assert current is not None
            self.cursor = shown.index(current)
            self._scroll_to_cursor()

    @property
    def selected_node(self) -> TreeNode | None:
        """The highlighted item."""
        return self.visible_nodes[self.cursor] if self.visible_nodes else None

    @property
    def value(self) -> TreeNode | None | tuple[TreeNode, ...]:  # type: ignore[override]
        if self.multiple:
            return tuple(self.selected_nodes)
        return self.selected_node

    @property
    def selected_nodes(self) -> list[TreeNode]:
        """The selected items."""
        if not self.multiple:
            node = self.selected_node
            return [node] if node is not None else []
        found: list[TreeNode] = []

        def walk(nodes: list[TreeNode]) -> None:
            for node in nodes:
                if node in self._selected_nodes:
                    found.append(node)
                walk(node.children)

        walk(self.roots)
        return found

    def set_selected_nodes(self, nodes: Iterable[TreeNode]) -> None:
        """Select other items.

        :param nodes: The items.
        """
        if not self.multiple:
            return
        chosen = set(nodes)
        if chosen != self._selected_nodes:
            self._selected_nodes = chosen
            self.refresh()
            self._changed()

    def _changed(self) -> None:
        """Sync selection with the visible items."""
        if self.multiple:
            shown = set(self.visible_nodes)
            self._selected_nodes = {
                node for node in self._selected_nodes if node not in shown
            } | {self.visible_nodes[index] for index in self.selected}
        super()._changed()

    def _reveal(self, node: TreeNode) -> bool:
        """Expand an item's ancestors; return whether any were collapsed.

        :param node: The item.
        """
        parent = node.parent
        opened = False
        while parent is not None:
            if not parent.expanded:
                parent.expanded, opened = True, True
            parent = parent.parent
        return opened

    def select(self, node: TreeNode) -> None:
        """Highlight an item, expanding its ancestors.

        :param node: The item.
        """
        if self._reveal(node):
            self.refresh()
        if node in self.visible_nodes:
            self.move_to(self.visible_nodes.index(node))

    def expand(self, node: TreeNode | None = None) -> None:
        """Expand an item.

        :param node: The item, or ``None`` for the highlighted one.
        """
        node = node if node is not None else self.selected_node
        if node is None or node.expanded or not node.has_children:
            return
        node.expanded = True
        node.loaded()
        self.refresh()
        if self.on_expand is not None:
            self.on_expand(self, node)

    def collapse(self, node: TreeNode | None = None) -> None:
        """Collapse an item.

        :param node: The item, or ``None`` for the highlighted one.
        """
        node = node if node is not None else self.selected_node
        if node is None or not node.expanded:
            return
        node.expanded = False
        current = self.selected_node
        while current is not None and current is not node:
            current = current.parent
        self.refresh()
        if current is node:
            self.move_to(self.visible_nodes.index(node))

    def toggle_node(self, node: TreeNode) -> None:
        """Expand or collapse an item.

        :param node: The item.
        """
        if node.expanded:
            self.collapse(node)
        else:
            self.expand(node)

    def choose(self) -> None:
        """Choose the highlighted item, as Enter does."""
        node = self.selected_node
        if self.on_choose is not None or node is None or not node.has_children:
            super().choose()
        else:
            self.toggle_node(node)

    # Drawing

    def _lines(self, node: TreeNode) -> str:
        """The outline lines before an item.

        :param node: The item.
        """
        if node.parent is None:
            return ""
        parts: list[str] = []
        above = node.parent
        while above.parent is not None:
            siblings = above.parent.children
            parts.append(GOING_ON if siblings[-1] is not above else "  ")
            above = above.parent
        last = node.parent.children[-1] is node
        return "".join(reversed(parts)) + (LAST if last else BRANCH)

    @staticmethod
    def _marker(node: TreeNode) -> str:
        if not node.has_children:
            return " "
        return DOWN if node.expanded else RIGHT

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        top, left = origin.row + self.rect.row, origin.column + self.rect.column
        width = self._column_widths()[0]
        for offset in range(self.rows):
            index = self._first + offset
            row = top + offset
            if not self._valid(index):
                canvas.write(row, left, " " * width, self.style, clip=origin)
                continue
            node = self.visible_nodes[index]
            style = self._item_style(index, focused)
            lines = self._lines(node)
            highlighted = style != self.style
            canvas.write(
                row,
                left,
                lines[:width],
                style if highlighted else self.lines_style,
                clip=origin,
            )
            rest = f"{self._marker(node)} {node.label}"[: max(0, width - len(lines))]
            canvas.write(
                row,
                left + len(lines),
                rest.ljust(max(0, width - len(lines))),
                style,
                clip=origin,
            )
        if self._needs_bar():
            self._sync_bar()
            self.scroll_bar.paint(canvas, origin, False)

    # Input

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Expand, collapse or choose with the keys.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        node = self.selected_node
        if node is not None:
            if shortcuts.matches("tree_expand", key):
                if node.has_children and not node.expanded:
                    self.expand(node)
                elif node.expanded and node.children:
                    self.move_to(self.cursor + 1)
                return True
            if shortcuts.matches("tree_collapse", key):
                if node.expanded:
                    self.collapse(node)
                elif node.parent is not None:
                    self.move_to(self.visible_nodes.index(node.parent))
                return True
            if shortcuts.matches("tree_choose", key) and (
                self.on_choose is not None or node.has_children
            ):
                self.choose()
                return True
        return super().handle_key(key, shortcuts)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Expand, collapse or select with the mouse.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        if event.button == "left" and event.action == "press" and event.clicks < 2:
            index = self.index_at(row - self.rect.row, column - self.rect.column)
            if index is not None:
                node = self.visible_nodes[index]
                marker = len(self._lines(node))
                if node.has_children and column - self.rect.column == marker:
                    self.move_to(index)
                    self.toggle_node(node)
                    return True
        return super().handle_mouse(event, row, column)
