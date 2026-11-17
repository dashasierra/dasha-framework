"""Draw the screens the tutorial shows, by running its steps.

Each screen comes from running a step as a reader would (``Notepad().run()``)
on a scripted 80 by 24 terminal: the keys a reader would press, then a
picture of the screen, in colour, as a PNG. Run it from the repository's
root after changing a step, and the pictures follow::

    python docs/tutorial/make_screens.py

Drawing needs Pillow and a monospaced font with box drawing characters
(DejaVu Sans Mono, found where systems keep fonts, or ``--font`` and
``--bold-font``). Install Pillow with the ``docs`` extra:
``python -m pip install -e ".[docs]"``. Dasha Framework itself never needs it.

Each PNG also holds what it shows as text (``screen_data``), so
``tests/test_tutorial.py`` can check the pictures are up to date without
Pillow, or the font.

The steps run in a folder of example files made for the purpose, shown in
the file dialogs as ``C:\\Users\\you\\notes``. The pictures are of a Windows
screen: elsewhere a file dialog has no Drive box, and folders end in ``/``.
"""

import argparse
import importlib.util
import json
import os
import struct
import sys
import tempfile
import zlib
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

# pylint: disable=wrong-import-position
from dasha.application import Application  # noqa: E402
from dasha.canvas import Canvas  # noqa: E402
from dasha.filedialog import FileDialog  # noqa: E402
from dasha.protocol import StyleTable, encode_row  # noqa: E402
from dasha.style import Style  # noqa: E402
from dasha.terminal import Terminal  # noqa: E402

if TYPE_CHECKING:
    from PIL import ImageDraw, ImageFont
    from PIL.Image import Image

FOLDER = ROOT / "docs" / "tutorial"
SCREENS = FOLDER / "screens"
SHOWN_FOLDER = r"C:\Users\you\notes"
"""What the file dialogs show for the folder of example files."""

SNAP = object()
"""In a list of keys: take a picture of the screen here."""

KEYS = {
    "enter": "\r",
    "escape": "\x1b",
    "ctrl+q": "\x11",
    "alt+e": "\x1be",
    "alt+f": "\x1bf",
    "alt+o": "\x1bo",
    "alt+f4": "\x1b[1;3S",
    "f2": "\x1bOQ",
    "f3": "\x1bOR",
}
"""What the terminal sends for the keys the screens press."""

FILES = {
    "shopping.txt": "Milk\r\nEggs\r\nBread\r\n",
    "todo.txt": "Remember the meeting at 10.\n",
    "ideas.md": "# Ideas\n",
}
"""The example files, in the folder the steps run in (and a ``letters``
folder beside them)."""

WRAPPED = (
    "Word wrap shows a long line on the rows below it, breaking it after a "
    "space, so the whole of it can be read without scrolling sideways."
)
"""A line too long for Notepad's window, typed with word wrap and line
numbers on."""

# Name: (step file, the application's arguments, what to type and press).
# A string in the keys is typed, a KEYS name is pressed.
SHOTS: dict[str, tuple[str, list[str], list[object]]] = {
    "desktop": ("notepad1.py", [], []),
    "file-menu": ("notepad1.py", [], ["alt+f"]),
    "close-question": ("notepad1.py", [], ["ctrl+q"]),
    "window": ("notepad2.py", [], []),
    "typing": ("notepad3.py", [], ["Dear diary,\r\rToday I wrote a text editor."]),
    "windows": ("notepad4.py", [], ["alt+f", "n", "alt+f", "n"]),
    "open-dialog": ("notepad5.py", [], ["f3"]),
    "opened-files": ("notepad5.py", ["shopping.txt", "todo.txt"], []),
    "save-as-dialog": ("notepad6.py", [], ["Plans for the weekend", "f2"]),
    "save-question": (
        "notepad7.py",
        ["todo.txt"],
        ["Cancel the meeting. ", "alt+f4"],
    ),
    "edit-menu": ("notepad8.py", [], ["Some text", "alt+e"]),
    "insert-menu": ("notepad9.py", [], ["alt+e", "i", "b"]),
    "box": ("notepad9.py", [], ["alt+e", "i", "b", "d"]),
    "format-menu": ("../../apps/notepad.py", [], ["alt+o"]),
    "word-wrap": (
        "../../apps/notepad.py",
        [],
        ["alt+o", "w", "alt+o", "l", WRAPPED + "\rAnd a short one."],
    ),
}
"""The screens, by the name of the file each is written to."""

# Drawing

FONT_SIZE = 20
"""The font's size in pixels: DejaVu Sans Mono makes 12 by 24 cells."""

FONTS = ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf")
"""The fonts to look for (regular, bold), unless named on the command line."""

