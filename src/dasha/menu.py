"""Drop-down menus and the menu bar."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from dasha.border import SINGLE, Border
from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts, pretty_key
from dasha.style import (
    BRIGHT_WHITE,
    WHITE,
    BRIGHT_GREEN,
    BLUE,
    SHADOW,
    BRIGHT_BLUE,
    Style,
)

SEPARATOR_LEFT = "\N{BOX DRAWINGS LIGHT VERTICAL AND RIGHT}"
SEPARATOR_RIGHT = "\N{BOX DRAWINGS LIGHT VERTICAL AND LEFT}"


def split_mnemonic(label: str) -> tuple[str, int | None]:
    """A label without ``&`` and its mnemonic index.

    :param label: The label.
    """
    text: list[str] = []
    mnemonic: int | None = None
    index = 0
    while index < len(label):
        char = label[index]
        if char == "&" and index + 1 < len(label):
            index += 1
            if label[index] != "&" and mnemonic is None:
                mnemonic = len(text)
        text.append(label[index])
        index += 1
    return "".join(text), mnemonic


def mnemonic_key(label: str) -> str | None:
    """A label's lowercase mnemonic letter, if any.

    :param label: The label.
    """
    text, index = split_mnemonic(label)
    return None if index is None else text[index].lower()


class DuplicateMnemonicError(ValueError):
    """Two labels mark the same mnemonic letter."""


def unique_mnemonics(
    labels: Iterable[str], *, strict: bool = False
) -> list[int | None]:
    """Mnemonic indexes, each letter used once.

    :param labels: The labels.
    :param strict: Whether a repeat raises ``DuplicateMnemonicError``.
    """
    owners: dict[str, str] = {}
    positions: list[int | None] = []
    for label in labels:
        text, index = split_mnemonic(label)
        if index is not None:
            letter = text[index].lower()
            if letter not in owners:
                owners[letter] = label
            elif strict:
                raise DuplicateMnemonicError(
                    f"{label!r} marks the mnemonic {letter!r},"
                    f" which {owners[letter]!r} already has"
                )
            else:
                index = None
        positions.append(index)
    return positions


def _letters(labels: Sequence[str]) -> list[str | None]:
    """Each label's unique mnemonic letter, or ``None``.

    :param labels: The labels.
    """
    return [
        None if index is None else split_mnemonic(label)[0][index].lower()
        for label, index in zip(labels, unique_mnemonics(labels))
    ]


SUBMENU_MARK = "\N{BLACK RIGHT-POINTING POINTER}"
"""Submenu marker character."""


@dataclass
class MenuItem:
    """One menu choice."""

    label: str
    action: Callable[[], object] | None = None
    shortcut: str = ""
    status: str = ""
    is_separator: bool = False
    submenu: "Menu | None" = None
    enabled: Callable[[], bool] | None = None

    @property
    def is_available(self) -> bool:
        """Whether the item can be chosen now."""
        if self.is_separator or (self.action is None and self.submenu is None):
            return False
        return self.enabled is None or bool(self.enabled())


def separator() -> MenuItem:
    """A dividing line between groups of items."""
    return MenuItem("", is_separator=True)


@dataclass
class Menu:
    """A titled list of items."""

    title: str
    items: list[MenuItem] = field(default_factory=list)
    lists_minimised: bool = False
    """Whether minimised windows are listed here."""
    on_open: "Callable[[Menu], object] | None" = None
    """Called with the menu before it opens."""
    after_window: bool = False
    """Whether it goes after the Window menu."""

    def mnemonics(self) -> list[str | None]:
        """Each item's unique mnemonic letter, or ``None``."""
        return _letters([item.label for item in self.items])

    def check_mnemonics(self) -> None:
        """Raise ``DuplicateMnemonicError`` on repeated letters."""
        seen: set[int] = set()
        pending: list[Menu] = [self]
        while pending:
            menu = pending.pop()
            if id(menu) in seen:
                continue  # a menu that is its own submenu, somewhere
            seen.add(id(menu))
            if menu.on_open is not None:
                menu.on_open(menu)
            unique_mnemonics((item.label for item in menu.items), strict=True)
            pending += [item.submenu for item in menu.items if item.submenu]


