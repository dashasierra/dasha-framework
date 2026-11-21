"""The Window menu."""

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING

from dasha.menu import Menu, MenuItem, separator
from dasha.window import Window

if TYPE_CHECKING:
    from dasha.application import Application
    from dasha.manager import PresentationManager


def window_menu(manager: "PresentationManager", window: Window) -> Menu:
    """A Window menu for a window.

    :param manager: The presentation manager.
    :param window: The window.
    """
    hint = manager.shortcuts.hint
    items = []
    if window.maximisable:
        items.append(
            MenuItem(
                "Ma&ximise / restore",
                partial(manager.toggle_maximise, window),
                hint("maximise_window"),
                "Fills the screen with this window, or restores its size",
            )
        )
    if window.minimisable:
        items.append(
            MenuItem(
                "Mi&nimise",
                partial(manager.minimise, window),
                hint("minimise_window"),
                f"Hides this window; restore it from the "
                f"{manager.system_menu_title} menu",
            )
        )
    items.append(
        MenuItem(
            "&Move",
            partial(manager.start_moving, window),
            hint("move_window"),
            "Move this window with the arrow keys; Enter when done",
        )
    )
    if window.resizable:
        items.append(
            MenuItem(
                "&Size",
                partial(manager.start_resizing, window),
                hint("resize_window"),
                "Resize this window with the arrow keys; Enter when done",
            )
        )
    items += [
        separator(),
        MenuItem(
            "Send to &back",
            partial(manager.send_to_back, window),
            status="Moves this window behind all the others",
        ),
        MenuItem(
            "Nex&t window",
            manager.activate_next,
            hint("next_window"),
            "Brings the next window to the front",
        ),
        separator(),
        MenuItem(
            "&Close",
            partial(manager.close, window),
            hint("close_window"),
            "Closes this window",
        ),
    ]
    return Menu("&Window", items, lists_minimised=True)


def fill_application_window_menu(
    manager: "PresentationManager", application: "Application", menu: Menu
) -> None:
    """Fill an application's Window menu in place.

    :param manager: The presentation manager.
    :param application: The application.
    :param menu: The Window menu.
    """
    hint = manager.shortcuts.hint
    window = application.active_window

    def needs(
        allowed: bool, method: Callable[[Window], object]
    ) -> Callable[[], object] | None:
        """The window's action, or ``None`` without a window.

        :param allowed: Whether the window allows it.
        :param method: The manager's action.
        """
        if window is None or not allowed:
            return None
        return partial(method, window)

    many = len(manager.windows) > 1
    items = [
        MenuItem(
            "Ma&ximise / restore",
            needs(
                window is not None and window.maximisable,
                manager.toggle_maximise,
            ),
            hint("maximise_window"),
            "Fills the screen with this window, or restores its size",
        ),
        MenuItem(
            "Mi&nimise",
            needs(window is not None and window.minimisable, manager.minimise),
            hint("minimise_window"),
            "Hides this window; bring it back from this menu",
        ),
        MenuItem(
            "&Move",
            needs(True, manager.start_moving),
            hint("move_window"),
            "Move this window with the arrow keys; Enter when done",
        ),
        MenuItem(
            "&Size",
            needs(
                window is not None and window.resizable,
                manager.start_resizing,
            ),
            hint("resize_window"),
            "Resize this window with the arrow keys; Enter when done",
        ),
        separator(),
        MenuItem(
            "Send to &back",
            needs(True, manager.send_to_back),
            status="Moves this window behind all the others",
        ),
        MenuItem(
            "Nex&t window",
            manager.activate_next if many else None,
            hint("next_window"),
            "Brings the next window to the front",
        ),
        separator(),
        MenuItem(
            "&Close",
            needs(window is not None and window.closable, manager.close),
            hint("close_window"),
            "Closes this window",
        ),
    ]
    if application.windows:
        items.append(separator())
    for number, listed in enumerate(application.windows, start=1):
        title = listed.title.replace("&", "&&")  # not a mnemonic marker
        if listed in manager.minimised:
            title += " (minimised)"
        items.append(
            MenuItem(
                f"&{number} {title}" if number < 10 else title,
                partial(manager.show_window, listed),
                status=f'Brings "{listed.title}" to the front',
            )
        )
    menu.items[:] = items
