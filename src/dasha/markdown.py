"""Markdown parsing and layout for text screens."""

# pylint: disable=too-many-lines

import html
import re
import string
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

TEXT = "text"
"""Ordinary text."""
BOLD = "bold"
"""Bold text (``**like this**``), and the headings of tables."""
EMPHASIS = "emphasis"
"""Italic text (``*like this*``), and the place of an image."""
CODE = "code"
"""Code (```like this```, and fenced blocks)."""
LINK = "link"
"""A link's text."""
HEADING = "heading"
"""A heading, and its decoration."""

MAX_DEPTH = 16
"""Deepest nesting of quotes and lists."""
_MAX_INLINE_DEPTH = 8
_SCAN_LIMIT = 2000
"""How far to look for a link's target."""
_NARROWEST = 8
"""Least width left by nesting."""
_NARROWEST_COLUMN = 3
_BULLETS = ("\N{BULLET}", "\N{WHITE CIRCLE}", "-")
_RULE = "\N{BOX DRAWINGS LIGHT HORIZONTAL}"

_PLAIN = str.maketrans(
    {
        "\N{EN DASH}": "-",
        "\N{EM DASH}": "-",
        "\N{HORIZONTAL BAR}": "-",
        "\N{MINUS SIGN}": "-",
        "\N{LEFT SINGLE QUOTATION MARK}": "'",
        "\N{RIGHT SINGLE QUOTATION MARK}": "'",
        "\N{LEFT DOUBLE QUOTATION MARK}": '"',
        "\N{RIGHT DOUBLE QUOTATION MARK}": '"',
        "\N{HORIZONTAL ELLIPSIS}": "...",
        "\N{NO-BREAK SPACE}": " ",
        "\N{ZERO WIDTH SPACE}": "",
        "\N{ZERO WIDTH NO-BREAK SPACE}": "",
    }
)

_MARKER = re.compile(r"( {0,3})(?:[-*+]|(\d{1,9})[.)])(?: +|$)")
_REFERENCE = re.compile(r" {0,3}\[([^\[\]]+)\]:\s*<?([^\s<>]+)>?")
_ATX = re.compile(r" {0,3}(#{1,6})(?=\s|$)")
_FENCE = re.compile(r"( {0,3})(`{3,}|~{3,})")
_TARGET = re.compile(
    r"\(\s*(<[^<>\n]*>|[^\s()]*(?:\([^\s()]*\)[^\s()]*)*)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)
_REFERENCE_USE = re.compile(r"\[([^\[\]]*)\]")
_AUTOLINK = re.compile(r"<([a-zA-Z][a-zA-Z0-9+.-]+:[^\s<>]*)>")
_LINE_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"</?[a-zA-Z][^<>]*>|<!--.*?-->|<![^<>]*>", re.DOTALL)
_BARE_URL = re.compile(r"https?://[^\s<>]+")
_PARTS = re.compile(r"\n|[^\S\n]+|\S+")


@dataclass(frozen=True, slots=True)
class Span:
    """A piece of text of one kind."""

    text: str
    kind: str = TEXT
    link: int | None = None
    """The link it belongs to, by number."""
    target: str = ""
    """Where the link goes, as the page wrote it."""


type Line = list[Span]
"""One line to draw: its pieces, from left to right."""


@dataclass(frozen=True)
class Heading:
    """A heading: ``level`` runs from 1 to 6."""

    level: int
    spans: list[Span]
    slug: str
    """What a link calls it (``other.md#the-slug``)."""


@dataclass(frozen=True)
class Paragraph:
    """Text to wrap."""

    spans: list[Span]


@dataclass(frozen=True)
class CodeBlock:
    """Lines of code, kept as they are."""

    lines: list[str]


@dataclass(frozen=True)
class ListBlock:
    """A list: each item is blocks of its own."""

    ordered: bool
    start: int
    items: list[list["Block"]]


@dataclass(frozen=True)
class Quote:
    """A block quote."""

    blocks: list["Block"]


@dataclass(frozen=True)
class Rule:
    """A horizontal rule."""


@dataclass(frozen=True)
class Table:
    """A table block."""

    header: list[list[Span]]
    aligns: list[str]
    rows: list[list[list[Span]]]


type Block = Heading | Paragraph | CodeBlock | ListBlock | Quote | Rule | Table
"""One of the things a page is made of."""


# Reading lines


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_rule(line: str) -> bool:
    if _indent(line) > 3:
        return False
    marks = line.replace(" ", "")
    return len(marks) >= 3 and len(set(marks)) == 1 and marks[0] in "-*_"


def _is_quote(line: str) -> bool:
    return _indent(line) <= 3 and line.lstrip(" ").startswith(">")


