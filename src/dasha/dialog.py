"""Dialog boxes: modal windows that must be answered before anything else
can be done.

A dialog is shown with ``PresentationManager.execute(dialog)``. That call
puts the dialog on top, lets nothing but the dialog respond until it has
been answered, and returns the answer: the ``result`` of the button pressed
(``"ok"``, ``"cancel"``, or any other result a button was given), or
``Dialog.cancel_result`` if the dialog was cancelled with Escape or its
close button. The dialog itself can still be read afterwards, so the caller
can look at every widget in it (``dialog.widget(name)``, ``dialog.values``)
to decide what to do::

    dialog = confirm("Delete", "Delete notes.txt?")
    if manager.execute(dialog) == "ok":
        delete("notes.txt")
"""

from collections.abc import Sequence

from dasha.canvas import Canvas, Rect
from dasha.style import BLACK, BLUE, BRIGHT_GREEN, BRIGHT_WHITE, WHITE, Style
from dasha.border import SINGLE
from dasha.events import MouseEvent
from dasha.menu import Menu, MenuBar, MenuItem, split_mnemonic, unique_mnemonics
from dasha.shortcuts import Shortcuts
from dasha.widgets import AutoCompleteBox, Button, Label, ListBox, Widget

# Lines a message up. Re-exported (as mypy wants it said), where it was first:
from dasha.widgets.paragraph import (  # pylint: disable=useless-import-alias
    align_lines as align_lines,
)
from dasha.window import Window

LINE = SINGLE.horizontal
"""``─``, used to draw a separator in a pop-up menu."""


