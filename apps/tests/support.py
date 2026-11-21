"""Helpers for the example applications' tests."""

from collections.abc import Callable
from io import StringIO
from typing import cast

from dasha.events import Event
from dasha.manager import PresentationManager
from dasha.terminal import Terminal


class FakeTerminal:
    """A terminal stand-in with scripted input.

    :param inputs: Reads; ``""`` is a timeout.
    :param size: Screen (columns, lines).
    """

    def __init__(self, inputs: list[str], size: tuple[int, int] = (80, 24)) -> None:
        self.inputs = inputs
        self.output = StringIO()
        self.screen_size = size

    def size(self) -> tuple[int, int]:
        """The screen's size, as a terminal reports it."""
        return self.screen_size

    def write(self, text: str) -> None:
        """Capture output.

        :param text: The output.
        """
        self.output.write(text)

    def flush(self) -> None:
        """Nothing to flush."""

    def read(self, timeout: float | None = None) -> str:
        """The next scripted input.

        :param timeout: Ignored.
        """
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
    """Run a manager on scripted input.

    :param manager: The desktop.
    :param inputs: Input to read.
    """
    terminal = FakeTerminal(inputs)
    manager.run(cast(Terminal, terminal))
    return terminal
