"""
sv_ramp dataset view — streams individual frames via direct HTTP Range requests.

The image stack (000_im_array) is stored contiguous and unchunked in the HDF5
file.  On first access we open the file with h5py/fsspec *once* to:
  - read the small 1-D metadata arrays (sv_array, imavg_array)
  - record dataset.id.get_offset() — the byte position where raw pixel data
    starts inside the file

Thereafter every /frame request issues a single HTTP Range request directly
(no h5py, no fsspec re-open) to fetch exactly the ~2 MB for that frame.
This keeps frame latency to the raw network round-trip time.

Signed download URLs are refreshed after _URL_TTL seconds.
"""

import io
import os
import time

import fsspec
import h5py
import numpy as np
import requests as _requests
from flask import Blueprint, Response, abort, current_app, render_template, request
from PIL import Image

from utils.auth import get_user_client

MEASUREMENT_TYPES = ['sv_ramp']
URL_PREFIX = '/dataset-view/sv-ramp-gcs'
LABEL = 'SV Ramp Viewer'

_URL_TTL = 600  # seconds — refresh signed URL before it expires

# {dsid: {
#   'filename':    str,
#   'url':         str,
#   'url_at':      float,          # monotonic time URL was fetched
#   'sv_array':    list[float],
#   'imavg_array': list[float],
#   'n_frames':    int,
#   'data_offset': int,            # byte offset of 000_im_array data in file
#   'frame_bytes': int,            # bytes per frame (H*W*itemsize)
#   'shape':       tuple[int,int,int],
#   'dtype':       np.dtype,
# }}
_cache: dict[str, dict] = {}

# LRU cache for raw frame bytes — keyed by (dsid, fi).
# Holds at most _FRAME_CACHE_SIZE frames (~2 MB each) to avoid unbounded RAM use.
_FRAME_CACHE_SIZE = 30
_frame_cache: dict[tuple, bytes] = {}   # OrderedDict-style via move-to-end


def _get_cached_frame(dsid: str, fi: int) -> bytes | None:
    key = (dsid, fi)
    raw = _frame_cache.get(key)
    if raw is not None:
        # Move to end (most-recently used)
        _frame_cache[key] = _frame_cache.pop(key)
    return raw


def _put_cached_frame(dsid: str, fi: int, raw: bytes) -> None:
    key = (dsid, fi)
    if key in _frame_cache:
        _frame_cache[key] = _frame_cache.pop(key)
    else:
        if len(_frame_cache) >= _FRAME_CACHE_SIZE:
            _frame_cache.pop(next(iter(_frame_cache)))  # evict LRU
        _frame_cache[key] = raw


# ── helpers ───────────────────────────────────────────────────────────────────

def _find_h5_filename(crucible_client, dsid: str) -> str:
    associated_files = crucible_client.datasets.get_associated_files(dsid)
    match = next((f for f in associated_files if f['filename'].endswith('.h5')), None)
    if not match:
        abort(404)
    return os.path.basename(match['filename'])


def _get_url(crucible_client, dsid: str, filename: str) -> str:
    download_links = crucible_client.datasets.get_download_links(dsid)
    url = download_links.get(f'{dsid}/{filename}')
    if not url:
        abort(404)
    return url


def _ensure_meta(dsid: str, crucible_client) -> dict:
    """
    Populate _cache[dsid] with metadata on first call.  Refreshes the signed
    URL if older than _URL_TTL without re-reading the HDF5 metadata.
    """
    now = time.monotonic()
    entry = _cache.get(dsid)

    if entry is None:
        # First time: read everything from the HDF5 file.
        filename = _find_h5_filename(crucible_client, dsid)
        url = _get_url(crucible_client, dsid, filename)

        fo = fsspec.open(url, 'rb').open()
        with h5py.File(fo, 'r') as h5:
            meas       = h5['measurement/sv_ramp']
            sv_array   = meas['0000_sv_array'][:].tolist()
            imavg      = meas['000_imavg_array'][:].tolist()
            im_ds      = meas['000_im_array']
            shape      = im_ds.shape          # (N, H, W)
            dtype      = im_ds.dtype
            offset     = im_ds.id.get_offset()  # byte offset of raw data in file

        frame_bytes = int(shape[1]) * int(shape[2]) * dtype.itemsize
        entry = {
            'filename':    filename,
            'url':         url,
            'url_at':      now,
            'sv_array':    sv_array,
            'imavg_array': imavg,
            'n_frames':    shape[0],
            'data_offset': offset,
            'frame_bytes': frame_bytes,
            'shape':       shape,
            'dtype':       dtype,
        }
        _cache[dsid] = entry

    elif (now - entry['url_at']) >= _URL_TTL:
        # Refresh the signed URL only.
        entry['url']    = _get_url(crucible_client, dsid, entry['filename'])
        entry['url_at'] = now

    return entry


