"""Tree views: an outline of items that can be expanded to show the items
below them, as folders can."""

# A tree view and a table are both list boxes underneath, and hand their
# options on to it alike.
# pylint: disable=duplicate-code

from collections.abc import Callable, Iterable
from typing import Any

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.scrollbar import DOWN, RIGHT
from dasha.shortcuts import Shortcuts
from dasha.style import BLACK, BLUE, BRIGHT_WHITE, BRIGHT_YELLOW, CYAN, GREEN, Style
from dasha.widgets.listbox import ListBox

BRANCH = "\N{BOX DRAWINGS LIGHT VERTICAL AND RIGHT}\N{BOX DRAWINGS LIGHT HORIZONTAL}"
LAST = "\N{BOX DRAWINGS LIGHT UP AND RIGHT}\N{BOX DRAWINGS LIGHT HORIZONTAL}"
GOING_ON = "\N{BOX DRAWINGS LIGHT VERTICAL} "
"""``├─`` before an item with more items after it, ``└─`` before the last
item, and ``"│ "`` where an outer item's line continues past (code page 437
glyphs 195, 192, 196 and 179)."""


class TreeNode:
    """One item of a ``TreeView``, together with the items below it.

    ``children`` holds the items below it. ``load``, if given, is called with
    the node the first time it is expanded, and returns the children instead,
    for items that are slow to find (such as a folder's files). ``data`` is
    anything the application wants to keep with the item.
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
        """Add an item below this one, after its other children, and return
        it."""
        child.parent = self
        self.children.append(child)
        return child

    @property
    def has_children(self) -> bool:
        """Whether the item has items below it, or may have (because they have
        not been loaded yet)."""
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
    """A ``TreeView`` is an outline of items (``TreeNode`` objects) that can be
    expanded to show the items below them, with lines joining each item to the
    one above it in the outline:

    ::

        ▼ C:
        ├─  Documents
        ├─► Programs
        └─  Settings

    ::

        roots = [TreeNode("C:", [TreeNode("Documents"),
                                 TreeNode("Programs", load=find_files)],
                          expanded=True)]
        folders = window.add(TreeView(roots, 0, 0, 18, 12, on_change=show_files))
        several = TreeView(other_roots, 0, 0, 18, 12, multiple=True)

    - **Nodes.** A ``TreeNode`` has a ``label``, ``children``, ``expanded``,
      ``data`` for the application, and optionally ``load``, which is called with
      the node the first time it is expanded and returns its children then, for
      items that are slow to find (such as a folder's files). ``parent``,
      ``depth`` and ``path`` say where the node is.
    - **Marks.** ``►`` marks an item that can be expanded, and ``▼`` one that is
      expanded.
    - **Single selection** (the default). The highlighted item is the selected
      one, as in a list box.
    - **Multiple selection** (``multiple=True``). Moving only moves the
      highlight, and Space (``list_toggle``), or a click, selects or deselects
      the highlighted item, so any number of items can be selected. Ctrl+A
      (``list_select_all``) selects every item showing, or deselects them all,
      and Shift and a click selects a range of the items showing. Items stay
      selected while the items above them are collapsed. ``value`` is a tuple of
      the selected items, and ``selected=`` sets which items start selected (or,
      with single selection, which one is highlighted).
    - **Keys.** Underneath, a tree is a list box, with its keys (``list_up`` and
      the rest) and typing to find a visible item. Right (``tree_expand``)
      expands the highlighted item, or, if it is already expanded, moves to its
      first child; Left (``tree_collapse``) collapses it, or moves to its parent.
      Enter (``tree_choose``) chooses it, by calling ``on_choose(tree)``, or
      otherwise by expanding or collapsing an item that has children; on any
      other item, Enter is left for the window.
    - **Mouse.** A click on ``►`` or ``▼`` expands or collapses the item, a
      click elsewhere highlights it (and with multiple selection, selects or
      deselects it), and a double-click chooses it.
    - **From code.** ``value`` (with single selection) and ``selected_node``
      are the highlighted item, and ``selected_nodes`` holds the selected items,
      in the order of the outline; ``set_selected_nodes(nodes)`` selects others
      instead. ``expand(node)``, ``collapse(node)``, ``select(node)`` (which expands the
      items above it) and ``refresh()`` (after nodes have changed) do the rest.
      ``on_change(tree)`` is called whenever the selection changes (with
      single selection, for every move of the highlight), and
      ``on_expand(tree, node)`` for every item expanded. ``visible_nodes`` holds
      the items shown. The colours are ``tree``, ``tree.focused``,
      ``tree.selected`` (highlighted, without the focus) and ``tree.lines``.
    """

    style: Style = Style(foreground=BLACK, background=CYAN)
    focused_style: Style = Style(foreground=BRIGHT_WHITE, background=GREEN, bold=True)
    selected_style: Style = Style(foreground=BRIGHT_YELLOW, background=CYAN, bold=True)
    """The style of the highlighted item, while the tree view does not have
    the focus."""
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
        """Work out the visible items again (after items have been added or
        removed, for example), keeping the highlight on its item if that item
        is still visible."""
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
        """The selected items, in the order of the outline, including any
        under collapsed items (with single selection, the highlighted one)."""
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
        """With multiple selection, select these items instead (the items
        above them are left as they are, expanded or not)."""
        if not self.multiple:
            return
        chosen = set(nodes)
        if chosen != self._selected_nodes:
            self._selected_nodes = chosen
            self.refresh()
            self._changed()

    def _changed(self) -> None:
        """With multiple selection, the list box's selected rows are the
        selected items showing; the items hidden keep their selection."""
        if self.multiple:
            shown = set(self.visible_nodes)
            self._selected_nodes = {
                node for node in self._selected_nodes if node not in shown
            } | {self.visible_nodes[index] for index in self.selected}
        super()._changed()

    def _reveal(self, node: TreeNode) -> bool:
        """Expand the items above an item, without working out the visible
        items again; whether any were collapsed."""
        parent = node.parent
        opened = False
        while parent is not None:
            if not parent.expanded:
                parent.expanded, opened = True, True
            parent = parent.parent
        return opened

    def select(self, node: TreeNode) -> None:
        """Highlight an item, expanding the items above it so that it is
        visible (with multiple selection, this does not select it)."""
        if self._reveal(node):
            self.refresh()
        if node in self.visible_nodes:
            self.move_to(self.visible_nodes.index(node))

    def expand(self, node: TreeNode | None = None) -> None:
        """Expand an item (the highlighted one, by default), calling
        ``on_expand``."""
        node = node if node is not None else self.selected_node
        if node is None or node.expanded or not node.has_children:
            return
        node.expanded = True
        node.loaded()
        self.refresh()
        if self.on_expand is not None:
            self.on_expand(self, node)

    def collapse(self, node: TreeNode | None = None) -> None:
        """Collapse an item (the highlighted one, by default). If the
        highlight was on one of its descendants, it moves to the item."""
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
        """Expand an item if it is collapsed, or collapse it if it is
        expanded."""
        if node.expanded:
            self.collapse(node)
        else:
            self.expand(node)

    def choose(self) -> None:
        """Do what Enter or a double-click does: call ``on_choose``, or
        otherwise expand or collapse an item that has children, or otherwise
        press the window's default button."""
        node = self.selected_node
        if self.on_choose is not None or node is None or not node.has_children:
            super().choose()
        else:
            self.toggle_node(node)

    # Drawing

    def _lines(self, node: TreeNode) -> str:
        """The lines before an item: ``│ `` for each item it is under that
        has more after it, then ``├─`` or ``└─`` (none at the top)."""
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
        """Right expands or moves in, Left collapses or moves out, and Enter
        chooses; other keys are handled as in a list box."""
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
        """A press on an item's ``►`` or ``▼`` expands or collapses it;
        everything else is handled as in a list box (a click highlights, and a
        double-click chooses)."""
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
