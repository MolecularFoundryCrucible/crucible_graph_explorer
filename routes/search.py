import logging
from concurrent.futures import ThreadPoolExecutor

import flask
from flask import Blueprint, abort, render_template, request
from flask_pyoidc.user_session import UserSession

from utils.auth import get_user_client
from utils.cache import get_project, get_user_projects, is_user_in_project

logger = logging.getLogger(__name__)


def _flatten_metadata(obj, path=''):
    """Recursively flatten a nested dict to 'dotted.key: value' lines."""
    lines = []
    if not isinstance(obj, dict):
        return lines
    for key, val in obj.items():
        full_path = f"{path}.{key}" if path else key
        if isinstance(val, dict):
            lines.extend(_flatten_metadata(val, full_path))
        else:
            lines.append(f"{full_path}: {val}")
    return lines


def create_blueprint(auth):
    bp = Blueprint('search', __name__)

    @bp.route("/search")
    @auth.oidc_auth('orcid')
    def global_search():
        client = get_user_client()
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        user_projects = get_user_projects(orcid, client)
        q = request.args.get('q', '').strip()

        sample_results  = []
        dataset_results = []

        def search_project(p):
            pid = p['project_id']
            try:
                pc = get_project(pid, orcid, include_metadata=False, client=client)
            except Exception as err:
                logger.warning("global_search: failed to load project %s: %s", pid, err)
                return [], []
            ql = q.lower()
            s_hits, d_hits = [], []
            for s in pc.get('samples', []):
                if (ql in (s.get('sample_name') or '').lower()
                        or ql in (s.get('sample_type') or '').lower()
                        or ql in (s.get('description') or '').lower()
                        or ql in (s.get('unique_id') or '').lower()
                        or ql in (s.get('owner_orcid') or '').lower()):
                    s_hits.append({**s, '_pid': pid,
                                   '_url': f'/{pid}/samples/{s["unique_id"]}'})
            for d in pc.get('datasets', []):
                if (ql in (d.get('dataset_name') or '').lower()
                        or ql in (d.get('measurement') or '').lower()
                        or ql in (d.get('session_name') or '').lower()
                        or ql in (d.get('instrument_name') or '').lower()
                        or ql in (d.get('unique_id') or '').lower()
                        or ql in (d.get('owner_orcid') or '').lower()):
                    d_hits.append({**d, '_pid': pid,
                                   '_url': f'/{pid}/datasets/{d["unique_id"]}'})
            return s_hits, d_hits

        if q:
            with ThreadPoolExecutor() as ex:
                for s_hits, d_hits in ex.map(search_project, user_projects):
                    sample_results.extend(s_hits)
                    dataset_results.extend(d_hits)

        return render_template('global_search.html',
                               q=q,
                               sample_results=sample_results,
                               dataset_results=dataset_results,
                               projects_total=len(user_projects))

    @bp.route("/<project_id>/search")
    @auth.oidc_auth('orcid')
    def project_search(project_id):
        if not is_user_in_project(project_id):
            abort(403)
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        pc = get_project(project_id, orcid, include_metadata=True)

        samples_index = [{
            'id': s['unique_id'],
            'name': s['sample_name'],
            'description': s.get('description', ''),
            'type': s.get('sample_type', ''),
            'owner': s.get('owner_orcid', ''),
            'url': f'/{project_id}/samples/{s["unique_id"]}'
        } for s in pc['samples']]

        datasets_index = [{
            'id': d['unique_id'],
            'name': d['dataset_name'],
            'measurement': d.get('measurement', ''),
            'instrument': d.get('instrument_name', ''),
            'session': d.get('session_name', ''),
            'owner': d.get('owner_orcid', ''),
            'metadata_str': '\n'.join(_flatten_metadata(d.get('scientific_metadata') or {})),
            'url': f'/{project_id}/datasets/{d["unique_id"]}'
        } for d in pc['datasets']]

        return render_template('search.html',
                               pc=pc,
                               samples_index=samples_index,
                               datasets_index=datasets_index)

    return bp
