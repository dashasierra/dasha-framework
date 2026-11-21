"""The base class of option groups."""

from collections.abc import Callable, Iterable, Sequence
from typing import TypedDict

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.menu import mnemonic_key, split_mnemonic
from dasha.shortcuts import Shortcuts
from dasha.style import (
    BLACK,
    BRIGHT_BLACK,
    BRIGHT_WHITE,
    BRIGHT_YELLOW,
    CYAN,
    Style,
)
from dasha.widgets.base import Widget


class Cluster(Widget):  # pylint: disable=too-many-instance-attributes
    """A group of options: check boxes or radio buttons.

    :param labels: Option labels; ``&`` marks mnemonics.
    :param row: Row in the window.
    :param column: Column in the window.
    :param columns: Number of columns.
    :param disabled: Indexes of greyed-out options.
    :param width: Minimum width, if any.
    :param on_change: Called with the group when an option is pressed.
    :param name: Widget name.
    :param status: Status bar text.
    """

    focusable = True
    style: Style = Style(foreground=BLACK, background=CYAN)
    """The style of the options."""
    selected_style: Style = Style(foreground=BRIGHT_WHITE, background=CYAN, bold=True)
    """The style of the current option, while the group has the focus."""
    mnemonic_style: Style = Style(foreground=BRIGHT_YELLOW, background=CYAN)
    """The style of each option's mnemonic letter."""
    disabled_style: Style = Style(foreground=BRIGHT_BLACK, background=CYAN)
    """The style of options that cannot be chosen."""
    marks: tuple[str, str] = ("[ ]", "[X]")
    """How an option looks when unmarked and when marked."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        labels: Sequence[str],
        row: int,
        column: int,
        *,
        columns: int = 1,
        disabled: Iterable[int] = (),
        width: int | None = None,
        on_change: "Callable[[Cluster], object] | None" = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        if not labels:
            raise ValueError("a group needs at least one option")
        if columns < 1:
            raise ValueError("columns must be at least 1")
        self.labels = list(labels)
        self.columns = min(columns, len(self.labels))
        """How many columns the options are laid out in."""
        self.rows = -(-len(self.labels) // self.columns)
        """How many rows: the options per column (the last may have fewer)."""
        self.disabled: set[int] = set()
        self._widths = [
            len(self.marks[0])
            + 3  # " [X] Label "
            + max(len(split_mnemonic(label)[0]) for label in self._column(number))
            for number in range(self.columns)
        ]
        if width is not None and width > sum(self._widths):
            self._widths[-1] += width - sum(self._widths)
        super().__init__(
            row, column, sum(self._widths), self.rows, name=name, status=status
        )
        self.on_change = on_change
        self.current = 0
        """The option the keys act on."""
        self.disable(*disabled)

    # Options

    def _column(self, number: int) -> list[str]:
        """The labels in one column.

        :param number: Column number.
        """
        return self.labels[number * self.rows : (number + 1) * self.rows]

    def is_marked(self, index: int) -> bool:
        """Whether an option is checked or selected.

        :param index: Option index.
        """
        raise NotImplementedError

    def press(self, index: int) -> None:
        """Press an option, as Space does.

        :param index: Option index.
        """
        raise NotImplementedError

    def is_enabled(self, index: int) -> bool:
        """Whether the user can press an option.

        :param index: Option index.
        """
        return index not in self.disabled

    def disable(self, *indexes: int) -> None:
        """Grey out options.

        :param indexes: Option indexes.
        """
        for index in indexes:
            if not 0 <= index < len(self.labels):
                raise IndexError(f"there is no option {index}")
        self.disabled.update(indexes)
        if not self.is_enabled(self.current):
            found = self._step(self.current, 1)
            if found is None:
                found = self._step(self.current, -1)
            if found is not None:
                self.current = found

    def enable(self, *indexes: int) -> None:
        """Re-enable options.

        :param indexes: Option indexes.
        """
        self.disabled.difference_update(indexes)
        if not self.is_enabled(self.current) and self.can_focus():
            self.disable()  # moves off the disabled current option

    def min_size(self) -> tuple[int, int]:
        """The laid-out size of the columns."""
        return sum(self._widths), self.rows

    def can_focus(self) -> bool:
        return len(self.disabled) < len(self.labels)

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change(self)

    # Layout

    def _place(self, index: int) -> tuple[int, int, int]:
        """An option's (row, column, width) in the group.

        :param index: Option index.
        """
        number, row = divmod(index, self.rows)
        return row, sum(self._widths[:number]), self._widths[number]

    def index_at(self, row: int, column: int) -> int | None:
        """The option at a position, if any.

        :param row: Row in the group.
        :param column: Column in the group.
        """
        if not 0 <= row < self.rows:
            return None
        left = 0
        for number, width in enumerate(self._widths):
            if left <= column < left + width:
                index = number * self.rows + row
                return index if index < len(self.labels) else None
            left += width
        return None

    # Moving

    def _step(self, start: int, step: int) -> int | None:
        """The next enabled option, or ``None``.

        :param start: Option to start from.
        :param step: Direction and stride.
        """
        index = start + step
        while 0 <= index < len(self.labels):
            if self.is_enabled(index):
                return index
            index += step
        return None

    def _sideways(self, direction: int) -> int | None:
        """The nearest enabled option in the next column.

        :param direction: -1 for left, 1 for right.
        """
        row = self.current % self.rows
        number = self.current // self.rows + direction
        while 0 <= number < self.columns:
            first = number * self.rows
            last = min(first + self.rows, len(self.labels))
            enabled = [i for i in range(first, last) if self.is_enabled(i)]
            if enabled:
                return min(enabled, key=lambda i: (abs(i - first - row), i))
            number += direction
        return None

    def move_to(self, index: int) -> None:
        """Make an option current.

        :param index: Option index.
        """
        self.current = index

    # Drawing and input

    def mnemonics(self) -> set[str]:
        return {
            letter
            for index, label in enumerate(self.labels)
            if self.is_enabled(index) and (letter := mnemonic_key(label))
        }

    def activate_mnemonic(self, letter: str) -> None:
        for index, label in enumerate(self.labels):
            if self.is_enabled(index) and mnemonic_key(label) == letter:
                self.current = index
                self.press(index)
                return

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        # The whole block first: a shorter last column leaves cells empty.
        rect = self.rect
        block = Rect(
            origin.row + rect.row, origin.column + rect.column, rect.height, rect.width
        )
        canvas.fill(origin.intersect(block), " ", self.style)
        for index in range(len(self.labels)):
            row, offset, _ = self._place(index)
            row += origin.row + self.rect.row
            column = origin.column + self.rect.column + offset
            current = focused and index == self.current and self.is_enabled(index)
            self._paint_option(
                canvas, origin, row, column, index=index, current=current
            )
        # No terminal cursor: the highlight already shows the current option.

    def _paint_option(  # pylint: disable=too-many-arguments
        self,
        canvas: Canvas,
        origin: Rect,
        row: int,
        column: int,
        *,
        index: int,
        current: bool,
    ) -> None:
        """Draw one option.

        :param canvas: Canvas to draw on.
        :param origin: The window's interior on screen.
        :param row: Option row.
        :param column: Option column.
        :param index: Option index.
        :param current: Whether it is the current option.
        """
        enabled = self.is_enabled(index)
        if not enabled:
            style = self.disabled_style
        else:
            style = self.selected_style if current else self.style
        mark = self.marks[1] if self.is_marked(index) else self.marks[0]
        text, letter = split_mnemonic(self.labels[index])
        line = f" {mark} {text}".ljust(self._place(index)[2])
        canvas.write(row, column, line, style, clip=origin)
        if letter is not None and enabled:
            mnemonic = Style(
                foreground=self.mnemonic_style.foreground,
                background=style.background,
                bold=style.bold or self.mnemonic_style.bold,
                reverse=self.mnemonic_style.reverse or style.reverse,
                underline=self.mnemonic_style.underline,
            )
            at = column + len(mark) + 2 + letter
            canvas.write(row, at, text[letter], mnemonic, clip=origin)

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Move or press with the keys.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        if shortcuts.matches("option_press", key):
            if self.is_enabled(self.current):
                self.press(self.current)
            return True
        moves: dict[str, Callable[[], int | None]] = {
            "option_up": lambda: self._step(self.current, -1),
            "option_down": lambda: self._step(self.current, 1),
            "option_left": lambda: self._sideways(-1),
            "option_right": lambda: self._sideways(1),
        }
        for action, find in moves.items():
            if shortcuts.matches(action, key):
                if self.columns == 1 and action in ("option_left", "option_right"):
                    return False
                index = find()
                if index is not None:
                    self.move_to(index)
                return True
        return False

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Press the option clicked.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        if event.button != "left":
            return False
        if event.action == "press":
            index = self.index_at(row - self.rect.row, column - self.rect.column)
            if index is not None and self.is_enabled(index):
                self.current = index
                self.press(index)
        return event.action in ("press", "drag", "release")


class ClusterOptions(TypedDict, total=False):
    """Keyword options every group accepts."""

    columns: int
    disabled: Iterable[int]
    width: int | None
    on_change: Callable[[Cluster], object] | None
    name: str | None
    status: str
