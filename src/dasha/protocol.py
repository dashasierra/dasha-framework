"""JSON messages between the desktop and applications."""

import json
import re
import threading
import time
from collections.abc import Sequence
from dataclasses import asdict
from multiprocessing.connection import Connection
from typing import Any, Protocol

from dasha.canvas import Rect
from dasha.events import MouseEvent
from dasha.style import Colour, Rgb, Style

PROTOCOL_VERSION = 2
"""The protocol version."""

MINIMUM_VERSION = 1
"""Oldest protocol version understood."""

WINDOW_STYLES = (
    "frame_style",
    "inactive_frame_style",
    "adjusting_frame_style",
    "body_style",
    "button_style",
    "resize_grip_style",
    "scrollbar_style",
)
"""Window attributes an application may set."""

ADDRESS_VARIABLE = "DASHA_ADDRESS"
"""Environment variable with the desktop's address."""

type Message = dict[str, Any]
"""A decoded message: always has a ``"type"``."""

type Cell = tuple[str, Style]


MAX_MESSAGE = 16 * 1024 * 1024
"""Largest message size, in bytes."""


MAX_DEPTH = 100
"""Deepest nesting allowed in a message."""

_STRING = re.compile(rb'"(?:[^"\\]|\\.)*"', re.DOTALL)
_NOT_BRACKETS = bytes(sorted(set(range(256)) - set(b"[]{}")))
_INNERMOST = re.compile(rb"\[\]|\{\}")


class ProtocolError(ValueError):
    """A message that cannot be understood."""


def _too_deep(data: bytes) -> bool:
    """Whether data nests deeper than ``MAX_DEPTH``.

    :param data: The message bytes.
    """
    if data.count(b"[") + data.count(b"{") <= MAX_DEPTH:
        return False
    brackets = _STRING.sub(b"", data).translate(None, _NOT_BRACKETS)
    for _ in range(MAX_DEPTH):
        brackets, removed = _INNERMOST.subn(b"", brackets)
        if not brackets:
            return False
        if not removed:
            return True  # unbalanced: not JSON, so not a message either
    return True


def agree_version(hello: Message) -> int | None:
    """The highest common protocol version, or ``None``.

    :param hello: The ``hello`` message.
    """
    versions = hello.get("versions", [hello.get("version")] * 2)
    if not isinstance(versions, list) or len(versions) != 2:
        return None
    if any(isinstance(value, bool) or not isinstance(value, int) for value in versions):
        return None
    oldest, newest = versions
    agreed = min(newest, PROTOCOL_VERSION)
    return agreed if agreed >= max(oldest, MINIMUM_VERSION) else None


def encode(kind: str, **fields: object) -> bytes:
    """Encode a message.

    :param kind: Message type.
    :param fields: Message fields.
    """
    return json.dumps({"type": kind, **fields}, separators=(",", ":")).encode("utf-8")


def send(connection: Connection, kind: str, **fields: object) -> None:
    """Send a message.

    :param connection: The connection.
    :param kind: Message type.
    :param fields: Message fields.
    """
    connection.send_bytes(encode(kind, **fields))


CLOSED_UNDER_IT = (OSError, TypeError)
"""What a closed connection raises."""


_CLOSING = threading.Lock()


class Closable(Protocol):  # pylint: disable=too-few-public-methods
    """A closable connection."""

    def close(self) -> None:
        """Close it."""


def close(connection: Closable) -> None:
    """Close a connection once; thread-safe.

    :param connection: The connection.
    """
    with _CLOSING:
        try:
            connection.close()
        except OSError:
            pass  # closed under it already


def refuse(connection: Connection, reason: str) -> None:
    """Refuse a connection with a reason.

    :param connection: The connection.
    :param reason: Why it is refused.
    """
    try:
        send(connection, "refuse", reason=reason)
    except CLOSED_UNDER_IT:
        pass  # gone already
    close(connection)


def decode(data: bytes) -> Message:
    """Decode a message.

    :param data: The message bytes.
    """
    if _too_deep(data):
        raise ProtocolError(f"not a message: nested deeper than {MAX_DEPTH}")
    try:
        message = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError) as error:
        # ValueError covers bad UTF-8 and bad JSON, and numbers too long to
        # convert; RecursionError, nesting deeper than Python can follow.
        raise ProtocolError(f"not a message: {error}") from error
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ProtocolError("a message must be an object with a type")
    return message


