import io
import json
import os

import h5py
import numpy as np
import requests
from utils.auth import get_user_client
from flask import Blueprint, abort, current_app, render_template

MEASUREMENT_TYPES = ['arres_ek', 'arres_mm']
URL_PREFIX = '/dataset-view/arres'
LABEL = 'ARRES Viewer'

_TEST_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'test_data')


def _read_arres(f):
    """Read ARRES data from an open h5py.File. Returns a dict with type, axes, and spin arrays."""
    if 'measurement/ARRES_EK' in f:
        m = f['measurement/ARRES_EK']
        spectrum = m['spectrum'][:]   # (2, n_eV, n_k)
        eV = m['eV'][:]               # (n_eV,)
        uv = m['uv'][:]               # (n_k, 2)
        # Use signed u-coordinate to preserve direction along the k-line
        x = uv[:, 0]
        return {
            'type': 'arres_ek',
            'spectrum': spectrum,
            'x': x.tolist(),
            'y': eV.tolist(),
            'x_label': 'k (r.l.u.)',
            'y_label': 'Energy (eV)',
        }
    elif 'measurement/ARRES_MM' in f:
        m = f['measurement/ARRES_MM']
        # loop_order is spin_ky_kx, so spectrum[spin, ky_idx, kx_idx]
        spectrum = m['spectrum'][:]   # (2, n_ky, n_kx)
        kx = m['kx'][:]              # (n_kx,)
        ky = m['ky'][:]              # (n_ky,)
        return {
            'type': 'arres_mm',
            'spectrum': spectrum,
            'x': kx.tolist(),
            'y': ky.tolist(),
            'x_label': 'kx (px)',
            'y_label': 'ky (px)',
        }
    return None


def _build_payload(data):
    """Build the JSON payload sent to the client for client-side rendering."""
    up   = data['spectrum'][0].astype(float)
    down = data['spectrum'][1].astype(float)
    diff = up - down
    total = up + down
    with np.errstate(invalid='ignore', divide='ignore'):
        pol = np.where(total != 0, diff / total, np.nan)

    def stats(arr):
        finite = arr[np.isfinite(arr)]
        return {
            'p1':  float(np.percentile(finite, 1)),
            'p99': float(np.percentile(finite, 99)),
            'min': float(finite.min()),
            'max': float(finite.max()),
        }

    # Replace NaN with None so JSON serialization works
    def to_list(arr):
        return [[None if np.isnan(v) else v for v in row] for row in arr.tolist()]

    return json.dumps({
        'scan_type': data['type'],
        'x':       data['x'],
        'y':       data['y'],
        'x_label': data['x_label'],
        'y_label': data['y_label'],
        'data': {
            'up':   to_list(up),
            'down': to_list(down),
            'diff': to_list(diff),
            'pol':  to_list(pol),
        },
        'stats': {
            'up':   stats(up),
            'down': stats(down),
            'diff': stats(diff),
            'pol':  stats(pol),
        },
    })


def _fetch_h5_bytes(dsid):
    """Download the first .h5 file for a dataset and return its bytes."""
    ds = get_user_client().datasets.get(dsid)
    associated_files = get_user_client().datasets.get_associated_files(dsid)
    try:
        download_links = get_user_client().datasets.get_download_links(dsid)
    except Exception:
        download_links = {}

    h5_file = next((f for f in associated_files if f['filename'].endswith('.h5')), None)
    if not h5_file:
        return None, None, 'No .h5 file found for this dataset.'

    basename = os.path.basename(h5_file['filename'])
    url = download_links.get(h5_file['mfid'])
    if not url:
        return None, None, 'Download link not available for the .h5 file.'

    resp = requests.get(url, timeout=120)
    if resp.status_code != 200:
        return None, None, f'Failed to download .h5 file (HTTP {resp.status_code}).'

    return resp.content, ds, None


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_arres', __name__)
    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/local/<filename>')
    @auth.oidc_auth('orcid')
    def local_view(filename):
        path = os.path.join(_TEST_DATA_DIR, filename)
        if not os.path.isfile(path):
            abort(404)
        with h5py.File(path, 'r') as f:
            data = _read_arres(f)
        if data is None:
            abort(400)
        return render_template(
            'dataset_views/arres.html',
            title=filename,
            scan_type=data['type'],
            payload=_build_payload(data),
        )

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        content, ds, error = _fetch_h5_bytes(dsid)
        if error:
            abort(404)
        with h5py.File(io.BytesIO(content), 'r') as f:
            data = _read_arres(f)
        if data is None:
            abort(400)
        return render_template(
            'dataset_views/arres.html',
            title=ds['dataset_name'],
            scan_type=data['type'],
            payload=_build_payload(data),
        )

    return bp
