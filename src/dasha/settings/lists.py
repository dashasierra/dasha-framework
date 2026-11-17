"""What the lists in Settings... do when an item is chosen."""

from dasha.widgets import ListBox


def stay_open(box: ListBox) -> None:
    """Choosing an item (a double-click on it) does nothing more than
    highlight or select it. Without this, a list box chooses by pressing
    its window's default button, which in Settings... is OK, and so a
    double-click would save the settings and close the dialog."""
    del box
