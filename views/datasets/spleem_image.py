"""
spleem_image dataset view — spin-polarized LEEM image series.

Images stored as (n_acq, 2, H, W) uint16, chunked as (1, 2, H, W).
Each chunk holds one full acquisition (both spin channels, 4 MB).
Frames are fetched via HTTP Range requests using per-chunk byte offsets.
Averages are computed once from all chunks and cached server-side.
"""

import io
import os
import time

import fsspec
import h5py
import numpy as np
import requests as _requests
from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request
from matplotlib import colormaps
from PIL import Image

MEASUREMENT_TYPES = ['spleem_image']
URL_PREFIX = '/dataset-view/spleem-image'
LABEL = 'SPLEEM Image Viewer'

_URL_TTL = 600

# {dsid: { n_acq, shape, dtype, ch_bytes, chunk_offsets,
#           url, url_at, filename, avg_up, avg_down }}
_cache: dict[str, dict] = {}

_FRAME_CACHE_SIZE = 30
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


def _ensure_meta(dsid, crucible_client):
    now = time.monotonic()
    entry = _cache.get(dsid)

    if entry is None:
        associated = crucible_client.get_associated_files(dsid)
        match = next((f for f in associated if f['filename'].endswith('.h5')), None)
        if not match:
            abort(404)
        filename = os.path.basename(match['filename'])
        links = crucible_client.get_dataset_download_links(dsid)
        url = links.get(f'{dsid}/{filename}')
        if not url:
            abort(404)

        fo = fsspec.open(url, 'rb').open()
        with h5py.File(fo, 'r') as h5:
            im_ds = h5['measurement/SPLEEM_image/images']
            shape = im_ds.shape   # (n_acq, 2, H, W)
            dtype = im_ds.dtype
            n_chunks = im_ds.id.get_num_chunks()
            # Map acquisition index → byte offset of its chunk in the file.
            # Each chunk covers (1, 2, H, W) = both channels for one acquisition.
            chunk_offsets = {}
            for i in range(n_chunks):
                info = im_ds.id.get_chunk_info(i)
                acq_idx = info.chunk_offset[0]
                chunk_offsets[acq_idx] = info.byte_offset

        # Bytes for one channel within a chunk: H × W × itemsize
        ch_bytes = int(shape[2]) * int(shape[3]) * dtype.itemsize
        entry = {
            'filename': filename, 'url': url, 'url_at': now,
            'n_acq': shape[0], 'shape': shape, 'dtype': dtype,
            'ch_bytes': ch_bytes, 'chunk_offsets': chunk_offsets,
            'avg_up': None, 'avg_down': None,
        }
        _cache[dsid] = entry

    elif (now - entry['url_at']) >= _URL_TTL:
        links = crucible_client.get_dataset_download_links(dsid)
        entry['url'] = links.get(f'{dsid}/{entry["filename"]}')
        entry['url_at'] = now

    return entry


def _fetch_channel(url, chunk_offsets, fi, ch, ch_bytes):
    """Fetch a single channel for acquisition fi via Range request."""
    base = chunk_offsets.get(fi)
    if base is None:
        abort(404)
    start = base + ch * ch_bytes
    resp = _requests.get(url, headers={'Range': f'bytes={start}-{start + ch_bytes - 1}'}, timeout=30)
    if resp.status_code not in (200, 206):
        abort(502)
    return resp.content


def _fetch_chunk(url, chunk_offsets, fi, ch_bytes):
    """Fetch the full chunk (both channels) for acquisition fi."""
    base = chunk_offsets.get(fi)
    if base is None:
        return None
    total = 2 * ch_bytes
    resp = _requests.get(url, headers={'Range': f'bytes={base}-{base + total - 1}'}, timeout=30)
    if resp.status_code not in (200, 206):
        abort(502)
    return resp.content


def _ensure_averages(entry):
    """Fetch all chunks and compute per-channel averages (cached per dataset)."""
    if entry['avg_up'] is not None:
        return
    H, W = entry['shape'][2], entry['shape'][3]
    dtype = entry['dtype']
    ch_bytes = entry['ch_bytes']
    acc_up   = np.zeros((H, W), dtype=np.float64)
    acc_down = np.zeros((H, W), dtype=np.float64)
    n = 0
    for fi, base in entry['chunk_offsets'].items():
        raw = _fetch_chunk(entry['url'], entry['chunk_offsets'], fi, ch_bytes)
        if raw is None:
            continue
        chunk = np.frombuffer(raw, dtype=dtype).reshape(2, H, W).astype(np.float64)
        acc_up   += chunk[0]
        acc_down += chunk[1]
        n += 1
    if n:
        entry['avg_up']   = acc_up   / n
        entry['avg_down'] = acc_down / n
    else:
        entry['avg_up']   = acc_up
        entry['avg_down'] = acc_down


