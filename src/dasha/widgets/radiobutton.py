"""Radio buttons: a group of options, exactly one of which is
selected."""

from collections.abc import Sequence
from typing import Unpack

from dasha.menu import split_mnemonic
from dasha.widgets.cluster import Cluster, ClusterOptions


class RadioButtons(Cluster):
    """A group of options of which exactly one is selected::

        RadioButtons(["&Small", "&Medium", "&Large"], 1, 2, selected=1)

    Moving with Up and Down selects each option in turn, and so does a
    click or an option's letter. The group's ``value`` is the index of the
    selected option (``selected``), and ``selected_label`` is that option's
    label without its ``&``.
    """

    marks = ("( )", "(\N{BULLET})")
    """How an option looks when not selected and when selected; ``•`` is
    code page 437 glyph 7."""

    def __init__(
        self,
        labels: Sequence[str],
        row: int,
        column: int,
        *,
        selected: int = 0,
        **options: Unpack[ClusterOptions],
    ) -> None:
        super().__init__(labels, row, column, **options)
        if not 0 <= selected < len(self.labels):
            raise ValueError("selected must be the index of an option")
        self.selected = selected
        if self.is_enabled(selected):
            self.current = selected

    @property
    def value(self) -> int:
        return self.selected

    @property
    def selected_label(self) -> str:
        """The selected option's label, without ``&``."""
        return split_mnemonic(self.labels[self.selected])[0]

    def is_marked(self, index: int) -> bool:
        return index == self.selected

    def press(self, index: int) -> None:
        if index != self.selected:
            self.selected = index
            self._changed()

    def move_to(self, index: int) -> None:
        self.current = index
        self.press(index)
