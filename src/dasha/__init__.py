"""Dasha Framework: a text-mode desktop and application framework."""

from pkgutil import extend_path

# Enable packages to use the dasha namespace
__path__ = extend_path(__path__, __name__)

__all__ = ["__version__"]

__version__ = "0.0.1"
