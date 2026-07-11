"""
sv_ramp dataset view — browser-side HTTP Range frame streaming.

The image stack (000_im_array) is stored contiguous and unchunked in the HDF5
file.  On first access the server opens the file once with h5py/fsspec to read:
  - the small 1-D metadata arrays (sv_array, imavg_array)
  - dataset.id.get_offset() — the byte position where raw pixel data starts

The server then hands the browser a short-lived signed URL plus the byte
offset, per-frame byte length, frame shape and dtype.  The browser issues its
own HTTP Range requests directly against the bucket for each frame, decodes the
raw bytes into a typed array and renders to a <canvas> client-side — no
per-frame round trip through the server.

Requires bucket CORS to allow GET with the Range request header and to expose
Content-Range (see cors.json).
"""

import os
import time

import fsspec
import h5py
from flask import Blueprint, abort, jsonify, render_template, request, send_from_directory

from utils.auth import get_user_client

MEASUREMENT_TYPES = ['sv_ramp']
DATA_TYPE_STEMS = ['ScopeFoundryH5.qspleem_sv_ramp']
URL_PREFIX = '/dataset-view/sv-ramp'
LABEL = 'SV Ramp Viewer'

# Directory of local .h5 files for the /local dev test route (not deployed to prod).
_TEST_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'test_data')

_URL_TTL = 600  # seconds — refresh signed URL before it expires

# {dsid: {url, url_at, sv_array, imavg_array, n_frames,
#          frame_offsets, frame_bytes, height, width, dtype}}
_cache: dict[str, dict] = {}


def _find_h5_url(crucible_client, dsid: str) -> str:
    associated_files = crucible_client.datasets.get_associated_files(dsid)
    match = next((f for f in associated_files if f['filename'].endswith('.h5')), None)
    if not match:
        abort(404)
    download_links = crucible_client.datasets.get_download_links(dsid)
    url = download_links.get(match['mfid'])
    if not url:
        abort(404)
    return url


def _frame_offsets(im_ds, n_frames: int, frame_bytes: int) -> list:
    """Byte offset of each frame's raw pixel data, so the browser can Range-fetch
    one frame per request.  Handles both layouts real files come in:
      - contiguous stack (chunks is None): offset + i*frame_bytes
      - one uncompressed chunk per frame (chunks == (1, H, W)): the chunk's
        byte_offset, read via get_chunk_info (this is what live acquisitions write)
    """
    if im_ds.compression is not None:
        abort(500)  # compressed chunks can't be raw Range-read
    if im_ds.chunks is None:
        base = im_ds.id.get_offset()
        if base is None:
            abort(500)  # unallocated
        return [base + i * frame_bytes for i in range(n_frames)]
    by_frame = {}
    for i in range(im_ds.id.get_num_chunks()):
        info = im_ds.id.get_chunk_info(i)
        by_frame[int(info.chunk_offset[0])] = int(info.byte_offset)
    return [by_frame[i] for i in range(n_frames)]


def _ensure_meta(dsid: str, crucible_client) -> dict:
    """Populate _cache[dsid] on first call; refresh only the signed URL after TTL."""
    now = time.monotonic()
    entry = _cache.get(dsid)

    if entry is None:
        url = _find_h5_url(crucible_client, dsid)
        fo = fsspec.open(url, 'rb').open()
        with h5py.File(fo, 'r') as h5:
            meas     = h5['measurement/sv_ramp']
            sv_array = meas['0000_sv_array'][:].tolist()
            imavg    = meas['000_imavg_array'][:].tolist()
            im_ds    = meas['000_im_array']
            shape    = im_ds.shape          # (N, H, W)
            dtype    = im_ds.dtype
            frame_bytes   = int(shape[1]) * int(shape[2]) * dtype.itemsize
            frame_offsets = _frame_offsets(im_ds, int(shape[0]), frame_bytes)

        entry = {
            'url':           url,
            'url_at':        now,
            'sv_array':      sv_array,
            'imavg_array':   imavg,
            'n_frames':      int(shape[0]),
            'frame_offsets': frame_offsets,
            'frame_bytes':   frame_bytes,
            'height':        int(shape[1]),
            'width':         int(shape[2]),
            'dtype':         dtype.str,        # e.g. '<u2'
        }
        _cache[dsid] = entry

    elif (now - entry['url_at']) >= _URL_TTL:
        entry['url']    = _find_h5_url(crucible_client, dsid)
        entry['url_at'] = now

    return entry


