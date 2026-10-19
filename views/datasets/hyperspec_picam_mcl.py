import os

import h5py
import numpy as np
from cachetools import TTLCache
from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request

from utils.auth import get_user_client

MEASUREMENT_TYPES = ['hyperspec_picam_mcl']
URL_PREFIX = '/dataset-view/hyperspec-picam-mcl'
LABEL = 'Hyperspectral Viewer'

X_AXES = {
    'wls':          {'key': 'wls',         'label': 'Wavelength (nm)'},
    'wave_numbers': {'key': 'wave_numbers', 'label': 'Wave numbers (cm⁻¹)'},
    'raman_shifts': {'key': 'raman_shifts', 'label': 'Raman shift (cm⁻¹)'},
}

_DOWNLOAD_DIR = os.environ.get('CRUCIBLE_DOWNLOAD_DIR', 'crucible-downloads')

# Open h5py.File objects keyed by dsid.  Evicted after 1 h or when holding
# more than 16 files simultaneously (re-opened transparently on next access).
_h5_cache: TTLCache = TTLCache(maxsize=16, ttl=3600)

# Full spec_map arrays (shape: Ny, Nx, Nspec) — pure numpy indexing on hits.
_spec_map_cache: TTLCache = TTLCache(maxsize=16, ttl=3600)


def _get_h5(dsid, crucible_client):
    """Return a cached local h5py.File for dsid, downloading on first access.

    download_dataset keys files as "{dsid}/{basename}", so the local path is
    crucible-downloads/{dsid}/{basename}.  If the file is already on disk from
    a previous request or a different worker, we open it directly without any
    API call.
    """
    if dsid not in _h5_cache:
        dsid_dir = os.path.join(_DOWNLOAD_DIR, dsid)
        # Fast path: file already on disk (e.g. downloaded by another worker)
        if os.path.isdir(dsid_dir):
    
            existing = [f for f in os.listdir(dsid_dir) if f.endswith('.h5')]
            if existing:
                _h5_cache[dsid] = h5py.File(os.path.join(dsid_dir, existing[0]), 'r')
                return _h5_cache[dsid]
        # Slow path: fetch filename from API and download
        associated_files = crucible_client.datasets.list_files(dsid)
        h5_file = next((f for f in associated_files if f['filename'].endswith('.h5')), None)
        if not h5_file:
            abort(404)
        filename = os.path.basename(h5_file['filename'])
        crucible_client.datasets.download(dsid, file_name=f'{dsid}/{filename}',
                                          output_dir=_DOWNLOAD_DIR)
        _h5_cache[dsid] = h5py.File(os.path.join(dsid_dir, filename), 'r')
    return _h5_cache[dsid]


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_hyperspec_picam_mcl', __name__)
    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds = get_user_client().datasets.get(dsid)
        h5 = _get_h5(dsid, get_user_client())
        meas = h5['measurement/hyperspec_picam_mcl']
        h_array = meas['h_array'][:].tolist()
        v_array = meas['v_array'][:].tolist()
        axes = [k for k in X_AXES if k in meas]
        return render_template(
            'dataset_views/hyperspec_picam_mcl.html',
            project_id=project_id,
            ds=ds,
            h_array=h_array,
            v_array=v_array,
            available_axes=axes,
            x_axis_labels={k: X_AXES[k]['label'] for k in axes},
        )

    @bp.route('/<project_id>/<dsid>/map')
    @auth.oidc_auth('orcid')
    def map_data(project_id, dsid):
        """Return summed-intensity spatial map, optionally over a spectral sub-range.

        Query params:
            x_axis   - one of wls / wave_numbers / raman_shifts  (default: wls)
            spec_min - lower bound in x_axis units (optional)
            spec_max - upper bound in x_axis units (optional)
        """
        if not is_user_in_project(project_id):
            abort(403)

        x_axis   = request.args.get('x_axis', 'wls')
        spec_min = request.args.get('spec_min', type=float)
        spec_max = request.args.get('spec_max', type=float)

        h5   = _get_h5(dsid, get_user_client())
        meas = h5['measurement/hyperspec_picam_mcl']
        h_array = meas['h_array'][:].tolist()
        v_array = meas['v_array'][:].tolist()
        x_vals  = meas[x_axis if x_axis in meas else 'wls'][:]
        if spec_min is not None or spec_max is not None:
            lo   = spec_min if spec_min is not None else float(x_vals.min())
            hi   = spec_max if spec_max is not None else float(x_vals.max())
            idxs = np.where((x_vals >= min(lo, hi)) & (x_vals <= max(lo, hi)))[0]
            img  = meas['spec_map'][0, :, :, int(idxs[0]):int(idxs[-1]) + 1].sum(axis=2) \
                   if len(idxs) else np.zeros((len(v_array), len(h_array)))
        else:
            img = meas['spec_map'][0, :, :, :].sum(axis=2)

        return jsonify({
            'h_array':  h_array,
            'v_array':  v_array,
            'map_data': img.tolist(),
            'x_values': x_vals.tolist(),
            'x_label':  X_AXES.get(x_axis, X_AXES['wls'])['label'],
        })

    @bp.route('/<project_id>/<dsid>/spectrum')
    @auth.oidc_auth('orcid')
    def spectrum(project_id, dsid):
        """Return spectrum at pixel (xi, yi) — x-axis is cached client-side.

        Query params:
            xi – horizontal index (required)
            yi – vertical index   (required)
        """
        if not is_user_in_project(project_id):
            abort(403)

        xi = request.args.get('xi', type=int)
        yi = request.args.get('yi', type=int)
        if xi is None or yi is None:
            abort(400)

        if dsid not in _spec_map_cache:
            h5 = _get_h5(dsid, get_user_client())
            _spec_map_cache[dsid] = h5['measurement/hyperspec_picam_mcl/spec_map'][0].astype(np.float32)
        arr = _spec_map_cache[dsid][yi, xi, :]
        return Response(arr.tobytes(), mimetype='application/octet-stream')

    return bp
