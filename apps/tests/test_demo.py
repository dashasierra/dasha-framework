"""Tests for the Demo: its windows, layouts and menus."""

import os
import tempfile
import unittest

from dasha.application import Application
from dasha.events import MouseEvent
from dasha.help import (
    HelpBook,
    HelpWindow,
    help_topic_of,
    is_external,
    resolve_link,
)
from dasha.manager import PresentationManager
from dasha.markdown import lay_out, parse
from dasha.shortcuts import Shortcuts
from dasha.canvas import Rect
from dasha.widgets import (
    Collapsible,
    GroupBox,
    Splitter,
    Table,
    Tabs,
    TreeView,
    Widget,
)
from dasha.window import Window

from demo import (
    Demo,
    FilesWindow,
    find_folder,
    folder_dialog,
    folder_nodes,
    pick_several_dialog,
    explorer_window,
    settings_dialog,
    survey_dialog,
)


def inside(widget: Widget, container: Widget) -> bool:
    """Whether ``widget`` is in ``container``, or in a container in it."""
    parent = widget.parent
    while parent is not None:
        if parent.anchor is container:
            return True
        parent = parent.anchor.parent
    return False


class DemoTests(unittest.TestCase):
    """The Widgets, More widgets and Files windows."""

    def setUp(self) -> None:
        self.manager = PresentationManager()
        self.manager.handle_resize(80, 24)
        demo = self.manager.launch(Demo)
        assert isinstance(demo, Demo)
        self.demo = demo

    def choose(self, label: str) -> None:
        """Choose an item of the File menu."""
        item = next(i for i in self.demo.menus[0].items if i.label == label)
        assert item.action is not None and item.is_available, label
        item.action()

    def titles(self) -> list[str]:
        """The demo's windows' titles."""
        return [window.title for window in self.demo.windows]

    def test_windows(self) -> None:
        """It starts with its three windows, Widgets in front."""
        self.assertEqual(self.titles(), ["Files", "More widgets", "Widgets"])
        self.assertEqual(self.manager.windows[-1].title, "Widgets")

    def assert_laid_out(self, window: Window) -> None:
        """No two widgets overlap, but for a widget inside a container's
        rect (a group box's), and each is inside the frame."""
        interior = window.interior
        shown = window.shown_widgets
        for widget in shown:
            rect = widget.rect
            self.assertLessEqual(rect.right, interior.width, (window.title, widget))
            self.assertLessEqual(rect.bottom, interior.height, (window.title, widget))
        for widget in shown:
            if isinstance(widget.parent, GroupBox):  # inside its frame
                frame = widget.parent.rect
                inner = Rect(
                    frame.row + 1, frame.column + 1, frame.height - 2, frame.width - 2
                )
                self.assertEqual(
                    widget.rect.intersect(inner), widget.rect, (window.title, widget)
                )
        for number, widget in enumerate(shown):
            for other in shown[number + 1 :]:
                if inside(other, widget) or inside(widget, other):
                    continue
                self.assertTrue(
                    widget.rect.intersect(other.rect).is_empty,
                    (window.title, widget.rect, other.rect),
                )

    def test_layouts(self) -> None:
        """Its windows and dialogs: nothing overlaps."""
        self.assert_laid_out(survey_dialog())
        self.assert_laid_out(pick_several_dialog())
        settings = settings_dialog()
        self.assert_laid_out(settings)
        tabs = settings.widgets[0]
        assert isinstance(tabs, Tabs)
        tabs.select(1)
        self.assert_laid_out(settings)  # the other page
        self.assert_laid_out(explorer_window())
        self.assert_laid_out(folder_dialog(directory=os.getcwd()))
        for window in self.demo.windows:
            self.assert_laid_out(window)
        more = next(w for w in self.demo.windows if w.title == "More widgets")
        options = more.widget(name="options")
        assert isinstance(options, Collapsible)
        options.expand()
        self.assert_laid_out(more)  # still nothing overlaps

    def test_new_windows(self) -> None:
        """Each window can be opened again."""
        for label in ("&New window", "&More widgets", "&Files"):
            self.choose(label)
        self.assertEqual(len(self.demo.windows), 6)

    def test_file_dialogs_need_a_files_window(self) -> None:
        """Open, Save as and Pick several are greyed out unless a Files
        window is in front."""
        items = {i.label: i for i in self.demo.menus[0].items}
        self.assertFalse(items["&Open..."].is_available)
        files = next(w for w in self.demo.windows if isinstance(w, FilesWindow))
        self.manager.bring_to_front(files)
        self.assertTrue(items["&Open..."].is_available)
        self.assertTrue(items["&Pick several..."].is_available)
        self.assertFalse(items["&Save"].is_available)

    def test_explorer(self) -> None:
        """Moving through the folders shows their files; Programs opens
        to show Tools; the divider moves and the tree and table follow it;
        the table's menu deletes a file."""
        self.choose("&Explorer")
        window = self.demo.windows[-1]
        folders, files = window.widget(name="folders"), window.widget(name="files")
        assert isinstance(folders, TreeView) and isinstance(files, Table)
        self.assertIn("changes.txt", files.items)  # Documents, to start
        folders.move_to(2)  # Programs
        self.assertIn("command.com", files.items)
        folders.expand()
        self.assertEqual([node.label for node in folders.visible_nodes][3], "Tools")
        splitter = window.widget(name="splitter")
        assert isinstance(splitter, Splitter)
        splitter.move_divider(22)
        self.assertEqual((folders.rect.width, files.rect.column), (22, 23))
        said: list[str] = []
        assert window.manager is not None
        window.manager.execute = lambda dialog: said.append(  # type: ignore[method-assign]
            str(dialog.widget(name="message").value)
        )
        files.move_to(index=1)
        # Both presses of a double-click on the highlighted row (row 2: the
        # headings are row 0); the first press of one highlights it.
        double = MouseEvent(action="press", button="left", row=2, column=30, clicks=2)
        files.handle_mouse(event=double, row=2, column=30)
        files.handle_key(key="enter", shortcuts=Shortcuts())
        name = files.selected_rows[0][0]
        self.assertEqual(said, [f"Opened {name} (not really)."] * 2)
        menu = files.popup_menu(shortcuts=Shortcuts())
        assert menu is not None
        delete = next(item for item in menu.items if item.label == "&Delete")
        before = len(files.data)
        assert delete.action is not None
        delete.action()
        self.assertEqual(len(files.data), before - 1)

    def test_explorer_made_small(self) -> None:
        """Made too short for the files, the Explorer does not scroll as a
        whole (moving both panes at once): the table and the tree shrink,
        and each scrolls by itself."""
        self.choose("&Explorer")
        window = self.demo.windows[-1]
        rect = window.rect
        window.rect = Rect(rect.row, rect.column, 8, rect.width)
        folders, files = window.widget(name="folders"), window.widget(name="files")
        assert isinstance(folders, TreeView) and isinstance(files, Table)
        self.assertEqual(window.max_scroll, (0, 0))
        self.assertEqual((folders.rect.height, files.rect.height), (6, 6))
        files.handle_key(key="end", shortcuts=Shortcuts())
        self.assertGreater(files.first_visible, 0)  # the table scrolled
        self.assertEqual(folders.first_visible, 0)  # the tree did not
        self.assertEqual(window.scroll_row, 0)

    def test_choose_folder(self) -> None:
        """File > Choose folder... opens on the current folder, and OK says
        which folder was chosen; Cancel says nothing."""
        said: list[str] = []
        answers = ["ok"]

        def execute(dialog: Window) -> str:
            if any(widget.name == "folders" for widget in dialog.widgets):
                folders = dialog.widget(name="folders")
                assert isinstance(folders, TreeView)
                node = folders.selected_node
                assert node is not None
                self.assertEqual(
                    os.path.normcase(node.data), os.path.normcase(os.getcwd())
                )
                return answers.pop()
            said.append(str(dialog.widget(name="message").value))
            return "ok"

        self.manager.execute = execute  # type: ignore[method-assign]
        self.choose("&Choose folder...")
        self.assertEqual(said, [f"Chose {os.getcwd()}"])
        answers.append("cancel")
        self.choose("&Choose folder...")
        self.assertEqual(len(said), 1)

    def help_window(self) -> HelpWindow:
        """The Demo's help window, which must be open."""
        found = [w for w in self.demo.windows if isinstance(w, HelpWindow)]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_help_on_a_widget(self) -> None:
        """F1 on the Name box goes straight to its page."""
        self.assertTrue(self.demo.has_help())
        window = self.manager.active_window
        assert window is not None
        window.focus(window.widget(name="name"))
        self.manager.handle_event("f1")
        self.assertEqual(self.help_window().view.topic, "name")

    def test_help_on_a_window(self) -> None:
        """A widget with no topic has its window's."""
        window = self.manager.active_window
        assert window is not None
        window.focus_next()  # from the Name box to the Age box...
        window.focus_next()  # ...to a button
        self.manager.handle_event("f1")
        self.assertEqual(self.help_window().view.topic, "widgets")

    def test_help_from_the_menu(self) -> None:
        """Help > Help does what F1 does."""
        menu = next(m for m in self.demo.menus if m.title == "&Help")
        item = menu.items[0]
        self.assertTrue(item.is_available)
        self.assertEqual(item.shortcut, "F1")
        assert item.action is not None
        item.action()
        self.assertEqual(self.help_window().view.topic, "name")

    def test_the_survey_has_topics(self) -> None:
        """The survey has topics."""
        dialog = survey_dialog()
        self.assertEqual(help_topic_of(dialog), "survey#do-you-like-dasha-framework")
        dialog.focus(dialog.widget(name="tried"))
        self.assertEqual(help_topic_of(dialog), "survey#what-have-you-tried")
        dialog.focus(dialog.widget(name="ok"))
        self.assertEqual(help_topic_of(dialog), "survey")

    def test_the_help_pages_hang_together(self) -> None:
        """Every link goes to a page that is there, and to a heading on it,
        but for the one page that shows what a missing page looks like."""
        book = HelpBook(Demo.help_folder or "")
        for topic in book.topics():
            for link in lay_out(parse(book.page(topic)), 60).links:
                if is_external(link.target) or link.target == "missing.md":
                    continue
                with self.subTest(topic=topic, target=link.target):
                    name, anchor = resolve_link(topic, link.target)
                    text = book.read(name)
                    assert text is not None
                    if anchor:
                        self.assertIn(anchor, lay_out(parse(text), 60).anchors)

    def test_the_topics_the_widgets_name_are_there(self) -> None:
        """The topics the widgets name are there."""
        book = HelpBook(Demo.help_folder or "")
        for topic in ("index", "name", "age", "widgets", "files", "survey"):
            self.assertIsNotNone(book.read(topic), topic)
        anchors = lay_out(parse(book.page("survey")), 60).anchors
        self.assertIn("do-you-like-dasha-framework", anchors)
        self.assertIn("what-have-you-tried", anchors)

    def test_file_exit(self) -> None:
        """File > Exit ends it; closing its windows does not."""
        for window in list(self.demo.windows):
            self.manager.close(window)
        self.assertTrue(self.demo.is_running)
        self.assertFalse(self.demo.has_window())
        self.choose("E&xit")
        self.assertFalse(self.demo.is_running)

    def test_is_an_application(self) -> None:
        """Named Demo, as the Applications menu lists it."""
        self.assertTrue(issubclass(Demo, Application))
        self.assertEqual(Demo.name, "Demo")