def receive(connection: Connection) -> Message:
    """Wait for the next message.

    :param connection: The connection.
    """
    return decode(connection.recv_bytes(MAX_MESSAGE))


class TimedConnection:
    """A handshake connection with a deadline.

    :param connection: The connection.
    :param seconds: Seconds until the deadline.
    """

    def __init__(self, connection: Connection, seconds: float) -> None:
        self._connection = connection
        self._deadline = time.monotonic() + seconds

    def send_bytes(self, data: bytes) -> None:
        """Send bytes.

        :param data: The bytes.
        """
        self._connection.send_bytes(data)

    def recv_bytes(self, maxlength: int | None = None) -> bytes:
        """Receive bytes before the deadline.

        :param maxlength: Largest message allowed, if any.
        """
        left = self._deadline - time.monotonic()
        if left <= 0 or not self._connection.poll(left):
            raise TimeoutError("no answer to the handshake in time")
        return self._connection.recv_bytes(maxlength)


# Values inside messages


def encode_colour(colour: Colour | None) -> int | str | None:
    """Encode a colour.

    :param colour: The colour, or ``None`` for the default.
    """
    return colour.hex if isinstance(colour, Rgb) else colour


def encode_style(style: Style) -> list[object]:
    """Encode a style.

    :param style: The style.
    """
    return [
        encode_colour(style.foreground),
        encode_colour(style.background),
        style.bold,
        style.reverse,
        style.underline,
    ]


def decode_colour(value: Any) -> Colour | None:
    """Decode a colour.

    :param value: The encoded colour.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return Rgb.parse(value)
        except ValueError:
            raise ProtocolError(f"not a colour: {value[:20]!r}") from None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise ProtocolError(f"not a colour: {value!r}")
    return value


def decode_style(data: Sequence[Any]) -> Style:
    """Decode a style.

    :param data: The encoded style.
    """
    foreground, background, bold, reverse, underline = data
    return Style(
        foreground=decode_colour(foreground),
        background=decode_colour(background),
        bold=bool(bold),
        reverse=bool(reverse),
        underline=bool(underline),
    )


def encode_rect(rect: Rect) -> list[int]:
    """Encode a rect.

    :param rect: The rect.
    """
    return [rect.row, rect.column, rect.height, rect.width]


LARGEST = 10_000
"""Largest size or position in a message."""


def bounded(value: Any, smallest: int = -LARGEST) -> int:
    """A number from a message, kept in range.

    :param value: The number.
    :param smallest: Smallest allowed.
    """
    return max(smallest, min(LARGEST, int(value)))


def decode_rect(data: Sequence[Any]) -> Rect:
    """Decode a rect.

    :param data: The encoded rect.
    """
    row, column, height, width = (bounded(value) for value in data)
    return Rect(row, column, height, width)


def encode_mouse(event: MouseEvent) -> dict[str, object]:
    """Encode a mouse event.

    :param event: The mouse event.
    """
    return asdict(event)


def decode_mouse(data: dict[str, Any]) -> MouseEvent:
    """Decode a mouse event.

    :param data: The encoded event.
    """
    return MouseEvent(**data)


class StyleTable:  # pylint: disable=too-few-public-methods
    """Styles used by one message."""

    def __init__(self) -> None:
        self._index: dict[Style, int] = {}
        self.styles: list[list[object]] = []
        """The table itself, to send with the rows."""

    def index(self, style: Style) -> int:
        """A style's index, adding it if new.

        :param style: The style.
        """
        number = self._index.get(style)
        if number is None:
            number = self._index[style] = len(self.styles)
            self.styles.append(encode_style(style))
        return number


def encode_row(cells: Sequence[Cell], table: StyleTable) -> list[list[object]]:
    """Encode a row of cells as styled runs.

    :param cells: The cells.
    :param table: The message's style table.
    """
    runs: list[list[object]] = []
    text: list[str] = []
    current: Style | None = None
    for char, style in cells:
        if style != current and text:
            assert current is not None
            runs.append(["".join(text), table.index(current)])
            text = []
        current = style
        text.append(char)
    if text and current is not None:
        runs.append(["".join(text), table.index(current)])
    return runs


def decode_row(runs: Sequence[Any], styles: Sequence[Style]) -> list[Cell]:
    """Decode a row of cells.

    :param runs: The encoded runs.
    :param styles: The message's styles.
    """
    cells: list[Cell] = []
    for text, number in runs:
        style = styles[number]
        cells.extend((char, style) for char in text)
    return cells
