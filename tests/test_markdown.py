"""Tests for Markdown: what it reads, and how it lays pages out."""

import unittest

from dasha.markdown import (
    BOLD,
    CODE,
    EMPHASIS,
    HEADING,
    LINK,
    TEXT,
    CodeBlock,
    Document,
    Heading,
    ListBlock,
    Paragraph,
    Quote,
    Rule,
    Span,
    Table,
    lay_out,
    parse,
    sections,
    title_of,
)


def laid(text: str, width: int = 40) -> Document:
    """A page, laid out.

    :param text: The Markdown.
    :param width: Page width.
    """
    return lay_out(parse(text), width)


def shown(text: str, width: int = 40) -> list[str]:
    """A page's lines as text.

    :param text: The Markdown.
    :param width: Page width.
    """
    document = laid(text, width)
    return [document.text(row) for row in range(len(document.lines))]


def spans_of(text: str) -> list[Span]:
    """The pieces of a paragraph.

    :param text: The Markdown.
    """
    block = parse(text)[0]
    assert isinstance(block, Paragraph)
    return block.spans


def kinds_of(text: str) -> list[tuple[str, str]]:
    """Each piece's text and kind.

    :param text: The Markdown.
    """
    return [(span.text, span.kind) for span in spans_of(text)]


class InlineTests(unittest.TestCase):
    """Bold, italics, code and so on, inside a block."""

    def test_plain(self) -> None:
        """Plain."""
        self.assertEqual(kinds_of("Just text"), [("Just text", TEXT)])

    def test_bold(self) -> None:
        """Bold."""
        for text in ("a **b** c", "a __b__ c"):
            with self.subTest(text=text):
                self.assertEqual(
                    kinds_of(text), [("a ", TEXT), ("b", BOLD), (" c", TEXT)]
                )

    def test_italics(self) -> None:
        """Italics."""
        for text in ("a *b* c", "a _b_ c"):
            with self.subTest(text=text):
                self.assertEqual(
                    kinds_of(text), [("a ", TEXT), ("b", EMPHASIS), (" c", TEXT)]
                )

    def test_bold_and_italics_together(self) -> None:
        """Bold and italics together."""
        self.assertEqual(kinds_of("***b***"), [("b", BOLD)])
        self.assertEqual(
            kinds_of("**a *b* c**"), [("a ", BOLD), ("b", BOLD), (" c", BOLD)]
        )
        self.assertEqual(
            kinds_of("*a **b** c*"), [("a ", EMPHASIS), ("b", BOLD), (" c", EMPHASIS)]
        )

    def test_marks_that_mean_nothing(self) -> None:
        """Marks that mean nothing stay."""
        for text in ("2 * 3 * 4", "*open", "**open", "snake_case_name", "`open"):
            with self.subTest(text=text):
                self.assertEqual(kinds_of(text), [(text, TEXT)])

    def test_code(self) -> None:
        """Code."""
        self.assertEqual(
            kinds_of("a `b*c*` d"), [("a ", TEXT), ("b*c*", CODE), (" d", TEXT)]
        )
        self.assertEqual(kinds_of("``a`b``"), [("a`b", CODE)])
        self.assertEqual(kinds_of("` a `"), [("a", CODE)])

    def test_escapes_and_entities(self) -> None:
        """Escapes and entities."""
        self.assertEqual(kinds_of(r"\*not\* \[it\]"), [("*not* [it]", TEXT)])
        self.assertEqual(
            kinds_of("a &amp; b &copy;"), [("a & b \N{COPYRIGHT SIGN}", TEXT)]
        )

    def test_typography_becomes_plain(self) -> None:
        """Characters that code page 437 does not have."""
        text = (
            "\N{EM DASH}\N{EN DASH}\N{LEFT DOUBLE QUOTATION MARK}a"
            "\N{RIGHT SINGLE QUOTATION MARK}\N{HORIZONTAL ELLIPSIS}"
        )
        self.assertEqual(kinds_of(text), [("--\"a'...", TEXT)])

    def test_html_is_removed(self) -> None:
        """Html is removed."""
        self.assertEqual(
            kinds_of('a <b class="x">b</b> <!-- no --> c'), [("a b  c", TEXT)]
        )
        self.assertEqual(kinds_of("1 < 2 > 0"), [("1 < 2 > 0", TEXT)])

    def test_line_breaks(self) -> None:
        """Line breaks."""
        self.assertEqual(shown("a\nb"), ["a b"])
        self.assertEqual(shown("a  \nb"), ["a", "b"])
        self.assertEqual(shown("a\\\nb"), ["a", "b"])
        self.assertEqual(shown("a<br>b<BR/>c"), ["a", "b", "c"])

    def test_images(self) -> None:
        """Images."""
        self.assertEqual(shown("![A cat](cat.png)"), ["[Image: A cat]"])
        self.assertEqual(shown("![](cat.png)"), ["[Image]"])

    def test_links(self) -> None:
        """Links."""
        spans = spans_of('see [the *other* page](other.md "Title") now')
        self.assertEqual(spans[0].text, "see ")
        self.assertEqual({span.target for span in spans[1:-1]}, {"other.md"})
        self.assertEqual({span.kind for span in spans[1:-1]}, {LINK})
        self.assertEqual(len({span.link for span in spans[1:-1]}), 1)
        self.assertEqual("".join(span.text for span in spans[1:-1]), "the other page")

    def test_targets(self) -> None:
        """Targets."""
        for text, target in (
            ("[a](b.md#c)", "b.md#c"),
            ("[a](<b c.md>)", "b c.md"),
            ("[a](b(c).md)", "b(c).md"),
            ("<https://example.com>", "https://example.com"),
            ("https://example.com.", "https://example.com"),
            ("[image ![a](b.png)](c.md)", "c.md"),
        ):
            with self.subTest(text=text):
                targets = [
                    span.target for span in spans_of(text) if span.link is not None
                ]
                self.assertEqual(set(targets), {target})

    def test_references(self) -> None:
        """References."""
        document = laid(
            "[a][one], [two][] and [three].\n\n[one]: a.md\n[two]: b.md\n[three]: c.md"
        )
        self.assertEqual(
            [link.target for link in document.links], ["a.md", "b.md", "c.md"]
        )
        self.assertEqual(document.text(0), "a, two and three.")

    def test_not_links(self) -> None:
        """Not links."""
        for text in ("[a]", "[a] (b)", "[a](b c d)", "[x] done", "[", "]", "[a](b"):
            with self.subTest(text=text):
                self.assertEqual(kinds_of(text), [(text, TEXT)])


