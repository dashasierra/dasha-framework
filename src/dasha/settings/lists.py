"""List behaviour in Settings."""

from dasha.widgets import ListBox


def stay_open(box: ListBox) -> None:
    """Choose without pressing the default button.

    :param box: The list box.
    """
    del box
