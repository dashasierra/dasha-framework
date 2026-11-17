"""Tests for RGB colours: ``style.Rgb``, drawn in 24-bit colour or as the
nearest 256-palette colour, read and written in colours files, sent in
messages, and the colour depth chosen on the command line or in
``settings.toml``."""

import json
import os
import unittest
from unittest import mock

from dasha import registry, style, theme
from dasha.protocol import ProtocolError, decode_style, encode_style
from dasha.registry import (
    ManifestError,
    read_colour_depth_setting,
    save_colour_depth_setting,
)
from dasha.style import (
    BLACK,
    BLUE,
    BRIGHT_BLACK,
    BRIGHT_BLUE,
    BRIGHT_WHITE,
    WHITE,
    YELLOW,
    Rgb,
    Style,
    set_colour_depth,
)
from tests.support import isolated_home, started_desktop


def depth_put_back(case: unittest.TestCase) -> None:
    """Put the colour depth back as it was, after a test."""
    case.addCleanup(setattr, style, "DRAWN_DEPTH", style.DRAWN_DEPTH)


class RgbTests(unittest.TestCase):
    """The colour itself."""

    def test_parts_are_0_to_255(self) -> None:
        """Each part must be a number from 0 to 255."""
        Rgb(0, 128, 255)
        for parts in ((256, 0, 0), (0, -1, 0), (0, 0, True), (0, 1.5, 0)):
            with self.subTest(parts=parts):
                self.assertRaises(ValueError, Rgb, *parts)

    def test_parse(self) -> None:
        """#rrggbb or #rgb, in either case; nothing else."""
        self.assertEqual(Rgb.parse("#FF8800"), Rgb(255, 136, 0))
        self.assertEqual(Rgb.parse("#f80"), Rgb(255, 136, 0))
        for text in ("ff8800", "#ff880", "#ff88001", "#gg0000", "", "# ff8800"):
            with self.subTest(text=text):
                self.assertRaises(ValueError, Rgb.parse, text)

    def test_written_as_hex(self) -> None:
        """Lower case, with all six digits."""
        self.assertEqual(Rgb(255, 136, 0).hex, "#ff8800")
        self.assertEqual(str(Rgb(1, 2, 3)), "#010203")

    def test_nearest_256(self) -> None:
        """The cube's own colours, greys, and colours in between."""
        self.assertEqual(Rgb(0, 0, 0).nearest_256(), 16)
        self.assertEqual(Rgb(255, 255, 255).nearest_256(), 231)
        self.assertEqual(Rgb(255, 0, 0).nearest_256(), 196)
        self.assertEqual(Rgb(95, 135, 175).nearest_256(), 16 + 36 + 12 + 3)
        self.assertEqual(Rgb(128, 128, 128).nearest_256(), 244)
        self.assertEqual(Rgb(250, 130, 5).nearest_256(), 208)  # 255, 135, 0

    def test_nearest_16(self) -> None:
        """The CGA's colours, and colours near them."""
        self.assertEqual(Rgb(0, 0, 0).nearest_16(), BLACK)
        self.assertEqual(Rgb(0xAA, 0x55, 0x00).nearest_16(), YELLOW)  # brown
        self.assertEqual(Rgb(255, 255, 255).nearest_16(), BRIGHT_WHITE)
        self.assertEqual(Rgb(0x10, 0x10, 0x18).nearest_16(), BLACK)
        self.assertEqual(Rgb(0x20, 0x30, 0x40).nearest_16(), BRIGHT_BLACK)
        self.assertEqual(Rgb(0x66, 0x99, 0xCC).nearest_16(), WHITE)
        self.assertEqual(Rgb(0x30, 0x30, 0xF0).nearest_16(), BRIGHT_BLUE)

    def test_of_palette(self) -> None:
        """The colours of the 256-colour palette's numbers."""
        self.assertEqual(Rgb.of_palette(BLUE), Rgb(0, 0, 0xAA))
        self.assertEqual(Rgb.of_palette(196), Rgb(255, 0, 0))
        self.assertEqual(Rgb.of_palette(16 + 36 + 12 + 3), Rgb(95, 135, 175))
        self.assertEqual(Rgb.of_palette(232), Rgb(8, 8, 8))
        self.assertEqual(Rgb.of_palette(255), Rgb(238, 238, 238))
        for number in range(16, 256):
            self.assertEqual(Rgb.of_palette(number).nearest_256(), number)


