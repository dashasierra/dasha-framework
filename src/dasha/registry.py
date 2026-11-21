"""Installed applications and desktop settings."""

import hashlib
import json
import os
import re
import shutil
import tempfile
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import dasha
from dasha.application import Application
from dasha.config import write_atomically
from dasha.style import COLOUR_DEPTHS

SETTINGS_FOLDER = Path.home() / ".dasha"
"""Dasha Framework's settings folder.

:meta hide-value:
"""
MANIFEST_FOLDER = SETTINGS_FOLDER / "apps"
"""Folder of application manifests.

:meta hide-value:
"""
VENV_FOLDER = SETTINGS_FOLDER / "venvs"
"""Folder of created virtual environments.

:meta hide-value:
"""
LEND_FOLDER = SETTINGS_FOLDER / "lend"
"""Folder of lent copies of Dasha Framework.

:meta hide-value:
"""
SETTINGS_PATH = SETTINGS_FOLDER / "settings.toml"
"""The desktop settings file.

:meta hide-value:
"""

_KEYS = ("name", "module", "class", "script", "venv", "group", "single_instance")


class ManifestError(ValueError):
    """An unusable manifest or settings file."""


@dataclass(frozen=True)
class AppEntry:  # pylint: disable=too-many-instance-attributes
    """An application that the desktop can start."""

    id: str
    """Command-line id."""
    name: str
    """The name shown for the application in the Applications menu."""
    target: str
    """What is run."""
    venv: str | None = None
    """Virtual environment folder, if any."""
    single_instance: bool = False
    """Whether only one copy may run."""
    group: str = ""
    """Applications submenu, or ""."""
    application: type[Application] | None = None
    """The application class, if importable."""
    manifest: Path | None = None
    """The manifest file the entry came from, if it was installed."""

    @classmethod
    def of(cls, application: type[Application], id_: str | None = None) -> "AppEntry":
        """The entry for an application class.

        :param application: The class.
        :param id_: Its id, or ``None`` to derive one.
        """
        return cls(
            id=id_ or slug(application.name),
            name=application.name,
            target=f"{application.__module__}:{application.__qualname__}",
            single_instance=application.single_instance,
            application=application,
        )

    @property
    def is_script(self) -> bool:
        """Whether the entry runs a script file rather than a module."""
        return is_script(self.target)


DESKTOP_ID = "desktop"
"""The id no application can have, as ``dasha desktop`` starts the desktop."""


def reserved_id_problem(app_id: str) -> str | None:
    """Why an id is reserved, or ``None``.

    :param app_id: The id.
    """
    if app_id == DESKTOP_ID:
        return (
            f'"{DESKTOP_ID}" cannot be an application\'s id, as '
            f"dasha {DESKTOP_ID} starts the desktop"
        )
    return None


def slug(text: str) -> str:
    """An id made from a name.

    :param text: The name.
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "app"


def is_script(target: str) -> bool:
    """Whether a target names a script.

    :param target: The target.
    """
    return target.endswith(".py") or ".py:" in target


def split_script(target: str) -> tuple[str, str | None]:
    """A script target's path and class name.

    :param target: The target.
    """
    if target.endswith(".py"):
        return target, None
    path, _, class_name = target.rpartition(":")
    return path, class_name or None


# Manifests


def read_manifest(path: Path) -> AppEntry:
    """Read a manifest.

    :param path: The manifest.
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ManifestError(f"{path.name}: {error}") from error
    problems = [f'unknown setting "{key}"' for key in data if key not in _KEYS]
    for key in ("name", "module", "class", "script", "venv", "group"):
        if key in data and not isinstance(data[key], str):
            problems.append(f'"{key}" must be a string')
    if not isinstance(data.get("single_instance", False), bool):
        problems.append('"single_instance" must be true or false')
    if not data.get("name"):
        problems.append('"name" is missing')
    module, class_name, script = (
        data.get("module"),
        data.get("class"),
        data.get("script"),
    )
    target = ""
    if bool(module) == bool(script):
        problems.append('give "module" (with "class") or "script", not both')
    elif module:
        if not class_name:
            problems.append('"module" needs a "class"')
        target = f"{module}:{class_name}"
    else:
        script_path = Path(str(script)).expanduser()
        target = str(script_path) + (f":{class_name}" if class_name else "")
    if problems:
        raise ManifestError(
            "\n".join(f"{path.name}: {problem}" for problem in problems)
        )
    venv = data.get("venv")
    return AppEntry(
        id=path.stem,
        name=str(data["name"]),
        target=target,
        venv=str(Path(venv).expanduser()) if venv else None,
        single_instance=bool(data.get("single_instance", False)),
        group=str(data.get("group", "")),
        manifest=path,
    )


