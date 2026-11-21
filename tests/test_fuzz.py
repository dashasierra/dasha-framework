"""Fuzz tests for untrusted input."""

import json
import random
import unittest
from multiprocessing.connection import Connection
from typing import Any, cast

from dasha.canvas import Canvas
from dasha.events import InputDecoder, KeyReleaseEvent, MouseEvent, PasteEvent
from dasha.hosting import AppHost, AppServer
from dasha.manager import PresentationManager
from dasha.protocol import MAX_DEPTH, ProtocolError, decode
from tests.support import pipe

# Pieces terminals really send, so random input reaches the sequence parser
# and not only the plain-character path.
_INPUT_PIECES = (
    "\x1b", "\x1b[", "\x1bO", "\x1b[<", "[", "O", ";", ":", "<", "~", "u",
    "M", "m", "A", "Z", "0", "1", "2", "5", "27", "64", "200~", "201~",
    "\x1b[200~", "\x1b[201~", "\x1b[<0;10;5M", "\x1b[1;5C", "\x1b[27;5;9~",
    "\x1b[9;5u", "\x1b[32;1:3u", "\x1b\x1bOR", "\r", "\n", "\t", "\x7f",
    "\x00", "\x03", "a", "é", "€", "\U0001f600", "\udcff", "9" * 40,
    "1114112", "99999999999999999999",
)  # fmt: skip

_SEEDS = range(20)


def _random_text(rng: random.Random) -> str:
    """Random terminal input.

    :param rng: Random source.
    """
    parts: list[str] = []
    for _ in range(rng.randint(0, 40)):
        roll = rng.random()
        if roll < 0.6:
            parts.append(rng.choice(_INPUT_PIECES))
        elif roll < 0.8:
            parts.append(chr(rng.randint(0, 0x7F)))
        else:
            parts.append(chr(rng.randint(0, 0x10FFFF)))
    return "".join(parts)


def _split(rng: random.Random, text: str) -> list[str]:
    """Text cut at random places.

    :param rng: Random source.
    :param text: The text.
    """
    cuts = sorted(rng.sample(range(len(text) + 1), min(len(text), rng.randint(0, 6))))
    pieces, start = [], 0
    for cut in cuts:
        pieces.append(text[start:cut])
        start = cut
    pieces.append(text[start:])
    return pieces


def _valid_event(event: object) -> bool:
    if isinstance(event, str):
        return bool(event)
    if isinstance(event, MouseEvent):
        return isinstance(event.row, int) and isinstance(event.column, int)
    if isinstance(event, PasteEvent):
        return isinstance(event.text, str)
    if isinstance(event, KeyReleaseEvent):
        return isinstance(event.key, str) and bool(event.key)
    return False


class InputDecoderFuzzTests(unittest.TestCase):
    """Random terminal input never makes the decoder raise."""

    def check(self, decoder: InputDecoder, events: list[Any], data: str) -> None:
        """Every event is a real event.

        :param decoder: The decoder.
        :param events: Events decoded.
        :param data: The input.
        """
        for event in events:
            self.assertTrue(_valid_event(event), f"{event!r} from {data!r}")
        self.assertIsInstance(decoder.is_pending, bool)

    def test_random_input_in_random_pieces(self) -> None:
        """Random input in random pieces."""
        for seed in _SEEDS:
            rng = random.Random(seed)
            for _ in range(200):
                text = _random_text(rng)
                decoder = InputDecoder()
                try:
                    for piece in _split(rng, text):
                        self.check(decoder, decoder.feed(piece), text)
                        if rng.random() < 0.2:
                            self.check(decoder, decoder.flush(), text)
                    self.check(decoder, decoder.flush(), text)
                except Exception as error:  # pylint: disable=broad-exception-caught
                    self.fail(f"seed {seed}: {text!r} raised {error!r}")

    def test_random_bytes_decoded_as_a_terminal_would(self) -> None:
        """Random bytes, decoded with replacement as the backends do."""
        for seed in _SEEDS:
            rng = random.Random(seed)
            for _ in range(100):
                data = rng.randbytes(rng.randint(0, 64))
                text = data.decode("utf-8", errors="replace")
                decoder = InputDecoder()
                try:
                    self.check(decoder, decoder.feed(text) + decoder.flush(), text)
                except Exception as error:  # pylint: disable=broad-exception-caught
                    self.fail(f"seed {seed}: {data!r} raised {error!r}")

    def test_numbers_too_long_to_convert(self) -> None:
        """Numbers too long to convert."""
        for text in (
            "\x1b[" + "9" * 5000 + "~",
            "\x1b[1;" + "9" * 5000 + "A",
            "\x1b[" + "9" * 5000 + "u",
            "\x1b[" + "9" * 5000 + ":3u",
            "\x1b[<" + "9" * 5000 + ";1;1M",
            "\x1b\x1b[" + "9" * 5000 + "~",
        ):
            with self.subTest(text=text[:12]):
                decoder = InputDecoder()
                events = decoder.feed(text) + decoder.flush()
                self.check(decoder, events, text)
                self.assertFalse(decoder.is_pending)


