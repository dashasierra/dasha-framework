"""Labels and mnemonic label drawing."""

from dataclasses import replace

from dasha.canvas import Canvas, Rect
from dasha.menu import split_mnemonic
from dasha.style import Style
from dasha.widgets.base import Widget


def on_window(own: Style, body: Style) -> Style:
    """A widget style filled in from its window's.

    :param own: The widget's style.
    :param body: The window's style.
    """
    return Style(
        foreground=own.foreground if own.foreground is not None else body.foreground,
        background=own.background if own.background is not None else body.background,
        bold=own.bold or body.bold,
        underline=own.underline,
        reverse=own.reverse != body.reverse,
    )


def focus_style(body: Style, focused: bool) -> Style:
    """A label style, reversed while focused.

    :param body: The window's style.
    :param focused: Whether the widget has the focus.
    """
    return Style(
        foreground=body.foreground,
        background=body.background,
        bold=body.bold,
        reverse=focused != body.reverse,
    )


def paint_mnemonic_label(  # pylint: disable=too-many-arguments
    canvas: Canvas,
    origin: Rect,
    at: tuple[int, int],
    label: str,
    style: Style,
    *,
    width: int | None = None,
    underline: bool = True,
    letter_style: Style | None = None,
) -> None:
    """Draw a label with its mnemonic letter.

    :param canvas: Canvas to draw on.
    :param origin: The window's interior on screen.
    :param at: Screen row and column.
    :param label: Label text; ``&`` marks the mnemonic.
    :param style: Label style.
    :param width: Width to cut to, if any.
    :param underline: Whether to underline the mnemonic.
    :param letter_style: Mnemonic letter style, if any.
    """
    text, letter = split_mnemonic(label)
    if width is not None:
        text = text[: max(0, width)]
    row, column = at
    canvas.write(row, column, text, style, clip=origin)
    if underline and letter is not None and letter < len(text):
        marked = letter_style or replace(style, underline=True)
        canvas.write(row, column + letter, text[letter], marked, clip=origin)


class Label(Widget):
    """A line of static text.

    :param text: The text.
    :param row: Row in the window.
    :param column: Column in the window.
    :param name: Widget name.
    :param style: Style, or ``None`` for the window's.
    """

    def __init__(
        self,
        text: str,
        row: int,
        column: int,
        *,
        name: str | None = None,
        style: Style | None = None,
    ) -> None:
        super().__init__(row, column, len(text), name=name)
        self._text = text
        self.style = style
        """Colours for the text; ``None`` uses the window's body colours."""

    @property
    def text(self) -> str:
        """The text shown. Setting it resizes the label to fit."""
        return self._text

    @text.setter
    def text(self, text: str) -> None:
        self._text = text
        self.rect = Rect(self.rect.row, self.rect.column, 1, len(text))

    @property
    def value(self) -> str:
        return self.text

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        style = self.style
        if style is None:
            style = self.window.body_style if self.window is not None else Style()
        canvas.write(
            origin.row + self.rect.row,
            origin.column + self.rect.column,
            self.text,
            style,
            clip=origin,
        )
