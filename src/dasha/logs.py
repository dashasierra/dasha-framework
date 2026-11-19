"""The logs of applications running in their own processes. Each
application's standard error goes to a log file in ``LOG_FOLDER``, with a
new file each time it starts.

A log is created as an application starts, to hold whatever it writes. A
log that the application wrote nothing to is deleted once the application
has ended (``drop_if_empty``), and only the newest ``LOG_KEEP`` logs are
kept (``prune``). When an application stops unexpectedly, the desktop
reports it, together with the last line of its log (``last_line``).

An application running on its own keeps the log of what went wrong in it
where its system keeps programs' logs, in a folder named after the
application (``app_log_folder``), so that nothing it shows names Dasha Framework.
"""

import os
import re
import sys
from pathlib import Path

LOG_FOLDER = Path.home() / ".dasha" / "logs"
"""The folder that each application's standard error is written to, with
a new file each time it starts: ``~/.dasha/logs``. The desktop keeps the
log of anything that goes wrong in its own code here too
(``dasha.recovery``).

:meta hide-value:
"""

LOG_TAIL = 8192
"""How many bytes from the end of a log are read to find its last
line."""

LOG_KEEP = 50
"""How many logs are kept; older ones are deleted as more applications
start."""


def app_log_folder(name: str) -> Path:
    """Where an application running on its own, called ``name``, keeps its
    logs: where its system keeps programs' logs, in a folder of its own.
    That is ``%LOCALAPPDATA%\\Notepad\\logs`` on Windows,
    ``~/Library/Logs/Notepad`` on macOS, and ``$XDG_STATE_HOME/notepad/logs``
    elsewhere (``~/.local/state/notepad/logs`` by default), for Notepad."""
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
    """A name made safe to name a file or folder with: only ASCII letters,
    digits and single hyphens, in lower case unless ``keep_case`` (``"Notepad and
    Demo"`` becomes ``"notepad-and-demo"``, or ``"Notepad-and-Demo"``), and
    ``"app"`` if nothing is left."""
    safe = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-") or "app"
    return safe if keep_case else safe.lower()


def last_line(path: Path) -> str:
    """The last line written to a log, read from the end of the log only,
    however much was written. Returns ``""`` if nothing was written, or if
    there is no log."""
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
    """Delete a log that nothing was written to, once its application has
    ended, rather than leaving an empty file behind each time an application
    starts."""
    try:
        if path.stat().st_size == 0:
            path.unlink()
    except OSError:
        pass  # gone already, or still held open


def prune(folder: Path, keep: int = LOG_KEEP) -> None:
    """Delete the oldest logs in ``folder``, keeping the newest ``keep``."""
    try:
        logs = sorted(folder.glob("*.log"), key=lambda path: path.stat().st_mtime)
    except OSError:
        return
    for path in logs[: max(0, len(logs) - keep)]:
        try:
            path.unlink()
        except OSError:
            pass  # in use, or gone already
