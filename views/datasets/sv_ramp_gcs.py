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

import time

import fsspec
import h5py
from flask import Blueprint, abort, jsonify, render_template

from utils.auth import get_user_client

MEASUREMENT_TYPES = ['sv_ramp']
URL_PREFIX = '/dataset-view/sv-ramp-gcs'
LABEL = 'SV Ramp Viewer'

_URL_TTL = 600  # seconds — refresh signed URL before it expires

# {dsid: {url, url_at, sv_array, imavg_array, n_frames,
#          data_offset, frame_bytes, height, width, dtype}}
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
            offset   = im_ds.id.get_offset()  # byte offset of raw data in file

        if offset is None:
            abort(500)  # dataset is chunked/unallocated — Range streaming impossible

        frame_bytes = int(shape[1]) * int(shape[2]) * dtype.itemsize
        entry = {
            'url':         url,
            'url_at':      now,
            'sv_array':    sv_array,
            'imavg_array': imavg,
            'n_frames':    int(shape[0]),
            'data_offset': int(offset),
            'frame_bytes': frame_bytes,
            'height':      int(shape[1]),
            'width':       int(shape[2]),
            'dtype':       dtype.str,        # e.g. '<u2'
        }
        _cache[dsid] = entry

    elif (now - entry['url_at']) >= _URL_TTL:
        entry['url']    = _find_h5_url(crucible_client, dsid)
        entry['url_at'] = now

    return entry


def _stream_spec(entry: dict) -> dict:
    return {
        'url':         entry['url'],
        'data_offset': entry['data_offset'],
        'frame_bytes': entry['frame_bytes'],
        'height':      entry['height'],
        'width':       entry['width'],
        'dtype':       entry['dtype'],
        'n_frames':    entry['n_frames'],
    }


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_sv_ramp_gcs', __name__)
    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds   = get_user_client().datasets.get(dsid)
        meta = _ensure_meta(dsid, get_user_client())
        return render_template(
            'dataset_views/sv_ramp_gcs.html',
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

    return bp