class FolderTests(unittest.TestCase):
    """The tree of folders, in a folder made for the test."""

    def setUp(self) -> None:
        # Its real path, as the tree shows it (not RUNNER~1, or /var).
        self.top = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(self.remove, self.top)
        for path in ("beta/inner", "Alpha", "gamma"):
            os.makedirs(os.path.join(self.top, path))
        with open(os.path.join(self.top, "file.txt"), "w", encoding="utf-8"):
            pass

    @staticmethod
    def remove(top: str) -> None:
        """Delete the test's folder."""
        for path, folders, files in os.walk(top, topdown=False):
            for name in files:
                os.remove(os.path.join(path, name))
            for name in folders:
                os.rmdir(os.path.join(path, name))
        os.rmdir(top)

    def test_folders_only_in_order(self) -> None:
        """Only folders, ignoring case in the order, each to load later."""
        nodes = folder_nodes(path=self.top)
        self.assertEqual([node.label for node in nodes], ["Alpha", "beta", "gamma"])
        beta = nodes[1]
        self.assertEqual(beta.data, os.path.join(self.top, "beta"))
        self.assertEqual(beta.children, [])
        self.assertTrue(beta.has_children)
        beta.loaded()
        self.assertEqual([node.label for node in beta.children], ["inner"])
        self.assertEqual(folder_nodes(path=os.path.join(self.top, "none")), [])

    def test_find_folder(self) -> None:
        """A folder is found by loading the folders on the way to it; a
        folder that is not there finds the nearest one above it."""
        roots = folder_nodes(path=self.top)
        inner = os.path.join(self.top, "beta", "inner")
        node = find_folder(roots=roots, directory=inner)
        assert node is not None
        self.assertEqual(node.path, ["beta", "inner"])
        missing = find_folder(roots=roots, directory=os.path.join(inner, "none"))
        self.assertIs(missing, node)
        self.assertIsNone(find_folder(roots=roots, directory=self.top))

    def test_find_folder_through_a_link(self) -> None:
        """A path through a link finds the folder it leads to, as a Windows
        short name (``RUNNER~1``) does."""
        link = os.path.join(self.top, "link")
        try:
            os.symlink(os.path.join(self.top, "beta"), link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("cannot make a link here")
        self.addCleanup(os.remove if os.name != "nt" else os.rmdir, link)
        roots = [node for node in folder_nodes(path=self.top) if node.label != "link"]
        node = find_folder(roots=roots, directory=os.path.join(link, "inner"))
        assert node is not None
        self.assertEqual(node.path, ["beta", "inner"])

    def test_dialog(self) -> None:
        """The dialog starts on the folder, highlighted and showing, with its
        path below; moving shows the next one's path."""
        inner = os.path.join(self.top, "beta", "inner")
        dialog = folder_dialog(directory=inner)
        folders, path = dialog.widget(name="folders"), dialog.widget(name="path")
        assert isinstance(folders, TreeView)
        node = folders.selected_node
        assert node is not None
        self.assertEqual(os.path.normcase(node.data), os.path.normcase(inner))
        self.assertEqual(path.value, inner if len(inner) <= 46 else "..." + inner[-43:])
        folders.handle_key(key="down", shortcuts=Shortcuts())
        gamma = os.path.join(self.top, "gamma")
        self.assertTrue(str(path.value).endswith(gamma[-40:]))


if __name__ == "__main__":
    unittest.main()
