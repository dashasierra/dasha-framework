"""Spin boxes."""

import time
from collections.abc import Callable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.scrollbar import DOWN, UP, AutoRepeat
from dasha.shortcuts import Shortcuts
from dasha.style import BRIGHT_WHITE, BLUE, Style
from dasha.widgets.base import Widget
from dasha.widgets.textbox import TextBox


class SpinBox(Widget):  # pylint: disable=too-many-instance-attributes
    """A number in a range, typed or stepped.

    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param minimum: Smallest value.
    :param maximum: Largest value.
    :param value: Initial value, or ``None`` for the minimum.
    :param step: Amount of one step.
    :param page: Amount of one page, if not ten steps.
    :param on_change: Called with the box when the user changes it.
    :param name: Widget name.
    :param status: Status bar text.
    """

    focusable = True
    arrow_style: Style = Style(foreground=BRIGHT_WHITE, background=BLUE, bold=True)
    """The style of the ``▼▲`` on the right."""
    min_width: int = 5
    """Narrowest width."""

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
        """The number."""
        return self._value

    @value.setter
    def value(self, value: int) -> None:
        self._value = max(self.minimum, min(value, self.maximum))
        self.field.text = str(self._value)

    def parse(self, text: str) -> int | None:
        """The number some text holds, if valid.

        :param text: The text.
        """
        try:
            number = int(text)
        except ValueError:
            return None
        return number if self.minimum <= number <= self.maximum else None

    def set(self, value: int) -> None:
        """Change the number, as the user does.

        :param value: New value.
        """
        before = self._value
        self.value = value
        if self._value != before and self.on_change is not None:
            self.on_change(self)

    def commit(self) -> None:
        """Accept the typed number, or restore the old one."""
        typed = self.parse(self.field.text)
        self.set(self._value if typed is None else typed)

    def step_by(self, amount: int) -> None:
        """Step the number.

        :param amount: Amount to step by.
        """
        self.commit()
        self.set(self._value + amount)

    # Layout and focus

    def min_size(self) -> tuple[int, int]:
        return self.min_width, 1

    def on_add(self) -> None:
        self.field.window = self.window

    def _place_field(self) -> None:
        """Keep the text box in place."""
        rect = self.rect
        self.field.rect = Rect(rect.row, rect.column, 1, rect.width - 2)

    def focus_changed(self, focused: bool) -> None:
        """Select or accept the number.

        :param focused: Whether the box now has the focus.
        """
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
        """Step or edit the number.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
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
        """An arrow's step direction: 1, -1 or 0.

        :param column: Column in the box.
        """
        return {self.rect.right - 2: -1, self.rect.right - 1: 1}.get(column, 0)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """Step with the arrows or wheel.

        :param event: The mouse event.
        :param row: Row in the window's interior.
        :param column: Column in the window's interior.
        """
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
        """Repeat a held arrow.

        :param now: The current ``time.monotonic``.
        """
        repeat = self._repeat
        if repeat.part is not None:
            on = self._arrow_at(repeat.column) if repeat.row == self.rect.row else 0
            if repeat.due(now, str(on)):
                self.step_by(int(repeat.part) * self.step)
        else:
            self.field.on_timer(now)