def _unquoted(line: str) -> str:
    text = line.lstrip(" ")[1:]
    return text[1:] if text.startswith(" ") else text


def _cells(line: str) -> list[str]:
    """A table row's cells.

    :param line: The row.
    """
    text = line.strip()
    text = text[1:] if text.startswith("|") else text
    cells, start, at = [], 0, 0
    while at < len(text):
        if text[at] == "\\":
            at += 2
            continue
        if text[at] == "|":
            cells.append(text[start:at].strip())
            start = at + 1
        at += 1
    if text[start:].strip():
        cells.append(text[start:].strip())
    return cells


def _align_of(cell: str) -> str | None:
    """A delimiter cell's alignment, or ``None``.

    :param cell: The cell.
    """
    dashes = cell.strip(":")
    if not dashes or set(dashes) != {"-"} or ":" in cell[1:-1]:
        return None
    if cell.startswith(":") and cell.endswith(":"):
        return "centre"
    return "right" if cell.endswith(":") else "left"


def _is_table(lines: Sequence[str], at: int) -> bool:
    if at + 1 >= len(lines) or "|" not in lines[at] or "-" not in lines[at + 1]:
        return False
    aligns = [_align_of(cell) for cell in _cells(lines[at + 1])]
    return bool(aligns) and None not in aligns and len(aligns) == len(_cells(lines[at]))


def _starts_block(lines: Sequence[str], at: int) -> bool:
    """Whether a line starts a new block.

    :param lines: The lines.
    :param at: Line index.
    """
    line = lines[at]
    marker = _MARKER.match(line)
    return (
        _FENCE.match(line) is not None
        or _ATX.match(line) is not None
        or _is_rule(line)
        or _is_quote(line)
        or (marker is not None and marker.group(2) in (None, "1"))
        or _is_table(lines, at)
    )


# Reading blocks


