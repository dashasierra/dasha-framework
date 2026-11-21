"""Tests for help."""

# pylint: disable=too-many-lines

import re
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import cast

from dasha.application import Application
from dasha.canvas import Canvas, Rect
from dasha.client import ClientManager, colours_of, look_of
from dasha.clipboard import CLIPBOARD
from dasha.dialog import Dialog, ListPopup, information
from dasha.events import MouseEvent
from dasha.help import (
    DESKTOP_PAGES,
    INDEX,
    HelpBook,
    HelpDialog,
    HelpSearchDialog,
    HelpView,
    HelpWindow,
    help_rect,
    help_topic_of,
    is_external,
    resolve_link,
)
from dasha.__main__ import _desktop
from dasha.manager import PresentationManager
from dasha.markdown import lay_out, parse
from dasha.protocol import send
from dasha.settings import SettingsDialog
from dasha.shortcuts import DEFAULTS, DESCRIPTIONS, Shortcuts
from dasha.style import CYAN, Style
from dasha.terminal import Terminal
from dasha.theme import (
    BASES,
    DESCRIPTIONS as ROLE_DESCRIPTIONS,
    ROLES,
    apply_theme,
    current_theme,
)
from dasha.widgets import Button, GroupBox, Tabs, TextBox, Widget
from dasha.window import Window
from tests.support import isolated_home, pipe
from tests.test_application import Scripted
from tests.test_hosting import WELCOME
from tests.test_manager import FakeTerminal

SHORTCUTS = Shortcuts()

PAGES = {
    "index.md": (
        "# The index\n\n[One](one.md), [Two](sub/two.md) and "
        "[the web](https://example.com/page).\n"
    ),
    "one.md": (
        "# One\n\nFirst [back to the index](index.md).\n\n"
        + "Line of text.\n\n" * 30
        + "## Saving\n\nThe word banana is here. [Same page](#saving)\n"
    ),
    "sub/two.md": "# Two\n\n[Beside it](three.md) and [above it](../one.md#saving)\n",
    "sub/three.md": "# Three\n\nbanana banana pear\n",
    "broken.md": "# Broken\n\n[Nowhere](nowhere.md)\n",
    "user_name.md": "# Your name\n\nAs on your passport.\n",
}