class BlockTests(unittest.TestCase):
    """What a page is made of."""

    def test_headings(self) -> None:
        """Headings."""
        blocks = parse("# One\n## Two ##\n###### Six\nSeven\n=====\nEight\n---\n")
        levels = [block.level for block in blocks if isinstance(block, Heading)]
        self.assertEqual(levels, [1, 2, 6, 1, 2])
        self.assertEqual(title_of(blocks), "One")

    def test_not_headings(self) -> None:
        """Not headings."""
        self.assertIsInstance(parse("#nospace")[0], Paragraph)
        self.assertIsInstance(parse("####### seven")[0], Paragraph)

    def test_slugs(self) -> None:
        """Slugs."""
        blocks = parse("# Saving a File!\n# Saving a file\n# `code` *here*\n")
        slugs = [block.slug for block in blocks if isinstance(block, Heading)]
        self.assertEqual(slugs, ["saving-a-file", "saving-a-file-1", "code-here"])

    def test_rules(self) -> None:
        """Rules."""
        for text in ("---", "***", "___", "- - -", " * * *"):
            with self.subTest(text=text):
                self.assertIsInstance(parse(text)[0], Rule)

    def test_fenced_code(self) -> None:
        """Fenced code."""
        blocks = parse("```python\n# not a heading\n\n**not bold**\n```\nAfter")
        self.assertEqual(blocks[0], CodeBlock(["# not a heading", "", "**not bold**"]))
        self.assertIsInstance(blocks[1], Paragraph)
        self.assertEqual(parse("~~~\na\n"), [CodeBlock(["a"])])  # never closed

    def test_indented_code(self) -> None:
        """Indented code."""
        self.assertEqual(parse("    a\n\n      b\n"), [CodeBlock(["a", "", "  b"])])

    def test_lists(self) -> None:
        """Lists."""
        bullets = parse("- a\n- b\n* c\n")[0]
        assert isinstance(bullets, ListBlock)
        self.assertFalse(bullets.ordered)
        self.assertEqual(len(bullets.items), 3)
        numbers = parse("3. a\n4) b\n")[0]
        assert isinstance(numbers, ListBlock)
        self.assertTrue(numbers.ordered)
        self.assertEqual(numbers.start, 3)

    def test_a_list_kinds_change(self) -> None:
        """A list kinds change."""
        self.assertEqual(len(parse("- a\n1. b\n")), 2)

    def test_a_number_does_not_interrupt_a_paragraph(self) -> None:
        """A number does not interrupt a paragraph."""
        self.assertEqual(shown("In\n1984. Then\n\n"), ["In 1984. Then"])

    def test_quotes(self) -> None:
        """Quotes."""
        block = parse("> a\n> > b\n")[0]
        assert isinstance(block, Quote)
        self.assertIsInstance(block.blocks[1], Quote)

    def test_tables(self) -> None:
        """Tables."""
        block = parse("| A | B | C |\n|:--|:-:|--:|\n| 1 | 2 |\n| x | y | z | w |\n")[0]
        assert isinstance(block, Table)
        self.assertEqual(block.aligns, ["left", "centre", "right"])
        self.assertEqual([len(row) for row in block.rows], [3, 3])

    def test_a_pipe_can_be_escaped(self) -> None:
        """A pipe can be escaped."""
        block = parse("| A |\n|---|\n| a\\|b |\n")[0]
        assert isinstance(block, Table)
        self.assertEqual(block.rows[0][0][0].text, "a|b")

    def test_not_tables(self) -> None:
        """Not tables."""
        self.assertIsInstance(parse("a | b\nc | d\n")[0], Paragraph)
        self.assertIsInstance(parse("a | b\n---\n")[0], Heading)

    def test_comments_are_left_out(self) -> None:
        """Comments are left out."""
        self.assertEqual(shown("<!-- one\ntwo -->\nThree"), ["Three"])

    def test_sections(self) -> None:
        """Sections."""
        found = sections(parse("Intro\n\n# One\n\nText\n\n- item\n\n# Two\n"))
        self.assertEqual(
            [(part.title, part.slug, part.text) for part in found],
            [("", "", "Intro"), ("One", "one", "Text\nitem"), ("Two", "two", "")],
        )


