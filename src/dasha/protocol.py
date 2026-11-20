"""How the desktop and its applications talk to each other: JSON messages
over a ``multiprocessing.connection`` connection.

Each message is a JSON object with a ``"type"``, sent as a single block of
UTF-8 bytes. JSON is used rather than pickles because the two ends may run
different versions of Python (such as an application in its own virtual
environment), and because nothing in a message can run code.
The ``hello`` message that an application sends first gives the range of
versions it speaks, and the desktop answers in ``welcome`` with the highest
version that both ends speak (``agree_version``), or refuses an application
with which it has none in common.

Window contents are sent as rows of runs: ``[text, style]`` pairs, where
``style`` is an index into a list of styles sent alongside, so that a row
in a single colour is one short run.
"""

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
"""The version of the protocol, which is increased whenever a message
changes in a way that the other end would notice.

1. The first release.
2. A theme (in ``welcome`` and ``theme``) may have the roles added since
   (``theme.NEWER_ROLES``): ``tabs.disabled``. An application of version 1
   refuses a theme with a role it does not know, so it is sent none."""

MINIMUM_VERSION = 1
"""The oldest version of the protocol still understood, which is raised
only when support for an old version is dropped."""

WINDOW_STYLES = (
    "frame_style",
    "inactive_frame_style",
    "adjusting_frame_style",
    "body_style",
    "button_style",
    "resize_grip_style",
    "scrollbar_style",
)
"""The ``Window`` attributes that an application can set for the desktop to
draw its window's frame in."""

ADDRESS_VARIABLE = "DASHA_ADDRESS"
"""The environment variable that tells a started application where its
desktop is listening. The key to connect with arrives on the application's
standard input."""

type Message = dict[str, Any]
"""A decoded message: always has a ``"type"``."""

type Cell = tuple[str, Style]


MAX_MESSAGE = 16 * 1024 * 1024
"""The largest size of a single message, in bytes. This leaves room for a
large clipboard, while ensuring that a message of gigabytes (from an
application that has gone wrong, or was written to do harm) cannot use up
the other end's memory. A longer message ends the connection."""


MAX_DEPTH = 100
"""How deeply a message's lists and objects may nest. The deepest that
Dasha Framework sends, menus with submenus ``remote.MAX_MENU_DEPTH`` deep, nest about
half as far. Deeper messages are refused whatever Python's ``json`` could
read, as code that walks a message must not run out of recursion."""

_STRING = re.compile(rb'"(?:[^"\\]|\\.)*"', re.DOTALL)
_NOT_BRACKETS = bytes(sorted(set(range(256)) - set(b"[]{}")))
_INNERMOST = re.compile(rb"\[\]|\{\}")


class ProtocolError(ValueError):
    """A message that cannot be understood."""


def _too_deep(data: bytes) -> bool:
    """Whether the lists and objects in ``data`` nest deeper than
    ``MAX_DEPTH``: with its strings left out, only its brackets kept, and
    the innermost pairs taken away a level at a time."""
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
    """The highest version of the protocol that both this end and the sender
    of ``hello`` speak, or ``None`` if they have none in common. The
    sender's ``"versions"`` is the range it speaks, ``[oldest, newest]``;
    without one, it speaks its ``"version"`` alone."""
    versions = hello.get("versions", [hello.get("version")] * 2)
    if not isinstance(versions, list) or len(versions) != 2:
        return None
    if any(isinstance(value, bool) or not isinstance(value, int) for value in versions):
        return None
    oldest, newest = versions
    agreed = min(newest, PROTOCOL_VERSION)
    return agreed if agreed >= max(oldest, MINIMUM_VERSION) else None


def encode(kind: str, **fields: object) -> bytes:
    """A message of type ``kind``, encoded as the bytes to send."""
    return json.dumps({"type": kind, **fields}, separators=(",", ":")).encode("utf-8")


def send(connection: Connection, kind: str, **fields: object) -> None:
    """Send one message of type ``kind``."""
    connection.send_bytes(encode(kind, **fields))


CLOSED_UNDER_IT = (OSError, TypeError)
"""What using a connection raises once it has gone: ``OSError``, or
``TypeError`` from ``multiprocessing`` when another thread closed it while
it was being used (its handle is then ``None``)."""


_CLOSING = threading.Lock()


class Closable(Protocol):  # pylint: disable=too-few-public-methods
    """A connection, of whichever kind the system gives (on Windows, a
    listener accepts a ``PipeConnection``)."""

    def close(self) -> None:
        """Close it."""


def close(connection: Closable) -> None:
    """Close a connection, once, whichever thread gets there first.
    ``Connection.close`` is not safe from two threads at once: both could
    close its handle, and the second would then close whatever has since
    been given that number (another application's connection, say)."""
    with _CLOSING:
        try:
            connection.close()
        except OSError:
            pass  # closed under it already