class _Parser:
    """Parses one page.

    :param references: Link reference definitions.
    """

    def __init__(self, references: dict[str, str]) -> None:
        self.references = references
        self.links = 0
        self._slugs: dict[str, int] = {}

    def slug(self, title: str) -> str:
        """A unique slug for a heading.

        :param title: The heading text.
        """
        kept = "".join(c for c in title.lower() if c.isalnum() or c in " -_")
        base = kept.strip().replace(" ", "-")
        count = self._slugs.get(base, 0)
        self._slugs[base] = count + 1
        return f"{base}-{count}" if count else base

    def inline(self, text: str, kind: str = TEXT) -> list[Span]:
        """Parse inline text into pieces.

        :param text: The text.
        :param kind: Its kind of text.
        """
        return _Inline(self, text, kind).spans()

    def blocks(self, lines: Sequence[str], depth: int = 0) -> list[Block]:
        """Parse lines into blocks.

        :param lines: The lines.
        :param depth: Nesting depth.
        """
        found: list[Block] = []
        at = 0
        while at < len(lines):
            if not lines[at].strip():
                at += 1
                continue
            block, at = self._block(lines, at, depth)
            if block is not None:
                found.append(block)
        return found

    def _block(
        self, lines: Sequence[str], at: int, depth: int
    ) -> tuple[Block | None, int]:
        """The block at a line and the next line.

        :param lines: The lines.
        :param at: Line index.
        :param depth: Nesting depth.
        """
        line = lines[at]
        result: tuple[Block | None, int]
        if line.lstrip().startswith("<!--"):
            result = self._comment(lines, at)
        elif (fence := _FENCE.match(line)) is not None:
            result = self._fenced(lines, at, fence)
        elif _indent(line) >= 4:
            result = self._indented(lines, at)
        elif (hashes := _ATX.match(line)) is not None:
            result = self._atx(line, hashes), at + 1
        elif _is_rule(line):
            result = Rule(), at + 1
        elif depth < MAX_DEPTH and _is_quote(line):
            result = self._quote(lines, at, depth)
        elif depth < MAX_DEPTH and _MARKER.match(line) is not None:
            result = self._list(lines, at, depth)
        elif _is_table(lines, at):
            result = self._table(lines, at)
        else:
            result = self._paragraph(lines, at)
        return result

    @staticmethod
    def _comment(lines: Sequence[str], at: int) -> tuple[None, int]:
        """An HTML comment's end.

        :param lines: The lines.
        :param at: Line index.
        """
        for end in range(at, len(lines)):
            if "-->" in lines[end]:
                return None, end + 1
        return None, len(lines)

    @staticmethod
    def _fenced(
        lines: Sequence[str], at: int, fence: re.Match[str]
    ) -> tuple[CodeBlock, int]:
        indent, mark = len(fence.group(1)), fence.group(2)
        code: list[str] = []
        at += 1
        while at < len(lines):
            line = lines[at]
            stripped = line.strip()
            if (
                len(stripped) >= len(mark)
                and set(stripped) == {mark[0]}
                and _indent(line) <= 3
            ):
                return CodeBlock(code), at + 1
            code.append(line[min(indent, _indent(line)) :])
            at += 1
        return CodeBlock(code), at

    @staticmethod
    def _indented(lines: Sequence[str], at: int) -> tuple[CodeBlock, int]:
        code = []
        while at < len(lines) and (_indent(lines[at]) >= 4 or not lines[at].strip()):
            code.append(lines[at][4:])
            at += 1
        while code and not code[-1].strip():
            code.pop()
        return CodeBlock(code), at

    def _atx(self, line: str, hashes: re.Match[str]) -> Heading:
        title = line[hashes.end() :].strip()
        closed = title.rstrip("#")
        if closed != title and (not closed or closed[-1] == " "):
            title = closed.rstrip()
        return self._heading(len(hashes.group(1)), title)

    def _heading(self, level: int, title: str) -> Heading:
        spans = self.inline(title, HEADING)
        return Heading(level, spans, self.slug(_text_of(spans)))

    def _quote(
        self, lines: Sequence[str], at: int, depth: int
    ) -> tuple[Quote | Paragraph, int]:
        inside = []
        while at < len(lines) and lines[at].strip():
            if _is_quote(lines[at]):
                inside.append(_unquoted(lines[at]))
            elif inside and inside[-1].strip() and not _starts_block(lines, at):
                inside.append(lines[at].strip())  # carries on the paragraph
            else:
                break
            at += 1
        return Quote(self.blocks(inside, depth + 1)), at

    def _list(self, lines: Sequence[str], at: int, depth: int) -> tuple[ListBlock, int]:
        first = _MARKER.match(lines[at])
        assert first is not None
        ordered = first.group(2) is not None
        items: list[list[Block]] = []
        while at < len(lines):
            marker = _MARKER.match(lines[at])
            if marker is None or (marker.group(2) is not None) != ordered:
                break
            inside, at = self._item(lines, at, marker)
            items.append(self.blocks(inside, depth + 1))
            following = _next_line(lines, at)
            if following >= len(lines) or _MARKER.match(lines[following]) is None:
                break
            at = following
        return ListBlock(ordered, int(first.group(2) or 1), items), at

    @staticmethod
    def _item(
        lines: Sequence[str], at: int, marker: re.Match[str]
    ) -> tuple[list[str], int]:
        """One list item's lines and the next line.

        :param lines: The lines.
        :param at: Line index.
        :param marker: The item marker match.
        """
        rest = lines[at][marker.end() :]
        content = marker.end() if rest.strip() else len(marker.group(0).rstrip()) + 1
        inside = [rest]
        at += 1
        while at < len(lines):
            line = lines[at]
            if not line.strip():
                following = _next_line(lines, at)
                if following >= len(lines) or _indent(lines[following]) < content:
                    break
                inside += [""] * (following - at)
                at = following
                continue
            sub = _MARKER.match(line)
            if _indent(line) >= content:
                inside.append(line[content:])
            elif sub is not None and _indent(line) > len(marker.group(1)):
                inside.append(line[_indent(line) :])
            elif sub is not None or _starts_block(lines, at):
                break
            else:
                inside.append(line.strip())
            at += 1
        return inside, at

    def _table(self, lines: Sequence[str], at: int) -> tuple[Table, int]:
        heads = _cells(lines[at])
        aligns = [_align_of(cell) or "left" for cell in _cells(lines[at + 1])]
        at += 2
        rows = []
        while (
            at < len(lines)
            and lines[at].strip()
            and "|" in lines[at]
            and not _starts_block(lines, at)
        ):
            cells = _cells(lines[at])[: len(heads)]
            cells += [""] * (len(heads) - len(cells))
            rows.append([self.inline(cell) for cell in cells])
            at += 1
        return Table([self.inline(head, BOLD) for head in heads], aligns, rows), at

    def _paragraph(
        self, lines: Sequence[str], at: int
    ) -> tuple[Paragraph | Heading, int]:
        """A paragraph or setext heading.

        :param lines: The lines.
        :param at: Line index.
        """
        parts = [lines[at]]
        at += 1
        while at < len(lines) and lines[at].strip():
            marks = lines[at].strip()
            if _indent(lines[at]) <= 3 and set(marks) in ({"="}, {"-"}):
                text = " ".join(part.strip() for part in parts)
                return self._heading(1 if marks[0] == "=" else 2, text), at + 1
            if _starts_block(lines, at):
                break
            parts.append(lines[at])
            at += 1
        return Paragraph(self.inline(_joined(parts))), at


