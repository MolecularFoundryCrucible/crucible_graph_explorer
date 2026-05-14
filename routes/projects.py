import logging
import time
from concurrent.futures import ThreadPoolExecutor

import flask
from flask import Blueprint, abort, jsonify, render_template, request
from flask_pyoidc.user_session import UserSession

from utils.auth import get_user_client
from utils.cache import (
    _project_cache, _PROJECT_CACHE_TTL,
    get_project, get_user_projects, is_user_in_project, warm_project_caches,
)
from utils.helpers import abbrev_name

logger = logging.getLogger(__name__)


def _slim_sample(s):
    return {
        'unique_id':   s['unique_id'],
        'sample_name': s.get('sample_name') or '',
        'sample_type': s.get('sample_type') or '',
        'owner_orcid': s.get('owner_orcid') or '',
        'timestamp':   s.get('timestamp') or '',
    }


def _slim_dataset(ds):
    return {
        'unique_id':       ds['unique_id'],
        'dataset_name':    ds.get('dataset_name') or '',
        'measurement':     ds.get('measurement') or '',
        'instrument_name': ds.get('instrument_name') or '',
        'session_name':    ds.get('session_name') or '',
        'data_format':     ds.get('data_format') or '',
        'owner_orcid':     ds.get('owner_orcid') or '',
        'timestamp':       ds.get('timestamp') or '',
    }


def create_blueprint(auth):
    bp = Blueprint('projects', __name__)

    @bp.route("/")
    @auth.oidc_auth('orcid')
    def list_projects():
        client = get_user_client()
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        info = user_session.userinfo
        user_name = info.get('given_name') or info.get('name') or orcid
        user_projects = get_user_projects(orcid, client)

        for p in user_projects:
            lead = p.get('lead') or {}
            first = (lead.get('first_name') or '').strip()
            last  = (lead.get('last_name')  or '').strip()
            email = lead.get('email') or p.get('project_lead_email') or ''
            p['project_lead_email'] = email
            p['project_lead_name']  = abbrev_name(first, last) or email

        warm_project_caches([p['project_id'] for p in user_projects], client, orcid)

        return render_template('project_list.html', projects=user_projects, user_name=user_name)

    @bp.route("/api/dashboard-stats")
    @auth.oidc_auth('orcid')
    def dashboard_stats():
        """Return dataset/sample counts for requested projects (async dashboard endpoint)."""
        client = get_user_client()
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        ids = [i.strip() for i in request.args.get('ids', '').split(',') if i.strip()]
        if not ids:
            return jsonify({})

        def get_stats(pid):
            cached = _project_cache.get((orcid, pid, False))
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
        client = get_user_client()
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        user_projects = get_user_projects(orcid, client)
        project_meta = next((p for p in user_projects if p['project_id'] == project_id), None)
        if project_meta is None:
            abort(403)

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

        # Samples and datasets are loaded asynchronously by the page JS
        # via /api/overview-data — no get_project() call here.
        return render_template('project_overview.html',
                               pc={'project_id': project_id},
                               project_meta=project_meta,
                               owner_map=owner_map,
                               project_users=project_users,
                               all_projects=user_projects,
                               custom_views=project_views.get_views(project_id))

    @bp.route("/<project_id>/api/overview-data")
    @auth.oidc_auth('orcid')
    def project_api_overview_data(project_id):
        """Return slim samples + datasets JSON for async project overview loading."""
        if not is_user_in_project(project_id):
            abort(403)
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        client = get_user_client()
        pc = get_project(project_id, orcid, client=client)
        return jsonify({
            'samples':  [_slim_sample(s)   for s in pc['samples']],
            'datasets': [_slim_dataset(ds) for ds in pc['datasets']],
        })

    @bp.route("/<project_id>/api/sample-types")
    @auth.oidc_auth('orcid')
    def project_api_sample_types(project_id):
        if not is_user_in_project(project_id):
            abort(403)
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        q = request.args.get('q', '').lower()
        pc = get_project(project_id, orcid)
        types = sorted({s.get('sample_type') for s in pc['samples'] if s.get('sample_type')})
        if q:
            types = [t for t in types if q in t.lower()]
        return jsonify(types)

    @bp.route("/<project_id>/api/samples")
    @auth.oidc_auth('orcid')
    def api_samples(project_id):
        if not is_user_in_project(project_id):
            abort(403)
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        q = request.args.get('q', '').lower()
        pc = get_project(project_id, orcid)
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
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        q = request.args.get('q', '').lower()
        pc = get_project(project_id, orcid)
        datasets = pc['datasets']
        if q:
            datasets = [d for d in datasets
                        if q in (d.get('dataset_name') or '').lower()
                        or q in (d.get('unique_id') or '').lower()]
        return jsonify([{'id': d['unique_id'], 'name': d['dataset_name']} for d in datasets[:20]])

    return bp
