import io
import math
import os

import h5py
import numpy as np
import requests
from flask import Blueprint, abort, current_app, jsonify, render_template

MEASUREMENT_TYPES = ['pollux_oospec_multipos_line_scan']
URL_PREFIX = '/dataset-view/pollux-oospec'
LABEL = 'Spectra Plot'


def _h5str(val):
    """Decode h5py string datasets which may be bytes or str depending on file version."""
    return val.decode() if isinstance(val, bytes) else str(val)


def _safe_1d(arr):
    return [None if not math.isfinite(v) else v for v in arr.tolist()]


def _safe_2d(arr):
    return [[None if not math.isfinite(v) else v for v in row] for row in arr.tolist()]


def _make_position(pos_name, raw, dark, safe_denom, sample_name, x_center, y_center):
    refl = (raw - dark) / safe_denom
    return {
        'pos_name':            pos_name,
        'sample_name':         sample_name,
        'x_center':            x_center,
        'y_center':            y_center,
        'mean_raw':            np.nanmean(raw, axis=0).tolist(),
        'mean_dark_corrected': np.nanmean(raw - dark, axis=0).tolist(),
        'mean_reflectance':    _safe_1d(np.nanmean(refl, axis=0)),
        'all_raw':             raw.tolist(),
        'all_dark_corrected':  (raw - dark).tolist(),
        'all_reflectance':     _safe_2d(refl),
    }


def _parse_h5(content_bytes):
    """Parse an in-memory .h5 file, handling two known format versions.

    New format: spectral_data per position, global DarkReference / BlankReference
                positions, metadata stored as datasets.
    Old format: raw_intensities / dark_intensities / blank_intensities per
                position, metadata stored as HDF5 attributes.
    """
    with h5py.File(io.BytesIO(content_bytes), 'r') as f:
        meas = f['measurement/pollux_oospec_multipos_line_scan']
        wavelengths = meas['wavelengths'][:].tolist()
        all_positions = sorted(meas['positions'].items())

        # Detect format from first position group
        first_grp = all_positions[0][1]
        new_format = 'spectral_data' in first_grp

        positions_out = []

        if new_format:
            settings_attrs = meas['settings'].attrs
            dark_idx  = int(settings_attrs.get('dark_idx',  0))
            blank_idx = int(settings_attrs.get('blank_idx', 1))

            dark  = np.mean(all_positions[dark_idx][1]['spectral_data'][:],  axis=0)
            blank = np.mean(all_positions[blank_idx][1]['spectral_data'][:], axis=0)
            safe_denom = np.where(np.abs(blank - dark) > 1e-6, blank - dark, np.nan)

            reference_indices = {dark_idx, blank_idx}
            for i, (pos_name, grp) in enumerate(all_positions):
                if i in reference_indices:
                    continue
                positions_out.append(_make_position(
                    pos_name,
                    raw        = grp['spectral_data'][:],
                    dark       = dark,
                    safe_denom = safe_denom,
                    sample_name = _h5str(grp['sample_name'][()]),
                    x_center    = float(grp['x_center'][()]),
                    y_center    = float(grp['y_center'][()]),
                ))

        else:  # old format
            for pos_name, grp in all_positions:
                raw   = grp['raw_intensities'][:]
                dark  = grp['dark_intensities'][:]
                blank = grp['blank_intensities'][:]
                safe_denom = np.where(np.abs(blank - dark) > 1e-6, blank - dark, np.nan)
                attrs = dict(grp.attrs)
                positions_out.append(_make_position(
                    pos_name,
                    raw        = raw,
                    dark       = dark,
                    safe_denom = safe_denom,
                    sample_name = str(attrs.get('sample_name', pos_name)),
                    x_center    = float(attrs.get('x_center', 0)),
                    y_center    = float(attrs.get('y_center', 0)),
                ))

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
        return None, 'No .h5 file found for this dataset.'

    basename = os.path.basename(h5_file['filename'])
    url = download_links.get(f"{ds['unique_id']}/{basename}")
    if not url:
        return None, 'Download link not available for the .h5 file.'

    resp = requests.get(url, timeout=60)
    if resp.status_code != 200:
        return None, f'Failed to download .h5 file (HTTP {resp.status_code}).'

    return resp.content, None


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

        try:
            content, error = _fetch_h5_bytes(dsid)
            if error:
                return jsonify({'error': error}), 404
            result = _parse_h5(content)
            return jsonify(result)
        except Exception as e:
            current_app.logger.exception('pollux_oospec /data failed for dsid=%s', dsid)
            return jsonify({'error': str(e)}), 500

    return bp