def write_pages(folder: Path, pages: dict[str, str]) -> None:
    """Make a folder of pages.

    :param folder: The folder.
    :param pages: Page text by name.
    """
    for name, text in pages.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class PagesCase(unittest.TestCase):
    """A folder of pages, for the length of a test."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        write_pages(self.folder, PAGES)
        self.book = HelpBook(self.folder)


class LinkTests(unittest.TestCase):
    """Where links go."""

    def test_relative_to_the_page(self) -> None:
        """Relative to the page."""
        self.assertEqual(resolve_link("index", "one.md"), ("one", ""))
        self.assertEqual(resolve_link("sub/two", "three.md"), ("sub/three", ""))
        self.assertEqual(resolve_link("sub/two", "../one.md#a"), ("one", "a"))

    def test_from_the_top(self) -> None:
        """From the top."""
        self.assertEqual(resolve_link("sub/two", "/one.md"), ("one", ""))

    def test_on_the_same_page(self) -> None:
        """On the same page."""
        self.assertEqual(resolve_link("sub/two", "#a"), ("sub/two", "a"))

    def test_without_md(self) -> None:
        """Without md."""
        self.assertEqual(resolve_link("index", "one"), ("one", ""))

    def test_spaces_written_as_codes(self) -> None:
        """Spaces written as %20."""
        self.assertEqual(resolve_link("index", "a%20b.md"), ("a b", ""))

    def test_external(self) -> None:
        """External."""
        for target in ("https://a.b", "http://a", "mailto:a@b.c", "//a.b/c"):
            with self.subTest(target=target):
                self.assertTrue(is_external(target))
        for target in ("one.md", "#a", "../a.md", "a/b.md", "c:d.md"):
            with self.subTest(target=target):
                self.assertFalse(is_external(target))


class BookTests(PagesCase):
    """A folder of pages."""

    def test_topics(self) -> None:
        """Topics."""
        self.assertEqual(
            self.book.topics(),
            ["broken", "index", "one", "sub/three", "sub/two", "user_name"],
        )
        self.assertTrue(self.book.has_topics())

    def test_no_pages(self) -> None:
        """No pages."""
        with tempfile.TemporaryDirectory() as empty:
            self.assertFalse(HelpBook(empty).has_topics())
        self.assertFalse(HelpBook(self.folder / "not there").has_topics())

    def test_reading(self) -> None:
        """Reading."""
        self.assertIn("passport", self.book.read("user_name") or "")
        self.assertIn("banana", self.book.read("sub/three") or "")
        self.assertIsNone(self.book.read("nowhere"))

    def test_a_page_cannot_lead_out_of_the_folder(self) -> None:
        """A page cannot lead out of the folder."""
        outside = self.folder.parent / "dasha-test-outside.md"
        outside.write_text("secret", encoding="utf-8")
        self.addCleanup(outside.unlink)
        for topic in (
            "../dasha-test-outside",
            "sub/../../dasha-test-outside",
            str(outside.with_suffix("")),
            "\x00",
        ):
            with self.subTest(topic=topic):
                self.assertIsNone(self.book.read(topic))

    def test_bad_utf8_is_read_anyway(self) -> None:
        """Bad utf8 is read anyway."""
        (self.folder / "bad.md").write_bytes(b"\xef\xbb\xbfgood \xff bad")
        self.assertEqual(self.book.read("bad"), "good \N{REPLACEMENT CHARACTER} bad")

    def test_a_missing_topic_says_so(self) -> None:
        """A missing topic says so."""
        page = self.book.page("no_such")
        self.assertIn("Topic not found", page)
        self.assertIn("no\\_such", page)
        self.assertIn("(/index.md)", page)

    def test_a_missing_index_has_no_link_to_itself(self) -> None:
        """A missing index has no link to itself."""
        self.assertNotIn("Go to the index", self.book.page(INDEX))

    def test_search(self) -> None:
        """Search."""
        results = self.book.search("banana")
        self.assertEqual([result.topic for result in results], ["sub/three", "one"])
        self.assertEqual(results[1].slug, "saving")
        self.assertEqual(results[1].title, "One")
        self.assertIn("banana", results[1].context)

    def test_search_needs_every_word(self) -> None:
        """Search needs every word."""
        self.assertEqual(
            [result.topic for result in self.book.search("PEAR banana")], ["sub/three"]
        )
        self.assertEqual(self.book.search("banana grape"), [])

    def test_search_puts_titles_first(self) -> None:
        """Search puts titles first."""
        self.assertEqual(self.book.search("One")[0].topic, "one")

    def test_search_of_nothing(self) -> None:
        """Search of nothing."""
        self.assertEqual(self.book.search("  "), [])

    def test_search_results_as_a_page(self) -> None:
        """Search results as a page."""
        document = lay_out(parse(self.book.results_page("banana")), 60)
        self.assertEqual(
            [link.target for link in document.links],
            ["/sub/three.md#three", "/one.md#saving"],
        )
        self.assertIn("2 topics found for banana", document.text(2))

    def test_search_results_are_not_read_as_markdown(self) -> None:
        """Search results are not read as markdown."""
        page = self.book.results_page("*[a](b)*")
        self.assertEqual(lay_out(parse(page), 60).links, [])
        self.assertIn(
            "Nothing was found for *[a](b)*.", lay_out(parse(page), 60).text(2)
        )


def laid_out_view(book: HelpBook, width: int = 40, height: int = 12) -> HelpView:
    """A help view at the index.

    :param book: The help pages.
    :param width: View width.
    :param height: View height.
    """
    view = HelpView(book, 0, 0, width, height)
    view.go(INDEX)
    return view


def press_at(view: HelpView, row: int, column: int) -> None:
    """Press and release the left button.

    :param view: The help view.
    :param row: Row in the view.
    :param column: Column in the view.
    """
    for action in ("press", "release"):
        event = MouseEvent(action, "left", row, column)
        view.handle_mouse(event, row, column)


def press_key(view: HelpView, name: str) -> bool:
    """Press a key on a view.

    :param view: The help view.
    :param name: The key.
    """
    return view.handle_key(name, SHORTCUTS)


class ViewTests(PagesCase):
    """Going places, in a view."""

    def setUp(self) -> None:
        super().setUp()
        self.view = laid_out_view(self.book)

    def test_starts_where_it_is_sent(self) -> None:
        """Starts where it is sent."""
        self.assertEqual(self.view.topic, "index")
        self.assertEqual(self.view.value, "index")

    def test_a_topic_may_name_a_heading(self) -> None:
        """A topic may name a heading."""
        self.view.go("one#saving")
        self.assertEqual(self.view.topic, "one")
        self.assertEqual(
            self.view.first_visible,
            min(
                self.view.document.anchors["saving"],
                len(self.view.document.lines) - 10,
            ),
        )

    def test_following_links(self) -> None:
        """Following links."""
        self.assertTrue(press_key(self.view, "tab"))
        self.assertEqual(self.view.focused_link, 0)
        self.assertTrue(press_key(self.view, "enter"))
        self.assertEqual(self.view.topic, "one")
        self.assertIsNone(self.view.focused_link)

    def test_links_relative_to_a_subfolder(self) -> None:
        """Links relative to a subfolder."""
        self.view.go("sub/two")
        press_key(self.view, "tab")
        press_key(self.view, "enter")
        self.assertEqual(self.view.topic, "sub/three")

    def test_tab_goes_round_the_links(self) -> None:
        """Tab goes round the links."""
        for expected in (0, 1, 2, 0):
            press_key(self.view, "tab")
            self.assertEqual(self.view.focused_link, expected)
        press_key(self.view, "shift+tab")
        self.assertEqual(self.view.focused_link, 2)

    def test_shift_tab_starts_from_the_last_showing(self) -> None:
        """Shift tab starts from the last showing."""
        press_key(self.view, "shift+tab")
        self.assertEqual(self.view.focused_link, 2)

    def test_tab_with_no_links(self) -> None:
        """Tab with no links."""
        self.view.go("sub/three")
        self.assertTrue(press_key(self.view, "tab"))
        self.assertIsNone(self.view.focused_link)
        self.assertTrue(press_key(self.view, "enter"))  # nothing to follow, but its key
        self.assertEqual(self.view.topic, "sub/three")

    def test_tab_scrolls_to_the_link(self) -> None:
        """Tab scrolls to the link."""
        self.view.go("one")
        press_key(self.view, "tab")  # the one at the top, then the one at the bottom
        press_key(self.view, "tab")
        self.assertGreater(self.view.first_visible, 0)
        link = self.view.document.links[1]
        self.assertGreaterEqual(link.row, self.view.first_visible)

    def test_tab_starts_from_what_is_showing(self) -> None:
        """Tab starts from what is showing."""
        self.view.go("one")
        press_key(self.view, "tab")
        press_key(self.view, "end")  # the highlighted link is scrolled away
        press_key(self.view, "tab")
        self.assertEqual(self.view.focused_link, 1)

    def test_back_and_forward(self) -> None:
        """Back and forward."""
        self.assertFalse(self.view.can_go_back)
        self.view.go("one")
        self.view.go("user_name")
        press_key(self.view, "alt+left")
        self.assertEqual(self.view.topic, "one")
        press_key(self.view, "alt+left")
        self.assertEqual(self.view.topic, "index")
        self.assertFalse(self.view.can_go_back)
        press_key(self.view, "alt+left")  # nowhere to go
        self.assertEqual(self.view.topic, "index")
        press_key(self.view, "alt+right")
        self.assertEqual(self.view.topic, "one")
        self.assertTrue(self.view.can_go_forward)

    def test_going_somewhere_new_ends_the_forward_pages(self) -> None:
        """Going somewhere new ends the forward pages."""
        self.view.go("one")
        self.view.go_back()
        self.view.go("user_name")
        self.assertFalse(self.view.can_go_forward)

    def test_going_to_the_same_place_adds_no_history(self) -> None:
        """Going to the same place adds no history."""
        self.view.go("one")
        self.view.go("one")
        self.view.go_back()
        self.assertEqual(self.view.topic, "index")

    def test_going_to_the_same_place_goes_back_to_its_top(self) -> None:
        """Going to the same place goes back to its top."""
        self.view.go("one")
        self.view.scroll_to(9)
        self.view.go("one")
        self.assertEqual(self.view.first_visible, 0)

    def test_back_restores_where_it_was(self) -> None:
        """Back restores where it was."""
        self.view.go("one")
        self.view.scroll_to(9)
        press_key(self.view, "tab")
        link = self.view.focused_link
        first = self.view.first_visible
        self.view.go("user_name")
        self.view.go_back()
        self.assertEqual(self.view.first_visible, first)
        self.assertEqual(self.view.focused_link, link)

    def test_a_link_to_a_heading_on_the_page_has_history(self) -> None:
        """A link to a heading on the page has history."""
        self.view.go("one")
        self.view.scroll_to(1000)
        press_key(self.view, "tab")
        self.assertEqual(
            self.view.document.links[self.view.focused_link or 0].target, "#saving"
        )
        press_key(self.view, "enter")
        self.assertEqual(self.view.topic, "one")
        self.view.go_back()
        self.assertEqual(self.view.topic, "one")
        self.assertGreater(self.view.first_visible, 0)

    def test_the_index_key(self) -> None:
        """The index key."""
        self.view.go("one")
        press_key(self.view, "alt+home")
        self.assertEqual(self.view.topic, "index")
        self.view.go_back()
        self.assertEqual(self.view.topic, "one")

    def test_the_help_key_inside_help_goes_to_the_index(self) -> None:
        """The help key inside help goes to the index."""
        self.view.go("one")
        self.assertTrue(press_key(self.view, "f1"))
        self.assertEqual(self.view.topic, "index")

    def test_a_web_link_copies_its_address(self) -> None:
        """A web link copies its address."""
        press_key(self.view, "shift+tab")
        self.assertEqual(self.view.status, "https://example.com/page")
        press_key(self.view, "enter")
        self.assertEqual(CLIPBOARD.text, "https://example.com/page")
        self.assertEqual(self.view.topic, "index")
        self.assertIn("Copied", self.view.status)
        press_key(self.view, "tab")  # it says where the next goes again
        self.assertEqual(self.view.status, "Go to one.md")

    def test_a_broken_link_says_so(self) -> None:
        """A broken link says so."""
        self.view.go("broken")
        press_key(self.view, "tab")
        press_key(self.view, "enter")
        self.assertEqual(self.view.topic, "nowhere")
        self.assertIn("Topic not found", self.view.document.text(0))
        press_key(self.view, "tab")  # and links to the index
        press_key(self.view, "enter")
        self.assertEqual(self.view.topic, "index")

    def test_scrolling(self) -> None:
        """Scrolling."""
        self.view.go("one")
        press_key(self.view, "down")
        self.assertEqual(self.view.first_visible, 1)
        press_key(self.view, "up")
        self.assertEqual(self.view.first_visible, 0)
        press_key(self.view, "pagedown")
        self.assertEqual(self.view.first_visible, 9)
        press_key(self.view, "pageup")
        self.assertEqual(self.view.first_visible, 0)
        press_key(self.view, "end")
        last = len(self.view.document.lines) - 10
        self.assertEqual(self.view.first_visible, last)
        press_key(self.view, "down")
        self.assertEqual(self.view.first_visible, last)
        press_key(self.view, "home")
        self.assertEqual(self.view.first_visible, 0)

    def test_the_wheel_scrolls(self) -> None:
        """The wheel scrolls."""
        self.view.go("one")
        down = MouseEvent("scroll", "down", 5, 5)
        self.assertTrue(self.view.handle_mouse(down, 5, 5))
        self.assertEqual(self.view.first_visible, HelpView.wheel_rows)

    def test_the_scroll_bar_scrolls(self) -> None:
        """The scroll bar scrolls."""
        self.view.go("one")
        canvas = Canvas(40, 12)
        self.view.paint(canvas, Rect(0, 0, 12, 40), True)
        press_at(self.view, 11, 39)  # the bar's down arrow
        self.assertGreater(self.view.first_visible, 0)

    def test_a_click_follows_a_link(self) -> None:
        """A click follows a link."""
        place = self.view.document.links[0].places[0]
        press_at(
            self.view,
            place[0] + HelpView.HEADER,
            place[1] + HelpView.MARGIN,
        )
        self.assertEqual(self.view.topic, "one")

    def test_a_click_elsewhere_does_nothing(self) -> None:
        """A click elsewhere does nothing."""
        press_at(self.view, 1, 1)
        press_at(self.view, HelpView.HEADER, 0)
        self.assertEqual(self.view.topic, "index")

    def test_the_top_row(self) -> None:
        """The top row."""
        self.view.go("one")
        items = {text: at for text, at, _, _ in self.view.nav_items()}
        press_at(self.view, 0, items["\N{BLACK LEFT-POINTING POINTER} Back"])
        self.assertEqual(self.view.topic, "index")
        press_at(self.view, 0, items["Forward \N{BLACK RIGHT-POINTING POINTER}"])
        self.assertEqual(self.view.topic, "one")
        press_at(self.view, 0, items["Index"])
        self.assertEqual(self.view.topic, "index")

    def test_the_top_row_cannot_go_nowhere(self) -> None:
        """The top row cannot go nowhere."""
        self.view.go("one")
        self.view.go_back()
        self.view.go_forward()
        self.view.go_back()
        items = {text: at for text, at, _, _ in self.view.nav_items()}
        press_at(self.view, 0, items["\N{BLACK LEFT-POINTING POINTER} Back"])
        self.assertEqual(self.view.topic, "index")

    def test_search(self) -> None:
        """Search."""
        self.view.search("banana")
        self.assertIsNone(self.view.topic)
        self.assertEqual(
            [link.target for link in self.view.document.links],
            ["/sub/three.md#three", "/one.md#saving"],
        )
        press_key(self.view, "tab")
        press_key(self.view, "enter")
        self.assertEqual(self.view.topic, "sub/three")
        self.view.go_back()  # and back to the results
        self.assertIsNone(self.view.topic)
        self.assertEqual(self.view.focused_link, 0)

    def test_searching_for_nothing_goes_nowhere(self) -> None:
        """Searching for nothing goes nowhere."""
        self.view.search("   ")
        self.assertEqual(self.view.topic, "index")

    def test_key_hints_say_what_can_be_done(self) -> None:
        """Key hints say what can be done."""
        hints = self.view.key_help(SHORTCUTS)
        self.assertEqual(hints, [("Ctrl+F", "Search"), ("Esc", "Close")])
        self.view.go("one")
        self.view.go_back()
        self.assertEqual(
            self.view.key_help(SHORTCUTS),
            [("Alt+Right", "Forward"), ("Ctrl+F", "Search"), ("Esc", "Close")],
        )
        self.view.go("user_name")
        self.assertIn(("Alt+Left", "Back"), self.view.key_help(SHORTCUTS))

    def test_a_highlighted_link_leaves_room_for_where_it_goes(self) -> None:
        """A highlighted link leaves room for its address."""
        self.view.go("one")
        press_key(self.view, "tab")
        self.assertEqual(
            self.view.key_help(SHORTCUTS), [("Enter", "Follow"), ("Esc", "Close")]
        )
        self.assertEqual(self.view.status, "Go to index.md")

    def test_the_keys_can_be_changed(self) -> None:
        """The keys can be changed."""
        shortcuts = Shortcuts({"help_back": ["ctrl+b"], "help_close": []})
        self.view.go("one")
        self.assertFalse(self.view.handle_key("alt+left", shortcuts))
        self.assertTrue(self.view.handle_key("ctrl+b", shortcuts))
        self.assertEqual(self.view.topic, "index")
        self.view.go("one")
        hints = self.view.key_help(shortcuts)
        self.assertIn(("Ctrl+B", "Back"), hints)
        self.assertNotIn("Close", [text for _, text in hints])

    def test_a_new_width_wraps_again(self) -> None:
        """A new width wraps again."""
        self.view.go("one")
        self.view.scroll_to(30)
        before = self.view.document.lines
        self.view.rect = Rect(0, 0, 12, 20)
        self.view.on_resize()
        self.assertIsNot(self.view.document.lines, before)
        self.assertLessEqual(
            max(len(self.view.document.text(r)) for r in range(10)), 17
        )
        self.assertGreater(self.view.first_visible, 0)

    def test_a_new_width_keeps_the_highlighted_link_showing(self) -> None:
        """A new width keeps the highlighted link showing."""
        self.view.go("one")
        press_key(self.view, "tab")
        self.view.rect = Rect(0, 0, 12, 14)
        self.view.on_resize()
        link = self.view.document.links[self.view.focused_link or 0]
        self.assertLess(link.row, self.view.first_visible + 10)
        self.assertGreaterEqual(link.last_row, self.view.first_visible)

    def test_painting_at_any_size(self) -> None:
        """Painting at any size."""
        for width, height in ((1, 1), (5, 2), (12, 3), (40, 12), (200, 60)):
            with self.subTest(width=width, height=height):
                canvas = Canvas(width, height)
                view = laid_out_view(self.book, width, height)
                view.go("one")
                view.paint(canvas, Rect(0, 0, height, width), True)


class LookTests(PagesCase):
    """What help windows look like."""

    def test_cyan(self) -> None:
        """Cyan."""
        window = HelpWindow(self.book, "Help", Rect(1, 1, 20, 60))
        self.assertEqual(window.body_style.background, CYAN)
        self.assertEqual(window.frame_style.background, CYAN)

    def test_a_help_dialog_looks_the_same(self) -> None:
        """A help dialog looks the same."""
        dialog = HelpDialog(self.book, "Help", Rect(1, 1, 20, 60))
        self.assertEqual(dialog.body_style, HelpWindow.body_style)
        self.assertEqual(dialog.frame_style, HelpWindow.frame_style)
        self.assertEqual(dialog.scrollbar_style, HelpWindow.scrollbar_style)

    def test_a_help_dialog_follows_the_theme(self) -> None:
        """A help dialog follows the theme."""
        saved = current_theme()
        self.addCleanup(apply_theme, saved)
        dialog = HelpDialog(self.book, "Help", Rect(1, 1, 20, 60))
        search = HelpSearchDialog()
        apply_theme(BASES["monochrome"])
        dialog.theme_changed()
        search.theme_changed()
        self.assertEqual(dialog.body_style, Style())
        self.assertEqual(search.body_style, Style())

    def test_every_theme_has_the_roles(self) -> None:
        """Every theme has the roles."""
        roles = [role for role in ROLES if role.startswith("help.")]
        self.assertTrue(roles)
        for name, theme in BASES.items():
            for role in roles:
                with self.subTest(theme=name, role=role):
                    self.assertIn(role, theme)
        for role in roles:
            self.assertIn(role, ROLE_DESCRIPTIONS)

    def test_the_dark_theme_stays_cyan(self) -> None:
        """The dark theme stays cyan."""
        body = BASES["dark"]["help.body"]
        assert isinstance(body, Style)
        self.assertEqual(body.background, CYAN)

    def test_the_styles_are_drawn(self) -> None:
        """The styles are drawn."""
        window = HelpWindow(self.book, "Help", Rect(0, 0, 14, 42))
        window.view.go("index")
        canvas = Canvas(42, 14)
        window.paint(canvas, True)
        interior_row = window.interior.row + HelpView.HEADER
        link = window.view.document.links[0]
        cell = canvas.cell(
            interior_row + link.row,
            window.interior.column + HelpView.MARGIN + link.places[0][1],
        )
        self.assertEqual(cell[1], HelpView.link_style)
        window.view.focus_next_link()
        canvas = Canvas(42, 14)
        window.paint(canvas, True)
        cell = canvas.cell(
            interior_row + link.row,
            window.interior.column + HelpView.MARGIN + link.places[0][1],
        )
        self.assertEqual(cell[1], HelpView.focused_link_style)

    def test_it_opens_where_there_is_room(self) -> None:
        """It opens where there is room."""
        self.assertEqual(help_rect(Rect(1, 0, 22, 80)), Rect(2, 7, 20, 66))
        tiny = help_rect(Rect(1, 0, 8, 20))
        self.assertEqual((tiny.height, tiny.width), (8, 30))


class _Helpful(Application):
    """An application with help.

    :param folder: Help folder, if any.
    """

    name = "Helpful"

    def __init__(self, folder: Path | None) -> None:
        super().__init__()
        self.help_folder = folder

    def start(self) -> None:
        window = Window("Details", Rect(2, 2, 12, 50), closable=True)
        window.add(TextBox(1, 2, 30, name="name")).help = "user_name"
        window.add(TextBox(2, 2, 30, name="other"))
        self.open(window)


class _Silent(Application):
    """An application with no help, as every application used to be."""

    name = "Silent"

    def start(self) -> None:
        window = Window("Details", Rect(2, 2, 12, 50), closable=True)
        window.add(TextBox(1, 2, 30, name="name")).help = "user_name"
        self.open(window)


class TopicTests(unittest.TestCase):
    """What the topic is for what has the focus."""

    def setUp(self) -> None:
        self.window = Window("W", Rect(0, 0, 20, 60))

    def test_nothing(self) -> None:
        """Nothing."""
        self.assertIsNone(help_topic_of(None))
        self.assertIsNone(help_topic_of(self.window))

    def test_the_window(self) -> None:
        """The window."""
        self.window.add(TextBox(0, 0, 10))
        self.window.help = "window"
        self.assertEqual(help_topic_of(self.window), "window")

    def test_the_widget_comes_first(self) -> None:
        """The widget comes first."""
        box = self.window.add(TextBox(0, 0, 10))
        box.help = "box"
        self.window.help = "window"
        self.assertEqual(help_topic_of(self.window), "box")

    def test_a_group_box(self) -> None:
        """A group box."""
        group = self.window.add(GroupBox("G", 0, 0, 20, 5))
        group.help = "group"
        group.add(TextBox(0, 0, 10))
        self.window.help = "window"
        self.assertEqual(help_topic_of(self.window), "group")

    def test_a_tab_page(self) -> None:
        """A tab page."""
        tabs = self.window.add(Tabs(0, 0, 40, 10))
        first = tabs.add_page("One")
        second = tabs.add_page("Two")
        first.help = "first"
        second.help = "second"
        self.assertEqual(help_topic_of(self.window), "first")  # on the tabs
        tabs.select(1)
        self.assertEqual(help_topic_of(self.window), "second")
        box = second.add(TextBox(0, 0, 10))
        self.window.focus(box)
        self.assertEqual(help_topic_of(self.window), "second")

    def test_tabs_with_a_topic_of_their_own(self) -> None:
        """Tabs with a topic of their own."""
        tabs = self.window.add(Tabs(0, 0, 40, 10))
        tabs.add_page("One")
        tabs.help = "tabs"
        self.assertEqual(help_topic_of(self.window), "tabs")

    def test_by_default_there_is_no_topic(self) -> None:
        """By default there is no topic."""
        self.assertIsNone(Widget(0, 0, 1).help)
        self.assertIsNone(Window.help)


class ApplicationTests(PagesCase):
    """F1 in an application on a desktop in this process."""

    def setUp(self) -> None:
        super().setUp()
        self.manager = PresentationManager()
        self.manager.handle_resize(80, 24)

    def launch(self, folder: Path | None = None) -> _Helpful:
        """A running application with help.

        :param folder: Help folder, or ``None`` for the test pages.
        """
        return self.manager.launch(_Helpful(folder or self.folder))

    def help_window(self, application: Application) -> HelpWindow:
        """The application's open help window.

        :param application: The application.
        """
        found = [w for w in application.windows if isinstance(w, HelpWindow)]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_f1_goes_to_the_widgets_topic(self) -> None:
        """F1 goes to the widgets topic."""
        application = self.launch()
        self.manager.handle_event("f1")
        window = self.help_window(application)
        self.assertEqual(window.view.topic, "user_name")
        self.assertIs(self.manager.active_window, window)
        self.assertIs(window.application, application)
        self.assertEqual(window.title, "Helpful Help")

    def test_without_a_topic_it_goes_to_the_index(self) -> None:
        """Without a topic it goes to the index."""
        application = self.launch()
        self.manager.handle_event("tab")
        self.manager.handle_event("f1")
        self.assertEqual(self.help_window(application).view.topic, "index")

    def test_a_missing_topic_says_so(self) -> None:
        """A missing topic says so."""
        application = self.launch()
        window = application.windows[0]
        window.widget("name").help = "no_such"
        self.manager.handle_event("f1")
        help_window = self.help_window(application)
        self.assertEqual(help_window.view.topic, "no_such")
        self.assertIn("Topic not found", help_window.view.document.text(0))

    def test_there_is_only_one_window(self) -> None:
        """There is only one window."""
        application = self.launch()
        details = application.windows[0]
        self.manager.handle_event("f1")
        window = self.help_window(application)
        self.manager.handle_event("f6")  # back to the details
        self.assertIs(self.manager.active_window, details)
        details.focus(details.widget("other"))
        self.manager.handle_event("f1")
        self.assertIs(self.help_window(application), window)
        self.assertIs(self.manager.active_window, window)
        self.assertEqual(window.view.topic, "index")
        window.view.go_back()
        self.assertEqual(window.view.topic, "user_name")

    def test_it_stays_open_beside_the_others(self) -> None:
        """It stays open beside the others."""
        application = self.launch()
        self.manager.handle_event("f1")
        self.assertIn(application.windows[0], self.manager.windows)
        self.assertFalse(self.help_window(application).modal)

    def test_a_minimised_window_comes_back(self) -> None:
        """A minimised window comes back."""
        application = self.launch()
        self.manager.handle_event("f1")
        window = self.help_window(application)
        self.manager.minimise(window)
        self.assertNotIn(window, self.manager.windows)
        application.show_help("one")
        self.assertIn(window, self.manager.windows)
        self.assertEqual(window.view.topic, "one")

    def test_closing_it_and_starting_afresh(self) -> None:
        """Closing it and starting afresh."""
        application = self.launch()
        self.manager.handle_event("f1")
        first = self.help_window(application)
        first.view.go("one")
        self.manager.handle_event("escape")
        self.assertNotIn(first, self.manager.windows)
        self.assertNotIn(first, application.windows)
        self.manager.handle_event("f1")
        second = self.help_window(application)
        self.assertIsNot(second, first)
        self.assertFalse(second.view.can_go_back)

    def test_it_ends_with_its_application(self) -> None:
        """It ends with its application."""
        application = self.launch()
        self.manager.handle_event("f1")
        window = self.help_window(application)
        application.quit()
        self.assertNotIn(window, self.manager.windows)

    def test_show_help_is_what_f1_does(self) -> None:
        """Show help is what F1 does."""
        application = self.launch()
        application.show_help()
        self.assertEqual(self.help_window(application).view.topic, "user_name")

    def test_show_help_can_name_a_topic(self) -> None:
        """Show help can name a topic."""
        application = self.launch()
        application.show_help("one#saving")
        self.assertEqual(self.help_window(application).view.topic, "one")

    def test_it_works_with_a_string_for_a_folder(self) -> None:
        """It works with a string for a folder."""
        manager = PresentationManager()
        application = manager.launch(_Helpful(self.folder))
        application.help_folder = str(self.folder)
        self.assertTrue(application.has_help())

    def test_has_help_is_for_menu_items(self) -> None:
        """Has help is for menu items."""
        self.assertTrue(self.launch().has_help())

    def test_an_application_with_no_windows(self) -> None:
        """An application with no windows."""
        application = self.launch()
        application.close(application.windows[0])
        self.assertIsNone(self.manager.active_window)
        self.manager.handle_event("f1")
        self.assertEqual(self.help_window(application).view.topic, "index")

    def test_a_window_with_nothing_to_focus(self) -> None:
        """A window with nothing to focus."""
        application = self.launch()
        application.open(Window("Empty", Rect(2, 2, 6, 30), closable=True))
        self.manager.handle_event("f1")
        self.assertEqual(self.help_window(application).view.topic, "index")

    def test_the_key_can_be_changed(self) -> None:
        """The key can be changed."""
        application = self.launch()
        self.manager.set_shortcuts(Shortcuts({"help": ["ctrl+h"]}))
        self.manager.handle_event("f1")
        self.assertEqual(len(application.windows), 1)
        self.manager.handle_event("ctrl+h")
        self.help_window(application)

    def test_the_status_bar_shows_only_inside_help(self) -> None:
        """The status bar shows only inside help."""
        application = self.launch()
        self.assertNotIn("Help", [text for _, text in self.manager.key_hints()])
        self.manager.handle_event("f1")
        self.help_window(application)
        self.assertIn(("Esc", "Close"), self.manager.key_hints())


class NoHelpTests(PagesCase):
    """Applications with none: F1 does nothing, and nothing has changed."""

    def assert_nothing_happens(self, application: Application) -> None:
        """Check F1 leaves the desktop as it was.

        :param application: The application.
        """
        manager = application.manager
        assert manager is not None
        windows = manager.windows
        manager.handle_event("f1")
        self.assertEqual(manager.windows, windows)

    def test_by_default(self) -> None:
        """By default."""
        manager = PresentationManager()
        application = manager.launch(_Silent)
        self.assertIsNone(application.help_folder)
        self.assertFalse(application.has_help())
        self.assert_nothing_happens(application)
        application.show_help("user_name")
        self.assert_nothing_happens(application)

    def test_with_nothing_in_the_folder(self) -> None:
        """With nothing in the folder."""
        with tempfile.TemporaryDirectory() as empty:
            application = PresentationManager().launch(_Helpful(Path(empty)))
            self.assertFalse(application.has_help())
            self.assert_nothing_happens(application)

    def test_with_no_such_folder(self) -> None:
        """With no such folder."""
        application = PresentationManager().launch(_Helpful(self.folder / "nope"))
        self.assert_nothing_happens(application)

    def test_a_status_bar_as_it_was(self) -> None:
        """A status bar as it was."""
        manager = PresentationManager()
        manager.launch(_Silent)
        self.assertEqual(manager.key_hints(), [("F10", "Menu")])

    def test_a_widget_that_uses_the_key_keeps_it(self) -> None:
        """A widget that uses the key keeps it."""

        class Taker(Widget):
            """Uses every key."""

            focusable = True
            keys: list[str] = []

            def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
                del shortcuts
                self.keys.append(key)
                return True

        manager = PresentationManager()
        application = manager.launch(_Helpful(self.folder))
        window = Window("Program", Rect(2, 2, 6, 30))
        taker = window.add(Taker(0, 0, 10))
        application.open(window)
        manager.handle_event("f1")
        self.assertEqual(taker.keys, ["f1"])
        self.assertFalse(any(isinstance(w, HelpWindow) for w in manager.windows))


TYPED = {
    "f1": ["\x1bOP"],
    "tab": ["\t"],
    "enter": ["\r"],
    "ctrl+f": ["\x06"],
    "escape": ["\x1b", ""],  # alone: nothing follows it in time
}
"""What a terminal sends for some keys, to script them."""


class _Noting(Scripted):
    """Notes each dialog it shows, and runs on scripted keys."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[Dialog] = []

    def execute(self, dialog: Dialog) -> str | None:
        self.seen.append(dialog)
        return super().execute(dialog)

    def run_keys(self, actions: list[Callable[[], object]], *keys: str) -> None:
        """Run on keys, with "x" running the next action.

        :param actions: Actions to run.
        :param keys: The keys.
        """
        self.actions = actions
        inputs = [raw for key in keys for raw in TYPED.get(key, [key])]
        self.run(cast(Terminal, FakeTerminal(inputs, [(80, 24)])))