def _fetch_frame_bytes(url: str, data_offset: int, frame_bytes: int, fi: int) -> bytes:
    """Fetch exactly one frame's worth of bytes via a single HTTP Range request."""
    start = data_offset + fi * frame_bytes
    end   = start + frame_bytes - 1
    resp  = _requests.get(url, headers={'Range': f'bytes={start}-{end}'}, timeout=30)
    if resp.status_code not in (200, 206):
        abort(502)
    return resp.content


def _frame_to_png(raw_bytes: bytes, shape: tuple, dtype: np.dtype,
                  vmin: float | None, vmax: float | None) -> bytes:
    frame = np.frombuffer(raw_bytes, dtype=dtype).reshape(shape[1], shape[2])
    arr   = frame.astype(np.float32)
    lo    = float(vmin) if vmin is not None else float(np.percentile(arr, 2))
    hi    = float(vmax) if vmax is not None else float(np.percentile(arr, 98))
    if hi <= lo:
        hi = lo + 1.0
    arr = np.clip((arr - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, mode='L').save(buf, format='PNG')
    return buf.getvalue()


# ── blueprint ─────────────────────────────────────────────────────────────────

def create_blueprint(auth, helpers):
    bp = Blueprint('dview_sv_ramp_gcs', __name__)
    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds    = get_user_client().datasets.get(dsid)
        meta  = _ensure_meta(dsid, get_user_client())
        return render_template(
            'dataset_views/sv_ramp_gcs.html',
            project_id=project_id,
            ds=ds,
            sv_array=meta['sv_array'],
            imavg_array=meta['imavg_array'],
            n_frames=meta['n_frames'],
        )

    @bp.route('/<project_id>/<dsid>/frame')
    @auth.oidc_auth('orcid')
    def frame(project_id, dsid):
        """
        Return one LEEM frame as an 8-bit grayscale PNG.

        Query params:
            fi   – frame index (required)
            vmin – lower clip in raw uint16 counts (optional)
            vmax – upper clip in raw uint16 counts (optional)
        """
        if not is_user_in_project(project_id):
            abort(403)

        fi   = request.args.get('fi',   type=int)
        vmin = request.args.get('vmin', type=float)
        vmax = request.args.get('vmax', type=float)
        if fi is None:
            abort(400)

        meta = _ensure_meta(dsid, get_user_client())
        if not (0 <= fi < meta['n_frames']):
            abort(400)

        raw = _get_cached_frame(dsid, fi)
        cache_hit = raw is not None

        t0 = time.perf_counter()
        if not cache_hit:
            raw = _fetch_frame_bytes(meta['url'], meta['data_offset'],
                                     meta['frame_bytes'], fi)
            _put_cached_frame(dsid, fi, raw)
        t1  = time.perf_counter()
        png = _frame_to_png(raw, meta['shape'], meta['dtype'], vmin, vmax)
        t2  = time.perf_counter()

        fetch_ms  = (t1 - t0) * 1000
        encode_ms = (t2 - t1) * 1000
        current_app.logger.info(
            f'sv_ramp frame fi={fi} cache={"HIT" if cache_hit else "MISS"} '
            f'fetch={fetch_ms:.0f}ms '
            + (f'({meta["frame_bytes"] / (t1-t0) / 1e6:.1f} MB/s) ' if not cache_hit else '')
            + f'encode={encode_ms:.0f}ms png={len(png)//1024}KB'
        )

        resp = Response(png, mimetype='image/png')
        resp.headers['Server-Timing'] = (
            f'fetch;desc="{"cache" if cache_hit else "GCS"} fetch";dur={fetch_ms:.1f}, '
            f'encode;desc="PNG encode";dur={encode_ms:.1f}'
        )
        return resp

    return bp
