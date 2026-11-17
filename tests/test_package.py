"""Basic sanity tests for the dasha package."""

import os
import re
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
from unittest.mock import patch

import dasha
from dasha.__main__ import main
from tests.support import ROOT, isolated_home


class PackageTests(unittest.TestCase):
    """Tests for package metadata and the command-line entry point."""

    def test_version_is_set(self) -> None:
        """The package exposes a non-empty version string."""
        self.assertIsInstance(dasha.__version__, str)
        self.assertTrue(dasha.__version__)

    def test_main_refuses_non_interactive_streams(self) -> None:
        """Without a terminal attached, main reports an error instead of drawing."""
        isolated_home(self)  # not the user's own settings, theme included
        with (
            patch("sys.stdin", StringIO()),
            patch("sys.stdout", StringIO()),
            redirect_stderr(StringIO()) as err,
        ):
            self.assertEqual(main(["desktop"]), 1)
        self.assertIn("interactive terminal", err.getvalue())

    def test_version_flag_prints_version(self) -> None:
        """``--version`` prints the version and exits 0."""
        out = StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn(dasha.__version__, out.getvalue())


class ChangelogTests(unittest.TestCase):
    """CHANGELOG.md has the version, as a release's build checks (in
    .github/workflows/build.yml), so a pull request finds out first."""

    def setUp(self) -> None:
        self.text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.version = re.escape(dasha.__version__)

    def test_a_dated_section(self) -> None:
        """``## [VERSION] - YYYY-MM-DD``, with a date that exists."""
        found = re.search(
            rf"^## \[{self.version}\] - (\d{{4}}-\d{{2}}-\d{{2}})$", self.text, re.M
        )
        self.assertIsNotNone(found, f"no dated section for {dasha.__version__}")
        assert found is not None
        date.fromisoformat(found[1])  # raises for 2026-13-40

    def test_a_link_to_the_release(self) -> None:
        """``[VERSION]: .../releases/tag/vVERSION``, at the bottom."""
        release = rf"https://github\.com/.+/releases/tag/v{self.version}"
        found = re.search(rf"^\[{self.version}\]: {release}$", self.text, re.M)
        self.assertIsNotNone(found, f"no link to the release of {dasha.__version__}")


class SurroundingsTests(unittest.TestCase):
    """The tests themselves, wherever they are run from."""

    def test_the_environment_makes_no_difference(self) -> None:
        """Run with ``NO_COLOR`` set, or from a desktop's command prompt, the
        tests that would notice still pass (see ``tests/support.py``), and
        the applications they start still reach their desktop."""
        environment = dict(
            os.environ,
            NO_COLOR="1",
            DASHA_ADDRESS="nowhere",
            DASHA_DESKTOP_PID="1",
            DASHA_SUSPENDED="1",
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "tests.test_theme_switching.StartingTests",
                "tests.test_crash_restore.CrashRestoreTests",
                "tests.test_robustness.HangTests.test_wait_keeps_it",
            ],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
