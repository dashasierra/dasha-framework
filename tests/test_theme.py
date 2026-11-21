"""Tests for the cosmetic changes and colour themes."""

import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from dasha import theme
from dasha.__main__ import main
from dasha.canvas import SHADOW_BLANKS, Canvas, Rect
from dasha.dialog import Dialog
from dasha.events import MouseEvent
from dasha.manager import PresentationManager
from dasha.menu import Menu, MenuBar, MenuItem
from dasha.statusbar import StatusBar
from dasha.style import BLUE, RED, SHADOW, Rgb, Style, terminal_has_colours
from dasha.widgets import (
    AutoCompleteBox,
    Button,
    CheckBoxes,
    Column,
    ColumnBar,
    ComboBox,
    GroupBox,
    Label,
    ListBox,
    Paragraph,
    PasswordBox,
    ProgressBar,
    RadioButtons,
    Slider,
    SpinBox,
    Splitter,
    Switch,
    Table,
    Tabs,
    TextArea,
    TextBox,
    TreeNode,
    TreeView,
)
from dasha.window import Window


class ThemeIsolation(unittest.TestCase):
    """Restore the theme after each test: themes change class attributes."""

    def setUp(self) -> None:
        saved = theme.current_theme()
        self.addCleanup(theme.apply_theme, saved)


class MenuPaddingTests(unittest.TestCase):
    """Drop-down menus have a blank column outside each side of the frame."""

    def test_padding_is_not_an_item(self) -> None:
        """Clicking the blank side column chooses nothing; inside does."""
        chosen: list[str] = []
        menu_bar = MenuBar()
        menu_bar.set_menus(
            [Menu("&File", [MenuItem("&Open", lambda: chosen.append("o"))])]
        )
        menu_bar.open(0)
        rect = menu_bar.dropdown_rect(40)
        assert rect is not None
        menu_bar.handle_mouse(MouseEvent("press", "left", 2, rect.column), 40)
        menu_bar.handle_mouse(MouseEvent("press", "left", 2, rect.right - 1), 40)
        self.assertEqual(chosen, [])
        self.assertTrue(menu_bar.is_open)
        menu_bar.handle_mouse(MouseEvent("press", "left", 2, rect.column + 2), 40)
        self.assertEqual(chosen, ["o"])


class ShadowBlankingTests(unittest.TestCase):
    """Shadows draw spaces over block characters."""

    def test_blocks_become_spaces(self) -> None:
        """▄▀█▌▐ under a shadow become spaces; other characters stay."""
        canvas = Canvas(12, 3)
        canvas.write(1, 0, "".join(sorted(SHADOW_BLANKS)) + "x\N{LIGHT SHADE}")
        canvas.cast_shadow(Rect(0, -10, 1, 20), SHADOW, width=0, height=1)
        self.assertEqual(canvas.text(1)[:7], "     x\N{LIGHT SHADE}")
        self.assertEqual(canvas.cell(1, 0), (" ", SHADOW))
        self.assertEqual(canvas.cell(1, 5), ("x", SHADOW))

    def test_button_shadow_under_window_shadow(self) -> None:
        """A window's shadow over a button's shadow leaves plain dark spaces."""
        behind = Window("Behind", Rect(1, 0, 8, 30))
        behind.add(Button("OK", 4, 6))  # its shadow row is screen row 6
        front = Window("Front", Rect(1, 0, 5, 12))  # bottom shadow on row 6
        manager = PresentationManager(windows=[behind, front])
        manager.handle_resize(40, 12)
        canvas = Canvas(40, 12)
        manager.compose(canvas)
        self.assertEqual(canvas.cell(6, 8), (" ", SHADOW))


