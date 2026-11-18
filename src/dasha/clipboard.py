"""The clipboard, which holds one item at a time and is shared by
everything in Dasha Framework.

Each item has a type, written in the same way as a MIME type
(``"text/plain"``), so that the clipboard can also hold other things, such
as binary data or files. Code that pastes asks only for the types it
understands, and ignores anything else; a text box, for example, accepts
``TEXT`` and nothing more.

``CLIPBOARD`` is the clipboard everything uses unless told otherwise::

    from dasha.clipboard import CLIPBOARD, ClipboardItem

    CLIPBOARD.copy_text(text="hello")
    CLIPBOARD.text                        # "hello"
    CLIPBOARD.copy(
        item=ClipboardItem(type="application/octet-stream", data=b"\\x00\\x01")
    )
    CLIPBOARD.text                        # None: not text any more

This is Dasha Framework's own clipboard, not the operating system's, which a
program running over SSH could not reach in any case.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

TEXT = "text/plain"
"""The type of plain text, whose data is a ``str``."""


@dataclass(frozen=True)
class ClipboardItem:
    """An item on the clipboard: its ``type``, its ``data``, and any other
    ``metadata`` that the code pasting it might want to know (such as where
    it came from)."""

    type: str
    data: object
    metadata: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.type == TEXT and not isinstance(self.data, str):
            raise TypeError(f"{TEXT} data must be a str")


class Clipboard:
    """Holds the item most recently cut or copied."""

    def __init__(self) -> None:
        self._item: ClipboardItem | None = None
        self.listeners: list[Callable[["Clipboard"], object]] = []
        """Called with the clipboard whenever its contents change."""

    @property
    def item(self) -> ClipboardItem | None:
        """What is on the clipboard, if anything."""
        return self._item

    def copy(self, item: ClipboardItem) -> None:
        """Put an item on the clipboard, replacing what was there."""
        self._item = item
        self._changed()

    def copy_text(self, text: str, **metadata: object) -> None:
        """Put text on the clipboard."""
        self.copy(ClipboardItem(TEXT, text, MappingProxyType(dict(metadata))))

    def clear(self) -> None:
        """Empty the clipboard."""
        self._item = None
        self._changed()

    def get(self, *types: str) -> ClipboardItem | None:
        """The item on the clipboard, if it is one of the given types (or of
        any type, if none are given); otherwise ``None``."""
        item = self._item
        if item is None or (types and item.type not in types):
            return None
        return item

    @property
    def text(self) -> str | None:
        """The text on the clipboard, or ``None`` if it holds something else,
        or nothing."""
        item = self.get(TEXT)
        return None if item is None else str(item.data)

    def _changed(self) -> None:
        for listener in list(self.listeners):
            listener(self)


CLIPBOARD = Clipboard()
"""The clipboard shared by everything in Dasha Framework."""