class DialogTests(PagesCase):
    """F1 in a dialog, which needs the desktop running."""

    def setUp(self) -> None:
        super().setUp()
        self.manager = _Noting()
        self.manager.handle_resize(80, 24)
        self.application = self.manager.launch(_Helpful(self.folder))
        self.dialog = Dialog("Question", 40, 10)
        self.box = self.dialog.add(TextBox(1, 2, 30, name="answer"))
        self.box.help = "user_name"
        self.dialog.add(Button("&OK", 3, 2, result="ok", default=True))
        self.seen = self.manager.seen

    def ask(self, *keys: str) -> None:
        """Show the dialog and press keys.

        :param keys: The keys.
        """

        def ask() -> None:
            self.manager.execute(self.dialog)

        self.manager.run_keys([ask, self.manager.quit], "x", *keys, "x")

    def help_window(self) -> HelpWindow:
        """The help window, which must be open."""
        return next(w for w in self.application.windows if isinstance(w, HelpWindow))

    def test_help_opens_in_front_and_goes_back(self) -> None:
        """Help opens in front and goes back."""
        self.ask("a", "f1", "escape", "b", "enter")
        kinds = [type(dialog) for dialog in self.seen]
        self.assertEqual(kinds, [Dialog, HelpDialog])
        assert isinstance(self.seen[1], HelpDialog)
        self.assertEqual(self.seen[1].view.topic, "user_name")
        self.assertEqual(self.dialog.result, "ok")
        self.assertEqual(self.box.value, "ab")  # kept while help was open
        self.assertFalse(
            any(isinstance(w, HelpWindow) for w in self.application.windows)
        )

    def test_links_work_in_a_dialog(self) -> None:
        """Links work in a dialog."""
        self.box.help = None
        self.ask("f1", "tab", "enter", "escape", "enter")
        assert isinstance(self.seen[1], HelpDialog)
        self.assertEqual(self.seen[1].view.topic, "one")

    def test_without_a_topic_the_dialog_goes_to_the_index(self) -> None:
        """Without a topic the dialog goes to the index."""
        self.box.help = None
        self.ask("f1", "escape", "enter")
        assert isinstance(self.seen[1], HelpDialog)
        self.assertEqual(self.seen[1].view.topic, "index")

    def test_the_dialogs_own_topic(self) -> None:
        """The dialogs own topic."""
        self.box.help = None
        self.dialog.help = "one"
        self.ask("f1", "escape", "enter")
        assert isinstance(self.seen[1], HelpDialog)
        self.assertEqual(self.seen[1].view.topic, "one")

    def test_a_drop_down_list_has_no_help(self) -> None:
        """A drop down list has no help."""
        popup = ListPopup(["a", "b"], 0, 10, 2)

        def show() -> None:
            self.manager.execute(popup)

        self.manager.run_keys([show, self.manager.quit], "x", "f1", "escape", "x")
        self.assertEqual([type(dialog) for dialog in self.seen], [ListPopup])

    def test_a_search_from_a_dialog(self) -> None:
        """A search from a dialog."""
        self.ask("f1", "ctrl+f", *"banana", "enter", "escape", "enter")
        kinds = [type(dialog) for dialog in self.seen]
        self.assertEqual(kinds, [Dialog, HelpDialog, HelpSearchDialog])
        assert isinstance(self.seen[1], HelpDialog)
        self.assertIsNone(self.seen[1].view.topic)  # the page of results

    def test_a_search_cancelled(self) -> None:
        """A search cancelled."""
        self.ask("f1", "ctrl+f", "a", "escape", "escape", "enter")
        assert isinstance(self.seen[1], HelpDialog)
        self.assertEqual(self.seen[1].view.topic, "user_name")

    def test_the_help_key_is_nothing_while_searching(self) -> None:
        """The help key is nothing while searching."""
        self.ask("f1", "ctrl+f", "f1", "escape", "escape", "enter")
        kinds = [type(dialog) for dialog in self.seen]
        self.assertEqual(kinds, [Dialog, HelpDialog, HelpSearchDialog])

    def test_searching_from_a_window(self) -> None:
        """Searching from a window."""

        def show() -> None:
            self.application.show_help("index")

        self.manager.run_keys(
            [show, self.manager.quit], "x", "ctrl+f", *"pear", "enter", "x"
        )
        view = self.help_window().view
        self.assertIsNone(view.topic)
        self.assertEqual(view.document.links[0].target, "/sub/three.md#three")

    def test_the_top_row_searches(self) -> None:
        """The top row searches."""

        def show() -> None:
            self.application.show_help("index")

        def click_search() -> None:
            view = self.help_window().view
            items = {text: at for text, at, _, _ in view.nav_items()}
            press_at(view, 0, items["Search"])

        self.manager.run_keys(
            [show, click_search, self.manager.quit], "x", "x", "escape", "x"
        )
        self.assertEqual([type(d) for d in self.seen], [HelpSearchDialog])

    def test_searching_does_nothing_without_a_running_desktop(self) -> None:
        """Searching does nothing without a running desktop."""
        self.application.show_help("index")
        self.help_window().view.ask_to_search()
        self.assertEqual(self.seen, [])


