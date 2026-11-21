"""The desktop's capped inbox of application messages."""

import threading
from collections import deque
from multiprocessing.connection import Connection

from dasha.protocol import Message, ProtocolError, close, decode

MIB = 1024 * 1024


class Inbox:
    """Messages from every application, capped in bytes."""

    max_bytes_per_application: int = 64 * MIB
    """Most bytes waiting per application."""
    max_bytes: int = 256 * MIB
    """Most bytes waiting in all."""
    recheck: float = 0.1
    """Seconds between closed-connection checks."""

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
        """Bytes waiting.

        :param connection: One connection, or ``None`` for all.
        """
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
        """Add a message, waiting while over a cap.

        :param connection: The sending connection.
        :param data: The message bytes, or ``None`` if it ended.
        """
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
        """The oldest message and its connection, or ``None``."""
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
