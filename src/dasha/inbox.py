"""The desktop's inbox: messages from applications, waiting to be handled.

Each application's connection has a thread of its own that reads its
messages (``AppServer._read_all``) and puts them here; the desktop takes
them out on each pass of its loop (``AppServer.poll``). An application can
send faster than the desktop handles messages, so what is waiting is
counted, in bytes, and capped:

- **Per application** (``max_bytes_per_application``): once an
  application has that much waiting, its reader waits for the desktop to
  catch up. The pipe then fills, and the application's own sends wait, so
  an application in a tight loop slows to the desktop's pace instead of
  using up its memory.
- **In all** (``max_bytes``): once everything waiting comes to that much,
  every application with something already waiting waits too. One with
  nothing waiting can always add a message, so a flood from one
  application never holds up the others.

Messages wait as the bytes that were sent, and are decoded only as the
desktop takes them, so what is counted is what is held. So at most
``max_bytes_per_application`` (or one message, if that is larger) waits for
any one application, and ``max_bytes`` plus one message for each other
application waits in all.
"""

import threading
from collections import deque
from multiprocessing.connection import Connection

from dasha.protocol import Message, ProtocolError, close, decode

MIB = 1024 * 1024


class Inbox:
    """Messages waiting for the desktop, from every application, in the
    order they arrived, counted and capped in bytes (see the module's
    description)."""

    max_bytes_per_application: int = 64 * MIB
    """The most that may wait for one application before its reader waits
    (unless nothing of its is waiting yet)."""
    max_bytes: int = 256 * MIB
    """The most that may wait in all before readers wait (except those with
    nothing waiting yet)."""
    recheck: float = 0.1
    """How often, in seconds, a waiting reader checks whether its
    connection has been closed."""

    def __init__(self) -> None:
        self._messages: deque[tuple[Connection, bytes | None]] = deque()
        self._bytes: dict[int, int] = {}
        self._total = 0
        self._changed = threading.Condition()
        self._stopped = False

    def __len__(self) -> int:
        with self._changed:
            return len(self._messages)

    def waiting_bytes(self, connection: Connection | None = None) -> int:
        """How many bytes are waiting: from one connection, or in all."""
        with self._changed:
            if connection is None:
                return self._total
            return self._bytes.get(id(connection), 0)

    def _full(self, connection: Connection, size: int) -> bool:
        mine = self._bytes.get(id(connection), 0)
        if mine == 0:
            return False  # one message at least, whatever its size
        if mine + size > self.max_bytes_per_application:
            return True
        return self._total + size > self.max_bytes

    def put(self, connection: Connection, data: bytes | None) -> None:
        """Add a message as it was sent (``None``: the connection has
        ended), first waiting while it would go over a cap. Gives up
        waiting, dropping the message, if the connection is closed or the
        inbox stopped meanwhile. Called by each connection's reader
        thread."""
        size = 0 if data is None else len(data)
        with self._changed:
            while size and self._full(connection, size):
                if self._stopped or connection.closed:
                    return
                self._changed.wait(self.recheck)
            self._messages.append((connection, data))
            if size:
                self._bytes[id(connection)] = self._bytes.get(id(connection), 0) + size
                self._total += size

    def get(self) -> tuple[Connection, Message | None] | None:
        """The oldest waiting message, decoded, and its connection; ``None``
        if nothing is waiting. The message is ``None`` when the connection
        has ended, or sent something that is not a message, in which case
        the connection is closed (its application will be ended)."""
        with self._changed:
            if not self._messages:
                return None
            connection, data = self._messages.popleft()
            if data is not None:
                left = self._bytes[id(connection)] - len(data)
                if left:
                    self._bytes[id(connection)] = left
                else:
                    del self._bytes[id(connection)]
                self._total -= len(data)
                self._changed.notify_all()
        if data is None:
            return connection, None
        try:
            return connection, decode(data)
        except ProtocolError:
            close(connection)
            return connection, None

    def stop(self) -> None:
        """Stop every waiting reader (the desktop is shutting down)."""
        with self._changed:
            self._stopped = True
            self._changed.notify_all()
