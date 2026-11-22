"""The presentation manager: desktop, bars and windows."""

# pylint: disable=too-many-lines

import signal
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast

from dasha import __version__, logs, registry, shell, style, theme
from dasha.animation import WindowAnimation, frame_parts
from dasha.application import Application
from dasha.recovery import GuardedTerminal, Recovery, TerminalFailed
from dasha.registry import AppEntry, slug
from dasha.rundialog import RunDialog
from dasha.settings import SettingsDialog
from dasha.canvas import Canvas, Rect
from dasha.desktop import Desktop
from dasha.dialog import (
    Dialog,
    ListPopup,
    MenuPopup,
    Popup,
    SuggestionPopup,
    confirm,
    information,
)
from dasha.events import (
    Event,
    InputDecoder,
    KeyReleaseEvent,
    MouseEvent,
    PasteEvent,
    read_events,
)
from dasha.help import (
    DESKTOP_PAGES,
    HelpBook,
    HelpWindow,
    help_topic_of,
    open_help,
)
from dasha.menu import Menu, MenuBar, MenuItem, separator
from dasha.scrollbar import AutoRepeat
from dasha.shortcuts import DEFAULT_PATH as SHORTCUTS_PATH
from dasha.shortcuts import Shortcuts, key_from_pretty
from dasha.statusbar import StatusBar, status_text
from dasha.terminal import Terminal
from dasha.widgets import AutoCompleteBox, Widget
from dasha.window import Window
from dasha.windowmenu import fill_application_window_menu, window_menu

if TYPE_CHECKING:
    from dasha.hosting import AppServer

AppT = TypeVar("AppT", bound=Application)
"""Any kind of application."""


def drawn_active(
    window: Window, active: Window | None, windows: Sequence[Window]
) -> bool:
    """Whether to draw a window as active.

    :param window: The window.
    :param active: The active window, if any.
    :param windows: Every window, back to front.
    """
    if window is active:
        return True
    if active is None or not active.close_on_outside_click:
        return False
    for front in reversed(windows):
        if front is window:
            return True
        if not front.close_on_outside_click:
            return False
    return False


def _end_on_signal(number: int, frame: object) -> None:
    del frame
    raise SystemExit(128 + number)


