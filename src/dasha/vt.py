"""A VT terminal emulator."""

import codecs
import re
import unicodedata
from collections import deque
from collections.abc import Iterable

from dasha.events import MouseEvent
from dasha.style import DEFAULT, Colour, Rgb, Style

# pylint: disable=too-many-lines

type Cell = tuple[str, Style]
"""A cell's text and style."""

SCROLLBACK = 1000
"""Default scrollback lines kept."""

MAX_TITLE = 1000
"""The longest window title kept, in characters."""

_MAX_SEQUENCE = 256
"""A control sequence longer than this is garbage, and is dropped."""

_MAX_STRING = 4096
"""Most characters kept of an OSC string."""

_PRINTABLE = re.compile(r"[^\x00-\x1f\x7f-\x9f]+")

DEC_GRAPHICS = str.maketrans(
    {
        "`": "\N{BLACK DIAMOND SUIT}",
        "a": "\N{MEDIUM SHADE}",
        "f": "\N{DEGREE SIGN}",
        "g": "\N{PLUS-MINUS SIGN}",
        "j": "\N{BOX DRAWINGS LIGHT UP AND LEFT}",
        "k": "\N{BOX DRAWINGS LIGHT DOWN AND LEFT}",
        "l": "\N{BOX DRAWINGS LIGHT DOWN AND RIGHT}",
        "m": "\N{BOX DRAWINGS LIGHT UP AND RIGHT}",
        "n": "\N{BOX DRAWINGS LIGHT VERTICAL AND HORIZONTAL}",
        "o": "\N{BOX DRAWINGS LIGHT HORIZONTAL}",
        "p": "\N{BOX DRAWINGS LIGHT HORIZONTAL}",
        "q": "\N{BOX DRAWINGS LIGHT HORIZONTAL}",
        "r": "\N{BOX DRAWINGS LIGHT HORIZONTAL}",
        "s": "\N{BOX DRAWINGS LIGHT HORIZONTAL}",
        "t": "\N{BOX DRAWINGS LIGHT VERTICAL AND RIGHT}",
        "u": "\N{BOX DRAWINGS LIGHT VERTICAL AND LEFT}",
        "v": "\N{BOX DRAWINGS LIGHT UP AND HORIZONTAL}",
        "w": "\N{BOX DRAWINGS LIGHT DOWN AND HORIZONTAL}",
        "x": "\N{BOX DRAWINGS LIGHT VERTICAL}",
        "y": "\N{LESS-THAN OR EQUAL TO}",
        "z": "\N{GREATER-THAN OR EQUAL TO}",
        "{": "\N{GREEK SMALL LETTER PI}",
        "}": "\N{POUND SIGN}",
        "~": "\N{MIDDLE DOT}",
    }
)
"""DEC line-drawing characters."""

PRIMARY_ATTRIBUTES = "\x1b[?62;22c"
"""The answer to "what are you?" (``CSI c``): a VT220 with colour."""

SECONDARY_ATTRIBUTES = "\x1b[>1;10;0c"
"""The answer to ``CSI > c``: a VT220, version 10."""

_GROUND, _ESCAPE, _CSI, _OSC, _STRING = range(5)

_width_cache: dict[str, int] = {}


def char_width(char: str) -> int:
    """Columns a character takes.

    :param char: The character.
    """
    if char < "̀":
        return 1
    known = _width_cache.get(char)
    if known is None:
        if unicodedata.category(char) in ("Mn", "Me", "Cf"):
            known = 0
        elif unicodedata.east_asian_width(char) in ("W", "F"):
            known = 2
        else:
            known = 1
        if len(_width_cache) < 4096:
            _width_cache[char] = known
    return known


class Line(list[Cell]):
    """One row of cells, noting whether it wrapped."""

    wrapped: bool = False
    """Whether the text ran on into the next line, rather than ending."""


def _number(part: str, default: int = 0) -> int:
    """A sequence parameter, or a default.

    :param part: The parameter text.
    :param default: Value if empty or invalid.
    """
    return int(part) if part.isdigit() and len(part) <= 9 else default


def _colour(parts: list[str]) -> Colour | None:
    """An extended colour, or ``None``.

    :param parts: The parameters after 38 or 48.
    """
    if not parts:
        return None
    if parts[0] == "5" and len(parts) >= 2:
        number = _number(parts[1], -1)
        return number if 0 <= number <= 255 else None
    if parts[0] == "2" and len(parts) >= 4:
        red, green, blue = (_number(part, -1) for part in parts[-3:])
        if all(0 <= part <= 255 for part in (red, green, blue)):
            return Rgb(red, green, blue)
    return None