class LayoutTests(unittest.TestCase):
    """Pages at a width."""

    def test_wrapping(self) -> None:
        """Wrapping."""
        self.assertEqual(
            shown("the quick brown fox jumps", 10),
            ["the quick", "brown fox", "jumps"],
        )

    def test_a_long_word_is_broken(self) -> None:
        """A long word is broken."""
        self.assertEqual(shown("abcdefghij", 4), ["abcd", "efgh", "ij"])

    def test_kinds_stay_when_wrapped(self) -> None:
        """Kinds stay when wrapped."""
        document = laid("aaa **bbb ccc** ddd", 7)
        kinds = [[span.kind for span in line] for line in document.lines]
        self.assertEqual(kinds, [[TEXT, BOLD], [BOLD, TEXT]])

    def test_punctuation_stays_with_its_word(self) -> None:
        """Punctuation stays with its word."""
        self.assertEqual(shown("aaaa **bbb**, c", 8), ["aaaa", "bbb, c"])

    def test_blocks_are_apart(self) -> None:
        """Blocks are apart."""
        self.assertEqual(shown("a\n\nb"), ["a", "", "b"])

    def test_headings_are_decorated(self) -> None:
        """Headings are decorated."""
        double = "\N{BOX DRAWINGS DOUBLE HORIZONTAL}" * 3
        line = "\N{BOX DRAWINGS LIGHT HORIZONTAL}"
        self.assertEqual(shown("# One"), [f"{double} One {double}"])
        self.assertEqual(shown("## Two"), ["Two", line * 3])
        self.assertEqual(shown("### Six"), [f"{line * 2} Six"])
        self.assertEqual(shown("#### Four"), ["Four"])

    def test_headings_are_of_their_kind(self) -> None:
        """Headings are of their kind."""
        document = laid("# One **two**")
        self.assertEqual({span.kind for span in document.lines[0]}, {HEADING})

    def test_a_link_in_a_heading_still_goes_there(self) -> None:
        """A link in a heading still goes there."""
        self.assertEqual(laid("## [One](a.md)").links[0].target, "a.md")

    def test_lists(self) -> None:
        """Lists."""
        bullet, circle = "\N{BULLET}", "\N{WHITE CIRCLE}"
        self.assertEqual(
            shown("- one\n- two\n  - three\n- four"),
            [f"{bullet} one", f"{bullet} two", f"  {circle} three", f"{bullet} four"],
        )

    def test_list_lines_wrap_under_their_text(self) -> None:
        """List lines wrap under their text."""
        self.assertEqual(shown("1. aaa bbb ccc", 10), ["1. aaa bbb", "   ccc"])

    def test_numbers_start_where_asked(self) -> None:
        """Numbers start where asked."""
        self.assertEqual(shown("3. a\n4. b"), ["3. a", "4. b"])

    def test_numbers_line_up(self) -> None:
        """Numbers line up."""
        lines = shown("9. a\n10. b")
        self.assertEqual(lines, ["9.  a", "10. b"])

    def test_items_of_several_paragraphs(self) -> None:
        """Items of several paragraphs."""
        self.assertEqual(
            shown("- a\n\n  b\n- c"), ["\N{BULLET} a", "  ", "  b", "\N{BULLET} c"]
        )

    def test_a_list_nested_under_a_number_by_two_spaces(self) -> None:
        """A list nested under a number by two spaces."""
        self.assertEqual(
            shown("1. a\n  - b\n2. c"), ["1. a", "   \N{WHITE CIRCLE} b", "2. c"]
        )

    def test_paragraph_runs_on_lazily_in_a_list(self) -> None:
        """Paragraph runs on lazily in a list."""
        self.assertEqual(shown("- a\nb"), ["\N{BULLET} a b"])

    def test_quotes(self) -> None:
        """Quotes."""
        line = "\N{BOX DRAWINGS LIGHT VERTICAL} "
        self.assertEqual(shown("> aaa\nbbb"), [f"{line}aaa bbb"])
        self.assertEqual(shown("> a\n>\n> b"), [f"{line}a", line, f"{line}b"])

    def test_rules_are_as_wide_as_the_page(self) -> None:
        """Rules are as wide as the page."""
        self.assertEqual(shown("---", 5), ["\N{BOX DRAWINGS LIGHT HORIZONTAL}" * 5])

    def test_code_is_kept_and_filled(self) -> None:
        """Code is kept and filled."""
        self.assertEqual(shown("```\n  a\n```", 6), ["   a  "])

    def test_long_code_is_broken_not_lost(self) -> None:
        """Long code is broken not lost."""
        self.assertEqual(shown("```\nabcdefg\n```", 6), [" abcd ", " efg  "])

    def test_tables(self) -> None:
        """Tables."""
        line = "\N{BOX DRAWINGS LIGHT HORIZONTAL}" * 3
        upright = "\N{BOX DRAWINGS LIGHT VERTICAL}"
        self.assertEqual(
            shown("| A | B |\n|---|--:|\n| x | 1 |\n"),
            [
                f"\N{BOX DRAWINGS LIGHT DOWN AND RIGHT}{line}"
                f"\N{BOX DRAWINGS LIGHT DOWN AND HORIZONTAL}{line}"
                "\N{BOX DRAWINGS LIGHT DOWN AND LEFT}",
                f"{upright} A {upright} B {upright}",
                f"\N{BOX DRAWINGS LIGHT VERTICAL AND RIGHT}{line}"
                f"\N{BOX DRAWINGS LIGHT VERTICAL AND HORIZONTAL}{line}"
                "\N{BOX DRAWINGS LIGHT VERTICAL AND LEFT}",
                f"{upright} x {upright} 1 {upright}",
                f"\N{BOX DRAWINGS LIGHT UP AND RIGHT}{line}"
                f"\N{BOX DRAWINGS LIGHT UP AND HORIZONTAL}{line}"
                "\N{BOX DRAWINGS LIGHT UP AND LEFT}",
            ],
        )

    def test_table_headings_are_bold(self) -> None:
        """Table headings are bold."""
        document = laid("| A |\n|---|\n")
        self.assertIn(BOLD, {span.kind for span in document.lines[1]})

    def test_tables_wrap_to_fit(self) -> None:
        """Tables wrap to fit."""
        lines = shown(
            "| Key | Words |\n|---|---|\n| F1 | one two three four five |\n", 20
        )
        self.assertTrue(all(len(line) == 20 for line in lines), lines)
        joined = " ".join(lines)
        for word in ("one", "two", "three", "four", "five"):
            self.assertIn(word, joined)

    def test_alignment_in_tables(self) -> None:
        """Alignment in tables."""
        lines = shown("| Heading |\n|:---:|\n| x |\n")
        self.assertIn("    x    ", lines[3])
        lines = shown("| Heading |\n|---:|\n| x |\n")
        self.assertIn("       x", lines[3])

    def test_a_table_too_wide_is_written_out(self) -> None:
        """A table too wide is written out."""
        heads = " | ".join(f"H{number}" for number in range(10))
        cells = " | ".join(f"c{number}" for number in range(10))
        lines = shown(f"| {heads} |\n{'|---' * 10}|\n| {cells} |\n", 20)
        self.assertIn("H0: c0", lines)
        self.assertIn("H9: c9", lines)

    def test_links_are_found(self) -> None:
        """Links are found."""
        document = laid("aa [bb cc](x.md) dd\n\n[ee](y.md)", 6)
        self.assertEqual([link.target for link in document.links], ["x.md", "y.md"])
        first = document.links[0]
        self.assertEqual(first.places, [(0, 3, 2), (1, 0, 2)])
        self.assertEqual((first.row, first.last_row), (0, 1))
        self.assertEqual(document.link_at(0, 4), 0)
        self.assertEqual(document.link_at(1, 1), 0)
        self.assertIsNone(document.link_at(0, 0))
        self.assertIsNone(document.link_at(1, 2))
        self.assertEqual(document.link_at(document.links[1].row, 0), 1)

    def test_a_link_in_a_list_is_placed_after_its_bullet(self) -> None:
        """A link in a list is placed after its bullet."""
        self.assertEqual(laid("- [a](b.md)").links[0].places, [(0, 2, 1)])

    def test_anchors_are_rows(self) -> None:
        """Anchors are rows."""
        document = laid("# One\n\ntext\n\n- item\n\n## Two\n\n> ### Three\n", 30)
        self.assertEqual(document.anchors["one"], 0)
        self.assertEqual(document.text(document.anchors["two"]), "Two")
        self.assertIn("Three", document.text(document.anchors["three"]))

    def test_any_width_will_do(self) -> None:
        """Any width will do."""
        page = (
            "# Heading\n\n## Heading\n\n### Heading\n\ntext **bold** [link](a)\n\n"
            "1. a\n   - b\n\n> c\n\n```\ncode\n```\n\n"
            "| a | b |\n|---|---|\n| c | d |\n\n---\n"
        )
        for width in (-1, 0, 1, 2, 3, 5, 9, 13, 80):
            with self.subTest(width=width):
                self.assertTrue(laid(page, width).lines)

    def test_nothing_at_all(self) -> None:
        """Nothing at all."""
        self.assertEqual(lay_out(parse(""), 40).lines, [])
        self.assertEqual(lay_out(parse("\n\n  \n"), 40).lines, [])


