"""Settings file reading and safe writing."""

import json
import os
import stat
import tempfile
from pathlib import Path

_WINDOWS = os.name == "nt"
"""Whether Windows file rules apply."""


class ConfigError(ValueError):
    """A settings file could not be used; the message explains why."""


def read_json_object(path: Path) -> dict[str, object] | None:
    """Read a JSON object, or ``None`` if missing.

    :param path: The file.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ConfigError(f"cannot read the file: {error.strerror}") from error
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    try:
        data = json.loads(raw.decode(encoding))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigError(f"not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError("the file must contain a JSON object")
    return data


def write_atomically(
    path: str | Path, text: str, *, encoding: str = "utf-8", newline: str | None = None
) -> None:
    """Write a text file whole or not at all.

    :param path: The file.
    :param text: The text.
    :param encoding: Text encoding.
    :param newline: As for ``open``.
    """
    target = Path(os.path.realpath(path))
    try:
        mode: int | None = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = None
    handle, temporary = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding=encoding, newline=newline) as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        try:
            os.replace(temporary, target)
        except PermissionError:
            if not _WINDOWS:
                raise
            # Held open by another program: write in place after all.
            with open(target, "w", encoding=encoding, newline=newline) as file:
                file.write(text)
            os.unlink(temporary)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass  # replaced already, or never made
        raise
