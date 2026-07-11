"""
spleem_image dataset view — spin-polarized LEEM image series.

Images stored as (n_acq, 2, H, W) uint16, chunked as (1, 2, H, W) with one
uncompressed chunk per acquisition (both spin channels, contiguous).  The
server reads each chunk's byte offset once via h5py and hands the browser a
signed URL plus the per-acquisition offsets, channel byte length, shape and
dtype.  The browser issues its own HTTP Range requests per acquisition/channel,
decodes the raw bytes and renders to a canvas client-side (grayscale for
up/down, RdBu_r for difference/asymmetry).  Averages and linecuts are computed
in the browser from Range reads of the chunks.

Requires bucket CORS to allow GET with the Range request header and to expose
Content-Range (see cors.json).
"""

import os
import time

import fsspec
import h5py
from flask import Blueprint, abort, jsonify, render_template, request, send_from_directory

from utils.auth import get_user_client

MEASUREMENT_TYPES = ['spleem_image']
DATA_TYPE_STEMS = ['ScopeFoundryH5.qspleem_spleem_image']
URL_PREFIX = '/dataset-view/spleem-image'
LABEL = 'SPLEEM Image Viewer'

_URL_TTL = 600

# Directory of local .h5 files for the /local dev test route (not deployed to prod).
_TEST_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'test_data')

# {dsid: { n_acq, height, width, dtype, ch_bytes, chunk_offsets, acqs,
#           url, url_at, filename, mfid }}
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
            im_ds = h5['measurement/SPLEEM_image/images']
            shape = im_ds.shape   # (n_acq, 2, H, W)
            dtype = im_ds.dtype
            n_chunks = im_ds.id.get_num_chunks()
            # acquisition index → byte offset of its (1, 2, H, W) chunk
            chunk_offsets = {}
            for i in range(n_chunks):
                info = im_ds.id.get_chunk_info(i)
                acq_idx = int(info.chunk_offset[0])
                chunk_offsets[str(acq_idx)] = int(info.byte_offset)

        ch_bytes = int(shape[2]) * int(shape[3]) * dtype.itemsize
        entry = {
            'filename': filename, 'mfid': mfid, 'url': url, 'url_at': now,
            'n_acq': int(shape[0]), 'height': int(shape[2]), 'width': int(shape[3]),
            'dtype': dtype.str, 'ch_bytes': ch_bytes,
            'chunk_offsets': chunk_offsets,
            'acqs': sorted(int(k) for k in chunk_offsets),
        }
        _cache[dsid] = entry

    elif (now - entry['url_at']) >= _URL_TTL:
        links = crucible_client.datasets.get_download_links(dsid)
        entry['url'] = links.get(entry['mfid'])
        entry['url_at'] = now

    return entry


def _stream_spec(entry):
    return {
        'url':           entry['url'],
        'chunk_offsets': entry['chunk_offsets'],
        'acqs':          entry['acqs'],
        'ch_bytes':      entry['ch_bytes'],
        'height':        entry['height'],
        'width':         entry['width'],
        'dtype':         entry['dtype'],
        'n_acq':         entry['n_acq'],
    }


def _local_meta(filename: str, browser_url: str) -> dict:
    """Read chunk offsets from a local test_data file for the /local dev route.

    Mirrors _ensure_meta but reads a local path directly with h5py; the stream url
    points at the /localfile route so the browser Range-fetches it same-origin.
    """
    path = os.path.join(_TEST_DATA_DIR, filename)
    if not os.path.isfile(path):
        abort(404)
    with h5py.File(path, 'r') as h5:
        im_ds = h5['measurement/SPLEEM_image/images']
        shape = im_ds.shape   # (n_acq, 2, H, W)
        dtype = im_ds.dtype
        n_chunks = im_ds.id.get_num_chunks()
        chunk_offsets = {}
        for i in range(n_chunks):
            info = im_ds.id.get_chunk_info(i)
            chunk_offsets[str(int(info.chunk_offset[0]))] = int(info.byte_offset)
    ch_bytes = int(shape[2]) * int(shape[3]) * dtype.itemsize
    return {
        'n_acq': int(shape[0]),
        'stream': {
            'url':           browser_url,
            'chunk_offsets': chunk_offsets,
            'acqs':          sorted(int(k) for k in chunk_offsets),
            'ch_bytes':      ch_bytes,
            'height':        int(shape[2]),
            'width':         int(shape[3]),
            'dtype':         dtype.str,
            'n_acq':         int(shape[0]),
        },
    }


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_spleem_image', __name__)
    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds   = get_user_client().datasets.get(dsid)
        meta = _ensure_meta(dsid, get_user_client())
        return render_template(
            'dataset_views/spleem_image.html',
            ds=ds, project_id=project_id,
            n_acq=meta['n_acq'],
            base_url=f'{request.script_root}{URL_PREFIX}/{project_id}/{dsid}',
            stream=_stream_spec(meta),
        )

    @bp.route('/<project_id>/<dsid>/stream-spec')
    @auth.oidc_auth('orcid')
    def stream_spec(project_id, dsid):
        """Return a fresh signed URL + chunk-offset spec for browser Range fetches."""
        if not is_user_in_project(project_id):
            abort(403)
        meta = _ensure_meta(dsid, get_user_client())
        return jsonify(_stream_spec(meta))

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
            'dataset_views/spleem_image.html',
            ds={'dataset_name': filename, 'unique_id': None},
            project_id=None,
            n_acq=data['n_acq'],
            base_url=f'{request.script_root}{URL_PREFIX}/local/{filename}',
            stream=data['stream'],
        )

    return bp
