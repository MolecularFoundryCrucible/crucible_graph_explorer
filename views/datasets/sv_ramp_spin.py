"""
sv_ramp_spin dataset view — spin-polarized SV ramp.

Crucible path: the server reads the contiguous up/down im_array byte offsets,
frame shape and dtype once, then hands the browser a signed URL plus that spec.
The browser issues its own HTTP Range requests per frame, decodes the raw bytes
and renders to a canvas client-side (grayscale for up/down, RdBu_r for
difference/asymmetry). ROI IV curves are computed in the browser from per-frame
Range reads of the selected rows.

Local path (dev only): reads test_data files via h5py and serves frame PNGs
server-side, unchanged.

Requires bucket CORS to allow GET with the Range request header and to expose
Content-Range (see cors.json).
"""

import io
import os
import time

import fsspec
import h5py
import numpy as np
from flask import Blueprint, Response, abort, jsonify, render_template, request
from matplotlib import colormaps
from PIL import Image

from utils.auth import get_user_client

MEASUREMENT_TYPES = ['sv_ramp_spin']
URL_PREFIX = '/dataset-view/sv-ramp-spin'
LABEL = 'SV Ramp Spin Viewer'

_URL_TTL = 600
_TEST_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'test_data')

# {dsid: { sv_array, imavg_up, imavg_down, asym_array, n_frames,
#           url, url_at, filename, mfid, up_offset, down_offset,
#           frame_bytes, height, width, dtype }}
_cache: dict[str, dict] = {}


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
            up_offset = up_ds.id.get_offset()
            down_offset = down_ds.id.get_offset()

        if up_offset is None or down_offset is None:
            abort(500)  # chunked/unallocated — Range streaming impossible

        frame_bytes = int(shape[1]) * int(shape[2]) * dtype.itemsize
        entry = {
            'filename': filename, 'mfid': mfid, 'url': url, 'url_at': now,
            'sv_array': sv_array, 'imavg_up': imavg_up,
            'imavg_down': imavg_down, 'asym_array': asym_array,
            'n_frames': int(shape[0]), 'up_offset': int(up_offset),
            'down_offset': int(down_offset), 'frame_bytes': frame_bytes,
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
        'url':         entry['url'],
        'up_offset':   entry['up_offset'],
        'down_offset': entry['down_offset'],
        'frame_bytes': entry['frame_bytes'],
        'height':      entry['height'],
        'width':       entry['width'],
        'dtype':       entry['dtype'],
        'n_frames':    entry['n_frames'],
    }


# ── local-only PNG rendering (dev test route) ──────────────────────────────────

def _to_png_gray(arr, vmin, vmax):
    arr = arr.astype(np.float32)
    lo = float(vmin) if vmin is not None else float(np.percentile(arr, 2))
    hi = float(vmax) if vmax is not None else float(np.percentile(arr, 98))
    if hi <= lo:
        hi = lo + 1.0
    arr = np.clip((arr - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, mode='L').save(buf, format='PNG')
    return buf.getvalue()


def _to_png_rdbu(arr, vmin, vmax):
    arr = arr.astype(np.float32)
    finite = arr[np.isfinite(arr)]
    if vmin is None or vmax is None:
        v = float(np.percentile(np.abs(finite), 98)) if len(finite) else 1.0
        lo, hi = -v, v
    else:
        lo, hi = float(vmin), float(vmax)
    if hi <= lo:
        hi = lo + 1.0
    normed = np.clip((arr - lo) / (hi - lo), 0, 1)
    rgba = (colormaps['RdBu_r'](normed) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgba, mode='RGBA').save(buf, format='PNG')
    return buf.getvalue()


def _make_png(channel, up_raw, down_raw, shape, dtype, vmin, vmax):
    def decode(raw):
        return np.frombuffer(raw, dtype=dtype).reshape(shape[1], shape[2]).astype(np.float32)

    if channel == 'up':
        return _to_png_gray(decode(up_raw), vmin, vmax)
    elif channel == 'down':
        return _to_png_gray(decode(down_raw), vmin, vmax)
    elif channel == 'diff':
        return _to_png_rdbu(decode(up_raw) - decode(down_raw), vmin, vmax)
    else:  # asym
        u, d = decode(up_raw), decode(down_raw)
        total = u + d
        asym = np.where(total > 0, (u - d) / total, np.nan)
        return _to_png_rdbu(np.nan_to_num(asym, nan=0.0), vmin, vmax)


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_sv_ramp_spin', __name__)
    is_user_in_project = helpers['is_user_in_project']

    # ── local test route (dev only, server-rendered PNG) ───────────────────────

    @bp.route('/local/<filename>')
    @auth.oidc_auth('orcid')
    def local_view(filename):
        path = os.path.join(_TEST_DATA_DIR, filename)
        with h5py.File(path, 'r') as h5:
            meas = h5['measurement/sv_ramp_spin']
            sv_array = meas['0000_sv_array'][:].tolist()
            imavg_up = meas['000_imavg_up_array'][:].tolist()
            imavg_down = meas['000_imavg_down_array'][:].tolist()
            asym_array = meas['000_asym_array'][:].tolist()
            n_frames = int(meas['000_im_up_array'].shape[0])
        return render_template(
            'dataset_views/sv_ramp_spin.html',
            ds={'dataset_name': filename, 'unique_id': None},
            project_id=None,
            sv_array=sv_array, imavg_up=imavg_up,
            imavg_down=imavg_down, asym_array=asym_array,
            n_frames=n_frames,
            base_url=f'{request.script_root}{URL_PREFIX}/local/{filename}',
            stream=None,
        )

    @bp.route('/local/<filename>/frame')
    @auth.oidc_auth('orcid')
    def local_frame(filename):
        fi = request.args.get('fi', type=int)
        channel = request.args.get('channel', default='up')
        vmin = request.args.get('vmin', type=float)
        vmax = request.args.get('vmax', type=float)
        if fi is None:
            abort(400)
        path = os.path.join(_TEST_DATA_DIR, filename)
        with h5py.File(path, 'r') as h5:
            meas = h5['measurement/sv_ramp_spin']
            shape = meas['000_im_up_array'].shape
            dtype = meas['000_im_up_array'].dtype
            if not (0 <= fi < shape[0]):
                abort(400)
            up_raw = meas['000_im_up_array'][fi].tobytes() if channel in ('up', 'diff', 'asym') else None
            down_raw = meas['000_im_down_array'][fi].tobytes() if channel in ('down', 'diff', 'asym') else None
        return Response(_make_png(channel, up_raw, down_raw, shape, dtype, vmin, vmax),
                        mimetype='image/png')

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
