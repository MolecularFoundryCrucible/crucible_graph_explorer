"""
Overlay-source adapter registry (Mosaic Viewer correlative overlays).

Mirrors the dataset-view plugin pattern: drop a module in this package that
defines an ``OverlayAdapter`` subclass, and every measurement type it lists in
``MEASUREMENT_TYPES`` becomes overlay-able. ``get_adapter(measurement)`` maps a
target dataset's measurement to its adapter; unknown types return None (the
"Add overlay" picker hides them).
"""

import importlib
import pkgutil
from pathlib import Path

from .base import OverlayAdapter, open_h5_cloud, open_h5_local  # noqa: F401

# measurement type -> adapter instance. Populated lazily on first lookup.
_registry: dict = {}
_discovered = False


def _discover():
    global _discovered
    if _discovered:
        return
    _discovered = True
    pkg_dir = Path(__file__).parent
    for _, name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        if name == 'base':
            continue
        try:
            module = importlib.import_module(f'overlays.{name}')
        except Exception:
            continue
        for obj in vars(module).values():
            if (isinstance(obj, type) and issubclass(obj, OverlayAdapter)
                    and obj is not OverlayAdapter):
                inst = obj()
                for mtype in inst.MEASUREMENT_TYPES:
                    _registry[mtype] = inst


def get_adapter(measurement):
    """Return the adapter instance for a measurement type, or None."""
    _discover()
    return _registry.get(measurement)


def adapter_measurements():
    """Sorted list of measurement types that have a registered adapter."""
    _discover()
    return sorted(_registry.keys())
