"""Helpers for the example applications' tests: a presentation manager
run on scripted input, as Dasha Framework's own tests do."""

from collections.abc import Callable
from io import StringIO
from typing import cast

from dasha.events import Event
from dasha.manager import PresentationManager
from dasha.terminal import Terminal


class FakeTerminal:
    """Stands in for Terminal: scripted input, captured output."""

    def __init__(self, inputs: list[str], size: tuple[int, int] = (80, 24)) -> None:
        self.inputs = inputs
        self.output = StringIO()
        self.screen_size = size

    def size(self) -> tuple[int, int]:
        """The screen's size, as a terminal reports it."""
        return self.screen_size

    def write(self, text: str) -> None:
        """Capture output."""
        self.output.write(text)

    def flush(self) -> None:
        """Nothing to flush."""

    def read(self, timeout: float | None = None) -> str:
        """Return the next scripted input; ``""`` in the script is a timeout."""
        del timeout
        return self.inputs.pop(0)


class Scripted(PresentationManager):
    """Runs the next of ``actions`` each time "x" is pressed."""

    def __init__(self) -> None:
        super().__init__()
        self.actions: list[Callable[[], object]] = []

    def handle_event(self, event: Event) -> None:
        if event == "x":
            self.actions.pop(0)()
        else:
            super().handle_event(event)


def run(manager: PresentationManager, inputs: list[str]) -> FakeTerminal:
    """Run a manager on scripted input, all of which must be read."""
    terminal = FakeTerminal(inputs)
    manager.run(cast(Terminal, terminal))
    return terminal
