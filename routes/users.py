import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import flask
from flask import Blueprint, abort, jsonify, render_template
from flask_pyoidc.user_session import UserSession

from utils.auth import get_user_client
from utils.cache import get_user_projects

logger = logging.getLogger(__name__)


def create_blueprint(auth):
    bp = Blueprint('users_routes', __name__)

    @bp.route("/users")
    @auth.oidc_auth('orcid')
    def users_overview():
        client = get_user_client()
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        user_projects = get_user_projects(orcid, client)

        def fetch_members(p):
            try:
                return client.projects.get_users(p['project_id']) or []
            except Exception:
                return []

        with ThreadPoolExecutor() as ex:
            all_members = list(ex.map(fetch_members, user_projects))

        projects_with_users = [
            {'project': p, 'members': m}
            for p, m in zip(user_projects, all_members)
        ]
        return render_template('users.html', projects_with_users=projects_with_users)

    @bp.route("/user/<target_orcid>")
    @auth.oidc_auth('orcid')
    def user_detail(target_orcid):
        client = get_user_client()
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        is_own_profile = (target_orcid == orcid)
        user_projects = get_user_projects(orcid, client)

        def fetch_members(p):
            try:
                return client.projects.get_users(p['project_id']) or []
            except Exception:
                return []

        with ThreadPoolExecutor() as ex:
            f_members  = [ex.submit(fetch_members, p) for p in user_projects]
            f_datasets = ex.submit(client.datasets.list, owner_orcid=target_orcid, limit=None)
            f_samples  = ex.submit(client.samples.list, owner_orcid=target_orcid, limit=None)
            all_members = [f.result() for f in f_members]
            try:
                recent_datasets = f_datasets.result() or []
            except Exception:
                recent_datasets = []
            try:
                recent_samples = f_samples.result() or []
            except Exception:
                recent_samples = []

        recent_datasets.sort(key=lambda d: d.get('timestamp') or '', reverse=True)
        recent_samples.sort(key=lambda s: s.get('timestamp') or '', reverse=True)

        user_info = {}
        shared_projects = []
        for p, members in zip(user_projects, all_members):
            for m in members:
                if m.get('unique_id') == target_orcid:
                    if not user_info:
                        user_info = m
                    shared_projects.append(p)
                    break

        if is_own_profile:
            shared_projects = user_projects

        dataset_counts = Counter(d.get('project_id') for d in recent_datasets if d.get('project_id'))
        sample_counts  = Counter(s.get('project_id') for s in recent_samples  if s.get('project_id'))

        return render_template('user.html',
                               user_info=user_info,
                               target_orcid=target_orcid,
                               shared_projects=shared_projects,
                               recent_datasets=recent_datasets,
                               recent_samples=recent_samples,
                               dataset_counts=dataset_counts,
                               sample_counts=sample_counts,
                               is_own_profile=is_own_profile)

    return bp
