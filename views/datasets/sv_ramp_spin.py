"""
sv_ramp_spin dataset view — spin-polarized SV ramp.

Streams individual frames via HTTP Range requests (Crucible route) or
reads directly via h5py (local test route).

Up/Down frames are served as grayscale PNGs.
Difference and Asymmetry frames are rendered with the RdBu_r colormap.
"""

import io
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import fsspec
import h5py
import numpy as np
import requests as _requests
from utils.auth import get_user_client
from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request
from matplotlib import colormaps
from PIL import Image

MEASUREMENT_TYPES = ['sv_ramp_spin']
URL_PREFIX = '/dataset-view/sv-ramp-spin'
LABEL = 'SV Ramp Spin Viewer'

_URL_TTL = 600
_TEST_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'test_data')

# {dsid: { sv_array, imavg_up, imavg_down, asym_array, n_frames,
#           url, url_at, filename, up_offset, down_offset, frame_bytes, shape, dtype }}
_cache: dict[str, dict] = {}

_FRAME_CACHE_SIZE = 20
_frame_cache: dict[tuple, bytes] = {}


def _get_cached_frame(key):
    raw = _frame_cache.get(key)
    if raw is not None:
        _frame_cache[key] = _frame_cache.pop(key)
    return raw


def _put_cached_frame(key, raw):
    if key in _frame_cache:
        _frame_cache[key] = _frame_cache.pop(key)
    else:
        if len(_frame_cache) >= _FRAME_CACHE_SIZE:
            _frame_cache.pop(next(iter(_frame_cache)))
        _frame_cache[key] = raw


def _fetch_range(url, offset, frame_bytes, fi):
    start = offset + fi * frame_bytes
    end = start + frame_bytes - 1
    resp = _requests.get(url, headers={'Range': f'bytes={start}-{end}'}, timeout=30)
    if resp.status_code not in (200, 206):
        abort(502)
    return resp.content


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

        frame_bytes = int(shape[1]) * int(shape[2]) * dtype.itemsize
        entry = {
            'filename': filename, 'mfid': mfid, 'url': url, 'url_at': now,
            'sv_array': sv_array, 'imavg_up': imavg_up,
            'imavg_down': imavg_down, 'asym_array': asym_array,
            'n_frames': shape[0], 'up_offset': up_offset,
            'down_offset': down_offset, 'frame_bytes': frame_bytes,
            'shape': shape, 'dtype': dtype,
        }
        _cache[dsid] = entry

    elif (now - entry['url_at']) >= _URL_TTL:
        links = crucible_client.datasets.get_download_links(dsid)
        entry['url'] = links.get(entry['mfid'])
        entry['url_at'] = now

    return entry


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

    # ── local test route ──────────────────────────────────────────────────────

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

    # ── Crucible-backed route ─────────────────────────────────────────────────

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
        )

    @bp.route('/<project_id>/<dsid>/frame')
    @auth.oidc_auth('orcid')
    def frame(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        fi = request.args.get('fi', type=int)
        channel = request.args.get('channel', default='up')
        vmin = request.args.get('vmin', type=float)
        vmax = request.args.get('vmax', type=float)
        if fi is None:
            abort(400)

        meta = _ensure_meta(dsid, get_user_client())
        if not (0 <= fi < meta['n_frames']):
            abort(400)

        cache_key = (dsid, fi, channel, vmin, vmax)
        png = _get_cached_frame(cache_key)
        if png is None:
            up_raw = _fetch_range(meta['url'], meta['up_offset'], meta['frame_bytes'], fi) \
                if channel in ('up', 'diff', 'asym') else None
            down_raw = _fetch_range(meta['url'], meta['down_offset'], meta['frame_bytes'], fi) \
                if channel in ('down', 'diff', 'asym') else None
            png = _make_png(channel, up_raw, down_raw, meta['shape'], meta['dtype'], vmin, vmax)
            _put_cached_frame(cache_key, png)

        return Response(png, mimetype='image/png')

    @bp.route('/<project_id>/<dsid>/roi')
    @auth.oidc_auth('orcid')
    def roi(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        x0 = request.args.get('x0', type=int)
        y0 = request.args.get('y0', type=int)
        x1 = request.args.get('x1', type=int)
        y1 = request.args.get('y1', type=int)
        if any(v is None for v in [x0, y0, x1, y1]):
            abort(400)

        meta = _ensure_meta(dsid, get_user_client())
        H, W = meta['shape'][1], meta['shape'][2]
        x0, x1 = sorted([max(0, x0), min(W - 1, x1)])
        y0, y1 = sorted([max(0, y0), min(H - 1, y1)])

        row_bytes = W * meta['dtype'].itemsize
        roi_bytes = (y1 - y0 + 1) * row_bytes
        n_frames = meta['n_frames']
        url = meta['url']
        dtype = meta['dtype']

        def fetch_mean(offset, fi):
            start = offset + fi * meta['frame_bytes'] + y0 * row_bytes
            resp = _requests.get(url, headers={'Range': f'bytes={start}-{start + roi_bytes - 1}'}, timeout=30)
            rows = np.frombuffer(resp.content, dtype=dtype).reshape(y1 - y0 + 1, W)
            return float(rows[:, x0:x1 + 1].astype(np.float64).mean())

        with ThreadPoolExecutor(max_workers=8) as ex:
            up_futs = {ex.submit(fetch_mean, meta['up_offset'], fi): fi for fi in range(n_frames)}
            down_futs = {ex.submit(fetch_mean, meta['down_offset'], fi): fi for fi in range(n_frames)}

        imavg_up = [f.result() for f in sorted(up_futs, key=up_futs.get)]
        imavg_down = [f.result() for f in sorted(down_futs, key=down_futs.get)]

        up_arr = np.array(imavg_up)
        down_arr = np.array(imavg_down)
        total = up_arr + down_arr
        asym = np.where(total > 0, (up_arr - down_arr) / total, 0.0).tolist()

        return jsonify({'imavg_up': imavg_up, 'imavg_down': imavg_down, 'asym': asym})

    return bp