class TitleButtonColourTests(unittest.TestCase):
    """Brackets in the frame's colours, symbols in the button colours."""

    def test_window_and_dialog(self) -> None:
        """[■] and [↓]: the brackets match the frame on windows and dialogs."""
        for window in (
            Window("W", Rect(0, 0, 4, 30), closable=True, minimisable=True),
            Dialog("D", 30, 4),
        ):
            canvas = Canvas(30, 4)
            window.paint(canvas, active=True)
            for action, cells in window.title_buttons:
                self.assertEqual(canvas.cell(0, cells.column)[1], window.frame_style)
                self.assertEqual(canvas.cell(0, cells.right - 1)[1], window.frame_style)
                self.assertEqual(
                    canvas.cell(0, cells.column + 1)[1], window.button_style, action
                )


class ColourParsingTests(unittest.TestCase):
    """Colour values in the colours file."""

    def test_names_numbers_and_default(self) -> None:
        """Names (any case, spaces or underscores), numbers and "default"."""
        self.assertEqual(theme.parse_colour("Bright White"), 15)
        self.assertEqual(theme.parse_colour("bright_blue"), 12)
        self.assertEqual(theme.parse_colour("grey"), 8)
        self.assertEqual(theme.parse_colour(200), 200)
        self.assertIsNone(theme.parse_colour("default"))

    def test_bad_colours(self) -> None:
        """Unknown names, out-of-range numbers and booleans are rejected."""
        for value in ("purple-ish", 256, -1, True, [1]):
            with self.assertRaises(ValueError):
                theme.parse_colour(value)


