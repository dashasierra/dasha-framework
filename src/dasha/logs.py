"""Application log files."""

import os
import re
import sys
from pathlib import Path

LOG_FOLDER = Path.home() / ".dasha" / "logs"
"""Folder for application logs.

:meta hide-value:
"""

LOG_TAIL = 8192
"""Bytes read from a log's end for its last line."""

LOG_KEEP = 50
"""Number of logs kept."""


def app_log_folder(name: str) -> Path:
    """Where a stand-alone application keeps its logs.

    :param name: Application name.
    """
    # if/elif/else (not early returns) lets mypy skip other platforms' branches.
    if sys.platform == "win32":  # pylint: disable=no-else-return
        local = os.environ.get("LOCALAPPDATA", "")
        base = (
            Path(local) if os.path.isabs(local) else Path.home() / "AppData" / "Local"
        )
        return base / log_name(name, keep_case=True) / "logs"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / log_name(name, keep_case=True)
    else:
        state = os.environ.get("XDG_STATE_HOME", "")
        # The specification says to ignore a relative path.
        base = Path(state) if os.path.isabs(state) else Path.home() / ".local" / "state"
        return base / log_name(name) / "logs"


def log_name(name: str, *, keep_case: bool = False) -> str:
    """A name made safe for a file name.

    :param name: The name.
    :param keep_case: Whether to keep letter case.
    """
    safe = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-") or "app"
    return safe if keep_case else safe.lower()


def last_line(path: Path) -> str:
    """A log's last line, or "".

    :param path: The log.
    """
    try:
        with open(path, "rb") as log:
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - LOG_TAIL))
            tail = log.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    lines = [line.strip() for line in tail.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def drop_if_empty(path: Path) -> None:
    """Delete a log if empty.

    :param path: The log.
    """
    try:
        if path.stat().st_size == 0:
            path.unlink()
    except OSError:
        pass  # gone already, or still held open


def prune(folder: Path, keep: int = LOG_KEEP) -> None:
    """Delete the oldest logs.

    :param folder: The log folder.
    :param keep: Number to keep.
    """
    try:
        logs = sorted(folder.glob("*.log"), key=lambda path: path.stat().st_mtime)
    except OSError:
        return
    for path in logs[: max(0, len(logs) - keep)]:
        try:
            path.unlink()
        except OSError:
            pass  # in use, or gone already
