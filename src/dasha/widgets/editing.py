"""What text boxes and text areas share: undo history, moving by words,
and their context menu."""

from typing import Protocol

from dasha.clipboard import Clipboard
from dasha.menu import Menu, MenuItem, separator
from dasha.shortcuts import Shortcuts


def is_word(char: str) -> bool:
    """Whether a character is part of a word (letters, digits and ``_``)."""
    return char.isalnum() or char == "_"


def word_left(text: str, index: int) -> int:
    """Where Ctrl+Left moves to from ``index``: back over any spaces and
    punctuation, and then to the start of the word before them."""
    while index > 0 and not is_word(text[index - 1]):
        index -= 1
    while index > 0 and is_word(text[index - 1]):
        index -= 1
    return index


def word_right(text: str, index: int) -> int:
    """Where Ctrl+Right moves to from ``index``: past the rest of the word,
    then past spaces and punctuation, to the start of the next word (as in
    Windows), or to the end."""
    while index < len(text) and is_word(text[index]):
        index += 1
    while index < len(text) and not is_word(text[index]):
        index += 1
    return index


class Editable(Protocol):
    """What an editable text widget (a text box or a text area) provides
    for its context menu."""

    clipboard: Clipboard

    @property
    def selection(self) -> object:
        """What is selected, or ``None`` if nothing is."""
        raise NotImplementedError

    @property
    def can_undo(self) -> bool:
        """Whether there is a change to undo."""
        raise NotImplementedError

    def undo(self) -> bool:
        """Undo the latest change."""
        raise NotImplementedError

    def cut(self) -> bool:
        """Cut the selection to the clipboard."""
        raise NotImplementedError

    def copy(self) -> bool:
        """Copy the selection to the clipboard."""
        raise NotImplementedError

    def paste(self) -> bool:
        """Paste the clipboard's text."""
        raise NotImplementedError

    def select_all(self) -> None:
        """Select all the text."""
        raise NotImplementedError


def edit_menu(widget: Editable, shortcuts: Shortcuts, *, copies: bool = True) -> Menu:
    """The context menu of a text widget: Undo, Cut, Copy, Paste and Select
    all, each greyed out when it would do nothing. Cut and Copy are left out
    if the widget never ``copies`` anything out, as with a password box."""

    def selected() -> bool:
        return widget.selection is not None

    def pasteable() -> bool:
        return widget.clipboard.text is not None

    items = [
        MenuItem(
            "&Undo",
            widget.undo,
            shortcuts.hint("text_undo"),
            "Undoes the last change",
            enabled=lambda: widget.can_undo,
        ),
        separator(),
    ]
    if copies:
        items += [
            MenuItem(
                "Cu&t",
                widget.cut,
                shortcuts.hint("text_cut"),
                "Cuts the selection to the clipboard",
                enabled=selected,
            ),
            MenuItem(
                "&Copy",
                widget.copy,
                shortcuts.hint("text_copy"),
                "Copies the selection to the clipboard",
                enabled=selected,
            ),
        ]
    items += [
        MenuItem(
            "&Paste",
            widget.paste,
            shortcuts.hint("text_paste"),
            "Pastes the clipboard's text",
            enabled=pasteable,
        ),
        separator(),
        MenuItem(
            "Select &all",
            widget.select_all,
            shortcuts.hint("text_select_all"),
            "Selects all the text",
        ),
    ]
    return Menu("Edit", items)


class UndoHistory[T]:
    """The changes that can be undone, oldest first and kept to a limit,
    and the undone changes that can be redone.

    What each step holds is up to the widget: a text box keeps the text as it
    was, and a text area what one change replaced. The limit is given with
    each step, so changing a widget's ``undo_limit`` takes effect at once; it
    can be as large as needed, or ``None`` for no limit. As in any editor, a
    new change forgets whatever could have been redone.
    """

    def __init__(self) -> None:
        self._steps: list[T] = []
        self._undone: list[T] = []

    def __len__(self) -> int:
        return len(self._steps)

    def push(self, step: T, limit: int | None, *, redoing: bool = False) -> None:
        """Remember a change, forgetting the oldest changes beyond ``limit``.
        Unless the change comes from redoing, it also forgets whatever could
        be redone."""
        self._steps.append(step)
        if limit is not None:
            del self._steps[: max(0, len(self._steps) - max(0, limit))]
        if not redoing:
            self._undone.clear()

    def undone(self, step: T) -> None:
        """Remember how to redo what was just undone."""
        self._undone.append(step)

    def pop_redo(self) -> T | None:
        """Take the most recent undone change, to redo it, or return ``None``
        if there is none."""
        return self._undone.pop() if self._undone else None

    @property
    def can_redo(self) -> bool:
        """Whether anything undone can be redone."""
        return bool(self._undone)

    def pop(self) -> T | None:
        """Take the most recent change, to undo it, or return ``None`` if there
        is none."""
        return self._steps.pop() if self._steps else None

    @property
    def last(self) -> T | None:
        """The most recent change, without taking it."""
        return self._steps[-1] if self._steps else None

    def replace_last(self, step: T) -> None:
        """Replace the most recent step, as continued typing does when it adds
        to it (which, being a new change, also forgets whatever could be
        redone)."""
        if self._steps:
            self._steps[-1] = step
        self._undone.clear()

    def clear(self) -> None:
        """Forget every change, and whatever could be redone (when new text is
        set, for example)."""
        self._steps.clear()
        self._undone.clear()
