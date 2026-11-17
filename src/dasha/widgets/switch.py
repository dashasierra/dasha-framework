"""Switches: a sliding on/off toggle for a setting that is either true or
false."""

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
"""The knob ``█`` (code page 437 glyph 219) and the track ``░`` (176)."""


class Switch(Widget):  # pylint: disable=too-many-instance-attributes
    """A ``Switch`` is a setting that is either true or false (On/Off, Yes/No,
    True/False, Dark mode), shown as a knob that slides along a three-cell track:
    on the left for off, and on the right for on. It takes up three columns, plus
    a shadow:

    ::

        █░░▄ Dark mode       off
         ▀▀▀
        ░░█▄ Dark mode       on
         ▀▀▀

    The knob (``█``, code page 437 glyph 219) and the track (``░``, 176) show
    the state by the side the knob is on, so a switch reads the same without
    colour. In colour, the track is grey when off and green when on
    (``switch.off``, ``switch.on``). It casts the same shadow as a push button,
    using the same ``button.shadow`` colours and ``button_shadow`` setting: solid
    half blocks in colour, and the single-line outline in monochrome (``█░░┐``
    above ``└──┘``), so that it looks raised in the same way. The label comes
    after it, with an optional ``&`` letter, and is drawn in reverse video while
    the switch has the focus.

    - Space (``switch_toggle``): switch it the other way
    - Left (``switch_off``): turn it off (the knob slides left)
    - Right (``switch_on``): turn it on (the knob slides right)
    - Its letter (Alt with the letter, or the letter alone in a dialog), or a
      click on it: switch it the other way

    ``on`` (and ``value``) is the setting. ``set(on)``, ``toggle()``,
    ``turn_on()`` and ``turn_off()`` change it as the user does, and
    ``on_change(switch)`` is called whenever the user changes it (setting ``on``
    from code notifies no one). A ``disabled`` switch is greyed out
    (``switch.disabled``), and can neither take the focus nor be changed. Enter
    and Tab are left for the window.

    The shadow is drawn by ``dasha.widgets.button.paint_shadow``, which any
    widget can use to look raised like a button.
    """

    focusable = True
    off_style: Style = Style(foreground=BRIGHT_WHITE, background=WHITE)
    on_style: Style = Style(foreground=BRIGHT_WHITE, background=GREEN, bold=True)
    disabled_style: Style = Style(foreground=BRIGHT_BLACK, background=WHITE)
    """The style of the track and label of a switch that cannot be
    changed."""

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
        """Turn the switch on or off as the user does, calling ``on_change``
        if the setting changed. (Setting ``on`` from code notifies no one.)"""
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
        """The label after the shadow: reversed while focused, so the focus
        shows on any window's colours, its letter underlined."""
        style = self.disabled_style if self.disabled else focus_style(body, focused)
        paint_mnemonic_label(
            canvas, origin, at, self.label, style, underline=not self.disabled
        )

    # Input

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Space switches it the other way, Left turns it off, and Right turns
        it on."""
        if self.disabled:
            return False
        actions: dict[str, Callable[[], object]] = {
            "switch_toggle": self.toggle,
            "switch_off": self.turn_off,
            "switch_on": self.turn_on,
        }
        return run_shortcut(shortcuts, key, actions)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """A press on the track or the label switches it the other way."""
        del column
        if event.button != "left" or self.disabled:
            return False
        if event.action == "press" and row == self.rect.row:
            self.toggle()
        return event.action in ("press", "drag", "release")