def load_manifests(folder: Path = MANIFEST_FOLDER) -> tuple[list[AppEntry], list[str]]:
    """Installed applications and manifest problems.

    :param folder: The manifest folder.
    """
    entries: list[AppEntry] = []
    problems: list[str] = []
    if not folder.is_dir():
        return entries, problems
    for path in sorted(folder.glob("*.toml")):
        try:
            entries.append(read_manifest(path))
        except ManifestError as error:
            problems.extend(str(error).splitlines())
    return entries, problems


def _toml_string(text: str) -> str:
    # A JSON string is a TOML basic string, escapes and all.
    return json.dumps(text, ensure_ascii=False)


def manifest_text(entry: AppEntry) -> str:
    """A manifest file's text.

    :param entry: The application.
    """
    lines = [f"name = {_toml_string(entry.name)}"]
    if entry.is_script:
        path, class_name = split_script(entry.target)
        lines.append(f"script = {_toml_string(path)}")
    else:
        module, _, class_name = entry.target.partition(":")
        lines.append(f"module = {_toml_string(module)}")
    if class_name:
        lines.append(f"class = {_toml_string(class_name)}")
    if entry.venv:
        lines.append(f"venv = {_toml_string(entry.venv)}")
    if entry.group:
        lines.append(f"group = {_toml_string(entry.group)}")
    if entry.single_instance:
        lines.append("single_instance = true")
    return "\n".join(lines) + "\n"


def write_manifest(entry: AppEntry, folder: Path = MANIFEST_FOLDER) -> Path:
    """Write a manifest; return its path.

    :param entry: The application.
    :param folder: The manifest folder.
    """
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{entry.id}.toml"
    write_atomically(path, manifest_text(entry), newline="\n")
    return path


# Desktop settings


_SETTINGS_KEYS = (
    "animations",
    "autostart",
    "colour_depth",
    "escape_timeout",
    "show_mouse",
    "theme",
)

ESCAPE_TIMEOUT = 100
"""Default milliseconds to wait after a lone ESC."""
ESCAPE_TIMEOUT_RANGE = range(10, 2001)
"""The waits that ``escape_timeout`` may be, in milliseconds."""


def _read_settings(path: Path) -> dict[str, object]:
    """The settings file's contents.

    :param path: The settings file.
    """
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ManifestError(f"{path.name}: {error}") from error
    unknown = [key for key in data if key not in _SETTINGS_KEYS]
    if unknown:
        raise ManifestError(f'{path.name}: unknown setting "{unknown[0]}"')
    return data


def read_autostart(path: Path = SETTINGS_PATH) -> list[str]:
    """Application ids to autostart.

    :param path: The settings file.
    """
    autostart = _read_settings(path).get("autostart", [])
    if not isinstance(autostart, list) or not all(
        isinstance(i, str) for i in autostart
    ):
        raise ManifestError(f'{path.name}: "autostart" must be a list of names')
    return list(autostart)


def read_theme_setting(path: Path = SETTINGS_PATH) -> str | None:
    """The saved theme, or ``None``.

    :param path: The settings file.
    """
    name = _read_settings(path).get("theme")
    if name is not None and (not isinstance(name, str) or not name):
        raise ManifestError(f'{path.name}: "theme" must be the name of a theme')
    return name


def save_theme_setting(name: str | None, path: Path = SETTINGS_PATH) -> None:
    """Save the theme setting.

    :param name: Theme name, or ``None`` to forget it.
    :param path: The settings file.
    """
    _save_setting("theme", None if name is None else _toml_string(name), path)


def save_autostart_setting(ids: Sequence[str], path: Path = SETTINGS_PATH) -> None:
    """Save the autostart setting.

    :param ids: Application ids.
    :param path: The settings file.
    """
    value = "[" + ", ".join(_toml_string(app_id) for app_id in ids) + "]"
    _save_setting("autostart", value if ids else None, path)


def read_animations_setting(path: Path = SETTINGS_PATH) -> bool:
    """Whether animations start on.

    :param path: The settings file.
    """
    animations = _read_settings(path).get("animations", True)
    if not isinstance(animations, bool):
        raise ManifestError(f'{path.name}: "animations" must be true or false')
    return animations


def save_animations_setting(on: bool, path: Path = SETTINGS_PATH) -> None:
    """Save the animations setting.

    :param on: Whether animations are on.
    :param path: The settings file.
    """
    _save_setting("animations", None if on else "false", path)


