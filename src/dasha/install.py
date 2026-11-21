"""Installing and uninstalling applications."""

import argparse
import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from dasha import registry
from dasha.printing import say
from dasha.registry import (
    AppEntry,
    ManifestError,
    is_script,
    load_manifests,
    read_manifest,
    slug,
    split_script,
    venv_python,
    write_manifest,
)

COMMANDS = ("install-app", "uninstall-app", "list-apps")
"""The subcommands that this module runs (``dasha install-app ...``)."""


def known_applications() -> tuple[dict[str, AppEntry], list[str]]:
    """Installed applications by id, and manifest problems."""
    installed, problems = load_manifests(registry.MANIFEST_FOLDER)
    return {entry.id: entry for entry in installed}, problems


def run(argv: Sequence[str]) -> int:
    """Run a command; return an exit code.

    :param argv: The command and its arguments.
    """
    command, *rest = argv
    if command == "install-app":
        return install(rest)
    if command == "uninstall-app":
        return uninstall(rest)
    return list_apps(rest)


def _fail(message: str) -> int:
    say(f"dasha: {message}", file=sys.stderr)
    return 1


# install-app


def _install_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dasha install-app",
        description="Install an application: write its manifest, and if asked, "
        "make a virtual environment for it.",
    )
    parser.add_argument(
        "source",
        help="a script (path/app.py) or a module and class (package.module:Class)",
    )
    parser.add_argument("--name", help="what the Applications menu calls it")
    parser.add_argument(
        "--class", dest="class_name", help="the Application class (if not in SOURCE)"
    )
    parser.add_argument("--id", help="what `dasha ID` calls it (from the name)")
    parser.add_argument(
        "--group", default="", help="an Applications submenu to list it in"
    )
    parser.add_argument("--single-instance", action="store_true", help="one at a time")
    parser.add_argument("--venv", help="run it with this virtual environment's Python")
    parser.add_argument(
        "--create-venv",
        action="store_true",
        help=f"make a virtual environment for it (in {registry.VENV_FOLDER}, "
        "or at --venv)",
    )
    parser.add_argument(
        "--python",
        metavar="PATH",
        help="the Python to make the virtual environment with (by default this "
        "one; in a build of dasha, one found on PATH)",
    )
    parser.add_argument(
        "--pip",
        action="append",
        default=[],
        metavar="REQUIREMENT",
        help="install this into its virtual environment with pip (repeatable)",
    )
    parser.add_argument(
        "-r", "--requirements", help="install a requirements file into its venv"
    )
    parser.add_argument(
        "--force", action="store_true", help="replace an application of the same id"
    )
    return parser


def _target(args: argparse.Namespace) -> tuple[str, str] | str:
    """(target, default name), or what is wrong.

    :param args: Parsed arguments.
    """
    source, class_name = str(args.source), args.class_name
    if source.endswith(".py") or is_script(source):
        path_text, from_source = split_script(source)
        path = Path(path_text).expanduser().resolve()
        if not path.is_file():
            return f"no such script: {path}"
        class_name = class_name or from_source
        target = str(path) + (f":{class_name}" if class_name else "")
        return target, class_name or path.stem.replace("_", " ").title()
    module, _, from_source = source.partition(":")
    if from_source and class_name and from_source != class_name:
        return "give the class once: in SOURCE or with --class"
    class_name = from_source or class_name
    if not module or not class_name:
        return "give the module's class: package.module:Class, or --class"
    return f"{module}:{class_name}", class_name


MINIMUM_PYTHON = (3, 12)
"""Oldest Python a virtual environment may have."""


