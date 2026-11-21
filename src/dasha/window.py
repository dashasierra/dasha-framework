"""Framed, titled windows."""

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
    """Where a view should start to show a range.

    :param start: Current start.
    :param size: View length.
    :param first: Range start.
    :param end: Range end.
    """
    if end - first > size:
        if first < start + size and start < end:
            return start  # part of it shows
        return first if start < first else end - size
    if end > start + size:
        start = end - size
    return min(start, first)


# pylint: disable-next=too-many-instance-attributes,too-many-public-methods
class Window:
    """A framed rectangle with a title and content.

    :param title: Title text.
    :param rect: Position and size, including the frame.
    :param lines: Lines of text to show.
    :param menus: Menus shown if it belongs to no application.
    :param status: Status bar text.
    :param resizable: Whether the user can resize it.
    :param maximisable: Whether it can be maximised.
    :param minimisable: Whether it can be minimised.
    :param closable: Whether it has a close button.
    """

    border: Border = DOUBLE
    inactive_border: Border = SINGLE
    """Frame lines when active and inactive."""
    adjusting_border: Border = SINGLE
    """Frame lines while being moved or resized."""
    frame_style: Style = Style(foreground=BRIGHT_WHITE, background=BLUE, bold=True)
    inactive_frame_style: Style = Style(foreground=WHITE, background=BLUE)
    """The frame's and title's colours while active, and while not."""
    adjusting_frame_style: Style = Style(
        foreground=BRIGHT_GREEN, background=BLUE, bold=True
    )
    """Frame style while being moved or resized."""
    application: "Application | None" = None
    """The owning application, if any."""
    help: str | None = None
    """Help topic for its widgets."""
    owner: "Application | None" = None
    """The application an unowned window came from."""
    modal: bool = False
    """Whether it is a dialog awaiting an answer."""
    close_on_outside_click: bool = False
    """Whether an outside click cancels it."""
    manager: "PresentationManager | None" = None
    """The presentation manager it is on."""
    adjusting: bool = False
    """Whether it is being moved or resized."""
    body_style: Style = Style(foreground=WHITE, background=BLUE)
    """The colours inside the frame, which labels and other widgets build on."""

    shadow_style: Style | None = SHADOW
    """Drop shadow style, or ``None``."""
    shadow_width: int = 2
    """Shadow columns to the right."""
    shadow_height: int = 1
    """How many rows of shadow fall below."""

    resize_grip: str = (
        "\N{BOX DRAWINGS LIGHT HORIZONTAL}\N{BOX DRAWINGS LIGHT UP AND LEFT}"
    )
    """Resize grip characters."""
    resize_grip_style: Style = Style(
        foreground=BRIGHT_GREEN, background=BLUE, bold=True
    )
    """Grip style while active."""
    min_width: int = 12
    """The narrowest width a window can be resized to."""
    min_height: int = 3
    """Smallest height."""

    close_button: str = "[\N{BLACK SQUARE}]"
    minimise_button: str = "[\N{DOWNWARDS ARROW}]"
    maximise_button: str = "[\N{UPWARDS ARROW}]"
    restore_button: str = "[\N{UP DOWN ARROW}]"
    """Title bar button symbols."""
    button_style: Style = Style(foreground=BRIGHT_GREEN, background=BLUE, bold=True)
    """Title bar button symbol style."""

    scrollbar_style: Style = Style(foreground=BLUE, background=CYAN)
    """Scroll bar style."""
    scroll_step: int = 1
    """Rows or columns per scroll step."""

    plain_mnemonics: bool = False
    """Whether mnemonic letters work without Alt."""

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
        """The text centred in the top edge of the frame."""
        self._rect = rect
        self.lines = list(lines)
        """Lines of plain text drawn inside the frame."""
        self.menus = list(menus)
        """Menus shown if it belongs to no application."""
        self.status = status
        """Help for the status bar while active (see the class's description)."""
        self.resizable = resizable
        self.maximisable = maximisable
        self.minimisable = minimisable
        self.closable = closable
        self.footer: list[str] = []
        """Footer parts on the bottom edge."""
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
        """Move the window.

        :param row: New top row.
        :param column: New left column.
        """
        self.rect = Rect(row, column, self.rect.height, self.rect.width)

    @property
    def resize_grip_rect(self) -> Rect | None:
        """The resize grip's rect, or ``None``."""
        if not self.resizable:
            return None
        width = len(self.resize_grip)
        return Rect(self.rect.bottom - 1, self.rect.right - width, 1, width)

    def maximise(self, area: Rect) -> None:
        """Fill an area, remembering the old position.

        :param area: The area to fill.
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
        """Stop being maximised, keeping the current rect."""
        self.maximised = False
        self._normal_rect = None

    @property
    def restored_rect(self) -> Rect:
        """The rect when not maximised."""
        if self.maximised and self._normal_rect is not None:
            return self._normal_rect
        return self.rect

    # Widgets

    @property
    def rect(self) -> Rect:
        """Position and size on screen, including the frame."""
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
        """Add a widget and return it.

        :param widget: The widget.
        :param grow: How it follows the window's size, if at all.
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
        """Position widgets for their containers."""
        if any(
            widget.parent is not None or isinstance(widget, Container)
            for widget in self.widgets
        ):
            lay_out(self.widgets)

    @property
    def shown_widgets(self) -> list[Widget]:
        """The widgets shown."""
        return [widget for widget in self.widgets if widget.is_shown]

    @staticmethod
    def _focusable(widget: Widget) -> bool:
        """Whether a widget can take the focus now.

        :param widget: The widget.
        """
        return widget.is_shown and widget.can_focus()

    def screen_rect(self, widget: Widget) -> Rect:
        """A widget's rect on screen.

        :param widget: The widget.
        """
        interior, rect = self.interior, widget.rect
        return Rect(
            interior.row + rect.row - self.scroll_row,
            interior.column + rect.column - self.scroll_column,
            rect.height,
            rect.width,
        )

    def widget(self, name: str) -> Widget:
        """The widget with a name.

        :param name: The widget's name.
        """
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
        """Focus a widget.

        :param widget: The widget.
        :param reveal: Whether to scroll it into view.
        """
        if widget in self.widgets and self._focusable(widget):
            before, self._focus = self._focus, widget
            if before is not widget:
                if before is not None:
                    before.focus_changed(False)
                widget.focus_changed(True)
            if reveal:
                self.scroll_into_view(widget.rect)

    def focus_next(self, step: int = 1) -> None:
        """Move the focus.

        :param step: 1 for next, -1 for previous.
        """
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
        """Called after a button is pressed.

        :param button: The button.
        """

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Offer a key to the widgets; return whether used.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
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
        """Move the focus with Tab.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
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
        """Press the focused or default button.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        :param focused: The focused widget, if any.
        """
        if not shortcuts.matches("press_button", key):
            return False
        target = focused if isinstance(focused, Button) else self.default_button
        if target is None:
            return False
        target.press_with_key(key, held=target is focused)
        return True

    context_menu: "Menu | None" = None
    """The window's right-click menu, if any."""

    def _pop_up(self, menu: Menu | None, row: int, column: int) -> bool:
        """Pop up a menu, if any.

        :param menu: The menu, if any.
        :param row: Screen row.
        :param column: Screen column.
        """
        manager = self.manager
        if menu is None or manager is None or not menu.items:
            return False
        manager.context_menu(menu, row, column)
        return True

    def _pop_up_for_key(self, shortcuts: Shortcuts) -> bool:
        """Pop up a menu for Shift+F10.

        :param shortcuts: Key bindings in effect.
        """
        focused = self._focus
        if focused is not None and (menu := focused.popup_menu(shortcuts)):
            at = self.screen_rect(focused)
            return self._pop_up(menu, at.row + 1, at.column)
        interior = self.interior
        return self._pop_up(self.context_menu, interior.row, interior.column)

    def _pop_up_for_click(self, event: MouseEvent, row: int, column: int) -> bool:
        """Pop up a menu for a right-click.

        :param event: The mouse event.
        :param row: Content row.
        :param column: Content column.
        """
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
        """Handle window-wide keys.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        if shortcuts.matches("context_menu", key) and self._pop_up_for_key(shortcuts):
            return True  # Shift+F10, for the focused widget or the window
        shown = self.shown_widgets
        first = [] if self._focus is None else owners(self._focus)
        for widget in first + [widget for widget in shown if widget not in first]:
            if widget.is_shown and widget.window_key(key, shortcuts):
                return True
        return False

    def handle_key_release(self, key: str) -> None:
        """Tell every widget a key was released.

        :param key: The key.
        """
        for widget in self.widgets:
            widget.handle_key_release(key, widget is self._focus)

    def _scroll_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Scroll with the arrow and page keys.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
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
        """Offer pasted text to the focused widget.

        :param text: The pasted text.
        """
        return self._focus is not None and self._focus.handle_paste(text)

    def handle_mouse(self, event: MouseEvent) -> bool:
        """Offer a mouse event to the widgets.

        :param event: The mouse event.
        """
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
        """Offer a press or wheel notch at a position.

        :param event: The mouse event.
        :param row: Content row.
        :param column: Content column.
        """
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
        """The content's (width, height)."""
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
        """Scroll to a position.

        :param row: First content row.
        :param column: First content column.
        """
        max_row, max_column = self.max_scroll
        self.scroll_row = min(max(row, 0), max_row)
        self.scroll_column = min(max(column, 0), max_column)

    def scroll_by(self, rows: int, columns: int) -> None:
        """Scroll by an amount.

        :param rows: Rows down; negative is up.
        :param columns: Columns right; negative is left.
        """
        self.scroll_to(self.scroll_row + rows, self.scroll_column + columns)

    def scroll_into_view(self, rect: Rect) -> None:
        """Scroll a rect into view.

        :param rect: Rect in content coordinates.
        """
        interior = self.interior
        self.scroll_to(
            _into_view(self.scroll_row, interior.height, rect.row, rect.bottom),
            _into_view(self.scroll_column, interior.width, rect.column, rect.right),
        )

    def footer_parts(self) -> list[str]:
        """The footer's parts."""
        return list(self.footer)

    @staticmethod
    def footer_width(parts: list[str]) -> int:
        """Cells the footer parts take.

        :param parts: The parts.
        """
        return sum(len(part) for part in parts) + 3 * max(0, len(parts) - 1)

    @property
    def shown_footer(self) -> list[str]:
        """The footer parts shown."""
        parts = [part for part in self.footer_parts() if part]
        if not parts:
            return []
        width, _ = self.content_size
        scrolls = width > self.interior.width and self.rect.width - 4 >= 2
        room = self.rect.width - (9 if scrolls else 7)
        return parts if self.footer_width(parts) <= room else []

    @property
    def scroll_bars(self) -> tuple[ScrollBarLayout | None, ScrollBarLayout | None]:
        """The (vertical, horizontal) scroll bars, or ``None`` each."""
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
        """The scroll bar and part at a position.

        :param row: Screen row.
        :param column: Screen column.
        """
        for scroll_bar in self.scroll_bars:
            if scroll_bar is not None:
                part = scroll_bar.part_at(row, column)
                if part is not None:
                    return scroll_bar, part
        return None

    def press_scroll_bar(self, scroll_bar: ScrollBarLayout, part: str) -> None:
        """Scroll for a scroll bar click.

        :param scroll_bar: The scroll bar.
        :param part: The part clicked.
        """
        step = scroll_bar.step(part, self.scroll_step)
        if scroll_bar.vertical:
            self.scroll_by(step, 0)
        else:
            self.scroll_by(0, step)

    def theme_changed(self) -> None:
        """Called when the theme changes."""

    def request_close(self) -> bool:
        """Whether the window may close."""
        return True

    @property
    def title_buttons(self) -> list[tuple[str, Rect]]:
        """Title bar buttons, as ``(action, cells)`` pairs."""
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
        """The title bar button action at a position, if any.

        :param row: Screen row.
        :param column: Screen column.
        """
        for action, cells in self.title_buttons:
            if cells.contains(row, column):
                return action
        return None

    def resize(self, width: int, height: int) -> None:
        """Resize the window.

        :param width: New width.
        :param height: New height.
        """
        width = max(width, self.min_width, 2)
        height = max(height, self.min_height, 2)
        self.rect = Rect(self.rect.row, self.rect.column, height, width)

    @property
    def shadow_rects(self) -> tuple[Rect, Rect]:
        """The drop shadow's rects."""
        return shadow_rects(self.rect, self.shadow_width, self.shadow_height)

    def paint(self, canvas: Canvas, active: bool) -> None:
        """Paint the whole window.

        :param canvas: Canvas to draw on.
        :param active: Whether it is drawn active.
        """
        self.paint_shadow(canvas)
        canvas.fill(self.rect, " ", self.body_style)
        self.paint_frame(canvas, active)
        self.paint_content(canvas)
        self.paint_widgets(canvas, active)

    def render_interior(self, active: bool) -> Canvas:
        """The window's interior on its own canvas.

        :param active: Whether it is drawn active.
        """
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
        """Paint the window mid-animation.

        :param canvas: Canvas to draw on.
        :param rect: Frame position.
        :param inside: The interior when the animation began.
        :param bars: Which (vertical, horizontal) bars to draw.
        """
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
        """Darken under the drop shadow.

        :param canvas: Canvas to draw on.
        """
        if self.shadow_style is not None:
            canvas.cast_shadow(
                self.rect, self.shadow_style, self.shadow_width, self.shadow_height
            )

    def paint_frame(
        self, canvas: Canvas, active: bool, bars: tuple[bool, bool] = (True, True)
    ) -> None:
        """Paint the frame and title.

        :param canvas: Canvas to draw on.
        :param active: Whether it is drawn active.
        :param bars: Which (vertical, horizontal) bars may show.
        """
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
        """The title's column and text, or ``None``.

        :param buttons: The title bar buttons.
        """
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
        """Paint the title and buttons.

        :param canvas: Canvas to draw on.
        :param active: Whether it is drawn active.
        :param style: Frame style.
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
        """Paint the lines of text.

        :param canvas: Canvas to draw on.
        """
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
        """Paint the widgets.

        :param canvas: Canvas to draw on.
        :param active: Whether it is drawn active.
        """
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
