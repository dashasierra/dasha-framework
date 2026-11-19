"""Applications: the programs that run on the Dasha Desktop.

An application owns a menu bar, any number of windows, and the dialogs it
opens from them. To write one, subclass ``Application``, and in ``start``,
set its ``menus`` and open its first windows::

    class Hello(Application):
        name = "Hello"

        def start(self) -> None:
            self.menus = [
                Menu(title="&File", items=[MenuItem(label="E&xit", action=self.exit)])
            ]
            self.open(
                window=Window(
                    title="Hello",
                    rect=Rect(row=2, column=2, height=6, width=30),
                    lines=["Hello, world"],
                    closable=True,
                )
            )

    if __name__ == "__main__":
        raise SystemExit(Hello().run())

While it is the active application, its ``menus`` make up the menu bar,
together with a Window menu that Dasha Framework adds. It runs until it quits
(typically through File > Exit), not until its windows are closed. With no
windows open, its menu bar stays, with the items that need a window
(``enabled=self.has_window``) greyed out.

``Hello().run()`` runs the application on its own, on a desktop of its own
that closes when the application ends. On a Dasha Desktop, the same
class is started with ``manager.launch(application=Hello)``, or from the Applications
menu once it has been registered (``manager.register``).
"""

import importlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dasha.help import HelpBook, HelpWindow, help_topic_of, open_help
from dasha.menu import Menu
from dasha.printing import say
from dasha.protocol import ADDRESS_VARIABLE
from dasha.window import Window

if TYPE_CHECKING:
    from dasha.manager import PresentationManager
    from dasha.shortcuts import Shortcuts
    from dasha.terminal import Terminal


