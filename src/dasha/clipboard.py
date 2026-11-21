"""The shared clipboard."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

TEXT = "text/plain"
"""The type of plain text, whose data is a ``str``."""


@dataclass(frozen=True)
class ClipboardItem:
    """A clipboard item."""

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
        """Put an item on the clipboard.

        :param item: The item.
        """
        self._item = item
        self._changed()

    def copy_text(self, text: str, **metadata: object) -> None:
        """Put text on the clipboard.

        :param text: The text.
        :param metadata: Extra details.
        """
        self.copy(ClipboardItem(TEXT, text, MappingProxyType(dict(metadata))))

    def clear(self) -> None:
        """Empty the clipboard."""
        self._item = None
        self._changed()

    def get(self, *types: str) -> ClipboardItem | None:
        """The item, if it is one of the types.

        :param types: Accepted types; none means any.
        """
        item = self._item
        if item is None or (types and item.type not in types):
            return None
        return item

    @property
    def text(self) -> str | None:
        """The clipboard's text, or ``None``."""
        item = self.get(TEXT)
        return None if item is None else str(item.data)

    def _changed(self) -> None:
        for listener in list(self.listeners):
            listener(self)


CLIPBOARD = Clipboard()
"""The clipboard shared by everything in Dasha Framework."""
