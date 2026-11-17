"""The entry point of a PyInstaller build of dasha (see ``dasha.spec``).

A built dasha has no Python interpreter beside it: ``sys.executable`` is the
dasha program itself. The desktop starts each application in a process of
its own as ``sys.executable -P -m dasha.host TARGET``, which a Python
interpreter understands but the dasha command line does not. So here,
in the built program only, ``-m dasha.host`` (after ``-P``, if given) is
taken as Python takes it; anything else is the dasha command line, as
``python -m dasha``.

This is what runs an application that has no virtual environment of its
own: the desktop then runs it with its own program, which for a build is
dasha itself.

A copy of the program named ``dasha-desktop`` (``dasha-desktop.exe`` on Windows) is
the ``dasha-desktop`` command, ``dasha desktop``, rather than ``dasha``.
"""

import sys
from pathlib import Path
from collections.abc import Sequence

HOST = ["-m", "dasha.host"]
"""How the desktop asks for an application to be run."""

SAFE_PATH = "-P"
"""Python's option not to put the working folder on the import path, which
the desktop gives before ``-m dasha.host``. A built dasha never puts it
there anyway (its modules come from inside the program), so the option
changes nothing here, and is accepted and passed over."""


DESKTOP_PROGRAM = "dasha-desktop"
"""The program's name (ignoring case and any extension) that makes it the
``dasha-desktop`` command."""


def main(argv: Sequence[str] | None = None, program: str | None = None) -> int:
    """Run an application for the desktop, or else dasha itself: as
    ``dasha-desktop`` if the ``program`` (by default, the one running) is
    called that."""
    args = list(sys.argv[1:] if argv is None else argv)
    program = sys.argv[0] if program is None else program
    command = args[1:] if args[:1] == [SAFE_PATH] else args
    if command[: len(HOST)] == HOST:
        # pylint: disable-next=import-outside-toplevel
        from dasha.host import main as host

        return host(command[len(HOST) :])
    # pylint: disable-next=import-outside-toplevel
    from dasha.__main__ import main as dasha

    return dasha(args, desktop=Path(program).stem.casefold() == DESKTOP_PROGRAM)


if __name__ == "__main__":
    raise SystemExit(main())
