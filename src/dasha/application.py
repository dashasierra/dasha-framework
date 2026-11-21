"""Applications that run on the desktop."""

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
    """An application with its menus and windows."""

    name: str = "Application"
    """Application name."""
    single_instance: bool = False
    """Whether only one copy may run."""
    help_folder: str | Path | None = None
    """Folder of help pages, if any."""
    is_remote: bool = False
    """Whether it runs in another process."""
    log_folder: Path | None = None
    """Folder for the stand-alone log."""

    def __init__(self) -> None:
        self.manager: "PresentationManager | None" = None
        """The presentation manager it runs on, once launched."""
        self.windows: list[Window] = []
        """Its windows, in the order they were opened (minimised ones too)."""
        self.menus: list[Menu] = []
        """The application's menus."""
        self.is_running = False
        self._help_book: HelpBook | None = None
        self._help_known = False
        self._help_window: HelpWindow | None = None

    def start(self) -> None:
        """Called once launched; set menus and open windows."""

    @property
    def active_window(self) -> Window | None:
        """The frontmost unminimised window, if any."""
        manager = self.manager
        if manager is None:
            return None
        for window in reversed(manager.windows):
            if window.application is self:
                return window
        return None

    def has_window(self) -> bool:
        """Whether a window is showing."""
        return self.active_window is not None

    def has_help(self) -> bool:
        """Whether the application has help pages."""
        if not self._help_known:
            self._help_known = True
            if self.help_folder is not None:
                book = HelpBook(self.help_folder)
                self._help_book = book if book.has_topics() else None
        return self._help_book is not None

    def show_help(self, topic: str | None = None) -> None:
        """Show help, as F1 does.

        :param topic: Help page, or ``None`` for the focused topic.
        """
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
        """Show a window in front.

        :param window: The window.
        """
        if self.manager is None:
            raise RuntimeError("an application opens windows once it is launched")
        window.application = self
        self.windows.append(window)
        self.manager.add(window)
        return window

    def close(self, window: Window) -> None:
        """Close a window, as the user would.

        :param window: The window.
        """
        if self.manager is not None:
            self.manager.close(window)

    def window_closed(self, window: Window) -> None:
        """Called when a window has closed.

        :param window: The window.
        """
        if window in self.windows:
            self.windows.remove(window)

    def set_theme(self, name: str | Path) -> bool:
        """Change the theme; return whether it changed.

        :param name: Theme name or file path.
        """
        if self.manager is None:
            return False
        return self.manager.set_theme(name)

    def shortcuts_changed(self) -> None:
        """Called when the keyboard shortcuts change."""

    def can_close(self) -> bool:
        """Whether the application may end."""
        return True

    def exit(self) -> None:
        """End the application if ``can_close`` agrees."""
        if self.can_close():
            self.quit()

    def quit(self) -> None:
        """End the application immediately."""
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
        """Run the application; return an exit code.

        :param terminal: Terminal to use, or ``None`` for the real one.
        :param shortcuts: Key bindings, or ``None`` for the defaults.
        """
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