def _random_json(rng: random.Random, depth: int = 0) -> Any:
    """Any JSON value.

    :param rng: Random source.
    :param depth: Nesting depth.
    """
    roll = rng.randint(0, 11 if depth < 3 else 7)
    simple: list[Any] = [
        None,
        rng.random() < 0.5,
        rng.randint(-5, 50),
        rng.choice((-(10**30), 10**30, 2**63, -1, 0)),
        rng.choice((float("nan"), float("inf"), -float("inf"), 1.5, -0.5)),
        "".join(chr(rng.randint(0, 0x2FF)) for _ in range(rng.randint(0, 8))),
        rng.choice(("window", "paint", "dialog", "popup", "exit", "front", "")),
        rng.choice((0, 1, 2)),
    ]
    if roll < len(simple):
        return simple[roll]
    if roll < 10:
        return [_random_json(rng, depth + 1) for _ in range(rng.randint(0, 5))]
    return {
        rng.choice(("type", "id", "items", "label", "x")): _random_json(rng, depth + 1)
        for _ in range(rng.randint(0, 4))
    }


class ProtocolDecodeFuzzTests(unittest.TestCase):
    """Only ``ProtocolError`` comes out of ``protocol.decode``."""

    def decode(self, data: bytes) -> None:
        """Decode, allowing only messages or ``ProtocolError``.

        :param data: The bytes.
        """
        try:
            message = decode(data)
        except ProtocolError:
            return
        except Exception as error:  # pylint: disable=broad-exception-caught
            self.fail(f"{data[:80]!r} raised {error!r}")
        self.assertIsInstance(message, dict)
        self.assertIsInstance(message["type"], str)

    def test_random_bytes(self) -> None:
        """Random bytes, and random bytes after a real message's start."""
        for seed in _SEEDS:
            rng = random.Random(seed)
            for _ in range(100):
                data = rng.randbytes(rng.randint(0, 64))
                self.decode(data)
                self.decode(b'{"type":"paint",' + data)

    def test_random_json(self) -> None:
        """Random JSON values, objects with random types among them."""
        for seed in _SEEDS:
            rng = random.Random(seed)
            for _ in range(100):
                value = _random_json(rng)
                self.decode(json.dumps(value).encode("utf-8"))
                self.decode(json.dumps({"type": value}).encode("utf-8"))

    def test_json_python_cannot_read(self) -> None:
        """JSON Python cannot read."""
        for data in (
            b"[" * 100_000,
            b'{"type":"x","a":' + b"[" * 100_000 + b"]" * 100_000 + b"}",
            b'{"type":"x","n":' + b"9" * 5000 + b"}",
        ):
            with self.subTest(data=data[:20]):
                with self.assertRaises(ProtocolError):
                    decode(data)

    def test_nesting_limit(self) -> None:
        """The nesting limit."""

        def nested(depth: int) -> bytes:
            inner = b"[" * (depth - 1) + b"]" * (depth - 1)
            return b'{"type":"x","a":' + inner + b"}"

        self.assertEqual(decode(nested(MAX_DEPTH))["type"], "x")
        with self.assertRaises(ProtocolError):
            decode(nested(MAX_DEPTH + 1))
        brackets = json.dumps({"type": "x", "s": "[{" * 500 + '\\"]'}).encode()
        self.assertEqual(decode(brackets)["type"], "x")
        flat = json.dumps({"type": "x", "a": [[1], {"b": [2]}] * 500}).encode()
        self.assertEqual(len(decode(flat)["a"]), 1000)


def _window(rng: random.Random) -> dict[str, Any]:
    return {
        "type": "window", "id": rng.choice((1, 2)), "title": "Hello",
        "rect": [2, 2, 6, 30], "maximised": False,
        "flags": [True, True, True, True],
        "look": rng.choice(("window", "dialog", "popup")),
        "modal": rng.random() < 0.3, "outside": False, "status": "Hi",
        "hints": [["F1", "Help"]], "footer": [], "content": [28, 4], "scroll": [0, 0],
    }  # fmt: skip


def _menus(_rng: random.Random) -> dict[str, Any]:
    item = {
        "label": "~Open", "enabled": True, "shortcut": "ctrl+o", "status": "",
        "separator": False, "submenu": None,
    }  # fmt: skip
    sub = {"title": "More", "items": [item]}
    return {
        "type": "menus",
        "menus": [{"title": "~File", "items": [item, {**item, "submenu": sub}]}],
    }


