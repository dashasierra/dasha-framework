"""Write the tutorial's steps 4 to 9 from the finished Notepad."""

from dataclasses import dataclass
from pathlib import Path

import black

ROOT = Path(__file__).resolve().parents[2]
FINAL = ROOT / "apps" / "notepad.py"
FOLDER = ROOT / "docs" / "tutorial"


@dataclass(frozen=True)
class Between:
    """The text from ``start`` up to, not including, ``end``."""

    start: str
    end: str

    def find(self, text: str) -> str:
        """This stretch of some text.

        :param text: The text.
        """
        first = text.index(self.start)
        return text[first : text.index(self.end, first)]


type Edit = tuple[str | Between, str]
"""Text in a step, and what it is in the step before."""

STEPS: dict[int, tuple[str, list[Edit]]] = {
    9: (
        "an Insert menu",
        [
            (Between("def marked(", "class NotepadWindow"), ""),
            (Between("MODIFIED = ", "def line_ending"), ""),
            (Between("    def footer_parts(self)", "    def _changed(self"), ""),
            (
                "                word_wrap=notepad.word_wrap,\n"
                "                line_numbers=notepad.line_numbers,\n",
                "",
            ),
            (Between("        self.word_wrap = False\n", "    def start(self)"), "\n"),
            (Between('            Menu(title="F&ormat"', "        ]\n"), ""),
            (Between("    def _areas(self)", "\n\nif __name__"), ""),
        ],
    ),
    8: (
        "an Edit menu",
        [
            ("import sys\nimport time\n", "import sys\n"),
            (Between("SINGLE_BOX = (", "def line_ending"), ""),
            (Between("    def _insert(self, text: str)", "    # Closing"), ""),
            (
                Between(
                    "        items += [\n            separator(),",
                    "        return items",
                ),
                "",
            ),
            (Between("    def _insert_menu(self)", "\n\nif __name__"), ""),
        ],
    ),
    7: (
        "not losing work",
        [
            ('            Menu(title="&Edit", items=self._edit_items()),\n', ""),
            (Between("    def _edit_items(self)", "\n\nif __name__"), ""),
        ],
    ),
    6: (
        "saving",
        [
            (
                "from dasha.dialog import confirm, information, question\n",
                "from dasha.dialog import confirm, information\n",
            ),
            (Between("    def offer_to_save(self)", "\n\nclass WindowAction"), ""),
            (Between("    # Closing\n", "    # Menus\n"), ""),
            (
                'status="Exits, offering to save each changed file",',
                'status="Exits Notepad",',
            ),
        ],
    ),
    5: (
        "opening files",
        [
            ("from dasha.config import write_atomically\n", ""),
            (
                "from dasha.dialog import confirm, information\n",
                "from dasha.dialog import information\n",
            ),
            ("                on_change=self._changed,\n", ""),
            (
                '        self.modified = False\n        """Whether there are changes'
                ' since it was opened or saved."""\n',
                "",
            ),
            (Between("    def _changed(self, area", "    def load(self"), ""),
            (
                "        self.area.text = text\n        self.modified = False\n",
                "        self.area.text = text\n",
            ),
            (Between("    # Saving\n", "\n\nclass WindowAction"), ""),
            ("            and not front.modified\n", ""),
            (
                Between(
                    '            MenuItem(\n                label="&Save",',
                    "            separator(),",
                ),
                "",
            ),
        ],
    ),
    4: (
        "a window class, and more windows",
        [
            ("import os\nimport sys\n", ""),
            (
                "from collections.abc import Callable, Sequence\n",
                "from collections.abc import Callable\n",
            ),
            ("from dasha.dialog import information\n", ""),
            ("from dasha.filedialog import FileDialog\n", ""),
            (Between("FILTERS = [", "class NotepadWindow"), ""),
            (
                "    :param path: The file, if any.\n"
                "    :param text: The file's text.\n",
                "",
            ),
            ('        path: str | None = None,\n        text: str = "",\n', ""),
            (
                Between("        self.path = path\n", "        self.area = self.add("),
                "",
            ),
            ("                text=text,\n", ""),
            (Between("    @property\n    def file_name", "\n\nclass WindowAction"), ""),
            ("        self._show_title()\n", ""),
            (
                '    """Edit plain text files, each in its own window.\n\n'
                '    :param paths: Files to open at start.\n    """\n',
                '    """Edit plain text files, each in its own window."""\n',
            ),
            (Between("    def __init__(self, paths", "    def start(self)"), ""),
            (
                "        for path in self.paths:\n"
                "            self.open_path(path=path)\n"
                "        if not self.windows:\n"
                "            self.new()\n",
                "        self.new()\n",
            ),
            (
                '    def new(self, path: str | None = None, text: str = "") -> '
                'NotepadWindow:\n        """Open a window for a new file.\n\n'
                "        :param path: The file, if any.\n"
                '        :param text: Initial text.\n        """\n'
                "        window = NotepadWindow(notepad=self, "
                "rect=self._place(), path=path, text=text)\n",
                '    def new(self) -> NotepadWindow:\n        """Open a window for a '
                'new file."""\n        window = NotepadWindow(notepad=self, '
                "rect=self._place())\n",
            ),
            (Between("    def show(self, window", "    def _front(self)"), ""),
            (
                Between(
                    '            MenuItem(\n                label="&Open...",',
                    "            separator(),",
                ),
                "",
            ),
            (
                "    raise SystemExit(Notepad(paths=sys.argv[1:]).run())",
                "    raise SystemExit(Notepad().run())",
            ),
        ],
    ),
}
"""Each step's title and the edits that take it away."""


def steps() -> dict[int, str]:
    """Steps 9 down to 4, each made from the one after it."""
    made: dict[int, str] = {}
    text = FINAL.read_text(encoding="utf-8")
    for step in sorted(STEPS, reverse=True):
        title, edits = STEPS[step]
        for old, new in edits:
            found = old.find(text) if isinstance(old, Between) else old
            if text.count(found) != 1:
                raise ValueError(f"step {step}: no longer fits: {found[:60]!r}")
            text = text.replace(found, new)
        body = text[text.index('"""', 3) + 3 :]
        text = f'"""Notepad, step {step}: {title}."""{body}'
        text = black.format_str(text, mode=black.Mode(line_length=88))
        made[step] = text
    return made


def main() -> None:
    """Write the steps."""
    for step, text in steps().items():
        path = FOLDER / f"notepad{step}.py"
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