def _stream_spec(entry: dict) -> dict:
    return {
        'url':           entry['url'],
        'frame_offsets': entry['frame_offsets'],
        'frame_bytes':   entry['frame_bytes'],
        'height':        entry['height'],
        'width':         entry['width'],
        'dtype':         entry['dtype'],
        'n_frames':      entry['n_frames'],
    }


def _local_meta(filename: str, browser_url: str) -> dict:
    """Read frame geometry from a local test_data file for the /local dev route.

    Mirrors _ensure_meta but reads a local path directly with h5py; the stream
    url points at the /localfile route so the browser Range-fetches it same-origin.
    """
    path = os.path.join(_TEST_DATA_DIR, filename)
    if not os.path.isfile(path):
        abort(404)
    with h5py.File(path, 'r') as h5:
        meas     = h5['measurement/sv_ramp']
        sv_array = meas['0000_sv_array'][:].tolist()
        imavg    = meas['000_imavg_array'][:].tolist()
        im_ds    = meas['000_im_array']
        shape    = im_ds.shape
        dtype    = im_ds.dtype
        frame_bytes   = int(shape[1]) * int(shape[2]) * dtype.itemsize
        frame_offsets = _frame_offsets(im_ds, int(shape[0]), frame_bytes)
    return {
        'sv_array':    sv_array,
        'imavg_array': imavg,
        'n_frames':    int(shape[0]),
        'stream': {
            'url':           browser_url,
            'frame_offsets': frame_offsets,
            'frame_bytes':   frame_bytes,
            'height':        int(shape[1]),
            'width':         int(shape[2]),
            'dtype':         dtype.str,
            'n_frames':      int(shape[0]),
        },
    }


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_sv_ramp', __name__)
    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds   = get_user_client().datasets.get(dsid)
        meta = _ensure_meta(dsid, get_user_client())
        return render_template(
            'dataset_views/sv_ramp.html',
            project_id=project_id,
            ds=ds,
            sv_array=meta['sv_array'],
            imavg_array=meta['imavg_array'],
            n_frames=meta['n_frames'],
            stream=_stream_spec(meta),
        )

    @bp.route('/<project_id>/<dsid>/stream-spec')
    @auth.oidc_auth('orcid')
    def stream_spec(project_id, dsid):
        """Return a fresh signed URL + byte-offset spec for browser Range fetches."""
        if not is_user_in_project(project_id):
            abort(403)
        meta = _ensure_meta(dsid, get_user_client())
        return jsonify(_stream_spec(meta))

    # ── local dev test route: point the browser at a test_data file ──────────────
    @bp.route('/localfile/<filename>')
    @auth.oidc_auth('orcid')
    def localfile(filename):
        return send_from_directory(_TEST_DATA_DIR, filename, conditional=True)

    @bp.route('/local/<filename>')
    @auth.oidc_auth('orcid')
    def local_view(filename):
        browser_url = f"{request.script_root}{URL_PREFIX}/localfile/{filename}"
        data = _local_meta(filename, browser_url)
        return render_template(
            'dataset_views/sv_ramp.html',
            project_id=None,
            ds={'dataset_name': filename, 'unique_id': None},
            sv_array=data['sv_array'],
            imavg_array=data['imavg_array'],
            n_frames=data['n_frames'],
            stream=data['stream'],
        )

    return bp
