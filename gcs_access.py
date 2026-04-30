"""
Lazy GCS file access with local block caching for dataset views.

Usage
-----
    import gcs_access

    # Any file type — returns a seekable file-like object
    with gcs_access.open_file(dsid, filename) as fo:
        data = some_library.open(fo)

    # HDF5 convenience wrapper — h5py fetches only datasets you touch
    with gcs_access.open_h5(dsid, filename) as f:
        arr = f['some/dataset'][:]

GCS path convention: gs://<BUCKET>/<dataset_id>/<basename(filename)>
Credentials: set GOOGLE_APPLICATION_CREDENTIALS or use ADC.

Caching
-------
Uses fsspec's blockcache layer: blocks are cached to local disk on first
fetch and reused on subsequent reads, including across open_file() calls.
Cache directory defaults to /tmp/gcs_cache; override with GCS_CACHE_DIR.
Blocks expire after GCS_CACHE_EXPIRY seconds (default 604800 = 1 week).
No size-based eviction — manage disk usage externally if needed.
"""

import os

import fsspec
from dotenv import load_dotenv

load_dotenv()

BUCKET = os.getenv('GCS_BUCKET', 'mf-storage-prod')
GCS_CACHE_DIR = os.getenv('GCS_CACHE_DIR', '/tmp/gcs_cache')
GCS_CACHE_EXPIRY = int(os.getenv('GCS_CACHE_EXPIRY', 604800))  # seconds; default 1 week

_fs: fsspec.AbstractFileSystem | None = None


def get_fs() -> fsspec.AbstractFileSystem:
    """Return a module-level blockcache filesystem singleton (thread-safe after init)."""
    global _fs
    if _fs is None:
        _fs = fsspec.filesystem(
            'blockcache',
            target_protocol='gcs',
            cache_storage=GCS_CACHE_DIR,
            expiry_time=GCS_CACHE_EXPIRY,
        )
    return _fs


def gcs_path(dataset_id: str, filename: str) -> str:
    """Canonical GCS path for a dataset's associated file."""
    return f'{BUCKET}/{dataset_id}/{os.path.basename(filename)}'


def open_file(dataset_id: str, filename: str, **kwargs):
    """
    Return a lazy seekable file-like object for an associated file.

    h5py, netCDF4, zarr, etc. can all accept this directly.
    Only the bytes that the caller actually reads are fetched from GCS.
    """
    return get_fs().open(gcs_path(dataset_id, filename), 'rb', **kwargs)


def open_h5(dataset_id: str, filename: str):
    """
    Return an h5py.File opened lazily over GCS.

    h5py translates internal seek/read calls into HTTP Range requests via
    gcsfs, so only the datasets you actually access are transferred.
    """
    import h5py
    fo = open_file(dataset_id, filename)
    return h5py.File(fo, 'r')