def base_python(explicit: str | None = None) -> list[str] | str:
    """A Python command for making virtual environments, or what is wrong.

    :param explicit: The ``--python`` given, if any.
    """
    if explicit:
        candidates = [[explicit]]
    elif not getattr(sys, "frozen", False):
        candidates = [[sys.executable]]
    else:
        candidates = [
            [found] for name in ("python3", "python") if (found := shutil.which(name))
        ]
        if (launcher := shutil.which("py")) is not None:
            candidates.append([launcher, "-3"])
        if not candidates:
            return "no Python found on PATH to make it with: give one with --python"
    wanted = ".".join(map(str, MINIMUM_PYTHON))
    check = f"import sys; sys.exit(sys.version_info < {MINIMUM_PYTHON!r})"
    for command in candidates:
        try:
            done = subprocess.run(
                [*command, "-c", check], check=False, capture_output=True, timeout=30
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if done.returncode == 0:
            return command
    return f"no Python {wanted} or newer to make it with: give one with --python"


def _make_venv(path: Path, with_pip: bool, python: list[str]) -> str | None:
    """Make a virtual environment; return any problem.

    :param path: Where to make it.
    :param with_pip: Whether to include pip.
    :param python: The Python command.
    """
    say(f"Making a virtual environment in {path} ...")
    options = [] if with_pip else ["--without-pip"]
    try:
        done = subprocess.run([*python, "-m", "venv", *options, str(path)], check=False)
    except OSError as error:
        return f"cannot make a virtual environment in {path}: {error}"
    if done.returncode != 0:
        return f"cannot make a virtual environment in {path}"
    return None


def _pip(python: Path, args: argparse.Namespace) -> str | None:
    """Install packages with pip; return any problem.

    :param python: The environment's Python.
    :param args: Parsed arguments.
    """
    requirements = list(args.pip)
    if args.requirements:
        requirements += ["-r", str(Path(args.requirements).expanduser().resolve())]
    if not requirements:
        return None
    say("Installing", " ".join(requirements), "...")
    done = subprocess.run(
        [str(python), "-m", "pip", "install", *requirements], check=False
    )
    return None if done.returncode == 0 else "pip could not install everything"


def module_found(module: str, python: Path | None) -> bool:
    """Whether a module can be imported.

    :param module: The module name.
    :param python: A virtual environment's Python, or ``None`` for this one.
    """
    if python is None:
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            return False
    check = (
        "import importlib.util, sys; "
        f"sys.exit(importlib.util.find_spec({module!r}) is None)"
    )
    return subprocess.run([str(python), "-c", check], check=False).returncode == 0


class _InstallError(Exception):
    """Installing stops here; the message says why."""


def _venv_for(args: argparse.Namespace, app_id: str) -> Path | None:
    """The virtual environment to use, or ``None``.

    :param args: Parsed arguments.
    :param app_id: The application id.
    """
    venv_path: Path | None = None
    if args.create_venv:
        venv_path = Path(args.venv or registry.VENV_FOLDER / app_id)
        venv_path = venv_path.expanduser().resolve()
        maker = base_python(args.python)
        if isinstance(maker, str):
            raise _InstallError(maker)
        wants_pip = bool(args.pip or args.requirements)
        if problem := _make_venv(venv_path, wants_pip, maker):
            raise _InstallError(problem)
    elif args.venv:
        venv_path = Path(args.venv).expanduser().resolve()
    elif args.pip or args.requirements:
        raise _InstallError("--pip and --requirements need --venv or --create-venv")
    if venv_path is None:
        return None
    python = venv_python(venv_path)
    if not python.exists():
        raise _InstallError(f"no Python in {venv_path}")
    if problem := _pip(python, args):
        raise _InstallError(problem)
    return venv_path


def _entry(args: argparse.Namespace) -> AppEntry:
    """The checked application entry.

    :param args: Parsed arguments.
    """
    found = _target(args)
    if isinstance(found, str):
        raise _InstallError(found)
    target, default_name = found
    name = args.name or default_name
    app_id = slug(args.id or name)
    if problem := registry.reserved_id_problem(app_id):
        raise _InstallError(f"{problem} (--id gives it another)")
    if (registry.MANIFEST_FOLDER / f"{app_id}.toml").exists() and not args.force:
        raise _InstallError(f'"{app_id}" is installed already (--force replaces it)')
    venv_path = _venv_for(args, app_id)
    module = target.partition(":")[0]
    python = venv_python(venv_path) if venv_path is not None else None
    if not is_script(target) and not module_found(module, python):
        where = (
            f"the virtual environment {venv_path}" if venv_path else "Dasha Framework"
        )
        raise _InstallError(f"{module} cannot be imported by {where}")
    return AppEntry(
        id=app_id,
        name=name,
        target=target,
        venv=str(venv_path) if venv_path is not None else None,
        single_instance=args.single_instance,
        group=args.group,
    )


def install(argv: Sequence[str]) -> int:
    """``dasha install-app``.

    :param argv: Command-line arguments.
    """
    args = _install_parser().parse_args(argv)
    try:
        entry = _entry(args)
    except _InstallError as failure:
        return _fail(str(failure))
    path = write_manifest(entry, registry.MANIFEST_FOLDER)
    say(f"Installed {entry.name} as {entry.id} ({path})")
    say(f"Start it from the Applications menu, or with: dasha {entry.id}")
    return 0


# uninstall-app and list-apps


def uninstall(argv: Sequence[str]) -> int:
    """``dasha uninstall-app``.

    :param argv: Command-line arguments.
    """
    parser = argparse.ArgumentParser(
        prog="dasha uninstall-app", description="Remove an installed application."
    )
    parser.add_argument("id", help="the application's id (dasha list-apps)")
    parser.add_argument(
        "--remove-venv",
        action="store_true",
        help=f"also delete its virtual environment, if install-app made it in "
        f"{registry.VENV_FOLDER}",
    )
    args = parser.parse_args(argv)
    try:
        done = remove_application(args.id, remove_venv=args.remove_venv)
    except ManifestError as error:
        return _fail(str(error))
    for line in done:
        say(line)
    return 0


def made_venv(entry: AppEntry) -> Path | None:
    """The virtual environment install-app made, if any.

    :param entry: The application entry.
    """
    if not entry.venv:
        return None
    venv_path = Path(entry.venv).resolve()
    return venv_path if venv_path.parent == registry.VENV_FOLDER.resolve() else None


def remove_application(app_id: str, *, remove_venv: bool = False) -> list[str]:
    """Uninstall an application; return what was done.

    :param app_id: The application id.
    :param remove_venv: Whether to delete its virtual environment.
    """
    path = registry.MANIFEST_FOLDER / f"{app_id}.toml"
    # Installed ids are always slugs: anything else ("../x") is not one, and
    # must not reach a file outside the folder.
    if app_id != slug(app_id) or not path.exists():
        raise ManifestError(f'no installed application "{app_id}"')
    try:
        entry: AppEntry | None = read_manifest(path)
    except ManifestError:
        entry = None
    path.unlink()
    done = [f"Uninstalled {app_id}"]
    if remove_venv and entry is not None and entry.venv:
        venv_path = made_venv(entry)
        if venv_path is not None:
            shutil.rmtree(venv_path, ignore_errors=True)
            done.append(f"Deleted {venv_path}")
        else:
            done.append(
                f"Left {Path(entry.venv).resolve()}: install-app did not make it"
            )
    return done


def list_apps(argv: Sequence[str]) -> int:
    """``dasha list-apps``.

    :param argv: Command-line arguments.
    """
    parser = argparse.ArgumentParser(
        prog="dasha list-apps",
        description="List the applications Dasha Framework knows.",
    )
    parser.parse_args(argv)
    entries, problems = known_applications()
    if not entries:
        say("No applications are installed (dasha install-app installs one).")
    width = max((len(key) for key in entries), default=0) + 2
    for key, entry in entries.items():
        where = entry.target
        if entry.venv:
            where += f"  (venv {entry.venv})"
        group = f" [{entry.group}]" if entry.group else ""
        say(f"{key:<{width}}{entry.name}{group}  {where}")
    for problem in problems:
        say(f"dasha: {problem}", file=sys.stderr)
    return 0
