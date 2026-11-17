"""Tables for the guides, built from Dasha Framework's own code at build time, so
they are always the colours and keys Dasha Framework really has:

``colour-roles``
    Every colour role (``dasha.theme.ROLES``): its default and
    monochrome styles, and what it colours.

``shortcut-actions``
    Every action (``dasha.shortcuts.DEFAULTS``): its default keys, and
    what it does.

In a Markdown guide::

    ```{colour-roles}
    ```
"""

from collections.abc import Sequence

from docutils import nodes
from docutils.nodes import Node
from sphinx.application import Sphinx
from sphinx.util.docutils import SphinxDirective

from dasha import shortcuts, theme
from dasha.style import Style

_COLOUR_NAMES = {number: name for name, number in theme.COLOUR_NAMES.items()}

# A cell is plain text, or text in code font.
type Cell = str | tuple[str, ...]


def colour_name(colour: int | None) -> str:
    """``"bright white"``, ``"colour 208"``; ``None`` is the window's own
    colour, which is what a role with no colour of its own draws in."""
    if colour is None:
        return "the window's"
    return _COLOUR_NAMES.get(colour, f"colour {colour}")


def describe(style: object, *, colours: bool = True) -> str:
    """A style in words, as the colours guide writes it: ``"bright white
    on blue, bold"``, ``"white on the window's"``, ``"plain"``. With
    ``colours`` false (the monochrome theme, which has none), only its
    attributes are given."""
    if style is None:
        return "none"
    if not isinstance(style, Style):
        return str(style)
    parts = []
    if colours:
        if style.foreground is None and style.background is None:
            parts.append("the window's")
        else:
            parts.append(
                f"{colour_name(style.foreground)} on {colour_name(style.background)}"
            )
    parts += [
        name
        for name, on in (
            ("bold", style.bold),
            ("reverse", style.reverse),
            ("underline", style.underline),
        )
        if on
    ]
    return ", ".join(parts) or "plain"


def table(headings: Sequence[str], rows: Sequence[Sequence[Cell]]) -> nodes.table:
    """A docutils table; a cell given as a tuple is a list of code names."""
    group = nodes.tgroup(cols=len(headings))
    group += [nodes.colspec(colwidth=1) for _ in headings]
    head = nodes.thead()
    head += _row(headings)
    body = nodes.tbody()
    body += [_row(cells) for cells in rows]
    group += [head, body]
    result = nodes.table(classes=["dasha-table"])
    result += group
    return result


def _row(cells: Sequence[Cell]) -> nodes.row:
    row = nodes.row()
    for cell in cells:
        paragraph = nodes.paragraph()
        if isinstance(cell, tuple):
            for index, name in enumerate(cell):
                if index:
                    paragraph += nodes.Text(", ")
                paragraph += nodes.literal(text=name)
        else:
            paragraph += nodes.Text(cell)
        entry = nodes.entry()
        entry += paragraph
        row += entry
    return row


class ColourRoles(SphinxDirective):
    """Every colour role, in the order ``dasha.theme`` lists them."""

    def run(self) -> list[Node]:
        rows: list[Sequence[Cell]] = []
        for role in theme.ROLES:
            rows.append(
                (
                    (role,),
                    describe(theme.DEFAULT_THEME[role]),
                    describe(theme.DARK_THEME[role]),
                    describe(theme.MONOCHROME_THEME[role], colours=False),
                    theme.DESCRIPTIONS[role],
                )
            )
        headings = ("Role", "Default", "Dark", "Monochrome", "What it colours")
        return [table(headings, rows)]


class ShortcutActions(SphinxDirective):
    """Every action, in the order ``dasha.shortcuts`` lists them."""

    def run(self) -> list[Node]:
        rows: list[Sequence[Cell]] = [
            ((action,), keys or "(none)", shortcuts.DESCRIPTIONS[action])
            for action, keys in shortcuts.DEFAULTS.items()
        ]
        return [table(("Action", "Default keys", "What it does"), rows)]


def setup(app: Sphinx) -> dict[str, object]:
    """Register the directives."""
    app.add_directive("colour-roles", ColourRoles)
    app.add_directive("shortcut-actions", ShortcutActions)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
