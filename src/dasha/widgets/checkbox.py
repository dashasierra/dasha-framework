"""Check boxes: a group of options, any number of which can be
checked."""

from collections.abc import Iterable, Sequence
from typing import Unpack

from dasha.menu import split_mnemonic
from dasha.widgets.cluster import Cluster, ClusterOptions


class CheckBoxes(Cluster):
    """A group of options that can each be on or off, with any number on at
    once::

        CheckBoxes(["&Bold", "&Italic", "&Underline"], 1, 2, checked=[0])

    Space (or a click, or the option's letter) checks or unchecks an
    option. The group's ``value`` is a tuple of the indexes of the checked
    options; ``checked`` is a list of ``True`` or ``False`` values, one for
    each option; and ``checked_labels`` holds the checked options' labels
    without their ``&``.
    """

    def __init__(
        self,
        labels: Sequence[str],
        row: int,
        column: int,
        *,
        checked: Iterable[int] = (),
        **options: Unpack[ClusterOptions],
    ) -> None:
        super().__init__(labels, row, column, **options)
        self.checked = [False] * len(self.labels)
        for index in checked:
            self.checked[index] = True

    @property
    def value(self) -> tuple[int, ...]:
        return tuple(index for index, on in enumerate(self.checked) if on)

    @property
    def checked_labels(self) -> list[str]:
        """The labels (without ``&``) of the checked options."""
        return [split_mnemonic(self.labels[index])[0] for index in self.value]

    def is_marked(self, index: int) -> bool:
        return self.checked[index]

    def press(self, index: int) -> None:
        self.checked[index] = not self.checked[index]
        self._changed()
