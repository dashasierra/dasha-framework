"""Tabs: pages of widgets sharing the same place, with a row of tabs to
choose which page is shown."""

from collections.abc import Callable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.menu import mnemonic_key, split_mnemonic
from dasha.shortcuts import Shortcuts
from dasha.style import Style
from dasha.widgets.base import Widget, run_shortcut
from dasha.widgets.container import Container
from dasha.widgets.label import on_window, paint_mnemonic_label

DIVIDER = "\N{BOX DRAWINGS LIGHT VERTICAL}"
LINE = "\N{BOX DRAWINGS LIGHT HORIZONTAL}"
JOIN = "\N{BOX DRAWINGS LIGHT UP AND HORIZONTAL}"
"""``│`` between the tabs, ``─`` below them, and ``┴`` where the two meet
(code page 437 glyphs 179, 196 and 193)."""
OPEN_LEFT = "\N{BOX DRAWINGS LIGHT UP AND LEFT}"
OPEN_RIGHT = "\N{BOX DRAWINGS LIGHT UP AND RIGHT}"
"""``┘`` and ``└``, which turn the line below up into the chosen tab's sides,
so that the tab opens onto its page (code page 437 glyphs 217 and 192)."""


class TabPage(Container):
    """One page of a ``Tabs`` widget, whose widgets are shown while it is the
    selected page. Pages are created by ``Tabs.add_page``, and ``add`` puts a
    widget on the page, positioned relative to the area below the row of
    tabs."""

    noun = "tabs"

    def __init__(self, tabs: "Tabs", label: str) -> None:
        super().__init__()
        self.tabs = tabs
        self.label = label
        """The tab's text, ``&`` marking its mnemonic letter."""

    @property
    def anchor(self) -> Widget:
        return self.tabs

    @property
    def is_showing_children(self) -> bool:
        return self.tabs.selected_page is self

    def content_origin(self) -> tuple[int, int]:
        return self.home_row + 2, self.tabs.rect.column