class _Cursor:  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """What saving the cursor (``ESC 7``) saves."""

    def __init__(self) -> None:
        self.row = 0
        self.column = 0
        self.attributes: tuple[Colour | None, Colour | None, bool, bool, bool, bool]
        self.attributes = (None, None, False, False, False, False)
        self.origin = False
        self.charsets = ["B", "B"]
        self.shift = 0


class Screen:  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """What a terminal shows, kept up to date by ``feed``.

    :param columns: Screen width.
    :param lines: Screen height.
    :param scrollback: Most lines kept off the top.
    """

    row: int
    """The cursor's row, from 0."""
    column: int
    """The cursor's column, from 0."""
    style: Style
    """The style that text written now takes."""
    top: int
    """The scroll region's first row."""
    bottom: int
    """The scroll region's last row."""
    app_cursor_keys: bool
    """Whether the cursor keys send their application forms (DECCKM)."""
    cursor_visible: bool
    """Whether the program wants the cursor shown (DECTCEM)."""
    bracketed_paste: bool
    """Whether the program wants pastes marked (mode 2004)."""
    mouse_modes: set[int]
    """Mouse reporting modes turned on."""

    def __init__(
        self, columns: int = 80, lines: int = 24, scrollback: int = SCROLLBACK
    ) -> None:
        self.columns = max(1, columns)
        self.lines = max(1, lines)
        self.scrollback: deque[Line] = deque(maxlen=max(0, scrollback))
        """Lines scrolled off the top of the main screen, oldest first."""
        self.scrolled_off = 0
        """Lines ever scrolled into the scrollback."""
        self.title = ""
        """The program's window title."""
        self.bells = 0
        """How many times the program has rung the bell."""
        self._replies: list[str] = []
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._main = self._blank_lines(self.lines)
        self._alternate = self._blank_lines(self.lines)
        self._rows = self._main
        self._saved = [_Cursor(), _Cursor()]
        self._state = _GROUND
        self._sequence: list[str] = []
        self._string: list[str] = []
        self._string_escape = False
        self._last_printed = " "
        self._reset_modes()

    def _reset_modes(self) -> None:
        """Back to how a terminal starts (all but the screen's contents)."""
        # pylint: disable=attribute-defined-outside-init
        self.row = 0
        self.column = 0
        self._pending_wrap = False
        self._foreground: Colour | None = None
        self._background: Colour | None = None
        self._bold = self._underline = self._reverse = self._hidden = False
        self.style = DEFAULT
        self.top = 0
        self.bottom = self.lines - 1
        self.origin = False
        self.autowrap = True
        self.insert = False
        self.newline = False
        self.app_cursor_keys = False
        self.app_keypad = False
        self.cursor_visible = True
        self.bracketed_paste = False
        self.mouse_modes = set()
        self._charsets = ["B", "B"]
        self._shift = 0
        self._tabs = set(range(8, self.columns, 8))

    # Feeding

    def feed_bytes(self, data: bytes) -> None:
        """Take in UTF-8 output.

        :param data: The output.
        """
        self.feed(self._decoder.decode(data))

    def feed(self, text: str) -> None:
        """Take in output.

        :param text: The output.
        """
        index, end = 0, len(text)
        while index < end:
            if self._state == _GROUND:
                found = _PRINTABLE.match(text, index)
                if found is not None:
                    self._print(found.group())
                    index = found.end()
                    continue
                self._control(text[index])
            elif self._state == _ESCAPE:
                self._escape(text[index])
            elif self._state == _CSI:
                self._csi(text[index])
            else:
                self._in_string(text[index])
            index += 1

    def take_replies(self) -> bytes:
        """Take the program's pending replies."""
        replies, self._replies = "".join(self._replies), []
        return replies.encode("utf-8")

    def _reply(self, text: str) -> None:
        if len(self._replies) < 100:  # a program asking without reading
            self._replies.append(text)

    # Controls

    def _control(self, char: str) -> None:
        """Handle a C0 control character.

        :param char: The character.
        """
        if char == "\x1b":
            self._state = _ESCAPE
            self._sequence = []
        elif char == "\r":
            self.column = 0
            self._pending_wrap = False
        elif char in "\n\x0b\x0c":
            self._index()
            if self.newline:
                self.column = 0
        elif char == "\x08":
            if self._pending_wrap:
                self._pending_wrap = False
            elif self.column > 0:
                self.column -= 1
        elif char == "\t":
            self._tab(1)
        elif char == "\x07":
            self.bells += 1
        elif char == "\x0e":
            self._shift = 1
        elif char == "\x0f":
            self._shift = 0

    def _escape(self, char: str) -> None:
        """Handle the character after an ESC.

        :param char: The character.
        """
        sequence = self._sequence
        if char == "\x1b":
            self._sequence = []
            return
        if "\x00" <= char < " ":
            self._control(char)  # executed in the middle of a sequence
            return
        if " " <= char <= "/":
            if len(sequence) < 4:
                sequence.append(char)
            return
        self._state = _GROUND
        if sequence:
            self._designate("".join(sequence), char)
            return
        if char == "[":
            self._state = _CSI
            self._sequence = []
        elif char == "]":
            self._start_string(osc=True)
        elif char in "PX^_":
            self._start_string(osc=False)
        else:
            self._simple_escape(char)

    def _designate(self, intermediates: str, final: str) -> None:
        """Handle a character set designation.

        :param intermediates: Intermediate characters.
        :param final: The final character.
        """
        if intermediates in ("(", ")"):
            self._charsets[intermediates == ")"] = "0" if final == "0" else "B"
        elif intermediates == "#" and final == "8":
            self._rows[:] = [
                Line([("E", DEFAULT)] * self.columns) for _ in range(self.lines)
            ]

    def _simple_escape(self, char: str) -> None:
        if char == "7":
            self._save_cursor()
        elif char == "8":
            self._restore_cursor()
        elif char == "D":
            self._index()
        elif char == "E":
            self._index()
            self.column = 0
        elif char == "M":
            self._reverse_index()
        elif char == "H":
            self._tabs.add(self.column)
        elif char == "c":
            self.reset()
        elif char == "=":
            self.app_keypad = True
        elif char == ">":
            self.app_keypad = False

    def _start_string(self, osc: bool) -> None:
        self._state = _OSC if osc else _STRING
        self._string = []
        self._string_escape = False

    def _in_string(self, char: str) -> None:
        """Handle a character of an OSC or ignored string.

        :param char: The character.
        """
        if self._string_escape:
            self._string_escape = False
            if char == "\\":
                self._end_string()
                return
            self._state = _ESCAPE  # another sequence, which ends this one
            self._sequence = []
            self._escape(char)
            return
        if char == "\x1b":
            self._string_escape = True
        elif char == "\x07":
            self._end_string()
        elif self._state == _OSC and len(self._string) < _MAX_STRING:
            self._string.append(char)

    def _end_string(self) -> None:
        if self._state == _OSC:
            self._osc("".join(self._string))
        self._state = _GROUND
        self._string = []

    def _osc(self, text: str) -> None:
        number, _, value = text.partition(";")
        if number in ("0", "2"):
            title = "".join(char for char in value if _PRINTABLE.fullmatch(char))
            self.title = title[:MAX_TITLE]

    # Control sequences (CSI)

    def _csi(self, char: str) -> None:
        if "@" <= char <= "~":
            self._state = _GROUND
            self._dispatch("".join(self._sequence), char)
        elif char == "\x1b":
            self._state = _ESCAPE
            self._sequence = []
        elif char < " ":
            self._control(char)
        elif len(self._sequence) < _MAX_SEQUENCE:
            self._sequence.append(char)
        else:
            self._state = _GROUND  # garbage: dropped

    def _dispatch(self, body: str, final: str) -> None:
        """Carry out a CSI sequence.

        :param body: Its parameters and intermediates.
        :param final: Its final character.
        """
        private = body[:1] if body[:1] in "?>=<" else ""
        body = body[len(private) :]
        intermediates = ""
        while body and " " <= body[-1] <= "/":
            intermediates = body[-1] + intermediates
            body = body[:-1]
        if private == "?" and final in "hl" and not intermediates:
            for part in body.split(";"):
                self._set_dec_mode(_number(part), final == "h")
            return
        if private == ">" and final == "c":
            self._reply(SECONDARY_ATTRIBUTES)
            return
        if intermediates == "!" and final == "p" and not private:
            self.soft_reset()
            return
        if private or intermediates:
            return  # not one of ours (such as CSI > 4 ; 2 m): ignored
        if final == "m":
            self._sgr(body)
            return
        numbers = [_number(part) for part in body.split(";")] if body else []
        self._command(final, numbers)

    # pylint: disable-next=too-many-branches,too-many-statements
    def _command(self, final: str, numbers: list[int]) -> None:
        first = numbers[0] if numbers else 0
        count = max(1, first)
        if final in "AF":
            self._move_to(max(self._row_floor(), self.row - count), self.column)
            if final == "F":
                self.column = 0
        elif final in "Be":
            self._move_to(min(self._row_ceiling(), self.row + count), self.column)
        elif final == "E":
            self._move_to(min(self._row_ceiling(), self.row + count), 0)
        elif final in "Ca":
            self._move_to(self.row, self.column + count)
        elif final == "D":
            self._move_to(self.row, self.column - count)
        elif final in "G`":
            self._move_to(self.row, count - 1)
        elif final in "Hf":
            row = numbers[1] if len(numbers) > 1 else 0
            self._address(count - 1, max(1, row) - 1)
        elif final == "d":
            self._address(count - 1, self.column)
        elif final == "J":
            self._erase_display(first)
        elif final == "K":
            self._erase_line(first)
        elif final == "@":
            self._insert_cells(count)
        elif final == "P":
            self._delete_cells(count)
        elif final == "X":
            self._erase_cells(count)
        elif final == "L":
            self._insert_lines(count)
        elif final == "M":
            self._delete_lines(count)
        elif final == "S":
            self._scroll_up(count)
        elif final == "T":
            self._scroll_down(count)
        elif final == "I":
            self._tab(count)
        elif final == "Z":
            self._tab(-count)
        elif final == "b":
            self._print(self._last_printed * min(count, self.columns * self.lines))
        elif final == "g":
            if first == 0:
                self._tabs.discard(self.column)
            elif first == 3:
                self._tabs.clear()
        elif final == "r":
            self._set_region(numbers)
        elif final == "s":
            self._save_cursor()
        elif final == "u":
            self._restore_cursor()
        elif final == "n":
            self._report(first)
        elif final == "c" and first == 0:
            self._reply(PRIMARY_ATTRIBUTES)
        elif final in "hl":
            for number in numbers:
                if number == 4:
                    self.insert = final == "h"
                elif number == 20:
                    self.newline = final == "h"

    def _report(self, number: int) -> None:
        """Answer a device status report.

        :param number: The report asked for.
        """
        if number == 5:
            self._reply("\x1b[0n")
        elif number == 6:
            row = self.row - (self.top if self.origin else 0)
            self._reply(f"\x1b[{row + 1};{self.column + 1}R")

    def _set_dec_mode(self, number: int, on: bool) -> None:
        # pylint: disable=too-many-branches
        if number == 1:
            self.app_cursor_keys = on
        elif number == 6:
            self.origin = on
            self._address(0, 0)
        elif number == 7:
            self.autowrap = on
            if not on:
                self._pending_wrap = False
        elif number == 25:
            self.cursor_visible = on
        elif number in (47, 1047):
            self._use_alternate(on, clear=number == 1047)
        elif number == 1048:
            if on:
                self._save_cursor()
            else:
                self._restore_cursor()
        elif number == 1049:
            if on:
                self._save_cursor()
                self._use_alternate(True, clear=True)
            else:
                self._use_alternate(False, clear=False)
                self._restore_cursor()
        elif number == 2004:
            self.bracketed_paste = on
        elif number in (1000, 1002, 1003, 1006):
            if on:
                self.mouse_modes.add(number)
            else:
                self.mouse_modes.discard(number)

    def _sgr(self, body: str) -> None:
        """Set colours and attributes.

        :param body: The SGR parameters.
        """
        groups = [group.split(":") for group in body.split(";")] if body else [["0"]]
        index = 0
        while index < len(groups):
            group = groups[index]
            code = _number(group[0])
            if code in (38, 48, 58):
                if len(group) > 1:
                    colour = _colour([part for part in group[1:] if part])
                else:
                    rest = [g[0] for g in groups[index + 1 : index + 5]]
                    colour = _colour(rest)
                    index += 2 if rest[:1] == ["5"] else 4 if rest[:1] == ["2"] else 0
                if code == 38:
                    self._foreground = colour
                elif code == 48:
                    self._background = colour
            else:
                self._attribute(code)
            index += 1
        self.style = Style(
            foreground=self._foreground,
            background=self._background,
            bold=self._bold,
            underline=self._underline,
            reverse=self._reverse,
        )

    def _attribute(self, code: int) -> None:
        # pylint: disable=too-many-branches
        if code == 0:
            self._foreground = self._background = None
            self._bold = self._underline = self._reverse = self._hidden = False
        elif code == 1:
            self._bold = True
        elif code == 4:
            self._underline = True
        elif code == 7:
            self._reverse = True
        elif code == 8:
            self._hidden = True
        elif code == 22:
            self._bold = False
        elif code == 24:
            self._underline = False
        elif code == 27:
            self._reverse = False
        elif code == 28:
            self._hidden = False
        elif 30 <= code <= 37:
            self._foreground = code - 30
        elif code == 39:
            self._foreground = None
        elif 40 <= code <= 47:
            self._background = code - 40
        elif code == 49:
            self._background = None
        elif 90 <= code <= 97:
            self._foreground = code - 90 + 8
        elif 100 <= code <= 107:
            self._background = code - 100 + 8

    # Writing text

    def _print(self, text: str) -> None:
        if self._charsets[self._shift] == "0":
            text = text.translate(DEC_GRAPHICS)
        if self._hidden:
            text = "".join(" " if char_width(char) else "" for char in text)
        if text.isascii() and not self.insert:
            self._print_ascii(text)
        else:
            for char in text:
                self._print_char(char)
        if text:
            self._last_printed = text[-1]

    def _wrap(self) -> None:
        """Continue on the next line."""
        self._rows[self.row].wrapped = True
        self._index()
        self.column = 0
        self._pending_wrap = False

    def _print_ascii(self, text: str) -> None:
        """Print one-cell text quickly.

        :param text: The text.
        """
        style, columns = self.style, self.columns
        while text:
            if self._pending_wrap:
                if self.autowrap:
                    self._wrap()
                else:
                    text = text[-1:]  # each overwrites the last column
                    self._pending_wrap = False
            row = self._rows[self.row]
            room = columns - self.column
            chunk, text = text[:room], text[room:]
            end = self.column + len(chunk)
            self._clear_wide_at(row, self.column, end)
            row[self.column : end] = [(char, style) for char in chunk]
            if end >= columns:
                self.column = columns - 1
                self._pending_wrap = True
            else:
                self.column = end

    def _print_char(self, char: str) -> None:
        width = char_width(char)
        if width == 0:
            self._combine(char)
            return
        if self._pending_wrap:
            if self.autowrap:
                self._wrap()
            else:
                self._pending_wrap = False
        if width == 2 and self.column == self.columns - 1:
            if not self.autowrap:
                return  # no room for it
            self._rows[self.row][self.column] = (" ", self.style)
            self._wrap()
        row = self._rows[self.row]
        if self.insert:
            self._insert_cells(width)
        self._clear_wide_at(row, self.column, self.column + width)
        row[self.column] = (char, self.style)
        if width == 2:
            row[self.column + 1] = ("", self.style)
        end = self.column + width
        if end >= self.columns:
            self.column = self.columns - 1
            self._pending_wrap = True
        else:
            self.column = end

    def _combine(self, mark: str) -> None:
        """Join a combining mark to the previous character.

        :param mark: The mark.
        """
        row = self._rows[self.row]
        column = self.column if self._pending_wrap else self.column - 1
        if 0 < column and row[column][0] == "":
            column -= 1  # the right half of a wide character
        if column < 0:
            return
        text, style = row[column]
        if text and len(text) < 8:
            row[column] = (unicodedata.normalize("NFC", text + mark), style)

    def _clear_wide_at(self, row: Line, start: int, end: int) -> None:
        """Blank the other half of cut wide characters.

        :param row: The line.
        :param start: First column overwritten.
        :param end: Column after the last.
        """
        if start > 0 and row[start][0] == "":
            row[start - 1] = (" ", row[start - 1][1])
        if end < self.columns and row[end][0] == "":
            row[end] = (" ", row[end][1])

    # The cursor

    def _row_floor(self) -> int:
        return self.top if self.top <= self.row <= self.bottom else 0

    def _row_ceiling(self) -> int:
        return self.bottom if self.top <= self.row <= self.bottom else self.lines - 1

    def _move_to(self, row: int, column: int) -> None:
        self.row = min(max(0, row), self.lines - 1)
        self.column = min(max(0, column), self.columns - 1)
        self._pending_wrap = False

    def _address(self, row: int, column: int) -> None:
        """Move to a program-given place.

        :param row: The row.
        :param column: The column.
        """
        if self.origin:
            row = min(self.top + row, self.bottom)
        self._move_to(row, column)

    def _index(self) -> None:
        """Down a line, scrolling the region at its bottom."""
        if self.row == self.bottom:
            self._scroll_up(1)
        elif self.row < self.lines - 1:
            self.row += 1
        self._pending_wrap = False

    def _reverse_index(self) -> None:
        """Up a line, scrolling the region down at its top."""
        if self.row == self.top:
            self._scroll_down(1)
        elif self.row > 0:
            self.row -= 1
        self._pending_wrap = False

    def _tab(self, count: int) -> None:
        """Move between tab stops.

        :param count: Stops forward; negative is back.
        """
        column = self.column
        for _ in range(abs(count)):
            if count > 0:
                stops = [stop for stop in self._tabs if stop > column]
                column = min(stops) if stops else self.columns - 1
            else:
                stops = [stop for stop in self._tabs if stop < column]
                column = max(stops) if stops else 0
        self.column = column
        self._pending_wrap = False

    def _save_cursor(self) -> None:
        saved = self._saved[self._rows is self._alternate]
        saved.row, saved.column = self.row, self.column
        saved.attributes = (
            self._foreground,
            self._background,
            self._bold,
            self._underline,
            self._reverse,
            self._hidden,
        )
        saved.origin = self.origin
        saved.charsets = list(self._charsets)
        saved.shift = self._shift

    def _restore_cursor(self) -> None:
        saved = self._saved[self._rows is self._alternate]
        (
            self._foreground,
            self._background,
            self._bold,
            self._underline,
            self._reverse,
            self._hidden,
        ) = saved.attributes
        self._sgr_refresh()
        self.origin = saved.origin
        self._charsets = list(saved.charsets)
        self._shift = saved.shift
        self._move_to(saved.row, saved.column)

    def _sgr_refresh(self) -> None:
        self.style = Style(
            foreground=self._foreground,
            background=self._background,
            bold=self._bold,
            underline=self._underline,
            reverse=self._reverse,
        )

    def _set_region(self, numbers: list[int]) -> None:
        top = max(1, numbers[0] if numbers else 1) - 1
        bottom = (numbers[1] if len(numbers) > 1 and numbers[1] else self.lines) - 1
        bottom = min(bottom, self.lines - 1)
        if top < bottom:
            self.top, self.bottom = top, bottom
            self._address(0, 0)

    # Erasing, inserting and deleting

    def _blank(self) -> Cell:
        """An erased cell: blank, in the background colour now in use."""
        if self._background is None:
            return (" ", DEFAULT)
        return (" ", Style(background=self._background))

    def _blank_line(self) -> Line:
        return Line([self._blank()] * self.columns)

    def _blank_lines(self, count: int) -> list[Line]:
        return [Line([(" ", DEFAULT)] * self.columns) for _ in range(count)]

    def _erase_display(self, how: int) -> None:
        if how == 0:
            self._erase_line(0)
            for row in range(self.row + 1, self.lines):
                self._rows[row] = self._blank_line()
        elif how == 1:
            self._erase_line(1)
            for row in range(self.row):
                self._rows[row] = self._blank_line()
        elif how == 2:
            for row in range(self.lines):
                self._rows[row] = self._blank_line()
        elif how == 3:
            self.clear_scrollback()

    def _erase_line(self, how: int) -> None:
        row = self._rows[self.row]
        start, end = {0: (self.column, self.columns), 1: (0, self.column + 1)}.get(
            how, (0, self.columns)
        )
        self._clear_wide_at(row, start, end)
        row[start:end] = [self._blank()] * (end - start)
        if how != 1:
            row.wrapped = False
        self._pending_wrap = False

    def _erase_cells(self, count: int) -> None:
        row = self._rows[self.row]
        end = min(self.columns, self.column + count)
        self._clear_wide_at(row, self.column, end)
        row[self.column : end] = [self._blank()] * (end - self.column)
        self._pending_wrap = False

    def _insert_cells(self, count: int) -> None:
        row = self._rows[self.row]
        count = min(count, self.columns - self.column)
        self._clear_wide_at(row, self.column, self.column)
        row[self.column : self.column] = [self._blank()] * count
        del row[self.columns :]
        if row[-1][0] == "":  # a wide character pushed half off the end
            row[-1] = (" ", row[-1][1])
        self._pending_wrap = False

    def _delete_cells(self, count: int) -> None:
        row = self._rows[self.row]
        count = min(count, self.columns - self.column)
        self._clear_wide_at(row, self.column, self.column + count)
        del row[self.column : self.column + count]
        row.extend([self._blank()] * count)
        self._pending_wrap = False

    def _insert_lines(self, count: int) -> None:
        if self.top <= self.row <= self.bottom:
            self._scroll_down(count, top=self.row)
            self.column = 0

    def _delete_lines(self, count: int) -> None:
        if self.top <= self.row <= self.bottom:
            self._scroll_up(count, top=self.row)
            self.column = 0

    def _scroll_up(self, count: int, top: int | None = None) -> None:
        """Scroll the region up.

        :param count: Lines to scroll.
        :param top: Top line, or ``None`` for the region's.
        """
        top = self.top if top is None else top
        rows, bottom = self._rows, self.bottom
        count = min(count, bottom - top + 1)
        keep = top == 0 and rows is self._main and self.scrollback.maxlen
        for _ in range(count):
            line = rows.pop(top)
            if keep:
                self.scrollback.append(line)
                self.scrolled_off += 1
            rows.insert(bottom, self._blank_line())
        self._pending_wrap = False

    def _scroll_down(self, count: int, top: int | None = None) -> None:
        top = self.top if top is None else top
        rows, bottom = self._rows, self.bottom
        count = min(count, bottom - top + 1)
        for _ in range(count):
            del rows[bottom]
            rows.insert(top, self._blank_line())
        self._pending_wrap = False

    def _use_alternate(self, on: bool, clear: bool) -> None:
        if on == (self._rows is self._alternate):
            return
        if on:
            self._rows = self._alternate
            if clear:
                self._alternate[:] = self._blank_lines(self.lines)
        else:
            if clear:
                self._alternate[:] = self._blank_lines(self.lines)
            self._rows = self._main
        self._pending_wrap = False

    # For the view

    @property
    def is_alternate(self) -> bool:
        """Whether the alternate screen is in use."""
        return self._rows is self._alternate

    @property
    def is_tracking_mouse(self) -> bool:
        """Whether the program tracks the mouse."""
        return bool(self.mouse_modes & TRACKING_MODES)

    @property
    def rows(self) -> list[Line]:
        """The rows on the screen, top first."""
        return self._rows

    @property
    def cursor(self) -> tuple[int, int]:
        """Where the cursor is: (row, column), from 0."""
        return self.row, self.column

    def shown_rows(self, back: int = 0) -> list[Line]:
        """The rows shown when scrolled back.

        :param back: Lines scrolled back.
        """
        back = max(0, min(back, len(self.scrollback)))
        if back == 0:
            return list(self._rows)
        older = list(self.scrollback)[len(self.scrollback) - back :]
        return (older + self._rows)[: self.lines]

    def clear_scrollback(self) -> None:
        """Forget the lines scrolled off the top."""
        self.scrollback.clear()

    def soft_reset(self) -> None:
        """Reset the modes, keeping the screen."""
        row, column = self.row, self.column
        self._reset_modes()
        self._saved = [_Cursor(), _Cursor()]
        self.row, self.column = row, column

    def reset(self) -> None:
        """Reset to the starting state."""
        self._main[:] = self._blank_lines(self.lines)
        self._alternate[:] = self._blank_lines(self.lines)
        self._rows = self._main
        self._saved = [_Cursor(), _Cursor()]
        self._reset_modes()

    def resize(self, columns: int, lines: int) -> None:
        """Change the size.

        :param columns: New width.
        :param lines: New height.
        """
        columns, lines = max(1, columns), max(1, lines)
        if (columns, lines) == (self.columns, self.lines):
            return
        old_columns = self.columns
        self.columns = columns
        for buffer in (self._main, self._alternate):
            for line in buffer:
                self._fit(line, columns)
        main = self._rows is self._main
        self._resize_rows(self._main, lines, keep_cursor=main, scroll=True)
        self._resize_rows(self._alternate, lines, keep_cursor=not main, scroll=False)
        self.lines = lines
        self.top, self.bottom = 0, lines - 1
        self._tabs = {stop for stop in self._tabs if stop < columns} | set(
            range((old_columns + 7) // 8 * 8, columns, 8)
        )
        self._move_to(self.row, self.column)
        for saved in self._saved:
            saved.row = min(saved.row, lines - 1)
            saved.column = min(saved.column, columns - 1)

    @staticmethod
    def _fit(line: Line, columns: int) -> None:
        if len(line) > columns:
            del line[columns:]
            if line[-1][0] == "":
                line[-1] = (" ", line[-1][1])
        else:
            line.extend([(" ", DEFAULT)] * (columns - len(line)))

    def _resize_rows(
        self, rows: list[Line], lines: int, keep_cursor: bool, scroll: bool
    ) -> None:
        """Resize a list of rows.

        :param rows: The rows.
        :param lines: New height.
        :param keep_cursor: Whether the cursor moves with the lines.
        :param scroll: Whether lines go to and from the scrollback.
        """
        height = len(rows)
        if lines < height:
            cursor = self.row if keep_cursor else 0
            off_top = max(0, cursor - lines + 1)
            for line in rows[:off_top]:
                if scroll and self.scrollback.maxlen:
                    self.scrollback.append(line)
                    self.scrolled_off += 1
            del rows[:off_top]
            del rows[lines:]
            if keep_cursor:
                self.row -= off_top
        else:
            back = 0
            if scroll:
                back = min(lines - height, len(self.scrollback))
                for _ in range(back):
                    line = self.scrollback.pop()
                    self.scrolled_off -= 1
                    self._fit(line, self.columns)
                    rows.insert(0, line)
                if keep_cursor:
                    self.row += back
            rows.extend(self._blank_lines(lines - height - back))

    def text(self, lines: Iterable[Line]) -> str:
        """Lines as plain text.

        :param lines: The lines.
        """
        parts: list[str] = []
        for line in lines:
            text = "".join(cell[0] for cell in line).rstrip(" ")
            parts.append(text if line.wrapped else text + "\n")
        return "".join(parts).rstrip("\n")


TRACKING_MODES = frozenset({1000, 1002, 1003})
"""DEC modes that report the mouse."""

_MOUSE_BUTTONS = {"left": 0, "middle": 1, "right": 2}
_WHEEL = {"up": 64, "down": 65, "left": 66, "right": 67}


# pylint: disable-next=too-many-return-statements
def encode_mouse(
    event: MouseEvent, row: int, column: int, modes: set[int]
) -> bytes | None:
    """The bytes reporting mouse activity, or ``None``.

    :param event: The mouse event.
    :param row: Row in the terminal.
    :param column: Column in the terminal.
    :param modes: The program's mouse modes.
    """
    if not modes & TRACKING_MODES:
        return None
    action, button = event.action, event.button
    if action == "scroll":
        if button not in _WHEEL:
            return None
        code = _WHEEL[button]
    elif action == "move":
        if 1003 not in modes:
            return None
        code = 3 + 32  # no button, moving
    elif button not in _MOUSE_BUTTONS:
        return None
    elif action == "drag":
        if not modes & {1002, 1003}:
            return None
        code = _MOUSE_BUTTONS[button] + 32
    elif action == "release" and 1006 not in modes:
        code = 3  # the original form does not say which was let go
    else:
        code = _MOUSE_BUTTONS[button]
    code += 4 * event.shift + 8 * event.alt + 16 * event.ctrl
    x, y = column + 1, row + 1
    if 1006 in modes:
        final = "m" if action == "release" else "M"
        return f"\x1b[<{code};{x};{y}{final}".encode()
    if max(x, y) > 223:
        return None
    return b"\x1b[M" + bytes([32 + code, 32 + x, 32 + y])


_CURSOR_KEYS = {
    "up": "A",
    "down": "B",
    "right": "C",
    "left": "D",
    "home": "H",
    "end": "F",
}
_SS3_KEYS = {"f1": "P", "f2": "Q", "f3": "R", "f4": "S"}
_TILDE_KEYS = {
    "insert": 2,
    "delete": 3,
    "pageup": 5,
    "pagedown": 6,
    "f5": 15,
    "f6": 17,
    "f7": 18,
    "f8": 19,
    "f9": 20,
    "f10": 21,
    "f11": 23,
    "f12": 24,
}
_MODIFIER_BITS = {"shift": 1, "alt": 2, "ctrl": 4}
_CTRL_PUNCTUATION = {
    "@": "\x00",
    " ": "\x00",
    "2": "\x00",
    "[": "\x1b",
    "3": "\x1b",
    "\\": "\x1c",
    "4": "\x1c",
    "]": "\x1d",
    "5": "\x1d",
    "^": "\x1e",
    "6": "\x1e",
    "_": "\x1f",
    "/": "\x1f",
    "7": "\x1f",
    "?": "\x7f",
    "8": "\x7f",
}


def _split_key(key: str) -> tuple[set[str], str]:
    """A key name's modifiers and key.

    :param key: The key name.
    """
    if key.endswith("++"):
        return set(key[:-2].split("+")), "+"
    *modifiers, base = key.split("+")
    return set(modifiers), base


# pylint: disable-next=too-many-return-statements,too-many-branches
def encode_key(key: str, app_cursor_keys: bool = False) -> bytes | None:
    """The bytes a terminal sends for a key, or ``None``.

    :param key: The key name.
    :param app_cursor_keys: Whether application cursor keys are on.
    """
    if len(key) == 1:
        return key.encode("utf-8", "replace")
    if key.startswith("unknown("):
        return None
    modifiers, base = _split_key(key)
    if not modifiers <= set(_MODIFIER_BITS) or not base:
        return None
    bits = sum(_MODIFIER_BITS[modifier] for modifier in modifiers)
    if base in _CURSOR_KEYS:
        final = _CURSOR_KEYS[base]
        if bits:
            return f"\x1b[1;{bits + 1}{final}".encode()
        return (("\x1bO" if app_cursor_keys else "\x1b[") + final).encode()
    if base in _SS3_KEYS:
        final = _SS3_KEYS[base]
        return (f"\x1b[1;{bits + 1}{final}" if bits else "\x1bO" + final).encode()
    if base in _TILDE_KEYS:
        number = _TILDE_KEYS[base]
        return (f"\x1b[{number};{bits + 1}~" if bits else f"\x1b[{number}~").encode()
    alt = "alt" in modifiers
    ctrl = "ctrl" in modifiers
    if base == "tab":
        text = "\x1b[Z" if "shift" in modifiers else "\t"
    elif base == "enter":
        text = "\r"
    elif base == "backspace":
        text = "\x08" if ctrl else "\x7f"
    elif base == "escape":
        text = "\x1b"
    elif base in ("space", " "):
        text = "\x00" if ctrl else " "
    elif len(base) == 1:
        if ctrl:
            lower = base.lower()
            if "a" <= lower <= "z":
                text = chr(ord(lower) - ord("a") + 1)
            elif base in _CTRL_PUNCTUATION:
                text = _CTRL_PUNCTUATION[base]
            else:
                return None
        else:
            text = base.upper() if "shift" in modifiers else base
    else:
        return None
    return (("\x1b" if alt else "") + text).encode("utf-8", "replace")
