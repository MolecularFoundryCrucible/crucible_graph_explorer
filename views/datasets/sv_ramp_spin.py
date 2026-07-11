"""
sv_ramp_spin dataset view — spin-polarized SV ramp.

Crucible path: the server reads the contiguous up/down im_array byte offsets,
frame shape and dtype once, then hands the browser a signed URL plus that spec.
The browser issues its own HTTP Range requests per frame, decodes the raw bytes
and renders to a canvas client-side (grayscale for up/down, RdBu_r for
difference/asymmetry). ROI IV curves are computed in the browser from per-frame
Range reads of the selected rows.

Local path (dev only): serves a test_data .h5 file over HTTP (Range-capable) and
hands the browser the same stream spec, so the client render path is exercised
locally exactly as in production.

Requires bucket CORS to allow GET with the Range request header and to expose
Content-Range (see cors.json).
"""

import os
import time

import fsspec
import h5py
from flask import Blueprint, abort, jsonify, render_template, request, send_from_directory

from utils.auth import get_user_client

MEASUREMENT_TYPES = ['sv_ramp_spin']
DATA_TYPE_STEMS = ['ScopeFoundryH5.qspleem_sv_ramp_spin']
URL_PREFIX = '/dataset-view/sv-ramp-spin'
LABEL = 'SV Ramp Spin Viewer'

_URL_TTL = 600
_TEST_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'test_data')

# {dsid: { sv_array, imavg_up, imavg_down, asym_array, n_frames,
#           url, url_at, filename, mfid, up_offsets, down_offsets,
#           frame_bytes, height, width, dtype }}
_cache: dict[str, dict] = {}


def _frame_offsets(im_ds, n_frames: int, frame_bytes: int) -> list:
    """Byte offset of each frame's raw pixel data (see sv_ramp.py). Handles a
    contiguous stack or one-uncompressed-chunk-per-frame (what live acquisitions
    write), so the browser can Range-fetch a single frame per request."""
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


def _ensure_meta(dsid, crucible_client):
    now = time.monotonic()
    entry = _cache.get(dsid)

    if entry is None:
        associated = crucible_client.datasets.get_associated_files(dsid)
        match = next((f for f in associated if f['filename'].endswith('.h5')), None)
        if not match:
            abort(404)
        filename = os.path.basename(match['filename'])
        mfid = match['mfid']
        links = crucible_client.datasets.get_download_links(dsid)
        url = links.get(mfid)
        if not url:
            abort(404)

        fo = fsspec.open(url, 'rb').open()
        with h5py.File(fo, 'r') as h5:
            meas = h5['measurement/sv_ramp_spin']
            sv_array = meas['0000_sv_array'][:].tolist()
            imavg_up = meas['000_imavg_up_array'][:].tolist()
            imavg_down = meas['000_imavg_down_array'][:].tolist()
            asym_array = meas['000_asym_array'][:].tolist()
            up_ds = meas['000_im_up_array']
            down_ds = meas['000_im_down_array']
            shape = up_ds.shape
            dtype = up_ds.dtype
            frame_bytes  = int(shape[1]) * int(shape[2]) * dtype.itemsize
            n            = int(shape[0])
            up_offsets   = _frame_offsets(up_ds, n, frame_bytes)
            down_offsets = _frame_offsets(down_ds, n, frame_bytes)

        entry = {
            'filename': filename, 'mfid': mfid, 'url': url, 'url_at': now,
            'sv_array': sv_array, 'imavg_up': imavg_up,
            'imavg_down': imavg_down, 'asym_array': asym_array,
            'n_frames': int(shape[0]), 'up_offsets': up_offsets,
            'down_offsets': down_offsets, 'frame_bytes': frame_bytes,
            'height': int(shape[1]), 'width': int(shape[2]), 'dtype': dtype.str,
        }
        _cache[dsid] = entry

    elif (now - entry['url_at']) >= _URL_TTL:
        links = crucible_client.datasets.get_download_links(dsid)
        entry['url'] = links.get(entry['mfid'])
        entry['url_at'] = now

    return entry


