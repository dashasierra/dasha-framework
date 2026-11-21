"""Radio button groups."""

from collections.abc import Sequence
from typing import Unpack

from dasha.menu import split_mnemonic
from dasha.widgets.cluster import Cluster, ClusterOptions


class RadioButtons(Cluster):
    """A group of options, one of which is selected.

    :param labels: Option labels; ``&`` marks mnemonics.
    :param row: Row in the window.
    :param column: Column in the window.
    :param selected: Index of the selected option.
    :param options: Further cluster options.
    """

    marks = ("( )", "(\N{BULLET})")
    """Unselected and selected marks."""

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
