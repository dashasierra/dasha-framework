"""Text boxes that suggest what to type."""

import re
from collections.abc import Callable, Iterable

from dasha.shortcuts import Shortcuts
from dasha.widgets.textbox import TextBox

type Matcher = Callable[[str, list[str]], Iterable[str]]
"""Picks the suggestions for some text, best first."""


def match_suggestions(text: str, suggestions: list[str]) -> list[str]:
    """Suggestions matching some text, ignoring case.

    :param text: The typed text.
    :param suggestions: Candidate suggestions.
    """
    folded = text.casefold()
    if not folded.strip():
        return []
    starting, containing = [], []
    for suggestion in dict.fromkeys(suggestions):
        other = suggestion.casefold()
        if other == folded:
            continue
        if other.startswith(folded):
            starting.append(suggestion)
        elif folded in other:
            containing.append(suggestion)
    return starting + containing


class AutoCompleteBox(TextBox):
    """A text box with a popup of suggestions.

    :param row: Row in the window.
    :param column: Column in the window.
    :param width: Width in columns.
    :param suggestions: Text to suggest.
    :param rows: Most suggestions shown at once.
    :param matcher: Chooses suggestions for some text, best first.
    :param text: Initial text.
    :param max_length: Longest text allowed, if limited.
    :param pattern: Pattern the text must match, if any.
    :param on_change: Called with the box when its text changes.
    :param name: Widget name.
    :param status: Status bar text.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        row: int,
        column: int,
        width: int,
        *,
        suggestions: Iterable[str] = (),
        rows: int = 8,
        matcher: Matcher | None = None,
        text: str = "",
        max_length: int | None = None,
        pattern: str | re.Pattern[str] | None = None,
        on_change: Callable[[TextBox], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        super().__init__(
            row,
            column,
            width,
            text=text,
            max_length=max_length,
            pattern=pattern,
            on_change=on_change,
            name=name,
            status=status,
        )
        self.suggestions: list[str] = list(suggestions)
        self.rows = max(1, rows)
        self.matcher = matcher
        self._suggesting = False

    def matches(self) -> list[str]:
        """The suggestions for the current text, best first."""
        matcher = self.matcher or match_suggestions
        return list(matcher(self.text, self.suggestions))

    def suggest(self, everything: bool = False) -> bool:
        """Show the suggestions popup; return whether it was shown.

        :param everything: Show every suggestion while the box is empty.
        """
        window = self.window
        manager = window.manager if window is not None else None
        if self._suggesting or window is None or manager is None:
            return False
        items = list(self.suggestions) if everything and not self.text else []
        items = items or self.matches()
        self._suggesting = True
        try:
            popup = manager.suggest(self, items)
        finally:
            self._suggesting = False
        if popup is None:
            return False
        chosen = popup.chosen
        if popup.result == "ok" and chosen is not None:
            self.select_all()
            if not self.insert(chosen):
                self.cursor = len(self.text)
        if popup.passed_key is not None:
            window.handle_key(popup.passed_key, manager.shortcuts)
        return True

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Edit the text, then suggest.

        :param key: The key pressed.
        :param shortcuts: Key bindings in effect.
        """
        if shortcuts.matches("suggest_open", key):
            self.suggest(everything=True)
            return True
        before = self.text
        used = super().handle_key(key, shortcuts)
        if self.text != before:
            self.suggest()
        return used

    def handle_paste(self, text: str) -> bool:
        used = super().handle_paste(text)
        if used:
            self.suggest()
        return used
