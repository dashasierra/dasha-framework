"""Collapsible areas: a header that shows or hides the widgets below it,
moving everything further down out of the way."""

from collections.abc import Callable

from dasha.canvas import Canvas, Rect
from dasha.events import MouseEvent
from dasha.menu import mnemonic_key, split_mnemonic
from dasha.scrollbar import DOWN, RIGHT
from dasha.shortcuts import Shortcuts
from dasha.style import BRIGHT_BLACK, BRIGHT_WHITE, BRIGHT_YELLOW, Style
from dasha.widgets.base import Widget, run_shortcut
from dasha.widgets.container import Container
from dasha.widgets.label import on_window, paint_mnemonic_label


class Collapsible(Container, Widget):
    """A ``Collapsible`` is a header above an area of widgets that are shown
    only while it is expanded: ``► Label`` when collapsed, and ``▼ Label`` when
    expanded (code page 437 glyphs 16 and 31). The area can hold widgets of any
    kind, including other collapsible areas.

    ::

        ► Advanced               ▼ Advanced
        Name: [          ]          [X] Verbose
                                    Retries: [3   ]
                                 Name: [          ]

    ::

        advanced = dialog.add(widget=Collapsible(label="&Advanced", row=4, column=2))
        advanced.add(
            widget=CheckBoxes(labels=["&Verbose"], row=0, column=2, name="verbose")
        )
        advanced.add(widget=Label(text="Retries:", row=1, column=2))
        advanced.add(widget=TextBox(row=1, column=11, width=6, name="retries"))
        # Just under the header, as though the area were collapsed:
        dialog.add(widget=Label(text="Name:", row=5, column=2))

    - **Placing widgets in it.** ``area.add(widget)`` places a widget relative
      to the area: row 0 is the first row below the header, and column 0 is the
      header's column. The area must already be in a window. Its widgets are still
      ordinary widgets of the window (``children`` lists them), so Tab,
      mnemonics, ``window.widget(name)`` and ``dialog.values`` all find them.
    - **Moving the rest.** Expanding the area moves every widget that starts below
      its header row down by the area's height (how far its widgets reach below
      the header), whatever its column, so that nothing is covered. Collapsing it
      moves them back exactly. Widgets beside the header, on the same row, stay
      where they are.
    - **Laying out a window.** A window is laid out as though every area were
      collapsed, so put the widgets that come after an area just below its header
      row. An area that is (or starts) expanded moves them down itself, including
      widgets added after it. Only the rows that the areas add are changed
      (``Widget.area_shift``), so a widget moved by code, or grown with its
      window, keeps its position.
    - **Hidden widgets.** While an area is collapsed, its widgets are not drawn,
      cannot receive the focus, clicks or their mnemonics, and have no timers, but
      they keep their values. ``widget.is_shown`` says whether a widget is shown, and
      ``window.shown_widgets`` lists those that are. Collapsing an area while the
      focus is inside it moves the focus to the area's header.
    - **Nesting.** An area inside an expanded area counts towards the outer
      area's height while it is expanded: expanding the inner area moves the outer
      area's later widgets, and everything below the outer area. Collapsing the
      outer area hides both.
    - **Room.** The window keeps its size. When its widgets no longer fit, scroll
      bars appear on its frame, as for any content larger than the window.

    - Space or Enter (``collapsible_toggle``): expand or collapse the area
    - Right / Left (``collapsible_expand`` / ``collapsible_collapse``): expand /
      collapse it
    - A click on the header, or the header's letter: expand or collapse it

    ``value`` (and ``expanded``) is whether the area is expanded. ``expand()``,
    ``collapse()``, ``toggle()`` and ``set(expanded)`` change it as the user does,
    and ``on_change(area)`` is called for every change the user makes; setting
    ``expanded`` from code moves the widgets too, but notifies no one. The label
    is dark grey (``collapsible.label``), or bright white while the area has the
    focus (``collapsible.focused``), with its mnemonic letter in yellow either
    way (``collapsible.mnemonic``; underlined in the monochrome theme), all on the
    window's background. The arrow uses ``collapsible.arrow``, whose colours, left
    as ``default``, are the window's.
    """

    focusable = True
    noun = "collapsible area"
    opens_below = True
    arrow_style: Style = Style(bold=True)
    """The style of the ``►`` or ``▼``. A colour it leaves as ``None``
    takes the window's colour, so by default the arrow is in the window's text
    colour, in bold."""
    label_style: Style = Style(foreground=BRIGHT_BLACK)
    """The style of the label: dark grey on the window's background
    (``None``), so that it can be read on both a window's blue and a dialog's
    grey."""
    focused_style: Style = Style(foreground=BRIGHT_WHITE)
    """The style of the label while the area has the focus: white on the
    window's background. Its letter stays in ``mnemonic_style``."""
    mnemonic_style: Style = Style(foreground=BRIGHT_YELLOW)
    """The style of the label's mnemonic letter: yellow on the window's
    background. The monochrome theme underlines it instead."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        label: str,
        row: int,
        column: int,
        width: int | None = None,
        *,
        expanded: bool = False,
        on_change: Callable[["Collapsible"], object] | None = None,
        name: str | None = None,
        status: str = "",
    ) -> None:
        text = split_mnemonic(label)[0]
        width = width if width is not None else 2 + len(text)
        Widget.__init__(self, row, column, max(width, 1), name=name, status=status)
        Container.__init__(self)
        self.label = label
        self._expanded = expanded
        self.on_change = on_change

    # Its state

    @property
    def value(self) -> bool:
        return self._expanded

    @property
    def expanded(self) -> bool:
        """Whether the area is expanded. Setting this from code moves the
        widgets below as well, but does not call ``on_change``."""
        return self._expanded

    @expanded.setter
    def expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        window = self.window
        if window is None:
            return
        window.lay_out()
        focused = window.focused
        if focused is not None and not focused.is_shown and self.is_shown:
            window.focus(self)  # the focus was hidden in the area

    def set(self, expanded: bool) -> None:
        """Expand or collapse the area as the user does, calling
        ``on_change`` if it changed."""
        if expanded != self._expanded:
            self.expanded = expanded
            if self.on_change is not None:
                self.on_change(self)

    def expand(self) -> None:
        """Show the area."""
        self.set(True)

    def collapse(self) -> None:
        """Hide the area."""
        self.set(False)

    def toggle(self) -> None:
        """Expand the area if it is collapsed, or collapse it if it is
        expanded."""
        self.set(not self._expanded)

    # Its widgets (``add`` puts one in: row 0 is the first row under the
    # header, column 0 the header's column)

    @property
    def anchor(self) -> Widget:
        return self

    @property
    def is_showing_children(self) -> bool:
        return self._expanded

    def content_origin(self) -> tuple[int, int]:
        return self.home_row + 1, self.rect.column

    # Drawing and input

    def mnemonic(self) -> str | None:
        return mnemonic_key(self.label)

    def activate(self) -> None:
        self.toggle()

    def paint(self, canvas: Canvas, origin: Rect, focused: bool) -> None:
        row = origin.row + self.rect.row
        column = origin.column + self.rect.column
        body = self.window.body_style if self.window is not None else Style()
        arrow = on_window(self.arrow_style, body)
        canvas.write(row, column, DOWN if self._expanded else RIGHT, arrow, clip=origin)
        label = on_window(self.focused_style if focused else self.label_style, body)
        letter = on_window(self.mnemonic_style, body)  # the same, focused or not
        paint_mnemonic_label(
            canvas,
            origin,
            (row, column + 2),
            self.label,
            label,
            width=self.rect.width - 2,
            letter_style=letter,
        )

    def handle_key(self, key: str, shortcuts: Shortcuts) -> bool:
        """Space or Enter toggles the area, Right expands it, and Left
        collapses it."""
        actions: dict[str, Callable[[], object]] = {
            "collapsible_toggle": self.toggle,
            "collapsible_expand": self.expand,
            "collapsible_collapse": self.collapse,
        }
        return run_shortcut(shortcuts, key, actions)

    def handle_mouse(self, event: MouseEvent, row: int, column: int) -> bool:
        """A press on the header toggles the area. The drag and release that
        follow are used up too, so that nothing under the header receives
        them."""
        del row, column
        left = event.button == "left"
        if left and event.action == "press":
            self.toggle()
        return left and event.action in ("press", "drag", "release")