def read_show_mouse_setting(path: Path = SETTINGS_PATH) -> bool:
    """Whether the mouse cell is shown.

    :param path: The settings file.
    """
    show = _read_settings(path).get("show_mouse", False)
    if not isinstance(show, bool):
        raise ManifestError(f'{path.name}: "show_mouse" must be true or false')
    return show


def save_show_mouse_setting(on: bool, path: Path = SETTINGS_PATH) -> None:
    """Save the show-mouse setting.

    :param on: Whether it is shown.
    :param path: The settings file.
    """
    _save_setting("show_mouse", "true" if on else None, path)


def read_escape_timeout_setting(path: Path = SETTINGS_PATH) -> int:
    """Milliseconds to wait after a lone ESC.

    :param path: The settings file.
    """
    wait = _read_settings(path).get("escape_timeout", ESCAPE_TIMEOUT)
    if isinstance(wait, bool) or wait not in ESCAPE_TIMEOUT_RANGE:
        raise ManifestError(
            f'{path.name}: "escape_timeout" must be a number of milliseconds, '
            f"{ESCAPE_TIMEOUT_RANGE.start} to {ESCAPE_TIMEOUT_RANGE.stop - 1}"
        )
    assert isinstance(wait, int)
    return wait


def save_escape_timeout_setting(wait: int, path: Path = SETTINGS_PATH) -> None:
    """Save the ESC wait setting.

    :param wait: Milliseconds.
    :param path: The settings file.
    """
    _save_setting("escape_timeout", None if wait == ESCAPE_TIMEOUT else str(wait), path)


def read_colour_depth_setting(path: Path = SETTINGS_PATH) -> str:
    """The saved colour depth, or ``"auto"``.

    :param path: The settings file.
    """
    depth = _read_settings(path).get("colour_depth", "auto")
    if depth not in COLOUR_DEPTHS:
        raise ManifestError(
            f'{path.name}: "colour_depth" must be "auto", "16", "256" or "24bit"'
        )
    assert isinstance(depth, str)
    return depth


def save_colour_depth_setting(depth: str, path: Path = SETTINGS_PATH) -> None:
    """Save the colour depth setting.

    :param depth: The depth.
    :param path: The settings file.
    """
    _save_setting(
        "colour_depth", None if depth == "auto" else _toml_string(depth), path
    )


def _save_setting(key: str, value: str | None, path: Path) -> None:
    """Set one top-level setting.

    :param key: Setting name.
    :param value: TOML value, or ``None`` to remove it.
    :param path: The settings file.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    kept = [line for line in lines if not re.match(rf"\s*{key}\s*=", line)]
    if value is not None:
        # A top-level setting: before any [table], where TOML puts them.
        at = next(
            (n for n, line in enumerate(kept) if line.lstrip().startswith("[")),
            len(kept),
        )
        kept.insert(at, f"{key} = {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomically(path, "".join(f"{line}\n" for line in kept))


# Virtual environments


def venv_python(venv: str | Path) -> Path:
    """A virtual environment's Python.

    :param venv: The environment folder.
    """
    folder = Path(venv)
    if os.name == "nt":
        return folder / "Scripts" / "python.exe"
    return folder / "bin" / "python"


def _site_packages(venv: Path) -> Iterable[Path]:
    yield venv / "Lib" / "site-packages"
    yield from (venv / "lib").glob("python*/site-packages")


def venv_has_dasha(venv: str | Path) -> bool:
    """Whether a virtual environment has Dasha Framework.

    :param venv: The environment folder.
    """
    for folder in _site_packages(Path(venv)):
        if folder.is_dir() and any("dasha" in p.name for p in folder.iterdir()):
            return True
    return False


def lend_folder(base: Path = LEND_FOLDER) -> Path:
    """A folder with only this Dasha Framework version.

    :param base: Parent folder.
    """
    package = Path(dasha.__file__).resolve().parent
    files = sorted(
        path
        for path in package.rglob("*")
        if path.is_file() and path.suffix != ".pyc" and "__pycache__" not in path.parts
    )
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(package).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    folder = base / f"{dasha.__version__}-{digest.hexdigest()[:12]}"
    if not (folder / "dasha").is_dir():
        base.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=base))
        shutil.copytree(
            package, staging / "dasha", ignore=shutil.ignore_patterns("__pycache__")
        )
        try:
            staging.rename(folder)
        except OSError:  # another desktop made it first
            shutil.rmtree(staging, ignore_errors=True)
    return folder