class DrawnTests(unittest.TestCase):
    """The escape sequences an RGB colour is drawn with."""

    def setUp(self) -> None:
        depth_put_back(self)

    def test_24_bit(self) -> None:
        """As it is, foreground and background."""
        set_colour_depth("24bit")
        drawn = Style(foreground=Rgb(255, 136, 0), background=Rgb(1, 2, 3)).sgr()
        self.assertEqual(drawn, "\x1b[0;38;2;255;136;0;48;2;1;2;3m")

    def test_256(self) -> None:
        """As the nearest palette colour."""
        set_colour_depth("256")
        self.assertEqual(Style(foreground=Rgb(255, 0, 0)).sgr(), "\x1b[0;38;5;196m")

    def test_16(self) -> None:
        """Every colour as the nearest of the 16 standard colours: RGB
        colours, and palette colours above 15; those up to 15 as before."""
        set_colour_depth("16")
        self.assertEqual(Style(foreground=Rgb(255, 0, 0)).sgr(), "\x1b[0;31m")
        self.assertEqual(Style(background=Rgb(0, 0, 0xA0)).sgr(), "\x1b[0;44m")
        self.assertEqual(Style(background=200).sgr(), "\x1b[0;105m")
        self.assertEqual(Style(foreground=BLUE).sgr(), "\x1b[0;34m")

    def test_numbers_are_unchanged(self) -> None:
        """Numbered colours are drawn as before, at 256 or 24-bit."""
        for depth in ("256", "24bit"):
            set_colour_depth(depth)
            self.assertEqual(Style(foreground=BLUE).sgr(), "\x1b[0;34m")
            self.assertEqual(Style(background=200).sgr(), "\x1b[0;48;5;200m")

    def test_automatic(self) -> None:
        """24-bit when COLORTERM says so, or on Windows; 16 for the Linux
        console and the like; otherwise 256."""
        for colour_term, term, name, expected in (
            ("truecolor", "xterm-256color", "posix", "24bit"),
            ("24bit", "linux", "posix", "24bit"),
            ("", "xterm-256color", "posix", "256"),
            ("", "linux", "posix", "16"),
            ("", "", "nt", "24bit"),
        ):
            with self.subTest(colour_term=colour_term, term=term, name=name):
                with (
                    mock.patch.dict(
                        os.environ, {"COLORTERM": colour_term, "TERM": term}
                    ),
                    mock.patch.object(os, "name", name),
                ):
                    set_colour_depth("auto")
                self.assertEqual(style.DRAWN_DEPTH, expected)

    def test_unknown_depth(self) -> None:
        """Refused."""
        self.assertRaises(ValueError, set_colour_depth, "8")


class FileTests(unittest.TestCase):
    """RGB colours in colours and theme files."""

    def test_parsed(self) -> None:
        """#rrggbb and #rgb are colours; a bad one says what to write."""
        self.assertEqual(theme.parse_colour("#FF8800"), Rgb(255, 136, 0))
        self.assertEqual(theme.parse_colour("#f80"), Rgb(255, 136, 0))
        with self.assertRaisesRegex(ValueError, "#ff8800"):
            theme.parse_colour("#ff88")

    def test_a_colours_file(self) -> None:
        """Read from a colours file, and written back as it was."""
        built = theme.build_theme({"colours": {"desktop": {"background": "#203040"}}})
        desktop = built["desktop"]
        assert isinstance(desktop, Style)
        self.assertEqual(desktop.background, Rgb(32, 48, 64))
        written = json.loads(theme.theme_to_json(built))
        self.assertEqual(written["colours"]["desktop"]["background"], "#203040")


