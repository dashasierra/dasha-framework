"""The base widget class."""

from collections.abc import Callable
from enum import Flag, auto
from typing import TYPE_CHECKING

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts

if TYPE_CHECKING:
    from dasha.menu import Menu
    from dasha.widgets.container import Container
    from dasha.window import Window


def run_shortcut(
    shortcuts: Shortcuts, key: str, actions: dict[str, Callable[[], object]]
) -> bool:
    """Run the command bound to a key; return whether there was one.

    :param shortcuts: Key bindings in effect.
    :param key: The key pressed.
    :param actions: Commands by shortcut action.
    """
    for action, command in actions.items():
        if shortcuts.matches(action, key):
            command()
            return True
    return False


class Grow(Flag):
    """Edges that follow the window when it resizes."""

    NONE = 0
    LEFT = auto()
    TOP = auto()
    RIGHT = auto()
    BOTTOM = auto()
    WIDTH = RIGHT
    """Stretch horizontally with the window."""
    HEIGHT = BOTTOM
    """Stretch vertically with the window."""
    ALL = RIGHT | BOTTOM
    """Stretch both ways."""
    STICK_RIGHT = LEFT | RIGHT
    """Keep the same distance from the window's right edge."""
    STICK_BOTTOM = TOP | BOTTOM
    """Keep the same distance from the window's bottom edge."""


class Widget:
    """Something drawn in a window.

    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param height: Height in rows.
    :param name: Widget name.
    :param status: Status bar text.
    """

    focusable: bool = False
    """Whether Tab can move the keyboard focus to this widget."""

    key_releases: bool = False
    """Whether the terminal reports key releases."""

    grow: Grow = Grow.NONE
    """How the widget follows its window's size."""

    parent: "Container | None" = None
    """The containing widget, if any."""

    context_menu: "Menu | None" = None
    """The right-click menu, if any."""

    help: str | None = None
    """Help topic for F1."""

    area_shift: int = 0
    """Rows moved down by expanded areas above."""

    def __init__(
        self,
        row: int,
        column: int,
        width: int,
        height: int = 1,
        *,
        name: str | None = None,
        status: str = "",
    ) -> None:
        self.rect = Rect(row, column, height, width)
        """Position and size, relative to the window's interior."""
        self.name = name
        """Widget name, or ``None``."""
        self.status = status
        """Help shown on the status bar while the widget has the focus."""
        self.window: "Window | None" = None
        """The window this widget is in; set by ``Window.add``."""
        # For ``grow``: the rect as laid out, the interior size it was laid
        # out for, and the rect last set from them.
        self._layout: tuple[Rect, int, int, Rect] | None = None

    @property
    def value(self) -> object:
        """The value this widget holds, for the code that reads a dialog."""
        return None

    @property
    def is_shown(self) -> bool:
        """Whether every container shows the widget."""
        container = self.parent
        while container is not None:
            if not container.is_showing_children:
                return False
            container = container.anchor.parent
        return True

    def help_topic(self) -> str | None:
        """The help topic for the widget now: ``help`` by default."""
        return self.help

    def mnemonic(self) -> str | None:
        """The letter that activates this widget, if it has one."""
        return None

    def min_size(self) -> tuple[int, int]:
        """Smallest (width, height)."""
        return 1, 1

    def follow_resize(self, before: tuple[int, int], after: tuple[int, int]) -> None:
        """Move or stretch with the window.

        :param before: Old interior width and height.
        :param after: New interior width and height.
        """
        if not self.grow:
            return
        layout = self._layout
        if layout is None or layout[3] != self.rect:
            layout = (self.rect, before[0], before[1], self.rect)
        base, width, height = layout[0], layout[1], layout[2]
        self.rect = self._grown(base, after[0] - width, after[1] - height)
        self._layout = (base, width, height, self.rect)
        self.on_resize()

    def _grown(self, base: Rect, across: int, down: int) -> Rect:
        """A rect with ``grow``'s edges moved.

        :param base: The original layout.
        :param across: Columns gained.
        :param down: Rows gained.
        """
        grow = self.grow
        left = base.column + (across if Grow.LEFT in grow else 0)
        right = base.right + (across if Grow.RIGHT in grow else 0)
        top = base.row + (down if Grow.TOP in grow else 0)
        bottom = base.bottom + (down if Grow.BOTTOM in grow else 0)
        least_width, least_height = self.min_size()
        return Rect(
            top, left, max(bottom - top, least_height), max(right - left, least_width)
        )

    def on_add(self) -> None:
        """Called once added to a window."""

    def on_resize(self) -> None:
        """Called after ``grow`` has changed the widget's size or position."""

    def focus_changed(self, focused: bool) -> None:
        """Called when the focus arrives or leaves.

        :param focused: Whether the widget now has the focus.
        """
        del focused

    def can_focus(self) -> bool:
        """Whether the widget can take the focus now."""
        return self.focusable

    def mnemonics(self) -> set[str]:
        """Every mnemonic letter."""
        return set(filter(None, [self.mnemonic()]))

    def activate_mnemonic(self, letter: str) -> None:
        """Respond to a mnemonic letter.

        :param letter: The letter pressed.
        """
        del letter
        self.activate()

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        """Draw the widget.

        :param canvas: Canvas to draw on.
        :param origin: The window's interior on screen.
        :param focused: Whether the widget has the focus.
        """

    def handle_key_release(self, key: str, focused: bool) -> None:
        """Called when a key is released.

        :param key: The key released.
        :param focused: Whether the widget has the focus.
        """
        del key, focused

    def key_help(self, shortcuts: Shortcuts) -> list[tuple[str, str]]:
        """Keys for the status bar, as (key, description) pairs.

        :param shortcuts: Key bindings in effect.
        """
        del shortcuts
        return []

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Handle a key; return whether it was used.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        del key, shortcuts
        return False

    def popup_menu(self, shortcuts: Shortcuts) -> "Menu | None":
        """The context menu to show.

        :param shortcuts: Key bindings shown in the menu.
        """
        del shortcuts
        return self.context_menu

    def point_at(self, row: int, column: int) -> None:
        """Called before a right-click menu pops up.

        :param row: Row clicked.
        :param column: Column clicked.
        """
        del row, column

    def window_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Handle a key unused by any widget; return whether it was used.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        del key, shortcuts
        return False

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Handle a mouse event; return whether it was used.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        del event, row, column
        return False

    def handle_paste(self, text: str) -> bool:
        """Handle terminal-pasted text; return whether it was used.

        :param text: The pasted text.
        """
        del text
        return False

    def activate(self) -> None:
        """Carry out the widget's action (pressing a button, for example)."""

    def wake_time(self) -> float | None:
        """When ``on_timer`` is next wanted, or ``None``."""
        return None

    def on_timer(self, now: float) -> None:
        """Called at ``wake_time``.

        :param now: The current ``time.monotonic``.
        """
        del now