class DesktopHelpTests(PagesCase):
    """Dasha Framework's own help."""

    def setUp(self) -> None:
        super().setUp()
        self.manager = _Noting()
        self.manager.handle_resize(80, 24)
        self.manager.help_folder = self.folder

    def windows(self) -> list[HelpWindow]:
        """The help windows on the desktop."""
        return [w for w in self.manager.windows if isinstance(w, HelpWindow)]

    def test_off_unless_asked_for(self) -> None:
        """Off unless asked for."""
        manager = PresentationManager()
        self.assertIsNone(manager.help_folder)
        labels = [item.label for item in manager.system_menu.items]
        self.assertNotIn("&Help", labels)
        manager.handle_event("f1")
        self.assertEqual(manager.windows, ())

    def test_an_empty_desktop(self) -> None:
        """An empty desktop."""
        self.manager.handle_event("f1")
        window = self.windows()[0]
        self.assertEqual(window.view.topic, "index")
        self.assertEqual(window.title, "Dasha Desktop Help")
        self.assertIsNone(window.application)
        self.manager.handle_event("f1")
        self.assertEqual(len(self.windows()), 1)

    def test_it_closes(self) -> None:
        """It closes."""
        self.manager.handle_event("f1")
        self.manager.handle_event("escape")
        self.assertEqual(self.windows(), [])
        self.manager.handle_event("f1")
        self.assertEqual(len(self.windows()), 1)

    def test_an_application_with_no_help_has_none_of_the_desktops(self) -> None:
        """An application with no help has none of the desktops."""
        self.manager.launch(_Silent)
        self.manager.handle_event("f1")
        self.assertEqual(self.windows(), [])

    def test_an_application_with_no_windows_and_no_help(self) -> None:
        """An application with no windows and no help."""
        application = self.manager.launch(_Silent)
        application.close(application.windows[0])
        self.manager.handle_event("f1")
        self.assertEqual(self.windows(), [])

    def test_an_application_with_help_has_its_own(self) -> None:
        """An application with help has its own."""
        with tempfile.TemporaryDirectory() as other:
            write_pages(Path(other), {"index.md": "# Its own\n"})
            application = self.manager.launch(_Helpful(Path(other)))
            self.manager.handle_event("tab")
            self.manager.handle_event("f1")
            self.assertIs(self.windows()[0].application, application)

    def test_the_desktops_own_dialogs(self) -> None:
        """The desktops own dialogs."""
        dialog = information("About", "Dasha Framework")
        dialog.help = "one"

        def show() -> None:
            self.manager.execute(dialog)

        self.manager.run_keys(
            [show, self.manager.quit], "x", "f1", "escape", "enter", "x"
        )
        seen = self.manager.seen
        self.assertEqual([type(shown) for shown in seen], [Dialog, HelpDialog])
        assert isinstance(seen[1], HelpDialog)
        self.assertEqual(seen[1].view.topic, "one")
        self.assertEqual(seen[1].title, "Dasha Desktop Help")

    def test_a_system_menu_item(self) -> None:
        """A system menu item."""
        manager = PresentationManager()
        manager.use_own_help()
        self.assertEqual(manager.help_folder, DESKTOP_PAGES)
        item = next(i for i in manager.system_menu.items if i.label == "&Help")
        assert item.action is not None
        item.action()
        window = manager.windows[-1]
        assert isinstance(window, HelpWindow)
        self.assertEqual(window.view.topic, "index")

    def test_the_system_menu_does_not_take_the_key_from_applications(self) -> None:
        """The system menu does not take the help key."""
        manager = PresentationManager()
        manager.use_own_help()
        item = next(i for i in manager.system_menu.items if i.label == "&Help")
        self.assertEqual(item.shortcut, "")
        application = manager.launch(_Helpful(self.folder))
        manager.handle_event("f1")
        window = manager.windows[-1]
        assert isinstance(window, HelpWindow)
        self.assertIs(window.application, application)
        self.assertEqual(window.view.topic, "user_name")

    def test_the_system_menu_item_on_an_application_with_no_help(self) -> None:
        """F1 does nothing there, though the desktop has help of its own."""
        manager = PresentationManager()
        manager.use_own_help()
        manager.launch(_Silent)
        manager.handle_event("f1")
        self.assertFalse(any(isinstance(w, HelpWindow) for w in manager.windows))

    def test_the_real_desktop_has_it_and_one_application_alone_does_not(self) -> None:
        """The real desktop has it and one application alone does not."""
        isolated_home(self)
        desktop = _desktop(None, [], processes=False)
        self.assertEqual(desktop.help_folder, DESKTOP_PAGES)
        alone = _desktop(None, [], processes=False, alone=True)
        self.assertIsNone(alone.help_folder)

    def test_settings_have_topics(self) -> None:
        """Settings have topics."""
        isolated_home(self)
        dialog = SettingsDialog(PresentationManager())
        self.assertEqual(help_topic_of(dialog), "settings#appearance")
        dialog.tabs.select(2)
        self.assertEqual(help_topic_of(dialog), "settings#desktop")


