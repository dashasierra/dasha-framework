"""Autocomplete boxes: text boxes that suggest what to type."""

import re
from collections.abc import Callable, Iterable

from dasha.shortcuts import Shortcuts
from dasha.widgets.textbox import TextBox

type Matcher = Callable[[str, list[str]], Iterable[str]]
"""Picks the suggestions for some text, best first."""


def match_suggestions(text: str, suggestions: list[str]) -> list[str]:
    """The suggestions that match ``text``, ignoring case: first those that
    start with it, then those that contain it anywhere else, each in the order
    given. There are none for blank text, and the text itself is never
    suggested."""
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
    """An ``AutoCompleteBox`` is a text box that suggests what to type. As
    text is typed, those of its ``suggestions`` that match it drop down in a
    popup, which follows the typing:

    ::

        ┌──────────────────────┐
        │ py                   │
        │ python.org           │
        │ pypi.org             │
        │ docs.python.org      │
        └──────────────────────┘

    Unlike a combo box's text, the text need not be one of the suggestions:
    they only save typing, and the box's ``value`` is whatever text it holds. The
    popup covers the box, with its top row lined up over the box, so that typing
    carries on in it, cursor and all. It goes below the box, or above it if there
    is more room there, and holds up to ``rows`` (8) suggestions; it shrinks as
    fewer suggestions match, and closes when none do.

    - Typing: edit the text, as in a text box; the suggestions follow it
    - Down / Up (``suggest_down`` / ``suggest_up``): highlight the next /
      previous suggestion (Up from the first highlights none)
    - Enter (``suggest_choose``): take the highlighted suggestion; with none
      highlighted, close the popup and pass the key on to the window (which
      presses a dialog's default button)
    - Tab or Shift+Tab (``next_widget``, ``previous_widget``): close the popup,
      and move the focus
    - Escape, or a click elsewhere: close the popup, keeping the text
    - A click on a suggestion: take it
    - Alt+Down or F4 (``suggest_open``): show the suggestions without typing,
      showing every one when the box is empty

    Suggestions are matched ignoring case, with those starting with the text
    first, then those containing it anywhere else; there are none for blank
    text, and the text itself is never suggested (``match_suggestions``).
    ``matcher(text, suggestions)`` can choose them in another way, best first.
    Everything else works as in a ``TextBox``, including ``on_change``: taking a
    suggestion is a change, which Ctrl+Z undoes.
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
        """Drop down the suggestions for the text, if there are any, and wait
        until the popup closes (with ``everything``, show all of them while the
        box is empty). Returns whether the popup was shown."""
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
        """Edit the text as a text box does, and then suggest what to type."""
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
