"""Tests for the desktop's inbox: messages waiting from applications,
counted in bytes and capped, so that an application sending in a tight loop
cannot use up the desktop's memory."""

# pylint: disable=protected-access

import threading
import time
import unittest
from multiprocessing.connection import Connection
from unittest import mock

from dasha.hosting import AppServer
from dasha.inbox import Inbox
from dasha.manager import PresentationManager
from dasha.protocol import encode
from tests.support import hosted, pipe

PING = encode("ping")


def connection() -> tuple[Connection, Connection]:
    """The desktop's end of a pipe, and the application's."""
    return pipe()


class InboxTests(unittest.TestCase):
    """An inbox with small caps."""

    def setUp(self) -> None:
        self.inbox = Inbox()
        self.inbox.max_bytes_per_application = 3 * len(PING)
        self.inbox.max_bytes = 5 * len(PING)
        self.inbox.recheck = 0.01
        self.app, app_end = connection()
        self.other, other_end = connection()
        for end in (self.app, app_end, self.other, other_end):
            self.addCleanup(end.close)

    def put_later(self, desktop_end: Connection, data: bytes) -> threading.Thread:
        """Put a message in a thread of its own, as a reader does; it may
        have to wait."""
        thread = threading.Thread(
            target=self.inbox.put, args=(desktop_end, data), daemon=True
        )
        thread.start()
        thread.join(0.2)
        return thread

    def test_counted(self) -> None:
        """Bytes waiting, for each connection and in all; taking a message
        decodes it and stops counting it."""
        self.inbox.put(self.app, PING)
        self.inbox.put(self.other, PING)
        self.inbox.put(self.app, PING)
        self.assertEqual(self.inbox.waiting_bytes(self.app), 2 * len(PING))
        self.assertEqual(self.inbox.waiting_bytes(), 3 * len(PING))
        self.assertEqual(len(self.inbox), 3)
        self.assertEqual(self.inbox.get(), (self.app, {"type": "ping"}))
        self.assertEqual(self.inbox.waiting_bytes(self.app), len(PING))
        self.inbox.get()
        self.inbox.get()
        self.assertEqual((self.inbox.waiting_bytes(), len(self.inbox)), (0, 0))
        self.assertIsNone(self.inbox.get())

    def test_one_application_capped(self) -> None:
        """Over its cap, an application's reader waits until the desktop
        takes some of its messages."""
        for _ in range(3):
            self.inbox.put(self.app, PING)
        waiting = self.put_later(self.app, PING)
        self.assertTrue(waiting.is_alive())
        self.assertEqual(self.inbox.waiting_bytes(self.app), 3 * len(PING))
        self.inbox.get()
        waiting.join(1)
        self.assertFalse(waiting.is_alive())
        self.assertEqual(self.inbox.waiting_bytes(self.app), 3 * len(PING))

    def test_a_message_bigger_than_the_cap(self) -> None:
        """Taken when nothing of the application's is waiting, so that no
        message can be held up for ever."""
        big = encode("clipboard", text="x" * 500)
        self.inbox.put(self.app, big)
        self.assertEqual(self.inbox.waiting_bytes(self.app), len(big))
        self.assertTrue(self.put_later(self.app, PING).is_alive())

    def test_all_applications_capped(self) -> None:
        """Over the cap in all, applications with something waiting wait;
        one with nothing waiting still gets a message in."""
        for _ in range(3):
            self.inbox.put(self.app, PING)
        self.inbox.put(self.other, PING)
        self.inbox.put(self.other, PING)  # 5 in all: the cap
        third, fourth = connection()
        self.addCleanup(third.close)
        self.addCleanup(fourth.close)
        self.inbox.put(third, PING)  # nothing of its waiting: in it goes
        self.assertTrue(self.put_later(self.other, PING).is_alive())
        self.assertEqual(self.inbox.waiting_bytes(), 6 * len(PING))

    def test_a_closed_connection_stops_waiting(self) -> None:
        """A reader waiting for an application that has been ended gives
        up, dropping the message."""
        for _ in range(3):
            self.inbox.put(self.app, PING)
        waiting = self.put_later(self.app, PING)
        self.app.close()
        waiting.join(1)
        self.assertFalse(waiting.is_alive())
        self.assertEqual(len(self.inbox), 3)

    def test_stopping(self) -> None:
        """Stopping the inbox (shutting down) releases every reader."""
        for _ in range(3):
            self.inbox.put(self.app, PING)
        waiting = self.put_later(self.app, PING)
        self.inbox.stop()
        waiting.join(1)
        self.assertFalse(waiting.is_alive())

    def test_the_end_of_a_connection_never_waits(self) -> None:
        """``None``, the connection ended, is always taken, and counts
        nothing."""
        for _ in range(3):
            self.inbox.put(self.app, PING)
        self.inbox.put(self.app, None)
        self.assertEqual(len(self.inbox), 4)
        self.assertEqual(self.inbox.waiting_bytes(self.app), 3 * len(PING))

    def test_not_a_message(self) -> None:
        """Taken as the connection ending, and the connection is closed so
        that its reader stops."""
        self.inbox.put(self.app, b"not json")
        self.assertEqual(self.inbox.get(), (self.app, None))
        self.assertTrue(self.app.closed)
        self.assertEqual(self.inbox.waiting_bytes(), 0)


class FloodTests(unittest.TestCase):
    """An application sending as fast as it can, read by the desktop's own
    reader thread."""

    def test_the_desktop_holds_no_more_than_the_cap(self) -> None:
        """The application is slowed to the desktop's pace: no more than
        its cap waits at any time, and every message arrives, in order."""
        manager = PresentationManager()
        manager.handle_resize(80, 24)
        server = AppServer(manager)
        manager.server = server
        server.inbox.max_bytes_per_application = 20 * len(encode("answer", ok=True))
        server.inbox.recheck = 0.01
        self.addCleanup(server.stop_all, 0)
        host, app_end = hosted(server, "Flood")
        assert host.connection is not None
        server._by_connection[id(host.connection)] = host
        count = 2000
        answered: list[bool] = []
        server.answered = lambda host, ok: answered.append(ok)  # type: ignore

        def send_all() -> None:
            for n in range(count):
                app_end.send_bytes(encode("answer", ok=n % 2 == 0))

        sending = threading.Thread(target=send_all, daemon=True)
        with mock.patch.object(server, "_authenticate", return_value=True):
            threading.Thread(
                target=server._read_all, args=(host.connection,), daemon=True
            ).start()
            sending.start()
            most = 0
            deadline = time.monotonic() + 20
            while len(answered) < count and time.monotonic() < deadline:
                most = max(most, server.inbox.waiting_bytes())
                server.poll()
                time.sleep(0.001)
        self.assertEqual(answered, [n % 2 == 0 for n in range(count)])
        self.assertLessEqual(most, server.inbox.max_bytes_per_application)
        self.assertGreater(most, 0)
        app_end.close()


if __name__ == "__main__":
    unittest.main()