def _stream_spec(entry):
    return {
        'url':          entry['url'],
        'up_offsets':   entry['up_offsets'],
        'down_offsets': entry['down_offsets'],
        'frame_bytes':  entry['frame_bytes'],
        'height':      entry['height'],
        'width':       entry['width'],
        'dtype':       entry['dtype'],
        'n_frames':    entry['n_frames'],
    }


def _local_meta(filename: str, browser_url: str) -> dict:
    """Read up/down frame geometry from a local test_data file for the /local dev route.

    Mirrors _ensure_meta but reads a local path directly with h5py; the stream url
    points at the /localfile route so the browser Range-fetches it same-origin.
    """
    path = os.path.join(_TEST_DATA_DIR, filename)
    if not os.path.isfile(path):
        abort(404)
    with h5py.File(path, 'r') as h5:
        meas        = h5['measurement/sv_ramp_spin']
        sv_array    = meas['0000_sv_array'][:].tolist()
        imavg_up    = meas['000_imavg_up_array'][:].tolist()
        imavg_down  = meas['000_imavg_down_array'][:].tolist()
        asym_array  = meas['000_asym_array'][:].tolist()
        up_ds       = meas['000_im_up_array']
        down_ds     = meas['000_im_down_array']
        shape       = up_ds.shape
        dtype       = up_ds.dtype
        frame_bytes  = int(shape[1]) * int(shape[2]) * dtype.itemsize
        n            = int(shape[0])
        up_offsets   = _frame_offsets(up_ds, n, frame_bytes)
        down_offsets = _frame_offsets(down_ds, n, frame_bytes)
    return {
        'sv_array': sv_array, 'imavg_up': imavg_up,
        'imavg_down': imavg_down, 'asym_array': asym_array,
        'n_frames': int(shape[0]),
        'stream': {
            'url':          browser_url,
            'up_offsets':   up_offsets,
            'down_offsets': down_offsets,
            'frame_bytes':  frame_bytes,
            'height':       int(shape[1]),
            'width':        int(shape[2]),
            'dtype':        dtype.str,
            'n_frames':     int(shape[0]),
        },
    }


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_sv_ramp_spin', __name__)
    is_user_in_project = helpers['is_user_in_project']

    # ── local dev test route: serve a test_data file; browser renders it ───────

    @bp.route('/localfile/<filename>')
    @auth.oidc_auth('orcid')
    def localfile(filename):
        return send_from_directory(_TEST_DATA_DIR, filename, conditional=True)

    @bp.route('/local/<filename>')
    @auth.oidc_auth('orcid')
    def local_view(filename):
        browser_url = f'{request.script_root}{URL_PREFIX}/localfile/{filename}'
        data = _local_meta(filename, browser_url)
        return render_template(
            'dataset_views/sv_ramp_spin.html',
            ds={'dataset_name': filename, 'unique_id': None},
            project_id=None,
            sv_array=data['sv_array'], imavg_up=data['imavg_up'],
            imavg_down=data['imavg_down'], asym_array=data['asym_array'],
            n_frames=data['n_frames'],
            base_url=f'{request.script_root}{URL_PREFIX}/local/{filename}',
            stream=data['stream'],
        )

    # ── Crucible-backed route (browser-side Range) ─────────────────────────────

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds = get_user_client().datasets.get(dsid)
        meta = _ensure_meta(dsid, get_user_client())
        return render_template(
            'dataset_views/sv_ramp_spin.html',
            ds=ds, project_id=project_id,
            sv_array=meta['sv_array'], imavg_up=meta['imavg_up'],
            imavg_down=meta['imavg_down'], asym_array=meta['asym_array'],
            n_frames=meta['n_frames'],
            base_url=f'{request.script_root}{URL_PREFIX}/{project_id}/{dsid}',
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

    return bp
