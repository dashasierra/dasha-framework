"""Tests for the key test screen's loop (``dasha.keytest.run``)."""

import unittest
from io import StringIO
from typing import cast

from dasha.keytest import run
from dasha.terminal import Terminal
from tests.support import assert_lines_shown, without_styles
from tests.test_manager import FakeTerminal


class KeyTestTerminal(FakeTerminal):
    """A scripted terminal keeping each frame, cleared on request.

    :param inputs: Reads; ``""`` is a timeout.
    :param sizes: Sizes to report, if any.
    :param clear_at: Frame after which the screen is cleared.
    """

    def __init__(
        self,
        inputs: list[str],
        sizes: list[tuple[int, int]] | None = None,
        clear_at: int = -1,
    ) -> None:
        super().__init__(inputs, sizes=sizes)
        self.frames: list[str] = []
        self.clear_at = clear_at
        self.cleared = False

    def flush(self) -> None:
        """Keep what was written since the last flush."""
        self.frames.append(self.output.getvalue())
        self.output = StringIO()
        self.cleared = len(self.frames) == self.clear_at

    def take_cleared(self) -> bool:
        """Whether the screen was cleared since last asked."""
        cleared, self.cleared = self.cleared, False
        return cleared


class RunTests(unittest.TestCase):
    """Showing each event until Ctrl+C."""

    def test_shows_keys_and_mouse_until_ctrl_c(self) -> None:
        """Keys and clicks are listed; plain movement is not; Ctrl+C ends."""
        terminal = KeyTestTerminal(
            ["a", "\x1b[<35;3;2M", "\x1b[<0;3;2M", "\x03", "never read"],
            sizes=[(80, 10)],
        )
        run(cast(Terminal, terminal))
        self.assertEqual(terminal.inputs, ["never read"])
        output = "".join(terminal.frames)
        assert_lines_shown(self, '"a" (A)\nmouse left press at row 1, column 2', output)
        self.assertNotIn("move", without_styles(output))

    def test_cleared_screen_is_drawn_again(self) -> None:
        """After the terminal clears the screen, the header is drawn again."""
        terminal = KeyTestTerminal(["", "", "\x03"], sizes=[(80, 10)], clear_at=2)
        run(cast(Terminal, terminal))
        self.assertIn("key test", without_styles(terminal.frames[2]))
        self.assertNotIn("key test", without_styles(terminal.frames[1]))

    def test_no_room_for_the_list(self) -> None:
        """On a screen with room only for the header, no keys are listed."""
        terminal = KeyTestTerminal(["a", "", "\x03"], sizes=[(80, 3)])
        run(cast(Terminal, terminal))
        self.assertNotIn('"a"', without_styles("".join(terminal.frames)))


if __name__ == "__main__":
    unittest.main()
