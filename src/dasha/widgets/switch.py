"""On/off switches."""

from collections.abc import Callable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.menu import mnemonic_key, split_mnemonic
from dasha.shortcuts import Shortcuts
from dasha.style import BRIGHT_BLACK, BRIGHT_WHITE, GREEN, WHITE, Style
from dasha.widgets.base import Widget, run_shortcut
from dasha.widgets.button import Button, paint_shadow
from dasha.widgets.label import focus_style, paint_mnemonic_label

KNOB = "\N{FULL BLOCK}"
TRACK = "\N{LIGHT SHADE}"
"""Knob and track characters."""


class Switch(Widget):  # pylint: disable=too-many-instance-attributes
    """A sliding on/off toggle.

    :param label: Label text; ``&`` marks the mnemonic.
    :param row: Row in the window.
    :param column: Column in the window.
    :param on: Whether it starts on.
    :param disabled: Whether it is greyed out.
    :param on_change: Called with the switch when the user changes it.
    :param name: Widget name.
    :param status: Status bar text.
    """

    focusable = True
    off_style: Style = Style(foreground=BRIGHT_WHITE, background=WHITE)
    """The style of the track while the switch is off."""
    on_style: Style = Style(foreground=BRIGHT_WHITE, background=GREEN, bold=True)
    """The style of the track while the switch is on."""
    disabled_style: Style = Style(foreground=BRIGHT_BLACK, background=WHITE)
    """Style when disabled."""

    track_width = 3

    def __init__(  # pylint: disable=too-many-arguments
        self,
        label: str,
        row: int,
        column: int,
        *,
        on: bool = False,
        disabled: bool = False,
        on_change: Callable[["Switch"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        text = split_mnemonic(label)[0]
        # The track, its shadow column, a gap, and the label.
        width = self.track_width + 1 + (1 + len(text) if text else 0)
        super().__init__(row, column, width, 2, name=name, status=status)
        self.label = label
        self.on = on
        """Whether the switch is on (knob to the right)."""
        self.disabled = disabled
        self.on_change = on_change

    @property
    def value(self) -> bool:
        return self.on

    def can_focus(self) -> bool:
        return not self.disabled

    def min_size(self) -> tuple[int, int]:
        return self.rect.width, 2

    # Changing it

    def set(self, on: bool) -> None:
        """Turn on or off, as the user does.

        :param on: Whether to turn it on.
        """
        if on != self.on:
            self.on = on
            if self.on_change is not None:
                self.on_change(self)

    def toggle(self) -> None:
        """Switch it the other way."""
        self.set(not self.on)

    def turn_on(self) -> None:
        """Slide the knob right."""
        self.set(True)

    def turn_off(self) -> None:
        """Slide the knob left."""
        self.set(False)

    def mnemonic(self) -> str | None:
        return None if self.disabled else mnemonic_key(self.label)

    def activate(self) -> None:
        if not self.disabled:
            self.toggle()

    # Drawing

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        row = origin.row + self.rect.row
        column = origin.column + self.rect.column
        body = self.window.body_style if self.window is not None else Style()
        if self.disabled:
            track_style = self.disabled_style
        else:
            track_style = self.on_style if self.on else self.off_style
        track = TRACK * (self.track_width - 1)
        track = track + KNOB if self.on else KNOB + track
        canvas.write(row, column, track, track_style, clip=origin)
        paint_shadow(
            canvas,
            origin,
            (row, column, self.track_width),
            body.background,
            (Button.shadow_style, Button.shadow_shape),
        )
        self._paint_label(
            canvas, origin, (row, column + self.track_width + 2), body, focused
        )

    def _paint_label(
        self,
        canvas: Canvas,
        origin: Rect,
        at: tuple[int, int],
        body: Style,
        focused: bool,
    ) -> None:
        """Draw the label.

        :param canvas: Canvas to draw on.
        :param origin: The window's interior on screen.
        :param at: Screen row and column.
        :param body: The window's style.
        :param focused: Whether the switch has the focus.
        """
        style = self.disabled_style if self.disabled else focus_style(body, focused)
        paint_mnemonic_label(
            canvas, origin, at, self.label, style, underline=not self.disabled
        )

    # Input

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Toggle, turn on or turn off with the keys.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        if self.disabled:
            return False
        actions: dict[str, Callable[[], object]] = {
            "switch_toggle": self.toggle,
            "switch_off": self.turn_off,
            "switch_on": self.turn_on,
        }
        return run_shortcut(shortcuts, key, actions)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Toggle on a click.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
        del column
        if event.button != "left" or self.disabled:
            return False
        if event.action == "press" and row == self.rect.row:
            self.toggle()
        return event.action in ("press", "drag", "release")
