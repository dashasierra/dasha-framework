"""Modal dialog boxes."""

from collections.abc import Sequence

from dasha.canvas import Canvas, Rect
from dasha.style import (
    BLACK,
    BLUE,
    BRIGHT_WHITE,
    BRIGHT_GREEN,
    BRIGHT_BLUE,
    BRIGHT_YELLOW,
    Style,
)
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
    """A modal window that ends with a result.

    :param title: Title text.
    :param width: Width in columns.
    :param height: Height in rows.
    :param status: Status bar text.
    """

    frame_style = Style(foreground=BRIGHT_WHITE, background=BRIGHT_BLUE, bold=True)
    inactive_frame_style = Style(foreground=BLACK, background=BRIGHT_BLUE)
    adjusting_frame_style = Style(
        foreground=BRIGHT_GREEN, background=BRIGHT_BLUE, bold=True
    )
    body_style = Style(foreground=BRIGHT_YELLOW, background=BRIGHT_BLUE)
    button_style = Style(foreground=BRIGHT_GREEN, background=BRIGHT_BLUE, bold=True)
    scrollbar_style = Style(foreground=BLUE, background=BRIGHT_BLUE)
    plain_mnemonics = True  # in a dialog, O alone presses "&OK"

    cancel_result: str = "cancel"
    """The answer that ``execute`` returns when the dialog is cancelled."""
    centred: bool = True
    """Whether ``execute`` centres the dialog."""
    takes_every_key: bool = False
    """Whether every key goes to the dialog."""

    def __init__(
        self, title: str, width: int, height: int, *, status: str = ""
    ) -> None:
        super().__init__(title, Rect(0, 0, height, width), status=status, closable=True)
        self.result: str | None = None
        """The answer, once the dialog has been answered; ``None`` before."""

    def button_pressed(self, button: Widget) -> None:
        """Answer with the pressed button's result.

        :param button: The button pressed.
        """
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
        """Centre the dialog in an area.

        :param area: The area.
        """
        self.move_to(
            area.row + max(0, (area.height - self.rect.height) // 2),
            area.column + max(0, (area.width - self.rect.width) // 2),
        )


class Popup(Dialog):
    """A dialog that drops down next to something."""

    centred = False
    close_on_outside_click = True
    border = SINGLE


class ListPopup(Popup):
    """A drop-down list to choose one item from.

    :param items: The items.
    :param selected: Index of the initial item.
    :param width: Width in columns.
    :param rows: Most rows shown.
    """

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
        """The highlighted item."""
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
        """Choose the item clicked.

        :param event: The mouse event.
        """
        used = super().handle_mouse(event)
        if event.action == "press" and event.button == "left":
            interior = self.interior
            row = event.row - interior.row + self.scroll_row - self.list.rect.row
            column = event.column - interior.column + self.scroll_column
            if self.list.index_at(row, column - self.list.rect.column) is not None:
                self.result = "ok"
        return used


class _BoxView(Widget):
    """An autocomplete box drawn inside its popup.

    :param box: The autocomplete box.
    :param row: Row in the popup.
    """

    focusable = True

    def __init__(self, box: AutoCompleteBox, row: int) -> None:
        super().__init__(row, 0, box.rect.width)
        self.box = box

    def _shift(self, row: int, column: int) -> tuple[int, int]:
        """A position in the box's own window.

        :param row: Row here.
        :param column: Column here.
        """
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
    """The suggestions list in a popup.

    :param items: The suggestions.
    :param row: Row in the popup.
    :param width: Width in columns.
    :param rows: Most rows shown.
    """

    def __init__(self, items: list[str], row: int, width: int, rows: int) -> None:
        super().__init__(row, 0, width, rows)
        self.items = items
        self.highlight = -1
        self.first = 0
        """The first item shown, when there are more than fit."""
        self.chosen = False
        """Whether a click has chosen the highlighted item."""

    def set_items(self, items: list[str], rows: int) -> None:
        """Show other suggestions.

        :param items: The suggestions.
        :param rows: Most rows shown.
        """
        current = self.items[self.highlight] if self.highlight >= 0 else None
        self.items = items
        self.rect = Rect(self.rect.row, 0, rows, self.rect.width)
        self.highlight = items.index(current) if current in items else -1
        self.first = 0
        self.move(0)

    def move(self, step: int) -> None:
        """Move the highlight.

        :param step: Items to move by.
        """
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
        """Choose or scroll with the mouse.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
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
    """An autocomplete box's suggestions popup.

    :param box: The autocomplete box.
    :param items: The suggestions.
    :param rows: Most rows shown.
    :param above: Whether it opens above the box.
    """

    def __init__(
        self, box: AutoCompleteBox, items: list[str], rows: int, above: bool
    ) -> None:
        super().__init__("", box.rect.width + 2, rows + 3)
        self.closable = False
        self.box = box
        self.above = above
        self.max_rows = rows
        """Most suggestions shown at once."""
        self.passed_key: str | None = None
        """A key that closed the popup, to pass on."""
        self.view = self.add(_BoxView(box, rows if above else 0))
        self.list = self.add(
            _SuggestionList(items, 0 if above else 1, box.rect.width, rows)
        )

    @property
    def chosen(self) -> str | None:
        """The highlighted suggestion."""
        highlight = self.list.highlight
        return self.list.items[highlight] if highlight >= 0 else None

    def refresh(self) -> None:
        """Update the suggestions for the box's text."""
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
        """Close and pass a key to the box's window.

        :param key: The key.
        """
        self.passed_key = key
        self.cancel()

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Move, take or type.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
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
    """A menu's items in a popup.

    :param menu: The menu.
    :param width: Width in columns.
    """

    focusable = True

    def __init__(self, menu: Menu, width: int) -> None:
        super().__init__(0, 0, width, max(1, len(menu.items)))
        self.menu = menu
        self.highlight = -1
        self.move(1)

    def move(self, step: int) -> None:
        """Highlight the next choosable item.

        :param step: 1 for next, -1 for previous.
        """
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
        """An item's style and letter style.

        :param number: Item index.
        :param item: The item.
        """
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
        """The choosable item at a row, if any.

        :param row: Content row.
        """
        index = row - self.rect.row
        items = self.menu.items
        return index if 0 <= index < len(items) and items[index].is_available else None


class MenuPopup(Popup):
    """A pop-up menu, such as a context menu.

    :param menu: The menu.
    :param submenu: Whether it is a submenu.
    """

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
        """Choose an item or open its submenu.

        :param index: Item index.
        """
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
        """Show a submenu beside an item.

        :param index: Item index.
        :param menu: The submenu.
        """
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
        """Choose the item clicked.

        :param event: The mouse event.
        """
        interior = self.interior
        if event.action == "press" and interior.contains(event.row, event.column):
            index = self.items.item_at(event.row - interior.row)
            if index is not None:
                self.choose(index)
        return event.action in ("press", "release", "drag")


def _place_in_row(buttons: list[Button], row: int, width: int, gap: int = 2) -> None:
    """Centre buttons on one row.

    :param buttons: The buttons.
    :param row: The row.
    :param width: Interior width.
    :param gap: Columns between buttons.
    """
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
    """A message dialog with buttons.

    :param title: Title text.
    :param message: The message.
    :param buttons: The buttons.
    :param status: Status bar text.
    :param align: Message alignment.
    """
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
    """An OK/Cancel dialog.

    :param title: Title text.
    :param message: The message.
    :param ok_label: OK button label.
    :param cancel_label: Cancel button label.
    :param status: Status bar text.
    :param align: Message alignment.
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
    """A dialog with a button per answer.

    :param title: Title text.
    :param message: The message.
    :param answers: (label, result) pairs; the first is the default.
    :param status: Status bar text.
    :param align: Message alignment.
    """
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
    """A message dialog with an OK button.

    :param title: Title text.
    :param message: The message.
    :param ok_label: OK button label.
    :param status: Status bar text.
    :param align: Message alignment.
    """
    buttons = [Button(ok_label, 0, 0, result="ok", default=True, name="ok")]
    return _message_dialog(title, message, buttons, status, align)
