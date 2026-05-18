import threading
import time
import flask
from flask import current_app
from flask_pyoidc.user_session import UserSession

_project_cache: dict = {}             # {(orcid, project_id, include_metadata): (data, timestamp)}
_project_membership_cache: dict = {}  # {orcid: (frozenset[project_id], timestamp)}
_user_projects_cache: dict = {}       # {orcid: ([project list], timestamp)}
_PROJECT_CACHE_TTL = 1200             # seconds (20 min)


def get_user_projects(orcid: str, client=None) -> list:
    """Return the cached project list for this user, fetching if stale."""
    cached = _user_projects_cache.get(orcid)
    if cached and time.time() - cached[1] < _PROJECT_CACHE_TTL:
        return cached[0]
    if client is None:
        from utils.auth import get_user_client
        client = get_user_client()
    projects = client.projects.list(orcid=orcid)
    _user_projects_cache[orcid] = (projects, time.time())
    # Keep membership cache in sync so is_user_in_project never needs its own call
    _project_membership_cache[orcid] = (
        frozenset(p['project_id'] for p in projects),
        time.time(),
    )
    return projects


def get_project(project_id: str, orcid: str, include_metadata: bool = False, client=None) -> dict:
    key = (orcid, project_id, include_metadata)
    cached = _project_cache.get(key)
    if cached and time.time() - cached[1] < _PROJECT_CACHE_TTL:
        return cached[0]
    if client is None:
        from utils.auth import get_user_client
        client = get_user_client()
    from utils.project_graph import generate_project_cache
    data = generate_project_cache(
        project_id, client,
        include_metadata=include_metadata, save=False,
    )
    _project_cache[key] = (data, time.time())
    return data


def warm_project_caches(project_ids: list, client, orcid: str) -> None:
    """Pre-warm project caches in background daemon threads (non-blocking).

    client and orcid must be passed explicitly — this runs in a thread where
    flask.g and flask.session are unavailable.
    """
    now = time.time()
    stale = [
        pid for pid in project_ids
        if not _project_cache.get((orcid, pid, False))
        or now - _project_cache[(orcid, pid, False)][1] > _PROJECT_CACHE_TTL * 0.8
    ]
    if not stale:
        return

    def _run():
        from concurrent.futures import ThreadPoolExecutor

        def _warm(pid):
            try:
                get_project(pid, orcid, client=client)
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(_warm, stale))

    threading.Thread(target=_run, daemon=True).start()


def clear_project_cache(project_id: str, orcid: str = None) -> None:
    if orcid:
        for key in [k for k in _project_cache if k[0] == orcid and k[1] == project_id]:
            del _project_cache[key]
    else:
        for key in [k for k in _project_cache if k[1] == project_id]:
            del _project_cache[key]


def clear_user_projects_cache(orcid: str) -> None:
    """Invalidate the project list cache for a user (e.g. after membership change)."""
    _user_projects_cache.pop(orcid, None)
    _project_membership_cache.pop(orcid, None)


def is_user_in_project(project_id: str, orcid: str | None = None) -> bool:
    """Check project membership using the shared user-projects cache."""
    if not orcid:
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
    now = time.time()
    cached = _project_membership_cache.get(orcid)
    if cached and now - cached[1] < _PROJECT_CACHE_TTL:
        return project_id in cached[0]
    # Warm via get_user_projects so the full list is cached too
    get_user_projects(orcid)
    cached = _project_membership_cache.get(orcid)
    return project_id in (cached[0] if cached else frozenset())