@dataclass
class _Level:
    """One open menu level."""

    menu: Menu
    highlight: int | None = None
    """The highlighted item, or ``None``."""


class MenuBar:  # pylint: disable=too-many-public-methods
    """The menu bar and its open menus.

    :param shortcuts: Key bindings, or ``None`` for the defaults.
    """

    bar_style: Style = Style(foreground=BRIGHT_WHITE, background=BRIGHT_BLUE)
    """The style of the bar, and of the drop-downs and their items."""
    mnemonic_style: Style = Style(foreground=BRIGHT_GREEN, background=BRIGHT_BLUE)
    """The style of mnemonic letters in titles and items."""
    selected_style: Style = Style(foreground=BRIGHT_WHITE, background=BLUE)
    """The style of the open menu's title, and of the highlighted item."""
    selected_mnemonic_style: Style = Style(foreground=BRIGHT_GREEN, background=BLUE)
    """Mnemonic style when highlighted."""
    disabled_style: Style = Style(foreground=WHITE, background=BRIGHT_BLUE)
    """The style of items that cannot be chosen."""
    border: Border = SINGLE
    """The frame drawn around each drop-down and submenu."""
    frame_padding: int = 1
    """Blank columns beside the drop-down's frame."""

    shadow_style: Style | None = SHADOW
    """Drop-down shadow style, or ``None``."""
    shadow_width: int = 2
    shadow_height: int = 1

    def __init__(self, shortcuts: Shortcuts | None = None) -> None:
        self.shortcuts = shortcuts if shortcuts is not None else Shortcuts()
        self.menus: list[Menu] = []
        self.lines = 24
        """Screen height."""
        self._open: int | None = None
        self._levels: list[_Level] = []
        self.shortcut_key: str | None = None
        """The key that chose the running item, or ``None``."""
        self.inert: frozenset[int] = frozenset()
        """Bar positions of menus that cannot open."""

    # State

    def set_menus(self, menus: Sequence[Menu], inert: Iterable[int] = ()) -> None:
        """Show these menus.

        :param menus: The menus.
        :param inert: Positions of menus that cannot open.
        """
        if len(menus) != len(self.menus) or any(
            new is not old for new, old in zip(menus, self.menus)
        ):
            self.menus = list(menus)
            self.close()
        self.inert = frozenset(inert)
        if self._open is not None and self._open in self.inert:
            self.close()

    def items_changed(self) -> None:
        """Follow changes to the open menus' items."""
        for depth in range(1, len(self._levels)):
            opener = self._item(depth - 1)
            if opener is None or opener.submenu is not self._levels[depth].menu:
                del self._levels[depth:]  # its item has gone, or is greyed out
                break
        if self._levels and self._item(len(self._levels) - 1) is None:
            self._move_highlight(1)

    def check_mnemonics(self) -> None:
        """Raise ``DuplicateMnemonicError`` on repeated letters."""
        unique_mnemonics((menu.title for menu in self.menus), strict=True)
        for menu in self.menus:
            menu.check_mnemonics()

    @property
    def is_open(self) -> bool:
        """Whether a drop-down is showing."""
        return self._open is not None

    @property
    def open_menu(self) -> Menu | None:
        """The menu whose drop-down is showing, if any."""
        return None if self._open is None else self.menus[self._open]

    @property
    def open_menus(self) -> list[Menu]:
        """Every open menu: the drop-down, then each submenu opened from it."""
        return [level.menu for level in self._levels]

    @property
    def highlighted(self) -> MenuItem | None:
        """The innermost highlighted item, if any."""
        if not self._levels:
            return None
        return self._item(len(self._levels) - 1)

    def _item(self, depth: int) -> MenuItem | None:
        """A level's highlighted item, if any.

        :param depth: The level.
        """
        level = self._levels[depth]
        index = level.highlight
        if index is None or index >= len(level.menu.items):
            return None
        item = level.menu.items[index]
        return item if item.is_available else None

    def open(self, index: int, step: int = 0) -> None:
        """Open a menu's drop-down.

        :param index: Bar position.
        :param step: Direction to skip inert menus, or 0.
        """
        index = self._not_inert(index, step)
        if index in self.inert:
            return
        self._open = index
        menu = self.menus[self._open]
        if menu.on_open is not None:
            menu.on_open(menu)
        self._levels = [_Level(menu)]
        self._move_highlight(1)  # to the first item that can be chosen

    def _not_inert(self, index: int, step: int) -> int:
        """The nearest non-inert bar position.

        :param index: Bar position.
        :param step: Direction to search, or 0.
        """
        count = len(self.menus)
        index %= count
        if step:
            for _ in range(count):
                if index not in self.inert:
                    break
                index = (index + step) % count
        return index

    def _step_along_bar(self, step: int) -> None:
        """Open the next menu along the bar.

        :param step: 1 or -1.
        """
        assert self._open is not None
        index = self._not_inert(self._open + step, step)
        if index != self._open:
            self.open(index)

    def close(self) -> None:
        """Close any open drop-down, along with its submenus."""
        self._open = None
        self._levels = []

    def open_submenu(self) -> bool:
        """Open the highlighted item's submenu; return whether it had one."""
        item = self.highlighted
        if item is None or item.submenu is None:
            return False
        if item.submenu.on_open is not None:
            item.submenu.on_open(item.submenu)
        self._levels.append(_Level(item.submenu))
        self._move_highlight(1)
        return True

    def close_submenu(self) -> bool:
        """Close the innermost submenu; return whether there was one."""
        if len(self._levels) <= 1:
            return False
        self._levels.pop()
        return True

    def choose(self, item: MenuItem) -> None:
        """Close the menus and run an item.

        :param item: The item.
        """
        if item.is_available and item.action is not None:
            self.close()
            item.action()

    def _choose_by_key(self, item: MenuItem, key: str) -> None:
        """Choose an item by its shortcut.

        :param item: The item.
        :param key: The key pressed.
        """
        self.shortcut_key = key
        try:
            self.choose(item)
        finally:
            self.shortcut_key = None

    def _activate(self, depth: int, index: int) -> None:
        """Choose an item at a level.

        :param depth: The level.
        :param index: Item index.
        """
        del self._levels[depth + 1 :]
        level = self._levels[depth]
        item = level.menu.items[index]
        if not item.is_available:
            return
        level.highlight = index
        if item.submenu is not None:
            self.open_submenu()
        else:
            self.choose(item)

    def _move_highlight(self, step: int) -> None:
        """Move the innermost highlight.

        :param step: 1 or -1.
        """
        level = self._levels[-1]
        items = level.menu.items
        if not any(item.is_available for item in items):
            level.highlight = None
            return
        index = level.highlight
        if index is None:
            index = -1 if step > 0 else len(items)
        while True:
            index = (index + step) % len(items)
            if items[index].is_available:
                break
        level.highlight = index

    # Layout

    @property
    def title_spans(self) -> list[Rect]:
        """Where each menu title is on the bar (on row 0)."""
        spans = []
        column = 1
        for menu in self.menus:
            width = len(split_mnemonic(menu.title)[0]) + 2
            spans.append(Rect(0, column, 1, width))
            column += width
        return spans

    def _width(self, menu: Menu, with_title: bool) -> int:
        """A menu box's width.

        :param menu: The menu.
        :param with_title: Whether to fit the title.
        """
        labels = [len(split_mnemonic(item.label)[0]) for item in menu.items]
        rights = [
            len(SUBMENU_MARK) if item.submenu is not None else len(item.shortcut)
            for item in menu.items
        ]
        inner = max(labels, default=0) + 2
        if any(rights):
            inner += max(rights) + 2
        if with_title:
            inner = max(inner, len(split_mnemonic(menu.title)[0]) + 2)
        return inner + 2 + 2 * self.frame_padding

    def level_rects(self, columns: int, lines: int | None = None) -> list[Rect]:
        """Where each open menu is drawn.

        :param columns: Screen width.
        :param lines: Screen height, if known.
        """
        if self._open is None or not self._levels:
            return []
        lines = self.lines if lines is None else lines
        first = self._levels[0].menu
        width = self._width(first, with_title=True)
        column = self.title_spans[self._open].column - 1
        column = max(0, min(column, columns - width))
        rects = [Rect(1, column, len(first.items) + 2, width)]
        pad = self.frame_padding
        for depth in range(1, len(self._levels)):
            parent, menu = rects[-1], self._levels[depth].menu
            opener = self._levels[depth - 1].highlight or 0
            width, height = self._width(menu, with_title=False), len(menu.items) + 2
            # Lined up with its item: the submenu's first item level with it.
            top = parent.row + opener
            column = parent.right - pad
            if column + width > columns:
                column = parent.column + pad - width  # the left side instead
                if column < 0:
                    column = max(0, columns - width)
            top = max(1, min(top, lines - height))
            rects.append(Rect(top, column, height, width))
        return rects

    def dropdown_rect(self, columns: int) -> Rect | None:
        """Where the drop-down is drawn.

        :param columns: Screen width.
        """
        rects = self.level_rects(columns)
        return rects[0] if rects else None

    # Drawing

    def _write_label(
        self,
        canvas: Canvas,
        row: int,
        column: int,
        label: str,
        styles: tuple[Style, Style],
        *,
        mnemonic: int | None,
    ) -> None:
        """Write a label with its mnemonic.

        :param canvas: Canvas to draw on.
        :param row: Screen row.
        :param column: Screen column.
        :param label: The label, without ``&``.
        :param styles: Label and mnemonic styles.
        :param mnemonic: Mnemonic index, if any.
        """
        text = split_mnemonic(label)[0]
        canvas.write(row, column, text, styles[0])
        if mnemonic is not None:
            canvas.write(row, column + mnemonic, text[mnemonic], styles[1])

    def dropping_rect(self, rect: Rect, shown: float) -> Rect:
        """A drop-down's rect while dropping.

        :param rect: Its full rect.
        :param shown: Fraction shown, from 0 to 1.
        """
        rows = max(1, min(rect.height, round(rect.height * shown)))
        return Rect(
            rect.row - (rect.height - rows), rect.column, rect.height, rect.width
        )

    def _shown_rects(self, canvas: Canvas, shown: float) -> list[Rect]:
        """The rects to draw now.

        :param canvas: Canvas to draw on.
        :param shown: Fraction of the drop-down shown.
        """
        rects = self.level_rects(canvas.width, canvas.height)
        if rects and shown < 1:
            return [self.dropping_rect(rects[0], shown)]
        return rects

    def paint(self, canvas: Canvas, shown: float = 1) -> None:
        """Paint the bar and open menus.

        :param canvas: Canvas to draw on.
        :param shown: Fraction of the drop-down shown.
        """
        canvas.fill(Rect(0, 0, 1, canvas.width), " ", self.bar_style)
        letters = unique_mnemonics(menu.title for menu in self.menus)
        for index, (menu, span) in enumerate(zip(self.menus, self.title_spans)):
            if index == self._open:
                styles = (self.selected_style, self.selected_mnemonic_style)
            else:
                styles = (self.bar_style, self.mnemonic_style)
            canvas.fill(span, " ", styles[0])
            self._write_label(
                canvas, 0, span.column + 1, menu.title, styles, mnemonic=letters[index]
            )
        below_bar = Rect(1, 0, canvas.height - 1, canvas.width)
        for depth, rect in enumerate(self._shown_rects(canvas, shown)):
            if depth > 0 and self.shadow_style is not None:
                # A submenu's shadow falls on the menus beneath it, but, like
                # every shadow, never on the status bar.
                with canvas.clipped(Rect(0, 0, canvas.height - 1, canvas.width)):
                    canvas.cast_shadow(
                        rect, self.shadow_style, self.shadow_width, self.shadow_height
                    )
            with canvas.clipped(below_bar):  # dropping, it comes from under it
                self._paint_level(canvas, self._levels[depth], rect)

    def paint_shadow(self, canvas: Canvas, shown: float = 1) -> None:
        """Paint the drop-down's shadow.

        :param canvas: Canvas to draw on.
        :param shown: Fraction of the drop-down shown.
        """
        rects = self._shown_rects(canvas, shown)
        if rects and self.shadow_style is not None:
            canvas.cast_shadow(
                rects[0], self.shadow_style, self.shadow_width, self.shadow_height
            )

    def _paint_level(self, canvas: Canvas, level: _Level, rect: Rect) -> None:
        border = self.border
        pad = " " * self.frame_padding
        left = rect.column + self.frame_padding  # where the frame starts
        inner = rect.width - 2 - 2 * self.frame_padding

        def frame_row(row: int, left_char: str, fill: str, right_char: str) -> None:
            canvas.write(
                row,
                rect.column,
                pad + left_char + fill * inner + right_char + pad,
                self.bar_style,
            )

        frame_row(rect.row, border.top_left, border.horizontal, border.top_right)
        letters = unique_mnemonics(item.label for item in level.menu.items)
        for offset, item in enumerate(level.menu.items):
            row = rect.row + 1 + offset
            if item.is_separator:
                frame_row(row, SEPARATOR_LEFT, border.horizontal, SEPARATOR_RIGHT)
                continue
            if offset == level.highlight and item.is_available:
                styles = (self.selected_style, self.selected_mnemonic_style)
            elif item.is_available:
                styles = (self.bar_style, self.mnemonic_style)
            else:
                styles = (self.disabled_style, self.disabled_style)
            frame_row(row, border.vertical, " ", border.vertical)
            canvas.fill(Rect(row, left + 1, 1, inner), " ", styles[0])
            self._write_label(
                canvas, row, left + 2, item.label, styles, mnemonic=letters[offset]
            )
            right = SUBMENU_MARK if item.submenu is not None else item.shortcut
            if right:
                canvas.write(row, left + inner - len(right), right, styles[0])
        frame_row(
            rect.bottom - 1, border.bottom_left, border.horizontal, border.bottom_right
        )

    # Input

    def _menu_for_mnemonic(self, letter: str) -> int | None:
        """The bar menu with a letter, if any.

        :param letter: The letter.
        """
        letters = _letters([menu.title for menu in self.menus])
        if letter in letters and letters.index(letter) not in self.inert:
            return letters.index(letter)
        return None

    def _mnemonic_menu(self, key: str) -> int | None:
        """The menu a mnemonic shortcut opens, if any.

        :param key: The key.
        """
        for modifier in self.shortcuts.keys("menu_mnemonic_modifiers"):
            prefix = modifier + "+"
            if key.startswith(prefix) and len(key) == len(prefix) + 1:
                return self._menu_for_mnemonic(key[-1].lower())
        return None

    def handle_key(self, key: str) -> bool:
        """Handle a key; return whether used.

        :param key: The key.
        """
        if not self.menus:
            return False
        if self._open is None:
            if self.shortcuts.matches("open_menu", key):
                self.open(0, step=1)  # the first that is not inert
                return True
            index = self._mnemonic_menu(key)
            if index is not None:
                self.open(index)
                return True
            item = self.item_for_shortcut(key)
            if item is not None:
                self._choose_by_key(item, key)
                return True
            return False
        self._handle_open_key(key)
        return True  # an open menu takes all keys

    def _navigate(self, key: str) -> bool:
        """Move about the open menus; return whether used.

        :param key: The key.
        """
        assert self._open is not None
        shortcuts = self.shortcuts
        if shortcuts.matches("open_menu", key):
            self.close()
        elif shortcuts.matches("menu_close", key):
            if not self.close_submenu():
                self.close()
        elif shortcuts.matches("menu_left", key):
            if not self.close_submenu():
                self._step_along_bar(-1)
        elif shortcuts.matches("menu_right", key):
            if not self.open_submenu():
                self._step_along_bar(1)
        elif shortcuts.matches("menu_up", key):
            self._move_highlight(-1)
        elif shortcuts.matches("menu_down", key):
            self._move_highlight(1)
        else:
            return False
        return True

    def _handle_open_key(self, key: str) -> None:
        shortcuts = self.shortcuts
        mnemonic_menu = self._mnemonic_menu(key)
        if self._navigate(key):
            pass
        elif shortcuts.matches("menu_choose", key):
            highlight = self._levels[-1].highlight
            if highlight is not None:
                self._activate(len(self._levels) - 1, highlight)
        elif mnemonic_menu is not None:
            self.open(mnemonic_menu)
        elif (item := self.item_for_shortcut(key)) is not None:
            self._choose_by_key(item, key)
        elif len(key) == 1:
            self._handle_letter(key.lower())

    def _handle_letter(self, letter: str) -> None:
        """Choose by letter in the open menus.

        :param letter: The letter.
        """
        for depth in range(len(self._levels) - 1, -1, -1):
            menu = self._levels[depth].menu
            for index, mnemonic in enumerate(menu.mnemonics()):
                if mnemonic == letter and menu.items[index].is_available:
                    self._activate(depth, index)
                    return
        bar_index = self._menu_for_mnemonic(letter)
        if bar_index is not None and bar_index != self._open:
            self.open(bar_index)

    def item_for_shortcut(self, key: str) -> MenuItem | None:
        """The enabled item with this shortcut, if any.

        :param key: The key.
        """
        if len(key) == 1:
            return None
        hint = pretty_key(key).lower()
        seen: set[int] = set()

        def search(menus: Sequence[Menu]) -> MenuItem | None:
            for menu in menus:
                if id(menu) in seen:
                    continue  # a menu that is its own submenu, somewhere
                seen.add(id(menu))
                for item in menu.items:
                    if item.is_available and item.shortcut.lower() == hint:
                        return item
                    if item.submenu is None or not item.is_available:
                        continue  # a greyed-out item's submenu is shut
                    if found := search([item.submenu]):
                        return found
            return None

        return search(
            [menu for index, menu in enumerate(self.menus) if index not in self.inert]
        )

    def _title_at(self, row: int, column: int) -> int | None:
        """The bar position of the title at a place, if any.

        :param row: Screen row.
        :param column: Screen column.
        """
        for index, span in enumerate(self.title_spans):
            if span.contains(row, column):
                return index
        return None

    def _items_rect(self, rect: Rect) -> Rect:
        """A drop-down's inner area.

        :param rect: The drop-down's rect.
        """
        pad = self.frame_padding
        return Rect(
            rect.row + 1,
            rect.column + pad + 1,
            rect.height - 2,
            rect.width - 2 - 2 * pad,
        )

    def _item_at(self, event: MouseEvent, columns: int) -> tuple[int, int] | None:
        """The (level, item) under the pointer, or ``None``.

        :param event: The mouse event.
        :param columns: Screen width.
        """
        rects = self.level_rects(columns)
        for depth in range(len(rects) - 1, -1, -1):
            rect = rects[depth]
            if self._items_rect(rect).contains(event.row, event.column):
                return depth, event.row - rect.row - 1
            if rect.contains(event.row, event.column):
                return None  # on this menu's frame: not the ones beneath
        return None

    def _hover(self, depth: int, index: int) -> None:
        """Highlight the hovered item.

        :param depth: The level.
        :param index: Item index.
        """
        level = self._levels[depth]
        item = level.menu.items[index]
        if not item.is_available:
            del self._levels[depth + 1 :]
            return  # disabled items are never highlighted
        already = (
            len(self._levels) > depth + 1
            and level.highlight == index
            and self._levels[depth + 1].menu is item.submenu
        )
        if already:
            return  # its submenu is open already: leave it as it is
        del self._levels[depth + 1 :]
        level.highlight = index
        if item.submenu is not None:
            self.open_submenu()

    def handle_mouse(self, event: MouseEvent, columns: int) -> bool:
        """Handle a mouse event; return whether used.

        :param event: The mouse event.
        :param columns: Screen width.
        """
        left = event.button == "left"
        if event.row == 0 and event.action == "press" and left:
            title = self._title_at(event.row, event.column)
            if title is None or title == self._open:
                self.close()
            elif title not in self.inert:
                self.open(title)
            return True
        if self._open is None:
            return False
        title = self._title_at(event.row, event.column)
        found = self._item_at(event, columns)
        if event.action in ("move", "drag"):
            if title is not None and title != self._open and title not in self.inert:
                self.open(title)
            elif found is not None:
                self._hover(*found)
        elif event.action == "press" and left:
            if found is not None:
                self._activate(*found)
            elif not any(
                rect.contains(event.row, event.column)
                for rect in self.level_rects(columns)
            ):
                self.close()
        elif event.action == "release" and left and found is not None:
            depth, index = found
            item = self._levels[depth].menu.items[index]
            if item.submenu is None:
                self._activate(depth, index)
        return True  # an open menu takes all mouse input
