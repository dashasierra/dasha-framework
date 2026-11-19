"""The Custom colour dialog in Settings...: an RGB colour, typed as
``#rrggbb`` or set by its red, green and blue."""

from dasha.dialog import Dialog
from dasha.style import Rgb, Style
from dasha.widgets import Button, Label, SpinBox, TextBox, Widget

SWATCH_WIDTH = 30
"""How wide the sample of the colour is."""


class ColourDialog(Dialog):
    """Asks for an RGB colour, starting from ``colour``. The text box and
    the three spin boxes keep in step, and the sample below them shows the
    colour. ``colour`` is the colour chosen, once answered ``"ok"``."""

    def __init__(self, colour: Rgb | None = None) -> None:
        super().__init__(
            "Custom colour",
            50,
            11,
            status="Type the colour as #rrggbb, or set its red, green and blue",
        )
        self.colour = colour or Rgb(0, 0, 0)
        """The colour shown."""
        self.add(Label("Colour", 0, 2))
        self.text = self.add(
            TextBox(
                0,
                10,
                9,
                text=self.colour.hex,
                max_length=7,
                on_change=lambda box: self._typed(),
                name="hex",
                status="The colour, as # and six hexadecimal digits",
            )
        )
        self.parts: list[SpinBox] = []
        for column, part in ((2, "red"), (16, "green"), (32, "blue")):
            self.add(Label(part.capitalize(), 2, column))
            self.parts.append(
                self.add(
                    SpinBox(
                        2,
                        column + len(part) + 1,
                        8,
                        minimum=0,
                        maximum=255,
                        value=getattr(self.colour, part),
                        on_change=lambda box: self._set_parts(),
                        name=part,
                        status=f"How much {part} is in the colour, from 0 to 255",
                    )
                )
            )
        self.add(Label("Sample", 4, 2))
        self.swatch = self.add(Label("\N{FULL BLOCK}" * SWATCH_WIDTH, 4, 10))
        self.problem = self.add(Label("", 5, 10, name="problem"))
        self.add(Button("&OK", 7, 12, result="ok", default=True, name="ok"))
        self.add(Button("&Cancel", 7, 26, result="cancel", name="cancel"))
        self._show()

    def _show(self) -> None:
        self.swatch.style = Style(foreground=self.colour)

    def _typed(self) -> None:
        """The text changed: the spin boxes and sample follow it, if it is a
        colour."""
        try:
            self.colour = Rgb.parse(self.text.text.strip())
        except ValueError:
            return
        self.problem.text = ""
        for box, part in zip(self.parts, ("red", "green", "blue")):
            box.value = getattr(self.colour, part)
        self._show()

    def _set_parts(self) -> None:
        """A spin box changed: the text and sample follow it."""
        self.colour = Rgb(*(box.value for box in self.parts))
        self.text.text = self.colour.hex
        self.problem.text = ""
        self._show()

    def button_pressed(self, button: Widget) -> None:
        """OK only with a colour typed; otherwise it says what to type."""
        if button.name == "ok":
            try:
                self.colour = Rgb.parse(self.text.text.strip())
            except ValueError:
                self.problem.text = "Type # and six digits, 0-9 or a-f"
                return
        super().button_pressed(button)
