import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import flask
from flask import Blueprint, abort, jsonify, render_template
from flask_pyoidc.user_session import UserSession

from utils.auth import get_user_client
from utils.cache import get_user_projects

logger = logging.getLogger(__name__)
RECENT_RESOURCE_LIMIT = 50


def _member_dict(member):
    return member.model_dump() if hasattr(member, 'model_dump') else member


def _project_members(client, project_id):
    try:
        return [
            _member_dict(member)
            for member in (client.projects.get_users(project_id) or [])
        ]
    except Exception as exc:
        logger.warning("Could not load members for project %s: %s", project_id, exc)
        return []


def create_blueprint(auth):
    bp = Blueprint('users_routes', __name__)

    @bp.route("/users")
    @auth.oidc_auth('orcid')
    def users_overview():
        client = get_user_client()
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        user_projects = get_user_projects(orcid, client)

        with ThreadPoolExecutor(max_workers=8) as ex:
            all_members = list(ex.map(
                lambda project: _project_members(client, project['project_id']),
                user_projects,
            ))

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
            # Profile from account.profile(); OIDC session values are fallback only.
            info = user_session.userinfo
            given  = info.get('given_name', '')
            family = info.get('family_name', '')
            if not given and not family:
                parts = (info.get('name') or '').rsplit(' ', 1)
                given  = parts[0] if parts else ''
                family = parts[1] if len(parts) > 1 else ''
            shared_projects = user_projects

            with ThreadPoolExecutor(max_workers=5) as ex:
                f_datasets = ex.submit(
                    client.datasets.list,
                    owner_orcid=orcid,
                    limit=RECENT_RESOURCE_LIMIT,
                )
                f_samples = ex.submit(
                    client.samples.list,
                    owner_orcid=orcid,
                    limit=RECENT_RESOURCE_LIMIT,
                )
                f_dataset_total = ex.submit(client.datasets.count, owner_orcid=orcid)
                f_sample_total = ex.submit(client.samples.count, owner_orcid=orcid)
                f_profile = ex.submit(client.account.profile)
            try:
                recent_datasets = f_datasets.result() or []
            except Exception:
                recent_datasets = []
            try:
                recent_samples = f_samples.result() or []
            except Exception:
                recent_samples = []
            try:
                api_profile = f_profile.result() or {}
            except Exception:
                api_profile = {}
            try:
                dataset_total = f_dataset_total.result()
            except Exception:
                dataset_total = len(recent_datasets)
            try:
                sample_total = f_sample_total.result()
            except Exception:
                sample_total = len(recent_samples)

            user_info = {
                'first_name': api_profile.get('first_name') or given,
                'last_name':  api_profile.get('last_name')  or family,
                'email':      api_profile.get('email')      or info.get('email', ''),
                'unique_id':  orcid,
                'username':   api_profile.get('username')   or '',
            }

        else:
            with ThreadPoolExecutor(max_workers=8) as ex:
                f_user_info = ex.submit(flask.current_app.admin_client.users.get, target_orcid)
                f_members = [
                    ex.submit(_project_members, client, project['project_id'])
                    for project in user_projects
                ]
                f_datasets = ex.submit(
                    client.datasets.list,
                    owner_orcid=target_orcid,
                    limit=RECENT_RESOURCE_LIMIT,
                )
                f_samples = ex.submit(
                    client.samples.list,
                    owner_orcid=target_orcid,
                    limit=RECENT_RESOURCE_LIMIT,
                )
                f_dataset_total = ex.submit(
                    client.datasets.count,
                    owner_orcid=target_orcid,
                )
                f_sample_total = ex.submit(
                    client.samples.count,
                    owner_orcid=target_orcid,
                )
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
                try:
                    dataset_total = f_dataset_total.result()
                except Exception:
                    dataset_total = len(recent_datasets)
                try:
                    sample_total = f_sample_total.result()
                except Exception:
                    sample_total = len(recent_samples)

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
                               dataset_total=dataset_total,
                               sample_total=sample_total,
                               dataset_counts=dataset_counts,
                               sample_counts=sample_counts,
                               is_own_profile=is_own_profile)

    return bp