def refuse(connection: Connection, reason: str) -> None:
    """Tell a connection why it is refused, then close it."""
    try:
        send(connection, "refuse", reason=reason)
    except CLOSED_UNDER_IT:
        pass  # gone already
    close(connection)


def decode(data: bytes) -> Message:
    """A message, decoded from the bytes it was sent as."""
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
    """Wait for the next message. Raises ``EOFError`` once the other end
    has gone, and ``OSError`` for a message longer than ``MAX_MESSAGE``."""
    return decode(connection.recv_bytes(MAX_MESSAGE))


class TimedConnection:
    """A connection for the handshake (``deliver_challenge`` and
    ``answer_challenge``, which only send and receive), on which every
    receive waits no later than a deadline. Closing a connection from
    another thread does not end a wait on every system, but this does."""

    def __init__(self, connection: Connection, seconds: float) -> None:
        self._connection = connection
        self._deadline = time.monotonic() + seconds

    def send_bytes(self, data: bytes) -> None:
        """Send bytes, as the underlying connection does."""
        self._connection.send_bytes(data)

    def recv_bytes(self, maxlength: int | None = None) -> bytes:
        """Receive bytes, as the underlying connection does, if something
        arrives in time. Otherwise, raises ``TimeoutError`` (an
        ``OSError``)."""
        left = self._deadline - time.monotonic()
        if left <= 0 or not self._connection.poll(left):
            raise TimeoutError("no answer to the handshake in time")
        return self._connection.recv_bytes(maxlength)


# Values inside messages


def encode_colour(colour: Colour | None) -> int | str | None:
    """A colour, encoded as its number, ``"#rrggbb"`` for an RGB colour, or
    ``None`` for the default colour."""
    return colour.hex if isinstance(colour, Rgb) else colour


def encode_style(style: Style) -> list[object]:
    """A style, encoded as ``[foreground, background, bold, reverse,
    underline]``, with colours as ``encode_colour`` encodes them."""
    return [
        encode_colour(style.foreground),
        encode_colour(style.background),
        style.bold,
        style.reverse,
        style.underline,
    ]


def decode_colour(value: Any) -> Colour | None:
    """A colour from a message: ``None`` (the default colour), a number
    from 0 to 255, or an RGB colour, ``"#rrggbb"`` (or ``"#rgb"``). Raises
    ``ProtocolError`` for anything else, which would otherwise only fail
    later, when the screen is drawn."""
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
    """The style that ``encode_style`` encoded as this list. Raises
    ``ProtocolError`` for an invalid colour (see ``decode_colour``)."""
    foreground, background, bold, reverse, underline = data
    return Style(
        foreground=decode_colour(foreground),
        background=decode_colour(background),
        bold=bool(bold),
        reverse=bool(reverse),
        underline=bool(underline),
    )


def encode_rect(rect: Rect) -> list[int]:
    """A rectangle, encoded as ``[row, column, height, width]``."""
    return [rect.row, rect.column, rect.height, rect.width]


LARGEST = 10_000
"""The largest size or position allowed in a message: more than any
screen, but small enough that a window claiming to be 10**30 cells tall
cannot keep the other end drawing it forever."""


def bounded(value: Any, smallest: int = -LARGEST) -> int:
    """A number from a message, kept between ``smallest`` and
    ``LARGEST``."""
    return max(smallest, min(LARGEST, int(value)))


def decode_rect(data: Sequence[Any]) -> Rect:
    """The rectangle that ``encode_rect`` encoded as this list, with its
    numbers kept within range (``bounded``)."""
    row, column, height, width = (bounded(value) for value in data)
    return Rect(row, column, height, width)


def encode_mouse(event: MouseEvent) -> dict[str, object]:
    """A mouse event, encoded as an object holding its fields."""
    return asdict(event)


def decode_mouse(data: dict[str, Any]) -> MouseEvent:
    """The mouse event that ``encode_mouse`` encoded."""
    return MouseEvent(**data)


class StyleTable:  # pylint: disable=too-few-public-methods
    """The styles used by the rows of one message, each of which is sent
    only once."""

    def __init__(self) -> None:
        self._index: dict[Style, int] = {}
        self.styles: list[list[object]] = []
        """The table itself, to send with the rows."""

    def index(self, style: Style) -> int:
        """The style's number in the table, adding the style if it is new."""
        number = self._index.get(style)
        if number is None:
            number = self._index[style] = len(self.styles)
            self.styles.append(encode_style(style))
        return number


def encode_row(cells: Sequence[Cell], table: StyleTable) -> list[list[object]]:
    """A row of cells, encoded as runs of text in a single style:
    ``[[text, style number], ...]``."""
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
    """The cells of a row encoded by ``encode_row``."""
    cells: list[Cell] = []
    for text, number in runs:
        style = styles[number]
        cells.extend((char, style) for char in text)
    return cells
