"""Spin boxes, which hold a whole number within a fixed range, typed in or
stepped up and down with ``▼`` and ``▲``."""

import time
from collections.abc import Callable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.scrollbar import DOWN, UP, AutoRepeat
from dasha.shortcuts import Shortcuts
from dasha.style import BRIGHT_WHITE, GREEN, Style
from dasha.widgets.base import Widget
from dasha.widgets.textbox import TextBox


class SpinBox(Widget):  # pylint: disable=too-many-instance-attributes
    """A ``SpinBox`` holds a whole number within a fixed range, from ``minimum``
    to ``maximum``, both given when it is created. The number is in a text box,
    with ``▼`` and ``▲`` on its right to step it:

    ::

         42      ▼▲

    - Up / Down (``spin_up`` / ``spin_down``): step the number by ``step``
      (1 by default)
    - Page Up / Page Down (``spin_page_up`` / ``spin_page_down``): step it by
      ``page`` (10 steps by default)
    - A click on ``▲`` or ``▼``: step it, repeating while the button is held
      down
    - The mouse wheel: step it
    - Digits (and ``-``, for ranges below 0): type a number

    Stepping stops at either end of the range. When the box receives the focus,
    the number is selected, so typing replaces it; the rest of the text box's
    editing works too. What was typed takes effect once the focus leaves, when
    Enter, Tab or Escape is pressed, or when the number is stepped. If it is not
    a whole number within the range (``150`` for a range of 0 to 100, or nothing
    at all), it is discarded, and the number goes back to what it was before
    typing began. Enter, Tab and Escape are then passed on to the window, so
    Enter presses a dialog's default button with the typed number already
    accepted.

    ``value`` is the number, which is kept within range when code sets it.
    ``set(value)`` changes it as the user does, ``commit()`` accepts what was
    typed, and ``on_change(box)`` is called for every change the user makes. The
    text box is ``field``, in the text box's colours, and the arrows use
    ``spinbox.arrows``.
    """

    focusable = True
    arrow_style: Style = Style(foreground=BRIGHT_WHITE, background=GREEN, bold=True)
    """The style of the ``▼▲`` on the right."""
    min_width: int = 5
    """The narrowest width: a text box's three columns, and the two
    arrows."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        row: int,
        column: int,
        width: int,
        *,
        minimum: int,
        maximum: int,
        value: int | None = None,
        step: int = 1,
        page: int | None = None,
        on_change: Callable[["SpinBox"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        if width < self.min_width:
            raise ValueError(f"a spin box must be at least {self.min_width} wide")
        if maximum < minimum:
            raise ValueError("maximum must not be less than minimum")
        if step < 1:
            raise ValueError("step must be at least 1")
        super().__init__(row, column, width, name=name, status=status)
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.page = max(step, page if page is not None else step * 10)
        self.on_change = on_change
        digits = max(len(str(minimum)), len(str(maximum)))
        self.field = TextBox(
            row,
            column,
            width - 2,
            max_length=digits,
            pattern=r"-?[0-9]*" if minimum < 0 else r"[0-9]*",
        )
        """The text box the number is typed in."""
        self._value = minimum
        self.value = minimum if value is None else value
        self._repeat = AutoRepeat()

    @property
    def value(self) -> int:
        """The number. Setting it from code keeps it within range, and does
        not call ``on_change``."""
        return self._value

    @value.setter
    def value(self, value: int) -> None:
        self._value = max(self.minimum, min(value, self.maximum))
        self.field.text = str(self._value)

    def parse(self, text: str) -> int | None:
        """The number that ``text`` holds, if it is a whole number within the
        range."""
        try:
            number = int(text)
        except ValueError:
            return None
        return number if self.minimum <= number <= self.maximum else None

    def set(self, value: int) -> None:
        """Change the number as the user does, keeping it within range and
        calling ``on_change`` if it changed."""
        before = self._value
        self.value = value
        if self._value != before and self.on_change is not None:
            self.on_change(self)

    def commit(self) -> None:
        """Accept what was typed, if it is a number within the range; otherwise
        put the number back as it was."""
        typed = self.parse(self.field.text)
        self.set(self._value if typed is None else typed)

    def step_by(self, amount: int) -> None:
        """Step the number (after accepting what was typed)."""
        self.commit()
        self.set(self._value + amount)

    # Layout and focus

    def min_size(self) -> tuple[int, int]:
        return self.min_width, 1

    def on_add(self) -> None:
        self.field.window = self.window

    def _place_field(self) -> None:
        """Keep the text box where the spin box is, less the arrows (the
        spin box may have been moved or stretched)."""
        rect = self.rect
        self.field.rect = Rect(rect.row, rect.column, 1, rect.width - 2)

    def focus_changed(self, focused: bool) -> None:
        """When the focus arrives, select the number, so that typing replaces
        it; when the focus leaves, accept what was typed."""
        if focused:
            self.field.select_all()
        else:
            self.commit()

    # Drawing and input

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        self._place_field()
        self.field.paint(canvas, origin, focused)
        row = origin.row + self.rect.row
        column = origin.column + self.rect.right - 2
        canvas.write(row, column, DOWN + UP, self.arrow_style, clip=origin)

    def key_help(self, shortcuts: Shortcuts) -> list[tuple[str, str]]:
        up, down = shortcuts.hint("spin_up"), shortcuts.hint("spin_down")
        steps = [(f"{up}/{down}", "Step")] if up and down else []
        return steps + self.field.key_help(shortcuts)

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Step the number, or edit it as text. A key the box does not use
        (Enter, Tab or Escape) first accepts what was typed, and is then
        passed on to the window."""
        steps = {
            "spin_up": self.step,
            "spin_down": -self.step,
            "spin_page_up": self.page,
            "spin_page_down": -self.page,
        }
        for action, amount in steps.items():
            if shortcuts.matches(action, key):
                self.step_by(amount)
                self.field.select_all()
                return True
        if self.field.handle_key(key, shortcuts):
            return True
        self.commit()
        return False

    def handle_paste(self, text: str) -> bool:
        return self.field.handle_paste(text)

    def _arrow_at(self, column: int) -> int:
        """Which way an arrow at ``column`` steps: 1 for ``▲``, -1 for
        ``▼``, 0 off the arrows."""
        return {self.rect.right - 2: -1, self.rect.right - 1: 1}.get(column, 0)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """The arrows step the number (repeating while held down), the mouse
        wheel steps it, and everything else goes to the text box."""
        self._place_field()
        if event.action == "scroll":
            self.step_by(self.step if event.button in ("up", "right") else -self.step)
            return True
        if event.button != "left":
            return False
        if event.action == "press":
            direction = self._arrow_at(column)
            if direction == 0:
                return self.field.handle_mouse(event, row, column)
            self.step_by(direction * self.step)
            self._repeat.start(str(direction), row, column, time.monotonic())
            return True
        if self._repeat.part is not None:
            if event.action == "drag":
                self._repeat.move(row, column)
            elif event.action == "release":
                self._repeat.stop()
            return event.action in ("drag", "release")
        return self.field.handle_mouse(event, row, column)

    def wake_time(self) -> float | None:
        repeat = self._repeat.wake_time()
        return repeat if repeat is not None else self.field.wake_time()

    def on_timer(self, now: float) -> None:
        """Repeat a held arrow, while the pointer stays on it."""
        repeat = self._repeat
        if repeat.part is not None:
            on = self._arrow_at(repeat.column) if repeat.row == self.rect.row else 0
            if repeat.due(now, str(on)):
                self.step_by(int(repeat.part) * self.step)
        else:
            self.field.on_timer(now)
