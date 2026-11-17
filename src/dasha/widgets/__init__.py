"""Widgets: the controls inside windows and dialogs.

Each kind of widget has a module of its own, and every widget can be
imported from here::

    from dasha.widgets import Button, CheckBoxes, Label, TextBox

A widget is positioned relative to its window's interior, so row 0,
column 0 is the first cell inside the frame. To create a new kind of
control, subclass ``Widget`` (in ``dasha.widgets.base``).
"""

from dasha.widgets.autocomplete import AutoCompleteBox, match_suggestions
from dasha.widgets.base import Grow, Widget
from dasha.widgets.button import (
    OUTLINE_BOTTOM_LEFT,
    OUTLINE_BOTTOM_RIGHT,
    OUTLINE_HORIZONTAL,
    OUTLINE_TOP_RIGHT,
    SHADOW_BELOW,
    SHADOW_RIGHT,
    SHADOW_SHAPES,
    Button,
)
from dasha.widgets.checkbox import CheckBoxes
from dasha.widgets.cluster import Cluster
from dasha.widgets.collapsible import Collapsible
from dasha.widgets.combobox import ComboBox
from dasha.widgets.container import Container
from dasha.widgets.groupbox import GroupBox
from dasha.widgets.label import Label
from dasha.widgets.listbox import ListBox
from dasha.widgets.paragraph import Paragraph
from dasha.widgets.password import PasswordBox
from dasha.widgets.progressbar import ColumnBar, ProgressBar
from dasha.widgets.radiobutton import RadioButtons
from dasha.widgets.scrollbar import ScrollBar
from dasha.widgets.slider import Slider
from dasha.widgets.splitter import SplitPane, Splitter
from dasha.widgets.spinbox import SpinBox
from dasha.widgets.switch import Switch
from dasha.widgets.table import Column, Table
from dasha.widgets.tabs import TabPage, Tabs
from dasha.widgets.terminalview import TerminalView
from dasha.widgets.textarea import TextArea
from dasha.widgets.textbox import TextBox
from dasha.widgets.tree import TreeNode, TreeView

__all__ = [
    "OUTLINE_BOTTOM_LEFT",
    "OUTLINE_BOTTOM_RIGHT",
    "OUTLINE_HORIZONTAL",
    "OUTLINE_TOP_RIGHT",
    "SHADOW_BELOW",
    "SHADOW_RIGHT",
    "SHADOW_SHAPES",
    "AutoCompleteBox",
    "Button",
    "CheckBoxes",
    "Cluster",
    "Collapsible",
    "Column",
    "ColumnBar",
    "ComboBox",
    "Container",
    "GroupBox",
    "Grow",
    "Label",
    "ListBox",
    "Paragraph",
    "PasswordBox",
    "ProgressBar",
    "RadioButtons",
    "ScrollBar",
    "Slider",
    "SpinBox",
    "SplitPane",
    "Splitter",
    "Switch",
    "TabPage",
    "Table",
    "Tabs",
    "TerminalView",
    "TextArea",
    "TextBox",
    "TreeNode",
    "TreeView",
    "Widget",
    "match_suggestions",
]
