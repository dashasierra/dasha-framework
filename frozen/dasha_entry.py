"""Entry point of a PyInstaller build of dasha."""

import sys
from pathlib import Path
from collections.abc import Sequence

HOST = ["-m", "dasha.host"]
"""How the desktop asks for an application to be run."""

SAFE_PATH = "-P"
"""Python's safe-path option."""


DESKTOP_PROGRAM = "dasha-desktop"
"""Program name that means ``dasha-desktop``."""


def main(argv: Sequence[str] | None = None, program: str | None = None) -> int:
    """Run an application or the dasha command line.

    :param argv: Arguments, or ``None`` for ``sys.argv``.
    :param program: Program name, or ``None`` for the running one.
    """
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
