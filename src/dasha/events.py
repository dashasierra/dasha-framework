"""Turning raw terminal input into key and mouse events.

Terminals send special keys as escape sequences (for example, the up
arrow is ``ESC [ A``), and once mouse reporting is switched on, they send
mouse activity in the same way (``ESC [ < button ; column ; row M``). Keys
become readable names such as ``"up"``, ``"shift+tab"``, ``"f6"``,
``"ctrl+q"`` or ``"alt+x"``, while ordinary characters are returned as
themselves. Mouse activity becomes a ``MouseEvent``. Text pasted through
the terminal itself arrives wrapped in ``ESC [ 200 ~`` ... ``ESC [ 201 ~``
(bracketed paste), and becomes a single ``PasteEvent`` rather than a key for
each character. Windows consoles are switched into VT input mode, so the
same sequences arrive on every platform, both locally and over SSH.
"""

import time
from dataclasses import dataclass
from typing import Protocol

ESC = "\x1b"

# A sequence that has not finished after this many characters is garbage.
_MAX_SEQUENCE_LENGTH = 32

PASTE_START = ESC + "[200~"
PASTE_END = ESC + "[201~"
"""The markers that a terminal with bracketed paste turned on puts around
pasted text."""

PASTE_TIMEOUT = 0.5
"""How many seconds ``read_events`` waits for more of a paste that has not
ended.

A big paste over a slow SSH connection arrives over many reads. If no more
arrives for this long, what has arrived so far is delivered as a paste of
its own, so that the screen never freezes waiting for an end that never
comes.
"""


@dataclass(frozen=True, slots=True)
class MouseEvent:
    """A mouse report. ``row`` and ``column`` are screen positions, counted
    from 0.

    ``action`` is ``"press"``, ``"release"``, ``"drag"`` (moving with a
    button held down), ``"move"`` (moving with no button held down) or
    ``"scroll"``. ``button`` is ``"left"``, ``"middle"``, ``"right"`` or
    ``"none"``, or, for scrolling, ``"up"``, ``"down"``, ``"left"`` or
    ``"right"``.
    """

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
    """For a press, 2 for the second press of a double-click, 3 for a
    triple-click, and so on. The presentation manager counts these clicks,
    because the terminal does not."""


@dataclass(frozen=True, slots=True)
class PasteEvent:
    """Text pasted through the terminal (with its own Ctrl+V, right-click or
    middle-click), exactly as it arrived. Line breaks and other control
    characters in it are part of the text, not key presses."""

    text: str


@dataclass(frozen=True, slots=True)
class KeyReleaseEvent:
    """A key being released. ``key`` is the key's name, as given when it
    was pressed (``" "`` for Space). Most terminals never report releases;
    see ``Terminal.can_report_key_releases``."""

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
"""Every key name that ``decode`` can produce, other than single
characters.

Combined with modifiers, these give names such as ``"ctrl+right"``.
``"space"`` appears only with a modifier (``"alt+space"``); a plain space is
``" "``.
"""


def _with_modifiers(name: str, parameter: int) -> str:
    """A key name with the modifiers an xterm parameter (the ``5`` in
    ``CSI 1 ; 5 C``) stands for, kept in the usual order even when the name
    has one already (``shift+tab`` with Ctrl is ``shift+ctrl+tab``)."""
    mask = parameter - 1
    for label, bit in _MODIFIER_BITS:
        if mask & bit:
            name = _add_modifier(name, label)
    return name


_BUTTONS = ("left", "middle", "right", "none")
_SCROLL_DIRECTIONS = ("up", "down", "left", "right")


