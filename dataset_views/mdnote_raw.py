import os

import requests
from flask import Blueprint, render_template, abort, current_app

MEASUREMENT_TYPES = ['MDNote']
URL_PREFIX = '/dataset-view/mdnote-raw'
LABEL = 'Raw Markdown'


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_mdnote_raw', __name__)

    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)

        ds = current_app.crucible_client.get_dataset(dsid)
        associated_files = current_app.crucible_client.get_associated_files(dsid)
        try:
            download_links = current_app.crucible_client.get_dataset_download_links(dsid)
        except Exception:
            download_links = {}

        raw_content = None
        error = None

        md_file = next((f for f in associated_files if f['filename'].endswith('.md')), None)
        if md_file:
            md_basename = os.path.basename(md_file['filename'])
            download_key = f"{ds['unique_id']}/{md_basename}"
            if download_key in download_links:
                try:
                    response = requests.get(download_links[download_key])
                    if response.status_code == 200:
                        raw_content = response.text
                    else:
                        error = f'Failed to fetch note (HTTP {response.status_code})'
                except Exception as err:
                    error = str(err)
            else:
                error = 'Download link not available for this note.'
        else:
            error = 'No markdown file found for this dataset.'

        return render_template(
            'dataset_views/mdnote_raw.html',
            project_id=project_id,
            ds=ds,
            raw_content=raw_content,
            error=error,
        )

    return bp