class ShippedPagesTests(unittest.TestCase):
    """The pages that come with Dasha Framework."""

    def setUp(self) -> None:
        self.book = HelpBook(DESKTOP_PAGES)

    def test_every_page_is_there(self) -> None:
        """Every page is there."""
        self.assertEqual(
            self.book.topics(),
            [
                "applications",
                "index",
                "keyboard",
                "menus",
                "running",
                "settings",
                "windows",
            ],
        )

    def test_every_link_goes_somewhere(self) -> None:
        """Every link goes somewhere."""
        for topic in self.book.topics():
            document = lay_out(parse(self.book.page(topic)), 60)
            for link in document.links:
                with self.subTest(topic=topic, target=link.target):
                    name, anchor = resolve_link(topic, link.target)
                    text = self.book.read(name)
                    assert text is not None
                    if anchor:
                        self.assertIn(anchor, lay_out(parse(text), 60).anchors)

    def test_the_topics_that_dialogs_name_are_there(self) -> None:
        """The topics that dialogs name are there."""
        anchors = lay_out(parse(self.book.page("settings")), 60).anchors
        for slug in ("appearance", "shortcuts", "desktop", "applications"):
            self.assertIn(slug, anchors)
        self.assertIsNotNone(self.book.read("running"))

    def test_they_are_packaged(self) -> None:
        """They are packaged."""
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        self.assertIn('"helppages/*.md"', pyproject.read_text(encoding="utf-8"))
        spec = pyproject.with_name("dasha.spec").read_text(encoding="utf-8")
        self.assertIn('"dasha/helppages"', spec)

    def test_they_use_code_page_437(self) -> None:
        """They use code page 437."""
        for topic in self.book.topics():
            text = self.book.read(topic) or ""
            with self.subTest(topic=topic):
                self.assertEqual(
                    {char for char in text if not _on_code_page_437(char)}, set()
                )


