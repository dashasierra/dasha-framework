"""Markdown help windows."""

import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

from dasha.canvas import Canvas, Rect
from dasha.clipboard import CLIPBOARD, TEXT, ClipboardItem
from dasha.dialog import Dialog, Popup
from dasha.events import MouseEvent
from dasha.markdown import (
    BOLD,
    CODE,
    EMPHASIS,
    HEADING,
    LINK,
    Block,
    Document,
    Span,
    lay_out,
    parse,
    sections,
    title_of,
)
from dasha.protocol import WINDOW_STYLES
from dasha.shortcuts import Shortcuts
from dasha.style import (
    BLACK,
    BLUE,
    BRIGHT_BLACK,
    BRIGHT_WHITE,
    BRIGHT_GREEN,
    CYAN,
    WHITE,
    Style,
)
from dasha.widgets import Button, Grow, Label, ScrollBar, TextBox, Widget
from dasha.widgets.base import run_shortcut
from dasha.widgets.container import ancestors
from dasha.window import Window

if TYPE_CHECKING:
    from dasha.manager import PresentationManager

DESKTOP_PAGES = Path(__file__).parent / "helppages"
"""Dasha Framework's desktop help pages.

:meta hide-value:
"""

INDEX = "index"
"""The topic of the default page: ``index.md``."""

MAX_PAGE = 1024 * 1024
"""The most of a page's file that is read, in bytes."""
MAX_TOPICS = 1000
"""The most pages that a search looks through."""
MAX_RESULTS = 100
"""The most topics that a search lists."""
MAX_HISTORY = 100
"""How many pages back ``HelpView`` remembers."""

HELP_WIDTH = 66
"""How wide a help window opens, if the screen has room."""
HELP_HEIGHT = 20
"""How tall a help window opens, if the screen has room."""

_SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]+:")


def is_external(target: str) -> bool:
    """Whether a link leaves the help.

    :param target: The link target.
    """
    return target.startswith("//") or _SCHEME.match(target) is not None


def resolve_link(current: str, target: str) -> tuple[str, str]:
    """A link's (topic, heading slug).

    :param current: The page linking.
    :param target: The link target.
    """
    path, _, anchor = target.partition("#")
    path = unquote(path).replace("\\", "/")
    if not path:
        return current, anchor
    if path.endswith(".md"):
        path = path[: -len(".md")]
    if path.startswith("/"):
        return posixpath.normpath(path.lstrip("/")), anchor
    return posixpath.normpath(posixpath.join(posixpath.dirname(current), path)), anchor


def _escaped(text: str) -> str:
    """Text escaped for Markdown.

    :param text: The text.
    """
    return re.sub(r"([\\`*_\[\]<>&!#|-])", r"\\\1", " ".join(text.split()))


def _page_link(topic: str, slug: str = "") -> str:
    """A link target for a topic.

    :param topic: The topic.
    :param slug: Heading slug.
    """
    return "/" + quote(topic) + ".md" + (f"#{slug}" if slug else "")


@dataclass(frozen=True)
class SearchResult:
    """A page that a search found."""

    topic: str
    title: str
    """The page's first heading, or its topic if it has none."""
    slug: str
    """Heading slug above the first match."""
    context: str
    """The line of the first match."""
    in_title: bool
    """Whether the page's title has one of the words."""
    count: int
    """How many times the words appear in the page."""


