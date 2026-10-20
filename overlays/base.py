"""
Overlay-source adapter harness for the Mosaic Viewer.

An overlay adapter knows how to read ONE instrument's dataset and reduce it to a
small scalar field that the mosaic viewer composites as a Google-Maps-style
layer on top of a stitched mosaic. Adapters are strictly per-instrument (h5
paths, grid geometry, spectral axes, reduction functions); everything above the
adapter — click-pair registration, client-side colormapping, the Layers panel,
and shared persistence — lives once in the viewer.

Data access is intentionally server-side: Flask reads the (possibly large)
source file via gcsfs and returns a small JSON reduction, so the raw cube never
reaches the browser. This mirrors the split the standalone hyperspec viewer
already uses.
"""

import os
from abc import ABC, abstractmethod

from cachetools import TTLCache

import gcs_access

# Open h5py.File objects cached so gcsfs's block cache is preserved between
# requests. Keyed by ('cloud', dsid) or ('local', abspath). Evicted after 1 h or
# at 16 simultaneous files — matches the standalone hyperspec viewer's policy.
_h5_cache: TTLCache = TTLCache(maxsize=16, ttl=3600)


def _cached(key, opener):
    if key not in _h5_cache:
        _h5_cache[key] = opener()          # intentionally kept open
    return _h5_cache[key]


def open_h5_cloud(dsid, client):
    """Return the cached h5py.File for a cloud dataset's .h5 associated file.

    Resolves the file via list_files (nano-crucible 3.x; get_associated_files was
    removed in 3.0) and opens it lazily over GCS so only touched datasets are
    fetched.
    """
    def opener():
        files = client.datasets.list_files(dsid) or []
        h5f = next((f for f in files
                    if str(f.get('filename', '')).lower().endswith('.h5')), None)
        if not h5f:
            raise FileNotFoundError(f'No .h5 file found for dataset {dsid}')
        return gcs_access.open_h5(dsid, os.path.basename(h5f['filename']))
    return _cached(('cloud', dsid), opener)


def open_h5_local(path):
    """Return the cached h5py.File for a local test_data .h5 path (offline harness)."""
    import h5py
    ap = os.path.abspath(path)
    return _cached(('local', ap), lambda: h5py.File(ap, 'r'))


class OverlayAdapter(ABC):
    """Contract every instrument implements to become overlay-able.

    All methods take an already-opened h5 handle (cloud or local), so the cloud
    and /local code paths share one implementation of "how to read this
    instrument."
    """

    #: measurement type strings this adapter handles, e.g. ['hyperspec_picam_mcl']
    MEASUREMENT_TYPES: list = []

    @abstractmethod
    def descriptor(self, h5) -> dict:
        """Small, normalized description that drives grid placement + reduction UI.

        Shape::

            {
              "grid": {"Nh": int, "Nv": int,
                       "extent_local": [xmin, xmax, ymin, ymax],  # native units
                       "pixel_size": float, "units": "um",
                       "h_array": [...], "v_array": [...]},
              "reductions": [ {"id", "label", "axes": [...], "params": {...}} ],
              "spectral_axis": {"wls": [...], ...},   # optional, for pickers
              "stage_hint": {...} | None,             # future Tier 0 auto-register
            }
        """

    @abstractmethod
    def reduce(self, h5, params: dict) -> dict:
        """Compute a small server-side scalar field.

        Returns ``{"Nh", "Nv", "map_data": [[...]]  # Nv x Nh row-major floats,
        "vmin", "vmax"}`` with a suggested display range.
        """

    def probe(self, h5, xi: int, yi: int):
        """Optional detail (e.g. a full spectrum) for the cross-layer inspect popover.

        Returns a dict or None. Default: no per-pixel detail.
        """
        return None
