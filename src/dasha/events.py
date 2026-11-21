"""Terminal input decoding into events."""

import time
from dataclasses import dataclass
from typing import Protocol

ESC = "\x1b"

# A sequence that has not finished after this many characters is garbage.
_MAX_SEQUENCE_LENGTH = 32

PASTE_START = ESC + "[200~"
PASTE_END = ESC + "[201~"
"""Bracketed paste markers."""

PASTE_TIMEOUT = 0.5
"""Seconds to wait for more of an unfinished paste."""


@dataclass(frozen=True, slots=True)
class MouseEvent:
    """A mouse report."""

    action: str
    button: str
    row: int
    column: int
    shift: bool = False
    """Whether Shift was held down."""
    alt: bool = False
    """Whether Alt was held down."""
    ctrl: bool = False
    """Whether Ctrl was held down."""
    clicks: int = 1
    """Click count for a press."""


@dataclass(frozen=True, slots=True)
class PasteEvent:
    """Text pasted through the terminal."""

    text: str


@dataclass(frozen=True, slots=True)
class KeyReleaseEvent:
    """A key release."""

    key: str


type Event = str | MouseEvent | PasteEvent | KeyReleaseEvent
"""A key name, a mouse event, a paste or a key release."""

_SIMPLE = {
    "\t": "tab",
    "\r": "enter",
    "\n": "enter",
    "\x7f": "backspace",
    "\x08": "backspace",
    ESC: "escape",
}

# Final character of CSI / SS3 sequences without a number.
_LETTER_KEYS = {
    "A": "up",
    "B": "down",
    "C": "right",
    "D": "left",
    "H": "home",
    "F": "end",
    "P": "f1",
    "Q": "f2",
    "R": "f3",
    "S": "f4",
    "Z": "shift+tab",
}

# Number in ``CSI <number> ~`` sequences.
_TILDE_KEYS = {
    1: "home",
    2: "insert",
    3: "delete",
    4: "end",
    5: "pageup",
    6: "pagedown",
    7: "home",
    8: "end",
    11: "f1",
    12: "f2",
    13: "f3",
    14: "f4",
    15: "f5",
    17: "f6",
    18: "f7",
    19: "f8",
    20: "f9",
    21: "f10",
    23: "f11",
    24: "f12",
}

# xterm modifier parameter (the ``2`` in ``CSI 1;2 A``) minus one is a bit mask.
_MODIFIER_BITS = (("shift", 1), ("alt", 2), ("ctrl", 4))


MODIFIERS = tuple(label for label, _ in _MODIFIER_BITS)
"""Modifier prefixes, in the order they appear in key names."""

NAMED_KEYS = frozenset(
    set(_SIMPLE.values())
    | {name for name in _LETTER_KEYS.values() if "+" not in name}
    | set(_TILDE_KEYS.values())
    | {"space"}
)
"""Every multi-character key name."""


def _with_modifiers(name: str, parameter: int) -> str:
    """A key name with xterm modifiers added.

    :param name: The key name.
    :param parameter: The xterm modifier parameter.
    """
    mask = parameter - 1
    for label, bit in _MODIFIER_BITS:
        if mask & bit:
            name = _add_modifier(name, label)
    return name


_BUTTONS = ("left", "middle", "right", "none")
_SCROLL_DIRECTIONS = ("up", "down", "left", "right")


def _decode_mouse(params: str, final: str) -> MouseEvent | None:
    """Decode an SGR mouse report.

    :param params: The sequence's parameters.
    :param final: Its final character.
    """
    try:
        code, column, row = (int(part) for part in params[1:].split(";"))
    except ValueError:
        return None
    modifiers = {
        "shift": bool(code & 4),
        "alt": bool(code & 8),
        "ctrl": bool(code & 16),
    }
    if code & 64:
        action, button = "scroll", _SCROLL_DIRECTIONS[code & 3]
    elif code & 32:
        button = _BUTTONS[code & 3]
        action = "move" if button == "none" else "drag"
    else:
        button = _BUTTONS[code & 3]
        action = "press" if final == "M" else "release"
    return MouseEvent(action, button, row - 1, column - 1, **modifiers)


def _parameter(part: str) -> int:
    """A sequence parameter as a number, or 0.

    :param part: The parameter text.
    """
    return int(part) if part.isdigit() and len(part) <= 9 else 0


