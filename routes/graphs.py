import logging

import flask
from flask import Blueprint, abort, jsonify, render_template
from flask_pyoidc.user_session import UserSession

from utils.auth import get_user_client
from utils.cache import get_project, is_user_in_project
from utils.graph import get_entity_graph_nx, get_project_graph, _to_nx

logger = logging.getLogger(__name__)


def create_blueprint(auth):
    bp = Blueprint('graphs', __name__)

    @bp.route("/<project_id>/entity-graph/<entity_type>/<entity_id>")
    @auth.oidc_auth('orcid')
    def entity_graph(project_id, entity_type, entity_id):
        if entity_type not in ('sample', 'dataset'):
            abort(400)
        if not is_user_in_project(project_id):
            abort(403)
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        pc = get_project(project_id, orcid)
        if entity_type == 'sample':
            entity = pc['samples_by_id'].get(entity_id, {})
            entity_name = entity.get('sample_name', entity_id[:13])
        else:
            entity = pc['datasets_by_id'].get(entity_id, {})
            entity_name = entity.get('dataset_name', entity_id[:13])
        return render_template('entity_graph.html',
                               pc=pc,
                               entity_type=entity_type,
                               entity_id=entity_id,
                               entity_name=entity_name)

    @bp.route("/<project_id>/api/entity-graph-data/<entity_type>/<entity_id>")
    @auth.oidc_auth('orcid')
    def entity_graph_data(project_id, entity_type, entity_id):
        if entity_type not in ('sample', 'dataset'):
            abort(400)
        if not is_user_in_project(project_id):
            abort(403)

        client = get_user_client()
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        pc = get_project(project_id, orcid)
        G = get_entity_graph_nx(entity_id)

        nodes = []
        edges = [{'source': src, 'target': tgt} for src, tgt in G.edges()]
        dataset_ids = []

        for node_id, attrs in G.nodes(data=True):
            ntype = attrs.get('entity_type', entity_type)
            if ntype == 'sample':
                sample = pc['samples_by_id'].get(node_id, {})
                nodes.append({
                    'id': node_id,
                    'label': sample.get('sample_name', attrs.get('name', node_id[:13])),
                    'type': 'sample',
                    'description': sample.get('description', ''),
                    'url': f'/{project_id}/samples/{node_id}'
                })
            else:
                dataset_ids.append(node_id)

        thumbnails = {}
        if dataset_ids:
            try:
                batch = client._request("POST", "/datasets/first_thumbnails", json=dataset_ids)
                thumbnails = {
                    dsid: f"data:image/png;base64,{data['thumbnail_b64str']}"
                    for dsid, data in batch.items()
                }
            except Exception:
                pass

        for node_id in dataset_ids:
            attrs = G.nodes[node_id]
            ds = pc['datasets_by_id'].get(node_id, {})
            nodes.append({
                'id': node_id,
                'label': ds.get('dataset_name', attrs.get('name', node_id[:13])),
                'type': 'dataset',
                'measurement': ds.get('measurement', ''),
                'url': f'/{project_id}/datasets/{node_id}',
                'thumbnail': thumbnails.get(node_id)
            })

        return jsonify({
            'nodes': nodes,
            'edges': edges,
            'centerNodeId': entity_id,
            'centerNodeType': entity_type
        })

    @bp.route("/<project_id>/project-graph")
    @auth.oidc_auth('orcid')
    def project_graph(project_id):
        if not is_user_in_project(project_id):
            abort(403)
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        pc = get_project(project_id, orcid)
        return render_template('project_graph.html', pc=pc)

    @bp.route("/<project_id>/api/project-graph-data")
    @auth.oidc_auth('orcid')
    def project_graph_data(project_id):
        if not is_user_in_project(project_id):
            abort(403)

        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        pc = get_project(project_id, orcid)
        G = get_project_graph(project_id)

        nodes = []
        edges = [{'source': src, 'target': tgt} for src, tgt in G.edges()]

        for node_id, attrs in G.nodes(data=True):
            if attrs.get('entity_type') == 'sample':
                sample = pc['samples_by_id'].get(node_id, {})
                nodes.append({
                    'id': node_id,
                    'label': sample.get('sample_name', attrs.get('name', node_id[:13])),
                    'type': 'sample',
                    'description': sample.get('description', ''),
                    'url': f'/{project_id}/samples/{node_id}'
                })
            else:
                ds = pc['datasets_by_id'].get(node_id, {})
                nodes.append({
                    'id': node_id,
                    'label': ds.get('dataset_name', attrs.get('name', node_id[:13])),
                    'type': 'dataset',
                    'measurement': ds.get('measurement', ''),
                    'url': f'/{project_id}/datasets/{node_id}'
                })

        return jsonify({'nodes': nodes, 'edges': edges})

    return bp
