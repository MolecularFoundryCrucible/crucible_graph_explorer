import os
import re

import markdown as md_lib
import requests
from flask import Blueprint, render_template, abort, current_app

MEASUREMENT_TYPES = ['MDNote']
URL_PREFIX = '/dataset-view/mdnote'
LABEL = 'View Note'


def _render_markdown(md_content, project_id):
    """Resolve wiki-style links then convert markdown to HTML."""
    def replace_dataset_link(match):
        dataset_id = match.group(1)
        name = match.group(2) if match.group(2) else f'Dataset-{dataset_id}'
        return f'[{name}](/{project_id}/dataset/{dataset_id})'

    def replace_sample_link(match):
        sample_id = match.group(1)
        name = match.group(2) if match.group(2) else f'Sample-{sample_id}'
        return f'[{name}](/{project_id}/sample-graph/{sample_id})'

    md_content = re.sub(
        r'\[\[dataset:([^\]|]+)(?:\|([^\]]+))?\]\]',
        replace_dataset_link, md_content
    )
    md_content = re.sub(
        r'\[\[sample:([^\]|]+)(?:\|([^\]]+))?\]\]',
        replace_sample_link, md_content
    )
    return md_lib.markdown(md_content, extensions=['extra', 'codehilite', 'tables'])


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_mdnote', __name__)

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

        markdown_html = None
        error = None

        md_file = next((f for f in associated_files if f['filename'].endswith('.md')), None)
        if md_file:
            md_basename = os.path.basename(md_file['filename'])
            download_key = f"{ds['unique_id']}/{md_basename}"
            if download_key in download_links:
                try:
                    response = requests.get(download_links[download_key])
                    if response.status_code == 200:
                        markdown_html = _render_markdown(response.text, project_id)
                    else:
                        error = f'Failed to fetch note (HTTP {response.status_code})'
                except Exception as err:
                    error = str(err)
            else:
                error = 'Download link not available for this note.'
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