class Tabs(Widget):  # pylint: disable=too-many-instance-attributes
    """``Tabs`` shows several pages of widgets in the same place, with a row of
    tabs above them to choose which page is shown, as a properties dialog does:

    ::

         General │ Account │
        ─────────┘         └──────────────
         (the chosen page's widgets)

    ::

        tabs = dialog.add(Tabs(1, 2, 50, 13))
        general = tabs.add_page("&General")
        general.add(CheckBoxes(["&Window shadows"], 0, 1))
        account = tabs.add_page("Accou&nt")
        account.add(PasswordBox(1, 11, 30, name="password"))

    Each page is a container (a ``TabPage``; see Containers).
    ``page.add(widget)`` places a widget relative to the area below the tabs,
    and only the selected page's widgets are shown. The widgets of every page
    are included in ``dialog.values``.

    - Left / Right, on the tabs (``tabs_left`` / ``tabs_right``): choose the
      neighbouring tab
    - Ctrl+PgDn / Ctrl+PgUp, anywhere in the window (``tabs_next`` /
      ``tabs_previous``): choose the next / previous page, wrapping round from
      the last to the first
    - A click on a tab, or its letter: choose that tab

    Tab moves the focus from the tabs into the selected page's widgets, and
    then onwards. Choosing another page while the focus was on the previous
    page moves the focus to the tabs. ``value`` (and ``selected``) is the selected
    page's number, and ``selected_page`` is the page itself. ``select(index)`` and
    ``step(step=1)`` choose a page as the user does, and ``on_change(tabs)`` is
    called for every change the user makes. The colours are ``tabs`` (the tabs
    not selected, and the lines), ``tabs.selected`` and ``tabs.focused``;
    colours left as ``default`` are the window's.
    """

    focusable = True
    style: Style = Style()
    """The style of the tabs not selected, and of the lines."""
    selected_style: Style = Style(bold=True)
    """The style of the selected tab."""
    focused_style: Style = Style(bold=True, reverse=True)
    """The style of the selected tab, while the tabs have the focus."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        row: int,
        column: int,
        width: int,
        height: int,
        *,
        on_change: Callable[["Tabs"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        if height < 3:
            raise ValueError("tabs need a row for the tabs, a line and a page")
        super().__init__(row, column, width, height, name=name, status=status)
        self.pages: list[TabPage] = []
        """The pages, in the order of their tabs."""
        self.on_change = on_change
        self._index = 0

    # The pages

    def add_page(self, label: str) -> TabPage:
        """Add a page, with its tab last (``&`` marks a mnemonic letter in the
        label)."""
        page = TabPage(self, label)
        self.pages.append(page)
        return page

    @property
    def selected(self) -> int:
        """The number of the selected page."""
        return self._index

    @property
    def value(self) -> int:
        return self._index

    @property
    def selected_page(self) -> TabPage | None:
        """The selected page (``None`` before any page has been added)."""
        return self.pages[self._index] if self.pages else None

    def help_topic(self) -> str | None:
        """The help topic of the selected page, if it has one, since that is
        what the tabs are showing; otherwise, as for any widget, ``help``."""
        page = self.selected_page
        return page.help if page is not None and page.help else self.help

    def select(self, index: int) -> None:
        """Choose a page as the user does, calling ``on_change`` if the page
        changed. If the focus was on the previous page, it moves to the
        tabs."""
        if not self.pages:
            return
        index = max(0, min(index, len(self.pages) - 1))
        if index == self._index:
            return
        self._index = index
        window = self.window
        if window is not None:
            focused = window.focused
            if focused is not None and not focused.is_shown:
                window.focus(self)
        if self.on_change is not None:
            self.on_change(self)

    def step(self, step: int) -> None:
        """Choose the page ``step`` places on, wrapping round from the last to
        the first."""
        if self.pages:
            self.select((self._index + step) % len(self.pages))

    # Where each tab is

    def _spans(self) -> list[tuple[int, int]]:
        """Each tab's (first column, width) along the row, relative to the
        widget: `` Label `` and then a divider."""
        spans, column = [], 0
        for page in self.pages:
            width = len(split_mnemonic(page.label)[0]) + 2
            spans.append((column, width))
            column += width + 1
        return spans

    def tab_at(self, column: int) -> int | None:
        """The tab at a column of the window's content, if there is one."""
        offset = column - self.rect.column
        for number, (first, width) in enumerate(self._spans()):
            if first <= offset < first + width:
                return number
        return None

    def min_size(self) -> tuple[int, int]:
        return 1, 3

    # Drawing and input

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        body = self.window.body_style if self.window is not None else Style()
        plain = on_window(self.style, body)
        chosen = on_window(self.focused_style if focused else self.selected_style, body)
        at = (origin.row + self.rect.row, origin.column + self.rect.column)
        width = self.rect.width
        canvas.write(at[0], at[1], " " * width, plain, clip=origin)
        line = [LINE] * width
        for number, span in enumerate(self._spans()):
            if span[0] >= width:
                break
            style = chosen if number == self._index else plain
            self._paint_tab(
                canvas, origin, at=at, number=number, span=span, styles=(style, plain)
            )
            divider = span[0] + span[1]
            if divider < width:
                line[divider] = JOIN
            if number == self._index:
                for column in range(span[0], min(divider, width)):
                    line[column] = " "  # the chosen tab opens onto its page
                if 0 < span[0] <= width:
                    line[span[0] - 1] = OPEN_LEFT
                if divider < width:
                    line[divider] = OPEN_RIGHT
        canvas.write(at[0] + 1, at[1], "".join(line), plain, clip=origin)

    def _paint_tab(
        self,
        canvas: Canvas,
        origin: Rect,
        *,
        at: tuple[int, int],
        number: int,
        span: tuple[int, int],
        styles: tuple[Style, Style],
    ) -> None:
        """One tab, `` Label ``, in its style, and the divider after it in
        the plain one, as far as the widget's width allows."""
        (row, left), (first, length), width = at, span, self.rect.width
        style, plain = styles
        canvas.write(row, left + first, " ", style, clip=origin)
        paint_mnemonic_label(
            canvas,
            origin,
            (row, left + first + 1),
            self.pages[number].label,
            style,
            width=min(length - 2, width - first - 1),
        )
        if first + length - 1 < width:
            canvas.write(row, left + first + length - 1, " ", style, clip=origin)
        if first + length < width:
            canvas.write(row, left + first + length, DIVIDER, plain, clip=origin)

    def mnemonics(self) -> set[str]:
        return {
            letter
            for page in self.pages
            if (letter := mnemonic_key(page.label)) is not None
        }

    def activate_mnemonic(self, letter: str) -> None:
        for number, page in enumerate(self.pages):
            if mnemonic_key(page.label) == letter:
                self.select(number)
                return

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Left and Right choose the neighbouring tab."""
        actions: dict[str, Callable[[], object]] = {
            "tabs_left": lambda: self.select(self._index - 1),
            "tabs_right": lambda: self.select(self._index + 1),
        }
        return run_shortcut(shortcuts, key, actions)

    def window_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Ctrl+PgDn and Ctrl+PgUp choose the next or previous page."""
        actions: dict[str, Callable[[], object]] = {
            "tabs_next": lambda: self.step(1),
            "tabs_previous": lambda: self.step(-1),
        }
        return bool(self.pages) and run_shortcut(shortcuts, key, actions)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """A press on a tab chooses it; presses on the rest of the widget,
        beneath its page's widgets, are not used up."""
        if event.button != "left" or row != self.rect.row:
            return False
        if event.action == "press":
            index = self.tab_at(column)
            if index is None:
                return False
            self.select(index)
        return event.action in ("press", "drag", "release")
