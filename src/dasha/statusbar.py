"""The status bar."""

from collections.abc import Sequence

from dasha.canvas import Canvas, Rect
from dasha.style import BRIGHT_WHITE, BRIGHT_GREEN, BRIGHT_BLUE, Style


def status_text(source: object) -> str:
    """An object's status text, or "".

    :param source: The object.
    """
    text = getattr(source, "status", None)
    return text if isinstance(text, str) else ""


class StatusBar:  # pylint: disable=too-few-public-methods
    """Draws status text and key hints on the bottom row."""

    style: Style = Style(foreground=BRIGHT_WHITE, background=BRIGHT_BLUE)
    """The style of the bar, its text and the hints' descriptions."""
    key_style: Style = Style(foreground=BRIGHT_GREEN, background=BRIGHT_BLUE)
    """The style of the key names in the hints on the right."""

    divider: str = "\N{BOX DRAWINGS LIGHT VERTICAL}"
    """Divider after the owner's name."""

    def paint(
        self,
        canvas: Canvas,
        text: str,
        hints: Sequence[tuple[str, str]] = (),
        owner: str = "",
    ) -> None:
        """Paint the status bar.

        :param canvas: Canvas to draw on.
        :param text: Status text.
        :param hints: (key, description) pairs.
        :param owner: The active application's name.
        """
        row = canvas.height - 1
        if row < 0:
            return
        canvas.fill(Rect(row, 0, 1, canvas.width), " ", self.style)
        start = self._text_start(owner)
        if owner:
            canvas.write(row, 1, f"{owner} {self.divider} ", self.style)
        placed = self.hint_places(canvas.width, hints, owner)
        width = sum(end - begin for begin, end, _ in placed)
        # Only the first line, so a stray newline cannot spill onto the screen.
        first_line = text.splitlines()[0] if text else ""
        if placed:  # leave a gap before the hints
            first_line = first_line[: max(0, canvas.width - 1 - start - width)]
        canvas.write(row, start, first_line, self.style)
        for begin, _, (key, label) in placed:
            canvas.write(row, begin + 1, key, self.key_style)
            canvas.write(row, begin + 2 + len(key), label, self.style)

    def _text_start(self, owner: str) -> int:
        """Column where the status text starts.

        :param owner: The active application's name.
        """
        return 1 + (len(f"{owner} {self.divider} ") if owner else 0)

    def hint_places(
        self, width: int, hints: Sequence[tuple[str, str]], owner: str = ""
    ) -> list[tuple[int, int, tuple[str, str]]]:
        """Where each fitting hint goes.

        :param width: Bar width.
        :param hints: (key, description) pairs.
        :param owner: The active application's name.
        """
        shown = self._fitting(hints, width - 1 - self._text_start(owner))
        column = width - sum(len(key) + len(label) + 3 for key, label in shown)
        places = []
        for key, label in shown:
            end = column + len(key) + len(label) + 3
            places.append((column, end, (key, label)))
            column = end
        return places

    def hint_at(
        self,
        column: int,
        width: int,
        hints: Sequence[tuple[str, str]],
        owner: str = "",
    ) -> tuple[str, str] | None:
        """The hint at a column, if any.

        :param column: Bar column.
        :param width: Bar width.
        :param hints: (key, description) pairs.
        :param owner: The active application's name.
        """
        for begin, end, hint in self.hint_places(width, hints, owner):
            if begin < column < end:  # not the gap before it
                return hint
        return None

    @staticmethod
    def _fitting(hints: Sequence[tuple[str, str]], room: int) -> list[tuple[str, str]]:
        """The hints that fit.

        :param hints: (key, description) pairs.
        :param room: Columns available.
        """
        shown, used = [], 0
        for key, label in hints:
            used += len(key) + len(label) + 3  # " Key Label" and a gap
            if used > room:
                break
            shown.append((key, label))
        return shown
