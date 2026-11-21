"""Tests for encoding keys and the mouse for programs."""

import unittest

from dasha.events import MouseEvent
from dasha.vt import encode_key, encode_mouse


class EncodeKeyTests(unittest.TestCase):
    """``encode_key``, in normal and application cursor key modes."""

    def test_characters(self) -> None:
        """Characters are sent as UTF-8."""
        self.assertEqual(encode_key("a"), b"a")
        self.assertEqual(encode_key("A"), b"A")
        self.assertEqual(encode_key(" "), b" ")
        self.assertEqual(encode_key("\N{POUND SIGN}"), "\N{POUND SIGN}".encode())

    def test_plain_keys(self) -> None:
        """Enter, Tab, Backspace and Escape."""
        table = {
            "enter": b"\r",
            "tab": b"\t",
            "shift+tab": b"\x1b[Z",
            "backspace": b"\x7f",
            "ctrl+backspace": b"\x08",
            "escape": b"\x1b",
            "alt+enter": b"\x1b\r",
        }
        for key, sent in table.items():
            with self.subTest(key=key):
                self.assertEqual(encode_key(key), sent)

    def test_ctrl_and_alt(self) -> None:
        """Ctrl gives the C0 controls; Alt puts ESC in front."""
        table = {
            "ctrl+a": b"\x01",
            "ctrl+c": b"\x03",
            "ctrl+z": b"\x1a",
            "ctrl+space": b"\x00",
            "ctrl+]": b"\x1d",
            "ctrl+_": b"\x1f",
            "alt+b": b"\x1bb",
            "alt+B": b"\x1bB",
            "alt+.": b"\x1b.",
            "alt+ctrl+d": b"\x1b\x04",
        }
        for key, sent in table.items():
            with self.subTest(key=key):
                self.assertEqual(encode_key(key), sent)

    def test_cursor_keys(self) -> None:
        """CSI normally, SS3 in application mode, CSI 1;m with modifiers."""
        self.assertEqual(encode_key("up"), b"\x1b[A")
        self.assertEqual(encode_key("left", app_cursor_keys=True), b"\x1bOD")
        self.assertEqual(encode_key("home"), b"\x1b[H")
        self.assertEqual(encode_key("end", app_cursor_keys=True), b"\x1bOF")
        self.assertEqual(encode_key("shift+up"), b"\x1b[1;2A")
        self.assertEqual(encode_key("ctrl+right", app_cursor_keys=True), b"\x1b[1;5C")
        self.assertEqual(encode_key("shift+alt+ctrl+down"), b"\x1b[1;8B")

    def test_editing_and_function_keys(self) -> None:
        """Insert, Delete, PgUp, PgDn and F1 to F12, with modifiers."""
        table = {
            "insert": b"\x1b[2~",
            "delete": b"\x1b[3~",
            "pageup": b"\x1b[5~",
            "ctrl+pagedown": b"\x1b[6;5~",
            "f1": b"\x1bOP",
            "f4": b"\x1bOS",
            "shift+f1": b"\x1b[1;2P",
            "f5": b"\x1b[15~",
            "f10": b"\x1b[21~",
            "f12": b"\x1b[24~",
            "alt+f5": b"\x1b[15;3~",
        }
        for key, sent in table.items():
            with self.subTest(key=key):
                self.assertEqual(encode_key(key), sent)

    def test_keys_with_no_bytes(self) -> None:
        """Unknown keys and modifiers send nothing."""
        for key in ("unknown(99x)", "hyper+a", "ctrl+\N{POUND SIGN}", "f99"):
            with self.subTest(key=key):
                self.assertIsNone(encode_key(key))


class EncodeMouseTests(unittest.TestCase):
    """``encode_mouse``: mouse reports, as a program asked for them."""

    SGR = {1000, 1002, 1006}

    def test_sgr_reports(self) -> None:
        """SGR reports."""
        table = [
            (MouseEvent("press", "left", 0, 0), b"\x1b[<0;6;3M"),
            (MouseEvent("release", "left", 0, 0), b"\x1b[<0;6;3m"),
            (MouseEvent("press", "right", 0, 0), b"\x1b[<2;6;3M"),
            (MouseEvent("drag", "middle", 0, 0), b"\x1b[<33;6;3M"),
            (MouseEvent("scroll", "up", 0, 0), b"\x1b[<64;6;3M"),
            (MouseEvent("scroll", "down", 0, 0), b"\x1b[<65;6;3M"),
            (
                MouseEvent("press", "left", 0, 0, shift=True, alt=True, ctrl=True),
                b"\x1b[<28;6;3M",
            ),
        ]
        for event, sent in table:
            with self.subTest(event=event):
                self.assertEqual(encode_mouse(event, 2, 5, self.SGR), sent)

    def test_original_form(self) -> None:
        """The original form."""
        modes = {1000}
        press = MouseEvent("press", "left", 0, 0)
        self.assertEqual(encode_mouse(press, 2, 5, modes), b"\x1b[M &#")
        release = MouseEvent("release", "right", 0, 0)
        self.assertEqual(encode_mouse(release, 0, 0, modes), b"\x1b[M#!!")
        self.assertIsNone(encode_mouse(press, 0, 223, modes))
        self.assertEqual(encode_mouse(press, 0, 223, {1000, 1006}), b"\x1b[<0;224;1M")

    def test_only_what_was_asked_for(self) -> None:
        """Only what was asked for."""
        drag = MouseEvent("drag", "left", 0, 0)
        move = MouseEvent("move", "none", 0, 0)
        self.assertIsNone(encode_mouse(MouseEvent("press", "left", 0, 0), 0, 0, {1006}))
        self.assertIsNone(encode_mouse(drag, 0, 0, {1000, 1006}))
        self.assertIsNone(encode_mouse(move, 0, 0, {1002, 1006}))
        self.assertEqual(encode_mouse(move, 0, 0, {1003, 1006}), b"\x1b[<35;1;1M")


if __name__ == "__main__":
    unittest.main()
