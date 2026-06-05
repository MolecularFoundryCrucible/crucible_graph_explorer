"""
Signed-URL spectra viewer for pollux_oospec_multipos_line_scan.

Instead of reading and parsing the HDF5 file server-side, this view hands the
browser a short-lived signed URL for the dataset's .h5 file. The browser
fetches the file directly from the bucket and parses it client-side with
h5wasm. This keeps large-file traffic off the Flask server entirely.

Requires bucket CORS to allow GET from the serving origin (see cors.json).
"""

import os

from flask import Blueprint, abort, jsonify, render_template

from utils.auth import get_user_client

MEASUREMENT_TYPES = ['pollux_oospec_multipos_line_scan']
URL_PREFIX = '/dataset-view/pollux-oospec-gcs'
LABEL = 'Spectra Plot'


def _find_h5_file(associated_files):
    """Return the first associated file whose name ends in .h5, or None."""
    return next((f for f in associated_files if f['filename'].endswith('.h5')), None)


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_pollux_oospec_gcs', __name__)

    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds = get_user_client().datasets.get(dsid)
        return render_template('dataset_views/pollux_oospec_gcs.html',
                               project_id=project_id, ds=ds)

    @bp.route('/<project_id>/<dsid>/file-url')
    @auth.oidc_auth('orcid')
    def file_url(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)

        client = get_user_client()
        associated_files = client.datasets.get_associated_files(dsid)
        h5_file = _find_h5_file(associated_files)
        if not h5_file:
            return jsonify({'error': 'No .h5 file found for this dataset.'}), 404

        try:
            url = client.files.get_download_link(h5_file['mfid'])
        except Exception as e:
            return jsonify({'error': str(e)}), 502

        return jsonify({'url': url, 'filename': os.path.basename(h5_file['filename'])})

    return bp
