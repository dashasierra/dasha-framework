"""The base class of every widget.

A widget is positioned relative to its window's interior, so row 0, column 0
is the first cell inside the frame. Every widget can have a ``name``, by
which the code that showed a dialog can find it again (``Dialog.widget``,
``Dialog.values``), and optional ``status`` text, which is shown on the
status bar while the widget has the focus.
"""

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
    """Run the command of the first entry in ``actions`` (a mapping of
    shortcut actions to commands) for which ``key`` is a shortcut, and
    return whether there was one."""
    for action, command in actions.items():
        if shortcuts.matches(action, key):
            command()
            return True
    return False


class Grow(Flag):
    """Which of a widget's edges follow its window's right and bottom edges
    when the window changes size. With none (the default), a widget stays as
    it was laid out.

    ``RIGHT`` and ``BOTTOM`` stretch the widget; combined with ``LEFT`` or
    ``TOP`` as well, they move the whole widget instead, keeping its size.
    The useful combinations have names of their own.
    """

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
    """Stretch in both directions, filling whatever room the window
    gains."""
    STICK_RIGHT = LEFT | RIGHT
    """Keep the same distance from the window's right edge."""
    STICK_BOTTOM = TOP | BOTTOM
    """Keep the same distance from the window's bottom edge."""


class Widget:
    """Something drawn inside a window, which may take the keyboard
    focus.

    Subclasses override ``paint``, and as needed ``handle_key``,
    ``handle_mouse``, ``handle_paste`` and ``value``.
    """

    focusable: bool = False
    """Whether Tab can move the keyboard focus to this widget."""

    key_releases: bool = False
    """Whether the terminal reports keys being released (the Windows
    console does, for Space). The presentation manager sets this when it
    starts running, and a button uses it to stay pushed in while Space is
    held down."""

    grow: Grow = Grow.NONE
    """How the widget follows its window's size (see ``Grow``). Set it on
    the widget, or with ``Window.add(widget, grow=...)``."""

    parent: "Container | None" = None
    """The container the widget is in, if any (such as a collapsible area,
    a group box or a tab page), set by the container's ``add``."""

    context_menu: "Menu | None" = None
    """The menu, if any, that pops up for a right-click on the widget (or
    for Shift+F10 while it has the focus). Set it on a widget. Text boxes and
    text areas have a menu of their own unless they are given another (see
    ``popup_menu``)."""

    help: str | None = None
    """The help topic for the widget, which F1 goes to while it has the focus
    (see ``dasha.help``): the name of a page in its application's
    ``help_folder``, without ``.md``. Set it on a widget. Without one, F1 goes
    to the topic of a container it is in, or its window, or else the index."""

    area_shift: int = 0
    """How many rows the expanded collapsible areas above the widget have
    moved it down (kept up to date by
    ``dasha.widgets.container.lay_out``)."""

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
        """The widget's name, by which code can find it again
        (``Window.widget``, ``Dialog.values``); ``None`` for none."""
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
        """Whether the widget is shown, which it is when every container it
        is in (and every container those are in, and so on) is showing its
        widgets. A widget in a collapsed area is not shown, for example, nor
        is one on a tab page that is not selected. A widget that is not shown
        is not drawn and receives no input, but it keeps its value."""
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
        """The smallest (width, height) the widget can have, which limits how
        far ``grow`` can shrink it."""
        return 1, 1

    def follow_resize(self, before: tuple[int, int], after: tuple[int, int]) -> None:
        """Handle the window's interior changing size from ``before`` to
        ``after`` (each a width and height), by moving or stretching the
        widget as ``grow`` says.

        The new position is worked out from where the widget was originally
        laid out, not from where it was most recently, so shrinking a window
        and growing it again puts everything back. If code has moved the
        widget since then, its new position becomes its layout.
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
        """``base`` with the edges ``grow`` names moved ``across`` and
        ``down``, kept to at least ``min_size()``."""
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
        """Called once ``Window.add`` has put the widget in its window, when
        ``self.window`` has been set."""

    def on_resize(self) -> None:
        """Called after ``grow`` has changed the widget's size or position."""

    def focus_changed(self, focused: bool) -> None:
        """Called when the keyboard focus arrives at this widget
        (``focused`` is true), or leaves it for another widget in its window.
        Does nothing by default; a spin box uses this to check what was typed
        in it when the focus leaves."""
        del focused

    def can_focus(self) -> bool:
        """Whether the widget can take the keyboard focus at the moment. This
        is ``focusable``, unless the widget decides otherwise (a group whose
        options are all disabled cannot take the focus, for example)."""
        return self.focusable

    def mnemonics(self) -> set[str]:
        """Every letter this widget responds to: just ``mnemonic()`` for most
        widgets, or one for each item in a group of check boxes."""
        return set(filter(None, [self.mnemonic()]))

    def activate_mnemonic(self, letter: str) -> None:
        """Respond to one of ``mnemonics()``; by default, by calling
        ``activate``."""
        del letter
        self.activate()

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        """Draw the widget. ``origin`` is the window's interior on the screen,
        and drawing is clipped to it."""

    def handle_key_release(self, key: str, focused: bool) -> None:
        """Called when a key is released (only where ``key_releases`` is
        true). ``focused`` is whether this widget has the focus. Does nothing
        by default."""
        del key, focused

    def key_help(self, shortcuts: Shortcuts) -> list[tuple[str, str]]:
        """The most useful keys while the widget has the focus, as (key,
        description) pairs such as ``("Ctrl+Tab", "Next")``, which the status
        bar shows. They are built from ``shortcuts``, so that they follow the
        user's own bindings. Keys that only edit text (cut, copy, paste,
        select all, undo, redo, clear, delete line) are left out. There are
        none by default."""
        del shortcuts
        return []

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Handle a key while the widget has the focus, and return whether
        the key was used. ``shortcuts`` holds the bindings in effect, for
        widgets with keys of their own."""
        del key, shortcuts
        return False

    def popup_menu(self, shortcuts: Shortcuts) -> "Menu | None":
        """The context menu to pop up for the widget now: ``context_menu`` by
        default. ``shortcuts`` gives the keys to show beside its items."""
        del shortcuts
        return self.context_menu

    def point_at(self, row: int, column: int) -> None:
        """Called for a right-click at a place in the widget (in window
        content coordinates), just before its context menu pops up. A list
        moves its highlight there, so that the menu acts on what was clicked.
        Does nothing by default."""
        del row, column

    def window_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Handle a key that no widget has used, wherever the focus is in the
        window (tabs use this to choose a page with Ctrl+PgDn), and return
        whether it was used. The widgets that contain the focus are asked
        first. Does nothing by default."""
        del key, shortcuts
        return False

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Handle a mouse event at ``row``, ``column``, relative to the
        window's interior, and return whether the event was used."""
        del event, row, column
        return False

    def handle_paste(self, text: str) -> bool:
        """Handle text pasted through the terminal while the widget has the
        focus (with the terminal's own Ctrl+V, for example, rather than
        Dasha Framework's), and return whether it was used."""
        del text
        return False

    def activate(self) -> None:
        """Carry out the widget's action (pressing a button, for example)."""

    def wake_time(self) -> float | None:
        """When (by ``time.monotonic``) this widget next wants ``on_timer``
        to be called, or ``None`` if it does not. The presentation manager
        waits for input only until then, so that a widget can act while
        nothing else is happening, such as scrolling while the mouse is held
        still."""
        return None

    def on_timer(self, now: float) -> None:
        """Called once ``wake_time`` has come; ``now`` is the current
        ``time.monotonic``."""
        del now
