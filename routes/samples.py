import logging
import os
import shutil
import tempfile

import flask
import networkx as nx
from flask import Blueprint, abort, jsonify, redirect, render_template, request
from flask_pyoidc.user_session import UserSession
from PIL import Image

from utils.auth import get_user_client
from utils.cache import clear_project_cache, get_project, get_user_name, get_user_projects
from utils.graph import get_entity_graph_nx

logger = logging.getLogger(__name__)


def create_blueprint(auth):
    bp = Blueprint('samples', __name__)

    @bp.route("/<project_id>/samples/new", methods=['GET'])
    @auth.oidc_auth('orcid')
    def sample_new(project_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        pc = get_project(project_id, orcid)
        return render_template('create_sample.html', pc=pc)

    @bp.route("/<project_id>/samples/new", methods=['POST'])
    @auth.oidc_auth('orcid')
    def sample_new_post(project_id):
        sample_name = request.form.get('sample_name', '').strip()
        sample_type = request.form.get('sample_type', '').strip()
        if not sample_name or not sample_type:
            abort(400)
        description = request.form.get('description', '').strip() or None
        parent_ids  = [pid for pid in request.form.getlist('parent_ids') if pid]
        child_ids   = [cid for cid in request.form.getlist('child_ids') if cid]

        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        try:
            result = get_user_client().samples.create(
                sample_name=sample_name,
                sample_type=sample_type,
                description=description,
                project_id=project_id,
                owner_orcid=orcid,
                parents=[{'unique_id': pid} for pid in parent_ids],
                children=[{'unique_id': cid} for cid in child_ids],
            )
        except Exception:
            results = get_user_client().samples.list(sample_name = sample_name, project_id = project_id)
            if len(results) > 0:
                result = results[-1]
            else:
                raise

        clear_project_cache(project_id, orcid)
        sample_mfid = result.get("unique_id")
        logger.info(f'{sample_mfid=}')
        return redirect(f'{request.script_root}/{project_id}/samples/{sample_mfid}')

    @bp.route("/<project_id>/samples/<sample_id>/edit", methods=['GET'])
    @auth.oidc_auth('orcid')
    def sample_edit(project_id, sample_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        pc = get_project(project_id, orcid)
        self_info = pc['samples_by_id'].get(sample_id)
        if not self_info:
            abort(404)
        G = get_entity_graph_nx(sample_id)
        direct_parents  = [pc['samples_by_id'][sid] for sid in G.predecessors(sample_id)
                           if sid in pc['samples_by_id']]
        direct_children = [pc['samples_by_id'][sid] for sid in G.successors(sample_id)
                           if sid in pc['samples_by_id']]
        return render_template('edit_sample.html', pc=pc, sample=self_info,
                               direct_parents=direct_parents, direct_children=direct_children)

    @bp.route("/<project_id>/samples/<sample_id>/edit", methods=['POST'])
    @auth.oidc_auth('orcid')
    def sample_edit_post(project_id, sample_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        G = get_entity_graph_nx(sample_id)
        existing_parent_ids = set(G.predecessors(sample_id))
        existing_child_ids  = set(G.successors(sample_id))

        sample_name = request.form.get('sample_name', '').strip()
        sample_type = request.form.get('sample_type', '').strip()
        if not sample_name or not sample_type:
            abort(400)
        description    = request.form.get('description', '').strip() or None
        new_parent_ids = [pid for pid in request.form.getlist('parent_ids')
                          if pid and pid not in existing_parent_ids]
        new_child_ids  = [cid for cid in request.form.getlist('child_ids')
                          if cid and cid not in existing_child_ids]

        get_user_client().samples.update(
            unique_id=sample_id,
            sample_name=sample_name,
            sample_type=sample_type,
            description=description,
            parents=[{'unique_id': pid} for pid in new_parent_ids],
            children=[{'unique_id': cid} for cid in new_child_ids],
        )
        clear_project_cache(project_id, orcid)
        return redirect(f'{request.script_root}/{project_id}/samples/{sample_id}')

    @bp.route("/<project_id>/samples/<sample_id>/upload-photo", methods=['GET'])
    @auth.oidc_auth('orcid')
    def upload_photo(project_id, sample_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        pc = get_project(project_id, orcid)
        sample = pc['samples_by_id'].get(sample_id)
        if not sample:
            abort(404)
        return render_template('upload_photo.html', pc=pc, sample=sample)

    @bp.route("/<project_id>/samples/<sample_id>/upload-photo", methods=['POST'])
    @auth.oidc_auth('orcid')
    def upload_photo_post(project_id, sample_id):

        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        from crucible.models import Dataset
        client = get_user_client()

        f = request.files.get('file')
        if not f or not f.filename:
            return jsonify({'error': 'No file received.'}), 400

        filename = os.path.basename(f.filename) or 'photo'
        dataset_name = request.form.get('dataset_name', '').strip() or os.path.splitext(filename)[0]
        description  = request.form.get('description', '').strip() or None

        tmpdir = tempfile.mkdtemp()
        tmpfile = os.path.join(tmpdir, filename)
        f.save(tmpfile)
        try:
            result = client.datasets.create(
                Dataset(dataset_name=dataset_name, measurement='img', project_id=project_id),
                files_to_upload=[tmpfile],
                scientific_metadata={'description': description} if description else None,
                wait_for_ingestion_response=False,
            )
            dataset_id = result['created_record']['unique_id']
            client.datasets.add_sample(dataset_id, sample_id)

            thumb_path = os.path.join(tmpdir, 'thumbnail.png')
            with Image.open(tmpfile) as img:
                img.thumbnail((512, 512))
                img.save(thumb_path, 'PNG')
            client.datasets.add_thumbnail(dataset_id, thumb_path, thumbnail_name=dataset_name)
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        clear_project_cache(project_id, orcid)
        return jsonify({'dataset_id': dataset_id, 'project_id': project_id})

    @bp.route("/<project_id>/samples/<sample_id>")
    @auth.oidc_auth('orcid')
    def sample_graph(project_id, sample_id):
        client = get_user_client()
        orcid = UserSession(flask.session).userinfo['sub']
        pc = get_project(project_id, orcid)
        G  = get_entity_graph_nx(sample_id)

        descendants = nx.descendants(G, sample_id)
        ancestors   = nx.ancestors(G, sample_id)

        # Fetch any nodes that appear in the graph but are missing from cache
        # (soft-deleted resources are filtered from list endpoints but still appear in graph topology)
        for node_id in G.nodes():
            if node_id not in pc['samples_by_id'] and node_id not in pc['datasets_by_id']:
                try:
                    resource = client.get(node_id)
                    if resource and resource.get('resource_type') == 'sample':
                        pc['samples_by_id'][node_id] = resource
                except Exception as err:
                    logger.debug("Could not fetch missing node %s: %s", node_id, err)

        descendants_path = {}
        for sid in descendants:
            sample_info = pc['samples_by_id'].get(sid)
            if not sample_info:
                continue
            try:
                path = nx.shortest_path(G, sample_id, sid)
                descendants_path[sample_info['sample_name']] = [
                    pc['samples_by_id'].get(x, {}).get('sample_name', x) for x in path
                ]
            except nx.NetworkXNoPath:
                pass

        ancestors_path = {}
        for sid in ancestors:
            sample_info = pc['samples_by_id'].get(sid)
            if not sample_info:
                continue
            try:
                path = nx.shortest_path(G, sid, sample_id)
                ancestors_path[sample_info['sample_name']] = [
                    pc['samples_by_id'].get(x, {}).get('sample_name', x) for x in path
                ]
            except nx.NetworkXNoPath:
                pass

        self_info = pc['samples_by_id'].get(sample_id)
        if not self_info:
            abort(404)

        try:
            detailed = client.samples.get(sample_id, include_metadata=True)
            self_info = {**self_info, 'scientific_metadata': (detailed or {}).get('scientific_metadata') or {}}
        except Exception as err:
            logger.warning("Failed to fetch metadata for sample %s: %s", sample_id, err)
            self_info = {**self_info, 'scientific_metadata': {}}

        direct_parent_ids   = set(G.predecessors(sample_id))
        direct_children_ids = set(G.successors(sample_id))

        def _sorted(sids):
            return sorted(
                [pc['samples_by_id'][sid] for sid in sids if sid in pc['samples_by_id']],
                key=lambda x: x.get('sample_name') or x['unique_id']
            )

        direct_ancestors   = _sorted(direct_parent_ids)
        indirect_ancestors = _sorted(ancestors - direct_parent_ids)
        direct_descendants   = _sorted(direct_children_ids)
        indirect_descendants = _sorted(descendants - direct_children_ids)
        ancestors_info   = direct_ancestors   + indirect_ancestors
        descendants_info = direct_descendants + indirect_descendants

        all_datasets = self_info.get('datasets', [])
        img_thumbnails = {}
        if all_datasets:
            try:
                batch = client._request(
                    "POST", "/datasets/first_thumbnails",
                    json=[d['unique_id'] for d in all_datasets]
                )
                img_thumbnails = {
                    dsid: f"data:image/png;base64,{data['thumbnail_b64str']}"
                    for dsid, data in batch.items()
                }
            except Exception:
                pass
        img_datasets = [d for d in all_datasets if d['unique_id'] in img_thumbnails]

        group_by  = request.args.get('sgb', 'sample_type')
        group_val = self_info.get(group_by)
        if group_val:
            siblings = sorted(
                [s for s in pc['samples'] if s.get(group_by) == group_val],
                key=lambda x: x.get('sample_name') or ''
            )
        else:
            siblings = [self_info]
        sibling_idx  = next((i for i, s in enumerate(siblings) if s['unique_id'] == sample_id), 0)
        prev_sibling = siblings[sibling_idx - 1] if sibling_idx > 0 else None
        next_sibling = siblings[sibling_idx + 1] if sibling_idx < len(siblings) - 1 else None

        all_projects = get_user_projects(orcid, client)
        owner_name = get_user_name(self_info.get('owner_orcid'))

        return render_template('sample.html',
                               pc=pc,
                               self_info=self_info,
                               owner_name=owner_name,
                               ancestors_info=ancestors_info,
                               descendants_info=descendants_info,
                               direct_ancestors=direct_ancestors,
                               indirect_ancestors=indirect_ancestors,
                               direct_descendants=direct_descendants,
                               indirect_descendants=indirect_descendants,
                               ancestors_path=ancestors_path,
                               descendants_path=descendants_path,
                               client=client,
                               datasets_by_id=pc['datasets_by_id'],
                               prev_sibling=prev_sibling,
                               next_sibling=next_sibling,
                               sibling_index=sibling_idx + 1,
                               sibling_count=len(siblings),
                               siblings=siblings,
                               sibling_label=group_val or '',
                               img_datasets=img_datasets,
                               img_thumbnails=img_thumbnails,
                               all_projects=all_projects)

    return bp
