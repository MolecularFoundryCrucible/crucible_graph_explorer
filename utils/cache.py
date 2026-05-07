import time
import flask
from flask import current_app
from flask_pyoidc.user_session import UserSession

_project_cache: dict = {}   # {(project_id, include_metadata): (data, timestamp)}
_project_membership_cache: dict = {}  # {orcid: (frozenset[project_id], timestamp)}
_PROJECT_CACHE_TTL = 300  # seconds


def get_project(project_id: str, include_metadata: bool = False, client=None) -> dict:
    key = (project_id, include_metadata)
    cached = _project_cache.get(key)
    if cached and time.time() - cached[1] < _PROJECT_CACHE_TTL:
        return cached[0]
    if client is None:
        client = current_app.crucible_client
    from utils.project_graph import generate_project_cache
    data = generate_project_cache(
        project_id, client,
        include_metadata=include_metadata, save=False,
    )
    _project_cache[key] = (data, time.time())
    return data


def clear_project_cache(project_id: str) -> None:
    for key in [k for k in _project_cache if k[0] == project_id]:
        del _project_cache[key]


def is_user_in_project(project_id: str, orcid: str | None = None) -> bool:
    """Check project membership, caching the project list per ORCID for 5 min."""
    if not orcid:
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
    now = time.time()
    cached = _project_membership_cache.get(orcid)
    if cached and now - cached[1] < _PROJECT_CACHE_TTL:
        return project_id in cached[0]
    projects = current_app.crucible_client.projects.list(orcid=orcid)
    project_ids = frozenset(p['project_id'] for p in projects)
    _project_membership_cache[orcid] = (project_ids, now)
    return project_id in project_ids
