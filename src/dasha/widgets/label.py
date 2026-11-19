"""Labels, which are lines of static text, and the drawing of a widget's
own label, which switches and collapsible areas share."""

from dataclasses import replace

from dasha.canvas import Canvas, Rect
from dasha.menu import split_mnemonic
from dasha.style import Style
from dasha.widgets.base import Widget


def on_window(own: Style, body: Style) -> Style:
    """A widget's own style, with anything it leaves out taken from its
    window's colours (``body``). A colour it leaves as ``None`` takes the
    window's colour. The result is bold if either is bold, and underlined
    only if the widget's own style is; reverse video in the widget's own
    style reverses the window's, so a widget on a reversed window is shown
    the right way round."""
    return Style(
        foreground=own.foreground if own.foreground is not None else body.foreground,
        background=own.background if own.background is not None else body.background,
        bold=own.bold or body.bold,
        underline=own.underline,
        reverse=own.reverse != body.reverse,
    )


def focus_style(body: Style, focused: bool) -> Style:
    """The style of a widget's label: its window's colours (``body``),
    reversed while the widget has the focus, so that the focus shows up on
    any window's colours."""
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
    """Draw ``label`` (with ``&`` marking its mnemonic letter) at ``at`` on
    the screen, cut to ``width`` if given. The mnemonic letter is drawn in
    ``letter_style`` if that is given (a colour of its own), and otherwise
    underlined, unless ``underline`` is false (for a disabled widget, for
    example)."""
    text, letter = split_mnemonic(label)
    if width is not None:
        text = text[: max(0, width)]
    row, column = at
    canvas.write(row, column, text, style, clip=origin)
    if underline and letter is not None and letter < len(text):
        marked = letter_style or replace(style, underline=True)
        canvas.write(row, column + letter, text[letter], marked, clip=origin)


class Label(Widget):
    """A line of static text, in the window's colours. Its ``value`` is its
    text, and setting ``text`` resizes the label to fit."""

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
