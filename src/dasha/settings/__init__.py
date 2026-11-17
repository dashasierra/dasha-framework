"""Settings...: everything that the command line and the settings files
configure, changed from within Dasha Framework.

``SettingsDialog`` (Settings... in the system menu) has a page each for the
appearance (the theme, and every part of the screen's colours), the
keyboard shortcuts, the desktop (animations, how colours are drawn,
showing the mouse, and the applications that start with it) and the
installed applications. Changes show at once. OK keeps them, saving them to
the usual files (the colours file, the shortcuts file and
``settings.toml``, so the desktop starts with them next time); Apply does
the same without closing; and Cancel puts back everything as it was when
the dialog opened, or when Apply was last pressed.
Installing and uninstalling applications happen at once, and are not put
back.

The files and command-line options still work as before: these are the
same settings, kept in the same files.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from dasha import registry, theme
from dasha.canvas import Rect
from dasha.config import write_atomically
from dasha.dialog import Dialog, confirm, information
from dasha.settings.applications import ApplicationsPage, InstallDialog
from dasha.settings.appearance import AppearancePage
from dasha.settings.colours import ColourDialog
from dasha.settings.keys import KeyDialog, ShortcutsPage
from dasha.settings.lists import stay_open
from dasha.shortcuts import Shortcuts
from dasha.style import COLOUR_DEPTHS
from dasha.widgets import (
    Button,
    ComboBox,
    Label,
    ListBox,
    SpinBox,
    Switch,
    Tabs,
    Widget,
)
from dasha.widgets.tabs import TabPage

if TYPE_CHECKING:
    from dasha.manager import PresentationManager

__all__ = [
    "ApplicationsPage",
    "AppearancePage",
    "ColourDialog",
    "DesktopPage",
    "InstallDialog",
    "KeyDialog",
    "SettingsDialog",
    "ShortcutsPage",
]

DEPTH_NAMES = ["Automatic", "16 colours (CGA)", "256 colours", "24-bit colour"]
"""How the colour depths (``style.COLOUR_DEPTHS``, in the same order) are
offered."""


class DesktopPage:
    """Animations, how colours are drawn, showing the mouse, how long Escape
    waits for the rest of a key, and the applications that start with the
    desktop."""

    def __init__(self, dialog: "SettingsDialog", page: TabPage) -> None:
        self.dialog = dialog
        self.manager = manager = dialog.desktop_manager
        self._saved_animations = manager.animations
        try:
            self._saved_autostart = registry.read_autostart(manager.settings_path)
        except registry.ManifestError:
            self._saved_autostart = []
        self._saved_depth = manager.colour_depth
        self._saved_show_mouse = manager.show_mouse
        self._saved_wait = round(manager.escape_timeout * 1000)
        self.animations = page.add(
            Switch(
                "A&nimations: menus drop down, and windows zoom",
                0,
                1,
                on=manager.animations,
                on_change=lambda switch: manager.set_animations(
                    switch.on, remember=False
                ),
                name="animations",
            )
        )
        page.add(Label("Applications to start with the desktop", 2, 1))
        page.add(Label("(Space chooses each one)", 3, 1))
        self.ids: list[str] = []
        self.autostart = page.add(
            ListBox(
                [],
                4,
                1,
                40,
                10,
                multiple=True,
                on_choose=stay_open,
                name="autostart",
                status="Space chooses an application to start with the desktop",
            )
        )
        self.empty = page.add(Label("", 4, 43, name="no_applications"))
        page.add(Label("Colours are drawn in", 6, 43))
        self.depth = page.add(
            ComboBox(
                DEPTH_NAMES,
                7,
                43,
                26,
                on_change=lambda box: manager.set_colour_depth(self.chosen_depth),
                name="colour_depth",
                status="Automatic: in 24-bit colour, if the terminal seems able to",
            )
        )
        self.depth.set_items(DEPTH_NAMES, COLOUR_DEPTHS.index(manager.colour_depth))
        self.show_mouse = page.add(
            Switch(
                "Show the &mouse",
                9,
                43,
                on=manager.show_mouse,
                on_change=lambda switch: manager.set_show_mouse(
                    switch.on, remember=False
                ),
                name="show_mouse",
                status="Inverts the cell under the mouse, for terminals that "
                "show no pointer",
            )
        )
        page.add(Label("Escape waits for a key (ms)", 12, 43))
        self.escape_wait = page.add(
            SpinBox(
                13,
                43,
                8,
                minimum=registry.ESCAPE_TIMEOUT_RANGE.start,
                maximum=registry.ESCAPE_TIMEOUT_RANGE.stop - 1,
                value=self._saved_wait,
                step=10,
                on_change=lambda box: setattr(
                    manager, "escape_timeout", box.value / 1000
                ),
                name="escape_timeout",
                status="How long after Escape to wait for the rest of a key: "
                "raise it over a slow connection",
            )
        )
        self.refresh(self._saved_autostart)

    @property
    def chosen_depth(self) -> str:
        """The colour depth chosen (one of ``style.COLOUR_DEPTHS``)."""
        return COLOUR_DEPTHS[self.depth.value]

    @property
    def chosen(self) -> list[str]:
        """The ids of the applications chosen to start with the desktop."""
        return [self.ids[index] for index in sorted(self.autostart.selected)]

    def refresh(self, chosen: list[str] | None = None) -> None:
        """Offer the applications the desktop knows now, keeping those
        chosen (or choosing ``chosen``)."""
        chosen = self.chosen if chosen is None else chosen
        entries = sorted(self.manager.registry.values(), key=lambda e: e.name.lower())
        self.ids = [entry.id for entry in entries]
        self.autostart.selected = set()
        self.autostart.set_items(entry.name for entry in entries)
        self.autostart.selected = {
            index for index, app_id in enumerate(self.ids) if app_id in chosen
        }
        self.empty.text = "" if entries else "(None installed)"

    def save(self) -> bool:
        """Keep the animations, colour depth, show the mouse and escape
        wait settings, and the applications to start with, in
        ``settings.toml``, if they have changed. Returns whether all went
        well."""
        path = self.manager.settings_path
        try:
            if self.animations.on != self._saved_animations:
                registry.save_animations_setting(self.animations.on, path)
                self._saved_animations = self.animations.on
            if self.chosen != self._saved_autostart:
                registry.save_autostart_setting(self.chosen, path)
                self._saved_autostart = self.chosen
            if self.chosen_depth != self._saved_depth:
                registry.save_colour_depth_setting(self.chosen_depth, path)
                self._saved_depth = self.chosen_depth
            if self.show_mouse.on != self._saved_show_mouse:
                registry.save_show_mouse_setting(self.show_mouse.on, path)
                self._saved_show_mouse = self.show_mouse.on
            if self.escape_wait.value != self._saved_wait:
                registry.save_escape_timeout_setting(self.escape_wait.value, path)
                self._saved_wait = self.escape_wait.value
        except OSError as error:
            self.dialog.problem(
                "Settings", f"The settings could not be saved:\n{error}"
            )
            return False
        return True


class SettingsDialog(Dialog):  # pylint: disable=too-many-instance-attributes
    """Settings...: tabs for the Appearance, Shortcuts, Desktop and
    Applications pages, above OK, Cancel and Apply. See the module's
    description for what each does."""

    WIDTH = 76
    HEIGHT = 22
    """The dialog's size, which fits a screen of 80 by 24."""

    def __init__(self, manager: "PresentationManager") -> None:
        super().__init__(
            "Settings",
            self.WIDTH,
            self.HEIGHT,
            status="Changes show at once: OK keeps them, and Cancel puts them back",
        )
        self.desktop_manager = manager
        """The desktop whose settings these are."""
        self._snapshot = self._now()
        self.tabs = self.add(Tabs(0, 1, 72, 17, name="tabs"))
        self.appearance = AppearancePage(self, self.tabs.add_page("&Appearance"))
        self.shortcuts = ShortcutsPage(self, self.tabs.add_page("&Shortcuts"))
        self.desktop = DesktopPage(self, self.tabs.add_page("&Desktop"))
        self.applications = ApplicationsPage(self, self.tabs.add_page("Appl&ications"))
        self.help = "settings"
        for page, slug in zip(
            self.tabs.pages, ("appearance", "shortcuts", "desktop", "applications")
        ):
            page.help = f"settings#{slug}"
        buttons = [
            Button("&OK", 18, 0, result="ok", default=True, name="ok"),
            Button("&Cancel", 18, 0, result="cancel", name="cancel"),
            Button("A&pply", 18, 0, result="apply", name="apply"),
        ]
        # Centred in the interior, two columns between each.
        column = (self.WIDTH - sum(button.rect.width + 2 for button in buttons)) // 2
        for button in buttons:
            button.rect = Rect(18, column, button.rect.height, button.rect.width)
            column += button.rect.width + 2
            self.add(button)

    def _now(
        self,
    ) -> tuple[theme.Theme, str | None, Shortcuts, bool, str, bool, float]:
        """What Cancel puts back: the colours and theme's name, the
        shortcuts, whether animations are on, the colour depth, whether the
        mouse is shown, and how long Escape waits for a key."""
        manager = self.desktop_manager
        return (
            theme.current_theme(),
            manager.theme_name,
            manager.shortcuts,
            manager.animations,
            manager.colour_depth,
            manager.show_mouse,
            manager.escape_timeout,
        )

    # Asking and telling

    def ask(self, dialog: Dialog) -> str | None:
        """Show another dialog over this one, and return its answer."""
        return self.desktop_manager.execute(dialog)

    def problem(self, title: str, message: str) -> None:
        """Say what went wrong."""
        self.ask(information(title, message))

    def write(self, path: Path, text: str, title: str, *, ask: bool = True) -> bool:
        """Write a settings file, making its folder if need be. With ``ask``,
        a file that is already there is replaced only once the user agrees.
        Returns whether it was written (a problem has been shown if not)."""
        if ask and path.exists():
            replacing = confirm(title, f"{path.name} is there already.\nReplace it?")
            if self.ask(replacing) != "ok":
                return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_atomically(path, text if text.endswith("\n") else text + "\n")
        except OSError as error:
            self.problem(title, f"{path} could not be written:\n{error.strerror}")
            return False
        return True

    # Answering

    def save(self) -> bool:
        """Keep every page's settings for next time. Returns whether all
        went well; Cancel then puts back only what has changed since."""
        kept = all([self.appearance.save(), self.shortcuts.save(), self.desktop.save()])
        self._snapshot = self._now()
        return kept

    def button_pressed(self, button: Widget) -> None:
        """OK keeps the settings and closes, Apply keeps them, and Cancel
        puts them back and closes."""
        if button.name == "ok":
            if self.save():
                self.result = "ok"
        elif button.name == "apply":
            self.save()
        elif button.name == "cancel":
            self.cancel()
        else:
            super().button_pressed(button)

    def cancel(self) -> None:
        """Put everything back as it was, and close."""
        colours, name, shortcuts, animations, depth, show_mouse, wait = self._snapshot
        manager = self.desktop_manager
        manager.use_theme(colours, name)
        manager.set_shortcuts(shortcuts)
        manager.set_animations(animations, remember=False)
        manager.set_colour_depth(depth)
        manager.set_show_mouse(show_mouse, remember=False)
        manager.escape_timeout = wait
        super().cancel()
