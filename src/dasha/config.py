"""Reading the user's JSON settings files (shortcuts, colours), and
writing files safely (``write_atomically``)."""

import json
import os
import stat
import tempfile
from pathlib import Path

_WINDOWS = os.name == "nt"
"""Whether files are written by Windows' rules (a file held open by another
program cannot be replaced)."""


class ConfigError(ValueError):
    """A settings file could not be used; the message explains why."""


def read_json_object(path: Path) -> dict[str, object] | None:
    """Read a JSON object from ``path``, or return ``None`` if the file does
    not exist.

    The file can be UTF-8 (with or without a byte order mark) or UTF-16,
    which is what Windows PowerShell 5.1 writes with ``>``. Raises
    ``ConfigError`` if the file cannot be read, is not valid JSON, or does
    not contain a JSON object.
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
    """Write a text file whole, or not at all, so that a failure part-way
    (a full disk, a drive going away, the process being killed) leaves the
    file as it was rather than empty or cut short.

    The text goes to a temporary file in the same folder, which is flushed
    to the disk and then put in the file's place in one step
    (``os.replace``). The file keeps its permissions, and a symbolic link is
    written through, to the file it points to. On Windows, a file that
    another program holds open cannot be replaced; it is then written in
    place, as before, once the text has been written safely beside it.
    ``newline`` is as for ``open``. Raises ``OSError`` if the file cannot
    be written; the temporary file is then removed.
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