def _catch_ending_signals() -> dict[int, Any]:
    """End ``run`` on SIGTERM and SIGHUP; return the old handlers."""
    caught: dict[int, Any] = {}
    if threading.current_thread() is not threading.main_thread():
        return caught
    for name in ("SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is not None:
            try:
                caught[number] = signal.signal(number, _end_on_signal)
            except (OSError, ValueError):
                pass
    return caught


def _with_mnemonic(label: str, taken: set[str]) -> str:
    """A label with a free mnemonic letter marked.

    :param label: The label, without ``&``.
    :param taken: Letters already taken; updated.
    """
    for index, char in enumerate(label):
        if char.isalnum() and char.lower() not in taken:
            taken.add(char.lower())
            return f"{label[:index]}&{label[index:]}"
    return label


class _RestoreItem(MenuItem):  # pylint: disable=too-few-public-methods
    """A menu item restoring a minimised window."""


class _AppItem(MenuItem):  # pylint: disable=too-few-public-methods
    """A system menu item switching application."""


@dataclass
class _Drag:
    """A mouse drag in progress."""

    window: Window
    kind: str  # "move", "resize", "vertical_thumb", "horizontal_thumb", "repeat"
    # Moving: where along the title bar it was grabbed. Resizing: how far left
    # of the corner the grip was grabbed. Otherwise unused.
    grab_offset: int = 0
    vertical: bool = True  # "repeat": which of the window's bars
    repeat: AutoRepeat = field(default_factory=AutoRepeat)


@dataclass
class _Adjust:
    """Moving or resizing a window from the keyboard."""

    window: Window
    kind: str  # "move" or "resize"
    original: Rect  # where it was, for cancelling
    # Where it goes back to when restored, if it was maximised: cancelling
    # maximises it again, as it was.
    maximised_from: Rect | None = None


# pylint: disable-next=too-many-instance-attributes,too-many-public-methods
class PresentationManager:
    """Runs the screen: desktop, menu bar, status bar and windows.

    :param desktop: The background, or ``None`` for the default.
    :param windows: Windows to start with.
    :param shortcuts: Key bindings, or ``None`` for the defaults.
    """

    escape_timeout: float = registry.ESCAPE_TIMEOUT / 1000
    """Seconds to wait after a lone ESC."""

    double_click_time: float = 0.4
    """Seconds allowed between double-click presses."""

    rescue_margin: int = 4
    """Title bar columns kept on screen after a resize."""

    system_menu_title: str = "\N{IDENTICAL TO}"
    """The burger icon that titles the system menu."""

    confirm_exit: bool = True
    """Whether quitting asks for confirmation."""
    about_title: str = "About Dasha Desktop"
    about_message: str = (
        f"Dasha Desktop - v{__version__}\n"
        "\n"
        "https://github.com/dashasierra/dasha-framework"
    )
    """The About box's title and message."""
    use_processes: bool = False
    """Whether ``start`` uses separate processes."""
    quit_when_empty: bool = False
    """Whether ``run`` stops when the last application ends."""
    show_system_menu: bool = True
    """Whether the system menu is shown."""
    exit_title: str = "Exit"
    exit_message: str = (
        "Warning: Shutting down Dasha Desktop will\nclose all open applications."
    )
    exit_button: str = "&Shutdown"
    """The label of the exit dialog's OK button."""
    exit_status: str = "Press Shutdown to close Dasha Desktop"
    program_name: str = "Dasha Desktop"
    """The program's name in messages."""
    help_folder: Path | None = None
    """Folder of the desktop's own help pages."""

    def __init__(
        self,
        desktop: Desktop | None = None,
        windows: Iterable[Window] = (),
        shortcuts: Shortcuts | None = None,
    ) -> None:
        self.desktop = desktop if desktop is not None else Desktop()
        self.shortcuts = shortcuts if shortcuts is not None else Shortcuts()
        self._windows: list[Window] = []
        self._running = False
        # What call_when_running holds back until the loop starts; None
        # while it is going.
        self._when_running: list[Callable[[], object]] | None = []
        # What call_from_thread has been given, waiting for the loop's thread.
        self._from_threads: deque[Callable[[], object]] = deque()
        self._drag: _Drag | None = None
        # The last left press: when, where, and how many clicks it counted.
        self._last_press: tuple[float, int, int, int] | None = None
        self._adjust: _Adjust | None = None
        self._minimised: list[Window] = []
        # The system menu items that list minimised windows, so they can be
        # replaced without disturbing items an application added.
        self._restore_items: list[MenuItem] = []
        self._applications: list[Application] = []
        self._active_app: Application | None = None
        self._window_menus: dict[Application, Menu] = {}
        self.server: "AppServer | None" = None
        """Runs applications in processes of their own, once one is started."""
        self.registry: dict[str, AppEntry] = {}
        """Applications offered, by id."""
        self._applications_item = MenuItem(
            "A&pplications",
            submenu=Menu("Applications", []),
            status="Starts an application",
        )
        self._run_item = MenuItem(
            "&Run...",
            self.run_dialog,
            status="Runs a Python script or module as an application, once",
        )
        self._help_window: HelpWindow | None = None
        self._size = (80, 24)  # updated by handle_resize before the first frame
        # Whether _size is the screen's, not that guess: windows are only
        # kept reachable (keep_reachable) against a size that is known.
        self._size_known = False
        # Set while run() is going, so execute() can run dialogs.
        self._terminal: Terminal | None = None
        self._decoder = InputDecoder()
        self._on_screen: Canvas | None = None
        self._screen_size: tuple[int, int] | None = None
        # Where the mouse was last reported (row, column), for show_mouse.
        self._mouse_at: tuple[int, int] | None = None
        self.menu_bar = MenuBar(self.shortcuts)
        self.status_bar = StatusBar()
        # Animations (see animations): the window one to draw before the next frame, and
        # while drawing it, how far along it is; the drop-down last drawn
        # (so a newly opened one drops), and how far out it is.
        self._animation: WindowAnimation | None = None
        self._moving: tuple[WindowAnimation, float] | None = None
        self._dropped: Menu | None = None
        self._dropping = 1.0
        self._animations_item = MenuItem(
            "A&nimations", self._toggle_animations, status=""
        )
        self._shutdown_item = MenuItem(
            "&Shutdown",
            self.request_exit,
            self.shortcuts.hint("exit"),
            "Shuts Dasha Desktop down, closing every application",
        )
        self._prompt_item = MenuItem(
            "&Command prompt",
            self.command_prompt,
            self.shortcuts.hint("command_prompt"),
            "Leaves for a command prompt; type exit to come back",
        )
        self.system_menu = Menu(
            self.system_menu_title,
            [
                MenuItem("&About", self.about_box, status="About Dasha Desktop"),
                MenuItem(
                    "S&ettings...",
                    self.settings_dialog,
                    status="Changes the colours, keys, desktop and applications",
                ),
                MenuItem(
                    "&Themes",
                    submenu=Menu("Themes", on_open=self._list_themes),
                    status="Changes the colours of everything on the screen",
                    enabled=lambda: not self.colours_locked,
                ),
                self._animations_item,
                self._prompt_item,
                separator(),
                self._shutdown_item,
            ],
        )
        """Always first on the menu bar. Add items to ``system_menu.items``."""
        self._label_animations()
        for window in windows:
            self.add(window)

    # Settings

    shortcuts_path: Path = SHORTCUTS_PATH
    """The shortcuts file."""

    def settings_dialog(self) -> None:
        """Show the Settings dialog."""
        if self.can_show_dialogs:
            self.execute(SettingsDialog(self))

    def set_shortcuts(self, shortcuts: Shortcuts) -> None:
        """Use other keyboard shortcuts.

        :param shortcuts: The new key bindings.
        """
        self.shortcuts = shortcuts
        self.menu_bar.shortcuts = shortcuts
        self._shutdown_item.shortcut = shortcuts.hint("exit")
        self._prompt_item.shortcut = shortcuts.hint("command_prompt")
        for application in list(self._applications):
            application.shortcuts_changed()
        if self.server is not None:
            bindings = {
                action: list(keys) for action, keys in shortcuts.bindings.items()
            }
            for host in self.server.hosts:
                host.send("shortcuts", shortcuts=bindings)

    colour_depth: str = "auto"
    """How colours are drawn."""

    def set_colour_depth(self, depth: str) -> None:
        """Change the colour depth.

        :param depth: One of ``style.COLOUR_DEPTHS``.
        """
        style.set_colour_depth(depth)
        self.colour_depth = depth
        self._on_screen = None  # draw every cell again

    # Themes

    theme_name: str | None = "default"
    """The current theme's name, or ``None``."""
    themes_folder: Path = theme.THEMES_FOLDER
    """The folder holding the theme files that the Themes menu offers."""
    colours_path: Path | None = theme.DEFAULT_PATH
    """The colours file, or ``None``."""
    remember_theme: bool = False
    """Whether the chosen theme is remembered."""
    settings_path: Path = registry.SETTINGS_PATH
    """The desktop settings file that remembered choices are written to."""

    @property
    def colours_locked(self) -> bool:
        """Whether ``NO_COLOR`` holds the theme at Monochrome."""
        return theme.no_colour_set()

    def set_theme(self, name: str | Path, *, remember: bool | None = None) -> bool:
        """Change the theme; return whether it changed.

        :param name: Theme name or file path.
        :param remember: Whether to remember it, or ``None`` for the default.
        """
        if self.colours_locked and name != "monochrome":
            return False
        try:
            colours = theme.load_named_theme(name, self.themes_folder)
        except theme.ThemeError as error:
            self._theme_problem(str(error))
            return False
        self.use_theme(colours, str(name))
        if self.remember_theme if remember is None else remember:
            self._remember(str(name))
        return True

    def use_starting_theme(self, *, saved: bool = True) -> None:
        """Choose a stand-alone application's starting theme.

        :param saved: Whether to try the remembered theme.
        """
        if self.colours_locked or not style.terminal_has_colours():
            self.set_theme("monochrome", remember=False)
            return
        if saved:
            path = self.colours_path
            try:
                name = registry.read_theme_setting(self.settings_path)
                if name is not None:
                    colours = theme.load_named_theme(name, self.themes_folder)
                    self.use_theme(colours, name)
                    return
                if path is not None and path.is_file():
                    self.use_theme(theme.load_theme(path), None)
                    return
            except (registry.ManifestError, theme.ThemeError):
                pass

    def use_theme(self, colours: theme.Theme, name: str | None) -> None:
        """Show a theme.

        :param colours: The theme.
        :param name: Its name, or ``None``.
        """
        if self.colours_locked:
            colours, name = dict(theme.MONOCHROME_THEME), "monochrome"
        theme.apply_theme(colours)
        self.theme_name = name
        for window in (*self._windows, *self._minimised):
            window.theme_changed()
        self._on_screen = None  # draw every cell again
        if self.server is not None:
            self.server.share_theme()

    def _use_colours_file(self) -> None:
        """Use the colours file."""
        if self.colours_path is None:
            return
        try:
            colours = theme.load_theme(self.colours_path)
        except theme.ThemeError as error:
            self._theme_problem(str(error))
            return
        self.use_theme(colours, None)
        if self.remember_theme:
            self._remember(None)

    def _remember(self, name: str | None) -> None:
        if self.colours_locked:
            return  # the theme chosen before is kept for after NO_COLOR
        try:
            registry.save_theme_setting(name, self.settings_path)
        except OSError as error:
            self._theme_problem(f"The theme could not be remembered:\n{error}")

    def _theme_problem(self, message: str, title: str = "Themes") -> None:
        if self.can_show_dialogs:
            self.execute(information(title, message))

    def _list_themes(self, menu: Menu) -> None:
        """Fill the Themes menu.

        :param menu: The Themes menu.
        """
        items: list[MenuItem] = []
        taken = {"c"}  # Colours file
        for name in theme.theme_names(self.themes_folder):
            built_in = name in theme.BASES
            label = name.capitalize() if built_in else name.replace("&", "&&")
            mark = "\N{SQUARE ROOT} " if name == self.theme_name else "  "
            items.append(
                MenuItem(
                    mark + (_with_mnemonic(label, taken) if built_in else label),
                    partial(self.set_theme, name),
                    status=f"Changes to the {label} theme",
                )
            )
        if self.colours_path is not None and self.colours_path.is_file():
            mark = "\N{SQUARE ROOT} " if self.theme_name is None else "  "
            items += [
                separator(),
                MenuItem(
                    f"{mark}&Colours file",
                    self._use_colours_file,
                    status=f"Changes to the colours in {self.colours_path.name}",
                ),
            ]
        menu.items = items

    # Animations

    animations: bool = False
    """Whether changes are animated."""
    animation_frames: int = 2
    """Intermediate frames per animation."""
    animation_frame_time: float = 0.02
    """How many seconds each intermediate frame stays on the screen."""
    remember_animations: bool = False
    """Whether the animations setting is remembered."""

    def set_animations(self, on: bool, *, remember: bool | None = None) -> None:
        """Turn animations on or off.

        :param on: Whether to turn them on.
        :param remember: Whether to remember it, or ``None`` for the default.
        """
        self.animations = on
        self._animation = None
        if self.remember_animations if remember is None else remember:
            try:
                registry.save_animations_setting(on, self.settings_path)
            except OSError as error:
                self._theme_problem(
                    f"The animations setting could not be remembered:\n{error}",
                    "Animations",
                )

    def use_saved_escape_timeout(self) -> None:
        """Use the saved ESC wait."""
        try:
            wait = registry.read_escape_timeout_setting(self.settings_path)
        except registry.ManifestError:
            return  # the desktop says what is wrong with it, when it starts
        self.escape_timeout = wait / 1000

    def use_saved_animations(self) -> None:
        """Use the saved animations setting."""
        try:
            self.animations = registry.read_animations_setting(self.settings_path)
        except registry.ManifestError:
            pass  # the desktop says what is wrong with it, when it starts

    def _toggle_animations(self) -> None:
        self.set_animations(not self.animations)

    def _label_animations(self) -> None:
        """Update the Animations menu item."""
        item = self._animations_item
        item.label = f"A&nimations: {'On' if self.animations else 'Off'}"
        item.status = (
            "Turns off menus dropping down and windows zooming"
            if self.animations
            else "Turns on menus dropping down and windows zooming"
        )

    # Showing the mouse

    show_mouse: bool = False
    """Whether the cell under the mouse is inverted."""
    remember_show_mouse: bool = False
    """Whether the ``show_mouse`` setting is remembered."""

    def set_show_mouse(self, on: bool, *, remember: bool | None = None) -> None:
        """Turn ``show_mouse`` on or off.

        :param on: Whether to turn it on.
        :param remember: Whether to remember it, or ``None`` for the default.
        """
        self.show_mouse = on
        if self.remember_show_mouse if remember is None else remember:
            try:
                registry.save_show_mouse_setting(on, self.settings_path)
            except OSError as error:
                self._theme_problem(
                    f"The mouse setting could not be remembered:\n{error}",
                    "Show the mouse",
                )

    def _notice(self, event: Event, dialog: Dialog | None = None) -> bool:
        """Handle desktop-wide keys first; return whether used.

        :param event: The event.
        :param dialog: The waiting dialog, if any.
        """
        if isinstance(event, MouseEvent):
            self._mouse_at = (event.row, event.column)
            return False
        if not isinstance(event, str) or (
            dialog is not None and dialog.takes_every_key
        ):
            return False
        if self.shortcuts.matches("show_mouse", event):
            self.set_show_mouse(not self.show_mouse)
            return True
        if self.shortcuts.matches("command_prompt", event):
            self.command_prompt()
            return True
        return False

    def _paint_mouse(self, canvas: Canvas) -> None:
        """Invert the cell under the mouse.

        :param canvas: Canvas to draw on.
        """
        if not self.show_mouse or self._mouse_at is None:
            return
        row, column = self._mouse_at
        if 0 <= row < canvas.height and 0 <= column < canvas.width:
            char, look = canvas.cell(row, column)
            canvas.write(row, column, char, replace(look, reverse=not look.reverse))

    def _start_animation(self, window: Window) -> WindowAnimation | None:
        """Start a window animation, if on.

        :param window: The window.
        """
        if not (self.animations and self._size_known):
            return None
        return WindowAnimation.of(window)

    @property
    def _status_middle(self) -> Rect:
        """The middle of the status bar, where windows minimise to."""
        columns, lines = self._size
        return Rect(lines - 1, columns // 2, 0, 0)

    def _animate(self, terminal: Terminal) -> None:
        """Draw the frames of a new animation.

        :param terminal: The terminal.
        """
        animation, self._animation = self._animation, None
        menu = self.menu_bar.open_menu
        drops = menu is not None and menu is not self._dropped
        self._dropped = menu
        if not self.animations:
            return
        if animation is not None and (
            (animation.window in self._windows) != animation.showing
            or animation.start == animation.end
        ):
            return  # closed, say, or minimised again, in the meantime
        if animation is None and not drops:
            return
        try:
            for part in frame_parts(self.animation_frames):
                if animation is not None:
                    self._moving = (animation, part)
                else:
                    self._dropping = part
                self._show(terminal)
                time.sleep(self.animation_frame_time)
        finally:
            self._moving = None
            self._dropping = 1.0

    # Applications

    @property
    def applications(self) -> tuple[Application, ...]:
        """The running applications, in the order they were launched."""
        return tuple(self._applications)

    @staticmethod
    def application_of(window: Window) -> Application | None:
        """A window's application, if any.

        :param window: The window.
        """
        return window.application

    def register(
        self,
        applications: (
            "type[Application] | AppEntry | Mapping[str, type[Application]]"
            " | Iterable[AppEntry]"
        ),
    ) -> None:
        """Offer applications in the Applications menu.

        :param applications: A class, entry, mapping or entries.
        """
        if isinstance(applications, Mapping):
            entries = [
                replace(AppEntry.of(cls, slug(name)), name=name)
                for name, cls in applications.items()
            ]
        elif isinstance(applications, (type, AppEntry)):
            single = applications
            entries = [single if isinstance(single, AppEntry) else AppEntry.of(single)]
        else:
            entries = list(applications)
        for entry in entries:
            self.registry[entry.id] = entry
        self._build_applications_menu()

    def _build_applications_menu(self) -> None:
        def item(entry: AppEntry) -> MenuItem:
            return MenuItem(
                f"&{entry.name}",
                partial(self.start, entry),
                status=f"Starts {entry.name}",
            )

        def by_name(entry: AppEntry) -> str:
            return entry.name.lower()

        entries = sorted(self.registry.values(), key=by_name)
        items = [item(entry) for entry in entries if not entry.group]
        groups = sorted(
            {entry.group for entry in entries if entry.group}, key=str.lower
        )
        if groups and items:
            items.append(separator())
        for group in groups:
            members = [item(entry) for entry in entries if entry.group == group]
            items.append(
                MenuItem(f"&{group}", submenu=Menu(group, members), status=group)
            )
        if not items:  # greyed out, saying how to get some
            items = [
                MenuItem(
                    "(None installed)",
                    status="dasha install-app installs an application",
                )
            ]
        submenu = self._applications_item.submenu
        assert submenu is not None
        submenu.items = items
        menu = self.system_menu.items
        if self._applications_item not in menu:
            about = next(i for i, entry in enumerate(menu) if entry.label == "&About")
            menu[about + 1 : about + 1] = [self._applications_item, self._run_item]

    def unregister(self, app_id: str) -> None:
        """Remove an application from the Applications menu.

        :param app_id: The application id.
        """
        self.registry.pop(app_id, None)
        self._build_applications_menu()

    def run_dialog(self) -> None:
        """Show the Run dialog."""
        if not self.can_show_dialogs:
            return
        dialog = RunDialog()
        if self.execute(dialog) == "ok" and dialog.entry is not None:
            self.start(dialog.entry)

    @property
    def screen_size(self) -> tuple[int, int]:
        """The size of the screen, as (columns, lines)."""
        return self._size

    def start(self, application: "type[Application] | AppEntry") -> None:
        """Start an application, as the Applications menu does.

        :param application: The class or entry.
        """
        entry = application if isinstance(application, AppEntry) else None
        if entry is None:
            assert isinstance(application, type)
            entry = AppEntry.of(application)
        in_process = entry.application is not None and entry.venv is None
        if in_process and not self.use_processes:
            assert entry.application is not None
            self.launch(entry.application)
            return
        # pylint: disable-next=import-outside-toplevel
        from dasha.hosting import AppServer

        if self.server is None:
            self.server = AppServer(self)
        running = self.server.running(entry.target)
        if entry.single_instance and running is not None:
            if not running.is_loading:  # it comes forward itself once it has
                self.switch_to(running.application)
            return
        # Run... names an application after its script or class; an
        # installed one's name is the manifest's, a built-in one's its own.
        guessed = entry.manifest is None and entry.application is None
        self.server.start(entry.target, entry.name, entry.venv, guessed_name=guessed)

    def add_application(self, application: Application) -> None:
        """Record a running application and make it active.

        :param application: The application.
        """
        application.manager = self
        application.is_running = True
        if application not in self._applications:
            self._applications.append(application)
        self._active_app = application

    @property
    def active_application(self) -> Application | None:
        """The application whose menus are shown."""
        return self._active_app

    def switch_to(self, application: Application) -> None:
        """Make an application active.

        :param application: The application.
        """
        self._active_app = application
        window = application.active_window
        if window is not None:
            self.bring_to_front(window)
        dialogs = [
            window
            for window in self._windows
            if window.modal and self.owner_of(window) is application
        ]
        if dialogs:
            self.bring_to_front(dialogs[-1])

    def show_window(self, window: Window) -> None:
        """Bring a window to the front, restoring it.

        :param window: The window.
        """
        if window in self._minimised:
            self.restore(window)
        elif window in self._windows:
            self.bring_to_front(window)

    def launch(self, application: "AppT | type[AppT]") -> AppT:
        """Start an application here and return it.

        :param application: An instance or class.
        """
        if isinstance(application, type):
            if application.single_instance:
                for running in self._applications:
                    if isinstance(running, application):
                        self.switch_to(running)
                        return running
            application = application()
        self.add_application(application)
        application.start()
        if application.is_running:
            self._active_app = application
        return application

    def stand_alone(self, name: str) -> None:
        """Run as a stand-alone application's desktop.

        :param name: The application's name.
        """
        self.no_application = ""
        self.program_name = name
        self.error_log_folder = logs.app_log_folder(name)
        self.error_log_name = logs.log_name(name)
        self.quit_when_empty = True
        self.show_system_menu = False
        self.exit_title = name
        self.exit_message = f"Close {name}?"
        self.exit_button = "&Close"
        self.exit_status = f"Press Close to close {name}"

    def application_ended(self, application: Application) -> None:
        """Called when an application quits.

        :param application: The application.
        """
        if application in self._applications:
            self._applications.remove(application)
        self._window_menus.pop(application, None)
        if application is self._active_app:
            front = [w.application for w in self._windows if w.application]
            if front:
                self._active_app = front[-1]
            else:
                self._active_app = (
                    self._applications[-1] if self._applications else None
                )
        if self.quit_when_empty and not self._applications and not self._is_loading:
            self.quit()

    # Z-order

    @property
    def windows(self) -> tuple[Window, ...]:
        """All the windows on screen, from back to front."""
        return tuple(self._windows)

    @property
    def active_window(self) -> Window | None:
        """The front window, if the active application's."""
        if not self._windows:
            return None
        front = self._windows[-1]
        application = self.owner_of(front)
        if application is not None and application is not self._active_app:
            return None
        return front

    @staticmethod
    def owner_of(window: Window) -> Application | None:
        """The application a window is for.

        :param window: The window.
        """
        return window.application or window.owner

    def _front_changed(self) -> None:
        """The front window's application becomes the active one."""
        if self._windows and (application := self.owner_of(self._windows[-1])):
            self._active_app = application

    # Dialogs that wait their turn

    def must_wait(self, window: Window) -> bool:
        """Whether a dialog must wait behind the front one.

        :param window: The dialog.
        """
        if not window.modal or not self._windows:
            return False
        front = self._windows[-1]
        return (
            front is not window
            and front.modal
            and self.owner_of(front) is not self.owner_of(window)
        )

    def add_waiting(self, window: Window) -> None:
        """Add a dialog behind the front one.

        :param window: The dialog.
        """
        self.add_behind(window)

    def add_behind(self, window: Window) -> None:
        """Add a window behind the front one.

        :param window: The window.
        """
        if window in self._windows or window in self._minimised:
            raise ValueError("Window is already on this desktop")
        if window.maximised:
            window.maximise(self.workspace)
        if self._size_known:
            self.keep_reachable(window)
        self._windows.insert(max(0, len(self._windows) - 1), window)
        window.manager = self

    @property
    def waiting(self) -> list[Window]:
        """Dialogs waiting their turn."""
        if not self._windows:
            return []
        front = self._windows[-1]
        return [
            window
            for window in self._windows[:-1]
            if window.modal and self.owner_of(window) is not self.owner_of(front)
        ]

    def _next_of(self, application: Application | None) -> None:
        """Bring the application's next window forward.

        :param application: The application, if any.
        """
        if application is not None and application is self._active_app:
            window = application.active_window
            if window is not None:
                self.bring_to_front(window)

    @property
    def minimised(self) -> tuple[Window, ...]:
        """Minimised windows, in order minimised."""
        return tuple(self._minimised)

    def add(self, window: Window) -> None:
        """Add a window in front.

        :param window: The window.
        """
        if window in self._windows or window in self._minimised:
            raise ValueError("Window is already on this desktop")
        if window.maximised:
            window.maximise(self.workspace)
        if self._size_known:
            self.keep_reachable(window)
        self._windows.append(window)
        window.manager = self
        self._front_changed()

    def remove(self, window: Window) -> None:
        """Take a window off the desktop.

        :param window: The window.
        """
        if window in self._minimised:
            self._minimised.remove(window)
            self._update_restore_items()
        else:
            self._windows.remove(window)
        window.manager = None
        if self._drag is not None and self._drag.window is window:
            self._end_drag()
        if self.adjusting is window:
            self.finish_adjusting()
        application = window.application
        if application is not None and application.is_running:
            application.window_closed(window)
            self._next_of(application)
        elif application is None:
            # A dialog answered: what is now in front (perhaps a dialog that
            # was waiting its turn) has the keyboard, and its application.
            self._front_changed()

    # Maximising, minimising and restoring

    def maximise(self, window: Window) -> None:
        """Maximise a window.

        :param window: The window.
        """
        animation = self._start_animation(window)
        minimised = window in self._minimised
        if minimised:
            self.restore(window)
        window.maximise(self.workspace)
        self.bring_to_front(window)
        if animation is not None:
            start = self._status_middle if minimised else None
            self._animation = animation.to_window(start)

    def minimise(self, window: Window) -> None:
        """Minimise a window.

        :param window: The window.
        """
        if window in self._minimised:
            return
        lone = self._windows == [window] and window.application is None
        if lone and not self.show_system_menu:
            return
        animation = self._start_animation(window)
        if animation is not None:
            animation.end, animation.showing = self._status_middle, False
            self._animation = animation
        self._windows.remove(window)
        self._minimised.append(window)
        if self._drag is not None and self._drag.window is window:
            self._end_drag()
        if self.adjusting is window:
            self.finish_adjusting()
        self._update_restore_items()
        self._next_of(window.application)

    def restore(self, window: Window) -> None:
        """Undo minimising or maximising.

        :param window: The window.
        """
        changes = window in self._minimised or window.maximised
        animation = self._start_animation(window) if changes else None
        if window in self._minimised:
            self._minimised.remove(window)
            self._windows.append(window)
            if window.maximised:
                window.maximise(self.workspace)  # the screen may have changed
            self._update_restore_items()
            self._front_changed()
            if animation is not None:
                self._animation = animation.to_window(self._status_middle)
        elif window.maximised:
            window.unmaximise()
            self.bring_to_front(window)
            if animation is not None:
                self._animation = animation.to_window()

    def toggle_maximise(self, window: Window) -> None:
        """Maximise or restore a window.

        :param window: The window.
        """
        if window.maximised:
            self.restore(window)
        else:
            self.maximise(window)

    def _update_restore_items(self) -> None:
        """List unowned minimised windows in the system menu."""
        items = self.system_menu.items
        for item in self._restore_items:
            if item in items:
                items.remove(item)
        self._restore_items = []
        loose = [window for window in self._minimised if window.application is None]
        for number, window in enumerate(loose, start=1):
            title = window.title.replace("&", "&&")  # not a mnemonic marker
            self._restore_items.append(
                _RestoreItem(
                    f"&{number} {title}" if number < 10 else title,
                    partial(self.restore, window),
                    status=f'Restores the minimised window "{window.title}"',
                )
            )
        if self._restore_items:
            self._restore_items.append(_RestoreItem("", is_separator=True))
        items[0:0] = self._restore_items

    def bring_to_front(self, window: Window) -> None:
        """Bring a window to the front.

        :param window: The window.
        """
        if window in self._minimised:
            self.restore(window)
            return
        if window not in self._windows:
            return
        self._windows.remove(window)
        self._windows.append(window)
        self._front_changed()

    def send_to_back(self, window: Window) -> None:
        """Send a window to the back.

        :param window: The window.
        """
        if window not in self._windows:
            return
        self._windows.remove(window)
        self._windows.insert(0, window)
        self._front_changed()

    def activate_next(self) -> None:
        """Activate the next window."""
        if len(self._windows) > 1:
            self.send_to_back(self._windows[-1])

    def activate_previous(self) -> None:
        """Undo ``activate_next``: bring the back window to the front."""
        if len(self._windows) > 1:
            self.bring_to_front(self._windows[0])

    def window_at(self, row: int, column: int) -> Window | None:
        """The frontmost window at a position, if any.

        :param row: Screen row.
        :param column: Screen column.
        """
        for window in reversed(self._windows):
            if window.rect.contains(row, column):
                return window
        return None

    # Menus and screen layout

    def bar_menus(self) -> list[Menu]:
        """The menus on the bar."""
        system = [self.system_menu] if self.show_system_menu else []
        if self.show_system_menu:
            self._list_applications()
            self._label_animations()
        front = self._windows[-1] if self._windows else None
        if (
            front is not None
            and front.application is None
            and (front.menus or self._active_app is None)
        ):
            own = list(front.menus)
            if not self.show_system_menu:
                for menu in own:
                    if menu.lists_minimised:
                        self._list_minimised(menu)
            return [*system, *own]
        application = self._active_app
        if application is None:
            return system
        window_menu_ = self._window_menus.get(application)
        if window_menu_ is None:
            window_menu_ = self._window_menus[application] = Menu("&Window")
        fill_application_window_menu(self, application, window_menu_)
        menus = application.menus
        return [
            *system,
            *(menu for menu in menus if not menu.after_window),
            window_menu_,
            *(menu for menu in menus if menu.after_window),
        ]

    no_application: str = "Dasha Desktop"
    """Status bar name with no active application."""

    def application_label(self, application: Application) -> str:
        """An application's displayed name.

        :param application: The application.
        """
        same = [app for app in self._applications if app.name == application.name]
        number = same.index(application) + 1 if application in same else 1
        return application.name + (f" ({number})" if number > 1 else "")

    @property
    def status_owner(self) -> str:
        """Names shown on the status bar's left."""
        application = self._active_app
        label = (
            self.application_label(application) if application else self.no_application
        )
        names: list[str] = []
        for window in self.waiting:
            owner = self.owner_of(window)
            name = self.application_label(owner) if owner else self.no_application
            if name and name not in names:
                names.append(name)
        if names:
            waiting = f"{', '.join(names)} waiting"
            label = f"{label} {self.status_bar.divider} {waiting}" if label else waiting
        return label

    def inert_menus(self) -> list[int]:
        """Bar positions of menus that cannot open."""
        front = self._windows[-1] if self._windows else None
        if front is None or front.application is not None or front.menus:
            return []
        if self._active_app is None:
            return []
        first = 1 if self.show_system_menu else 0
        return list(range(first, len(self.bar_menus())))

    @property
    def _is_loading(self) -> bool:
        """Whether an application is still loading."""
        return self.server is not None and self.server.is_loading

    def _sync_menu_bar(self) -> None:
        """Give the menu bar the menus to show, and which are inert."""
        self.menu_bar.set_menus(self.bar_menus(), self.inert_menus())

    def _list_applications(self) -> None:
        """List running applications in the system menu."""
        items = self.system_menu.items
        items[:] = [item for item in items if not isinstance(item, _AppItem)]
        listed: list[MenuItem] = []
        for number, application in enumerate(self._applications, start=1):
            name = self.application_label(application)
            mark = "\N{SQUARE ROOT} " if application is self._active_app else "  "
            shown = name.replace("&", "&&")
            listed.append(
                _AppItem(
                    f"{mark}&{number} {shown}" if number < 10 else f"{mark}{shown}",
                    partial(self.switch_to, application),
                    status=f"Switches to {name}",
                )
            )
        if listed:
            listed.append(_AppItem("", is_separator=True))
        items[0:0] = listed

    def _list_minimised(self, menu: Menu) -> None:
        """List minimised windows in a Window menu.

        :param menu: The Window menu.
        """
        kept = [item for item in menu.items if not isinstance(item, _RestoreItem)]
        windows = [item for item in self._restore_items if not item.is_separator]
        if windows:
            kept += [_RestoreItem("", is_separator=True), *windows]
        menu.items = kept

    @property
    def workspace(self) -> Rect:
        """The screen area between the menu bar and the status bar."""
        columns, lines = self._size
        return Rect(1, 0, max(0, lines - 2), columns)

    def status(self) -> str:
        """The status bar text."""
        if self._adjust is not None:
            return self._adjust_help()
        self._sync_menu_bar()
        if self.menu_bar.is_open:
            return status_text(self.menu_bar.highlighted)
        active = self.active_window
        if active is not None:
            focused = status_text(active.focused)
            if focused:
                return focused
        return status_text(active)

    def key_hints(self) -> list[tuple[str, str]]:
        """Keys listed on the status bar's right."""
        if self.menu_bar.is_open or self._adjust is not None:
            return []
        hints = []
        menu_key = self.shortcuts.hint("open_menu")
        if menu_key and self._menu_bar_opens():
            hints.append((menu_key, "Menu"))
        active = self.active_window
        if active is not None and active.focused is not None:
            hints += active.focused.key_help(self.shortcuts)
        return hints

    def _menu_bar_opens(self) -> bool:
        """Whether the ``open_menu`` key would open the bar."""
        if any(window.modal for window in self._windows):
            return False
        inert = self.inert_menus()
        return any(index not in inert for index in range(len(self.bar_menus())))

    # Drawing and input

    def looks_active(self, window: Window) -> bool:
        """Whether a window is drawn active.

        :param window: The window.
        """
        return drawn_active(window, self.active_window, self._windows)

    def compose(self, canvas: Canvas) -> None:
        """Paint the desktop, windows and bars.

        :param canvas: Canvas to draw on.
        """
        self._sync_menu_bar()
        self.desktop.paint(canvas)
        active = self.active_window
        moving = self._moving
        for window in self._windows:
            if moving is not None and window is moving[0].window:
                continue  # drawn part-way, in front, below
            if window is active:
                # Only the active window shows the cursor: not the window
                # under a context menu, which still looks active.
                canvas.cursor = None
            window.paint(canvas, self.looks_active(window))
        if moving is not None:
            moving[0].paint(canvas, moving[1])
            canvas.cursor = None
        # A focused text box shows the cursor, unless a menu or bar is over it.
        cursor = canvas.cursor
        if cursor is not None and (
            self.menu_bar.is_open or cursor[0] in (0, canvas.height - 1)
        ):
            canvas.cursor = None
        self.menu_bar.paint_shadow(canvas, self._dropping)
        self.status_bar.paint(
            canvas, self.status(), self.key_hints(), self.status_owner
        )
        if self.menu_bar.menus or not self._is_loading:
            self.menu_bar.paint(canvas, self._dropping)
        else:
            self.desktop.paint_row(canvas, 0)
        self._paint_mouse(canvas)

    def handle_event(self, event: Event) -> None:
        """Dispatch one input event.

        :param event: The event.
        """
        self._sync_menu_bar()
        active = self.active_window
        # A dialog of an application in its own process that takes every key
        # (as its own process's execute would give it).
        held = (
            isinstance(event, str)
            and not self.menu_bar.is_open
            and active is not None
            and active.modal
            and getattr(active, "takes_every_key", False) is True
        )
        if not held and self._notice(event):
            return
        if isinstance(event, MouseEvent):
            event = self._count_clicks(event)
        if self._adjust is not None and self._adjust_event(event):
            return
        if isinstance(event, KeyReleaseEvent):
            if not self.menu_bar.is_open and (active := self.active_window) is not None:
                active.handle_key_release(event.key)
        elif isinstance(event, PasteEvent):
            if not self.menu_bar.is_open:
                self.handle_paste(event.text)
        elif isinstance(event, MouseEvent):
            self._route_mouse(event)
        elif held:
            assert active is not None
            active.handle_key(event, self.shortcuts)
        elif not self.menu_bar.handle_key(event):
            active = self.active_window
            if active is None or not active.handle_key(event, self.shortcuts):
                self.handle_key(event)

    def _route_mouse(self, event: MouseEvent) -> None:
        """Dispatch a mouse event.

        :param event: The mouse event.
        """
        if self.server is not None and self.server.outside_press(event):
            pass  # it closed a drop-down list of an application's
        elif (key := self.hint_key_at(event)) is not None:
            self.handle_event(key)  # as though it were pressed
        elif self._is_system_menu_double_click(event):
            # As with a window's control menu: double-clicking the
            # system menu asks to leave, like choosing its Exit item.
            self.menu_bar.close()
            self.request_exit()
        elif not self.menu_bar.handle_mouse(event, self._size[0]):
            self.handle_mouse(event)

    def hint_key_at(self, event: MouseEvent) -> str | None:
        """The key a status bar hint click stands for, if any.

        :param event: The mouse event.
        """
        if event.action != "press" or event.button != "left":
            return None
        columns, lines = self._size
        if event.row != lines - 1:
            return None
        hint = self.status_bar.hint_at(
            event.column, columns, self.key_hints(), self.status_owner
        )
        return None if hint is None else key_from_pretty(hint[0])

    def _is_system_menu_double_click(self, event: MouseEvent) -> bool:
        """Whether a press double-clicks the system menu.

        :param event: The mouse event.
        """
        if event.action != "press" or event.button != "left" or event.clicks < 2:
            return False
        if not self.show_system_menu:
            return False
        spans = self.menu_bar.title_spans
        return bool(spans) and spans[0].contains(event.row, event.column)

    def _count_clicks(self, event: MouseEvent) -> MouseEvent:
        """Count clicks of a multi-click press.

        :param event: The mouse event.
        """
        if event.action != "press" or event.button != "left":
            return event
        now = time.monotonic()
        clicks = 1
        if self._last_press is not None:
            when, row, column, count = self._last_press
            same_cell = (row, column) == (event.row, event.column)
            # Strictly within: Windows' clock moves in steps of about 15 ms,
            # so two presses can share a time, and 0 must mean never.
            if same_cell and now - when < self.double_click_time:
                clicks = count + 1
        self._last_press = (now, event.row, event.column, clicks)
        return replace(event, clicks=clicks) if clicks > 1 else event

    @property
    def dragging(self) -> Window | None:
        """The window being moved or resized with the mouse, if any."""
        return self._drag.window if self._drag is not None else None

    @property
    def is_resizing(self) -> bool:
        """Whether the current mouse drag, if any, is resizing a window."""
        return self._drag is not None and self._drag.kind == "resize"

    def handle_paste(self, text: str) -> None:
        """Paste text into the focused widget.

        :param text: The pasted text.
        """
        active = self.active_window
        if active is not None:
            active.handle_paste(text)

    def handle_mouse(self, event: MouseEvent) -> None:
        """Handle mouse activity.

        :param event: The mouse event.
        """
        if event.action == "scroll":
            self._mouse_wheel(event)
            return
        if event.button == "right":
            if event.action == "press":
                self._right_press(event)
            return
        if event.button != "left":
            return
        if event.action == "press":
            self._mouse_press(event)
        elif event.action == "drag" and self._drag is not None:
            self._mouse_drag(self._drag, event)
        elif self._drag is not None:
            if event.action == "release":
                self._end_drag()
        elif (active := self.active_window) is not None:
            active.handle_mouse(event)  # a drag or release for a widget

    def _mouse_drag(self, drag: _Drag, event: MouseEvent) -> None:
        """Continue a mouse drag.

        :param drag: The drag in progress.
        :param event: The mouse event.
        """
        window = drag.window
        if drag.kind == "repeat":
            drag.repeat.move(event.row, event.column)
            return
        if drag.kind.endswith("_thumb"):
            self._drag_thumb(window, event)
            return
        if drag.kind == "resize":
            window.release()  # maximised: not any more, from this size
            rect = window.rect
            window.resize(
                event.column + drag.grab_offset - rect.column + 1,
                event.row - rect.row + 1,
            )
            return
        if window.maximised:
            self._unmaximise_for_drag(window, event)
        # The title bar may not go under the menu or status bar, or it
        # could not be grabbed again.
        workspace = self.workspace
        row = min(max(event.row, workspace.row), workspace.bottom - 1)
        window.move_to(row, event.column - drag.grab_offset)

    def _mouse_wheel(self, event: MouseEvent) -> None:
        """Scroll the window under the pointer.

        :param event: The mouse event.
        """
        if not self.workspace.contains(event.row, event.column):
            return
        window = self.window_at(event.row, event.column)
        if window is None or window.handle_mouse(event):
            return  # nothing there, or a widget (a list box, say) scrolled
        notch = 3
        sideways = event.button in ("left", "right") or event.shift
        amount = -notch if event.button in ("up", "left") else notch
        if sideways:
            window.scroll_by(0, amount)
        else:
            window.scroll_by(amount, 0)

    def _drag_thumb(self, window: Window, event: MouseEvent) -> None:
        """Follow a dragged scroll bar thumb.

        :param window: The window.
        :param event: The mouse event.
        """
        assert self._drag is not None
        vertical, horizontal = window.scroll_bars
        if self._drag.kind == "vertical_thumb" and vertical is not None:
            window.scroll_to(
                vertical.value_at(event.row, event.column), window.scroll_column
            )
        elif self._drag.kind == "horizontal_thumb" and horizontal is not None:
            window.scroll_to(
                window.scroll_row, horizontal.value_at(event.row, event.column)
            )

    def _right_press(self, event: MouseEvent) -> None:
        """Raise the window and pop up its context menu.

        :param event: The mouse event.
        """
        if not self.workspace.contains(event.row, event.column):
            return
        window = self.window_at(event.row, event.column)
        if window is None:
            return
        if window is not self.active_window:
            self.bring_to_front(window)
        window.handle_mouse(event)

    def _mouse_press(self, event: MouseEvent) -> None:
        """Handle a left-button press.

        :param event: The mouse event.
        """
        if not self.workspace.contains(event.row, event.column):
            return  # a click on a bar never reaches a window beneath it
        window = self.window_at(event.row, event.column)
        if window is None:
            return
        # Title bar buttons are only drawn, and only work, on the active
        # window; a click on an inactive window just brings it forward.
        button = window.button_at(event.row, event.column)
        if window is self.active_window and button is not None:
            self.press_button(window, button)
            return
        if window is not self.active_window:
            self.bring_to_front(window)
        on_bar = window.scroll_bar_at(event.row, event.column)
        if on_bar is not None:
            scroll_bar, part = on_bar
            if part == "thumb":
                kind = "vertical_thumb" if scroll_bar.vertical else "horizontal_thumb"
                self._drag = _Drag(window, kind)
            else:
                window.press_scroll_bar(scroll_bar, part)
                # Held down, the click repeats (see run_timers).
                drag = _Drag(window, "repeat", vertical=scroll_bar.vertical)
                drag.repeat.start(part, event.row, event.column, time.monotonic())
                self._drag = drag
            return
        grip = window.resize_grip_rect
        if grip is not None and grip.contains(event.row, event.column):
            # How far left of the corner the grip was grabbed, so the
            # corner does not jump to the pointer.
            offset = window.rect.right - 1 - event.column
            self._start_drag(_Drag(window, "resize", grab_offset=offset))
        elif (
            event.clicks >= 2
            and window.maximisable
            and window.title_bar.contains(event.row, event.column)
        ):
            # A double-click on the title bar maximises, or restores.
            self.toggle_maximise(window)
        elif window.title_bar.contains(event.row, event.column):
            # Maximised too: dragging it restores it (_unmaximise_for_drag).
            offset = event.column - window.rect.column
            self._start_drag(_Drag(window, "move", grab_offset=offset))
        else:
            window.handle_mouse(event)  # perhaps a widget

    def _unmaximise_for_drag(self, window: Window, event: MouseEvent) -> None:
        """Restore a maximised window being dragged.

        :param window: The window.
        :param event: The mouse event.
        """
        drag = self._drag
        assert drag is not None
        wide = window.rect.width
        self.restore(window)
        self._animation = None  # it follows the pointer instead
        width = window.rect.width
        offset = round(drag.grab_offset * width / max(1, wide))
        drag.grab_offset = min(max(offset, 1), max(1, width - 2))
        window.move_to(window.rect.row, event.column - drag.grab_offset)

    def _start_drag(self, drag: _Drag) -> None:
        """Start a mouse move or resize.

        :param drag: The drag.
        """
        self._drag = drag
        drag.window.adjusting = True

    def _end_drag(self) -> None:
        """End a mouse drag."""
        drag = self._drag
        self._drag = None
        if drag is not None and drag.kind in ("move", "resize"):
            drag.window.adjusting = self.adjusting is drag.window

    def press_button(self, window: Window, button: str) -> None:
        """Do a title bar button's action.

        :param window: The window.
        :param button: The button.
        """
        if button == "close":
            self.close(window)
        elif button == "maximise":
            self.maximise(window)
        elif button == "restore":
            self.restore(window)
        elif button == "minimise":
            self.minimise(window)

    def handle_resize(self, columns: int, lines: int) -> None:
        """Handle a new screen size.

        :param columns: Screen width.
        :param lines: Screen height.
        """
        self.menu_bar.lines = lines
        self._size = (columns, lines)
        self._size_known = True
        workspace = self.workspace
        for window in self._windows:
            if window.maximised:
                window.maximise(workspace)  # keep filling the work area
                continue
            rect = window.rect
            if not rect.intersect(workspace).is_empty:
                if rect.row < workspace.row:
                    window.move_to(workspace.row, rect.column)
                continue
            showing = min(self.rescue_margin, rect.width, columns)
            row = min(max(rect.row, workspace.row), workspace.bottom - 1)
            column = rect.column
            if column >= columns:
                column = columns - showing
            elif column + rect.width <= 0:
                column = showing - rect.width
            window.move_to(row, column)

    def handle_key(self, key: str) -> None:
        """Handle a key press.

        :param key: The key.
        """
        if self.shortcuts.matches("exit", key):
            self.request_exit()
        elif self.shortcuts.matches("help", key):
            self.press_help()
        elif self.shortcuts.matches("next_window", key):
            self.activate_next()
        elif self.shortcuts.matches("previous_window", key):
            self.activate_previous()
        elif (window := self.active_window) is not None:
            if self.shortcuts.matches("maximise_window", key) and window.maximisable:
                self.toggle_maximise(window)
            elif self.shortcuts.matches("minimise_window", key) and (
                window.minimisable
            ):
                self.minimise(window)
            elif self.shortcuts.matches("close_window", key) and window.closable:
                self.close(window)
            elif self.shortcuts.matches("move_window", key):
                self.start_moving(window)
            elif self.shortcuts.matches("resize_window", key):
                self.start_resizing(window)

    # Moving and resizing from the keyboard

    @property
    def adjusting(self) -> Window | None:
        """The window being moved or resized from the keyboard, if any."""
        return self._adjust.window if self._adjust is not None else None

    def start_moving(self, window: Window | None = None) -> None:
        """Move a window with the keyboard.

        :param window: The window, or ``None`` for the active one.
        """
        self._start_adjusting(window, "move")

    def start_resizing(self, window: Window | None = None) -> None:
        """Resize a window with the keyboard.

        :param window: The window, or ``None`` for the active one.
        """
        self._start_adjusting(window, "resize")

    def _start_adjusting(self, window: Window | None, kind: str) -> None:
        window = window if window is not None else self.active_window
        if window is None or window not in self._windows:
            return
        if kind == "resize" and not window.resizable:
            return
        self.finish_adjusting()
        # A maximised one stays so until the first step (_adjust_step).
        maximised_from = window.restored_rect if window.maximised else None
        self.bring_to_front(window)
        self.menu_bar.close()
        self._adjust = _Adjust(window, kind, window.rect, maximised_from)
        window.adjusting = True

    def finish_adjusting(self, cancel: bool = False) -> None:
        """Finish moving or resizing from the keyboard.

        :param cancel: Whether to put the window back.
        """
        adjust = self._adjust
        if adjust is None:
            return
        self._adjust = None
        window = adjust.window
        window.adjusting = False
        if cancel and adjust.maximised_from is not None:
            window.release()
            window.rect = adjust.maximised_from  # to go back to, restored
            window.maximise(self.workspace)
        elif cancel:
            window.rect = adjust.original

    def _adjust_event(self, event: Event) -> bool:
        """Handle input while adjusting; return whether used.

        :param event: The event.
        """
        adjust = self._adjust
        assert adjust is not None
        if isinstance(event, MouseEvent):
            if event.action == "press":
                self.finish_adjusting()
            return False
        if isinstance(event, (PasteEvent, KeyReleaseEvent)):
            return True
        shortcuts, window = self.shortcuts, adjust.window
        if shortcuts.matches("adjust_accept", event):
            self.finish_adjusting()
        elif shortcuts.matches("adjust_cancel", event):
            self.finish_adjusting(cancel=True)
        elif shortcuts.matches("adjust_switch", event):
            if window.resizable:
                adjust.kind = "resize" if adjust.kind == "move" else "move"
        else:
            steps = {
                "adjust_left": (0, -1),
                "adjust_right": (0, 1),
                "adjust_up": (-1, 0),
                "adjust_down": (1, 0),
            }
            for action, (rows, columns) in steps.items():
                if shortcuts.matches(action, event):
                    self._adjust_step(window, adjust.kind, rows, columns)
        return True

    def _adjust_step(self, window: Window, kind: str, rows: int, columns: int) -> None:
        if window.maximised:
            # Moved: back to its size before; resized: on from this size.
            if kind == "move":
                window.unmaximise()
            else:
                window.release()
        rect = window.rect
        if kind == "resize":
            window.resize(rect.width + columns, rect.height + rows)
        else:
            window.move_to(rect.row + rows, rect.column + columns)
        # It stops at the edge, rather than going where it cannot be found.
        self.keep_reachable(window)

    def keep_reachable(self, window: Window) -> None:
        """Keep a window reachable on screen.

        :param window: The window.
        """
        if window.maximised:
            return
        rect = window.rect
        workspace = self.workspace
        columns = self._size[0]
        showing = min(self.rescue_margin, rect.width, columns)
        row = min(
            max(rect.row, workspace.row), max(workspace.row, workspace.bottom - 1)
        )
        column = min(max(rect.column, showing - rect.width), columns - showing)
        if (row, column) != (rect.row, rect.column):
            window.move_to(row, column)

    def _adjust_help(self) -> str:
        """The status bar's help while moving or resizing."""
        adjust = self._adjust
        assert adjust is not None
        hint = self.shortcuts.hint
        doing = "Moving" if adjust.kind == "move" else "Resizing"
        parts = [f"{doing}: arrows {adjust.kind}"]
        if adjust.window.resizable and hint("adjust_switch"):
            other = "resize" if adjust.kind == "move" else "move"
            parts.append(f"{hint('adjust_switch')} to {other}")
        if hint("adjust_accept"):
            parts.append(f"{hint('adjust_accept')} to finish")
        if hint("adjust_cancel"):
            parts.append(f"{hint('adjust_cancel')} to cancel")
        return ", ".join(parts)

    @property
    def is_running(self) -> bool:
        """Whether ``run`` is still handling input."""
        return self._running

    @property
    def can_show_dialogs(self) -> bool:
        """Whether dialogs can be shown now."""
        return self._terminal is not None

    def quit(self) -> None:
        """Stop ``run`` after the current input has been handled."""
        self._running = False

    def call_when_running(self, callback: Callable[[], object]) -> None:
        """Call something once the desktop is running.

        :param callback: Called with no arguments.
        """
        if self._when_running is None:
            callback()
        else:
            self._when_running.append(callback)

    def call_from_thread(self, callback: Callable[[], object]) -> None:
        """Call something on the desktop's thread.

        :param callback: Called with no arguments.
        """
        self._from_threads.append(callback)
        self.wake()

    def wake(self) -> None:
        """Interrupt the input wait; thread-safe."""
        terminal = self._terminal
        wake = getattr(terminal, "wake", None) if terminal is not None else None
        if wake is not None:
            wake()

    def _call_from_threads(self) -> None:
        """Run queued ``call_from_thread`` callbacks."""
        for _ in range(len(self._from_threads)):
            if not self.is_running:
                return
            self._from_threads.popleft()()

    def _now_running(self) -> None:
        """Call what ``call_when_running`` held back: the loop has started."""
        waiting = self._when_running or []
        self._when_running = None
        for callback in waiting:
            if not self.is_running:
                break
            callback()

    def close(self, window: Window) -> None:
        """Close a window, if it agrees.

        :param window: The window.
        """
        if window.request_close():
            self.remove(window)

    # The command prompt (see dasha.shell)

    def command_prompt(self) -> None:
        """Hand the terminal to the user's shell until exit."""
        terminal = self._terminal
        if terminal is None or not hasattr(terminal, "suspended"):
            return
        self.menu_bar.close()
        failure: OSError | None = None
        with terminal.suspended():
            try:
                shell.run_shell(name=self.program_name)
            except OSError as error:
                failure = error
        self._on_screen = None  # draw every cell again, at the size now
        self._mouse_at = None  # until it is next reported, wherever it went
        if failure is not None:
            self.execute(
                information(
                    "Command prompt",
                    f"The command prompt could not be started:\n{failure}",
                    status="Press OK",
                )
            )

    def window_menu(self, window: Window) -> Menu:
        """A Window menu for a window.

        :param window: The window.
        """
        return window_menu(self, window)

    def about_box(self) -> None:
        """Show the About box."""
        if not self.can_show_dialogs:
            return
        dialog = information(
            self.about_title,
            self.about_message,
            status="Press OK to close",
            align="centre",
        )
        self.execute(dialog)

    pick_rows: int = 8
    """The most rows a drop-down list (``pick``) shows at once."""

    def place_popup(self, popup: Dialog, row: int, column: int) -> None:
        """Place a popup on screen.

        :param popup: The popup.
        :param row: Desired screen row.
        :param column: Desired screen column.
        """
        workspace, rect = self.workspace, popup.rect
        if row + rect.height > workspace.bottom:
            row = row - rect.height + 1
        row = max(workspace.row, min(row, workspace.bottom - rect.height))
        column = max(0, min(column, self._size[0] - rect.width))
        popup.move_to(row, column)

    def context_menu(self, menu: Menu, row: int, column: int) -> None:
        """Pop up a menu and run its choice.

        :param menu: The menu.
        :param row: Screen row.
        :param column: Screen column.
        """
        if not self.can_show_dialogs or not menu.items:
            return
        popup = MenuPopup(menu)
        self.place_popup(popup, row, column)
        if self.execute(popup) == "ok" and popup.chosen is not None:
            action = popup.chosen.action
            if action is not None:
                action()

    def pick(self, items: list[str], selected: int, below: Rect) -> int | None:
        """Drop down a list; return the chosen index, or ``None``.

        :param items: The items.
        :param selected: Index of the initial item.
        :param below: Screen rect to drop below.
        """
        if not self.can_show_dialogs or not items:
            return None
        rows = min(len(items), self.pick_rows)
        popup = ListPopup(items, selected, max(below.width, 6), rows)
        workspace, height = self.workspace, rows + 2
        row = below.bottom
        if row + height > workspace.bottom:
            row = max(workspace.row, below.row - height)
        column = max(0, min(below.column, self._size[0] - popup.rect.width))
        popup.move_to(row, column)
        return popup.chosen if self.execute(popup) == "ok" else None

    def suggest(self, box: AutoCompleteBox, items: list[str]) -> SuggestionPopup | None:
        """Show autocomplete suggestions; return the popup, or ``None``.

        :param box: The autocomplete box.
        :param items: The suggestions.
        """
        window = box.window
        if not self.can_show_dialogs or not items or window is None:
            return None
        at, workspace = window.screen_rect(box), self.workspace
        below = workspace.bottom - at.bottom - 1  # less the popup's frame
        above = at.row - workspace.row - 1
        wanted = min(len(items), box.rows)
        upwards = below < wanted and above > below
        rows = min(wanted, above if upwards else below)
        if rows < 1:
            return None
        popup = SuggestionPopup(box, items, rows, upwards)
        popup.move_to(at.row - 1 - (rows if upwards else 0), max(0, at.column - 1))
        self.execute(popup)
        return popup

    def request_exit(self) -> None:
        """Quit, after confirmation and applications agree."""
        if self.confirm_exit and self.can_show_dialogs:
            dialog = confirm(
                self.exit_title,
                self.exit_message,
                status=self.exit_status,
                ok_label=self.exit_button,
            )
            if self.execute(dialog) != "ok":
                return
        for application in list(self._applications):
            if not application.can_close():
                return  # it wants to stay (to save its work, say)
        if self.server is not None and self.server.is_busy:
            self.server.ask_to_close(self.quit)  # they answer in their own time
        else:
            self.quit()

    # Help

    def press_help(self) -> None:
        """Show the relevant help."""
        window = self.answering_dialog or self.active_window
        if isinstance(window, Popup):
            return
        owner = None if window is None else self.owner_of(window)
        application = owner or self.active_application
        if application is None or (
            window is not None and owner is None and application.is_remote
        ):
            self.show_desktop_help()
        else:
            application.show_help()

    def use_own_help(self) -> None:
        """Offer the desktop's own help."""
        self.help_folder = DESKTOP_PAGES
        # With no key of its own: the help key is the active application's
        # while there is one, and a menu item's shortcut would take it.
        item = MenuItem(
            "&Help", self.show_desktop_help, status="How to use Dasha Desktop"
        )
        menu = self.system_menu.items
        settings = next(
            i for i, item in enumerate(menu) if item.label == "S&ettings..."
        )
        menu.insert(settings, item)

    def show_desktop_help(self) -> None:
        """Show the desktop's help."""
        if self.help_folder is None:
            return
        book = HelpBook(self.help_folder)
        if book.has_topics():
            self._help_window = open_help(
                self,
                book,
                "Dasha Desktop Help",
                help_topic_of(self.answering_dialog),
                window=self._help_window,
                open_window=self.add,
            )

    # Dialogs

    @property
    def answering_dialog(self) -> Dialog | None:
        """The dialog waiting for an answer, if any."""
        for window in reversed(self._windows):
            if window.modal and isinstance(window, Dialog):
                return window
        return None

    def execute(self, dialog: Dialog) -> str | None:
        """Show a dialog and return its answer.

        :param dialog: The dialog.
        """
        if self._terminal is None:
            raise RuntimeError("execute() needs the presentation manager running")
        terminal = self._terminal
        dialog.result = None
        if dialog.centred:
            dialog.centre(self.workspace)
        if dialog not in self._windows:
            self.add(dialog)
        self.bring_to_front(dialog)
        self.menu_bar.close()
        dialog.modal = True
        try:
            while dialog.result is None and self.is_running:
                self._guard(partial(self._draw_frame, terminal), "drawing")
                events = self._wait_for_events(terminal)
                while events and dialog.result is None and self.is_running:
                    self._guard(
                        partial(self.handle_modal_event, dialog, events.pop(0)), None
                    )
        finally:
            dialog.modal = False
        if dialog in self._windows:
            self.remove(dialog)
        return dialog.result

    def handle_modal_event(  # pylint: disable=too-many-return-statements
        self, dialog: Dialog, event: Event
    ) -> None:
        """Handle input while a dialog waits.

        :param dialog: The dialog.
        :param event: The event.
        """
        if self._notice(event, dialog):
            return
        if isinstance(event, PasteEvent):
            dialog.handle_paste(event.text)
            return
        if isinstance(event, KeyReleaseEvent):
            dialog.handle_key_release(event.key)
            return
        if isinstance(event, MouseEvent):
            if (key := self.hint_key_at(event)) is not None:
                self.handle_modal_event(dialog, key)  # as though it were pressed
                return
            event = self._count_clicks(event)
            starts = event.action in ("press", "scroll")
            if starts and not dialog.rect.contains(event.row, event.column):
                if event.action == "press" and dialog.close_on_outside_click:
                    dialog.cancel()  # a drop-down list: a click away closes it
                return
            self.handle_mouse(event)
            return
        if dialog.handle_key(event, self.shortcuts):
            return
        if self.shortcuts.matches("help", event):
            self.press_help()
        elif self.shortcuts.matches("dialog_cancel", event):
            dialog.cancel()

    def _draw_frame(self, terminal: Terminal) -> None:
        """Update the screen.

        :param terminal: The terminal.
        """
        columns, lines = terminal.size()
        if hasattr(terminal, "take_cleared") and terminal.take_cleared():
            self._on_screen = None  # draw every cell again
        if (columns, lines) != self._screen_size:
            self._screen_size = (columns, lines)
            self.handle_resize(columns, lines)
            self._animation = None  # it was going between places now moved
        if self.server is not None:
            self.server.flush()
        self._animate(terminal)
        self._show(terminal)

    def _show(self, terminal: Terminal) -> None:
        """Draw the screen.

        :param terminal: The terminal.
        """
        columns, lines = terminal.size()
        canvas = Canvas(columns, lines)
        self.compose(canvas)
        terminal.write(canvas.render(self._on_screen))
        terminal.flush()
        self._on_screen = canvas

    def _widgets(self) -> Iterable[Widget]:
        for window in self._windows:
            yield from window.shown_widgets

    def _wait_for_events(self, terminal: Terminal) -> list[Event]:
        """Wait for input, timers or a wake; return any input.

        :param terminal: The terminal.
        """
        wakes = [wake for w in self._widgets() if (wake := w.wake_time()) is not None]
        if self._drag is not None and (wake := self._drag.repeat.wake_time()):
            wakes.append(wake)
        timeout = max(0.0, min(wakes) - time.monotonic()) if wakes else None
        if self._from_threads:
            timeout = 0.0  # left over from a pass that failed part-way
        server = self.server
        if server is not None and server.is_busy:
            # Applications' messages cannot wake the terminal read: look often.
            interval = server.poll_interval
            timeout = interval if timeout is None else min(timeout, interval)
        events = read_events(terminal, self._decoder, self.escape_timeout, timeout)
        self._guard(partial(self.run_timers, time.monotonic()), "timers")
        self._guard(self._call_from_threads, "callbacks")
        if server is not None:
            self._guard(server.poll, "messages")
        return events

    def run_timers(self, now: float) -> None:
        """Run due widget timers.

        :param now: The current ``time.monotonic``.
        """
        drag = self._drag
        if drag is not None and drag.kind == "repeat":
            vertical, horizontal = drag.window.scroll_bars
            scroll_bar = vertical if drag.vertical else horizontal
            repeat = drag.repeat
            part = None
            if scroll_bar is not None:
                part = scroll_bar.part_at(repeat.row, repeat.column)
            if repeat.due(now, part) and scroll_bar is not None and part:
                drag.window.press_scroll_bar(scroll_bar, part)
        for widget in list(self._widgets()):
            wake = widget.wake_time()
            if wake is not None and wake <= now:
                widget.on_timer(now)

    # Failing softly (see dasha.recovery)

    survive_errors: bool = False
    """Whether loop errors are logged and survived."""
    error_log_folder: Path = logs.LOG_FOLDER
    """Folder for the error log."""
    error_log_name: str = "desktop"
    """Start of the error log's file name."""
    recovery: Recovery | None = None
    """What has gone wrong, once something has: the log, and the count."""
    stopped_by_errors: bool = False
    """Whether the desktop gave up, failing too often to carry on."""
    _telling_of_error = False

    def _guard(self, step: Callable[[], object], kind: str | None) -> None:
        """Run one loop step, recovering from errors.

        :param step: The step.
        :param kind: Step kind, or ``None`` for input handling.
        """
        if not self.survive_errors:
            step()
            return
        if kind is None and self._telling_of_error:
            kind = "the error dialog"  # failing in turn: it counts
        try:
            step()
        except TerminalFailed:
            raise
        except Exception as error:  # pylint: disable=broad-exception-caught
            self._recover(error, kind)
            return
        if self.recovery is not None and kind is not None:
            self.recovery.succeeded(kind)

    def _recover(self, error: Exception, kind: str | None) -> None:
        """Log and report a failed step.

        :param error: The exception.
        :param kind: Step kind, or ``None`` for input handling.
        """
        if self.recovery is None:
            self.recovery = Recovery(
                self.error_log_folder,
                name=self.program_name,
                log_name=self.error_log_name,
            )
        recovery = self.recovery
        recovery.record(error, kind)
        for put_aside in (
            self.menu_bar.close,
            self._end_drag,
            partial(self.finish_adjusting, cancel=True),
        ):
            try:
                put_aside()
            except Exception:  # pylint: disable=broad-exception-caught
                pass  # broken too: the redraw below still happens
        self._animation = self._moving = None
        self._dropping = 1.0
        self._on_screen = None  # draw every cell again
        if recovery.has_too_many_failures:
            self.stopped_by_errors = True
            self.quit()
            return
        if self._telling_of_error or not self.is_running:
            return  # already telling the user (that dialog failing too)
        if not recovery.should_tell(by_user=kind is None):
            return  # told of one a moment ago; it is in the log
        self._telling_of_error = True
        try:
            self.execute(
                information("Something went wrong", recovery.message, status="Press OK")
            )
        finally:
            self._telling_of_error = False

    def run(self, terminal: Terminal) -> None:
        """Draw and handle input until ``quit``.

        :param terminal: The terminal.
        """
        self._running = True
        if self.survive_errors:
            terminal = cast(Terminal, GuardedTerminal(terminal))
        self._terminal = terminal
        # Buttons stay pushed in while Space is held, where releases arrive.
        Widget.key_releases = bool(getattr(terminal, "can_report_key_releases", False))
        self._decoder = InputDecoder()
        self._on_screen = None
        self._screen_size = None
        caught = _catch_ending_signals()
        try:
            self._guard(self._now_running, "starting")
            while self.is_running:
                self._guard(partial(self._draw_frame, terminal), "drawing")
                events = self._wait_for_events(terminal)
                # Input after the event that quits is ignored.
                while events and self.is_running:
                    self._guard(partial(self.handle_event, events.pop(0)), None)
                self._guard(self._report_crashes, "reports")
        finally:
            self._terminal = None
            self._when_running = []
            Widget.key_releases = False
            if self.server is not None:
                self.server.stop_all()
            for number, handler in caught.items():
                signal.signal(number, handler)

    def _report_crashes(self) -> None:
        """Report crashed, slow or unresponsive applications."""
        server = self.server
        while server is not None and server.notices and self.is_running:
            title, message = server.notices.pop(0)
            self.execute(information(title, message, status="Press OK"))
        if server is not None and self.is_running and (host := server.slow_to_load()):
            host.ask_about_loading()
        if server is not None and self.is_running and (host := server.stuck()):
            server.ask_about(host)
