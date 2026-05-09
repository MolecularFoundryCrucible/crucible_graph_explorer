import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import flask
import requests
from flask import Blueprint, abort, jsonify, render_template, request
from flask_pyoidc.user_session import UserSession

from utils.cache import get_project, is_user_in_project
from utils.helpers import render_markdown

logger = logging.getLogger(__name__)


def create_blueprint(auth):
    bp = Blueprint('datasets', __name__)

    @bp.route("/<project_id>/dataset/<dsid>")
    @auth.oidc_auth('orcid')
    def dataset(project_id, dsid):
        import views.datasets as dataset_views
        client = flask.current_app.crucible_client
        t0 = time.perf_counter()

        if not is_user_in_project(project_id):
            abort(403)

        def _get_links():
            try:
                return client.datasets.get_download_links(dsid)
            except Exception as err:
                logger.warning("Failed to get download links for %s: %s", dsid, err)
                return {}

        with ThreadPoolExecutor() as ex:
            f_pc       = ex.submit(get_project, project_id, client=client)
            f_ds       = ex.submit(client.datasets.get, dsid, include_metadata=True)
            f_samples  = ex.submit(client.samples.list, dataset_id=dsid)
            f_thumbs   = ex.submit(client.datasets.get_thumbnails, dsid)
            f_files    = ex.submit(client.datasets.get_associated_files, dsid)
            f_links    = ex.submit(_get_links)
            f_children = ex.submit(client.datasets.list_children, dsid)
            f_parents  = ex.submit(client.datasets.list_parents, dsid)

        pc               = f_pc.result()
        ds               = f_ds.result()
        samples          = f_samples.result()
        thumbnails       = f_thumbs.result()
        associated_files = f_files.result()
        download_links   = f_links.result()
        child_datasets   = f_children.result()
        parent_datasets  = f_parents.result()
        logger.debug("dataset parallel fetch=%.3fs", time.perf_counter() - t0)

        markdown_html = None
        if ds.get('measurement') == 'MDNote':
            md_file = next((f for f in associated_files if f['filename'].endswith('.md')), None)
            if md_file:
                md_basename  = os.path.basename(md_file['filename'])
                download_key = f"{ds['unique_id']}/{md_basename}"
                if download_key in download_links:
                    try:
                        response = requests.get(download_links[download_key])
                        if response.status_code == 200:
                            markdown_html = render_markdown(response.text, project_id)
                    except Exception as err:
                        logger.warning("Failed to render markdown for %s: %s", dsid, err)

        group_by  = request.args.get('dgb', 'measurement')
        group_val = ds.get(group_by)
        if group_val:
            ds_siblings = sorted(
                [d for d in pc['datasets'] if d.get(group_by) == group_val],
                key=lambda x: x.get('dataset_name') or ''
            )
        else:
            ds_siblings = [ds]
        ds_sibling_idx = next((i for i, d in enumerate(ds_siblings) if d['unique_id'] == dsid), 0)
        prev_sibling = ds_siblings[ds_sibling_idx - 1] if ds_sibling_idx > 0 else None
        next_sibling = ds_siblings[ds_sibling_idx + 1] if ds_sibling_idx < len(ds_siblings) - 1 else None

        return render_template("dataset.html",
                               project_id=project_id, pc=pc, ds=ds,
                               child_datasets=child_datasets,
                               parent_datasets=parent_datasets,
                               samples=samples,
                               files=associated_files,
                               download_links=download_links,
                               thumbnails=thumbnails,
                               markdown_html=markdown_html,
                               custom_views=dataset_views.get_views(ds.get('measurement'), project_id, dsid),
                               prev_sibling=prev_sibling,
                               next_sibling=next_sibling,
                               sibling_index=ds_sibling_idx + 1,
                               sibling_count=len(ds_siblings),
                               siblings=ds_siblings,
                               sibling_label=group_val or '')

    @bp.route("/<project_id>/dataset/<dsid>/mdnote-edit", methods=['GET', 'POST'])
    @auth.oidc_auth('orcid')
    def mdnote_edit(project_id, dsid):
        client = flask.current_app.crucible_client
        if not is_user_in_project(project_id):
            abort(403)
        ds = client.datasets.get(dsid, include_metadata=True)

        if request.method == 'POST':
            md_content = request.json.get('content', '')
            associated_files = client.datasets.get_associated_files(dsid)
            md_filename = 'note.md'
            for file in associated_files:
                if file['filename'].endswith('.md'):
                    md_filename = os.path.basename(file['filename'])
                    break
            tmp_dir = tempfile.mkdtemp()
            tmp_path = os.path.join(tmp_dir, md_filename)
            try:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    f.write(md_content)
                client.datasets.add_file_to_dataset(dsid, tmp_path,
                                                    ingestion_class='ApiUploadIngestor',
                                                    wait_for_ingestion_response=True)
            finally:
                os.unlink(tmp_path)
                os.rmdir(tmp_dir)
            return jsonify({'status': 'ok'})

        associated_files = client.datasets.get_associated_files(dsid)
        try:
            download_links = client.datasets.get_download_links(dsid)
        except Exception as err:
            logger.warning("Failed to get download links for %s: %s", dsid, err)
            download_links = {}
        md_content = ''
        for file in associated_files:
            if file['filename'].endswith('.md'):
                md_basename  = os.path.basename(file['filename'])
                download_key = f"{ds['unique_id']}/{md_basename}"
                if download_key in download_links:
                    response = requests.get(download_links[download_key])
                    if response.status_code == 200:
                        md_content = response.text
                break

        return render_template('mdnote_edit.html',
                               project_id=project_id, ds=ds, md_content=md_content)

    return bp
