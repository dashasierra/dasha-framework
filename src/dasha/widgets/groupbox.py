"""Group boxes."""

from dasha.border import SINGLE
from dasha.canvas import Canvas, Rect
from dasha.menu import mnemonic_key, split_mnemonic
from dasha.style import Style
from dasha.widgets.base import Widget
from dasha.widgets.container import Container
from dasha.widgets.label import on_window, paint_mnemonic_label


class GroupBox(Container, Widget):
    """A titled frame around widgets.

    :param title: Frame title; ``&`` marks the mnemonic.
    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param height: Height in rows.
    :param name: Widget name.
    """

    noun = "group box"
    style: Style = Style()
    """Frame and title style."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        title: str,
        row: int,
        column: int,
        width: int,
        height: int,
        *,
        name: str | None = None,
    ) -> None:
        if width < 2 or height < 2:
            raise ValueError("a group box needs room for its frame (2x2 at least)")
        Widget.__init__(self, row, column, width, height, name=name)
        Container.__init__(self)
        self.title = title

    @property
    def anchor(self) -> Widget:
        return self

    def content_origin(self) -> tuple[int, int]:
        return self.home_row + 1, self.rect.column + 1

    def min_size(self) -> tuple[int, int]:
        return 2, 2

    # The title's letter

    def mnemonic(self) -> str | None:
        return mnemonic_key(self.title)

    def activate(self) -> None:
        """Focus the group's first focusable widget."""
        window = self.window
        if window is None:
            return
        for widget in self.children:
            if widget.is_shown and widget.can_focus():
                window.focus(widget)
                return

    # Drawing

    def _style(self) -> Style:
        """``style``, its missing colours the window's."""
        body = self.window.body_style if self.window is not None else Style()
        return on_window(self.style, body)

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        del focused
        style = self._style()
        top = origin.row + self.rect.row
        left = origin.column + self.rect.column
        width, height = self.rect.width, self.rect.height
        inner = width - 2
        border = SINGLE
        canvas.write(
            top,
            left,
            border.top_left + border.horizontal * inner + border.top_right,
            style,
            clip=origin,
        )
        for row in range(top + 1, top + height - 1):
            canvas.write(row, left, border.vertical, style, clip=origin)
            canvas.write(row, left + width - 1, border.vertical, style, clip=origin)
        canvas.write(
            top + height - 1,
            left,
            border.bottom_left + border.horizontal * inner + border.bottom_right,
            style,
            clip=origin,
        )
        text = split_mnemonic(self.title)[0]
        if text and inner >= 3:
            room = inner - 3  # "─ " before, " " after, inside the corners
            canvas.write(top, left + 2, " ", style, clip=origin)
            paint_mnemonic_label(
                canvas, origin, (top, left + 3), self.title, style, width=room
            )
            shown = min(len(text), room)
            canvas.write(top, left + 3 + shown, " ", style, clip=origin)