class HelpBook:
    """A folder of Markdown pages.

    :param folder: The folder.
    """

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)

    def _path(self, topic: str) -> Path | None:
        """A topic's file, if in the folder.

        :param topic: The topic.
        """
        try:
            root = self.folder.resolve()
            path = (root / f"{topic}.md").resolve()
            return path if path.is_relative_to(root) and path.is_file() else None
        except (OSError, ValueError):
            return None

    def topics(self) -> list[str]:
        """Every page's topic, in order of name (at most ``MAX_TOPICS``)."""
        found = []
        try:
            for path in sorted(self.folder.rglob("*.md"))[:MAX_TOPICS]:
                if path.is_file():
                    topic = path.relative_to(self.folder).with_suffix("")
                    found.append(topic.as_posix())
        except (OSError, ValueError):
            return found
        return found

    def has_topics(self) -> bool:
        """Whether there are any pages."""
        return bool(self.topics())

    def read(self, topic: str) -> str | None:
        """A page's text, or ``None``.

        :param topic: The topic.
        """
        path = self._path(topic)
        if path is None:
            return None
        try:
            with path.open("rb") as file:
                data = file.read(MAX_PAGE)
        except OSError:
            return None
        return data.decode("utf-8-sig", errors="replace")

    def page(self, topic: str) -> str:
        """The text to show for a topic.

        :param topic: The topic.
        """
        text = self.read(topic)
        if text is not None:
            return text
        back = f"\n\n[Go to the index]({_page_link(INDEX)})" if topic != INDEX else ""
        return f"# Topic not found\n\nThere is no help on {_escaped(topic)}.{back}\n"

    def _searched(self, topic: str, words: list[str]) -> SearchResult | None:
        """A search result for a page, or ``None``.

        :param topic: The topic.
        :param words: Words that must all appear.
        """
        text = self.read(topic)
        if text is None:
            return None
        blocks = parse(text)
        parts = sections(blocks)
        whole = "\n".join(f"{part.title}\n{part.text}" for part in parts).casefold()
        if not all(word in whole for word in words):
            return None
        title = title_of(blocks)
        slug, context = "", ""
        for part in parts:
            for line in [part.title, *part.text.splitlines()]:
                if any(word in line.casefold() for word in words):
                    slug, context = part.slug, line
                    break
            if context:
                break
        return SearchResult(
            topic,
            title or topic,
            slug,
            context,
            any(word in title.casefold() for word in words),
            sum(whole.count(word) for word in words),
        )

    def search(self, query: str) -> list[SearchResult]:
        """Pages with every word of a query.

        :param query: The search words.
        """
        words = query.casefold().split()
        if not words:
            return []
        found = [self._searched(topic, words) for topic in self.topics()]
        results = [result for result in found if result is not None]
        results.sort(key=lambda r: (not r.in_title, -r.count, r.title.casefold()))
        return results[:MAX_RESULTS]

    def results_page(self, query: str) -> str:
        """A page of search result links.

        :param query: The search words.
        """
        results = self.search(query)
        said = _escaped(query)
        if not results:
            return f"# Search\n\nNothing was found for {said}.\n"
        count = "1 topic" if len(results) == 1 else f"{len(results)} topics"
        lines = [f"# Search\n\n{count} found for {said}:\n"]
        for result in results:
            link = _page_link(result.topic, result.slug)
            lines.append(f"- [{_escaped(result.title)}]({link})")
            if result.context and result.context != result.title:
                lines[-1] += "  "  # the context goes on a line of its own
                lines.append(f"  {_escaped(result.context)}")
        return "\n".join(lines) + "\n"


@dataclass
class _Place:
    """A history entry and its scroll position."""

    topic: str
    anchor: str = ""
    query: str | None = None
    """What was searched for, if this is a page of results."""
    first: int = 0
    link: int | None = None


