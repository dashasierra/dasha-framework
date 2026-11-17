"""Tests for how long the desktop waits after a lone ESC for the rest of a
key: 100 ms unless ``escape_timeout`` in ``settings.toml`` (or Settings...)
says otherwise, so a key arriving slowly over SSH is not taken as Escape."""

import unittest

from dasha import registry
from dasha.manager import PresentationManager
from dasha.registry import (
    ESCAPE_TIMEOUT,
    ManifestError,
    read_escape_timeout_setting,
    save_escape_timeout_setting,
)
from tests.support import isolated_home, started_desktop


class SettingTests(unittest.TestCase):
    """``escape_timeout`` in ``settings.toml``."""

    def setUp(self) -> None:
        self.path = isolated_home(self) / "settings.toml"

    def test_read_and_saved(self) -> None:
        """100 ms unless the file says otherwise; the default is never
        written."""
        self.assertEqual(read_escape_timeout_setting(self.path), ESCAPE_TIMEOUT)
        self.assertEqual(ESCAPE_TIMEOUT, 100)
        save_escape_timeout_setting(250, self.path)
        self.assertEqual(self.path.read_text("utf-8"), "escape_timeout = 250\n")
        self.assertEqual(read_escape_timeout_setting(self.path), 250)
        save_escape_timeout_setting(ESCAPE_TIMEOUT, self.path)
        self.assertEqual(self.path.read_text("utf-8"), "")

    def test_refused(self) -> None:
        """A whole number of milliseconds, from 10 to 2,000."""
        for value in ("5", "2001", "true", '"100"', "100.5", "-1"):
            with self.subTest(value=value):
                self.path.write_text(f"escape_timeout = {value}\n", "utf-8")
                with self.assertRaisesRegex(ManifestError, "escape_timeout"):
                    read_escape_timeout_setting(self.path)

    def test_the_desktop_uses_it(self) -> None:
        """Started from the command line, or an application on its own."""
        self.assertEqual(started_desktop()[1].call_args.kwargs["escape_timeout"], 100)
        save_escape_timeout_setting(400, registry.SETTINGS_PATH)
        code, desktop, _ = started_desktop()
        self.assertEqual((code, desktop.call_args.kwargs["escape_timeout"]), (0, 400))
        manager = PresentationManager()
        manager.settings_path = registry.SETTINGS_PATH
        self.assertEqual(manager.escape_timeout, 0.1)
        manager.use_saved_escape_timeout()
        self.assertEqual(manager.escape_timeout, 0.4)

    def test_a_bad_setting_stops_it(self) -> None:
        """Said before the screen is taken over."""
        registry.SETTINGS_PATH.write_text("escape_timeout = 1\n", "utf-8")
        code, desktop, said = started_desktop()
        self.assertEqual(code, 1)
        self.assertFalse(desktop.called)
        self.assertIn("escape_timeout", said)


if __name__ == "__main__":
    unittest.main()