def _on_code_page_437(char: str) -> bool:
    """Whether code page 437 has a character.

    :param char: The character.
    """
    try:
        char.encode("cp437")
        return True
    except UnicodeEncodeError:
        return re.match(r"[←-↕]", char) is not None


class ShortcutTests(unittest.TestCase):
    """The keys."""

    def test_the_defaults(self) -> None:
        """The defaults."""
        self.assertEqual(DEFAULTS["help"], ("f1",))
        self.assertEqual(DEFAULTS["help_back"], ("alt+left",))
        self.assertEqual(DEFAULTS["help_close"], ("escape",))

    def test_every_action_is_described(self) -> None:
        """Every action is described."""
        for action in DEFAULTS:
            if action.startswith("help"):
                self.assertIn(action, DESCRIPTIONS)

    def test_help_can_be_turned_off(self) -> None:
        """Help can be turned off."""
        manager = PresentationManager(shortcuts=Shortcuts({"help": []}))
        manager.help_folder = DESKTOP_PAGES
        manager.handle_event("f1")
        self.assertEqual(manager.windows, ())


class _NotingClient(ClientManager):
    """Notes each dialog it shows."""

    seen: list[Dialog]

    def execute(self, dialog: Dialog) -> str | None:
        self.seen.append(dialog)
        return super().execute(dialog)