class HostileTests(unittest.TestCase):
    """Hostile pages never raise or hang."""

    def test_hostile_pages(self) -> None:
        """Hostile pages."""
        for name, text in (
            ("stars", "*a " * 20000),
            ("brackets", "[" * 100000),
            ("closed brackets", "[" * 5000 + "]" * 5000),
            ("ticks", "` `` " * 20000),
            ("quotes", "> " * 20000 + "x"),
            ("lists", "\n".join(" " * n + "- x" for n in range(500))),
            ("spaces after a hash", "# " + " " * 100000),
            ("a link's spaces", "[x](" + " " * 100000),
            ("angle brackets", "<a" * 50000),
            ("pipes", "|" * 5000 + "\n" + "|-" * 2000),
            ("nested links", "[a](" * 5000),
            ("nested emphasis", "*a **b " * 5000),
            ("control characters", "\x1b[2J\x07\x00\x7f\x9b"),
            ("surrogates", "\udcff\ud800"),
            ("an unclosed comment", "<!-- " * 1000),
        ):
            with self.subTest(name=name):
                self.assertIsInstance(laid(text), Document)

    def test_control_characters_are_only_text(self) -> None:
        """The canvas keeps them from the terminal, as it does all text."""
        self.assertEqual(shown("a\x1bb"), ["a\x1bb"])
