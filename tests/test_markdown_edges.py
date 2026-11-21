"""Tests for Markdown's less common corners."""

import unittest

from dasha.markdown import (
    EMPHASIS,
    LINK,
    TEXT,
    CodeBlock,
    ListBlock,
    Paragraph,
    Quote,
    Table,
    lay_out,
    parse,
    sections,
    title_of,
)
from tests.test_markdown import kinds_of, shown, spans_of


class InlineEdgeTests(unittest.TestCase):
    """Escapes, brackets and links inside links."""

    def test_a_backslash_before_a_letter_stays(self) -> None:
        """Only punctuation can be escaped."""
        self.assertEqual(kinds_of("a\\b"), [("a\\b", TEXT)])

    def test_unclosed_code_twice(self) -> None:
        """Backticks that never close stay, however many times."""
        self.assertEqual(kinds_of("`a ``"), [("`a ``", TEXT)])

    def test_escapes_inside_emphasis_and_links(self) -> None:
        """An escaped mark does not end emphasis, nor an escaped bracket a
        link."""
        self.assertEqual(kinds_of("*a\\*b*"), [("a*b", EMPHASIS)])
        spans = spans_of("[a\\]b](x.md)")
        self.assertEqual(
            [(span.text, span.target) for span in spans], [("a]b", "x.md")]
        )

    def test_links_inside_link_text(self) -> None:
        """A link or autolink inside a link's text is only text."""
        spans = spans_of("[a [b](c.md) <https://x.example> d](e.md)")
        self.assertEqual({span.target for span in spans}, {"e.md"})
        self.assertEqual({span.kind for span in spans}, {LINK})
        self.assertIn("https://x.example", "".join(span.text for span in spans))

    def test_an_unknown_reference_falls_back_to_the_label(self) -> None:
        """``[a][nope]`` with no ``nope`` uses ``a``'s target."""
        document = lay_out(parse("[a][nope]\n\n[a]: x.md"), 40)
        self.assertEqual([link.target for link in document.links], ["x.md"])

    def test_images_that_are_not(self) -> None:
        """An image with no closing bracket, or no target, is only text."""
        self.assertEqual(kinds_of("![a"), [("![a", TEXT)])
        self.assertEqual(kinds_of("![a] b"), [("![a] b", TEXT)])


class BlockEdgeTests(unittest.TestCase):
    """Where blocks end."""

    def test_not_a_table_delimiter(self) -> None:
        """A delimiter row with anything but dashes and colons is no table."""
        self.assertNotIsInstance(parse("| A |\n| -x- |\n")[0], Table)
        self.assertNotIsInstance(parse("| A |\n| -:- |\n")[0], Table)

    def test_indented_code_drops_trailing_blank_lines(self) -> None:
        """Blank lines after indented code are not part of it."""
        blocks = parse("    a\n    \n\nb")
        self.assertEqual(blocks[0], CodeBlock(["a"]))
        self.assertIsInstance(blocks[1], Paragraph)

    def test_a_quote_ends_at_another_block(self) -> None:
        """A line starting another block ends a quote."""
        blocks = parse("> a\n- b\n")
        self.assertIsInstance(blocks[0], Quote)
        self.assertIsInstance(blocks[1], ListBlock)


class SectionEdgeTests(unittest.TestCase):
    """The text of each section, from every kind of block."""

    def test_code_quotes_and_tables(self) -> None:
        """Code, quotes and tables are all searchable text."""
        page = "# H\n\n    code\n\n> quoted\n\n***\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
        found = sections(parse(page))
        self.assertEqual([part.text for part in found], ["code\nquoted\nA B\n1 2"])

    def test_nothing(self) -> None:
        """An empty page has no sections and no title."""
        self.assertEqual(sections([]), [])
        self.assertEqual(title_of(parse("just text")), "")


class LayoutEdgeTests(unittest.TestCase):
    """Laying out the edges."""

    def test_a_break_at_the_end(self) -> None:
        """A line break that ends a paragraph adds no line."""
        self.assertEqual(shown("a<br>"), ["a"])

    def test_a_wide_table_of_several_rows(self) -> None:
        """Rows of a written-out table are apart."""
        heads = " | ".join(f"H{number}" for number in range(10))
        first = " | ".join(f"a{number}" for number in range(10))
        second = " | ".join(f"b{number}" for number in range(10))
        lines = shown(f"| {heads} |\n{'|---' * 10}|\n| {first} |\n| {second} |\n", 20)
        self.assertEqual(lines[9:12], ["H9: a9", "", "H0: b0"])


if __name__ == "__main__":
    unittest.main()