class HostedTests(PagesCase):
    """F1 in a hosted application."""

    def setUp(self) -> None:
        super().setUp()
        self.desktop, app_end = pipe()
        self.manager = _NotingClient(app_end, WELCOME)
        self.manager.seen = []
        self.addCleanup(self.manager.stop_listening)
        self.application = self.manager.launch(_Helpful(self.folder))
        self.window = self.application.windows[0]

    def press(self, window: Window, name: str) -> None:
        """A key from the desktop.

        :param window: The window.
        :param name: The key.
        """
        self.manager.handle(
            {"type": "key", "id": self.manager.window_id(window), "key": name}
        )

    def help_window(self) -> HelpWindow:
        """The help window, which must be open."""
        return next(w for w in self.application.windows if isinstance(w, HelpWindow))

    def test_f1_goes_to_the_widgets_topic(self) -> None:
        """F1 goes to the widgets topic."""
        self.press(self.window, "f1")
        self.assertEqual(self.help_window().view.topic, "user_name")

    def test_the_help_message_is_for_no_windows(self) -> None:
        """The help message is for no windows."""
        self.application.close(self.window)
        self.manager.handle({"type": "help"})
        self.assertEqual(self.help_window().view.topic, "index")

    def test_the_frame_is_told_its_colours(self) -> None:
        """The frame is told its colours."""
        self.press(self.window, "f1")
        window = self.help_window()
        self.assertEqual(look_of(window), "window")
        self.assertEqual(colours_of(window)["body_style"][1], CYAN)

    def test_it_tells_the_desktop_the_hints_inside_help(self) -> None:
        """It tells the desktop the hints inside help."""
        # pylint: disable=protected-access
        hints = cast(list[tuple[str, str]], self.manager._state(self.window)["hints"])
        self.assertNotIn(("F1", "Help"), hints)
        self.press(self.window, "f1")
        hints = cast(
            list[tuple[str, str]], self.manager._state(self.help_window())["hints"]
        )
        self.assertIn(("Esc", "Close"), hints)

    def test_an_application_with_none(self) -> None:
        """An application with none."""
        application = self.manager.launch(_Silent)
        window = application.windows[0]
        self.press(window, "f1")
        self.assertEqual(application.windows, [window])
        application.show_help()
        self.assertEqual(application.windows, [window])

    def test_escape_closes_it(self) -> None:
        """Escape closes it."""
        self.press(self.window, "f1")
        window = self.help_window()
        self.press(window, "escape")
        self.assertNotIn(window, self.application.windows)

    def test_a_dialog_of_its_own(self) -> None:
        """Help over a dialog of its own."""
        dialog = Dialog("Question", 40, 10)
        box = dialog.add(TextBox(1, 2, 30, name="answer"))
        box.help = "one"
        dialog.add(Button("&OK", 3, 2, result="ok", default=True))
        self.manager.window_id(self.window)
        dialog_id, help_id = 2, 3  # the next window numbers
        send(self.desktop, "key", id=dialog_id, key="a")
        send(self.desktop, "key", id=dialog_id, key="f1")
        send(self.desktop, "key", id=help_id, key="alt+home")
        send(self.desktop, "key", id=help_id, key="escape")
        send(self.desktop, "key", id=dialog_id, key="b")
        send(self.desktop, "key", id=dialog_id, key="enter")
        self.assertEqual(self.manager.execute(dialog), "ok")
        self.assertEqual(box.value, "ab")
        shown = self.manager.seen[1]
        assert isinstance(shown, HelpDialog)
        self.assertEqual(shown.view.topic, "index")
        shown.view.go_back()
        self.assertEqual(shown.view.topic, "one")
        self.assertEqual(look_of(shown), "dialog")
        self.assertEqual(colours_of(shown)["body_style"][1], CYAN)
        self.assertFalse(
            any(isinstance(w, HelpWindow) for w in self.application.windows)
        )

    def test_typing_ahead_into_a_window_a_dialog_is_blocking(self) -> None:
        """F1 typed ahead into a blocked window."""
        dialog = information("Told", "Something")
        number = self.manager.window_id(self.window)
        help_id = 3
        send(self.desktop, "key", id=number, key="f1")
        send(self.desktop, "key", id=help_id, key="escape")
        send(self.desktop, "key", id=2, key="enter")
        self.assertEqual(self.manager.execute(dialog), "ok")
        self.assertIsInstance(self.manager.seen[1], HelpDialog)

    def test_its_drop_down_lists_have_none(self) -> None:
        """Its drop down lists have none."""
        popup = ListPopup(["a"], 0, 10, 1)
        self.manager.window_id(self.window)
        send(self.desktop, "key", id=2, key="f1")
        send(self.desktop, "key", id=2, key="escape")
        self.manager.execute(popup)
        self.assertEqual(self.manager.seen, [popup])