def _channel_arr(up, down, channel):
    if channel == 'up':   return up
    if channel == 'down': return down
    if channel == 'diff': return up - down
    total = up + down
    return np.where(total > 0, (up - down) / total, 0.0)


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


def _arr_to_png(arr, channel, vmin, vmax):
    if channel in ('up', 'down'):
        return _to_png_gray(arr, vmin, vmax)
    return _to_png_rdbu(arr, vmin, vmax)


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_spleem_image', __name__)
    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds   = current_app.crucible_client.get_dataset(dsid)
        meta = _ensure_meta(dsid, current_app.crucible_client)
        return render_template(
            'dataset_views/spleem_image.html',
            ds=ds, project_id=project_id,
            n_acq=meta['n_acq'],
            base_url=f'{URL_PREFIX}/{project_id}/{dsid}',
        )

    @bp.route('/<project_id>/<dsid>/frame')
    @auth.oidc_auth('orcid')
    def frame(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        fi      = request.args.get('fi', type=int)
        channel = request.args.get('channel', default='up')
        vmin    = request.args.get('vmin', type=float)
        vmax    = request.args.get('vmax', type=float)
        if fi is None:
            abort(400)

        meta = _ensure_meta(dsid, current_app.crucible_client)
        if fi not in meta['chunk_offsets']:
            abort(404)

        cache_key = (dsid, fi, channel, vmin, vmax)
        png = _get_cached_frame(cache_key)
        if png is None:
            H, W = meta['shape'][2], meta['shape'][3]
            dtype = meta['dtype']
            ch_bytes = meta['ch_bytes']
            if channel in ('diff', 'asym'):
                # Fetch full chunk (both channels) in one request
                raw = _fetch_chunk(meta['url'], meta['chunk_offsets'], fi, ch_bytes)
                chunk = np.frombuffer(raw, dtype=dtype).reshape(2, H, W).astype(np.float64)
                arr = _channel_arr(chunk[0], chunk[1], channel)
            else:
                ch = 0 if channel == 'up' else 1
                raw = _fetch_channel(meta['url'], meta['chunk_offsets'], fi, ch, ch_bytes)
                arr = np.frombuffer(raw, dtype=dtype).reshape(H, W).astype(np.float64)
            png = _arr_to_png(arr, channel, vmin, vmax)
            _put_cached_frame(cache_key, png)

        return Response(png, mimetype='image/png')

    @bp.route('/<project_id>/<dsid>/average')
    @auth.oidc_auth('orcid')
    def average(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        channel = request.args.get('channel', default='up')
        vmin    = request.args.get('vmin', type=float)
        vmax    = request.args.get('vmax', type=float)

        meta = _ensure_meta(dsid, current_app.crucible_client)
        _ensure_averages(meta)
        arr = _channel_arr(meta['avg_up'], meta['avg_down'], channel)
        return Response(_arr_to_png(arr, channel, vmin, vmax), mimetype='image/png')

    @bp.route('/<project_id>/<dsid>/linecut')
    @auth.oidc_auth('orcid')
    def linecut(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        x0      = request.args.get('x0', type=int)
        y0      = request.args.get('y0', type=int)
        x1      = request.args.get('x1', type=int)
        y1      = request.args.get('y1', type=int)
        channel = request.args.get('channel', default='up')
        if any(v is None for v in [x0, y0, x1, y1]):
            abort(400)

        meta = _ensure_meta(dsid, current_app.crucible_client)
        _ensure_averages(meta)
        arr  = _channel_arr(meta['avg_up'], meta['avg_down'], channel)
        H, W = arr.shape

        x0, x1 = max(0, x0), min(W - 1, x1)
        y0, y1 = max(0, y0), min(H - 1, y1)

        n = max(int(np.hypot(x1 - x0, y1 - y0)), 2)
        xs = np.linspace(x0, x1, n)
        ys = np.linspace(y0, y1, n)
        xi = np.clip(np.round(xs).astype(int), 0, W - 1)
        yi = np.clip(np.round(ys).astype(int), 0, H - 1)

        return jsonify({
            'distance':  np.sqrt((xs - x0) ** 2 + (ys - y0) ** 2).tolist(),
            'intensity': arr[yi, xi].tolist(),
        })

    return bp
