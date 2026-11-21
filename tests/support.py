"""Helpers shared by the tests."""

import atexit
import os
import re
import shutil
import sys
import tempfile
import unittest
from collections.abc import Callable
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from multiprocessing import Pipe
from multiprocessing.connection import Connection
from typing import TYPE_CHECKING, cast
from unittest import mock

from dasha import logs
from dasha.canvas import Canvas
from dasha.processes import DESKTOP_PID_VARIABLE
from dasha.protocol import ADDRESS_VARIABLE
from dasha.shell import SUSPENDED_VARIABLE
from dasha.style import NO_COLOUR_TERMINALS
from dasha.window import Window

if TYPE_CHECKING:
    from dasha.hosting import AppHost, AppServer
    from dasha.manager import PresentationManager

# What would change how Dasha Framework behaves in ways no test asks for: taken out
# of the environment, so that the tests pass whatever they are run from (a
# terminal with NO_COLOR set, or a desktop's command prompt). A test that wants
# one sets it for itself. Here, not in tests/__init__.py: an application the
# tests start imports that too (tests.hosted_apps), and needs its address.
for _name in ("NO_COLOR", ADDRESS_VARIABLE, DESKTOP_PID_VARIABLE, SUSPENDED_VARIABLE):
    os.environ.pop(_name, None)
if os.environ.get("TERM", "").lower() in NO_COLOUR_TERMINALS:
    os.environ["TERM"] = "xterm"

# An application running on its own logs what goes wrong where the system
# keeps programs' logs (logs.app_log_folder). While the tests run, that is a
# folder of their own instead, deleted afterwards, so that no test leaves a
# log in the developer's own folders. The real one is kept, to be tested.
real_app_log_folder = logs.app_log_folder
"""``dasha.logs.app_log_folder`` itself, which the tests replace."""
_TEST_LOGS = Path(tempfile.mkdtemp(prefix="standalone-logs-"))
atexit.register(shutil.rmtree, _TEST_LOGS, True)


def _test_log_folder(name: str) -> Path:
    """The tests' stand-in for ``logs.app_log_folder``.

    :param name: Application name.
    """
    return _TEST_LOGS / logs.log_name(name) / "logs"


setattr(logs, "app_log_folder", _test_log_folder)

_STYLE = re.compile(r"\x1b\[[0-9;]*m")

ROOT = Path(__file__).resolve().parents[1]
"""The repository's root, where ``tests`` can be imported from."""

HOSTED_APPS = ROOT / "tests" / "hosted_apps.py"
"""The applications the tests start, as a script."""


def pipe() -> tuple[Connection, Connection]:
    """Two connected ends (typed as plain connections on every system)."""
    here, there = Pipe()
    # Needed on Windows only, where Pipe may give PipeConnections.
    return (
        cast(Connection, here),  # type: ignore[redundant-cast,unused-ignore]
        cast(Connection, there),  # type: ignore[redundant-cast,unused-ignore]
    )


def hosted(server: "AppServer", name: str) -> tuple["AppHost", Connection]:
    """A connected application and its pipe end.

    :param server: The application server.
    :param name: Application name.
    """
    # pylint: disable-next=import-outside-toplevel
    from dasha.hosting import AppHost

    host = AppHost(server, "x:Y", name)
    here, there = pipe()
    host.connected(there)
    server.hosts.append(host)
    server.manager.add_application(host.application)
    return host, here


def isolated_home(case: unittest.TestCase) -> Path:
    """Use an empty settings folder for a test; return it.

    :param case: The test.
    """
    # pylint: disable=import-outside-toplevel
    import dasha.__main__
    from dasha import registry, style, theme

    folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
    case.addCleanup(folder.cleanup)
    home = Path(folder.name)
    saved = theme.current_theme()
    case.addCleanup(theme.apply_theme, saved)
    case.addCleanup(setattr, style, "DRAWN_DEPTH", style.DRAWN_DEPTH)
    for patch in (
        mock.patch.object(registry, "SETTINGS_PATH", home / "settings.toml"),
        mock.patch.object(registry, "MANIFEST_FOLDER", home / "apps"),
        mock.patch.object(theme, "DEFAULT_PATH", home / "colours.json"),
        mock.patch.object(theme, "THEMES_FOLDER", home / "themes"),
        mock.patch.object(dasha.__main__, "DEFAULT_PATH", home / "shortcuts.json"),
    ):
        patch.start()
        case.addCleanup(patch.stop)
    return home


def serving(case: unittest.TestCase, manager: "PresentationManager") -> "AppServer":
    """A server for a desktop, shut down after the test.

    :param case: The test.
    :param manager: The desktop.
    """
    # pylint: disable-next=import-outside-toplevel
    from dasha.hosting import AppServer

    server = AppServer(manager)
    manager.server = server
    case.addCleanup(server.stop_all, 0)
    return server


def started_desktop(*arguments: str) -> tuple[int, mock.MagicMock, str]:
    """Run ``dasha desktop`` (see ``started``).

    :param arguments: Command-line arguments.
    """
    # pylint: disable=import-outside-toplevel
    from dasha.__main__ import main

    return started(main, ["desktop", *arguments])


def started(
    command: Callable[[list[str]], int], arguments: list[str]
) -> tuple[int, mock.MagicMock, str]:
    """Run a command line with a mock desktop.

    :param command: The entry point.
    :param arguments: Command-line arguments.
    """
    terminal = mock.MagicMock()
    terminal.isatty.return_value = True
    errors = StringIO()
    with (
        mock.patch("dasha.__main__.Terminal"),
        mock.patch("dasha.__main__._desktop") as desktop,
        mock.patch.object(sys, "stdin", terminal),
        mock.patch.object(sys, "stdout", terminal),
        redirect_stderr(errors),
    ):
        desktop.return_value.recovery = None  # nothing went wrong in it
        code = command(arguments)
    return code, desktop, errors.getvalue()


def tests_importable(case: unittest.TestCase) -> None:
    """Let child processes import the tests' modules.

    :param case: The test.
    """
    paths = [str(ROOT), os.environ.get("PYTHONPATH", "")]
    patch = mock.patch.dict(
        os.environ, {"PYTHONPATH": os.pathsep.join(path for path in paths if path)}
    )
    patch.start()
    case.addCleanup(patch.stop)


def painted(window: Window) -> Canvas:
    """A window painted on a canvas of its size.

    :param window: The window.
    """
    canvas = Canvas(window.rect.right, window.rect.bottom)
    window.paint(canvas, active=True)
    return canvas


def without_styles(output: str) -> str:
    """Terminal output without style changes.

    :param output: The output.
    """
    return _STYLE.sub("", output)


def assert_lines_shown(test: unittest.TestCase, text: str, output: str) -> None:
    """Check each line of text was drawn.

    :param test: The test.
    :param text: The expected text.
    :param output: The terminal output.
    """
    shown = without_styles(output)
    gap = r"(?: |\x1b\[\d+;\d+H)+"
    for line in text.splitlines():
        if line.strip():
            pattern = gap.join(re.escape(word) for word in line.split())
            test.assertRegex(shown, pattern, f"line {line!r} not on screen")
