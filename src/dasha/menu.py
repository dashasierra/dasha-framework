"""Drop-down menus and the menu bar along the top of the screen.

Menu titles and item labels can mark a mnemonic letter with ``&``, as in
``"&File"`` or ``"E&xit"``. The letter is highlighted; Alt with that letter
opens a menu from the bar, and pressing the letter in an open menu chooses
the item. Write ``&&`` for a literal ampersand. The keys that operate the
menus come from ``dasha.shortcuts``, so users can remap them.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from dasha.border import SINGLE, Border
from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.shortcuts import Shortcuts, pretty_key
from dasha.style import BLACK, BRIGHT_BLACK, GREEN, RED, SHADOW, WHITE, Style

SEPARATOR_LEFT = "\N{BOX DRAWINGS LIGHT VERTICAL AND RIGHT}"
SEPARATOR_RIGHT = "\N{BOX DRAWINGS LIGHT VERTICAL AND LEFT}"


def split_mnemonic(label: str) -> tuple[str, int | None]:
    """Return a label without its ``&`` marker, together with the index of
    its mnemonic letter."""
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
    """The mnemonic letter of a label, in lower case, if it has one."""
    text, index = split_mnemonic(label)
    return None if index is None else text[index].lower()


class DuplicateMnemonicError(ValueError):
    """Two items of one menu, or two titles on the menu bar, mark the same
    mnemonic letter (raised by ``Menu.check_mnemonics`` and
    ``unique_mnemonics(..., strict=True)``)."""


def unique_mnemonics(
    labels: Iterable[str], *, strict: bool = False
) -> list[int | None]:
    """Where each label's mnemonic letter is, as ``split_mnemonic`` gives it,
    except that a letter can only be used once: the first label to mark it
    keeps it, and any later label marking the same letter (in either case)
    is treated as having none, so its letter is neither highlighted nor
    pressed. With ``strict``, a repeated letter raises
    ``DuplicateMnemonicError`` instead."""
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
    """Each label's mnemonic letter, in lower case, as ``unique_mnemonics``
    leaves them: ``None`` for a label with none, or with a repeated one."""
    return [
        None if index is None else split_mnemonic(label)[0][index].lower()
        for label, index in zip(labels, unique_mnemonics(labels))
    ]


SUBMENU_MARK = "\N{BLACK RIGHT-POINTING POINTER}"
"""``►`` (code page 437 glyph 16), shown on the right of an item that has
a submenu."""


@dataclass
class MenuItem:
    """One choice in a menu.

    When chosen, an item runs its ``action``, or opens its ``submenu``
    (a ``Menu`` of its own, which can have submenus too), in which case it
    is shown with ``►`` on its right. An item with neither is greyed out,
    including its shortcut, and can be neither chosen nor highlighted.

    ``shortcut`` is shown on the right, written in the style of
    ``pretty_key`` (``"Ctrl+Q"``, ``"Alt+F3"``). Pressing that key chooses
    the item, whether or not its menu is open, including for items in
    submenus (except for single characters). ``status`` is optional help
    shown on the status bar while the item is highlighted, such as
    ``"Opens a file"``. ``enabled``, if given, is called each time the menu
    is shown or the item is chosen, and the item is greyed out whenever it
    returns false; for example, ``enabled=app.has_window`` for an item that
    needs a window.
    """

    label: str
    action: Callable[[], object] | None = None
    shortcut: str = ""
    status: str = ""
    is_separator: bool = False
    submenu: "Menu | None" = None
    enabled: Callable[[], bool] | None = None

    @property
    def is_available(self) -> bool:
        """Whether the item can be chosen (or its submenu opened) at the
        moment."""
        if self.is_separator or (self.action is None and self.submenu is None):
            return False
        return self.enabled is None or bool(self.enabled())


def separator() -> MenuItem:
    """A dividing line between groups of items."""
    return MenuItem("", is_separator=True)


@dataclass
class Menu:
    """A list of items with a title, shown as a drop-down from the menu bar,
    or as a submenu beside the item that opens it.

    ``items`` is an ordinary list, so items can be added or removed at any
    time.

    Each mnemonic letter belongs to one item: if two items mark the same
    letter, the first keeps it and the later one is shown and treated as
    if it had none (``mnemonics``). ``check_mnemonics`` raises
    ``DuplicateMnemonicError`` instead, for catching such a mistake in a
    test.
    """

    title: str
    items: list[MenuItem] = field(default_factory=list)
    lists_minimised: bool = False
    """Whether the presentation manager adds its minimised windows to the
    end of this menu, so that they can be restored from it, when there is no
    system menu to list them in. A Window menu does this."""
    on_open: "Callable[[Menu], object] | None" = None
    """Called with the menu just before it opens, from the menu bar or as a
    submenu, to bring its items up to date. For example, the system menu's
    Themes uses it to list the theme files present at that moment."""
    after_window: bool = False
    """Whether the menu bar shows this menu, one of an application's
    ``menus``, after the Window menu that Dasha Framework adds, rather than before
    it, as a Help menu usually is."""

    def mnemonics(self) -> list[str | None]:
        """Each item's mnemonic letter, in lower case, in the order of
        ``items``: ``None`` for an item (or separator) without one, and for
        an item whose letter an earlier item already has."""
        return _letters([item.label for item in self.items])

    def check_mnemonics(self) -> None:
        """Raise ``DuplicateMnemonicError`` if two of the items mark the
        same mnemonic letter, in this menu or in any submenu opened from it
        (each submenu is checked on its own, since its letters only work
        while it is open). Each menu's ``on_open`` is called first, so that
        items it fills in are checked as they would be shown."""
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
    """One open menu: the drop-down from the bar, or a submenu of it."""

    menu: Menu
    highlight: int | None = None
    """The highlighted item: always an enabled one, or ``None`` when the
    menu has nothing that can be chosen."""


class MenuBar:  # pylint: disable=too-many-public-methods
    """The bar of menu titles along the top row, together with the open
    drop-down and any submenus opened from it.

    The bar does not own its menus: the presentation manager gives it the
    current list (``set_menus``) whenever the list may have changed. While a
    menu is open, the bar takes all keyboard and mouse input. Its appearance
    is set by class attributes, so a subclass can restyle it.

    The open menus form levels: the drop-down is the first level, a submenu
    opened from it the next, and so on. A submenu opens beside its item,
    lined up with it: to the right if it fits, and otherwise to the left,
    moved up or inwards as needed to stay on the screen.
    """

    bar_style: Style = Style(foreground=BLACK, background=WHITE)
    mnemonic_style: Style = Style(foreground=RED, background=WHITE)
    selected_style: Style = Style(foreground=BLACK, background=GREEN)
    selected_mnemonic_style: Style = Style(foreground=RED, background=GREEN)
    disabled_style: Style = Style(foreground=BRIGHT_BLACK, background=WHITE)
    border: Border = SINGLE
    frame_padding: int = 1
    """How many blank columns there are outside each side of the
    drop-down's frame (``" │ Open │ "``)."""

    shadow_style: Style | None = SHADOW
    """The style of the open drop-down's shadow, like a window's; ``None``
    for no shadow. The bar itself casts no shadow."""
    shadow_width: int = 2
    shadow_height: int = 1

    def __init__(self, shortcuts: Shortcuts | None = None) -> None:
        self.shortcuts = shortcuts if shortcuts is not None else Shortcuts()
        self.menus: list[Menu] = []
        self.lines = 24
        """The screen's height, for keeping submenus on it (the presentation
        manager keeps it up to date)."""
        self._open: int | None = None
        self._levels: list[_Level] = []
        self.shortcut_key: str | None = None
        """While an item chosen by its shortcut runs: the key pressed (an
        item's action can pass it on; ``None`` otherwise)."""
        self.inert: frozenset[int] = frozenset()
        """The menus (by place on the bar) that are shown but cannot be
        opened: an application's, while one of its dialogs waits."""

    # State

    def set_menus(self, menus: Sequence[Menu], inert: Iterable[int] = ()) -> None:
        """Show these menus. Those at the positions in ``inert`` are shown,
        but cannot be opened by key or mouse, and their shortcuts do not
        work. An open menu is closed if the list has changed, or if it has
        become inert."""
        if len(menus) != len(self.menus) or any(
            new is not old for new, old in zip(menus, self.menus)
        ):
            self.menus = list(menus)
            self.close()
        self.inert = frozenset(inert)
        if self._open is not None and self._open in self.inert:
            self.close()

    def check_mnemonics(self) -> None:
        """Raise ``DuplicateMnemonicError`` if two menu titles on the bar
        mark the same letter, or if any of the menus fails
        ``Menu.check_mnemonics``. Shown as they are, a repeated letter goes
        to the first title or item with it, and the others have none."""
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
        """The highlighted item of the innermost open menu, if any. Only an
        enabled item is ever highlighted."""
        if not self._levels:
            return None
        return self._item(len(self._levels) - 1)

    def _item(self, depth: int) -> MenuItem | None:
        """The highlighted item of one level, if any."""
        level = self._levels[depth]
        index = level.highlight
        if index is None or index >= len(level.menu.items):
            return None
        item = level.menu.items[index]
        return item if item.is_available else None

    def open(self, index: int, step: int = 0) -> None:
        """Open the drop-down of the menu at ``index``, closing any other. An
        inert menu is not opened; with ``step`` (1 or -1, for moving along
        the bar), the next menu in that direction that is not inert is
        opened instead."""
        count = len(self.menus)
        index %= count
        if step:
            for _ in range(count):
                if index not in self.inert:
                    break
                index = (index + step) % count
        if index in self.inert:
            return
        self._open = index
        menu = self.menus[self._open]
        if menu.on_open is not None:
            menu.on_open(menu)
        self._levels = [_Level(menu)]
        self._move_highlight(1)  # to the first item that can be chosen

    def close(self) -> None:
        """Close any open drop-down, along with its submenus."""
        self._open = None
        self._levels = []

    def open_submenu(self) -> bool:
        """Open the submenu of the innermost highlighted item. Returns
        ``False`` if the item has no submenu."""
        item = self.highlighted
        if item is None or item.submenu is None:
            return False
        if item.submenu.on_open is not None:
            item.submenu.on_open(item.submenu)
        self._levels.append(_Level(item.submenu))
        self._move_highlight(1)
        return True

    def close_submenu(self) -> bool:
        """Close the innermost submenu. Returns ``False`` if only the
        drop-down is open."""
        if len(self._levels) <= 1:
            return False
        self._levels.pop()
        return True

    def choose(self, item: MenuItem) -> None:
        """Close the menus and run an item's action, if the item is enabled."""
        if item.is_available and item.action is not None:
            self.close()
            item.action()

    def _choose_by_key(self, item: MenuItem, key: str) -> None:
        """Choose an item by its shortcut, ``shortcut_key`` saying which."""
        self.shortcut_key = key
        try:
            self.choose(item)
        finally:
            self.shortcut_key = None

    def _activate(self, depth: int, index: int) -> None:
        """Choose item ``index`` of level ``depth``: open its submenu, or
        run it. Any submenus open beyond that level close first."""
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
        """Move the innermost highlight to the next enabled item in the
        direction of ``step``, wrapping round. Separators and disabled items
        are skipped; if nothing can be chosen, nothing is highlighted."""
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
        """How wide a menu's box is: its labels, shortcuts or ``►``, frame
        and padding (and, for a drop-down, room for its title)."""
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
        """Where each open menu is drawn on a screen of the given size: the
        drop-down below its title, and each submenu beside the item that
        opened it, to its right if there is room and otherwise to its left,
        always kept on the screen."""
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
        """Where the open drop-down is drawn on a screen of the given width."""
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
        mnemonic: int | None,
    ) -> None:
        """Write a label, its mnemonic letter (at ``mnemonic``, as
        ``unique_mnemonics`` gives it) in the second style."""
        text = split_mnemonic(label)[0]
        canvas.write(row, column, text, styles[0])
        if mnemonic is not None:
            canvas.write(row, column + mnemonic, text[mnemonic], styles[1])

    def dropping_rect(self, rect: Rect, shown: float) -> Rect:
        """Where a drop-down at ``rect`` is drawn while it is dropping down:
        moved up under the bar, so that only the fraction ``shown`` of it
        (from 0 to 1, but always at least one row) has come out below the
        bar."""
        rows = max(1, min(rect.height, round(rect.height * shown)))
        return Rect(
            rect.row - (rect.height - rows), rect.column, rect.height, rect.width
        )

    def _shown_rects(self, canvas: Canvas, shown: float) -> list[Rect]:
        """``level_rects``; while the drop-down drops (``shown`` under 1),
        just the drop-down, part of the way out."""
        rects = self.level_rects(canvas.width, canvas.height)
        if rects and shown < 1:
            return [self.dropping_rect(rects[0], shown)]
        return rects

    def paint(self, canvas: Canvas, shown: float = 1) -> None:
        """Paint the bar on the top row, the open drop-down below it, and its
        submenus, each with its shadow (which never falls on the status
        bar).

        With ``shown`` below 1, the drop-down is part-way through dropping
        down from the bar (``PresentationManager.animations``): only that
        fraction of it has come out from under the bar, and its submenus are
        not drawn yet."""
        canvas.fill(Rect(0, 0, 1, canvas.width), " ", self.bar_style)
        letters = unique_mnemonics(menu.title for menu in self.menus)
        for index, (menu, span) in enumerate(zip(self.menus, self.title_spans)):
            if index == self._open:
                styles = (self.selected_style, self.selected_mnemonic_style)
            else:
                styles = (self.bar_style, self.mnemonic_style)
            canvas.fill(span, " ", styles[0])
            self._write_label(
                canvas, 0, span.column + 1, menu.title, styles, letters[index]
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
        """Darken the area under the open drop-down's shadow, keeping what
        lies beneath, with the drop-down the fraction ``shown`` of the way
        out, as in ``paint``.

        This is separate from ``paint`` so that the presentation manager
        can paint the status bar in between, because shadows never fall on
        the status bar.
        """
        rects = self._shown_rects(canvas, shown)
        if rects and self.shadow_style is not None:
            canvas.cast_shadow(
                rects[0], self.shadow_style, self.shadow_width, self.shadow_height
            )

    def _paint_level(self, canvas: Canvas, level: _Level, rect: Rect) -> None:
        border, style = self.border, self.bar_style
        pad = " " * self.frame_padding
        left = rect.column + self.frame_padding  # where the frame starts
        inner = rect.width - 2 - 2 * self.frame_padding

        def frame_row(row: int, left_char: str, fill: str, right_char: str) -> None:
            canvas.write(
                row,
                rect.column,
                pad + left_char + fill * inner + right_char + pad,
                style,
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
                canvas, row, left + 2, item.label, styles, letters[offset]
            )
            right = SUBMENU_MARK if item.submenu is not None else item.shortcut
            if right:
                canvas.write(row, left + inner - len(right), right, styles[0])
        frame_row(
            rect.bottom - 1, border.bottom_left, border.horizontal, border.bottom_right
        )

    # Input

    def _menu_for_mnemonic(self, letter: str) -> int | None:
        """The menu on the bar with this letter, if any (only the first
        title to mark a letter has it), unless that menu is inert."""
        letters = _letters([menu.title for menu in self.menus])
        if letter in letters and letters.index(letter) not in self.inert:
            return letters.index(letter)
        return None

    def _mnemonic_menu(self, key: str) -> int | None:
        """The menu a mnemonic shortcut (such as Alt+F) opens, if any."""
        for modifier in self.shortcuts.keys("menu_mnemonic_modifiers"):
            prefix = modifier + "+"
            if key.startswith(prefix) and len(key) == len(prefix) + 1:
                return self._menu_for_mnemonic(key[-1].lower())
        return None

    def handle_key(self, key: str) -> bool:
        """Handle a key, and return whether the menu bar used it."""
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
        """The keys that move about the open menus; whether ``key`` was one.
        Escape and Left go back a submenu at a time (Left, from the
        drop-down, to the menu before); Right opens a submenu, or the next
        menu; F10 closes them all."""
        assert self._open is not None
        shortcuts = self.shortcuts
        if shortcuts.matches("open_menu", key):
            self.close()
        elif shortcuts.matches("menu_close", key):
            if not self.close_submenu():
                self.close()
        elif shortcuts.matches("menu_left", key):
            if not self.close_submenu():
                self.open(self._open - 1, step=-1)
        elif shortcuts.matches("menu_right", key):
            if not self.open_submenu():
                self.open(self._open + 1, step=1)
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
        """A plain letter while menus are open: the innermost open submenu
        with an enabled item of that letter wins, then each menu out from
        it, then a menu on the bar with that letter. Submenus that are not
        showing do not count, nor do disabled items, nor items whose letter
        an earlier item in the same menu already has; otherwise the letter is
        ignored."""
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
        """The enabled item, in any menu or submenu, whose ``shortcut`` names
        this key (``"Alt+F3"`` for ``"alt+f3"``), so that the shortcut a menu
        shows works whether or not the menu is open. Plain characters never
        count, because they are used for typing and for choosing items by
        their letters."""
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
        """The index of the menu whose title is at a position, if any."""
        for index, span in enumerate(self.title_spans):
            if span.contains(row, column):
                return index
        return None

    def _items_rect(self, rect: Rect) -> Rect:
        """The part of a drop-down inside its frame (and padding)."""
        pad = self.frame_padding
        return Rect(
            rect.row + 1,
            rect.column + pad + 1,
            rect.height - 2,
            rect.width - 2 - 2 * pad,
        )

    def _item_at(self, event: MouseEvent, columns: int) -> tuple[int, int] | None:
        """The (level, item) under the pointer, the innermost menu first, as
        it is drawn on top; ``None`` if over no item."""
        rects = self.level_rects(columns)
        for depth in range(len(rects) - 1, -1, -1):
            rect = rects[depth]
            if self._items_rect(rect).contains(event.row, event.column):
                return depth, event.row - rect.row - 1
            if rect.contains(event.row, event.column):
                return None  # on this menu's frame: not the ones beneath
        return None

    def _hover(self, depth: int, index: int) -> None:
        """The pointer moved onto an item: highlight it, closing any
        submenus beyond its menu, and open its own submenu."""
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
        """Handle a mouse event, and return whether the menu bar used it.

        A click on a title opens its menu (or closes it, if it is already
        open). A click on an enabled item chooses it or opens its submenu,
        and so does releasing the button over an item after dragging down
        from the title. While a menu is open, moving over an item highlights
        it (and opens its submenu), moving over another title opens that
        menu, and a click anywhere else closes the menus.
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
