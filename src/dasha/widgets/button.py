"""Push buttons."""

from collections.abc import Callable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.menu import mnemonic_key, split_mnemonic
from dasha.style import BLACK, BRIGHT_WHITE, BRIGHT_YELLOW, GREEN, Colour, Style
from dasha.widgets.base import Widget

SHADOW_BELOW = "\N{UPPER HALF BLOCK}"
SHADOW_RIGHT = "\N{LOWER HALF BLOCK}"
"""Shadow characters (half blocks)."""

OUTLINE_TOP_RIGHT = "\N{BOX DRAWINGS LIGHT DOWN AND LEFT}"
OUTLINE_BOTTOM_LEFT = "\N{BOX DRAWINGS LIGHT UP AND RIGHT}"
OUTLINE_BOTTOM_RIGHT = "\N{BOX DRAWINGS LIGHT UP AND LEFT}"
OUTLINE_HORIZONTAL = "\N{BOX DRAWINGS LIGHT HORIZONTAL}"
"""Outline shadow characters."""

SHADOW_SHAPES = ("solid", "outline")
"""Ways to draw a button's shadow."""


class Button(Widget):
    """A push button with a shadow.

    :param label: Button text; ``&`` marks the mnemonic letter.
    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Face width, or ``None`` to fit the label.
    :param action: Called with the button when pressed.
    :param result: The dialog's answer when pressed.
    :param default: Whether Enter presses it from elsewhere.
    :param name: Widget name.
    :param status: Status bar text.
    """

    focusable = True
    face_style: Style = Style(foreground=BLACK, background=GREEN)
    """The style of the face and its label."""
    focused_style: Style = Style(foreground=BRIGHT_WHITE, background=GREEN, bold=True)
    """Face style while focused."""
    mnemonic_style: Style = Style(foreground=BRIGHT_YELLOW, background=GREEN)
    """The style of the label's mnemonic letter."""
    focused_mnemonic_style: Style = Style(
        foreground=BRIGHT_YELLOW, background=GREEN, bold=True
    )
    """The style of the mnemonic letter while the button has the focus."""
    shadow_style: Style = Style(foreground=BLACK)
    """Shadow style."""
    shadow_shape: str = "solid"
    """Shadow shape: ``"solid"`` or ``"outline"``."""
    min_width: int = 10

    def __init__(
        self,
        label: str,
        row: int,
        column: int,
        *,
        width: int | None = None,
        action: Callable[["Button"], object] | None = None,
        result: str | None = None,
        default: bool = False,
        name: str | None = None,
        status: str = "",
    ) -> None:
        text, _ = split_mnemonic(label)
        face_width = width if width is not None else max(len(text) + 4, self.min_width)
        # The face, plus a column of shadow to its right and a row below.
        super().__init__(row, column, face_width + 1, 2, name=name, status=status)
        self.label = label
        self.action = action
        self.result = result
        """What a dialog answers when this button is pressed, if anything."""
        self.default = default
        """Whether Enter presses this button when the focus is elsewhere."""
        self._pressed = False

    def min_size(self) -> tuple[int, int]:
        """Enough room for the label, and for the face and shadow rows."""
        return len(split_mnemonic(self.label)[0]) + 3, 2

    @property
    def face(self) -> Rect:
        """The face, without its shadow."""
        return Rect(self.rect.row, self.rect.column, 1, self.rect.width - 1)

    @property
    def value(self) -> str | None:
        return self.result

    def mnemonic(self) -> str | None:
        return mnemonic_key(self.label)

    def press_with_key(self, key: str, held: bool = True) -> None:
        """Handle Enter or Space.

        :param key: The key pressed.
        :param held: Whether the button has the focus.
        """
        if key == " " and held and self.key_releases:
            self._pressed = True  # until handle_key_release
            return
        self.activate()

    def handle_key_release(self, key: str, focused: bool) -> None:
        """Handle the release of Space.

        :param key: The key released.
        :param focused: Whether the button has the focus.
        """
        if key != " " or not self._pressed or not self.key_releases:
            return
        self._pressed = False
        if focused:
            self.activate()

    def activate(self) -> None:
        if self.action is not None:
            self.action(self)
        if self.window is not None:
            self.window.button_pressed(self)

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        face = self.face
        row = origin.row + face.row
        column = origin.column + face.column + (1 if self._pressed else 0)
        styles = (
            (self.focused_style, self.focused_mnemonic_style)
            if focused
            else (self.face_style, self.mnemonic_style)
        )
        text, mnemonic = split_mnemonic(self.label)
        left = (face.width - len(text)) // 2
        canvas.write(row, column, " " * face.width, styles[0], clip=origin)
        canvas.write(row, column + left, text, styles[0], clip=origin)
        if mnemonic is not None:
            canvas.write(
                row, column + left + mnemonic, text[mnemonic], styles[1], clip=origin
            )
        if not self._pressed:  # pressed, it is pushed down into its shadow
            self._paint_shadow(canvas, origin, row, column)

    def _paint_shadow(
        self, canvas: Canvas, origin: Rect, row: int, column: int
    ) -> None:
        """Draw the shadow.

        :param canvas: Canvas to draw on.
        :param origin: The window's interior on screen.
        :param row: Face row.
        :param column: Face column.
        """
        background = self.window.body_style.background if self.window else None
        paint_shadow(
            canvas,
            origin,
            (row, column, self.face.width),
            background,
            (self.shadow_style, self.shadow_shape),
        )

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Push in, press or cancel with the mouse.

        :param event: The mouse event.
        :param row: Row within the button.
        :param column: Column within the button.
        """
        if event.button != "left":
            return False
        over = self.face.contains(row, column)
        if event.action == "press" and over:
            self._pressed = True
            return True
        if event.action == "drag" and self._pressed:
            return True
        if event.action == "release" and self._pressed:
            self._pressed = False
            if over:
                self.activate()
            return True
        return False


def paint_shadow(
    canvas: Canvas,
    origin: Rect,
    face: tuple[int, int, int],
    background: Colour | None,
    looks: tuple[Style, str],
) -> None:
    """Draw a raised-looking shadow.

    :param canvas: Canvas to draw on.
    :param origin: The window's interior on screen.
    :param face: The face's row, column and width.
    :param background: The window's background colour.
    :param looks: Shadow style and shape.
    """
    row, column, width = face
    style, shape = looks
    shadow = Style(foreground=style.foreground, background=background, bold=style.bold)
    if shape == "outline":
        #  OK  ┐
        # └────┘
        # The bottom line starts right under the face's left edge: box
        # corners sit in the middle of their cell, unlike half blocks, so
        # starting one column in would look lopsided.
        right = OUTLINE_TOP_RIGHT
        below = (
            OUTLINE_BOTTOM_LEFT
            + OUTLINE_HORIZONTAL * (width - 1)
            + OUTLINE_BOTTOM_RIGHT
        )
        below_column = column
    else:
        right, below = SHADOW_RIGHT, SHADOW_BELOW * width
        below_column = column + 1
    canvas.write(row, column + width, right, shadow, clip=origin)
    canvas.write(row + 1, below_column, below, shadow, clip=origin)
