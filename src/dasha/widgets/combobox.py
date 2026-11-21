"""Combo boxes."""

from collections.abc import Callable, Iterable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts
from dasha.style import BLUE, BRIGHT_WHITE, CYAN, GREEN, Style
from dasha.widgets.base import Widget

DROP_DOWN = "\N{BLACK DOWN-POINTING TRIANGLE}"
"""The drop-down button."""


class ComboBox(Widget):  # pylint: disable=too-many-instance-attributes
    """A field that drops down a list of choices.

    :param items: The choices.
    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param selected: Index of the initial choice.
    :param on_change: Called with the box when the choice changes.
    :param name: Widget name.
    :param status: Status bar text.
    """

    focusable = True
    style: Style = Style(foreground=BLUE, background=CYAN)
    """The style of the field."""
    focused_style: Style = Style(foreground=BRIGHT_WHITE, background=CYAN, bold=True)
    """The style of the field while it has the focus."""
    button_style: Style = Style(foreground=BRIGHT_WHITE, background=GREEN, bold=True)
    """The style of the ``▼`` on the right."""
    min_width: int = 3

    def __init__(  # pylint: disable=too-many-arguments
        self,
        items: Iterable[str],
        row: int,
        column: int,
        width: int,
        *,
        selected: int = 0,
        on_change: Callable[["ComboBox"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        if width < self.min_width:
            raise ValueError(f"a combo box must be at least {self.min_width} wide")
        super().__init__(row, column, width, name=name, status=status)
        self.items: list[str] = list(items)
        self.on_change = on_change
        self.selected = max(0, min(selected, len(self.items) - 1))
        """The index of the chosen item."""

    @property
    def value(self) -> int:
        return self.selected

    @property
    def selected_item(self) -> str:
        """The chosen item's text (``""`` when there are no items)."""
        return self.items[self.selected] if self.items else ""

    def set_items(self, items: Iterable[str], selected: int = 0) -> None:
        """Replace the items without notifying.

        :param items: The new choices.
        :param selected: Index of the choice.
        """
        self.items = list(items)
        self.selected = max(0, min(selected, len(self.items) - 1))

    def choose(self, index: int) -> None:
        """Choose an item, as the user does.

        :param index: Item index.
        """
        if not self.items:
            return
        index = max(0, min(index, len(self.items) - 1))
        if index != self.selected:
            self.selected = index
            if self.on_change is not None:
                self.on_change(self)

    def min_size(self) -> tuple[int, int]:
        return self.min_width, 1

    # Dropping the list down

    def drop_down(self) -> None:
        """Drop down the list and take the choice."""
        window = self.window
        manager = window.manager if window is not None else None
        if window is None or manager is None or not self.items:
            return
        chosen = manager.pick(self.items, self.selected, window.screen_rect(self))
        if chosen is not None:
            self.choose(chosen)

    # Drawing and input

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        row = origin.row + self.rect.row
        column = origin.column + self.rect.column
        width = self.rect.width
        text = f" {self.selected_item}"[: width - 2].ljust(width - 1)
        style = self.focused_style if focused else self.style
        canvas.write(row, column, text, style, clip=origin)
        canvas.write(row, column + width - 1, DROP_DOWN, self.button_style, clip=origin)

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Open, step through or jump in the list.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        if shortcuts.matches("combo_open", key):
            self.drop_down()
            return True
        if shortcuts.matches("combo_previous", key):
            self.choose(self.selected - 1)
            return True
        if shortcuts.matches("combo_next", key):
            self.choose(self.selected + 1)
            return True
        if len(key) == 1 and key.isprintable() and key != " " and self.items:
            letter = key.casefold()
            for index, item in enumerate(self.items):
                if item.casefold().startswith(letter):
                    self.choose(index)
                    break
            return True
        return False

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Drop down the list on a click.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        del row, column
        if event.button != "left":
            return False
        if event.action == "press":
            self.drop_down()
        return event.action in ("press", "drag", "release")
