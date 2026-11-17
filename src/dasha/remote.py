"""The desktop's view of an application running in its own process: the
application's windows (``RemoteWindow``), drawn here from what the
application sends, and the application itself (``RemoteApplication``), as
the presentation manager sees it. ``dasha.hosting`` runs the process
and the connection.

Everything here comes from another process, which may have gone wrong or
been written to do harm, so nothing it sends is accepted as it is. Text is
kept to one line of at most ``MAX_TEXT`` characters (``one_line``), and
sizes and colours are checked (``dasha.protocol``). An application
cannot take over the desktop's own keys, or its name.
"""

from typing import TYPE_CHECKING

from dasha.application import Application
from dasha.canvas import Canvas
from dasha.dialog import Dialog, Popup
from dasha.events import MouseEvent
from dasha.protocol import (
    WINDOW_STYLES,
    Message,
    ProtocolError,
    bounded,
    decode_rect,
    decode_style,
    encode_mouse,
)
from dasha.shortcuts import DESKTOP_KEYS, Shortcuts
from dasha.style import Style
from dasha.widgets import Widget
from dasha.window import Window

if TYPE_CHECKING:
    from dasha.hosting import AppHost

MAX_WINDOWS = 100
"""The largest number of windows (including dialogs and drop-down lists)
that one application may have open at once."""
MAX_MENU_ITEMS = 2000
"""The largest number of items that an application's menu bar may have,
counting every menu and submenu together."""
MAX_MENU_DEPTH = 16
"""How many levels deep an application's submenus may go."""
MAX_TEXT = 1000
"""The largest number of characters kept of a title, status line or key
hint."""
MAX_HINTS = 20
"""The largest number of key hints that a window may give the status
bar."""
MAX_NAME = 40
"""The largest number of characters kept of an application's name."""
MAX_FOOTER = 40
"""The largest number of characters kept of each part of a window's
footer (``Window.footer``)."""
MAX_FOOTER_PARTS = 8
"""The largest number of parts kept of a window's footer."""


def one_line(text: object, limit: int = MAX_TEXT) -> str:
    """Text from an application, made into a single line of at most
    ``limit`` characters, because a title, status line or hint has no reason
    to break lines."""
    return " ".join(str(text).split())[:limit]


def application_name(text: object) -> str:
    """A name that an application gave itself, made fit for the desktop to
    use: a single line with no control characters, of at most ``MAX_NAME``
    characters. Returns ``""`` if nothing usable is left."""
    name = "".join(char for char in one_line(text, MAX_NAME * 4) if char.isprintable())
    return name.strip()[:MAX_NAME]


def never_enabled() -> bool:
    """The ``enabled`` check for an item that the application has greyed
    out."""
    return False


class _Focus(Widget):
    """Stands in for a remote window's focused widget: its status text and
    the keys the status bar lists for it."""

    def __init__(self) -> None:
        super().__init__(0, 0, 1)
        self.hints: list[tuple[str, str]] = []

    def key_help(self, shortcuts: Shortcuts) -> list[tuple[str, str]]:
        del shortcuts
        return list(self.hints)


