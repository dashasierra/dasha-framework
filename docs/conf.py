"""Sphinx configuration for Dasha Framework's documentation.

The guides are Markdown (read by MyST); the API reference is generated from
the package's docstrings and type hints (autodoc and autosummary), and the
colour and shortcut tables from ``dasha.theme`` and
``dasha.shortcuts`` (``_ext/dasha_tables.py``).

Build it with::

    python -m sphinx -W --keep-going -b html docs docs/_build/html
"""

# Sphinx reads these lower-case names.
# pylint: disable=invalid-name

import os
import sys
from pathlib import Path

# Values made from the home folder (``~/.dasha`` and the files in it)
# are worked out when autodoc imports Dasha Framework. Their docstrings give them
# as ``~/...`` and hide the value (``:meta hide-value:``), which differs
# from system to system; should one be missed, a made-up home still keeps
# the real one, and its user name, out of the pages, whoever builds them.
os.environ["HOME"] = "/home/username"
os.environ["USERPROFILE"] = r"C:\Users\username"

HERE = Path(__file__).resolve().parent
# The package from the source tree, so a build works without installing it.
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE / "_ext"))

import dasha  # pylint: disable=wrong-import-position

project = "Dasha Framework"
author = "Dasha Sierra"
copyright = "2026, Dasha Sierra"  # pylint: disable=redefined-builtin
release = dasha.__version__
version = ".".join(release.split(".")[:2])

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "dasha_tables",
]

source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
root_doc = "index"
exclude_patterns = ["_build"]
templates_path = ["_templates"]

# MyST: anchors for headings, so the guides' "#mouse" style links work.
myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3

# The API reference: a page per module, written by autosummary at build
# time (into api/, which is not kept in the repository).
autosummary_generate = True
autosummary_imported_members = False
autodoc_default_options = {
    "members": True,
    "show-inheritance": True,
    "member-order": "bysource",
    # Only what each module defines itself: a package's __all__ re-exports
    # (dasha.widgets) are documented in the modules they come from.
    "ignore-module-all": True,
}
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented_params"
autodoc_preserve_defaults = True
autodoc_class_signature = "separated"

intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}

html_theme = "furo"
html_static_path = ["_static"]
html_css_files = ["dasha.css"]
html_title = f"Dasha Framework {release}"