def _next_line(lines: Sequence[str], at: int) -> int:
    """The first non-blank line from an index.

    :param lines: The lines.
    :param at: Line index.
    """
    while at < len(lines) and not lines[at].strip():
        at += 1
    return at


def _joined(parts: Sequence[str]) -> str:
    """A paragraph's lines joined.

    :param parts: The lines.
    """
    text = ""
    for number, part in enumerate(parts):
        stripped = part.strip()
        last = number == len(parts) - 1
        if not last and part.endswith("  "):
            text += stripped + "\n"
        elif not last and stripped.endswith("\\"):
            text += stripped[:-1] + "\n"
        else:
            text += stripped + ("" if last else " ")
    return text


def _text_of(spans: Sequence[Span]) -> str:
    return "".join(span.text for span in spans).replace("\n", " ")


# Reading text inside a block


class _Inline:  # pylint: disable=too-few-public-methods
    """Parses inline Markdown.

    :param parser: The page parser.
    :param text: The text.
    :param kind: Its kind of text.
    :param link: Link number, if inside one.
    :param target: Link target, if inside one.
    :param depth: Nesting depth.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        parser: _Parser,
        text: str,
        kind: str,
        *,
        link: int | None = None,
        target: str = "",
        depth: int = 0,
    ) -> None:
        self.parser = parser
        self.text = text
        self.kind = kind
        self.link = link
        self.target = target
        self.depth = depth
        self.found: list[Span] = []
        self.plain: list[str] = []
        # What has already been looked for to the end of the text, and not
        # found, so that a page of unmatched marks is read once, not over
        # and over.
        self._no_end: set[tuple[str, int]] = set()
        self._brackets: dict[int, int] | None = None

    def spans(self) -> list[Span]:
        """The pieces of the text."""
        handlers = {
            "\\": self._escape,
            "\n": self._line_break,
            "`": self._code,
            "!": self._image,
            "[": self._link,
            "<": self._angle,
            "*": self._emphasis,
            "_": self._emphasis,
            "h": self._bare_url,
        }
        at = 0
        while at < len(self.text):
            handler = handlers.get(self.text[at])
            after = handler(at) if handler is not None else None
            if after is None:
                self.plain.append(self.text[at])
                at += 1
            else:
                at = after
        self._flush()
        return self.found

    def _flush(self) -> None:
        if self.plain:
            text = html.unescape("".join(self.plain))
            self.plain = []
            self.found.append(Span(text, self.kind, self.link, self.target))

    def _emit(self, text: str, kind: str) -> None:
        self._flush()
        self.found.append(Span(text, kind, self.link, self.target))

    def _within(self, kind: str) -> str:
        """The kind for nested text.

        :param kind: The inner kind.
        """
        if self.kind in (LINK, HEADING):
            return self.kind
        return BOLD if BOLD in (self.kind, kind) else kind

    def _inner(self, text: str, kind: str) -> list[Span]:
        return _Inline(
            self.parser,
            text,
            kind,
            link=self.link,
            target=self.target,
            depth=self.depth + 1,
        ).spans()

    def _escape(self, at: int) -> int | None:
        following = self.text[at + 1 : at + 2]
        if following and following in string.punctuation:
            self.plain.append(following)
            return at + 2
        return None

    def _line_break(self, at: int) -> int:
        self._emit("\n", self.kind)
        return at + 1

    def _run_at(self, at: int) -> int:
        """Run length of a repeated character.

        :param at: Position.
        """
        end = at
        while end < len(self.text) and self.text[end] == self.text[at]:
            end += 1
        return end - at

    def _code(self, at: int) -> int | None:
        size = self._run_at(at)
        if ("`", size) in self._no_end:
            return None
        end = at + size
        while (end := self.text.find("`", end)) != -1:
            run = self._run_at(end)
            if run == size:
                code = self.text[at + size : end].replace("\n", " ")
                if code.startswith(" ") and code.endswith(" ") and code.strip():
                    code = code[1:-1]
                self._emit(code, self.kind if self.kind in (LINK, HEADING) else CODE)
                return end + size
            end += run
        self._no_end.add(("`", size))
        return None

    def _emphasis(self, at: int) -> int | None:
        char = self.text[at]
        run = self._run_at(at)
        size = min(run, 3)
        before = self.text[at - 1] if at else " "
        after = self.text[at + size : at + size + 1]
        if (
            not after
            or after.isspace()
            or (char == "_" and before.isalnum())
            or self.depth >= _MAX_INLINE_DEPTH
        ):
            return None
        end = self._emphasis_end(at + size, char, size)
        if end is None:
            return None
        self._flush()
        kind = self._within(EMPHASIS if size == 1 else BOLD)
        self.found += self._inner(self.text[at + size : end], kind)
        return end + size

    def _emphasis_end(self, at: int, char: str, size: int) -> int | None:
        """Where emphasis closes.

        :param at: Position after the opener.
        :param char: The emphasis character.
        :param size: The opener's length.
        """
        if (char, size) in self._no_end:
            return None
        text = self.text
        while at < len(text):
            if text[at] == "\\":
                at += 2
            elif text[at] != char:
                at += 1
            else:
                run = self._run_at(at)
                fits = run >= 3 if size == 3 else run in (size, 3)
                after = text[at + run : at + run + 1]
                if (
                    fits
                    and not text[at - 1].isspace()
                    and not (char == "_" and after.isalnum())
                ):
                    return at + run - size
                at += run
        self._no_end.add((char, size))
        return None

    def _closing_bracket(self, at: int) -> int | None:
        """The matching ``]``.

        :param at: Position of the ``[``.
        """
        if self._brackets is None:
            self._brackets = {}
            opened = []
            position = 0
            while position < len(self.text):
                char = self.text[position]
                if char == "\\":
                    position += 1
                elif char == "[":
                    opened.append(position)
                elif char == "]" and opened:
                    self._brackets[opened.pop()] = position
                position += 1
        return self._brackets.get(at)

    def _destination(self, at: int, label: str) -> tuple[str, int] | None:
        """A link's target and the position after it.

        :param at: Position after the link text.
        :param label: The link text.
        """
        references = self.parser.references
        if self.text[at : at + 1] == "(":
            found = _TARGET.match(self.text, at, at + _SCAN_LIMIT)
            if found is not None:
                target = found.group(1)
                if target.startswith("<"):
                    target = target[1:-1]
                return target, found.end()
        used = _REFERENCE_USE.match(self.text, at, at + _SCAN_LIMIT)
        if used is not None:
            name = (used.group(1) or label).strip().lower()
            if name in references:
                return references[name], used.end()
        if label.strip().lower() in references:
            return references[label.strip().lower()], at
        return None

    def _link(self, at: int) -> int | None:
        if self.link is not None or self.depth >= _MAX_INLINE_DEPTH:
            return None
        close = self._closing_bracket(at)
        if close is None:
            return None
        label = self.text[at + 1 : close]
        destination = self._destination(close + 1, label)
        if destination is None:
            return None
        target, after = destination
        self._flush()
        number = self.parser.links
        self.parser.links += 1
        self.found += _Inline(
            self.parser, label, LINK, link=number, target=target, depth=self.depth + 1
        ).spans()
        return after

    def _image(self, at: int) -> int | None:
        if self.text[at + 1 : at + 2] != "[" or self.depth >= _MAX_INLINE_DEPTH:
            return None
        close = self._closing_bracket(at + 1)
        if close is None:
            return None
        label = self.text[at + 2 : close]
        destination = self._destination(close + 1, label)
        if destination is None:
            return None
        alt = _text_of(self._inner(label, self.kind)).strip()
        self._emit(f"[Image: {alt}]" if alt else "[Image]", self._within(EMPHASIS))
        return destination[1]

    def _add_link(self, text: str, target: str) -> None:
        self._flush()
        number = self.parser.links
        self.parser.links += 1
        self.found.append(Span(text, LINK, number, target))

    def _angle(self, at: int) -> int | None:
        """An autolink, line break or HTML tag.

        :param at: Position of the ``<``.
        """
        found = _AUTOLINK.match(self.text, at)
        if found is not None:
            if self.link is None:
                self._add_link(found.group(1), found.group(1))
            else:
                self._emit(found.group(1), self.kind)
            return found.end()
        found = _LINE_BREAK.match(self.text, at)
        if found is not None:
            self._emit("\n", self.kind)
            return found.end()
        found = _TAG.match(self.text, at)
        return found.end() if found is not None else None

    def _bare_url(self, at: int) -> int | None:
        """A bare web address.

        :param at: Position.
        """
        if self.link is not None or (at and self.text[at - 1].isalnum()):
            return None
        found = _BARE_URL.match(self.text, at)
        if found is None:
            return None
        address = found.group(0).rstrip(".,;:!?)'\"*_")
        self._add_link(address, address)
        return at + len(address)


def parse(text: str) -> list[Block]:
    """Parse a Markdown page into blocks.

    :param text: The Markdown.
    """
    lines = text.translate(_PLAIN).expandtabs(4).splitlines()
    references: dict[str, str] = {}
    kept = []
    fenced = False
    for line in lines:
        if _FENCE.match(line):
            fenced = not fenced
        found = None if fenced else _REFERENCE.fullmatch(line.rstrip())
        if found is not None:
            references[found.group(1).strip().lower()] = found.group(2)
        else:
            kept.append(line)
    return _Parser(references).blocks(kept)


# What a page says, for finding things in it


@dataclass(frozen=True)
class Section:
    """The text of a page under one heading, for searching."""

    title: str
    """The heading's text (``""`` for what comes before the first)."""
    slug: str
    """What a link calls the heading (``""`` for no heading)."""
    text: str
    """Its words, a line for each block, without any Markdown."""


def _plain_lines(block: Block) -> list[str]:
    """A block's plain text lines.

    :param block: The block.
    """
    lines: list[str] = []
    if isinstance(block, Paragraph):
        lines.append(_text_of(block.spans))
    elif isinstance(block, CodeBlock):
        lines += block.lines
    elif isinstance(block, ListBlock):
        for item in block.items:
            for inside in item:
                lines += _plain_lines(inside)
    elif isinstance(block, Quote):
        for inside in block.blocks:
            lines += _plain_lines(inside)
    elif isinstance(block, Table):
        for row in [block.header, *block.rows]:
            lines.append(" ".join(_text_of(cell) for cell in row))
    return lines


def sections(blocks: Sequence[Block]) -> list[Section]:
    """A page's text, by heading.

    :param blocks: The page's blocks.
    """
    found: list[Section] = []
    title, slug = "", ""
    lines: list[str] = []
    for block in blocks:
        if isinstance(block, Heading):
            if lines:
                found.append(Section(title, slug, "\n".join(lines)))
            title, slug, lines = _text_of(block.spans), block.slug, []
        else:
            lines += _plain_lines(block)
    if lines or title:
        found.append(Section(title, slug, "\n".join(lines)))
    return found


def title_of(blocks: Sequence[Block]) -> str:
    """A page's first heading, or "".

    :param blocks: The page's blocks.
    """
    for block in blocks:
        if isinstance(block, Heading):
            return _text_of(block.spans)
    return ""


# Laying out


@dataclass
class Link:
    """One link on a page, as laid out."""

    key: int
    """The number that its pieces carry (``Span.link``)."""
    target: str
    """Where it goes, as the page wrote it."""
    places: list[tuple[int, int, int]] = field(default_factory=list)
    """Where its pieces are, as (row, column, length)."""

    @property
    def row(self) -> int:
        """The row it starts on."""
        return self.places[0][0]

    @property
    def last_row(self) -> int:
        """The row it ends on."""
        return self.places[-1][0]


@dataclass
class Document:
    """A page laid out to a width."""

    lines: list[Line]
    """The lines to draw."""
    links: list[Link]
    """Its links, from the top of the page."""
    anchors: dict[str, int]
    """The row of each heading, by slug."""

    def link_at(self, row: int, column: int) -> int | None:
        """The link number at a place, if any.

        :param row: Line number.
        :param column: Column.
        """
        for number, link in enumerate(self.links):
            for at_row, at_column, length in link.places:
                if at_row == row and at_column <= column < at_column + length:
                    return number
        return None

    def text(self, row: int) -> str:
        """A line's characters.

        :param row: Line number.
        """
        return "".join(span.text for span in self.lines[row])


class _Wrapper:
    """Wraps pieces of text to a width.

    :param width: Line width.
    """

    def __init__(self, width: int) -> None:
        self.width = max(1, width)
        self.lines: list[Line] = []
        self.line: Line = []
        self.used = 0
        self.word: list[Span] = []
        self.gap: Span | None = None

    def add(self, span: Span) -> None:
        """Add a piece of text.

        :param span: The piece.
        """
        for part in _PARTS.findall(span.text):
            if part == "\n":
                self._end_word()
                self._break()
            elif part.isspace():
                self._end_word()
                self.gap = self.gap or replace(span, text=" ")
            else:
                self.word.append(replace(span, text=part))

    def _end_word(self) -> None:
        """Place the pending word."""
        if not self.word:
            return
        length = sum(len(piece.text) for piece in self.word)
        gap = self.gap if self.used else None
        if self.used and self.used + (1 if gap else 0) + length > self.width:
            self._break()
            gap = None
        if gap is not None:
            self.line.append(gap)
            self.used += 1
        for piece in self.word:
            text = piece.text
            while text:
                if self.used >= self.width:
                    self._break()
                room = self.width - self.used
                self.line.append(replace(piece, text=text[:room]))
                self.used += len(text[:room])
                text = text[room:]
        self.word = []
        self.gap = None

    def _break(self) -> None:
        self.lines.append(_merged(self.line))
        self.line = []
        self.used = 0
        self.gap = None

    def finish(self) -> list[Line]:
        """The lines, once everything has been added."""
        self._end_word()
        if self.line or not self.lines:
            self._break()
        return self.lines


def _merged(line: Line) -> Line:
    """A line with like pieces merged.

    :param line: The line.
    """
    merged: Line = []
    for span in line:
        if merged and replace(merged[-1], text="") == replace(span, text=""):
            merged[-1] = replace(merged[-1], text=merged[-1].text + span.text)
        else:
            merged.append(span)
    return merged


def _wrapped(spans: Sequence[Span], width: int) -> list[Line]:
    wrapper = _Wrapper(width)
    for span in spans:
        wrapper.add(span)
    return wrapper.finish()


def _length(line: Line) -> int:
    return sum(len(span.text) for span in line)


@dataclass
class _Laid:
    """Lines laid out, with the rows of the headings among them."""

    lines: list[Line] = field(default_factory=list)
    anchors: dict[str, int] = field(default_factory=dict)

    def extend(self, other: "_Laid") -> None:
        """Add lines below.

        :param other: The lines to add.
        """
        offset = len(self.lines)
        self.lines += other.lines
        for slug, row in other.anchors.items():
            self.anchors.setdefault(slug, offset + row)


def _laid_heading(block: Heading, width: int) -> _Laid:
    mark = "\N{BOX DRAWINGS DOUBLE HORIZONTAL}" * 3
    if block.level == 1 and width >= _NARROWEST + 2:
        lines = [
            [Span(f"{mark} ", HEADING), *line, Span(f" {mark}", HEADING)]
            for line in _wrapped(block.spans, width - len(mark) * 2 - 2)
        ]
    elif block.level == 2:
        lines = _wrapped(block.spans, width)
        longest = max(_length(line) for line in lines)
        lines.append([Span(_RULE * min(longest, width), HEADING)])
    elif block.level == 3 and width >= _NARROWEST:
        lines = _wrapped(block.spans, width - 3)
        lines = [
            [Span(_RULE * 2 + " " if number == 0 else "   ", HEADING), *line]
            for number, line in enumerate(lines)
        ]
    else:
        lines = _wrapped(block.spans, width)
    return _Laid(lines, {block.slug: 0})


def _laid_code(block: CodeBlock, width: int) -> _Laid:
    """A code block laid out.

    :param block: The code block.
    :param width: Page width.
    """
    inner = max(1, width - 2)
    lines: list[Line] = []
    for line in block.lines or [""]:
        pieces = [line[at : at + inner] for at in range(0, len(line), inner)] or [""]
        lines += [[Span(f" {piece.ljust(inner)} ", CODE)] for piece in pieces]
    return _Laid(lines)


def _prefixed(laid: _Laid, first: str, others: str) -> None:
    """Prefix lines in place.

    :param laid: The lines.
    :param first: Prefix for the first line.
    :param others: Prefix for the rest.
    """
    laid.lines = [
        [Span(first if number == 0 else others), *line]
        for number, line in enumerate(laid.lines or [[]])
    ]


def _laid_list(block: ListBlock, width: int, depth: int) -> _Laid:
    laid = _Laid()
    last_number = block.start + len(block.items) - 1
    size = len(str(last_number)) + 2
    bullet = _BULLETS[min(depth, len(_BULLETS) - 1)]
    for number, item in enumerate(block.items):
        if block.ordered:
            marker = f"{block.start + number}.".ljust(size)
        else:
            marker = f"{bullet} "
        inner = _stack(item, max(_NARROWEST, width - len(marker)), depth + 1, True)
        _prefixed(inner, marker, " " * len(marker))
        laid.extend(inner)
    return laid


def _laid_quote(block: Quote, width: int, depth: int) -> _Laid:
    line = "\N{BOX DRAWINGS LIGHT VERTICAL} "
    laid = _stack(block.blocks, max(_NARROWEST, width - len(line)), depth, False)
    _prefixed(laid, line, line)
    return laid


def _column_widths(block: Table, room: int) -> list[int] | None:
    """Column widths to fit, or ``None``.

    :param block: The table.
    :param room: Width available.
    """
    if _NARROWEST_COLUMN * len(block.header) > room:
        return None
    widths = []
    for number, head in enumerate(block.header):
        cells = [head, *(row[number] for row in block.rows)]
        widths.append(max(1, min(room, max(len(_text_of(cell)) for cell in cells))))
    while sum(widths) > room:
        widths[widths.index(max(widths))] -= 1
    return widths


def _aligned(line: Line, width: int, align: str) -> Line:
    """A cell line padded to its column.

    :param line: The line.
    :param width: Column width.
    :param align: Alignment.
    """
    spare = max(0, width - _length(line))
    before = {"left": 0, "centre": spare // 2, "right": spare}[align]
    return [Span(" " * before), *line, Span(" " * (spare - before))]


def _table_row(
    cells: Sequence[list[Span]], widths: list[int], aligns: list[str]
) -> list[Line]:
    """One table row's lines.

    :param cells: The row's cells.
    :param widths: Column widths.
    :param aligns: Column alignments.
    """
    upright = Span("\N{BOX DRAWINGS LIGHT VERTICAL}")
    columns = [_wrapped(cell, width) for cell, width in zip(cells, widths)]
    lines = []
    for row in range(max(len(column) for column in columns)):
        line: Line = [upright]
        for column, width, align in zip(columns, widths, aligns):
            text = column[row] if row < len(column) else []
            line += [Span(" "), *_aligned(text, width, align), Span(" "), upright]
        lines.append(_merged(line))
    return lines


def _table_edge(widths: list[int], left: str, middle: str, right: str) -> Line:
    parts = [_RULE * (width + 2) for width in widths]
    return [Span(left + middle.join(parts) + right)]


def _laid_table(block: Table, width: int) -> _Laid:
    borders = len(block.header) * 3 + 1
    widths = _column_widths(block, width - borders)
    if widths is None:
        return _table_written_out(block, width)
    lines = [
        _table_edge(
            widths,
            "\N{BOX DRAWINGS LIGHT DOWN AND RIGHT}",
            "\N{BOX DRAWINGS LIGHT DOWN AND HORIZONTAL}",
            "\N{BOX DRAWINGS LIGHT DOWN AND LEFT}",
        ),
        *_table_row(block.header, widths, block.aligns),
        _table_edge(
            widths,
            "\N{BOX DRAWINGS LIGHT VERTICAL AND RIGHT}",
            "\N{BOX DRAWINGS LIGHT VERTICAL AND HORIZONTAL}",
            "\N{BOX DRAWINGS LIGHT VERTICAL AND LEFT}",
        ),
    ]
    for row in block.rows:
        lines += _table_row(row, widths, block.aligns)
    lines.append(
        _table_edge(
            widths,
            "\N{BOX DRAWINGS LIGHT UP AND RIGHT}",
            "\N{BOX DRAWINGS LIGHT UP AND HORIZONTAL}",
            "\N{BOX DRAWINGS LIGHT UP AND LEFT}",
        )
    )
    return _Laid(lines)


def _table_written_out(block: Table, width: int) -> _Laid:
    """A too-wide table as ``Heading: value`` lines.

    :param block: The table.
    :param width: Page width.
    """
    laid = _Laid()
    empty: list[list[Span]] = [[] for _ in block.header]
    for number, row in enumerate(block.rows or [empty]):
        if number:
            laid.lines.append([])
        for head, cell in zip(block.header, row):
            laid.lines += _wrapped([*head, Span(": ", BOLD), *cell], width)
    return laid


def _laid_block(  # pylint: disable=too-many-return-statements
    block: Block, width: int, depth: int
) -> _Laid:
    if isinstance(block, Heading):
        return _laid_heading(block, width)
    if isinstance(block, Paragraph):
        return _Laid(_wrapped(block.spans, width))
    if isinstance(block, CodeBlock):
        return _laid_code(block, width)
    if isinstance(block, ListBlock):
        return _laid_list(block, width, depth)
    if isinstance(block, Quote):
        return _laid_quote(block, width, depth)
    if isinstance(block, Table):
        return _laid_table(block, width)
    return _Laid([[Span(_RULE * width)]])


def _stack(blocks: Sequence[Block], width: int, depth: int, in_item: bool) -> _Laid:
    """Lay blocks out one below another.

    :param blocks: The blocks.
    :param width: Page width.
    :param depth: Nesting depth.
    :param in_item: Whether inside a list item.
    """
    laid = _Laid()
    for number, block in enumerate(blocks):
        if number and not (in_item and isinstance(block, ListBlock)):
            laid.lines.append([])
        laid.extend(_laid_block(block, width, depth))
    return laid


def lay_out(blocks: Sequence[Block], width: int) -> Document:
    """Lay blocks out to a width.

    :param blocks: The blocks.
    :param width: Page width.
    """
    laid = _stack(blocks, max(1, width), 0, False)
    links: dict[int, Link] = {}
    for row, line in enumerate(laid.lines):
        column = 0
        for span in line:
            if span.link is not None:
                link = links.setdefault(span.link, Link(span.link, span.target))
                link.places.append((row, column, len(span.text)))
            column += len(span.text)
    return Document(laid.lines, list(links.values()), laid.anchors)