def _decode_sequence(params: str, final: str) -> Event:
    if params.startswith("<") and final in "Mm":
        mouse = _decode_mouse(params, final)
        if mouse is not None:
            return mouse
        return f"unknown({params}{final})"
    if final == "u" and ":" in params:
        return _decode_kitty_key(params)
    numbers = [_parameter(part) for part in params.split(";")]
    if final == "u" or (final == "~" and numbers[0] == 27 and len(numbers) == 3):
        # A key that has no sequence of its own, with modifiers: CSI code ;
        # mods u (the "CSI u" form) or xterm's CSI 27 ; mods ; code ~. This
        # is how terminals that can tell them apart send Ctrl+Tab.
        code, mods = (
            (numbers[0], numbers[1:2]) if final == "u" else (numbers[2], numbers[1:2])
        )
        name = (
            _single_key(chr(code))
            if 0 < code < 0x110000
            else f"unknown({params}{final})"
        )
        if name == " ":
            name = "space"
        return _with_modifiers(name, mods[0]) if mods and mods[0] > 1 else name
    if final == "~":
        name = _TILDE_KEYS.get(numbers[0], f"unknown({params}~)")
    else:
        name = _LETTER_KEYS.get(final, f"unknown({params}{final})")
    if len(numbers) > 1 and numbers[1] > 1:
        return _with_modifiers(name, numbers[1])
    return name


_FUNCTION_KEYS = frozenset(f"f{number}" for number in range(1, 13))


def _decode_kitty_key(params: str) -> Event:
    """Decode a kitty keyboard protocol key.

    :param params: The sequence's parameters.
    """
    fields = [field.split(":") for field in params.split(";")]
    try:
        code = int(fields[0][0])
        mods = int(fields[1][0]) if len(fields) > 1 and fields[1][0] else 1
        kind = int(fields[1][1]) if len(fields) > 1 and len(fields[1]) > 1 else 1
        name = _single_key(chr(code))
    except (ValueError, OverflowError):
        return f"unknown({params}u)"
    if name == " " and mods > 1:
        name = "space"
    if mods > 1:
        name = _with_modifiers(name, mods)
    return KeyReleaseEvent(name) if kind == 3 else name


def _add_modifier(key: str, modifier: str) -> str:
    """A key name with a modifier added.

    :param key: The key name.
    :param modifier: The modifier.
    """
    *prefixes, base = key.split("+")
    held = set(prefixes) | {modifier}
    return "".join(f"{label}+" for label in MODIFIERS if label in held) + base


def _single_key(char: str) -> str:
    if char in _SIMPLE:
        return _SIMPLE[char]
    if "\x01" <= char <= "\x1a":
        return "ctrl+" + chr(ord(char) + ord("a") - 1)
    return char