PALETTE: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),
    (170, 0, 0),
    (0, 170, 0),
    (170, 85, 0),
    (0, 0, 170),
    (170, 0, 170),
    (0, 170, 170),
    (170, 170, 170),
    (85, 85, 85),
    (255, 85, 85),
    (85, 255, 85),
    (255, 255, 85),
    (85, 85, 255),
    (255, 85, 255),
    (85, 255, 255),
    (255, 255, 255),
)
"""The 16 standard colours, as a text-mode screen shows them."""

DEFAULT_FOREGROUND = 7
"""The terminal's own colours, for a style that leaves them (light grey on
black)."""
DEFAULT_BACKGROUND = 0

DATA_KEY = "dasha-screen"
"""The PNG text chunk (iTXt) that holds what a picture shows."""


def rgb(colour: int) -> tuple[int, int, int]:
    """One of the 256 terminal colours, as red, green and blue."""
    if colour < 16:
        return PALETTE[colour]
    if colour < 232:  # the 6 by 6 by 6 colour cube
        levels = (0, 95, 135, 175, 215, 255)
        index = colour - 16
        return levels[index // 36], levels[index // 6 % 6], levels[index % 6]
    grey = 8 + 10 * (colour - 232)
    return grey, grey, grey


def colours(style: Style) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """A style's foreground and background, reversed if it says so."""
    foreground = DEFAULT_FOREGROUND if style.foreground is None else style.foreground
    background = DEFAULT_BACKGROUND if style.background is None else style.background
    if style.reverse:
        foreground, background = background, foreground
    return rgb(foreground), rgb(background)


def find_font(name: str) -> Path:
    """Where a font file is, among the places systems keep fonts."""
    home = Path.home()
    folders = [
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
        Path(os.environ.get("LOCALAPPDATA", home)) / "Microsoft" / "Windows" / "Fonts",
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        home / ".local" / "share" / "fonts",
        home / ".fonts",
        Path("/Library/Fonts"),
        home / "Library" / "Fonts",
    ]
    for folder in folders:
        if not folder.is_dir():
            continue
        found = next(folder.rglob(name), None)
        if found is not None:
            return found
    raise SystemExit(
        f"make_screens: cannot find {name}; install DejaVu Sans Mono, or name "
        "fonts with --font and --bold-font"
    )


def draw(canvas: Canvas, fonts: tuple[Path, Path]) -> "Image":
    """A canvas as a picture: each cell its colours, character and style."""
    # Only drawing needs Pillow, so only drawing imports it.
    # pylint: disable-next=import-outside-toplevel
    from PIL import Image, ImageDraw, ImageFont

    regular, bold = (ImageFont.truetype(str(path), FONT_SIZE) for path in fonts)
    width = round(regular.getlength("M"))
    ascent, descent = regular.getmetrics()
    height = ascent + descent  # box drawing characters join up at this height
    image = Image.new("RGB", (canvas.width * width, canvas.height * height))
    pen = ImageDraw.Draw(image)
    for row in range(canvas.height):
        for column in range(canvas.width):
            draw_cell(
                pen,
                canvas.cell(row, column),
                box=(column * width, row * height, width, height),
                baseline=ascent,
                faces=(regular, bold),
            )
    return image


def draw_cell(
    pen: "ImageDraw.ImageDraw",
    cell: tuple[str, Style],
    *,
    box: tuple[int, int, int, int],
    baseline: int,
    faces: "tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont]",
) -> None:
    """One cell: its background, its character (bold if its style is), and
    an underline, in ``box`` (left, top, width, height)."""
    char, style = cell
    foreground, background = colours(style)
    left, top, width, height = box
    pen.rectangle((left, top, left + width - 1, top + height - 1), fill=background)
    if char != " ":
        font = faces[1] if style.bold else faces[0]
        pen.text((left, top), char, font=font, fill=foreground)
    if style.underline:
        line = top + baseline + 2
        pen.line((left, line, left + width - 1, line), fill=foreground)


# What a picture shows


def screen_data(canvas: Canvas) -> str:
    """What a picture shows, as text: its rows, and their styles (as the
    desktop and its applications send them to each other)."""
    table = StyleTable()
    rows = [
        encode_row([canvas.cell(row, column) for column in range(canvas.width)], table)
        for row in range(canvas.height)
    ]
    data = {"size": [canvas.width, canvas.height], "styles": table.styles}
    return json.dumps({**data, "rows": rows}, ensure_ascii=False, indent=1)


def read_screen_data(path: Path) -> str | None:
    """What a PNG ``make_screens`` wrote shows (``screen_data``), read with
    the standard library alone; ``None`` if it holds none."""
    data = path.read_bytes()
    position = 8  # after the PNG signature
    while position < len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        kind = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        position += 12 + length
        if kind != b"iTXt":
            continue
        keyword, _, rest = body.partition(b"\0")
        if keyword.decode("latin-1") != DATA_KEY:
            continue
        compressed = rest[0] == 1
        _language, _, rest = rest[2:].partition(b"\0")
        _translated, _, text = rest.partition(b"\0")
        return (zlib.decompress(text) if compressed else text).decode("utf-8")
    return None


def write_png(path: Path, canvas: Canvas, fonts: tuple[Path, Path]) -> None:
    """Draw a canvas into a PNG, with what it shows (``screen_data``)."""
    # pylint: disable-next=import-outside-toplevel
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_itxt(DATA_KEY, screen_data(canvas), zip=True)
    draw(canvas, fonts).save(path, pnginfo=info, optimize=True)


# Running the steps


class Stop(Exception):
    """The keys have all been pressed."""


class ScriptedTerminal:
    """Stands in for the terminal: the keys from a script, and a picture of
    the screen at each ``SNAP``."""

    def __init__(self, application: Application, keys: list[object]) -> None:
        self.application = application
        self.keys = keys
        self.screen_size = (80, 24)
        self.output = StringIO()
        self.pictures: list[Canvas] = []

    def size(self) -> tuple[int, int]:
        """The screen's size, as a terminal reports it."""
        return self.screen_size

    def write(self, text: str) -> None:
        """Output is not needed: the pictures come from the screen itself."""
        self.output.write(text)

    def flush(self) -> None:
        """Nothing to flush."""

    def read(self, timeout: float | None = None) -> str:
        """The next key, after taking any pictures due first."""
        del timeout
        while self.keys and self.keys[0] is SNAP:
            self.keys.pop(0)
            self.pictures.append(self.picture())
        if not self.keys:
            raise Stop
        return cast(str, self.keys.pop(0))

    def picture(self) -> Canvas:
        """The screen as it is."""
        manager = self.application.manager
        assert manager is not None
        canvas = Canvas(*self.screen_size)
        manager.compose(canvas)
        return canvas


def load(step: str) -> Callable[..., Application]:
    """The application class a step's file defines (Notepad takes the files
    to open from step 5 on)."""
    path = (FOLDER / step).resolve()
    name = f"tutorial_{path.stem}"  # apart from any other "notepad"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    found: Callable[..., Application] = module.Notepad
    return found


@contextmanager
def example_folder() -> Iterator[str]:
    """A folder of example files to run in, shown as ``SHOWN_FOLDER``."""
    before = os.getcwd()
    # pylint: disable=protected-access
    show = FileDialog._show_directory
    with tempfile.TemporaryDirectory() as root:
        folder = os.path.join(os.path.realpath(root), "notes")
        os.makedirs(os.path.join(folder, "letters"))
        for name, text in FILES.items():
            path = os.path.join(folder, name)
            with open(path, "w", encoding="utf-8", newline="") as file:
                file.write(text)

        def shown(dialog: FileDialog) -> None:
            """The dialog's folder line, the example folder renamed."""
            directory = dialog.directory
            dialog.directory = directory.replace(folder, SHOWN_FOLDER)
            show(dialog)
            dialog.directory = directory

        FileDialog._show_directory = shown  # type: ignore[method-assign,assignment]
        os.chdir(folder)
        try:
            yield folder
        finally:
            os.chdir(before)
            FileDialog._show_directory = show  # type: ignore[method-assign]


def take(step: str, arguments: list[str], keys: list[object]) -> Canvas:
    """Run a step, press its keys, and picture the screen at the end."""
    application = load(step)(arguments) if arguments else load(step)()
    script = [KEYS.get(key, key) if isinstance(key, str) else key for key in keys]
    terminal = ScriptedTerminal(application, [*script, SNAP])
    try:
        application.run(cast(Terminal, terminal))
    except Stop:
        pass
    return terminal.pictures[-1]


def screens() -> dict[str, Canvas]:
    """Every screen, by name."""
    with example_folder():
        return {
            name: take(step, arguments, keys)
            for name, (step, arguments, keys) in SHOTS.items()
        }


def main(argv: Sequence[str] | None = None) -> None:
    """Draw the screens."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--font", type=Path, help="the regular font to draw with")
    parser.add_argument("--bold-font", type=Path, help="the bold font")
    args = parser.parse_args(argv)
    fonts = (
        args.font or find_font(FONTS[0]),
        args.bold_font or args.font or find_font(FONTS[1]),
    )
    SCREENS.mkdir(exist_ok=True)
    for name, canvas in screens().items():
        path = SCREENS / f"{name}.png"
        write_png(path, canvas, fonts)
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