class Application:
    """An application on the desktop, which owns its menus and windows and
    decides what happens to them."""

    name: str = "Application"
    """The name of the application, as the Applications menu and messages
    show it."""
    single_instance: bool = False
    """Whether only one copy of the application can run at a time. If so,
    launching it again switches to the running copy instead."""
    help_folder: str | Path | None = None
    """The folder of the application's help pages, ``.md`` files with
    ``index.md`` as the default page (see ``dasha.help``). An application
    has no help by default, and F1 then does nothing."""
    is_remote: bool = False
    """Whether this stands for an application running in another process
    (``dasha.remote``)."""
    log_folder: Path | None = None
    """Where ``run`` keeps the log of anything that goes wrong while the
    application runs on its own. By default, where the system keeps
    programs' logs, in a folder named after the application
    (``dasha.logs.app_log_folder``). On the desktop, the desktop's own log is
    used instead."""

    def __init__(self) -> None:
        self.manager: "PresentationManager | None" = None
        """The presentation manager it runs on, once launched."""
        self.windows: list[Window] = []
        """Its windows, in the order they were opened (minimised ones too)."""
        self.menus: list[Menu] = []
        """Its menu bar, while it is the active application. Dasha Framework adds
        a Window menu after them."""
        self.is_running = False
        self._help_book: HelpBook | None = None
        self._help_known = False
        self._help_window: HelpWindow | None = None

    def start(self) -> None:
        """Called once the application has been launched. Set ``menus`` and
        open the first windows here.

        This runs before the desktop is running, so it cannot show a dialog
        itself. Instead, pass a function that shows the dialog to
        ``manager.call_when_running``, which calls it once the desktop is
        running."""

    @property
    def active_window(self) -> Window | None:
        """The application's window nearest the front of the desktop (and not
        minimised), if it has one. This is the window its menus act on."""
        manager = self.manager
        if manager is None:
            return None
        for window in reversed(manager.windows):
            if window.application is self:
                return window
        return None

    def has_window(self) -> bool:
        """Whether the application has a window showing. A method rather
        than a property, unlike the other queries, so that it can be given
        as it is to ``MenuItem(enabled=self.has_window)``."""
        return self.active_window is not None

    def has_help(self) -> bool:
        """Whether the application has help: a ``help_folder`` with pages in
        it. The folder is looked at once. A method rather than a property, as
        ``has_window`` is, so that it can be given as it is to
        ``MenuItem(enabled=self.has_help)``."""
        if not self._help_known:
            self._help_known = True
            if self.help_folder is not None:
                book = HelpBook(self.help_folder)
                self._help_book = book if book.has_topics() else None
        return self._help_book is not None

    def show_help(self, topic: str | None = None) -> None:
        """Show the application's help, if it has any, as F1 does. Without a
        topic, that is the topic of whatever has the focus, or else the
        index. A menu item can be given this as it is::

            MenuItem(
                label="&Help",
                action=self.show_help,
                shortcut=hint(action="help"),
                enabled=self.has_help,
            )

        See ``dasha.help``."""
        manager = self.manager
        if manager is None or not self.has_help():
            return
        assert self._help_book is not None
        if topic is None:
            topic = help_topic_of(manager.answering_dialog or self.active_window)
        self._help_window = open_help(
            manager,
            self._help_book,
            f"{self.name} Help",
            topic,
            window=self._help_window,
            open_window=self.open,
        )

    def open(self, window: Window) -> Window:
        """Show a window belonging to this application, in front of the
        others."""
        if self.manager is None:
            raise RuntimeError("an application opens windows once it is launched")
        window.application = self
        self.windows.append(window)
        self.manager.add(window)
        return window

    def close(self, window: Window) -> None:
        """Close one of the application's windows, as the user would (the
        window's ``request_close`` may keep it open)."""
        if self.manager is not None:
            self.manager.close(window)

    def window_closed(self, window: Window) -> None:
        """Called by the manager when one of the application's windows has
        closed. The application carries on running until it quits."""
        if window in self.windows:
            self.windows.remove(window)

    def set_theme(self, name: str | Path) -> bool:
        """Change every colour on the screen to a theme's, as the system
        menu's Themes does. The theme can be a built-in one (``"default"``,
        ``"dark"`` or ``"monochrome"``), one in ``~/.dasha/themes`` given
        by name, or the theme file at a path. For an application running on
        its own, its desktop changes at once. On the Dasha Desktop, the
        desktop is asked to change, and does so if this is the application
        the user is working in. Returns whether the theme was changed (or
        the change was requested), and ``False`` before the application has
        been launched. See ``PresentationManager.set_theme``."""
        if self.manager is None:
            return False
        return self.manager.set_theme(name)

    def shortcuts_changed(self) -> None:
        """Called when the keyboard shortcuts change while the application
        runs (from Settings..., say): ``manager.shortcuts`` holds the new
        ones. Menu items keep the key hints (``shortcut``) they were made
        with, so an application that shows hints can make its menus again
        here. Does nothing by default."""

    def can_close(self) -> bool:
        """Called before the application ends (``exit``) or the desktop shuts
        down. Return ``False`` to keep running (after offering to save work,
        for example)."""
        return True

    def exit(self) -> None:
        """End the application if ``can_close`` agrees. This is what
        File > Exit does."""
        if self.can_close():
            self.quit()

    def quit(self) -> None:
        """End the application immediately, taking its windows off the
        desktop."""
        if not self.is_running:
            return
        self.is_running = False
        manager = self.manager
        for window in list(self.windows):
            self.windows.remove(window)
            if manager is not None and window.manager is manager:
                manager.remove(window)
        if manager is not None:
            manager.application_ended(self)

    def run(
        self,
        terminal: "Terminal | None" = None,
        *,
        shortcuts: "Shortcuts | None" = None,
    ) -> int:
        """Run the application, and return a process exit code.

        When a Dasha Desktop started this process (and set
        ``DASHA_ADDRESS``), the application runs on that desktop.
        Otherwise, it runs on its own on a desktop of its own that closes
        when the application ends, in the real terminal unless another
        terminal is given. That desktop has no system menu (``≡``), and the
        desktop's exit key (``exit``, Ctrl+Q) asks whether to close the
        application. It has the terminal's size
        before ``start`` is called, so ``start`` can fit windows to the
        screen (``manager.workspace``), and the Monochrome theme if
        ``NO_COLOR`` is set (https://no-color.org). In the real terminal, it
        has the theme the desktop would (``use_starting_theme``), and is
        animated as the desktop is, unless animations were last turned
        off, and it fails softly as the desktop does (an unexpected error
        is logged and reported, and it carries on: see
        ``dasha.recovery``)."""
        if terminal is None and os.environ.get(ADDRESS_VARIABLE):
            # By name: the client imports the manager, which imports this.
            client = importlib.import_module("dasha.client")
            return int(client.run_hosted(self))
        # Imported here: the manager imports this module.
        # pylint: disable-next=import-outside-toplevel
        from dasha.manager import PresentationManager

        manager = PresentationManager(shortcuts=shortcuts)
        # Just this application: no system menu, and leaving closes it.
        manager.stand_alone(self.name)
        if self.log_folder is not None:
            manager.error_log_folder = Path(self.log_folder)
        given = terminal is not None
        # Before ``start``, which can change it.
        manager.use_starting_theme(saved=not given)
        if terminal is None:
            # pylint: disable-next=import-outside-toplevel
            from dasha.terminal import Terminal

            terminal = Terminal()
        # The screen's size from the start, so that ``start`` can size its
        # windows to fit (``manager.workspace``), as on the desktop.
        manager.handle_resize(*terminal.size())
        manager.launch(self)
        if not self.is_running:
            return 0  # it ended as it started
        if given:
            manager.run(terminal)
            return 0
        manager.use_saved_animations()  # animated as the desktop is
        manager.use_saved_escape_timeout()  # and waiting for keys as it does
        manager.survive_errors = True  # fail softly, as the desktop does
        with terminal as real:
            manager.run(real)
        if manager.recovery is not None:  # said once the screen is back
            summary = manager.recovery.summary(manager.stopped_by_errors)
            say(f"{self.name}: {summary}", file=sys.stderr)
        return 1 if manager.stopped_by_errors else 0
