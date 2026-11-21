"""Collapsible areas."""

from collections.abc import Callable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.menu import mnemonic_key, split_mnemonic
from dasha.scrollbar import DOWN, RIGHT
from dasha.shortcuts import Shortcuts
from dasha.style import BRIGHT_BLACK, BRIGHT_WHITE, BRIGHT_YELLOW, Style
from dasha.widgets.base import Widget, run_shortcut
from dasha.widgets.container import Container
from dasha.widgets.label import on_window, paint_mnemonic_label


class Collapsible(Container, Widget):
    """A header that shows or hides an area of widgets.

    :param label: Header text; ``&`` marks the mnemonic.
    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Header width, if fixed.
    :param expanded: Whether it starts expanded.
    :param on_change: Called with the area when toggled.
    :param name: Widget name.
    :param status: Status bar text.
    """

    focusable = True
    noun = "collapsible area"
    opens_below = True
    arrow_style: Style = Style(bold=True)
    """Arrow style."""
    label_style: Style = Style(foreground=BRIGHT_BLACK)
    """Label style."""
    focused_style: Style = Style(foreground=BRIGHT_WHITE)
    """Label style while focused."""
    mnemonic_style: Style = Style(foreground=BRIGHT_YELLOW)
    """Mnemonic letter style."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        label: str,
        row: int,
        column: int,
        width: int | None = None,
        *,
        expanded: bool = False,
        on_change: Callable[["Collapsible"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        text = split_mnemonic(label)[0]
        width = width if width is not None else 2 + len(text)
        Widget.__init__(self, row, column, max(width, 1), name=name, status=status)
        Container.__init__(self)
        self.label = label
        self._expanded = expanded
        self.on_change = on_change

    # Its state

    @property
    def value(self) -> bool:
        return self._expanded

    @property
    def expanded(self) -> bool:
        """Whether the area is expanded."""
        return self._expanded

    @expanded.setter
    def expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        window = self.window
        if window is None:
            return
        window.lay_out()
        focused = window.focused
        if focused is not None and not focused.is_shown and self.is_shown:
            window.focus(self)  # the focus was hidden in the area

    def set(self, expanded: bool) -> None:
        """Expand or collapse, as the user does.

        :param expanded: Whether to expand.
        """
        if expanded != self._expanded:
            self.expanded = expanded
            if self.on_change is not None:
                self.on_change(self)

    def expand(self) -> None:
        """Show the area."""
        self.set(True)

    def collapse(self) -> None:
        """Hide the area."""
        self.set(False)

    def toggle(self) -> None:
        """Expand or collapse."""
        self.set(not self._expanded)

    # Its widgets (``add`` puts one in: row 0 is the first row under the
    # header, column 0 the header's column)

    @property
    def anchor(self) -> Widget:
        return self

    @property
    def is_showing_children(self) -> bool:
        return self._expanded

    def content_origin(self) -> tuple[int, int]:
        return self.home_row + 1, self.rect.column

    # Drawing and input

    def mnemonic(self) -> str | None:
        return mnemonic_key(self.label)

    def activate(self) -> None:
        self.toggle()

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        row = origin.row + self.rect.row
        column = origin.column + self.rect.column
        body = self.window.body_style if self.window is not None else Style()
        arrow = on_window(self.arrow_style, body)
        canvas.write(row, column, DOWN if self._expanded else RIGHT, arrow, clip=origin)
        label = on_window(self.focused_style if focused else self.label_style, body)
        letter = on_window(self.mnemonic_style, body)  # the same, focused or not
        paint_mnemonic_label(
            canvas,
            origin,
            (row, column + 2),
            self.label,
            label,
            width=self.rect.width - 2,
            letter_style=letter,
        )

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Toggle, expand or collapse with the keys.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        actions: dict[str, Callable[[], object]] = {
            "collapsible_toggle": self.toggle,
            "collapsible_expand": self.expand,
            "collapsible_collapse": self.collapse,
        }
        return run_shortcut(shortcuts, key, actions)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Toggle on a header click.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        del row, column
        left = event.button == "left"
        if left and event.action == "press":
            self.toggle()
        return left and event.action in ("press", "drag", "release")
