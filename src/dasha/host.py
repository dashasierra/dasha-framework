"""Start an application in its own process."""

import importlib
import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from dasha.application import Application
from dasha.printing import say
from dasha.registry import is_script, split_script


def _package_name(path: Path) -> tuple[Path, str] | None:
    """A script's package root and module name, or ``None``.

    :param path: The script.
    """
    parts = [] if path.stem == "__init__" else [path.stem]
    folder = path.parent
    while (folder / "__init__.py").is_file() and folder.name.isidentifier():
        parts.insert(0, folder.name)
        folder = folder.parent
    if folder == path.parent:
        return None
    return folder, ".".join(parts)


def _load_script(path: Path) -> ModuleType:
    """Import a script as a module.

    :param path: The script.
    """
    if not path.is_file():
        raise ImportError(f"no such script: {path}")
    package = _package_name(path)
    if package is not None:
        root, name = package
        sys.path.insert(0, str(root))
        importlib.invalidate_caches()
        return importlib.import_module(name)
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("dasha_script", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _only_application(module: ModuleType) -> type[Application]:
    """The one application class a module defines.

    :param module: The module.
    """
    found = [
        value
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, Application)
        and value.__module__ == module.__name__
    ]
    if len(found) != 1:
        what = "no Application class" if not found else "several Application classes"
        raise ValueError(f"{module.__file__} has {what}: name one, as app.py:CLASS")
    return found[0]


def find(target: str) -> type[Application]:
    """The application class a target names.

    :param target: ``MODULE:CLASS`` or a script path.
    """
    if is_script(target):
        path, class_name = split_script(target)
        module = _load_script(Path(path).expanduser().resolve())
        if class_name is None:
            return _only_application(module)
        found: object = module
        qualified_name = class_name
    else:
        module_name, _, qualified_name = target.partition(":")
        if not module_name or not qualified_name:
            raise ValueError(f"expected MODULE:CLASS or a script, not {target!r}")
        found = importlib.import_module(module_name)
    for part in qualified_name.split("."):
        found = getattr(found, part, None)
    if not (isinstance(found, type) and issubclass(found, Application)):
        raise ValueError(f"{target} is not an Application class")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """Run the named application; return an exit code.

    :param argv: Arguments, or ``None`` for ``sys.argv``.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        say(
            "usage: python -m dasha.host MODULE:CLASS | SCRIPT[:CLASS]",
            file=sys.stderr,
        )
        return 2
    try:
        application = find(args[0])
    except (ImportError, ValueError) as error:
        say(f"dasha: {error}", file=sys.stderr)
        return 2
    return application().run()


if __name__ == "__main__":
    raise SystemExit(main())
