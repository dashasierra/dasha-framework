"""``python -m dasha.host TARGET``: how the desktop starts an
application in its own process.

``TARGET`` is either ``MODULE:CLASS`` (an importable module and the
application class in it), or a script: ``path/app.py``, or
``path/app.py:CLASS`` when the script holds more than one application. A
script's folder is put on ``sys.path``, so that the script can import the
modules beside it; a script inside a package (its folder has an
``__init__.py``) is imported as part of that package instead, with the
folder above the package on ``sys.path``, so that its imports of the
package's other modules work. The application then finds the desktop through
``DASHA_ADDRESS`` (with the key arriving on standard input) and runs on
it.
"""

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
    """For a script inside a package, the folder above the outermost
    package and the script's dotted module name (``pgh/app.py`` is
    ``pgh.app``); ``None`` for a script that is not in one."""
    parts = [] if path.stem == "__init__" else [path.stem]
    folder = path.parent
    while (folder / "__init__.py").is_file() and folder.name.isidentifier():
        parts.insert(0, folder.name)
        folder = folder.parent
    if folder == path.parent:
        return None
    return folder, ".".join(parts)


def _load_script(path: Path) -> ModuleType:
    """Run a script as a module (not as ``__main__``, so its own
    ``if __name__ == "__main__"`` part does not start anything)."""
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
    """The one application class a module defines itself."""
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
    """The application class that ``target`` names. Raises ``ValueError``
    if it names something other than an application class, and
    ``ImportError`` if it cannot be found."""
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
    """Run the application named on the command line, and return an exit
    code."""
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