class InputDecoder:
    """Turns terminal input into events."""

    def __init__(self) -> None:
        self._buffer = ""
        self._in_paste = False
        # A paste so far, set aside piece by piece as it arrives, so that
        # each read is searched for the end marker once, however long it is.
        self._pasted: list[str] = []

    @property
    def is_pending(self) -> bool:
        """Whether an unfinished escape sequence or paste is being held back."""
        return bool(self._buffer or self._pasted)

    @property
    def is_pasting(self) -> bool:
        """Whether a bracketed paste has started and not yet ended."""
        return self._in_paste

    def feed(self, data: str) -> list[Event]:
        """Decode new input.

        :param data: The input.
        """
        self._buffer += data
        return self._decode(final=False)

    def flush(self) -> list[Event]:
        """Decode held-back input."""
        return self._decode(final=True)

    def _decode(self, final: bool) -> list[Event]:
        data = self._buffer
        events: list[Event] = []
        index = 0
        while index < len(data):
            if self._in_paste:
                index, ended = self._take_paste(data, index, final, events)
                if not ended:
                    break  # the rest of the paste has not arrived yet
                continue
            char = data[index]
            if char != ESC:
                events.append(_single_key(char))
                index += 1
                continue
            step = self._escape(data, index, final)
            if step is None:
                break  # the rest of the sequence has not arrived yet
            event, index = step
            if event is not None:
                events.append(event)
        self._buffer = data[index:]
        return events

    def _escape(
        self, data: str, index: int, final: bool
    ) -> tuple[Event | None, int] | None:
        """Decode an escape sequence, or ``None`` if incomplete.

        :param data: The input.
        :param index: Position of the ESC.
        :param final: Whether no more input is coming.
        """
        if index + 1 == len(data):
            # Might be the start of a sequence, unless no more is coming.
            return ("escape", index + 1) if final else None
        follower = data[index + 1]
        if follower == ESC:
            return self._after_two_escapes(data, index, final)
        if follower in "[O":
            # CSI (ESC [) or SS3 (ESC O): parameters, then a final character.
            end = index + 2
            while end < len(data) and data[end] in "0123456789;:<":
                end += 1
            if end < len(data):
                sequence = data[index : end + 1]
                if sequence in (PASTE_START, PASTE_END):  # a stray end: ignored
                    self._in_paste = sequence == PASTE_START
                    return None, end + 1
                return _decode_sequence(data[index + 2 : end], data[end]), end + 1
            if not final and end - index < _MAX_SEQUENCE_LENGTH:
                return None
        # ESC followed by another key is how terminals send Alt+key.
        name = _single_key(follower)
        return "alt+" + ("space" if name == " " else name), index + 2

    @staticmethod
    def _after_two_escapes(
        data: str, index: int, final: bool
    ) -> tuple[str, int] | None:
        """Decode two ESCs, or ``None`` if incomplete.

        :param data: The input.
        :param index: Position of the first ESC.
        :param final: Whether no more input is coming.
        """
        escape = ("escape", index + 1)
        start = index + 1  # the second ESC
        if start + 1 >= len(data):
            # Nothing after it yet: the rest of a key may be on its way.
            return escape if final else None
        if data[start + 1] not in "[O":
            return escape
        end = start + 2
        while end < len(data) and data[end] in "0123456789;:":
            end += 1
        if end >= len(data):
            waiting = not final and end - start < _MAX_SEQUENCE_LENGTH
            return None if waiting else escape
        key = _decode_sequence(data[start + 2 : end], data[end])
        if not isinstance(key, str) or key.split("+")[-1] not in _FUNCTION_KEYS:
            return escape
        return _add_modifier(key, "alt"), end + 1

    def _take_paste(
        self, data: str, index: int, final: bool, events: list[Event]
    ) -> tuple[int, bool]:
        """Take pasted text; return where to go on and whether it ended.

        :param data: The input.
        :param index: Start of the paste.
        :param final: Whether no more input is coming.
        :param events: Events to add to.
        """
        end = data.find(PASTE_END, index)
        if end < 0 and not final:
            keep = max(index, len(data) - (len(PASTE_END) - 1))
            if keep > index:
                self._pasted.append(data[index:keep])
            return keep, False
        stop = len(data) if end < 0 else end
        text = "".join(self._pasted) + data[index:stop]
        self._pasted = []
        if text:
            events.append(PasteEvent(text))
        if end < 0:
            return stop, False
        self._in_paste = False
        return end + len(PASTE_END), True


def decode(data: str) -> list[Event]:
    """Decode a complete chunk of input.

    :param data: The input.
    """
    decoder = InputDecoder()
    return decoder.feed(data) + decoder.flush()


class _Reader(Protocol):  # pylint: disable=too-few-public-methods
    def read(self, timeout: float | None = None) -> str:
        """Wait for and return input.

        :param timeout: Seconds to wait, or ``None`` for ever.
        """


def read_events(
    reader: _Reader,
    decoder: InputDecoder,
    escape_timeout: float,
    timeout: float | None = None,
    paste_timeout: float = PASTE_TIMEOUT,
) -> list[Event]:
    """Wait for input and return its events.

    :param reader: The input source.
    :param decoder: The decoder.
    :param escape_timeout: Seconds to wait after a lone ESC.
    :param timeout: Seconds to wait, or ``None`` for ever.
    :param paste_timeout: Seconds to wait for more of a paste.
    """
    events = decoder.feed(reader.read(timeout))
    while decoder.is_pending:
        data = _read_all_of(
            reader, paste_timeout if decoder.is_pasting else escape_timeout
        )
        events += decoder.feed(data) if data else decoder.flush()
    return events


def _read_all_of(reader: _Reader, timeout: float) -> str:
    """Read for the whole timeout, despite early wakes.

    :param reader: The input source.
    :param timeout: Seconds to wait.
    """
    deadline = time.monotonic() + timeout
    data = reader.read(timeout)
    while not data and getattr(reader, "is_woken", False):
        left = deadline - time.monotonic()
        if left <= 0:
            break
        data = reader.read(left)
    return data
