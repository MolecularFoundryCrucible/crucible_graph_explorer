import logging
import time
from concurrent.futures import ThreadPoolExecutor

import flask
from flask import Blueprint, abort, jsonify, render_template, request
from flask_pyoidc.user_session import UserSession

from utils.cache import (
    _project_cache, _PROJECT_CACHE_TTL,
    get_project, is_user_in_project,
)
from utils.helpers import abbrev_name

logger = logging.getLogger(__name__)


def create_blueprint(auth):
    bp = Blueprint('projects', __name__)

    @bp.route("/")
    @auth.oidc_auth('orcid')
    def list_projects():
        client = flask.current_app.crucible_client
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        info = user_session.userinfo
        user_name = info.get('given_name') or info.get('name') or orcid
        user_projects = client.projects.list(orcid=orcid)

        for p in user_projects:
            lead = p.get('lead') or {}
            first = (lead.get('first_name') or '').strip()
            last  = (lead.get('last_name')  or '').strip()
            email = lead.get('email') or p.get('project_lead_email') or ''
            p['project_lead_email'] = email
            p['project_lead_name']  = abbrev_name(first, last) or email

        return render_template('project_list.html', projects=user_projects, user_name=user_name)

    @bp.route("/api/dashboard-stats")
    @auth.oidc_auth('orcid')
    def dashboard_stats():
        """Return dataset/sample counts for requested projects (async dashboard endpoint)."""
        client = flask.current_app.crucible_client
        ids = [i.strip() for i in request.args.get('ids', '').split(',') if i.strip()]
        if not ids:
            return jsonify({})

        def get_stats(pid):
            cached = _project_cache.get((pid, False))
            if cached and time.time() - cached[1] < _PROJECT_CACHE_TTL:
                pc = cached[0]
                return pid, len(pc.get('datasets', [])), len(pc.get('samples', []))
            try:
                n_datasets = client.datasets.count(project_id=pid)
                n_samples  = client.samples.count(project_id=pid)
                return pid, n_datasets, n_samples
            except Exception:
                return pid, None, None

        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(get_stats, ids))

        return jsonify({pid: {'datasets': ds, 'samples': s} for pid, ds, s in results})

    @bp.route("/<project_id>/")
    @auth.oidc_auth('orcid')
    def project_overview(project_id):
        import views.projects as project_views
        client = flask.current_app.crucible_client
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        user_projects = client.projects.list(orcid=orcid)
        project_meta = next((p for p in user_projects if p['project_id'] == project_id), None)
        if project_meta is None:
            abort(403)

        pc = get_project(project_id)

        samples_by_type: dict = {}
        for s in pc['samples']:
            samples_by_type.setdefault(s.get('sample_type'), []).append(s)
        samples_by_type = {
            k: sorted(v, key=lambda x: x.get('sample_name') or '')
            for k, v in sorted(samples_by_type.items(), key=lambda item: item[0] or '')
        }

        datasets_by_type: dict = {}
        for ds in pc['datasets']:
            datasets_by_type.setdefault(ds.get('measurement'), []).append(ds)
        datasets_by_type = {
            k: sorted(v, key=lambda x: x['dataset_name'] or '')
            for k, v in sorted(datasets_by_type.items(), key=lambda item: item[0] or '')
        }

        owner_map: dict = {}
        project_users: list = []
        try:
            for u in (client.projects.get_users(project_id) or []):
                uid = u.get('unique_id')
                if not uid:
                    continue
                first = u.get('first_name') or ''
                last  = u.get('last_name')  or ''
                name  = (first + ' ' + last).strip()
                email = u.get('email') or ''
                owner_map[uid] = name or email or uid
                project_users.append({
                    'orcid':    uid,
                    'name':     name,
                    'email':    email,
                    'initials': ((first[:1] if first else '') + (last[:1] if last else '')).upper() or '?',
                })
            project_users.sort(key=lambda u: u['name'].lower() or u['orcid'])
        except Exception:
            pass

        return render_template('project_overview.html', pc=pc,
                               project_meta=project_meta,
                               sample_info=sorted(pc['samples_by_name'].values(),
                                                  key=lambda x: x['sample_name']),
                               samples_by_type=samples_by_type,
                               datasets_by_type=datasets_by_type,
                               owner_map=owner_map,
                               project_users=project_users,
                               custom_views=project_views.get_views(project_id))

    @bp.route("/<project_id>/api/sample-types")
    @auth.oidc_auth('orcid')
    def project_api_sample_types(project_id):
        if not is_user_in_project(project_id):
            abort(403)
        q = request.args.get('q', '').lower()
        pc = get_project(project_id)
        types = sorted({s.get('sample_type') for s in pc['samples'] if s.get('sample_type')})
        if q:
            types = [t for t in types if q in t.lower()]
        return jsonify(types)

    @bp.route("/<project_id>/api/samples")
    @auth.oidc_auth('orcid')
    def api_samples(project_id):
        if not is_user_in_project(project_id):
            abort(403)
        q = request.args.get('q', '').lower()
        pc = get_project(project_id)
        samples = pc['samples']
        if q:
            samples = [s for s in samples
                       if q in (s.get('sample_name') or '').lower()
                       or q in (s.get('unique_id') or '').lower()]
        return jsonify([
            {'id': s['unique_id'], 'name': s['sample_name'], 'type': s.get('sample_type') or ''}
            for s in samples[:20]
        ])

    @bp.route("/<project_id>/api/datasets")
    @auth.oidc_auth('orcid')
    def api_datasets(project_id):
        if not is_user_in_project(project_id):
            abort(403)
        q = request.args.get('q', '').lower()
        pc = get_project(project_id)
        datasets = pc['datasets']
        if q:
            datasets = [d for d in datasets
                        if q in (d.get('dataset_name') or '').lower()
                        or q in (d.get('unique_id') or '').lower()]
        return jsonify([{'id': d['unique_id'], 'name': d['dataset_name']} for d in datasets[:20]])

    return bp