def _decode_mouse(params: str, final: str) -> MouseEvent | None:
    """Decode an SGR mouse report: ``ESC [ < button ; column ; row M/m``."""
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
    """A number in a sequence's parameters: 0 if it is missing, not a
    number, or too long to be a real one (Python will not convert one of
    thousands of digits)."""
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
    """``CSI code ; mods : event u``, the kitty keyboard protocol's form with
    an event type: 1 a press, 2 a repeat, 3 a release. The Windows backend
    writes Space's release this way too."""
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
    """``"shift+f3"`` with ``"alt"`` added is ``"shift+alt+f3"``: modifiers
    stay in the order key names always use."""
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
    """Turns a stream of terminal input into events.

    Input can arrive in pieces, especially over SSH, so an escape
    sequence may be split across two reads. ``feed`` holds back an unfinished
    sequence until the rest arrives. A lone ESC is also the start of every
    sequence, so when input stops with one pending (``is_pending`` is true), the
    caller should wait briefly for more and then call ``flush``, which treats
    it as the Escape key.

    A bracketed paste is held back in the same way until its end marker
    arrives, and then becomes a single ``PasteEvent``. While a paste is under
    way (``is_pasting``), ``flush`` delivers what has arrived so far as one
    paste, and anything more, up to the end marker, as another.
    """

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
        """Decode new input, holding back any unfinished escape sequence."""
        self._buffer += data
        return self._decode(final=False)

    def flush(self) -> list[Event]:
        """Decode whatever is held back, treating a lone ESC as the Escape key."""
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
        """Decode what starts with the ESC at ``index``: the event (``None``
        for one that makes none, such as the start of a paste) and where the
        next one begins; ``None`` if the rest has not arrived yet."""
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
        """Two ESCs at ``index``: the event they start, and where the next
        one begins; ``None`` if the rest has not arrived yet.

        ESC followed by a function key's whole sequence (``ESC ESC O R``) is
        how PuTTY, rxvt and the Linux console send Alt with a function key,
        so it is ``alt+f3``. Anything else is Escape, then whatever follows:
        Escape and an arrow pressed quickly can arrive together over SSH,
        and must not turn into Alt+arrow."""
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
        """Add the pasted text starting at ``index`` to ``events`` as a
        ``PasteEvent``. Return where decoding goes on, and whether the paste
        ended there. Without the end marker, the text is held back unless
        ``final``: set aside, but for the last few characters, which may be
        the start of the end marker, and are searched again with the next
        read."""
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
    """Decode a complete chunk of input in one go."""
    decoder = InputDecoder()
    return decoder.feed(data) + decoder.flush()


class _Reader(Protocol):  # pylint: disable=too-few-public-methods
    def read(self, timeout: float | None = None) -> str:
        """Wait (forever, or up to ``timeout`` seconds) and return input."""


def read_events(
    reader: _Reader,
    decoder: InputDecoder,
    escape_timeout: float,
    timeout: float | None = None,
    paste_timeout: float = PASTE_TIMEOUT,
) -> list[Event]:
    """Wait for input from a terminal (indefinitely, or for up to
    ``timeout`` seconds), and return the events in it.

    If the input ends part-way through an escape sequence, wait up to
    ``escape_timeout`` seconds for the rest; if none arrives, the ESC was the
    Escape key. Part-way through a paste, wait up to ``paste_timeout``
    seconds at a time for the rest. Those waits last their whole time even
    if the reader is woken meanwhile (by ``Terminal.wake`` or a resize), so
    that a sequence split in two is never cut short. Returns an empty list
    if the read was woken, or timed out.
    """
    events = decoder.feed(reader.read(timeout))
    while decoder.is_pending:
        data = _read_all_of(
            reader, paste_timeout if decoder.is_pasting else escape_timeout
        )
        events += decoder.feed(data) if data else decoder.flush()
    return events


def _read_all_of(reader: _Reader, timeout: float) -> str:
    """Read, waiting up to ``timeout`` seconds, and waiting again for the
    rest of that time when the read was woken early (where the reader says
    so with ``is_woken``, as ``Terminal`` does)."""
    deadline = time.monotonic() + timeout
    data = reader.read(timeout)
    while not data and getattr(reader, "is_woken", False):
        left = deadline - time.monotonic()
        if left <= 0:
            break
        data = reader.read(left)
    return data
