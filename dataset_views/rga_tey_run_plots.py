import os

import requests
from flask import Blueprint, render_template, abort, current_app, Response

MEASUREMENT_TYPES = ['automated_RGA_TEY_run']
URL_PREFIX = '/dataset-view/rga-tey-run-plots'
LABEL = 'RGA/TEY Plots'


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_rga_tey_run_plots', __name__)

    is_user_in_project = helpers['is_user_in_project']

    def _get_gcs_url(ds, associated_files, download_links, name_fragment):
        """Return the download URL for the first .txt file whose basename contains
        name_fragment *and* that actually has a download link."""
        for f in associated_files:
            basename = os.path.basename(f['filename'])
            if name_fragment in basename and basename.endswith('.txt'):
                url = download_links.get(f"{ds['unique_id']}/{basename}")
                if url:
                    return url
        return None

    def _fetch_context(dsid):
        ds = current_app.crucible_client.get_dataset(dsid)
        associated_files = current_app.crucible_client.get_associated_files(dsid)
        try:
            download_links = current_app.crucible_client.get_dataset_download_links(dsid)
        except Exception:
            download_links = {}
        return ds, associated_files, download_links

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)

        ds, associated_files, download_links = _fetch_context(dsid)
        tey_found = bool(_get_gcs_url(ds, associated_files, download_links, 'TEY'))
        rga_found = bool(_get_gcs_url(ds, associated_files, download_links, 'RGA_histogram'))

        return render_template(
            'dataset_views/rga_tey_run_plots.html',
            project_id=project_id,
            ds=ds,
            tey_found=tey_found,
            rga_found=rga_found,
        )

    def _proxy(dsid, name_fragment):
        ds, associated_files, download_links = _fetch_context(dsid)
        gcs_url = _get_gcs_url(ds, associated_files, download_links, name_fragment)
        if not gcs_url:
            abort(404)
        resp = requests.get(gcs_url, timeout=30)
        resp.raise_for_status()
        return Response(resp.content, mimetype='text/plain')

    @bp.route('/<project_id>/<dsid>/tey-data')
    @auth.oidc_auth('orcid')
    def tey_data(project_id, dsid):
        """Proxy: fetches the TEY txt from GCS server-side to avoid CORS."""
        if not is_user_in_project(project_id):
            abort(403)
        return _proxy(dsid, 'TEY')

    @bp.route('/<project_id>/<dsid>/rga-data')
    @auth.oidc_auth('orcid')
    def rga_data(project_id, dsid):
        """Proxy: fetches the RGA histogram txt from GCS server-side to avoid CORS."""
        if not is_user_in_project(project_id):
            abort(403)
        return _proxy(dsid, 'RGA_histogram')

    return bp
