"""Tests for containers of mixed kinds nested in each other: what shows,
and where things go."""

import unittest

from dasha.canvas import Rect
from dasha.shortcuts import Shortcuts
from dasha.widgets import Collapsible, Container, GroupBox, Label, TextBox, Widget
from dasha.window import Window


class Bare(Container):
    """A container that is not a widget, anchored to one (as a tab page
    is), showing its widgets or not as it is told."""

    def __init__(self, owner: Widget) -> None:
        super().__init__()
        self.owner = owner
        self.showing = True

    @property
    def anchor(self) -> Widget:
        return self.owner

    @property
    def is_showing_children(self) -> bool:
        return self.showing

    def content_origin(self) -> tuple[int, int]:
        return self.home_row + 1, self.owner.rect.column + 1


class NestingTests(unittest.TestCase):
    """A collapsible area holding a group box, and a group box holding an
    area, then a label below both."""

    def setUp(self) -> None:
        self.window = Window("W", Rect(0, 0, 20, 50))
        self.area = self.window.add(Collapsible("&Area", 0, 0))
        self.group = self.area.add(GroupBox("&Group", 0, 2, 30, 4))
        self.inside = self.group.add(TextBox(0, 1, 10, name="inside"))
        self.inner = self.group.add(Collapsible("&Inner", 1, 1))
        self.deep = self.inner.add(Label("deep", 0, 2))
        self.below = self.window.add(Label("below", 1, 0))

    def test_placed_through_each(self) -> None:
        """Relative to each container's content, in window rows."""
        self.assertEqual((self.group.rect.row, self.group.rect.column), (1, 2))
        self.assertEqual((self.inside.rect.row, self.inside.rect.column), (2, 4))
        self.assertEqual((self.inner.rect.row, self.deep.rect.row), (3, 4))

    def test_shown_through_each(self) -> None:
        """Collapsed, nothing inside shows; expanded, the group and what is
        directly in it; the inner area's widgets only once it is open too."""
        hidden = (self.group, self.inside, self.inner, self.deep)
        self.assertFalse(any(widget.is_shown for widget in hidden))
        self.area.expand()
        self.assertTrue(
            self.group.is_shown and self.inside.is_shown and self.inner.is_shown
        )
        self.assertFalse(self.deep.is_shown)
        self.inner.expand()
        self.assertTrue(self.deep.is_shown)

    def test_the_group_moves_with_the_area(self) -> None:
        """Expanding moves what is below by the group's height; the inner
        area's opening, inside the group's frame, does not."""
        self.area.expand()
        self.assertEqual(self.below.rect.row, 5)  # header, then a 4-row group
        self.inner.expand()
        self.assertEqual(self.below.rect.row, 5)
        self.area.collapse()
        self.assertEqual(self.below.rect.row, 1)

    def test_a_container_that_is_not_a_widget(self) -> None:
        """Anchored to a widget: moves with it, shows with it."""
        window = Window("W", Rect(0, 0, 20, 50))
        area = window.add(Collapsible("Area", 0, 0, expanded=True))
        owner = area.add(Label("owner", 0, 0))
        bare = Bare(owner)
        held = bare.add(Label("held", 0, 0))
        self.assertEqual(held.rect.row, 2)  # under the owner, on row 1
        self.assertTrue(held.is_shown)
        bare.showing = False
        self.assertFalse(held.is_shown)
        bare.showing = True
        area.collapse()
        self.assertFalse(held.is_shown)

    def test_needs_a_window(self) -> None:
        """A container must be in a window before its widgets go in."""
        with self.assertRaisesRegex(ValueError, "group box"):
            GroupBox("G", 0, 0, 10, 4).add(Label("x", 0, 0))

    def test_hidden_widgets_take_no_keys(self) -> None:
        """Tab goes past them."""
        self.window.focus(self.area)
        self.window.handle_key("tab", Shortcuts())
        self.assertIs(self.window.focused, self.area)  # nothing else to go to


if __name__ == "__main__":
    unittest.main()
