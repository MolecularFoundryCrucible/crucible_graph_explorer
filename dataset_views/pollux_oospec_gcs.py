"""
GCS-backed spectra viewer for pollux_oospec_multipos_line_scan.

This module is an example of the gcs_access pattern for large HDF5 files.
The h5py.File is opened lazily over GCS — only the groups/datasets touched
during parsing are fetched.  For typical large files this means the entire
file is never downloaded; only the slices the view actually needs are read.

(Pollux files happen to be small and are fully read anyway, but the access
pattern here is the template for future large-file dataset views.)
"""

import os

import numpy as np
from flask import Blueprint, abort, current_app, jsonify, render_template

import gcs_access

MEASUREMENT_TYPES = ['pollux_oospec_multipos_line_scan']
URL_PREFIX = '/dataset-view/pollux-oospec-gcs'
LABEL = 'Spectra Plot'


def _find_h5_filename(associated_files):
    """Return the basename of the first .h5 associated file, or None."""
    match = next((f for f in associated_files if f['filename'].endswith('.h5')), None)
    return os.path.basename(match['filename']) if match else None


def _parse_h5(h5file):
    """
    Parse an open h5py.File and return a dict ready to JSON-serialise.

    Only the datasets explicitly accessed below are fetched from GCS.
    """
    meas = h5file['measurement/pollux_oospec_multipos_line_scan']
    wavelengths = meas['wavelengths'][:].tolist()

    positions_out = []
    for pos_name, grp in sorted(meas['positions'].items()):
        raw   = grp['raw_intensities'][:]    # (n_pts, n_wl)
        dark  = grp['dark_intensities'][:]   # (n_wl,)
        blank = grp['blank_intensities'][:]  # (n_wl,)

        denom      = blank - dark
        safe_denom = np.where(np.abs(denom) > 1e-6, denom, np.nan)
        refl       = (raw - dark) / safe_denom

        attrs = dict(grp.attrs)
        positions_out.append({
            'pos_name':    pos_name,
            'sample_name': str(attrs.get('sample_name', pos_name)),
            'sample_uuid': str(attrs.get('sample_uuid', '')),
            'tray_name':   str(attrs.get('tray_name', '')),
            'integration_time': float(attrs.get('integration_time', 0)),
            'x_center': float(attrs.get('x_center', 0)),
            'y_center': float(attrs.get('y_center', 0)),
            'mean_raw':            np.nanmean(raw, axis=0).tolist(),
            'mean_dark_corrected': np.nanmean(raw - dark, axis=0).tolist(),
            'mean_reflectance':    np.nanmean(refl, axis=0).tolist(),
            'all_raw':             raw.tolist(),
            'all_dark_corrected':  (raw - dark).tolist(),
            'all_reflectance':     np.where(np.isfinite(refl), refl, None).tolist(),
        })

    return {'wavelengths': wavelengths, 'positions': positions_out}


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_pollux_oospec_gcs', __name__)

    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds = current_app.crucible_client.get_dataset(dsid)
        return render_template('dataset_views/pollux_oospec_gcs.html',
                               project_id=project_id, ds=ds)

    @bp.route('/<project_id>/<dsid>/data')
    @auth.oidc_auth('orcid')
    def data(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)

        associated_files = current_app.crucible_client.get_associated_files(dsid)
        filename = _find_h5_filename(associated_files)
        if not filename:
            return jsonify({'error': 'No .h5 file found for this dataset.'}), 404

        try:
            with gcs_access.open_h5(dsid, filename) as h5file:
                result = _parse_h5(h5file)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

        return jsonify(result)

    return bp