class ThemeTests(ThemeIsolation):
    """Building, applying and loading themes."""

    def test_default_theme_is_the_classes(self) -> None:
        """The default theme is exactly the colours the classes define."""
        self.assertEqual(theme.DEFAULT_THEME["window.body"], Window.body_style)
        everything = set(theme.ROLES) | set(theme.SETTINGS)
        self.assertEqual(set(theme.DEFAULT_THEME), everything)
        self.assertEqual(set(theme.MONOCHROME_THEME), everything)
        self.assertEqual(set(theme.DESCRIPTIONS), set(theme.ROLES))

    def test_a_base_that_is_not_text(self) -> None:
        """A base that is not text."""
        for base in (["dark"], {"dark": True}, 1, None):
            with self.subTest(base=base):
                with self.assertRaisesRegex(theme.ThemeError, '"base" must be'):
                    theme.build_theme({"base": base})
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "broken.json").write_text('{"base": ["dark"]}', "utf-8")
            manager = PresentationManager()
            manager.themes_folder = Path(folder)
            before = theme.current_theme()
            self.assertFalse(manager.set_theme("broken"))
            self.assertEqual(theme.current_theme(), before)

    def test_button_shadow_setting(self) -> None:
        """Solid by default, outline in monochrome, and settable in the file."""
        self.assertEqual(theme.DEFAULT_THEME["button_shadow"], "solid")
        self.assertEqual(theme.MONOCHROME_THEME["button_shadow"], "outline")
        built = theme.build_theme({"button_shadow": "outline"})
        self.assertEqual(built["button_shadow"], "outline")
        self.assertEqual(built["window.body"], theme.DEFAULT_THEME["window.body"])
        solid_mono = theme.build_theme({"base": "monochrome", "button_shadow": "solid"})
        self.assertEqual(solid_mono["button_shadow"], "solid")
        with self.assertRaisesRegex(theme.ThemeError, "must be one of solid, outline"):
            theme.build_theme({"button_shadow": "dotted"})
        theme.apply_theme(theme.MONOCHROME_THEME)
        self.assertEqual(Button.shadow_shape, "outline")

    def test_outline_shadow_drawing(self) -> None:
        """The outline frames where the shadow falls, in box characters."""
        window = Window("W", Rect(0, 0, 5, 20))
        window.add(Button("OK", 1, 1))  # face at screen row 2, columns 2-11
        Button.shadow_shape = "outline"
        canvas = Canvas(20, 5)
        window.paint(canvas, active=True)
        self.assertEqual(canvas.cell(2, 12)[0], "\N{BOX DRAWINGS LIGHT DOWN AND LEFT}")
        # Starts right under the button's left edge (column 2), ends under ┐.
        self.assertEqual(
            canvas.text(3)[1:14],
            " "
            + "\N{BOX DRAWINGS LIGHT UP AND RIGHT}"
            + "\N{BOX DRAWINGS LIGHT HORIZONTAL}" * 9
            + "\N{BOX DRAWINGS LIGHT UP AND LEFT}"
            + " ",
        )
        for char in set(canvas.text(3)[2:13]) | {canvas.cell(2, 12)[0]}:
            char.encode("cp437")

    def test_apply_sets_class_attributes(self) -> None:
        """Applying a theme changes what every instance draws with."""
        styled = dict(theme.DEFAULT_THEME, status=Style(foreground=BLUE))
        theme.apply_theme(styled)
        self.assertEqual(StatusBar.style, Style(foreground=BLUE))
        canvas = Canvas(10, 2)
        StatusBar().paint(canvas, "hi")
        self.assertEqual(canvas.cell(1, 1), ("h", Style(foreground=BLUE)))

    def test_overrides_merge_with_base(self) -> None:
        """An override changes only the parts it names."""
        built = theme.build_theme(
            {
                "colours": {
                    "window.body": {"foreground": "yellow"},
                    "window.shadow": None,
                }
            }
        )
        self.assertEqual(
            built["window.body"],
            Style(foreground=3, background=Window.body_style.background),
        )
        self.assertIsNone(built["window.shadow"])
        self.assertEqual(built["menu.bar"], theme.DEFAULT_THEME["menu.bar"])

    def test_every_problem_is_reported(self) -> None:
        """Mistakes are listed together."""
        with self.assertRaises(theme.ThemeError) as context:
            theme.build_theme(
                {
                    "base": "sepia",
                    "colour": {},
                    "colours": {
                        "windw.body": {},
                        "window.body": {"foreground": "purple", "blink": True},
                        "status": None,
                        "menu.bar": {"bold": "yes"},
                    },
                }
            )
        message = str(context.exception)
        for text in (
            '"base" must be one of default, dark, monochrome',
            'unknown setting "colour"',
            'unknown role "windw.body"',
            "'purple' is not a colour",
            'unknown setting "blink"',
            '"status" cannot be null',
            '"menu.bar" bold must be true or false',
        ):
            self.assertIn(text, message)

    def test_to_json_round_trips(self) -> None:
        """The file written by --init-colours rebuilds the same theme."""
        written = json.loads(theme.theme_to_json(theme.DEFAULT_THEME))
        self.assertEqual(theme.build_theme(written), theme.DEFAULT_THEME)
        mono = json.loads(theme.theme_to_json(theme.MONOCHROME_THEME, "monochrome"))
        self.assertEqual(theme.build_theme(mono), theme.MONOCHROME_THEME)

    def test_newer_roles_written_only_where_needed(self) -> None:
        """Newer roles written only where needed."""
        for base, colours in theme.BASES.items():
            written = json.loads(theme.theme_to_json(colours, base))
            self.assertNotIn("tabs.disabled", written["colours"])
            self.assertEqual(theme.build_theme(written), colours)
        changed = theme.DEFAULT_THEME | {"tabs.disabled": Style(foreground=RED)}
        written = json.loads(theme.theme_to_json(changed))
        self.assertEqual(written["colours"]["tabs.disabled"]["foreground"], "red")
        self.assertEqual(theme.build_theme(written), changed)
        for version, sent in ((1, False), (2, True)):
            colours = json.loads(theme.theme_to_json(changed, version=version))
            self.assertEqual("tabs.disabled" in colours["colours"], sent)
        default = json.loads(theme.theme_to_json(theme.DEFAULT_THEME, version=2))
        self.assertIn("tabs.disabled", default["colours"])

    def test_monochrome_choice(self) -> None:
        """--monochrome always wins; NO_COLOR applies unless the file has a base."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "colours.json"
            mono = theme.MONOCHROME_THEME
            self.assertEqual(theme.load_theme(path, no_colour=True), mono)
            path.write_text('{"base": "default"}', encoding="utf-8")
            self.assertEqual(
                theme.load_theme(path, no_colour=True), theme.DEFAULT_THEME
            )
            self.assertEqual(theme.load_theme(path, monochrome=True), mono)


class NoColoursDrawnTests(ThemeIsolation):
    """No colours drawn under a colourless theme."""

    COLOURED = Style(foreground=RED, background=BLUE, bold=True)

    def test_colours_left_out(self) -> None:
        """A background becomes reverse video, and a foreground goes."""
        theme.apply_theme(theme.MONOCHROME_THEME)
        self.assertFalse(theme.has_colours())
        self.assertEqual(self.COLOURED.sgr(), "\x1b[0;1;7m")
        self.assertEqual(Style(foreground=RED).sgr(), "\x1b[0m")
        reversed_already = Style(background=Rgb(1, 2, 3), reverse=True)
        self.assertEqual(reversed_already.sgr(), "\x1b[0;7m")

    def test_colours_come_back(self) -> None:
        """Another theme has colours again."""
        theme.apply_theme(theme.MONOCHROME_THEME)
        theme.apply_theme(theme.DEFAULT_THEME)
        self.assertTrue(theme.has_colours())
        self.assertIn("31", self.COLOURED.sgr())

    def test_colours_added_to_the_theme_are_drawn(self) -> None:
        """Monochrome with colours the user added is not without colours."""
        theme.apply_theme(theme.MONOCHROME_THEME)
        theme.apply_theme({"window.body": Style(foreground=RED)})
        self.assertIn("31", self.COLOURED.sgr())

    def test_no_colour_terminal(self) -> None:
        """A terminal with no colours gets none under any theme."""
        with mock.patch("dasha.theme.terminal_has_colours", return_value=False):
            theme.apply_theme(theme.DEFAULT_THEME)
        self.assertEqual(self.COLOURED.sgr(), "\x1b[0;1;7m")

    def test_a_coloured_window_draws_none(self) -> None:
        """A coloured window draws none."""

        class Coloured(Window):
            """Colours of its own, as an application might have."""

            frame_style = Style(foreground=RED, background=BLUE)
            body_style = Style(foreground=RED, background=BLUE)

        theme.apply_theme(theme.MONOCHROME_THEME)
        manager = PresentationManager()
        manager.handle_resize(40, 12)
        manager.add(Coloured("Mine", Rect(1, 1, 8, 30)))
        canvas = Canvas(40, 12)
        manager.compose(canvas=canvas)
        codes = re.findall(r"\x1b\[([0-9;]*)m", canvas.render())
        self.assertTrue(codes)
        for code in codes:
            self.assertLessEqual(set(code.split(";")), {"", "0", "1", "4", "7"}, code)

    def test_which_terminals_have_colours(self) -> None:
        """By ``TERM``, unless ``COLORTERM`` says so; Windows always has."""
        for term, colour_term, name, expected in (
            ("vt100", "", "posix", False),
            ("dumb", "", "posix", False),
            ("VT220", "", "posix", False),
            ("xterm", "", "posix", True),
            ("vt100", "truecolor", "posix", True),
            ("vt100", "", "nt", True),
        ):
            with (
                mock.patch.dict(os.environ, {"TERM": term, "COLORTERM": colour_term}),
                mock.patch("dasha.style.os.name", name),
            ):
                found = terminal_has_colours()
            self.assertEqual(found, expected, (term, colour_term, name))


class StartingThemeTests(ThemeIsolation):
    """The theme an application running on its own starts with."""

    def setUp(self) -> None:
        super().setUp()
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.manager = PresentationManager()
        self.manager.settings_path = self.folder / "settings.toml"
        self.colours = self.folder / "colours.json"
        self.manager.colours_path = self.colours
        self.manager.themes_folder = self.folder

    def started(self, no_colour: str = "", *, saved: bool = True) -> str | None:
        """The starting theme's name.

        :param no_colour: The ``NO_COLOR`` value.
        :param saved: Whether a theme is saved.
        """
        self.manager.theme_name = "default"
        with (
            mock.patch.dict(os.environ, {"NO_COLOR": no_colour}),
            mock.patch("dasha.style.terminal_has_colours", return_value=True),
        ):
            self.manager.use_starting_theme(saved=saved)
        return self.manager.theme_name

    def test_nothing_saved(self) -> None:
        """With nothing saved, the Default theme, or Monochrome for NO_COLOR."""
        self.assertEqual(self.started(), "default")
        self.assertEqual(self.started("1"), "monochrome")

    def test_the_saved_theme(self) -> None:
        """The theme chosen last is used, unless NO_COLOR is set."""
        self.manager.settings_path.write_text('theme = "monochrome"\n', "utf-8")
        self.assertEqual(self.started(), "monochrome")
        self.assertFalse(theme.has_colours())
        self.manager.settings_path.write_text('theme = "dark"\n', "utf-8")
        self.assertEqual(self.started(), "dark")
        self.assertEqual(self.started("1"), "monochrome")

    def test_no_colour_comes_before_the_colours_file(self) -> None:
        """``NO_COLOR`` comes before the colours file."""
        self.colours.write_text('{"base": "dark"}', "utf-8")
        self.assertEqual(self.started("1"), "monochrome")
        self.assertFalse(theme.has_colours())

    def test_the_colours_file(self) -> None:
        """The colours file counts, as it does on the desktop."""
        self.colours.write_text('{"base": "monochrome"}', "utf-8")
        self.assertIsNone(self.started())
        self.assertFalse(theme.has_colours())

    def test_what_cannot_be_used_is_passed_over(self) -> None:
        """A saved theme that is not there leaves it to NO_COLOR."""
        self.manager.settings_path.write_text('theme = "missing"\n', "utf-8")
        self.assertEqual(self.started(), "default")
        self.assertEqual(self.started("1"), "monochrome")

    def test_saved_only_when_asked(self) -> None:
        """Without ``saved``, as in a given terminal, the settings go unread."""
        self.manager.settings_path.write_text('theme = "dark"\n', "utf-8")
        self.assertEqual(self.started(saved=False), "default")

    def test_a_terminal_with_no_colours_comes_first(self) -> None:
        """It gets Monochrome, whatever was saved, and that is not saved."""
        self.manager.settings_path.write_text('theme = "dark"\n', "utf-8")
        with mock.patch("dasha.style.terminal_has_colours", return_value=False):
            self.manager.use_starting_theme()
        self.assertEqual(self.manager.theme_name, "monochrome")
        self.assertIn("dark", self.manager.settings_path.read_text("utf-8"))


class MonochromeOutputTests(ThemeIsolation):
    """The monochrome theme sends no colour codes at all."""

    def test_demo_screen_has_no_colours(self) -> None:
        """Every window, menu, dialog and widget: only bold/underline/reverse."""
        theme.apply_theme(theme.MONOCHROME_THEME)
        manager = PresentationManager()
        manager.handle_resize(80, 24)
        long_lines = [f"line {n} " + "wider than the window " * 3 for n in range(30)]
        manager.add(Window("Scrolls", Rect(1, 0, 8, 30), long_lines))
        editor = Window("Edits", Rect(2, 50, 6, 28))
        editor.add(TextArea(0, 0, text="some text"))
        manager.add(editor)
        manager.add(widgets_window())
        manager.add(Dialog("Dialog", 30, 6))
        manager.handle_event("f10")
        canvas = Canvas(80, 24)
        manager.compose(canvas)
        codes = re.findall(r"\x1b\[([0-9;]*)m", canvas.render())
        self.assertTrue(codes)
        parameters = {p for code in codes for p in code.split(";") if p}
        self.assertLessEqual(parameters, {"0", "1", "4", "7"})


def widgets_window() -> Window:
    """A window of every kind of widget."""
    window = Window("Widgets", Rect(3, 2, 20, 60))
    window.add(Label("Label", 0, 0))
    window.add(TextBox(0, 10, 12, text="text"))
    window.add(Button("&OK", 1, 0))
    window.add(Switch("&Switch", 1, 14, on=True))
    window.add(CheckBoxes(["&A", "&B"], 4, 0, checked=[0], disabled=[1]))
    window.add(RadioButtons(["&C", "&D"], 4, 20))
    window.add(ListBox(["one", "two", "three"], 7, 0, 12, 2, multiple=True))
    window.add(ComboBox(["x", "y"], 7, 20, 10))
    window.add(ProgressBar(10, 0, 20, value=50))
    window.add(ColumnBar(10, 40, 5, 4, value=50))
    window.add(Slider(12, 0, 20))
    window.add(SpinBox(13, 0, 8, minimum=0, maximum=9))
    window.add(AutoCompleteBox(14, 0, 20, suggestions=["a"]))
    window.add(PasswordBox(15, 0, 12, text="secret"))
    group = window.add(GroupBox("&Group", 0, 30, 25, 4))
    group.add(Paragraph("wrapped words in a group box, scrolling", 0, 0, 20, 2))
    tabs = window.add(Tabs(4, 30, 25, 5))
    tabs.add_page("&One").add(Label("on a page", 0, 0))
    tabs.add_page("&Two")
    splitter = window.add(Splitter(10, 30, 25, 4, position=10))
    splitter.first.add(Label("left", 0, 0))
    columns = [Column("Name", 8), Column("Size", 4)]
    window.add(Table(columns, 15, 30, 14, 3, rows=[["a", "1"]]))
    window.add(
        TreeView([TreeNode("root", [TreeNode("leaf")], expanded=True)], 16, 14, 14, 2)
    )
    return window


class CommandLineTests(ThemeIsolation):
    """--init-colours, --colours and --monochrome."""

    def setUp(self) -> None:
        super().setUp()
        directory = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "colours.json"

    def run_main(self, *args: str) -> tuple[int, str, str]:
        """Run main; return exit code, stdout and stderr.

        :param args: Command-line arguments.
        """
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_init_colours(self) -> None:
        """``--init-colours``."""
        code, out, _ = self.run_main("--init-colours", "--colours", str(self.path))
        self.assertEqual(code, 0)
        self.assertIn(str(self.path), out)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(data["colours"]), set(theme.ROLES) - set(theme.NEWER_ROLES)
        )
        code, _, err = self.run_main("--init-colours", "--colours", str(self.path))
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)

    def test_bad_colours_file_stops_before_starting(self) -> None:
        """A broken colours file is reported, with how to recover."""
        self.path.write_text('{"colours": {"nope": {}}}', encoding="utf-8")
        code, _, err = self.run_main("desktop", "--colours", str(self.path))
        self.assertEqual(code, 1)
        self.assertIn('unknown role "nope"', err)
        self.assertIn("move it aside", err)

    def test_a_base_that_is_not_text_stops_before_starting(self) -> None:
        """Reported as a problem with the file, not with a traceback."""
        self.path.write_text('{"base": ["dark"]}', encoding="utf-8")
        code, _, err = self.run_main("desktop", "--colours", str(self.path))
        self.assertEqual(code, 1)
        self.assertIn('"base" must be one of', err)
        self.assertNotIn("Traceback", err)

    def test_monochrome_option_applies_theme(self) -> None:
        """--monochrome installs the monochrome theme before starting."""
        self.path.write_text("{}", encoding="utf-8")  # a named file must exist
        self.run_main("--monochrome", "--colours", str(self.path), "--key-test")
        self.assertEqual(theme.current_theme(), theme.MONOCHROME_THEME)

    def test_monochrome_leaves_out_the_colours_file(self) -> None:
        """Monochrome leaves out the colours file."""
        colours = {
            "base": "default",
            "colours": {"desktop": {"foreground": "#6699cc", "background": "blue"}},
        }
        self.path.write_text(json.dumps(colours), encoding="utf-8")
        self.run_main("--monochrome", "--colours", str(self.path), "--key-test")
        self.assertEqual(theme.current_theme(), theme.MONOCHROME_THEME)


if __name__ == "__main__":
    unittest.main()
