import io

import h5py
import numpy as np
import requests
from flask import Blueprint, abort, current_app, jsonify, render_template

MEASUREMENT_TYPES = ['pollux_oospec_multipos_line_scan']
URL_PREFIX = '/dataset-view/pollux-oospec'
LABEL = 'Spectra Plot'


def _parse_h5(content_bytes):
    """Parse an in-memory .h5 file and return a dict ready to JSON-serialise."""
    with h5py.File(io.BytesIO(content_bytes), 'r') as f:
        meas = f['measurement/pollux_oospec_multipos_line_scan']
        wavelengths = meas['wavelengths'][:].tolist()

        positions_out = []
        for pos_name, grp in sorted(meas['positions'].items()):
            raw = grp['raw_intensities'][:]      # (n_pts, n_wl)
            dark = grp['dark_intensities'][:]    # (n_wl,)
            blank = grp['blank_intensities'][:]  # (n_wl,)

            denom = blank - dark
            # Avoid division by zero / tiny denominators
            safe_denom = np.where(np.abs(denom) > 1e-6, denom, np.nan)
            refl = (raw - dark) / safe_denom     # (n_pts, n_wl)

            attrs = dict(grp.attrs)

            positions_out.append({
                'pos_name':    pos_name,
                'sample_name': str(attrs.get('sample_name', pos_name)),
                'sample_uuid': str(attrs.get('sample_uuid', '')),
                'tray_name':   str(attrs.get('tray_name', '')),
                'integration_time': float(attrs.get('integration_time', 0)),
                'x_center':    float(attrs.get('x_center', 0)),
                'y_center':    float(attrs.get('y_center', 0)),
                # Mean spectra (one curve per display mode)
                'mean_raw':    np.nanmean(raw, axis=0).tolist(),
                'mean_dark_corrected': np.nanmean(raw - dark, axis=0).tolist(),
                'mean_reflectance':    np.nanmean(refl, axis=0).tolist(),
                # All individual line-scan spectra for detail view (per mode)
                'all_raw':           raw.tolist(),
                'all_dark_corrected': (raw - dark).tolist(),
                'all_reflectance':   np.where(np.isfinite(refl), refl, None).tolist(),
            })

    return {'wavelengths': wavelengths, 'positions': positions_out}


def _fetch_h5_bytes(dsid):
    """Fetch the first .h5 associated file for the dataset and return its bytes."""
    ds = current_app.crucible_client.get_dataset(dsid)
    associated_files = current_app.crucible_client.get_associated_files(dsid)
    try:
        download_links = current_app.crucible_client.get_dataset_download_links(dsid)
    except Exception:
        download_links = {}

    h5_file = next(
        (f for f in associated_files if f['filename'].endswith('.h5')),
        None
    )
    if not h5_file:
        return None, ds, 'No .h5 file found for this dataset.'

    import os
    basename = os.path.basename(h5_file['filename'])
    url = download_links.get(f"{ds['unique_id']}/{basename}")
    if not url:
        return None, ds, 'Download link not available for the .h5 file.'

    resp = requests.get(url, timeout=60)
    if resp.status_code != 200:
        return None, ds, f'Failed to download .h5 file (HTTP {resp.status_code}).'

    return resp.content, ds, None


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_pollux_oospec', __name__)

    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds = current_app.crucible_client.get_dataset(dsid)
        return render_template(
            'dataset_views/pollux_oospec.html',
            project_id=project_id,
            ds=ds,
        )

    @bp.route('/<project_id>/<dsid>/data')
    @auth.oidc_auth('orcid')
    def data(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)

        content, ds, error = _fetch_h5_bytes(dsid)
        if error:
            return jsonify({'error': error}), 404

        try:
            result = _parse_h5(content)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

        return jsonify(result)

    return bp