class RemoteWindow(Window):  # pylint: disable=too-many-instance-attributes
    """A window of an application running in another process. The frame is
    drawn here, and the inside is what the application sent."""

    def __init__(self, host: "AppHost", number: int, state: Message) -> None:
        super().__init__(one_line(state["title"]), decode_rect(state["rect"]))
        self.host = host
        self.number = number
        """The number the application knows this window by."""
        self.look = "window"
        self._colours: dict[str, Style] = {}
        self.modal = False
        self.close_on_outside_click = False
        self._runs: list[list[tuple[str, Style]]] = []
        self._cursor: tuple[int, int] | None = None
        self._content = (0, 0)
        self._remote_focus = _Focus()
        self.told_rect = (self.rect, self.maximised)
        """Where the application last knew the window was."""
        self.told_scroll = (0, 0)
        self.apply(state)
        # Its dialogs and drop-down lists are its application's, but belong
        # to none, as in an application's own process.
        self.application = host.application if self.look == "window" else None
        self.owner = host.application

    # From the application

    def apply(self, state: Message) -> None:
        """Apply the window's frame, title and settings, as sent by the
        application."""
        self.remote_title = one_line(state["title"])  # as the application gave it
        self.show_title()
        parts = state["footer"]
        if not isinstance(parts, list):
            raise ProtocolError("a footer is a list of parts")
        self.footer = [one_line(part, MAX_FOOTER) for part in parts[:MAX_FOOTER_PARTS]]
        self.maximised = bool(state["maximised"])
        self.rect = decode_rect(state["rect"])
        self.told_rect = (self.rect, self.maximised)
        flags = [bool(flag) for flag in state["flags"]]
        self.resizable, self.maximisable, self.minimisable, self.closable = flags
        self._set_look(str(state["look"]), state.get("colours", {}))
        self.modal = bool(state["modal"])
        self.close_on_outside_click = bool(state["outside"])
        self.status = one_line(state["status"])
        self._remote_focus.status = self.status
        hints = state["hints"][:MAX_HINTS]
        self._remote_focus.hints = [(one_line(k), one_line(v)) for k, v in hints]
        width, height = state["content"]
        self._content = (bounded(width, 0), bounded(height, 0))
        row, column = state["scroll"]
        self.scroll_row, self.scroll_column = bounded(row), bounded(column)
        self.told_scroll = (self.scroll_row, self.scroll_column)

    def _set_look(self, look: str, colours: object) -> None:
        """How the application wants the window framed, and which colours of
        its own to use. Only the colours in ``WINDOW_STYLES`` are kept."""
        if not isinstance(colours, dict):
            raise ProtocolError("a window's colours are named styles")
        kept = {
            name: decode_style(colours[name])
            for name in WINDOW_STYLES
            if name in colours
        }
        if look == self.look and kept == self._colours:
            return
        self.look = look
        self._colours = kept
        self.theme_changed()

    def theme_changed(self) -> None:
        """Take on the current theme's colours for the window's look, except
        for those that the application chose itself."""
        theme_class = Dialog if self.look in ("dialog", "popup") else Window
        for name in WINDOW_STYLES:
            style = self._colours.get(name, getattr(theme_class, name))
            setattr(self, name, style)
        if self.look == "popup":
            self.border = Popup.border

    def apply_paint(self, message: Message) -> None:
        """Apply the changed rows of the window's interior, as sent by the
        application."""
        styles = [decode_style(style) for style in message["styles"]]
        width, height = (bounded(value, 0) for value in message["size"])
        if len(self._runs) != height:
            blank = [(" " * width, self.body_style)]
            self._runs = [list(blank) for _ in range(height)]
        for number, runs in message["rows"]:
            if 0 <= number < height:
                self._runs[number] = [(str(text), styles[n]) for text, n in runs]
        cursor = message.get("cursor")
        self._cursor = (
            None if cursor is None else (bounded(cursor[0]), bounded(cursor[1]))
        )

    # Shown here

    @property
    def content_size(self) -> tuple[int, int]:
        return self._content

    @property
    def focused(self) -> Widget | None:
        return self._remote_focus

    def paint(self, canvas: Canvas, active: bool) -> None:
        super().paint(canvas, active)
        if active and self._cursor is not None:
            interior = self.interior
            with canvas.clipped(interior):
                canvas.place_cursor(
                    interior.row + self._cursor[0], interior.column + self._cursor[1]
                )

    def paint_content(self, canvas: Canvas) -> None:
        interior = self.interior
        for offset, runs in enumerate(self._runs[: interior.height]):
            column = interior.column
            for text, style in runs:
                canvas.write(interior.row + offset, column, text, style, clip=interior)
                column += len(text)

    # Sent to the application

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        if any(shortcuts.matches(action, key) for action in DESKTOP_KEYS):
            return False  # the desktop's own: close, next window and so on
        self.host.input(self, "key", key=key)
        return True

    def handle_key_release(self, key: str) -> None:
        self.host.input(self, "release", key=key)

    def handle_paste(self, text: str) -> bool:
        self.host.input(self, "paste", text=text)
        return True

    def handle_mouse(self, event: MouseEvent) -> bool:
        self.host.input(self, "mouse", event=encode_mouse(event))
        return True

    def show_title(self) -> None:
        """Show the title, marked while the application is not
        responding."""
        hung = not self.host.responding
        self.title = self.remote_title + (" (Not responding)" if hung else "")

    def request_close(self) -> bool:
        """Let the application decide (it may ask about unsaved work), and
        close the window itself if it agrees. An application that is not
        responding cannot decide, so the user is offered the chance to end
        it instead."""
        if self.host.responding:
            self.host.send("close_request", id=self.number)
        else:
            self.host.offer_to_end()
        return False


class RemoteApplication(Application):
    """An application running in another process, as the desktop sees
    it."""

    keep_running = True  # it ends when its process says so
    is_remote = True

    def __init__(self, host: "AppHost", name: str) -> None:
        super().__init__()
        self.host = host
        self.name = name

    def has_help(self) -> bool:
        return True  # its own to know: it does nothing with show_help if not

    def show_help(self, topic: str | None = None) -> None:
        """Ask the application to show its help. This is for when it has no
        window to send the key to; it chooses the topic itself."""
        del topic
        self.host.send("help")

    def window_closed(self, window: Window) -> None:
        if window in self.windows:
            self.windows.remove(window)

    def can_close(self) -> bool:
        return True  # asked over the connection instead (AppServer.ask_to_close)

    def quit(self) -> None:
        self.host.stop()