# pylint: disable-next=too-many-instance-attributes,too-many-public-methods
class HelpView(Widget):
    """A scrolling help page viewer with history.

    :param book: The help pages.
    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param height: Height in rows.
    :param on_close: Called when closed, if given.
    """

    focusable = True
    wheel_rows = 3
    """How many lines one notch of the mouse wheel scrolls."""
    HEADER = 2
    """How many rows the top row and the line below it take."""
    MARGIN = 1
    """How many columns are left clear on each side of the page."""

    heading_style: Style = Style(foreground=BRIGHT_WHITE, background=CYAN, bold=True)
    """The style of headings."""
    bold_style: Style = Style(foreground=BRIGHT_WHITE, background=CYAN, bold=True)
    """The style of bold text."""
    emphasis_style: Style = Style(foreground=BLACK, background=CYAN, underline=True)
    """The style of italic text, and of the places of images."""
    code_style: Style = Style(foreground=BLACK, background=WHITE)
    """The style of code."""
    link_style: Style = Style(foreground=BLUE, background=CYAN, underline=True)
    """Style of links and usable top-row parts."""
    focused_link_style: Style = Style(
        foreground=BRIGHT_WHITE, background=BLUE, bold=True
    )
    """The style of the highlighted link."""
    disabled_style: Style = Style(foreground=BRIGHT_BLACK, background=CYAN)
    """The parts of the top row that cannot be used now."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        book: HelpBook,
        row: int,
        column: int,
        width: int,
        height: int,
        *,
        on_close: Callable[[], object] | None = None,
    ) -> None:
        super().__init__(row, column, width, height)
        self.book = book
        self.on_close = on_close
        """Called when the key that closes help is pressed."""
        self._history: list[_Place] = []
        self._at = -1
        self._blocks: list[Block] = []
        self._document = Document([], [], {})
        self._laid_width = -1
        self._first = 0
        self._link: int | None = None
        self.scroll_bar = ScrollBar(
            row, column + width - 1, 2, on_change=self._scrolled
        )
        self._bar_mouse = False

    # Where it is

    @property
    def topic(self) -> str | None:
        """The topic shown, if any."""
        place = self._place
        return None if place is None or place.query is not None else place.topic

    @property
    def value(self) -> str | None:
        return self.topic

    @property
    def _place(self) -> _Place | None:
        return self._history[self._at] if self._at >= 0 else None

    @property
    def document(self) -> Document:
        """The page, laid out to the width there is."""
        self._fit()
        return self._document

    @property
    def can_go_back(self) -> bool:
        """Whether there is a page to go back to."""
        return self._at > 0

    @property
    def can_go_forward(self) -> bool:
        """Whether there is a page to go forward to."""
        return self._at < len(self._history) - 1

    @property
    def first_visible(self) -> int:
        """The first line of the page shown."""
        return self._first

    @property
    def focused_link(self) -> int | None:
        """The number of the highlighted link in ``document.links``."""
        return self._link

    @property
    def _rows(self) -> int:
        """How many lines of the page there is room for."""
        return max(0, self.rect.height - self.HEADER)

    @property
    def _text_width(self) -> int:
        """Page layout width."""
        return max(1, self.rect.width - self.MARGIN * 2 - 1)

    def min_size(self) -> tuple[int, int]:
        return 12, 3

    # Going places

    def go(self, topic: str) -> None:
        """Go to a topic.

        :param topic: The topic, optionally with ``#heading``.
        """
        name, _, anchor = topic.partition("#")
        self._visit(_Place(name or INDEX, anchor))

    def go_to_index(self) -> None:
        """Go to the default page."""
        self.go(INDEX)

    def search(self, query: str) -> None:
        """Show search results.

        :param query: The search words.
        """
        if query.split():
            self._visit(_Place("", query=query.strip()))

    def _visit(self, place: _Place) -> None:
        current = self._place
        same = current is not None and (
            (current.topic, current.anchor, current.query)
            == (place.topic, place.anchor, place.query)
        )
        if not same:
            self._remember()
            del self._history[self._at + 1 :]
            self._history.append(place)
            if len(self._history) > MAX_HISTORY:
                del self._history[0]
            self._at = len(self._history) - 1
        self._show(self._history[self._at], restore=False)

    def go_back(self) -> None:
        """Go to the page before, where it was left."""
        if self.can_go_back:
            self._remember()
            self._at -= 1
            self._show(self._history[self._at], restore=True)

    def go_forward(self) -> None:
        """Go to the page after, where it was left."""
        if self.can_go_forward:
            self._remember()
            self._at += 1
            self._show(self._history[self._at], restore=True)

    def _remember(self) -> None:
        """Note how far down the page is, to come back to."""
        place = self._place
        if place is not None:
            place.first, place.link = self._first, self._link

    def _show(self, place: _Place, *, restore: bool) -> None:
        if place.query is not None:
            text = self.book.results_page(place.query)
        else:
            text = self.book.page(place.topic)
        self._blocks = parse(text)
        self._laid_width = -1
        self._fit()
        if restore:
            self._first, self._link = place.first, place.link
        else:
            self._first = self._document.anchors.get(place.anchor, 0)
            self._link = None
        self.scroll_to(self._first)
        self._update_status()

    # Laying out

    def _fit(self) -> None:
        """Relayout the page if the width changed."""
        width = self._text_width
        if width == self._laid_width:
            return
        before = len(self._document.lines)
        first = self._first
        self._document = lay_out(self._blocks, width)
        self._laid_width = width
        if before:
            self._first = first * len(self._document.lines) // before
        links = self._document.links
        if self._link is not None and self._link >= len(links):
            self._link = None
        self.scroll_to(self._first)
        self._reveal_link()

    def on_resize(self) -> None:
        self._fit()
        self.scroll_to(self._first)

    # Scrolling

    def scroll_to(self, first: int) -> None:
        """Scroll to a line.

        :param first: First line to show.
        """
        last = max(0, len(self._document.lines) - self._rows)
        self._first = max(0, min(first, last))

    def scroll_by(self, rows: int) -> None:
        """Scroll by some lines.

        :param rows: Lines down; negative is up.
        """
        self.scroll_to(self._first + rows)

    def _scrolled(self, scroll_bar: ScrollBar) -> None:
        self.scroll_to(scroll_bar.value)

    def _sync_bar(self) -> None:
        rect = self.rect
        rows = self._rows
        self.scroll_bar.rect = Rect(
            rect.row + self.HEADER, rect.right - 1, max(2, rows), 1
        )
        self.scroll_bar.set_range(
            max(0, len(self._document.lines) - rows), max(1, rows)
        )
        self.scroll_bar.value = self._first

    @property
    def _is_scrollable(self) -> bool:
        return len(self._document.lines) > self._rows >= 2

    def wake_time(self) -> float | None:
        return self.scroll_bar.wake_time()  # its arrows repeat while held

    def on_timer(self, now: float) -> None:
        self._sync_bar()
        self.scroll_bar.on_timer(now)

    # Links

    def _reveal_link(self) -> None:
        """Scroll as little as needed to show the highlighted link."""
        if self._link is None:
            return
        link = self._document.links[self._link]
        if link.row < self._first:
            self.scroll_to(link.row)
        elif link.last_row >= self._first + self._rows:
            self.scroll_to(link.last_row - self._rows + 1)

    def _is_showing(self, number: int) -> bool:
        link = self._document.links[number]
        return link.last_row >= self._first and link.row < self._first + self._rows

    def focus_next_link(self, step: int = 1) -> bool:
        """Highlight the next link; return whether there are any.

        :param step: 1 for next, -1 for previous.
        """
        self._fit()
        links = self._document.links
        if not links:
            return False
        numbers = range(len(links)) if step > 0 else range(len(links) - 1, -1, -1)
        if self._link is not None and self._is_showing(self._link):
            self._link = (self._link + step) % len(links)
        else:
            self._link = next(
                (number for number in numbers if self._is_showing(number)),
                numbers[0],
            )
        self._reveal_link()
        self._update_status()
        return True

    def follow_link(self) -> None:
        """Follow the highlighted link."""
        self._fit()
        if self._link is None:
            return
        target = self._document.links[self._link].target
        if is_external(target):
            CLIPBOARD.copy(ClipboardItem(TEXT, target))
            self.status = f"Copied to the clipboard: {target}"
            return
        place = self._place
        self._visit(_Place(*resolve_link(place.topic if place else "", target)))

    def _update_status(self) -> None:
        """Say where the highlighted link goes, on the status bar."""
        if self._link is None:
            self.status = ""
            return
        target = self._document.links[self._link].target
        self.status = target if is_external(target) else f"Go to {target}"

    def ask_to_search(self) -> None:
        """Ask for words to search for, and search for them."""
        manager = self.window.manager if self.window is not None else None
        if manager is None or not manager.can_show_dialogs:
            return
        dialog = HelpSearchDialog()
        if manager.execute(dialog) == "ok":
            self.search(str(dialog.widget("words").value))

    # Drawing

    def nav_items(self) -> list[tuple[str, int, bool, Callable[[], object]]]:
        """Top row parts: text, column, enabled and action."""
        items = [
            ("\N{BLACK LEFT-POINTING POINTER} Back", self.can_go_back, self.go_back),
            (
                "Forward \N{BLACK RIGHT-POINTING POINTER}",
                self.can_go_forward,
                self.go_forward,
            ),
            ("Index", True, self.go_to_index),
            ("Search", True, self.ask_to_search),
        ]
        placed: list[tuple[str, int, bool, Callable[[], object]]] = []
        column = self.MARGIN
        for text, usable, action in items:
            placed.append((text, column, usable, action))
            column += len(text) + 3
        return placed

    def _style_of(self, span: Span, body: Style) -> Style:
        if span.link is not None:
            focused = self._link is not None and (
                span.link == self._document.links[self._link].key
            )
            return self.focused_link_style if focused else self.link_style
        styles = {
            HEADING: self.heading_style,
            BOLD: self.bold_style,
            EMPHASIS: self.emphasis_style,
            CODE: self.code_style,
            LINK: self.link_style,
        }
        return styles.get(span.kind, body)

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        del focused
        self._fit()
        self.scroll_to(self._first)
        body = self.window.body_style if self.window is not None else Style()
        rect = self.rect
        row, column = origin.row + rect.row, origin.column + rect.column
        canvas.fill(Rect(row, column, rect.height, rect.width), " ", body)
        for text, at, usable, _ in self.nav_items():
            style = self.link_style if usable else self.disabled_style
            canvas.write(row, column + at, text, style, clip=origin)
        rule = "\N{BOX DRAWINGS LIGHT HORIZONTAL}" * rect.width
        canvas.write(row + 1, column, rule, body, clip=origin)
        self._paint_page(canvas, row + self.HEADER, column + self.MARGIN, body)
        if self._is_scrollable:
            self._sync_bar()
            scrollbar_style = (
                self.window.scrollbar_style
                if self.window is not None
                else ScrollBar.style
            )
            self.scroll_bar.layout(row + self.HEADER, column + rect.width - 1).paint(
                canvas, scrollbar_style
            )

    def _paint_page(self, canvas: Canvas, row: int, column: int, body: Style) -> None:
        """Draw the visible page lines.

        :param canvas: Canvas to draw on.
        :param row: Screen row.
        :param column: Screen column.
        :param body: The window's style.
        """
        page = Rect(row, column, self._rows, self._text_width)
        lines = self._document.lines[self._first : self._first + self._rows]
        for offset, line in enumerate(lines):
            at = column
            for span in line:
                style = self._style_of(span, body)
                canvas.write(row + offset, at, span.text, style, page)
                at += len(span.text)

    # Input

    def key_help(self, shortcuts: Shortcuts) -> list[tuple[str, str]]:
        """Keys for the status bar.

        :param shortcuts: Key bindings in effect.
        """
        hints = []
        if self._link is not None:
            hints.append(("help_follow", "Follow"))
        else:
            if self.can_go_back:
                hints.append(("help_back", "Back"))
            if self.can_go_forward:
                hints.append(("help_forward", "Forward"))
            hints.append(("help_search", "Search"))
        hints.append(("help_close", "Close"))
        return [
            (shortcuts.hint(action), text)
            for action, text in hints
            if shortcuts.hint(action)
        ]

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Follow links, navigate, scroll and close.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        page = max(1, self._rows - 1)
        everything = len(self._document.lines)
        actions: dict[str, Callable[[], object]] = {
            "help": self.go_to_index,
            "help_follow": self.follow_link,
            "help_next_link": lambda: self.focus_next_link(1),
            "help_previous_link": lambda: self.focus_next_link(-1),
            "help_back": self.go_back,
            "help_forward": self.go_forward,
            "help_index": self.go_to_index,
            "help_search": self.ask_to_search,
            "help_close": self._close,
        }
        for action, rows in (
            ("list_up", -1),
            ("list_down", 1),
            ("list_page_up", -page),
            ("list_page_down", page),
            ("list_home", -everything),
            ("list_end", everything),
        ):
            actions[action] = partial(self.scroll_by, rows)
        return run_shortcut(shortcuts, key, actions)

    def _close(self) -> None:
        if self.on_close is not None:
            self.on_close()

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Scroll or follow links with the mouse.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        self._fit()
        self._sync_bar()
        if event.action == "scroll":
            rows = self.wheel_rows
            self.scroll_by(-rows if event.button in ("up", "left") else rows)
            return True
        if event.action == "press" and event.button == "left":
            arrows = self.scroll_bar.rect
            self._bar_mouse = self._is_scrollable and arrows.contains(row, column)
            if not self._bar_mouse:
                self._press(row - self.rect.row, column - self.rect.column)
        if not self._bar_mouse:
            return event.button == "left"
        self._bar_mouse = event.action != "release"
        return self.scroll_bar.handle_mouse(event, row, column)

    def _press(self, row: int, column: int) -> None:
        """Handle a press.

        :param row: Row in the view.
        :param column: Column in the view.
        """
        if row == 0:
            for text, at, usable, action in self.nav_items():
                if usable and at <= column < at + len(text):
                    action()
            return
        number = self._document.link_at(
            row - self.HEADER + self._first, column - self.MARGIN
        )
        if number is not None:
            self._link = number
            self._update_status()
            self.follow_link()


def _wear_help_colours(window: Window) -> None:
    """Give a window help colours.

    :param window: The window.
    """
    for name in WINDOW_STYLES:
        setattr(window, name, getattr(HelpWindow, name))


class HelpWindow(Window):
    """Help in its own window.

    :param book: The help pages.
    :param title: Title text.
    :param rect: Position and size.
    """

    frame_style: Style = Style(foreground=BRIGHT_WHITE, background=CYAN, bold=True)
    inactive_frame_style: Style = Style(foreground=BLACK, background=CYAN)
    adjusting_frame_style: Style = Style(
        foreground=BRIGHT_GREEN, background=CYAN, bold=True
    )
    body_style: Style = Style(foreground=BLACK, background=CYAN)
    button_style: Style = Style(foreground=BRIGHT_GREEN, background=CYAN, bold=True)
    resize_grip_style: Style = Style(
        foreground=BRIGHT_GREEN, background=CYAN, bold=True
    )
    scrollbar_style: Style = Style(foreground=BLUE, background=CYAN)
    min_width = 30
    min_height = 8

    def __init__(self, book: HelpBook, title: str, rect: Rect) -> None:
        super().__init__(
            title,
            rect,
            resizable=True,
            maximisable=True,
            minimisable=True,
            closable=True,
        )
        interior = self.interior
        self.view = self.add(
            HelpView(book, 0, 0, interior.width, interior.height, on_close=self._close),
            grow=Grow.ALL,
        )

    def _close(self) -> None:
        if self.manager is not None:
            self.manager.close(self)


class HelpDialog(Dialog):
    """Help in front of a dialog.

    :param book: The help pages.
    :param title: Title text.
    :param rect: Position and size.
    """

    def __init__(self, book: HelpBook, title: str, rect: Rect) -> None:
        super().__init__(title, rect.width, rect.height)
        self.resizable = True
        self.maximisable = True
        self.min_width = HelpWindow.min_width
        self.min_height = HelpWindow.min_height
        _wear_help_colours(self)
        interior = self.interior
        self.view = self.add(
            HelpView(book, 0, 0, interior.width, interior.height, on_close=self.cancel),
            grow=Grow.ALL,
        )

    def theme_changed(self) -> None:
        _wear_help_colours(self)


class HelpSearchDialog(Dialog):
    """Asks for help search words."""

    def __init__(self) -> None:
        super().__init__(
            "Search help", 46, 9, status="Finds the topics with all the words"
        )
        _wear_help_colours(self)
        self.add(Label("Words to find:", 1, 2))
        self.add(TextBox(2, 2, 40, name="words"))
        self.add(Button("&Search", 4, 10, result="ok", default=True, name="ok"))
        self.add(Button("&Cancel", 4, 24, result="cancel", name="cancel"))

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Ignore the help key.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        return shortcuts.matches("help", key) or super().handle_key(key, shortcuts)

    def theme_changed(self) -> None:
        _wear_help_colours(self)


def help_topic_of(window: Window | None) -> str | None:
    """The focused help topic in a window, or ``None``.

    :param window: The window.
    """
    if window is None:
        return None
    focused = window.focused
    if focused is not None:
        topic = focused.help_topic()
        if topic is not None:
            return topic
        for container in ancestors(focused):
            topic = container.help or container.anchor.help
            if topic is not None:
                return topic
    return window.help


def help_rect(area: Rect) -> Rect:
    """Where a help window opens.

    :param area: The work area.
    """
    width = min(HELP_WIDTH, max(HelpWindow.min_width, area.width - 4))
    height = min(HELP_HEIGHT, max(HelpWindow.min_height, area.height - 2))
    return Rect(
        area.row + max(0, (area.height - height) // 2),
        area.column + max(0, (area.width - width) // 2),
        height,
        width,
    )


def open_help(  # pylint: disable=too-many-arguments
    manager: "PresentationManager",
    book: HelpBook,
    title: str,
    topic: str | None,
    *,
    window: HelpWindow | None,
    open_window: Callable[[HelpWindow], object],
) -> HelpWindow | None:
    """Show help; return the help window.

    :param manager: The presentation manager.
    :param book: The help pages.
    :param title: Title text.
    :param topic: The topic, if any.
    :param window: The open help window, if any.
    :param open_window: Shows a new help window.
    """
    dialog = manager.answering_dialog
    if isinstance(dialog, Popup):
        return window
    if dialog is not None:
        if manager.can_show_dialogs:
            modal = HelpDialog(book, title, help_rect(manager.workspace))
            modal.view.go(topic or INDEX)
            manager.execute(modal)
        return window
    if window is None or window.manager is not manager:
        window = HelpWindow(book, title, help_rect(manager.workspace))
        window.view.go(topic or INDEX)
        open_window(window)
    else:
        window.view.go(topic or INDEX)
        manager.show_window(window)
    return window
