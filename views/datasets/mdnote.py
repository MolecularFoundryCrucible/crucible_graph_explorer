import os

import requests
from flask import Blueprint, render_template, abort, current_app

from utils.auth import get_user_client
from utils.helpers import render_markdown

MEASUREMENT_TYPES = ['MDNote']
URL_PREFIX = '/dataset-view/mdnote'
LABEL = 'View Note'


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_mdnote', __name__)

    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)

        ds = get_user_client().datasets.get(dsid)
        associated_files = get_user_client().datasets.get_associated_files(dsid)

        markdown_html = None
        error = None

        md_file = next((f for f in associated_files if f['filename'].endswith('.md')), None)
        if md_file:
            try:
                url = get_user_client().datasets.get_download_link(md_file['mfid'])
                response = requests.get(url)
                if response.status_code == 200:
                    markdown_html = render_markdown(response.text, project_id)
                else:
                    error = f'Failed to fetch note (HTTP {response.status_code})'
            except Exception as err:
                error = str(err)
        else:
            error = 'No markdown file found for this dataset.'

        return render_template(
            'dataset_views/mdnote.html',
            project_id=project_id,
            ds=ds,
            markdown_html=markdown_html,
            error=error,
        )

    return bp
