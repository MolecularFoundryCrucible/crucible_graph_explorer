"""
Deep-zoom mosaic viewer for stitched_mosaic datasets (pyramidal OME-TIFF).

Method A (client-side): the browser reads the tiled, factor-2 pyramid OME-TIFF
directly via HTTP Range with geotiff.js and renders it in OpenSeadragon, so the
Flask server stays out of the image-data path. This module therefore only:
  - serves the viewer page, and
  - hands the browser a URL to the OME-TIFF that supports Range requests.

Production path: a short-lived signed URL to the file in GCS (browser → GCS
directly; requires bucket CORS for the serving origin — see cors.json).

Local dev path: drop an ``.ome.tif`` into ``test_data/`` and open
``/dataset-view/mosaic/local/<filename>``. The file is served same-origin (with
Range support), so the whole viewer can be tested on your machine with no GCS or
CORS setup.
"""

import os

from flask import (Blueprint, abort, jsonify, render_template, request,
                   send_from_directory)

from utils.auth import get_user_client

MEASUREMENT_TYPES = ['stitched_mosaic']
URL_PREFIX = '/dataset-view/mosaic'
LABEL = 'Mosaic Viewer'

# Local .ome.tif files for the /local dev route (not used in production).
_TEST_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'test_data')

def _find_mosaic_file(associated_files):
    """Return the mosaic TIFF file record to view, or None.

    Prefers our pipeline's plain IFD-pyramid ``.tif`` over a legacy SubIFD
    ``.ome.tif`` when both are present on a re-stitched dataset: browser
    geotiff.js can read the IFD pyramid but not the SubIFD one. Falls back to any
    TIFF (so a not-yet-re-stitched legacy child still resolves to *something*).
    """
    tifs = [f for f in associated_files
            if f['filename'].lower().endswith(('.tif', '.tiff'))]
    if not tifs:
        return None
    plain = [f for f in tifs
             if not f['filename'].lower().endswith(('.ome.tif', '.ome.tiff'))]
    return (plain or tifs)[0]


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_mosaic', __name__)
    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds = get_user_client().datasets.get(dsid)
        return render_template(
            'dataset_views/mosaic_viewer.html',
            project_id=project_id, ds=ds,
            base_url=f'{request.script_root}{URL_PREFIX}/{project_id}/{dsid}',
            # None → the page fetches a fresh signed URL from the /file-url route.
            file_url=None,
        )

    @bp.route('/<project_id>/<dsid>/file-url')
    @auth.oidc_auth('orcid')
    def file_url(project_id, dsid):
        """Return a fresh signed URL to the mosaic OME-TIFF for browser Range fetches."""
        if not is_user_in_project(project_id):
            abort(403)
        client = get_user_client()
        associated_files = client.datasets.list_files(dsid)
        mosaic = _find_mosaic_file(associated_files)
        if not mosaic:
            return jsonify({'error': 'No OME-TIFF file found for this dataset.'}), 404
        try:
            url = client.files.get_download_link(mosaic['mfid'])
        except Exception as e:
            return jsonify({'error': str(e)}), 502
        return jsonify({'url': url, 'filename': os.path.basename(mosaic['filename'])})

    # ── local dev routes: test the viewer against a file in test_data/ ─────────
    @bp.route('/localfile/<path:filename>')
    @auth.oidc_auth('orcid')
    def localfile(filename):
        # conditional=True → Flask honors Range requests, which geotiff.js needs.
        return send_from_directory(_TEST_DATA_DIR, filename, conditional=True)

    @bp.route('/local/<path:filename>')
    @auth.oidc_auth('orcid')
    def local_view(filename):
        if not os.path.isfile(os.path.join(_TEST_DATA_DIR, filename)):
            abort(404)
        browser_url = f'{request.script_root}{URL_PREFIX}/localfile/{filename}'
        return render_template(
            'dataset_views/mosaic_viewer.html',
            ds={'dataset_name': filename, 'unique_id': None},
            project_id=None,
            base_url=f'{request.script_root}{URL_PREFIX}/local/{filename}',
            # Same-origin, Range-capable URL → page uses it directly, skips /file-url.
            file_url=browser_url,
        )

    return bp
