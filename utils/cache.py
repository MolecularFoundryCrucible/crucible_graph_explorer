import threading
from concurrent.futures import ThreadPoolExecutor

import cachetools
import flask
from flask_pyoidc.user_session import UserSession

_PROJECT_CACHE_TTL = 1200  # seconds (20 min)

_project_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=512, ttl=_PROJECT_CACHE_TTL)
_project_cache_lock = threading.RLock()

_project_membership_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=512, ttl=_PROJECT_CACHE_TTL)
_membership_lock = threading.RLock()

_user_projects_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=512, ttl=_PROJECT_CACHE_TTL)
_user_projects_lock = threading.RLock()

_user_name_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=2048, ttl=_PROJECT_CACHE_TTL)
_user_name_lock = threading.RLock()


def get_user_name(orcid: str) -> str | None:
    """Resolve an ORCID to a display name ('First Last') via the admin client.

    Returns None if the ORCID is empty or the lookup fails. Result is cached.
    """
    if not orcid:
        return None

    with _user_name_lock:
        if orcid in _user_name_cache:
            return _user_name_cache[orcid]

    name = None
    try:
        info = flask.current_app.admin_client.users.get(orcid) or {}
        first = (info.get('first_name') or '').strip()
        last = (info.get('last_name') or '').strip()
        name = (first + ' ' + last).strip() or None
    except Exception:
        name = None

    with _user_name_lock:
        _user_name_cache[orcid] = name

    return name


def get_user_projects(orcid: str, client=None) -> list:
    with _user_projects_lock:
        if orcid in _user_projects_cache:
            return _user_projects_cache[orcid]

    if client is None:
        from utils.auth import get_user_client
        client = get_user_client()

    projects = client.projects.list(orcid=orcid, limit=10000)

    with _user_projects_lock:
        _user_projects_cache[orcid] = projects

    with _membership_lock:
        _project_membership_cache[orcid] = frozenset(p['project_id'] for p in projects)

    return projects


def get_project(project_id: str, orcid: str, include_metadata: bool = False, client=None) -> dict:
    key = (orcid, project_id, include_metadata)

    with _project_cache_lock:
        if key in _project_cache:
            return _project_cache[key]

    if client is None:
        from utils.auth import get_user_client
        client = get_user_client()

    from utils.project_graph import generate_project_cache
    data = generate_project_cache(
        project_id, client,
        include_metadata=include_metadata, save=False,
    )

    with _project_cache_lock:
        _project_cache[key] = data

    return data


def warm_project_caches(project_ids: list, client, orcid: str) -> None:
    """Pre-warm project caches in background daemon threads (non-blocking)."""
    with _project_cache_lock:
        stale = [pid for pid in project_ids if (orcid, pid, False) not in _project_cache]

    if not stale:
        return

    def _run():
        def _warm(pid):
            try:
                get_project(pid, orcid, client=client)
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(_warm, stale))

    threading.Thread(target=_run, daemon=True).start()


def clear_project_cache(project_id: str, orcid: str = None) -> None:
    with _project_cache_lock:
        keys = [
            k for k in list(_project_cache)
            if k[1] == project_id and (orcid is None or k[0] == orcid)
        ]
        for k in keys:
            del _project_cache[k]


def clear_user_projects_cache(orcid: str) -> None:
    with _user_projects_lock:
        _user_projects_cache.pop(orcid, None)
    with _membership_lock:
        _project_membership_cache.pop(orcid, None)


def is_user_in_project(project_id: str, orcid: str | None = None) -> bool:
    if not orcid:
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']

    with _membership_lock:
        if orcid in _project_membership_cache:
            return project_id in _project_membership_cache[orcid]

    get_user_projects(orcid)

    with _membership_lock:
        membership = _project_membership_cache.get(orcid, frozenset())
    return project_id in membership
