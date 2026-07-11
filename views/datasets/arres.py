"""
Signed-URL ARRES viewer.

Instead of downloading and parsing the HDF5 file server-side, this view hands
the browser a short-lived signed URL for the dataset's .h5 file. The browser
fetches the file directly from the bucket and parses it client-side with
h5wasm, computing the up/down/diff/polarization channels in JS.

Requires bucket CORS to allow GET from the serving origin (see cors.json).
"""

import os

from flask import Blueprint, abort, jsonify, render_template, request, send_from_directory

from utils.auth import get_user_client

MEASUREMENT_TYPES = ['arres_ek', 'arres_mm', 'ARRES_EK', 'ARRES_MM']  # incl. pre-flip SF group names (old datasets)
DATA_TYPE_STEMS = ['ScopeFoundryH5.qspleem_arres_ek', 'ScopeFoundryH5.qspleem_arres_mm']
URL_PREFIX = '/dataset-view/arres'
LABEL = 'ARRES Viewer'

# Directory of local .h5 files for the /local dev test route (not deployed to prod).
_TEST_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'test_data')


def _find_h5_file(associated_files):
    """Return the first associated file whose name ends in .h5, or None."""
    return next((f for f in associated_files if f['filename'].endswith('.h5')), None)


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_arres', __name__)
    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds = get_user_client().datasets.get(dsid)
        return render_template('dataset_views/arres.html',
                               project_id=project_id, ds=ds,
                               file_url_endpoint=f'{request.script_root}{URL_PREFIX}/{project_id}/{dsid}/file-url')

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

    # ── local dev test route: serve a test_data file; browser parses it ────────
    @bp.route('/localfile/<filename>')
    @auth.oidc_auth('orcid')
    def localfile(filename):
        return send_from_directory(_TEST_DATA_DIR, filename, conditional=True)

    @bp.route('/local/<filename>')
    @auth.oidc_auth('orcid')
    def local_view(filename):
        return render_template('dataset_views/arres.html',
                               project_id=None,
                               ds={'dataset_name': filename, 'unique_id': None},
                               file_url_endpoint=f'{request.script_root}{URL_PREFIX}/local/{filename}/file-url')

    @bp.route('/local/<filename>/file-url')
    @auth.oidc_auth('orcid')
    def local_file_url(filename):
        if not os.path.isfile(os.path.join(_TEST_DATA_DIR, filename)):
            return jsonify({'error': 'file not found'}), 404
        return jsonify({'url': f'{request.script_root}{URL_PREFIX}/localfile/{filename}',
                        'filename': filename})

    return bp
