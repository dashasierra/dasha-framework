"""The base class of check boxes and radio buttons, each of which is a
group of options (a cluster)."""

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
    """``CheckBoxes`` and ``RadioButtons`` are groups of options, known as
    clusters. The difference between them is how many options can be marked:
    any number of check boxes, but exactly one radio button.

    ::

        dialog.add(RadioButtons(["&Small", "&Medium", "&Large"], 2, 2, selected=1,
                                name="size"))
        dialog.add(CheckBoxes(["&Bold", "&Italic", "&Underline"], 2, 20, checked=[0],
                              name="style"))
        ...
        dialog.values  # {"size": 1, "style": (0,)}

    Each group is a single widget, so Tab moves to it, and past it, as a
    whole. Its rows are drawn as ``" [X] Label"`` and ``" (•) Label"`` (``•`` is
    code page 437 glyph 7) in black on cyan, at least as wide as the longest
    label, or ``width`` if that is wider. While a group has the focus, its
    current option is highlighted.

    - Up / Down (``option_up`` / ``option_down``): for check boxes, move to
      another option; for radio buttons, move to another option and select it
    - Left / Right (``option_left`` / ``option_right``), with columns: for check
      boxes, move to the next column; for radio buttons, move and select
    - Space (``option_press``): for check boxes, check or uncheck the current
      option; for radio buttons, select the current option
    - An option's letter (Alt with the letter, or the letter alone in a dialog):
      for check boxes, move to the option and check or uncheck it; for radio
      buttons, move to the option and select it
    - A click on an option: for check boxes, check or uncheck it; for radio
      buttons, select it

    Enter is left for the dialog's default button. Up and Down stop at the first
    and last options.

    **Columns.** ``columns=3`` lays the options out in three columns, filled
    from top to bottom and then from left to right. ``rows`` is how many options
    each column holds (the last column may hold fewer). Each column is as wide as
    its own longest label, and ``width``, if it is wider, widens the last column.
    Up and Down run on from the bottom of one column to the top of the next, and
    Left and Right move to the next column, to the enabled option nearest the
    same row. With a single column, Left and Right are left for the window.

    ::

        CheckBoxes(["&Windows", "M&enus", "Mo&use", "&Dialogs", "&Themes", "&Plugins"],
                   2, 22, columns=2, disabled=[5])
        #  [ ] Windows  [X] Dialogs
        #  [ ] Menus    [ ] Themes
        #  [ ] Mouse    [ ] Plugins   (greyed out)

    **Disabled options.** The options whose indexes are given in
    ``disabled=`` are greyed out (``cluster.disabled``). They cannot be pressed by
    key, click or letter, their letters are free for other widgets to use, and
    moving skips over them. ``disable(*indexes)`` and ``enable(*indexes)`` change
    this later, and ``is_enabled(index)`` and the ``disabled`` set say which
    options are which. Code can still ``press`` a disabled option. If the current
    option is disabled, the next enabled one becomes current. A radio button can
    stay selected while it is disabled, but cannot be chosen again. A group whose
    options are all disabled cannot take the focus, so Tab skips over it. Whether
    any widget can take the focus at the moment is given by its ``can_focus()``,
    which is ``focusable`` unless the widget decides otherwise.

    - **Check boxes.** ``value`` is a tuple of the indexes of the checked
      options, ``checked`` is a list of ``True`` or ``False`` values (which code
      can change), and ``checked_labels`` holds the checked options' labels
      without their ``&``.
    - **Radio buttons.** ``value`` and ``selected`` are the index of the selected
      option, and ``selected_label`` is its label without the ``&``.

    ``on_change(group)`` is called whenever the marks change. Both kinds share
    the base class ``Cluster``, whose ``marks`` (``("[ ]", "[X]")``) a subclass
    can change.

    The layout is worked out when the group is created.
    """

    focusable = True
    style: Style = Style(foreground=BLACK, background=CYAN)
    selected_style: Style = Style(foreground=BRIGHT_WHITE, background=CYAN, bold=True)
    """The style of the current option, while the group has the focus."""
    mnemonic_style: Style = Style(foreground=BRIGHT_YELLOW, background=CYAN)
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
        """The option the keys work on; an enabled one, if there is any."""
        self.disable(*disabled)

    # Options

    def _column(self, number: int) -> list[str]:
        """The labels in one column."""
        return self.labels[number * self.rows : (number + 1) * self.rows]

    def is_marked(self, index: int) -> bool:
        """Whether an option is shown as checked or selected."""
        raise NotImplementedError

    def press(self, index: int) -> None:
        """Do to an option what Space does (check, uncheck or select it).
        Code can press a disabled option, though the user cannot."""
        raise NotImplementedError

    def is_enabled(self, index: int) -> bool:
        """Whether the user can press an option."""
        return index not in self.disabled

    def disable(self, *indexes: int) -> None:
        """Grey out options, so that they cannot be chosen. If the current
        option is one of them, the next enabled option becomes current."""
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
        """Allow options to be chosen again."""
        self.disabled.difference_update(indexes)
        if not self.is_enabled(self.current) and self.can_focus():
            self.disable()  # moves off the disabled current option

    def min_size(self) -> tuple[int, int]:
        """The size of the columns as laid out, because the options are never
        squeezed."""
        return sum(self._widths), self.rows

    def can_focus(self) -> bool:
        return len(self.disabled) < len(self.labels)

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change(self)

    # Layout

    def _place(self, index: int) -> tuple[int, int, int]:
        """Where an option is within the group: (row, column, width)."""
        number, row = divmod(index, self.rows)
        return row, sum(self._widths[:number]), self._widths[number]

    def index_at(self, row: int, column: int) -> int | None:
        """The option at a position within the group, if any."""
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
        """The first enabled option after ``start``, going ``step`` at a
        time; ``None`` if there is none that way."""
        index = start + step
        while 0 <= index < len(self.labels):
            if self.is_enabled(index):
                return index
            index += step
        return None

    def _sideways(self, direction: int) -> int | None:
        """The enabled option in the next column to the left (-1) or right
        (1) that is nearest the current row, the upper one if two are as
        near; columns with nothing enabled are passed over."""
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
        """Make an option the current one, as moving with the keys does."""
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
        """One option: `` [X] Label``, its letter highlighted."""
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
        """Up and Down move, and Space presses; Left and Right move between
        columns (with only one column, they are left for the window)."""
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
        """A press on an enabled option presses it."""
        if event.button != "left":
            return False
        if event.action == "press":
            index = self.index_at(row - self.rect.row, column - self.rect.column)
            if index is not None and self.is_enabled(index):
                self.current = index
                self.press(index)
        return event.action in ("press", "drag", "release")


class ClusterOptions(TypedDict, total=False):
    """The keyword options that every group accepts, for subclasses that add
    options of their own and pass the rest on with ``**options``."""

    columns: int
    disabled: Iterable[int]
    width: int | None
    on_change: Callable[[Cluster], object] | None
    name: str | None
    status: str
