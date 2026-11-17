"""Push buttons."""

from collections.abc import Callable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.menu import mnemonic_key, split_mnemonic
from dasha.style import BLACK, BRIGHT_WHITE, BRIGHT_YELLOW, GREEN, Colour, Style
from dasha.widgets.base import Widget

SHADOW_BELOW = "\N{UPPER HALF BLOCK}"
SHADOW_RIGHT = "\N{LOWER HALF BLOCK}"
"""The characters of a button's shadow: code page 437 characters 223 (▀)
and 220 (▄)."""

OUTLINE_TOP_RIGHT = "\N{BOX DRAWINGS LIGHT DOWN AND LEFT}"
OUTLINE_BOTTOM_LEFT = "\N{BOX DRAWINGS LIGHT UP AND RIGHT}"
OUTLINE_BOTTOM_RIGHT = "\N{BOX DRAWINGS LIGHT UP AND LEFT}"
OUTLINE_HORIZONTAL = "\N{BOX DRAWINGS LIGHT HORIZONTAL}"
"""The characters of the outline shadow (code page 437 characters 191,
192, 217 and 196)."""

SHADOW_SHAPES = ("solid", "outline")
"""The ways a button's shadow can be drawn: with half blocks, or as a
single-line outline (which looks neater without colour, where solid blocks
look like part of the button)."""


class Button(Widget):
    """A push button: a green face with a ``▄``/``▀`` shadow (code page
    437 glyphs 220 and 223). It is at least 10 columns wide, and ``label``
    can mark a mnemonic letter with ``&``.

    - **Enter or Space** (``press_button``) presses the focused button, or
      the ``default`` button if the focus is not on a button.
    - **Holding Space.** Where the terminal reports keys being released
      (the Windows console), Space pushes in the focused button, just as a
      mouse press does, and the button stays pushed in while Space is held
      down; releasing Space presses it. The key's own repeats while it is
      held do nothing more, and if the focus moves on first, the button
      simply springs back. Elsewhere, Space presses the button straight
      away. Enter always presses the button straight away.
    - **Mnemonic letter.** Alt with the button's letter presses it. In a
      dialog, the letter on its own does.
    - **Mouse.** A press pushes the button in, moving it into its shadow.
      Releasing the mouse button over it presses it, and releasing it
      elsewhere cancels the press.

    Pressing the button calls ``action(button)``, and then the window's
    ``button_pressed(button)``; in a dialog, that ends the dialog with the
    button's ``result``.
    """

    focusable = True
    face_style: Style = Style(foreground=BLACK, background=GREEN)
    focused_style: Style = Style(foreground=BRIGHT_WHITE, background=GREEN, bold=True)
    mnemonic_style: Style = Style(foreground=BRIGHT_YELLOW, background=GREEN)
    focused_mnemonic_style: Style = Style(
        foreground=BRIGHT_YELLOW, background=GREEN, bold=True
    )
    shadow_style: Style = Style(foreground=BLACK)
    """The shadow's colours. Its background is always the window's, so
    that the shadow sits on the window."""
    shadow_shape: str = "solid"
    """``"solid"`` (``▄``/``▀`` half blocks) or ``"outline"`` (single box
    lines around where the shadow falls). The monochrome theme uses the
    outline."""
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
        """The button's face (without its shadow), relative to the window's
        interior."""
        return Rect(self.rect.row, self.rect.column, 1, self.rect.width - 1)

    @property
    def value(self) -> str | None:
        return self.result

    def mnemonic(self) -> str | None:
        return mnemonic_key(self.label)

    def press_with_key(self, key: str, held: bool = True) -> None:
        """Handle Enter or Space (``press_button``) pressed while the button
        has the focus (``held``) or is the default. Where the terminal reports
        keys being released (``key_releases``), Space pushes in the focused
        button, as a mouse press does, and releasing Space presses it;
        repeats while Space is held do nothing more. Otherwise, and for
        Enter, the button is pressed straight away, with nothing to show."""
        if key == " " and held and self.key_releases:
            self._pressed = True  # until handle_key_release
            return
        self.activate()

    def handle_key_release(self, key: str, focused: bool) -> None:
        """Handle the release of Space: a button pushed in by it springs
        back, and is pressed if it still has the focus."""
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
        """The shadow beside and below the face at ``row``, ``column``."""
        background = self.window.body_style.background if self.window else None
        paint_shadow(
            canvas,
            origin,
            (row, column, self.face.width),
            background,
            (self.shadow_style, self.shadow_shape),
        )

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """A press on the face pushes the button in; releasing the mouse
        button over the face presses it, and releasing it elsewhere cancels
        the press."""
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
    """Draw a button's shadow beside and below a one-row ``face`` at (row,
    column, width) on the screen, on the window's ``background``, as
    ``looks`` describes (the shadow's style, and its shape, ``"solid"`` or
    ``"outline"``). Anything that wants to look raised in the same way (such
    as a ``Switch``) uses this too."""
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
