"""The status bar: one line of help along the bottom of the screen.

Anything that can have the focus (a window, a widget or a menu item) can
offer status text through a ``status`` attribute. It is always optional:
``status_text`` treats a missing attribute, ``None`` and an empty string in
the same way, as nothing to show.
"""

from collections.abc import Sequence

from dasha.canvas import Canvas, Rect
from dasha.style import BLACK, RED, WHITE, Style


def status_text(source: object) -> str:
    """The status text an object offers, or ``""`` if it offers none."""
    text = getattr(source, "status", None)
    return text if isinstance(text, str) else ""


class StatusBar:  # pylint: disable=too-few-public-methods
    """Draws the status text on the bottom row, and on its right the most
    useful keys for whatever has the focus
    (``F10 Menu  Ctrl+Tab Next``), with the key names picked out in
    ``key_style``.

    Its appearance is set by class attributes, so a subclass can restyle it.
    """

    style: Style = Style(foreground=BLACK, background=WHITE)
    key_style: Style = Style(foreground=RED, background=WHITE)
    """The style of the key names in the hints on the right."""

    divider: str = "\N{BOX DRAWINGS LIGHT VERTICAL}"
    """The divider between ``owner`` and the status text: ``│`` (code page
    437 character 179)."""

    def paint(
        self,
        canvas: Canvas,
        text: str,
        hints: Sequence[tuple[str, str]] = (),
        owner: str = "",
    ) -> None:
        """Paint the bar on the bottom row: ``owner`` (the active
        application's name, if given) and a divider on the left, followed by
        ``text`` (which may be empty), with ``hints`` (pairs of a key and
        its description) on the right. Hints that do not fit are dropped from
        the end, and the text is shortened to make room for those that do."""
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
        """The column the status text starts at, after ``owner``."""
        return 1 + (len(f"{owner} {self.divider} ") if owner else 0)

    def hint_places(
        self, width: int, hints: Sequence[tuple[str, str]], owner: str = ""
    ) -> list[tuple[int, int, tuple[str, str]]]:
        """Where ``paint`` puts each hint that fits on a bar ``width``
        columns wide, as ``(first column, column after it, (key, label))``,
        where each hint's span covers its key, its label and the gap before
        it."""
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
        """The hint drawn at ``column`` of a bar ``width`` columns wide (on its
        key or its label), if any: the hint that a click there is on."""
        for begin, end, hint in self.hint_places(width, hints, owner):
            if begin < column < end:  # not the gap before it
                return hint
        return None

    @staticmethod
    def _fitting(hints: Sequence[tuple[str, str]], room: int) -> list[tuple[str, str]]:
        """As many hints, from the first, as fit in ``room`` columns."""
        shown, used = [], 0
        for key, label in hints:
            used += len(key) + len(label) + 3  # " Key Label" and a gap
            if used > room:
                break
            shown.append((key, label))
        return shown