class Dialog(Window):
    """A modal window, grey by default, that ends with a result."""

    frame_style = Style(foreground=BRIGHT_WHITE, background=WHITE, bold=True)
    inactive_frame_style = Style(foreground=BLACK, background=WHITE)
    adjusting_frame_style = Style(foreground=BRIGHT_GREEN, background=WHITE, bold=True)
    body_style = Style(foreground=BLACK, background=WHITE)
    button_style = Style(foreground=BRIGHT_GREEN, background=WHITE, bold=True)
    scrollbar_style = Style(foreground=BLUE, background=WHITE)
    plain_mnemonics = True  # in a dialog, O alone presses "&OK"

    cancel_result: str = "cancel"
    """The answer that ``execute`` returns when the dialog is cancelled."""
    centred: bool = True
    """Whether ``execute`` puts the dialog in the middle of the work area. A
    popup placed next to something turns this off."""
    takes_every_key: bool = False
    """Whether every key goes to the dialog, even those the desktop would
    otherwise take wherever the focus is (such as ``show_mouse``)."""

    def __init__(
        self, title: str, width: int, height: int, *, status: str = ""
    ) -> None:
        super().__init__(title, Rect(0, 0, height, width), status=status, closable=True)
        self.result: str | None = None
        """The answer, once the dialog has been answered; ``None`` before."""

    def button_pressed(self, button: Widget) -> None:
        """Answer the dialog with the result of the button pressed, if the
        button has one."""
        if isinstance(button, Button) and button.result is not None:
            self.result = button.result

    def cancel(self) -> None:
        """Answer the dialog with ``cancel_result``."""
        self.result = self.cancel_result

    def request_close(self) -> bool:
        """Closing a dialog (with its ``[■]`` button) cancels it."""
        self.cancel()
        return False  # execute() takes it off the screen

    def centre(self, area: Rect) -> None:
        """Move the dialog to the middle of ``area``."""
        self.move_to(
            area.row + max(0, (area.height - self.rect.height) // 2),
            area.column + max(0, (area.width - self.rect.width) // 2),
        )


class Popup(Dialog):
    """A dialog that drops down next to something, such as a drop-down
    list. It is framed in single lines, and a click outside it cancels it.
    The desktop frames popups from applications in the same way."""

    centred = False
    close_on_outside_click = True
    border = SINGLE


class ListPopup(Popup):
    """A list that drops down next to something (such as a combo box's
    field), from which to choose one item. Enter, or a click on an item,
    chooses it and answers ``"ok"``; Escape, or a click outside the list,
    cancels it. ``chosen`` is then the index of the chosen item.
    ``PresentationManager.pick`` shows these lists."""

    def __init__(self, items: list[str], selected: int, width: int, rows: int) -> None:
        super().__init__("", width, rows + 2)
        self.closable = False
        self.list = self.add(
            ListBox(
                items, 0, 0, width - 2, rows, selected=selected, on_choose=self._chosen
            )
        )

    @property
    def chosen(self) -> int | None:
        """The highlighted item (which is the chosen one, once the answer is
        ``"ok"``)."""
        return self.list.value if isinstance(self.list.value, int) else None

    def _chosen(self, box: ListBox) -> None:
        del box
        self.result = "ok"

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        if shortcuts.matches("menu_choose", key):
            self.result = "ok"
            return True
        return super().handle_key(key, shortcuts)

    def handle_mouse(self, event: MouseEvent) -> bool:
        """A press on an item chooses it (while a press on the scroll bar only
        scrolls)."""
        used = super().handle_mouse(event)
        if event.action == "press" and event.button == "left":
            interior = self.interior
            row = event.row - interior.row + self.scroll_row - self.list.rect.row
            column = event.column - interior.column + self.scroll_column
            if self.list.index_at(row, column - self.list.rect.column) is not None:
                self.result = "ok"
        return used


class _BoxView(Widget):
    """An autocomplete box shown (and typed in) inside its suggestions'
    popup, which covers it: it draws the box, with the cursor, and passes
    the mouse on to it."""

    focusable = True

    def __init__(self, box: AutoCompleteBox, row: int) -> None:
        super().__init__(row, 0, box.rect.width)
        self.box = box

    def _shift(self, row: int, column: int) -> tuple[int, int]:
        """A position here, as one in the box's own window."""
        box = self.box.rect
        return row - self.rect.row + box.row, column - self.rect.column + box.column

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        # The box draws at its own place: move the origin so that is here.
        box = self.box.rect
        shifted = Rect(
            origin.row + self.rect.row - box.row,
            origin.column + self.rect.column - box.column,
            box.bottom,
            box.right,
        )
        self.box.paint(canvas, shifted, focused)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        return self.box.handle_mouse(event, *self._shift(row, column))

    def wake_time(self) -> float | None:
        return self.box.wake_time()

    def on_timer(self, now: float) -> None:
        self.box.on_timer(now)


class _SuggestionList(Widget):
    """The suggestions under (or over) an autocomplete box, one a row, with
    one highlighted (or none, ``highlight`` -1) in the list box's colours."""

    def __init__(self, items: list[str], row: int, width: int, rows: int) -> None:
        super().__init__(row, 0, width, rows)
        self.items = items
        self.highlight = -1
        self.first = 0
        """The first item shown, when there are more than fit."""
        self.chosen = False
        """Whether a click has chosen the highlighted item."""

    def set_items(self, items: list[str], rows: int) -> None:
        """Show other items, keeping the highlighted one if it is still there."""
        current = self.items[self.highlight] if self.highlight >= 0 else None
        self.items = items
        self.rect = Rect(self.rect.row, 0, rows, self.rect.width)
        self.highlight = items.index(current) if current in items else -1
        self.first = 0
        self.move(0)

    def move(self, step: int) -> None:
        """Highlight the item ``step`` on (or back: from the first, back to
        none), keeping it in view."""
        self.highlight = max(-1, min(self.highlight + step, len(self.items) - 1))
        rows = self.rect.height
        if 0 <= self.highlight < self.first:
            self.first = self.highlight
        elif self.highlight >= self.first + rows:
            self.first = self.highlight - rows + 1

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        del focused
        width = self.rect.width
        for offset in range(self.rect.height):
            index = self.first + offset
            text = self.items[index] if index < len(self.items) else ""
            style = ListBox.focused_style if index == self.highlight else ListBox.style
            canvas.write(
                origin.row + self.rect.row + offset,
                origin.column + self.rect.column,
                f" {text}"[:width].ljust(width),
                style,
                clip=origin,
            )

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """A press on an item chooses it; the wheel moves the highlight."""
        del column
        if event.action == "scroll":
            self.move(1 if event.button == "down" else -1)
            return True
        if event.button != "left":
            return False
        index = self.first + row - self.rect.row
        if event.action == "press" and 0 <= index < len(self.items):
            self.highlight, self.chosen = index, True
        return event.action in ("press", "drag", "release")


class SuggestionPopup(Popup):
    """An autocomplete box's suggestions, dropped down below the box (or
    above it, with ``above``, near the bottom of the screen). The popup
    covers the box, with a row lined up over the box itself, so that typing
    carries on there while the suggestions follow it.

    Down and Up (``suggest_down``, ``suggest_up``) move through the
    suggestions, and Enter (``suggest_choose``) or a click takes the
    highlighted one. When none is highlighted, Enter is passed on to the
    window (to press its default button, for example), as Tab is; Escape, or
    a click outside, just closes the popup. ``PresentationManager.suggest``
    shows these popups.
    """

    def __init__(
        self, box: AutoCompleteBox, items: list[str], rows: int, above: bool
    ) -> None:
        super().__init__("", box.rect.width + 2, rows + 3)
        self.closable = False
        self.box = box
        self.above = above
        self.max_rows = rows
        """The most suggestions shown at once (as many as there is room for)."""
        self.passed_key: str | None = None
        """A key that closed the popup, to go on to the box's window."""
        self.view = self.add(_BoxView(box, rows if above else 0))
        self.list = self.add(
            _SuggestionList(items, 0 if above else 1, box.rect.width, rows)
        )

    @property
    def chosen(self) -> str | None:
        """The highlighted suggestion (which is the one taken, once the answer is
        ``"ok"``)."""
        highlight = self.list.highlight
        return self.list.items[highlight] if highlight >= 0 else None

    def refresh(self) -> None:
        """Handle a change to the box's text: show the suggestions that match
        it now, and close if none do."""
        items = self.box.matches()
        if not items:
            self.cancel()
            return
        rows = min(len(items), self.max_rows)
        bottom = self.rect.bottom
        self.resize(self.rect.width, rows + 3)
        if self.above:  # the box stays put, so the popup grows upwards
            self.move_to(bottom - self.rect.height, self.rect.column)
            self.view.rect = Rect(rows, 0, 1, self.view.rect.width)
        self.list.set_items(items, rows)

    def pass_on(self, key: str) -> None:
        """Close, and pass the key on to the box's window."""
        self.passed_key = key
        self.cancel()

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Move through the suggestions, take one, or type into the box."""
        if shortcuts.matches("suggest_down", key):
            self.list.move(1)
        elif shortcuts.matches("suggest_up", key):
            self.list.move(-1)
        elif shortcuts.matches("suggest_choose", key) and self.chosen is not None:
            self.result = "ok"
        elif any(
            shortcuts.matches(action, key)
            for action in ("suggest_choose", "next_widget", "previous_widget")
        ):
            self.pass_on(key)
        elif shortcuts.matches("dialog_cancel", key):
            self.cancel()
        else:
            before = self.box.text
            used = self.box.handle_key(key, shortcuts)
            if self.box.text != before:
                self.refresh()
            return used
        return True

    def handle_paste(self, text: str) -> bool:
        used = self.box.handle_paste(text)
        if used:
            self.refresh()
        return used

    def handle_mouse(self, event: MouseEvent) -> bool:
        used = super().handle_mouse(event)
        if self.list.chosen:
            self.result = "ok"
        return used


class _MenuItems(Widget):
    """A menu's items, one a row, in the menu bar's colours: labels with
    their letters, shortcuts on the right, ``►`` for a submenu, ``─`` for a
    separator, greyed out where they cannot be chosen."""

    focusable = True

    def __init__(self, menu: Menu, width: int) -> None:
        super().__init__(0, 0, width, max(1, len(menu.items)))
        self.menu = menu
        self.highlight = -1
        self.move(1)

    def move(self, step: int) -> None:
        """Highlight the next item (or previous: ``step`` -1) that can be
        chosen, round the ends."""
        items = self.menu.items
        if not any(item.is_available for item in items):
            self.highlight = -1
            return
        index = self.highlight
        for _ in range(len(items)):
            index = (index + step) % len(items)
            if items[index].is_available:
                self.highlight = index
                return

    def _styles(self, number: int, item: MenuItem) -> tuple[Style, Style]:
        """An item's colours, and its letter's: greyed out where it cannot
        be chosen, lit where highlighted, as in the menu bar's menus."""
        if not item.is_available:
            return MenuBar.disabled_style, MenuBar.disabled_style
        if number == self.highlight:
            return MenuBar.selected_style, MenuBar.selected_mnemonic_style
        return MenuBar.bar_style, MenuBar.mnemonic_style

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        del focused
        width = self.rect.width
        items = self.menu.items
        for number, (item, letter) in enumerate(
            zip(items, unique_mnemonics(item.label for item in items))
        ):
            row = origin.row + self.rect.row + number
            column = origin.column + self.rect.column
            if item.is_separator:
                canvas.write(row, column, LINE * width, MenuBar.bar_style, clip=origin)
                continue
            style, mnemonic = self._styles(number, item)
            text = split_mnemonic(item.label)[0]
            right = (
                "\N{BLACK RIGHT-POINTING POINTER}" if item.submenu else item.shortcut
            )
            line = f" {text}".ljust(width - len(right) - 1) + right + " "
            canvas.write(row, column, line[:width], style, clip=origin)
            if letter is not None and item.is_available:
                canvas.write(
                    row, column + 1 + letter, text[letter], mnemonic, clip=origin
                )

    def item_at(self, row: int) -> int | None:
        """The item at a row of the content, if one can be chosen there."""
        index = row - self.rect.row
        items = self.menu.items
        return index if 0 <= index < len(items) and items[index].is_available else None


class MenuPopup(Popup):
    """A menu that pops up next to something, such as a widget's context
    menu, opened with a right-click or Shift+F10. Down and Up
    (``menu_down``, ``menu_up``) move through the items that can be chosen.
    Enter (``menu_choose``), an item's letter or a click on an item chooses
    it, and Right (``menu_right``) opens a submenu beside it. Escape, Left
    in a submenu, or a click outside closes the menu. ``chosen`` is then the
    chosen item, if any. ``PresentationManager.context_menu`` shows these
    menus, and runs the chosen item once the menu has closed."""

    def __init__(self, menu: Menu, *, submenu: bool = False) -> None:
        items = menu.items
        label_width = max(
            (len(split_mnemonic(item.label)[0]) for item in items), default=0
        )
        right = max(
            (1 if item.submenu else len(item.shortcut) for item in items), default=0
        )
        width = max(8, label_width + (right + 2 if right else 0) + 2)
        super().__init__("", width + 2, max(1, len(items)) + 2)
        self.closable = False
        self.body_style = MenuBar.bar_style
        self.menu = menu
        self.submenu = submenu
        """Whether it is a submenu, opened from another."""
        self.chosen: MenuItem | None = None
        """The item chosen, once answered ``"ok"``."""
        self.items = self.add(_MenuItems(menu, width))

    def theme_changed(self) -> None:
        """Take on the menu bar's colours from the current theme."""
        self.body_style = MenuBar.bar_style

    @property
    def status(self) -> str:
        """The highlighted item's help text, for the status bar."""
        highlight = self.items.highlight
        return self.menu.items[highlight].status if highlight >= 0 else ""

    @status.setter
    def status(self, status: str) -> None:
        del status  # always the highlighted item's

    def choose(self, index: int) -> None:
        """Choose an item: open its submenu, or make it the answer."""
        item = self.menu.items[index]
        if not item.is_available:
            return
        self.items.highlight = index
        if item.submenu is not None:
            self._open_submenu(index, item.submenu)
            return
        self.chosen = item
        self.result = "ok"

    def _open_submenu(self, index: int, menu: Menu) -> None:
        """Show a submenu beside the item; what it chooses is the answer."""
        manager = self.manager
        if manager is None:
            return
        popup = MenuPopup(menu, submenu=True)
        manager.place_popup(popup, self.rect.row + index, self.rect.right - 1)
        if manager.execute(popup) == "ok" and popup.chosen is not None:
            self.chosen = popup.chosen
            self.result = "ok"

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        items, highlight = self.menu.items, self.items.highlight
        if shortcuts.matches("menu_down", key):
            self.items.move(1)
        elif shortcuts.matches("menu_up", key):
            self.items.move(-1)
        elif shortcuts.matches("menu_choose", key) and highlight >= 0:
            self.choose(highlight)
        elif (
            shortcuts.matches("menu_right", key)
            and highlight >= 0
            and items[highlight].submenu is not None
        ):
            self.choose(highlight)
        elif shortcuts.matches("menu_left", key) and self.submenu:
            self.cancel()
        elif shortcuts.matches("menu_close", key):
            self.cancel()
        elif (letter := key.casefold() if len(key) == 1 else None) is not None:
            for index, mnemonic in enumerate(self.menu.mnemonics()):
                if mnemonic == letter and items[index].is_available:
                    self.choose(index)
                    break
        else:
            return False
        return True

    def handle_mouse(self, event: MouseEvent) -> bool:
        """A click on an item that can be chosen chooses it."""
        interior = self.interior
        if event.action == "press" and interior.contains(event.row, event.column):
            index = self.items.item_at(event.row - interior.row)
            if index is not None:
                self.choose(index)
        return event.action in ("press", "release", "drag")


def _place_in_row(buttons: list[Button], row: int, width: int, gap: int = 2) -> None:
    """Centre buttons side by side on one row of an interior ``width`` wide."""
    total = sum(button.rect.width for button in buttons) + gap * (len(buttons) - 1)
    column = (width - total) // 2
    for button in buttons:
        button.rect = Rect(row, column, button.rect.height, button.rect.width)
        column += button.rect.width + gap


def _message_dialog(  # pylint: disable=too-many-arguments
    title: str,
    message: str,
    buttons: list[Button],
    status: str,
    align: str = "left",
) -> Dialog:
    """A dialog of a message, a line per ``Label`` lined up by ``align``,
    above a row of buttons."""
    lines = message.splitlines() or [""]
    buttons_width = sum(button.rect.width for button in buttons) + 2
    text_width = max(max(len(line) for line in lines), buttons_width)
    inner_width = text_width + 4
    # A blank row, the message, a blank row, the buttons and their shadow,
    # and a blank row before the frame.
    dialog = Dialog(title, inner_width + 2, len(lines) + 6, status=status)
    for number, (offset, line) in enumerate(align_lines(lines, text_width, align)):
        name = "message" if number == 0 else f"message{number + 1}"
        dialog.add(Label(line, 1 + number, 2 + offset, name=name))
    _place_in_row(buttons, len(lines) + 2, inner_width)
    for button in buttons:
        dialog.add(button)
    return dialog


def confirm(
    title: str,
    message: str,
    *,
    ok_label: str = "&OK",
    cancel_label: str = "&Cancel",
    status: str = "",
    align: str = "left",
) -> Dialog:
    """A dialog with a message, and OK and Cancel buttons.

    It answers ``"ok"`` or ``"cancel"``. OK is the default button, and
    starts with the focus. The widgets are named ``"message"`` (with one
    ``Label`` for each line: ``"message"``, ``"message2"`` and so on),
    ``"ok"`` and ``"cancel"``. ``align`` sets the alignment of the message:
    ``"left"`` (the default), ``"centre"``, ``"right"`` or ``"justify"`` (see
    ``align_lines``).
    """
    buttons = [
        Button(ok_label, 0, 0, result="ok", default=True, name="ok"),
        Button(cancel_label, 0, 0, result="cancel", name="cancel"),
    ]
    return _message_dialog(title, message, buttons, status, align)


def question(  # pylint: disable=too-many-arguments
    title: str,
    message: str,
    answers: Sequence[tuple[str, str]],
    *,
    status: str = "",
    align: str = "left",
) -> Dialog:
    """A dialog with a message and a button for each answer, with the
    answers given as (label, result) pairs: ``[("&Save", "save"),
    ("&Don't save", "discard"), ("&Cancel", "cancel")]``. The first button is
    the default, and starts with the focus; Escape answers ``"cancel"``. The
    buttons are named after their results, and ``align`` sets the alignment
    of the message, as for ``confirm``."""
    if not answers:
        raise ValueError("a question needs at least one answer")
    buttons = [
        Button(label, 0, 0, result=result, default=number == 0, name=result)
        for number, (label, result) in enumerate(answers)
    ]
    return _message_dialog(title, message, buttons, status, align)


def information(
    title: str,
    message: str,
    *,
    ok_label: str = "&OK",
    status: str = "",
    align: str = "left",
) -> Dialog:
    """A dialog with a message and only an OK button, to tell the user
    something. ``align`` sets the alignment of the message, as for
    ``confirm``.

    It answers ``"ok"``, or ``"cancel"`` if it is closed with Escape or its
    close button instead. OK is the default button, and starts with the
    focus. The widgets are named ``"message"`` (with one ``Label`` for each
    line: ``"message"``, ``"message2"`` and so on) and ``"ok"``.
    """
    buttons = [Button(ok_label, 0, 0, result="ok", default=True, name="ok")]
    return _message_dialog(title, message, buttons, status, align)
