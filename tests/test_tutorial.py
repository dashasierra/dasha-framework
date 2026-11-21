"""Tests for the tutorial."""

import difflib
import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

TUTORIAL = Path(__file__).resolve().parents[1] / "docs" / "tutorial"


def tool(name: str) -> ModuleType:
    """Import one of the tutorial's scripts.

    :param name: Script name.
    """
    spec = importlib.util.spec_from_file_location(name, TUTORIAL / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    # Run as a script, a tool puts src on sys.path itself; imported here,
    # that is undone, as Dasha Framework is importable already.
    with mock.patch.object(sys, "path", list(sys.path)):
        spec.loader.exec_module(module)
    return module


class StepsTests(unittest.TestCase):
    """Steps 4 to 9 are the finished Notepad with features taken away."""

    def test_steps_are_up_to_date(self) -> None:
        """What make_steps.py writes is what is there (run it if not)."""
        try:
            make_steps = tool("make_steps")
        except ImportError:
            self.skipTest("make_steps.py needs black (the dev extra)")
        for step, text in make_steps.steps().items():
            path = TUTORIAL / f"notepad{step}.py"
            with self.subTest(step=step):
                self.assertEqual(path.read_text(encoding="utf-8"), text)


class ScreensTests(unittest.TestCase):
    """The pictures in the tutorial are what each step draws."""

    def test_screens_are_up_to_date(self) -> None:
        """The screens are up to date."""
        make_screens = tool("make_screens")
        windows_only = {"open-dialog", "save-as-dialog"}
        for name, canvas in make_screens.screens().items():
            if name in windows_only and os.name != "nt":
                continue
            path = TUTORIAL / "screens" / f"{name}.png"
            with self.subTest(screen=name):
                self.assertEqual(
                    make_screens.read_screen_data(path),
                    make_screens.screen_data(canvas),
                )

    def test_every_screen_is_shown(self) -> None:
        """Every screen is shown."""
        make_screens = tool("make_screens")
        pages = "".join(page.read_text(encoding="utf-8") for page in pages_of())
        for name in make_screens.SHOTS:
            with self.subTest(screen=name):
                self.assertIn(f"screens/{name}.png", pages)
        files = {path.name for path in (TUTORIAL / "screens").iterdir()}
        self.assertEqual(files, {f"{name}.png" for name in make_screens.SHOTS})


def pages_of() -> list[Path]:
    """The tutorial's pages: a page for each step, and the last one."""
    return sorted(TUTORIAL.glob("*.md"))


def line_numbers(spec: str) -> set[int]:
    """The lines an ``:emphasize-lines:`` option names.

    :param spec: The option's value.
    """
    numbers: set[int] = set()
    for part in spec.split(","):
        first, _, last = part.strip().partition("-")
        numbers.update(range(int(first), int(last or first) + 1))
    return numbers


class PagesTests(unittest.TestCase):
    """The pages that show a whole step highlight what it adds."""

    def test_highlights_are_what_each_step_adds(self) -> None:
        """Highlights are what each step adds."""
        include = re.compile(
            r"```\{literalinclude\} notepad(\d)\.py\n(?::[^\n]*\n)*?"
            r":emphasize-lines: ([\d,\- ]+)\n"
        )
        found = 0
        for page in pages_of():
            for match in include.finditer(page.read_text(encoding="utf-8")):
                step = int(match[1])
                before, after = (
                    (TUTORIAL / f"notepad{n}.py").read_text(encoding="utf-8")
                    for n in (step - 1, step)
                )
                matcher = difflib.SequenceMatcher(
                    None, before.splitlines(), after.splitlines()
                )
                added = {
                    number + 1
                    for kind, _, _, start, end in matcher.get_opcodes()
                    if kind in ("insert", "replace")
                    for number in range(start, end)
                } - {1}
                with self.subTest(page=page.name, step=step):
                    found += 1
                    self.assertEqual(line_numbers(match[2]), added)
        self.assertGreater(found, 0)


if __name__ == "__main__":
    unittest.main()
