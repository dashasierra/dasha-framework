"""Command-line entry point, used by ``python -m dasha`` and the ``dasha``
and ``dasha-desktop`` scripts.

``dasha`` needs to be told what to run: ``dasha desktop`` for the desktop
(with any applications named after it started on it), or applications by
id (``dasha notepad``) to run on their own. ``dasha-desktop`` is ``dasha
desktop``: ``dasha-desktop notepad`` starts the desktop with Notepad on it."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from dasha import __version__, keytest, shell
from dasha import style, theme
from dasha import install, registry
from dasha.config import write_atomically
from dasha.manager import PresentationManager
from dasha.printing import say
from dasha.registry import AppEntry, ManifestError
from dasha.shortcuts import DEFAULT_PATH, Shortcuts, ShortcutsError
from dasha.terminal import Terminal

DESKTOP = registry.DESKTOP_ID
"""What starts the desktop: ``dasha desktop``, followed by any applications
to start on it. No application can have it as its id."""


def _desktop(  # pylint: disable=too-many-arguments
    shortcuts: Shortcuts | None,
    names: Sequence[str],
    *,
    processes: bool = True,
    entries: dict[str, AppEntry] | None = None,
    theme_name: str | None = "default",
    alone: bool = False,
    animations: bool = True,
    paths: tuple[Path, Path] | None = None,
    colour_depth: str = "auto",
    show_mouse: bool = False,
    escape_timeout: int = registry.ESCAPE_TIMEOUT,
) -> PresentationManager:
    """An empty desktop offering the applications Dasha Framework knows (the
    installed ones, unless given ``entries``), with the named
    ones started: each in a process of its own, unless ``processes`` is
    false. ``theme_name`` is the theme it starts with (``None``: the colours
    file's colours), and a theme chosen later is remembered; so is turning
    ``animations`` (on, unless told otherwise) on or off. ``colour_depth``
    is how it draws colours (``style.COLOUR_DEPTHS``), and
    ``show_mouse`` whether it inverts the cell under the mouse, which is
    remembered when it is turned on or off.

    ``alone`` runs just the named applications, as each would run on its
    own (``PresentationManager.stand_alone``): no system menu, and it ends
    when they do. So ``dasha notepad`` is the same as running Notepad's
    script, and ``dasha desktop notepad`` (or ``dasha-desktop notepad``) is
    the desktop with Notepad on it.

    ``paths`` are the shortcuts file and the colours file, to which
    Settings... saves (by default, ``~/.dasha/shortcuts.json`` and
    ``~/.dasha/colours.json``)."""
    if entries is None:
        entries, _ = install.known_applications()
    manager = PresentationManager(shortcuts=shortcuts)
    manager.use_processes = processes
    manager.theme_name = theme_name
    manager.remember_theme = True
    manager.animations = animations
    manager.remember_animations = True
    manager.set_colour_depth(colour_depth)
    manager.show_mouse = show_mouse
    manager.remember_show_mouse = True
    manager.escape_timeout = escape_timeout / 1000
    if paths is not None:
        manager.shortcuts_path, manager.colours_path = paths
    manager.register(entries.values())
    if alone:
        manager.stand_alone(_listed([entries[name].name for name in names]))
    else:
        manager.use_own_help()
    for name in names:
        manager.start(entries[name])
    return manager


def _listed(names: Sequence[str]) -> str:
    """Names as a sentence lists them: "Notepad", "Notepad and Demo",
    "Notepad, Demo and Clock"."""
    if len(names) < 2:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _find(name: str, entries: dict[str, AppEntry]) -> list[str]:
    """The ids of the applications that ``name``, given on the command line,
    means: the one with that id; failing that, the one whose id it is in
    another case (``NOTEPAD``); failing that, those that are called it,
    ignoring case (``git``, for an application ``dasha-github`` called
    "Git"). More than one is a name too many applications have; none, a
    name no application has."""
    if name in entries:
        return [name]
    wanted = name.casefold()
    by_id = [app_id for app_id in entries if app_id.casefold() == wanted]
    if by_id:
        return by_id
    return [
        app_id for app_id, entry in entries.items() if entry.name.casefold() == wanted
    ]


def _startup(
    names: Sequence[str], *, desktop: bool = False
) -> tuple[dict[str, AppEntry], list[str]] | None:
    """The applications Dasha Framework knows, and the ids of those to start:
    the ones named, by id or by name (``_find``), and, for the ``desktop``,
    first those listed in ``autostart`` in the settings (an application
    that is both named and listed there is started once). Manifests with
    problems are reported and left out. An unknown name, a name that more
    than one application has, or a settings file that cannot be read is
    reported and gives ``None``, as does starting inside the command prompt
    of a desktop that is already running (see ``dasha.shell``)."""
    if os.environ.get(shell.SUSPENDED_VARIABLE):
        say(
            "dasha: Dasha Framework is already running in this terminal; "
            "type exit to return to it",
            file=sys.stderr,
        )
        return None
    entries, problems = install.known_applications()
    for problem in problems:
        say(f"dasha: {problem} (left out)", file=sys.stderr)
    try:
        autostart = registry.read_autostart(registry.SETTINGS_PATH) if desktop else []
    except ManifestError as error:
        say(f"dasha: {error}", file=sys.stderr)
        return None
    unknown = [name for name in autostart if name not in entries]
    ids: list[str] = []
    for name in names:
        found = _find(name, entries)
        if len(found) > 1:
            say(
                f'dasha: more than one application is called "{name}" '
                f"({', '.join(found)}); name one by its id",
                file=sys.stderr,
            )
            return None
        if found:
            ids.append(found[0])
        else:
            unknown.append(name)
    if unknown:
        known = ", ".join(entries) or "none are installed"
        say(
            f"dasha: no application called {', '.join(unknown)} "
            f"(there are: {known}; see dasha list-apps)",
            file=sys.stderr,
        )
        return None
    return entries, [*autostart, *(app_id for app_id in ids if app_id not in autostart)]


def _parse_arguments(
    argv: Sequence[str] | None, *, desktop: bool = False
) -> argparse.Namespace:
    """The command line, as ``dasha`` (or, if ``desktop``, as ``dasha-desktop``)
    takes it. ``apps`` are the applications to start, and ``desktop``
    whether to start them on the desktop. With nothing to run, the usage is
    shown and the program ends (``SystemExit``), as for any mistake in the
    arguments."""
    parser = argparse.ArgumentParser(
        prog="dasha-desktop" if desktop else "dasha",
        description="Dasha Framework - a text-mode desktop and application framework.",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"Dasha Framework {__version__}"
    )
    parser.add_argument(
        "-s",
        "--shortcuts",
        type=Path,
        metavar="FILE",
        help=f"keyboard shortcuts file (default: {DEFAULT_PATH})",
    )
    parser.add_argument(
        "--init-shortcuts",
        action="store_true",
        help="write the default shortcuts to the shortcuts file, ready to edit",
    )
    parser.add_argument(
        "-c",
        "--colours",
        type=Path,
        metavar="FILE",
        help=f"colours file (default: {theme.DEFAULT_PATH})",
    )
    parser.add_argument(
        "--init-colours",
        action="store_true",
        help="write the default colours to the colours file, ready to edit",
    )
    parser.add_argument(
        "--init-theme",
        metavar="NAME",
        help=f"write a new theme, NAME, to edit: a file in {theme.THEMES_FOLDER}, "
        "offered by the system menu's Themes",
    )
    parser.add_argument(
        "--monochrome",
        action="store_true",
        help="use no colours, only bold, underline and reverse video "
        "(also chosen by the NO_COLOR environment variable)",
    )
    parser.add_argument(
        "-d",
        "--colour-depth",
        choices=style.COLOUR_DEPTHS,
        help="draw RGB colours as they are (24bit), as the nearest of 256 "
        "colours (256), every colour as the nearest of the 16 standard "
        "colours (16), or as the terminal seems to allow (auto, the default); "
        "remembered for next time",
    )
    parser.add_argument(
        "-m",
        "--show-mouse",
        action="store_true",
        help="show where the mouse is by inverting the cell under it, for "
        "terminals that show no pointer; remembered for next time (Alt+` "
        "turns it on and off)",
    )
    parser.add_argument(
        "-k",
        "--key-test",
        action="store_true",
        help="show the name of each key as you press it (Ctrl+C to finish)",
    )
    if desktop:
        apps_help = (
            "applications, by id or name, to start on the desktop, after those "
            "that start with it (dasha list-apps lists them)"
        )
    else:
        apps_help = (
            f"{DESKTOP} for the desktop, followed by any applications to start "
            "on it; or applications, by id or name, to run on their own with no "
            "desktop around them (dasha list-apps lists them)"
        )
    parser.add_argument("apps", nargs="*", metavar="APP", help=apps_help)
    parser.epilog = (
        "The desktop: dasha desktop [APP ...], or dasha-desktop [APP ...]. "
        "Applications: dasha install-app, uninstall-app and list-apps "
        "(each with --help)."
    )
    # Intermixed, so that options may come between applications, as in
    # "dasha desktop --monochrome notepad".
    args = parser.parse_intermixed_args(argv)
    args.desktop = desktop
    if args.apps[:1] == [DESKTOP]:
        args.desktop, args.apps = True, args.apps[1:]
    runs_nothing = (
        args.key_test
        or args.init_shortcuts
        or args.init_colours
        or args.init_theme is not None
    )
    if not (args.desktop or args.apps or runs_nothing):
        parser.error(
            f"the following arguments are required: APP ({DESKTOP} for the "
            "desktop, or an application's id or name: dasha list-apps lists them)"
        )
    return args


def _write_new_file(path: Path, text: str, what: str) -> int:
    """Write a settings file for the user to edit, never overwriting one."""
    if path.exists():
        say(f"dasha: {path} already exists; not overwriting it", file=sys.stderr)
        return 1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomically(path, text + "\n")
    except OSError as error:
        say(f"dasha: cannot write {path}: {error.strerror}", file=sys.stderr)
        return 1
    say(f"Wrote the default {what} to {path}")
    return 0


def _report_problems(kind: str, path: Path, error: Exception) -> None:
    """Explain why a settings file cannot be used."""
    say(f"dasha: cannot use the {kind} file {path}:", file=sys.stderr)
    for problem in str(error).splitlines():
        say(f"  - {problem}", file=sys.stderr)
    say(f"Fix the file, or move it aside to use the default {kind}.", file=sys.stderr)


class _Reported(Exception):
    """A settings problem, already reported to the user."""


def _saved_theme() -> tuple[theme.Theme, str] | None:
    """The theme last chosen from the system menu (``theme`` in the
    settings), if one is remembered. Raises ``_Reported`` once it has said
    why it cannot be used."""
    try:
        name = registry.read_theme_setting(registry.SETTINGS_PATH)
    except ManifestError as error:
        say(f"dasha: {error}", file=sys.stderr)
        raise _Reported from error
    if name is None:
        return None
    try:
        return theme.load_named_theme(name), name
    except theme.ThemeError as error:
        say(
            f'dasha: cannot use the theme "{name}" named in '
            f"{registry.SETTINGS_PATH}:\n  - {error}\n"
            "Choose another from the system menu's Themes, or take the "
            "theme line out of the settings.",
            file=sys.stderr,
        )
        raise _Reported from error


def _load_colours(  # pylint: disable=too-many-return-statements
    path: Path, explicit: bool, monochrome: bool
) -> tuple[theme.Theme, str | None] | None:
    """The colours to start with, and the theme's name (``None`` for the
    colours file's), or ``None`` after reporting why they cannot be used.

    ``--monochrome``, ``NO_COLOR``, or a terminal with no colours, comes
    first, and is the Monochrome theme exactly, as the Themes menu gives it:
    a colours file's changes are left out, as they may well add colours.
    Then come the file given with ``--colours``, the theme last chosen from
    the system menu (``theme`` in the settings), the colours file, and
    finally the default theme. The theme chosen last stays in the settings,
    for when ``NO_COLOR`` is no longer set."""
    if explicit and not path.exists():
        say(f"dasha: colours file {path} does not exist", file=sys.stderr)
        return None
    if monochrome or theme.no_colour_set() or not style.terminal_has_colours():
        return theme.load_named_theme("monochrome"), "monochrome"
    try:
        saved = None if explicit else _saved_theme()
    except _Reported:
        return None
    if saved is not None:
        return saved  # the colours file is not needed, nor read
    try:
        colours = theme.load_theme(path)
    except theme.ThemeError as error:
        _report_problems("colours", path, error)
        return None
    if path.exists():
        return colours, None
    return colours, "default"


def _load_shortcuts(path: Path, explicit: bool) -> Shortcuts | None:
    """Load the shortcuts file, or report why it cannot be used."""
    if explicit and not path.exists():
        say(f"dasha: shortcuts file {path} does not exist", file=sys.stderr)
        return None
    try:
        return Shortcuts.load(path)
    except ShortcutsError as error:
        _report_problems("shortcuts", path, error)
        return None


def _load_settings(
    args: argparse.Namespace, shortcuts_path: Path, colours_path: Path
) -> tuple[Shortcuts | None, tuple[theme.Theme, str | None]] | None:
    """The shortcuts (not needed for the key test) and the colour theme
    with its name, or ``None`` after reporting why a settings file cannot
    be used."""
    shortcuts = None
    if not args.key_test:
        shortcuts = _load_shortcuts(shortcuts_path, explicit=args.shortcuts is not None)
        if shortcuts is None:
            return None
    colours = _load_colours(
        colours_path, explicit=args.colours is not None, monochrome=args.monochrome
    )
    if colours is None:
        return None
    return shortcuts, colours


def _remember_options(args: argparse.Namespace) -> None:
    """Keep ``--colour-depth`` and ``--show-mouse`` in the settings, as
    Settings... does, so they need not be given every time
    (``--colour-depth auto`` forgets the depth). A settings file that
    cannot be written is reported, and Dasha Framework starts anyway."""
    try:
        if args.colour_depth is not None:
            registry.save_colour_depth_setting(
                args.colour_depth, registry.SETTINGS_PATH
            )
        if args.show_mouse:
            registry.save_show_mouse_setting(True, registry.SETTINGS_PATH)
    except OSError as error:
        say(f"dasha: the settings could not be saved: {error}", file=sys.stderr)


def _take_the_screen(
    args: argparse.Namespace,
    shortcuts: Shortcuts | None,
    theme_name: str | None,
    paths: tuple[Path, Path],
) -> int:
    """Run the key test, or the desktop with its applications; an exit code.
    What would stop it is reported before the screen is taken over.
    ``paths`` are the shortcuts and colours files in use."""
    startup = None if args.key_test else _startup(args.apps, desktop=args.desktop)
    if startup is None and not args.key_test:
        return 1
    try:
        animations = args.key_test or registry.read_animations_setting(
            registry.SETTINGS_PATH
        )
        colour_depth = args.colour_depth or registry.read_colour_depth_setting(
            registry.SETTINGS_PATH
        )
        show_mouse = args.show_mouse or registry.read_show_mouse_setting(
            registry.SETTINGS_PATH
        )
        escape_timeout = registry.read_escape_timeout_setting(registry.SETTINGS_PATH)
    except ManifestError as error:
        say(f"dasha: {error}", file=sys.stderr)
        return 1
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        say("dasha: must be run in an interactive terminal", file=sys.stderr)
        return 1
    _remember_options(args)
    desktop: PresentationManager | None = None
    try:
        with Terminal() as terminal:
            if startup is None:
                keytest.run(terminal)
            else:
                entries, names = startup
                desktop = _desktop(
                    shortcuts,
                    names,
                    entries=entries,
                    theme_name=theme_name,
                    alone=not args.desktop,
                    animations=animations,
                    paths=paths,
                    colour_depth=colour_depth,
                    show_mouse=show_mouse,
                    escape_timeout=escape_timeout,
                )
                desktop.survive_errors = True  # fail softly (dasha.recovery)
                desktop.run(terminal)
    except OSError as error:
        say(f"dasha: {error}", file=sys.stderr)
        return 1
    if desktop is not None:
        _report_unsaid(desktop)
        if _report_errors(desktop):
            return 1
    return 0


def _report_errors(desktop: PresentationManager) -> bool:
    """Say where the log is, if anything went wrong in the desktop's own
    code while it ran; returns whether it went wrong so often that the
    desktop gave up."""
    recovery = desktop.recovery
    if recovery is None:
        return False
    say(f"dasha: {recovery.summary(desktop.stopped_by_errors)}", file=sys.stderr)
    return desktop.stopped_by_errors


def _report_unsaid(desktop: PresentationManager) -> None:
    """What the desktop had to say but ended before it could (an
    application that could not start, when it was the only one): said on
    the terminal instead, once the screen is given back."""
    server = desktop.server
    for title, message in server.notices if server is not None else []:
        say(f"dasha: {title}: {' '.join(message.split())}", file=sys.stderr)


def main(argv: Sequence[str] | None = None, *, desktop: bool = False) -> int:
    """Run the Dasha Framework command line (the ``dasha`` command, or, if
    ``desktop``, ``dasha-desktop``) and return a process exit code."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in install.COMMANDS:
        return install.run(arguments)
    args = _parse_arguments(arguments, desktop=desktop)
    path: Path = args.shortcuts if args.shortcuts is not None else DEFAULT_PATH

    colours_path: Path = (
        args.colours if args.colours is not None else theme.DEFAULT_PATH
    )

    if args.init_shortcuts:
        return _write_new_file(path, Shortcuts().to_json(), "shortcuts")
    if args.init_colours:
        return _write_new_file(
            colours_path, theme.theme_to_json(theme.DEFAULT_THEME), "colours"
        )
    if args.init_theme is not None:
        name = registry.slug(args.init_theme)
        return _write_new_file(
            theme.THEMES_FOLDER / f"{name}.json",
            theme.theme_to_json(theme.DEFAULT_THEME),
            f"colours, as the theme {name},",
        )

    # Load (and check) the settings before taking over the screen, so any
    # problem is reported where the user can read it.
    settings = _load_settings(args, path, colours_path)
    if settings is None:
        return 1
    shortcuts, (colours, theme_name) = settings
    theme.apply_theme(colours)
    return _take_the_screen(args, shortcuts, theme_name, (path, colours_path))


def desktop_main(argv: Sequence[str] | None = None) -> int:
    """Run the ``dasha-desktop`` command, which is ``dasha desktop``: the
    desktop, with any applications named started on it. Returns a process
    exit code."""
    return main(argv, desktop=True)


if __name__ == "__main__":
    raise SystemExit(main())
