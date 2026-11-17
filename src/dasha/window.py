"""Windows: framed, titled rectangles, which the presentation manager
stacks on the desktop."""

from collections.abc import Iterable
from typing import TYPE_CHECKING, TypeVar

from dasha.border import DOUBLE, SINGLE, Border
from dasha.canvas import Canvas, Rect, shadow_rects
from dasha.events import MouseEvent
from dasha.menu import Menu
from dasha.scrollbar import ScrollBarLayout
from dasha.shortcuts import Shortcuts
from dasha.style import (
    BLUE,
    BRIGHT_GREEN,
    CYAN,
    BRIGHT_WHITE,
    SHADOW,
    WHITE,
    Style,
)

from dasha.widgets import Button, Grow, Widget
from dasha.widgets.container import (
    Container,
    lay_out,
    owners,
    sized_by_container,
)

if TYPE_CHECKING:
    from dasha.application import Application
    from dasha.manager import PresentationManager

# Border and its styles moved to dasha.border; re-exported for convenience.
__all__ = ["DOUBLE", "SINGLE", "Border", "Window"]

W = TypeVar("W", bound=Widget)


def _into_view(start: int, size: int, first: int, end: int) -> int:
    """Where a view ``size`` long, starting at ``start``, should start to
    show ``first`` up to ``end`` (one way: rows, or columns), moved as
    little as it can be. Something longer than the view stays where it is
    while part of it shows."""
    if end - first > size:
        if first < start + size and start < end:
            return start  # part of it shows
        return first if start < first else end - size
    if end > start + size:
        start = end - size
    return min(start, first)