_MESSAGES = (
    _window,
    lambda rng: {
        "type": "paint", "id": rng.choice((1, 2)), "size": [28, 4],
        "styles": [[7, 1, False, False, False]], "rows": [[0, [["Hi", 0]]]],
        "cursor": [0, 1],
    },  # fmt: skip
    _menus,
    lambda rng: {"type": "close", "id": rng.choice((1, 2))},
    lambda rng: {
        "type": "request", "id": rng.choice((1, 2)),
        "op": rng.choice(("front", "move", "resize", "maximise", "minimise",
                          "restore", "toggle_maximise", "send_to_back",
                          "next_window", "previous_window")),
    },  # fmt: skip
    lambda rng: {"type": "clipboard", "text": "copied"},
    lambda rng: {"type": "answer", "ok": True},
    lambda rng: {"type": "nonsense"},
)


def _mutate(rng: random.Random, value: Any, rate: float) -> Any:
    """A value with random parts swapped or dropped.

    :param rng: Random source.
    :param value: The value.
    :param rate: Mutation rate.
    """
    if rng.random() < rate:
        return _random_json(rng)
    if isinstance(value, dict):
        mutated = {}
        for key, item in value.items():
            if key == "type" and rng.random() > rate / 4:
                mutated[key] = item  # mostly a real type, to get past it
            elif rng.random() >= rate / 3:
                mutated[key] = _mutate(rng, item, rate)
        return mutated
    if isinstance(value, list):
        return [_mutate(rng, item, rate) for item in value]
    return value


class DispatchFuzzTests(unittest.TestCase):
    """Random messages never make the desktop raise."""

    def start(self) -> tuple[PresentationManager, AppServer, AppHost, Connection]:
        """A desktop with one connected application, as ``_greet`` leaves it."""
        manager = PresentationManager()
        manager.handle_resize(80, 24)
        server = AppServer(manager)
        self.addCleanup(server.stop_all, 0)
        manager.server = server
        host = AppHost(server, "tests.hosted_apps:Hello", "Hello")
        app_end, desktop_end = pipe()
        host.connected(desktop_end)
        server.hosts.append(host)
        manager.add_application(host.application)
        # pylint: disable-next=protected-access
        server._by_connection[id(desktop_end)] = host
        return manager, server, host, app_end

    def test_random_messages(self) -> None:
        """Random messages."""
        for seed in _SEEDS:
            rng = random.Random(seed)
            for run in range(15):
                manager, server, host, app_end = self.start()
                connection = cast(Connection, host.connection)
                log: list[Any] = []
                try:
                    for _ in range(rng.randint(1, 8)):
                        message = _mutate(rng, rng.choice(_MESSAGES)(rng), 0.15)
                        if not isinstance(message, dict):
                            continue
                        # As it would arrive: through JSON and decode.
                        try:
                            message = decode(json.dumps(message).encode("utf-8"))
                        except ProtocolError:
                            continue
                        log.append(message)
                        # pylint: disable-next=protected-access
                        server._dispatch(connection, message)
                        server.flush()
                        manager.compose(Canvas(80, 24))
                        if manager.bar_menus():
                            manager.handle_key("f10")
                            manager.compose(Canvas(80, 24))
                            manager.handle_key("down")
                            manager.compose(Canvas(80, 24))
                            manager.handle_key("escape")
                            manager.handle_key("escape")
                        if host.ended:
                            break
                except Exception as error:  # pylint: disable=broad-exception-caught
                    self.fail(f"seed {seed} run {run}: {log!r} raised {error!r}")
                finally:
                    host.end_now()
                    app_end.close()
                for notice in server.notices:
                    self.assertEqual(notice[0], "Application stopped")

    def test_numbers_out_of_reach(self) -> None:
        """Out-of-reach numbers."""
        huge = 10**30
        for changes, ends in (
            ({"rect": [0, 0, huge, huge]}, False),
            ({"rect": [-huge, -huge, 5, 5], "content": [huge, huge]}, False),
            ({"scroll": [huge, -huge]}, False),
            ({"rect": [0, float("inf"), 5, 5]}, True),
        ):
            with self.subTest(changes=changes):
                manager, server, host, app_end = self.start()
                connection = cast(Connection, host.connection)
                message = {**_window(random.Random(0)), "id": 1, **changes}
                message = decode(json.dumps(message).encode("utf-8"))
                # pylint: disable=protected-access
                server._dispatch(connection, message)
                server._dispatch(
                    connection,
                    {"type": "paint", "id": 1, "size": [huge, huge], "styles": [],
                     "rows": [], "cursor": [huge, huge]},  # fmt: skip
                )
                # pylint: enable=protected-access
                manager.compose(Canvas(80, 24))
                self.assertEqual(host.ended, ends)
                host.end_now()
                app_end.close()


if __name__ == "__main__":
    unittest.main()