class MessageTests(unittest.TestCase):
    """RGB colours in messages."""

    def test_round_trip(self) -> None:
        """Sent as #rrggbb, and taken back as the same style."""
        sent = Style(foreground=Rgb(255, 136, 0), background=7, bold=True)
        encoded = encode_style(sent)
        self.assertEqual(encoded[:2], ["#ff8800", 7])
        self.assertEqual(decode_style(json.loads(json.dumps(encoded))), sent)

    def test_not_a_colour(self) -> None:
        """Anything else ends the application."""
        for colour in ("#zzzzzz", "#12345", "#" + "f" * 10_000, "red"):
            with self.subTest(colour=colour[:10]):
                with self.assertRaises(ProtocolError) as caught:
                    decode_style([colour, None, 0, 0, 0])
                self.assertLess(len(str(caught.exception)), 60)


class DepthSettingTests(unittest.TestCase):
    """The colour depth in ``settings.toml``, and ``--colour-depth``."""

    def setUp(self) -> None:
        self.home = isolated_home(self)
        depth_put_back(self)
        self.path = self.home / "settings.toml"

    def test_read_and_saved(self) -> None:
        """Automatic, unless the file says otherwise; automatic is never
        written."""
        self.assertEqual(read_colour_depth_setting(self.path), "auto")
        save_colour_depth_setting("256", self.path)
        self.assertEqual(self.path.read_text("utf-8"), 'colour_depth = "256"\n')
        self.assertEqual(read_colour_depth_setting(self.path), "256")
        save_colour_depth_setting("auto", self.path)
        self.assertEqual(self.path.read_text("utf-8"), "")

    def test_refused(self) -> None:
        """Only the three depths."""
        self.path.write_text("colour_depth = 16\n", encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "colour_depth"):
            read_colour_depth_setting(self.path)

    def started_with(self, *arguments: str) -> tuple[int, str | None, str]:
        """The exit code of the command line, the colour depth the desktop
        started with, and what it said."""
        code, desktop, said = started_desktop(*arguments)
        depth = desktop.call_args.kwargs["colour_depth"] if desktop.called else None
        return code, depth, said

    def test_the_command_line_wins(self) -> None:
        """--colour-depth, else settings.toml, else automatic."""
        self.assertEqual(self.started_with()[:2], (0, "auto"))
        save_colour_depth_setting("24bit", registry.SETTINGS_PATH)
        self.assertEqual(self.started_with()[:2], (0, "24bit"))
        self.assertEqual(self.started_with("--colour-depth", "256")[:2], (0, "256"))

    def test_the_command_line_is_remembered(self) -> None:
        """A depth given with -d (--colour-depth) is kept in settings.toml
        for next time, as Settings... keeps it; -d auto forgets it."""
        self.assertEqual(self.started_with("-d", "16")[:2], (0, "16"))
        self.assertEqual(read_colour_depth_setting(registry.SETTINGS_PATH), "16")
        self.assertEqual(self.started_with()[:2], (0, "16"))
        self.assertEqual(self.started_with("-d", "auto")[:2], (0, "auto"))
        self.assertEqual(self.started_with()[:2], (0, "auto"))
        self.assertNotIn("colour_depth", registry.SETTINGS_PATH.read_text("utf-8"))

    def test_a_bad_setting_stops_it(self) -> None:
        """Said before the screen is taken over."""
        registry.SETTINGS_PATH.write_text('colour_depth = "lots"\n', "utf-8")
        code, depth, said = self.started_with()
        self.assertEqual((code, depth), (1, None))
        self.assertIn("colour_depth", said)


if __name__ == "__main__":
    unittest.main()