# pylint: disable-next=too-many-instance-attributes,too-many-public-methods
class Window:
    """A framed rectangle with a title and some content.

    The active (focused) window has a double frame and the others a single
    one, as in classic text-mode environments. Its appearance is set by class
    attributes, so subclasses can restyle windows without changing the
    drawing code. To draw something other than plain lines of text, override
    ``paint_content``.

    While the window is active, its ``menus`` are shown on the menu bar,
    after the system menu, and its optional ``status`` text is shown on the
    status bar.

    A ``resizable`` window has a two-cell grip in its bottom-right corner,
    highlighted while the window is active, and dragging the grip resizes
    the window. Windows are not resizable unless they are asked to be.

    While it is active, a ``maximisable`` or ``minimisable`` window shows
    buttons at the right of its title bar: ``[↓]`` to minimise, ``[↑]`` to
    maximise, and ``[↕]`` to restore a maximised window. A ``closable``
    window shows ``[■]`` at the left. The presentation manager carries out
    these actions (see its ``maximise``, ``minimise``, ``restore`` and
    ``close`` methods).

    Widgets (labels, buttons and so on) are added with ``add`` and drawn
    inside the frame. One focusable widget at a time has the keyboard focus,
    and Tab moves it to the next. ``widget(name)`` and ``values`` read the
    widgets back.

    The lines and widgets make up the window's content, which can be bigger
    than the window (``content_size``). The window then scrolls: it shows the
    part of the content starting at ``scroll_row`` and ``scroll_column``, and
    a scroll bar appears on the frame in each direction in which the content
    does not fit.
    """

    border: Border = DOUBLE
    inactive_border: Border = SINGLE
    adjusting_border: Border = SINGLE
    """The frame's lines while the window is being moved or resized, with the
    mouse or the keyboard (drawn in ``adjusting_frame_style``)."""
    frame_style: Style = Style(foreground=BRIGHT_WHITE, background=BLUE, bold=True)
    inactive_frame_style: Style = Style(foreground=WHITE, background=BLUE)
    adjusting_frame_style: Style = Style(
        foreground=BRIGHT_GREEN, background=BLUE, bold=True
    )
    """The frame's colours while the window is being moved or resized, with
    the mouse or the keyboard."""
    application: "Application | None" = None
    """The application the window belongs to, set by ``Application.open``
    (``None`` for a window added directly to the manager)."""
    help: str | None = None
    """The help topic for the widgets in the window that have none of their
    own (see ``dasha.help``). Set it on a window."""
    owner: "Application | None" = None
    """For a window that belongs to no application (a dialog), the
    application it came from, if known. That application becomes the active
    one while the window is in front."""
    modal: bool = False
    """Whether the window is a dialog waiting for an answer (set by
    ``execute``)."""
    close_on_outside_click: bool = False
    """Whether a click outside the window cancels it, as it does for a
    drop-down list or a context menu (a ``Popup``), rather than being
    ignored. The window behind such a popup still looks active
    (``PresentationManager.looks_active``)."""
    manager: "PresentationManager | None" = None
    """The presentation manager the window is on, set by the manager's
    ``add`` and cleared by its ``remove``, so that widgets can reach it (to
    drop down a list, for example)."""
    adjusting: bool = False
    """Whether the window is being moved or resized, with the mouse or the
    keyboard. The presentation manager sets this while it happens, and the
    frame changes style to show it."""
    body_style: Style = Style(foreground=WHITE, background=BLUE)

    shadow_style: Style | None = SHADOW
    """How the drop shadow recolours what lies beneath it; ``None`` for no
    shadow."""
    shadow_width: int = 2
    """How many columns of shadow fall to the right (two, so that the shadow
    looks square)."""
    shadow_height: int = 1
    """How many rows of shadow fall below."""

    resize_grip: str = (
        "\N{BOX DRAWINGS LIGHT HORIZONTAL}\N{BOX DRAWINGS LIGHT UP AND LEFT}"
    )
    """The bottom-right corner of a resizable window, drawn over the end of
    the frame. It is two cells wide, so that it is easy to see and to grab,
    and uses plain single-line box characters, which every code page 437 font
    has."""
    resize_grip_style: Style = Style(
        foreground=BRIGHT_GREEN, background=BLUE, bold=True
    )
    """The grip's colours while the window is active; otherwise, it takes the
    frame's colours."""
    min_width: int = 12
    """The narrowest width a window can be resized to."""
    min_height: int = 3
    """The smallest height a window can be resized to (its frame and one
    line)."""

    close_button: str = "[\N{BLACK SQUARE}]"
    minimise_button: str = "[\N{DOWNWARDS ARROW}]"
    maximise_button: str = "[\N{UPWARDS ARROW}]"
    restore_button: str = "[\N{UP DOWN ARROW}]"
    """The title bar buttons. ■ is code page 437 character 254, and the
    arrows are its glyphs 25, 24 and 18."""
    button_style: Style = Style(foreground=BRIGHT_GREEN, background=BLUE, bold=True)
    """The colours of the symbol inside each title bar button (``■``, ``↓``,
    ``↑``, ``↕``); the brackets around it are drawn in the frame's colours."""

    scrollbar_style: Style = Style(foreground=BLUE, background=CYAN)
    """The colours of the scroll bars on the frame: their arrows, track and
    thumb."""
    scroll_step: int = 1
    """How many rows or columns one click on a scroll bar arrow (or one
    press of an arrow key) scrolls."""

    plain_mnemonics: bool = False
    """Whether a widget's mnemonic letter works on its own, without Alt (as
    it does in dialogs)."""

    def __init__(
        self,
        title: str,
        rect: Rect,
        lines: Iterable[str] = (),
        *,
        menus: Iterable[Menu] = (),
        status: str = "",
        resizable: bool = False,
        maximisable: bool = False,
        minimisable: bool = False,
        closable: bool = False,
    ) -> None:
        if rect.height < 2 or rect.width < 2:
            raise ValueError("A window needs room for its frame (at least 2x2)")
        self.title = title
        self._rect = rect
        self.lines = list(lines)
        self.menus = list(menus)
        self.status = status
        self.resizable = resizable
        self.maximisable = maximisable
        self.minimisable = minimisable
        self.closable = closable
        self.footer: list[str] = []
        """A few words at the left of the frame's bottom edge, in parts
        (``["☼", "12:3"]`` shows ``╚═ ☼ ═ 12:3 ═══``): the frame draws the
        line between each two, in its own border and colours as they are,
        active, inactive or being moved. Shown while there is room for
        them all; the horizontal scroll bar starts after them. None by
        default. See ``footer_parts``."""
        self.maximised = False
        """Whether the window is filling the work area (see ``maximise``)."""
        self._normal_rect: Rect | None = None
        self.widgets: list[Widget] = []
        self._focus: Widget | None = None
        self._mouse_widget: Widget | None = None  # the one a press went to
        self.scroll_row = 0
        """How far the content is scrolled down (rows hidden above)."""
        self.scroll_column = 0
        """How far the content is scrolled right (columns hidden on the left)."""

    @property
    def interior(self) -> Rect:
        """The area inside the frame, where content is drawn."""
        return self.rect.inset(1)

    @property
    def title_bar(self) -> Rect:
        """The top row of the frame, used to drag the window around."""
        return Rect(self.rect.row, self.rect.column, 1, self.rect.width)

    def move_to(self, row: int, column: int) -> None:
        """Move the window's top-left corner, keeping its size.

        The new position may be partly (or even wholly) off the screen; the
        window is simply clipped when it is drawn.
        """
        self.rect = Rect(row, column, self.rect.height, self.rect.width)

    @property
    def resize_grip_rect(self) -> Rect | None:
        """The grip's cells for a resizable window, whether or not it is
        maximised (resizing a maximised window stops it being maximised), or
        ``None`` for a window that is not resizable."""
        if not self.resizable:
            return None
        width = len(self.resize_grip)
        return Rect(self.rect.bottom - 1, self.rect.right - width, 1, width)

    def maximise(self, area: Rect) -> None:
        """Fill ``area``, remembering the current position and size.

        Calling this again while the window is maximised just fits it to the
        new ``area`` (after the terminal is resized, for example), keeping the
        size that it will be restored to.
        """
        if not self.maximised:
            self._normal_rect = self.rect
            self.maximised = True
        self.rect = area

    def unmaximise(self) -> None:
        """Stop being maximised, returning to the earlier position and size."""
        if self.maximised and self._normal_rect is not None:
            self.rect = self._normal_rect
        self.maximised = False
        self._normal_rect = None

    def release(self) -> None:
        """Stop being maximised, keeping the current position and size. This
        is what resizing a maximised window does, so that the resize starts
        from the size the window has now."""
        self.maximised = False
        self._normal_rect = None

    @property
    def restored_rect(self) -> Rect:
        """Where the window is when it is not maximised: while it is
        maximised, where restoring it would put it, and otherwise simply where
        it is."""
        if self.maximised and self._normal_rect is not None:
            return self._normal_rect
        return self.rect

    # Widgets

    @property
    def rect(self) -> Rect:
        """Where the window is on the screen, including its frame. Setting a
        new size moves and stretches the widgets that have a ``grow``
        setting."""
        return self._rect

    @rect.setter
    def rect(self, rect: Rect) -> None:
        before = self.interior
        self._rect = rect
        after = self.interior
        if (before.width, before.height) != (after.width, after.height):
            for widget in self.widgets:
                if not sized_by_container(widget):  # a pane sizes its own
                    widget.follow_resize(
                        (before.width, before.height), (after.width, after.height)
                    )

    def add(self, widget: W, grow: Grow | None = None) -> W:
        """Put a widget in the window, and return it for convenience.

        The first focusable widget added receives the focus. ``grow`` sets
        how the widget follows the window's size (for example, ``Grow.ALL``
        makes it fill the room the window gains); by default it keeps its
        position and size.
        """
        if grow is not None:
            widget.grow = grow
        widget.window = self
        self.widgets.append(widget)
        if self._focus is None and self._focusable(widget):
            self._focus = widget
            widget.focus_changed(True)
        widget.on_add()
        self.lay_out()
        return widget

    def lay_out(self) -> None:
        """Move widgets with their containers, moving those below each
        expanded collapsible area down out of its way, and back up below each
        collapsed one (see ``dasha.widgets.container``)."""
        if any(
            widget.parent is not None or isinstance(widget, Container)
            for widget in self.widgets
        ):
            lay_out(self.widgets)

    @property
    def shown_widgets(self) -> list[Widget]:
        """The widgets that are shown: all of them except those inside
        containers that are hiding their widgets, such as collapsed areas."""
        return [widget for widget in self.widgets if widget.is_shown]

    @staticmethod
    def _focusable(widget: Widget) -> bool:
        """Whether a widget can take the focus now: it shows, and it can."""
        return widget.is_shown and widget.can_focus()

    def screen_rect(self, widget: Widget) -> Rect:
        """Where a widget is on the screen, taking scrolling into account."""
        interior, rect = self.interior, widget.rect
        return Rect(
            interior.row + rect.row - self.scroll_row,
            interior.column + rect.column - self.scroll_column,
            rect.height,
            rect.width,
        )

    def widget(self, name: str) -> Widget:
        """The widget with this ``name``. Raises ``KeyError`` if there is
        none."""
        for widget in self.widgets:
            if widget.name == name:
                return widget
        raise KeyError(name)

    @property
    def values(self) -> dict[str, object]:
        """The ``value`` of every named widget, keyed by name."""
        return {w.name: w.value for w in self.widgets if w.name is not None}

    @property
    def focused(self) -> Widget | None:
        """The widget with the keyboard focus, if any."""
        return self._focus

    def focus(self, widget: Widget, *, reveal: bool = True) -> None:
        """Give a widget in this window the keyboard focus, scrolling it into
        view if necessary (unless ``reveal`` is false, as it is for a widget
        that was clicked, which is already in view)."""
        if widget in self.widgets and self._focusable(widget):
            before, self._focus = self._focus, widget
            if before is not widget:
                if before is not None:
                    before.focus_changed(False)
                widget.focus_changed(True)
            if reveal:
                self.scroll_into_view(widget.rect)

    def focus_next(self, step: int = 1) -> None:
        """Move the focus to the next focusable widget (or, with ``step`` -1,
        to the previous one)."""
        focusable = [widget for widget in self.widgets if self._focusable(widget)]
        if not focusable:
            return
        index = focusable.index(self._focus) if self._focus in focusable else -step
        self.focus(focusable[(index + step) % len(focusable)])

    @property
    def default_button(self) -> Button | None:
        """The button Enter presses when the focus is not on a button."""
        for widget in self.shown_widgets:
            if isinstance(widget, Button) and widget.default:
                return widget
        return None

    def button_pressed(self, button: Widget) -> None:
        """Called after any button in the window is pressed. Dialogs use this
        to finish with the button's result; ordinary windows do nothing."""

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Offer a key to the window's widgets, and return whether it was
        used.

        The focused widget receives the key first. After that, Tab and
        Shift+Tab move the focus (when there are at least two focusable
        widgets), Enter or Space presses the focused button (or the default
        one), and a widget's mnemonic letter activates that widget.
        """
        focused = self._focus
        if focused is not None and focused.handle_key(key, shortcuts):
            return True
        if (
            self._window_key(key, shortcuts)
            or self._focus_key(key, shortcuts)
            or self._press_key(key, shortcuts, focused)
        ):
            return True
        letter = self._mnemonic_letter(key, shortcuts)
        if letter is not None:
            for widget in self.shown_widgets:
                if letter in widget.mnemonics():
                    self.focus(widget)
                    widget.activate_mnemonic(letter)
                    return True
        return self._scroll_key(key, shortcuts)

    def _focus_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Tab and Shift+Tab move the focus, when there are at least two
        widgets to move it between."""
        if sum(self._focusable(widget) for widget in self.widgets) < 2:
            return False
        # Ctrl+Tab and Ctrl+Shift+Tab do too, so they get out of (and into)
        # a text area, where Tab types a tab.
        if shortcuts.matches("next_widget", key) or shortcuts.matches(
            "area_next_widget", key
        ):
            self.focus_next(1)
            return True
        if shortcuts.matches("previous_widget", key) or shortcuts.matches(
            "area_previous_widget", key
        ):
            self.focus_next(-1)
            return True
        return False

    def _press_key(
        self, key: str, shortcuts: Shortcuts, focused: Widget | None
    ) -> bool:
        """Enter or Space presses the focused button, or else the default
        one."""
        if not shortcuts.matches("press_button", key):
            return False
        target = focused if isinstance(focused, Button) else self.default_button
        if target is None:
            return False
        target.press_with_key(key, held=target is focused)
        return True

    context_menu: "Menu | None" = None
    """The menu that pops up for a right-click on the window where no
    widget has a menu of its own, and for Shift+F10 when the focused widget
    has none. Set it on a window."""

    def _pop_up(self, menu: Menu | None, row: int, column: int) -> bool:
        """Pop a context menu up at a place on the screen, if there is one
        and a manager to show it."""
        manager = self.manager
        if menu is None or manager is None or not menu.items:
            return False
        manager.context_menu(menu, row, column)
        return True

    def _pop_up_for_key(self, shortcuts: Shortcuts) -> bool:
        """Shift+F10: the focused widget's menu under it, or the window's
        at the top left of its inside."""
        focused = self._focus
        if focused is not None and (menu := focused.popup_menu(shortcuts)):
            at = self.screen_rect(focused)
            return self._pop_up(menu, at.row + 1, at.column)
        interior = self.interior
        return self._pop_up(self.context_menu, interior.row, interior.column)

    def _pop_up_for_click(self, event: MouseEvent, row: int, column: int) -> bool:
        """A right-click: the menu of the widget under the pointer (front
        first, focusing it), or else the window's, at the pointer."""
        manager = self.manager
        shortcuts = manager.shortcuts if manager is not None else Shortcuts()
        for widget in reversed(self.shown_widgets):
            if widget.rect.contains(row, column):
                menu = widget.popup_menu(shortcuts)
                if menu is not None:
                    self.focus(widget, reveal=False)
                    widget.point_at(row, column)  # a list's row, say
                    return self._pop_up(menu, event.row, event.column)
        return self._pop_up(self.context_menu, event.row, event.column)

    def _window_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Keys that work anywhere in the window: Shift+F10 for a context
        menu, then a key no widget used offered to every widget that shows
        (``Widget.window_key``), first the focused widget and those it is
        inside, nearest first."""
        if shortcuts.matches("context_menu", key) and self._pop_up_for_key(shortcuts):
            return True  # Shift+F10, for the focused widget or the window
        shown = self.shown_widgets
        first = [] if self._focus is None else owners(self._focus)
        for widget in first + [widget for widget in shown if widget not in first]:
            if widget.is_shown and widget.window_key(key, shortcuts):
                return True
        return False

    def handle_key_release(self, key: str) -> None:
        """A key was released, so tell every widget (such as a button pushed
        in by Space, which is pressed only if it still has the focus)."""
        for widget in self.widgets:
            widget.handle_key_release(key, widget is self._focus)

    def _scroll_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Scroll for the arrow and page keys, if there is anything to scroll."""
        max_row, max_column = self.max_scroll
        page_rows = max(1, self.interior.height - 1)
        moves = {
            "scroll_up": (-self.scroll_step, 0),
            "scroll_down": (self.scroll_step, 0),
            "scroll_left": (0, -self.scroll_step),
            "scroll_right": (0, self.scroll_step),
            "scroll_page_up": (-page_rows, 0),
            "scroll_page_down": (page_rows, 0),
        }
        for action, (rows, columns) in moves.items():
            if shortcuts.matches(action, key):
                if (rows and max_row) or (columns and max_column):
                    self.scroll_by(rows, columns)
                    return True
                return False
        return False

    def _mnemonic_letter(self, key: str, shortcuts: Shortcuts) -> str | None:
        for modifier in shortcuts.keys("menu_mnemonic_modifiers"):
            prefix = modifier + "+"
            if key.startswith(prefix) and len(key) == len(prefix) + 1:
                return key[-1].lower()
        if self.plain_mnemonics and len(key) == 1 and key.isalnum():
            return key.lower()
        return None

    def handle_paste(self, text: str) -> bool:
        """Offer text pasted through the terminal to the focused widget, and
        return whether it was used."""
        return self._focus is not None and self._focus.handle_paste(text)

    def handle_mouse(self, event: MouseEvent) -> bool:
        """Offer a mouse event to the widget under the pointer (or, for drags
        and releases, to the widget on which the button was pressed). The
        mouse wheel goes to whatever is under the pointer, if it accepts it."""
        interior = self.interior
        # Widget positions are within the content, which may be scrolled.
        row = event.row - interior.row + self.scroll_row
        column = event.column - interior.column + self.scroll_column
        if event.action in ("press", "scroll"):
            if event.action == "press":
                self._mouse_widget = None
            if not interior.contains(event.row, event.column):
                return False
            if (
                event.action == "press"
                and event.button == "right"
                and self._pop_up_for_click(event, row, column)
            ):
                return True
            return self._offer_at(event, row, column)
        target = self._mouse_widget
        if target is None:
            return False
        if event.action == "release":
            self._mouse_widget = None
        return target.handle_mouse(event, row, column)

    def _offer_at(self, event: MouseEvent, row: int, column: int) -> bool:
        """Offer a press or a wheel notch to the widgets at a position in the
        content, front first. A press focuses the widget, and the one that
        takes it gets the drags and the release that follow. If none takes
        it, the focus goes to the front-most widget there that can have it,
        rather than staying with the last one offered the press (a splitter,
        say, behind the panes it holds)."""
        front: Widget | None = None  # the front-most one that took the focus
        for widget in reversed(self.shown_widgets):
            if not widget.rect.contains(row, column):
                continue
            if event.action == "scroll":
                return widget.handle_mouse(event, row, column)
            # Showing under the pointer already: scrolling it into view
            # would move what was clicked on (a text area bigger than the
            # window, say) out from under the pointer.
            self.focus(widget, reveal=False)
            if front is None and self._focus is widget:
                front = widget
            if widget.handle_mouse(event, row, column):
                self._mouse_widget = widget
                return True
        if front is not None:
            self.focus(front, reveal=False)
        return False

    # Scrolling

    @property
    def content_size(self) -> tuple[int, int]:
        """The (width, height) of the content: how far the furthest line or
        widget reaches. Override this if ``paint_content`` draws something
        else."""
        width = max((len(line) + 1 for line in self.lines), default=0)
        height = len(self.lines)
        for widget in self.shown_widgets:
            width = max(width, widget.rect.right)
            height = max(height, widget.rect.bottom)
        return width, height

    @property
    def max_scroll(self) -> tuple[int, int]:
        """How far the content can be scrolled, as (rows, columns)."""
        width, height = self.content_size
        interior = self.interior
        return max(0, height - interior.height), max(0, width - interior.width)

    def scroll_to(self, row: int, column: int) -> None:
        """Scroll to show the content from ``row``, ``column`` (kept within
        range)."""
        max_row, max_column = self.max_scroll
        self.scroll_row = min(max(row, 0), max_row)
        self.scroll_column = min(max(column, 0), max_column)

    def scroll_by(self, rows: int, columns: int) -> None:
        """Scroll by a number of rows (down) and columns (right); negative
        numbers scroll back."""
        self.scroll_to(self.scroll_row + rows, self.scroll_column + columns)

    def scroll_into_view(self, rect: Rect) -> None:
        """Scroll as little as needed to show ``rect``, given in content
        coordinates. A rectangle bigger than the window (such as a long text
        area) is left where it is if part of it is showing, and otherwise is
        brought into view only until it fills the window."""
        interior = self.interior
        self.scroll_to(
            _into_view(self.scroll_row, interior.height, rect.row, rect.bottom),
            _into_view(self.scroll_column, interior.width, rect.column, rect.right),
        )

    def footer_parts(self) -> list[str]:
        """The parts of the footer to show at the left of the frame's bottom
        edge (``╚═ ☼ ═ 12:3 ═══``). This returns ``footer``, but a subclass
        can override it to work the parts out each time the window is drawn,
        as Notepad's window does to show the cursor position. Empty parts are
        left out, and no parts means no footer."""
        return list(self.footer)

    @staticmethod
    def footer_width(parts: list[str]) -> int:
        """How many cells the footer parts take up, not counting the spaces
        around the whole footer: the parts themselves, and a frame line with a
        space on either side between each pair of parts."""
        return sum(len(part) for part in parts) + 3 * max(0, len(parts) - 1)

    @property
    def shown_footer(self) -> list[str]:
        """The footer's parts as the frame shows them: ``footer_parts``
        without the empty ones, or no parts at all when there is not room for
        all of them along the bottom edge, beside the corner and (if the
        content needs one) a horizontal scroll bar of at least two cells."""
        parts = [part for part in self.footer_parts() if part]
        if not parts:
            return []
        width, _ = self.content_size
        scrolls = width > self.interior.width and self.rect.width - 4 >= 2
        room = self.rect.width - (9 if scrolls else 7)
        return parts if self.footer_width(parts) <= room else []

    @property
    def scroll_bars(self) -> tuple[ScrollBarLayout | None, ScrollBarLayout | None]:
        """The (vertical, horizontal) scroll bars, each ``None`` where the
        content fits, or where the frame is too small for a bar.

        The vertical bar runs down the right edge of the frame, between the
        corners. The horizontal bar runs along the bottom edge from two cells
        in (or from after the footer, when one is shown), stopping two cells
        short of the corner, clear of the resize grip.
        """
        self.scroll_to(self.scroll_row, self.scroll_column)  # after any resize
        width, height = self.content_size
        interior, rect = self.interior, self.rect
        vertical = horizontal = None
        if height > interior.height and rect.height - 2 >= 2:
            vertical = ScrollBarLayout(
                True,
                rect.row + 1,
                rect.right - 1,
                rect.height - 2,
                self.scroll_row,
                height - interior.height,
                interior.height,
            )
        if width > interior.width and rect.width - 4 >= 2:
            # After the footer (``╚═ 12:3 ═◄``), if one shows.
            footer = self.shown_footer
            start = rect.column + 2 + (self.footer_width(footer) + 3 if footer else 0)
            horizontal = ScrollBarLayout(
                False,
                rect.bottom - 1,
                start,
                rect.right - 2 - start,
                self.scroll_column,
                width - interior.width,
                interior.width,
            )
        return vertical, horizontal

    def scroll_bar_at(
        self, row: int, column: int
    ) -> tuple[ScrollBarLayout, str] | None:
        """The scroll bar at a screen position, and which part of it is
        there."""
        for scroll_bar in self.scroll_bars:
            if scroll_bar is not None:
                part = scroll_bar.part_at(row, column)
                if part is not None:
                    return scroll_bar, part
        return None

    def press_scroll_bar(self, scroll_bar: ScrollBarLayout, part: str) -> None:
        """Scroll as a click on a scroll bar's arrow or track does."""
        step = scroll_bar.step(part, self.scroll_step)
        if scroll_bar.vertical:
            self.scroll_by(step, 0)
        else:
            self.scroll_by(0, step)

    def theme_changed(self) -> None:
        """Called when the theme changes (``manager.set_theme``). A window
        reads its colours from its class's attributes, which the theme sets,
        so usually there is nothing to do. A window that keeps its own copy
        of a style updates it here."""

    def request_close(self) -> bool:
        """Called when the user closes the window. Return ``False`` to keep
        it open (a subclass might ask about unsaved work first)."""
        return True

    @property
    def title_buttons(self) -> list[tuple[str, Rect]]:
        """The title bar buttons, as ``(action, cells)`` pairs.

        First come the buttons at the right of the top edge, from right to
        left: ``"maximise"`` (or ``"restore"``) and ``"minimise"``, leaving one
        frame cell and the corner beyond them. Then comes ``"close"``, at the
        left, two cells in. Buttons that would not fit are left out.
        """
        buttons: list[tuple[str, str]] = []
        if self.maximisable:
            if self.maximised:
                buttons.append(("restore", self.restore_button))
            else:
                buttons.append(("maximise", self.maximise_button))
        if self.minimisable:
            buttons.append(("minimise", self.minimise_button))
        result = []
        right = self.rect.right - 2  # one frame cell, then the corner
        for action, text in buttons:
            left = right - len(text)
            if left <= self.rect.column:
                break
            result.append((action, Rect(self.rect.row, left, 1, len(text))))
            right = left
        if self.closable:
            left = self.rect.column + 2
            if left + len(self.close_button) <= right:
                result.append(
                    ("close", Rect(self.rect.row, left, 1, len(self.close_button)))
                )
        return result

    def button_at(self, row: int, column: int) -> str | None:
        """The action of the title bar button at a position, if any."""
        for action, cells in self.title_buttons:
            if cells.contains(row, column):
                return action
        return None

    def resize(self, width: int, height: int) -> None:
        """Change the window's size, keeping its top-left corner in place.

        The window is never made smaller than ``min_width`` by ``min_height``.
        This works whether or not the window is ``resizable``, which controls
        only whether the user can resize it.
        """
        width = max(width, self.min_width, 2)
        height = max(height, self.min_height, 2)
        self.rect = Rect(self.rect.row, self.rect.column, height, width)

    @property
    def shadow_rects(self) -> tuple[Rect, Rect]:
        """The drop shadow: a strip down the right side and a strip along the
        bottom, each offset so that the window seems to float above the
        screen."""
        return shadow_rects(self.rect, self.shadow_width, self.shadow_height)

    def paint(self, canvas: Canvas, active: bool) -> None:
        """Paint the whole window (its shadow, frame and content) onto the
        canvas."""
        self.paint_shadow(canvas)
        canvas.fill(self.rect, " ", self.body_style)
        self.paint_frame(canvas, active)
        self.paint_content(canvas)
        self.paint_widgets(canvas, active)

    def render_interior(self, active: bool) -> Canvas:
        """The inside of the window (its content and widgets, without the
        frame), drawn on a canvas of its own whose top-left cell is the
        interior's. This is what an application sends its desktop to show
        inside the frame. The cursor, if a widget shows one, is given in the
        canvas's coordinates."""
        interior = self.interior
        canvas = Canvas(max(0, interior.width), max(0, interior.height))
        real = self._rect
        # Drawn as though the window's frame were just off the canvas, so
        # the interior lands at 0, 0; the size is the same, so nothing grows.
        self._rect = Rect(-1, -1, real.height, real.width)
        try:
            canvas.fill(canvas.bounds, " ", self.body_style)
            self.paint_content(canvas)
            self.paint_widgets(canvas, active)
        finally:
            self._rect = real
        return canvas

    def paint_between(
        self, canvas: Canvas, rect: Rect, inside: Canvas, bars: tuple[bool, bool]
    ) -> None:
        """Paint the window part-way through an animation (see
        ``PresentationManager.animations``). Its frame is drawn at ``rect``,
        as the active window's frame, holding ``inside`` (a
        ``render_interior`` taken when the animation began) exactly as it
        was, cut off where the frame is smaller and with blank space beyond it
        where it is bigger. Only the scroll bars that ``bars`` (vertical,
        horizontal) allows, which are those the window has at the end, are
        drawn. The window itself is left unchanged."""
        real, scroll = self._rect, (self.scroll_row, self.scroll_column)
        self._rect = rect  # not the setter: nothing is laid out again
        try:
            self.paint_shadow(canvas)
            canvas.fill(rect, " ", self.body_style)
            self.paint_frame(canvas, True, bars)
            interior = self.interior
            canvas.copy_from(inside, interior.row, interior.column, clip=interior)
        finally:
            self._rect = real
            self.scroll_row, self.scroll_column = scroll

    def paint_shadow(self, canvas: Canvas) -> None:
        """Darken whatever lies under the drop shadow, keeping its
        characters."""
        if self.shadow_style is not None:
            canvas.cast_shadow(
                self.rect, self.shadow_style, self.shadow_width, self.shadow_height
            )

    def paint_frame(
        self, canvas: Canvas, active: bool, bars: tuple[bool, bool] = (True, True)
    ) -> None:
        """Paint the frame, with the title centred in its top edge, and the
        scroll bars that ``bars`` (vertical, horizontal) allows, where the
        content needs them."""
        border = self.border if active else self.inactive_border
        style = self.frame_style if active else self.inactive_frame_style
        if self.adjusting:
            border, style = self.adjusting_border, self.adjusting_frame_style
        rect = self.rect
        inner_width = rect.width - 2

        canvas.write(
            rect.row,
            rect.column,
            border.top_left + border.horizontal * inner_width + border.top_right,
            style,
        )
        for row in range(rect.row + 1, rect.bottom - 1):
            canvas.write(row, rect.column, border.vertical, style)
            canvas.write(row, rect.right - 1, border.vertical, style)
        canvas.write(
            rect.bottom - 1,
            rect.column,
            border.bottom_left + border.horizontal * inner_width + border.bottom_right,
            style,
        )

        footer = self.shown_footer
        if footer:
            # Parted by the frame's own line, as it is drawn now: double
            # while active, single while not, and so on.
            between = f" {border.horizontal} "
            text = f" {between.join(footer)} "
            canvas.write(rect.bottom - 1, rect.column + 2, text, style)

        if self.resize_grip_rect is not None:  # resizable, maximised or not
            canvas.write(
                rect.bottom - 1,
                rect.right - len(self.resize_grip),
                self.resize_grip,
                self.resize_grip_style if active else style,
            )

        for scroll_bar, allowed in zip(self.scroll_bars, bars):
            if scroll_bar is not None and allowed:
                scroll_bar.paint(canvas, self.scrollbar_style)

        self._paint_title(canvas, active, style)

    def _title_place(self, buttons: list[tuple[str, Rect]]) -> tuple[int, str] | None:
        """Where the title goes (its column and text, cut to fit), centred
        on the frame but clear of ``buttons``; ``None`` if there is no room."""
        rect = self.rect
        left, right = rect.column + 1, rect.right - 1
        for action, cells in buttons:
            if action == "close":
                left = cells.right
            else:
                right = min(right, cells.column)
        if not self.title or right - left <= 2:
            return None
        title = f" {self.title} "[: right - left]
        centred = rect.column + (rect.width - len(title)) // 2
        return max(left, min(centred, right - len(title))), title

    def _paint_title(self, canvas: Canvas, active: bool, style: Style) -> None:
        """The title, and on the active window the title bar buttons.

        Buttons show only on the active window. The
        title is centred on the whole frame, so it sits in the middle
        whichever buttons there are (and does not move as the window becomes
        active); it moves aside only if a button would cover it.
        """
        buttons = self.title_buttons if active else []
        placed = self._title_place(buttons)
        if placed is not None:
            canvas.write(self.rect.row, placed[0], placed[1], style)
        texts = {
            "close": self.close_button,
            "maximise": self.maximise_button,
            "restore": self.restore_button,
            "minimise": self.minimise_button,
        }
        for action, cells in buttons:
            # The brackets take the frame's colours; only the symbol between
            # them is drawn in the button colours.
            text = texts[action]
            canvas.write(cells.row, cells.column, text, style)
            canvas.write(cells.row, cells.column + 1, text[1:-1], self.button_style)

    def paint_content(self, canvas: Canvas) -> None:
        """Paint the window's lines of text inside the frame, scrolled."""
        interior = self.interior
        first = self.scroll_row
        for offset, line in enumerate(self.lines[first : first + interior.height]):
            canvas.write(
                interior.row + offset,
                interior.column + 1 - self.scroll_column,
                line,
                self.body_style,
                clip=interior,
            )

    def paint_widgets(self, canvas: Canvas, active: bool) -> None:
        """Paint the widgets inside the frame, scrolled, showing the focus
        while the window is active. Each widget draws itself at its position
        in the content, and the canvas keeps the drawing inside the frame."""
        interior = self.interior
        width, height = self.content_size
        origin = Rect(
            interior.row - self.scroll_row,
            interior.column - self.scroll_column,
            max(height, interior.height),
            max(width, interior.width),
        )
        with canvas.clipped(interior):
            for widget in self.shown_widgets:
                widget.paint(canvas, origin, active and widget is self._focus)
