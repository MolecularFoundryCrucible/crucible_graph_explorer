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

        if is_own_profile:
            # Name/email already in the ORCID session — no member fetching needed.
            # shared_projects is the full project list for own profile.
            info = user_session.userinfo
            given  = info.get('given_name', '')
            family = info.get('family_name', '')
            if not given and not family:
                parts = (info.get('name') or '').rsplit(' ', 1)
                given  = parts[0] if parts else ''
                family = parts[1] if len(parts) > 1 else ''
            user_info = {
                'first_name': given,
                'last_name':  family,
                'email':      info.get('email', ''),
                'unique_id':  orcid,
            }
            shared_projects = user_projects

            with ThreadPoolExecutor() as ex:
                f_datasets = ex.submit(client.datasets.list, owner_orcid=orcid, limit=None)
                f_samples  = ex.submit(client.samples.list,  owner_orcid=orcid, limit=None)
            try:
                recent_datasets = f_datasets.result() or []
            except Exception:
                recent_datasets = []
            try:
                recent_samples = f_samples.result() or []
            except Exception:
                recent_samples = []

        else:
            # Fetch user info directly + member lists to find shared projects.
            def fetch_members(p):
                try:
                    return client.projects.get_users(p['project_id']) or []
                except Exception:
                    return []

            with ThreadPoolExecutor() as ex:
                f_user_info = ex.submit(flask.current_app.admin_client.users.get, target_orcid)
                f_members   = [ex.submit(fetch_members, p) for p in user_projects]
                f_datasets  = ex.submit(client.datasets.list, owner_orcid=target_orcid, limit=None)
                f_samples   = ex.submit(client.samples.list,  owner_orcid=target_orcid, limit=None)
                all_members = [f.result() for f in f_members]
                try:
                    recent_datasets = f_datasets.result() or []
                except Exception:
                    recent_datasets = []
                try:
                    recent_samples = f_samples.result() or []
                except Exception:
                    recent_samples = []
                try:
                    user_info = f_user_info.result() or {}
                except Exception:
                    user_info = {}

            shared_projects = [
                p for p, members in zip(user_projects, all_members)
                if any(m.get('unique_id') == target_orcid for m in members)
            ]

        recent_datasets.sort(key=lambda d: d.get('timestamp') or '', reverse=True)
        recent_samples.sort(key=lambda s: s.get('timestamp') or '', reverse=True)

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
