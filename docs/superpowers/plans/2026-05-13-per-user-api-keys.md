# Per-User API Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single shared admin API key with per-user Crucible API keys for all data-access operations, so the Crucible API enforces authorization natively rather than relying solely on the Flask layer.

**Architecture:** After ORCID login, the Flask backend calls `GET /user_apikey` (forwarding the browser's `crucible_user_token` cookie) and stores the returned key in the server-side Flask session. A `get_user_client()` helper (cached on `flask.g` per request) returns a `CrucibleClient` initialized with that key. The existing admin client (`app.admin_client`) is kept for privileged operations (user creation, profile update, account existence checks). The project cache gains an `orcid` dimension so users can never see each other's cached data.

**Tech Stack:** Flask, flask-pyoidc, crucible-python SDK (`CrucibleClient`), pytest

---

## File Map

| File | Change |
|---|---|
| `crucible_graph_explore_flask_app.py` | Rename `app.crucible_client` → `app.admin_client`; add `_fetch_user_api_key()`; call it in `login_go` and `require_login` |
| `utils/auth.py` | **NEW** — `get_user_client()` helper using `flask.g` |
| `utils/cache.py` | Cache key gains `orcid` prefix; `is_user_in_project` uses user client |
| `utils/graph.py` | Both graph helpers use user client |
| `routes/projects.py` | All 4 routes use user client; `warm_project_caches` / `get_project` pass `orcid` |
| `routes/datasets.py` | 3 routes use user client |
| `routes/graphs.py` | 2 routes use user client |
| `routes/search.py` | 1 route uses user client |
| `routes/samples.py` | All routes use user client; `get_project` / `clear_project_cache` pass `orcid` |
| `routes/users.py` | Data-access routes use user client (privileged ops stay on `current_app.admin_client`) |
| `routes/chat.py` | 2 call sites use user client |
| `tests/test_auth.py` | **NEW** — unit tests for `get_user_client()` and `_fetch_user_api_key()` |

---

## Task 1: Rename admin client + create `utils/auth.py`

**Files:**
- Modify: `crucible_graph_explore_flask_app.py:33`
- Modify: `crucible_graph_explore_flask_app.py:98,178,232` (three admin-only callers)
- Create: `utils/auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write failing tests for `get_user_client()`**

Create `tests/test_auth.py`:

```python
import pytest
import flask
from crucible import CrucibleClient
from utils.auth import get_user_client


@pytest.fixture
def app():
    from crucible_graph_explore_flask_app import app as _app
    _app.config['TESTING'] = True
    return _app


def test_get_user_client_returns_client(app):
    with app.test_request_context('/'):
        flask.session['crucible_apikey'] = 'test-key-abc'
        client = get_user_client()
        assert isinstance(client, CrucibleClient)


def test_get_user_client_cached_on_g(app):
    with app.test_request_context('/'):
        flask.session['crucible_apikey'] = 'test-key-abc'
        c1 = get_user_client()
        c2 = get_user_client()
        assert c1 is c2  # same object, not re-created


def test_get_user_client_aborts_401_when_no_key(app):
    with app.test_request_context('/'):
        with pytest.raises(Exception) as exc_info:
            get_user_client()
        assert '401' in str(exc_info.value) or exc_info.type.__name__ == 'HTTPException'
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/roncofaber/software/crucible_graph_explorer
pytest tests/test_auth.py -v
```

Expected: `ImportError` or `ModuleNotFoundError: utils.auth`

- [ ] **Step 3: Create `utils/auth.py`**

```python
import flask
from crucible import CrucibleClient


def get_user_client() -> CrucibleClient:
    """Return a per-request CrucibleClient using the logged-in user's API key.

    The client is cached on flask.g so it is created at most once per request.
    Aborts with 401 if no key is present in the session (should not happen in
    normal flow since require_login ensures the key is fetched before any route
    handler runs).
    """
    if 'user_client' not in flask.g:
        key = flask.session.get('crucible_apikey')
        if not key:
            flask.abort(401)
        flask.g.user_client = CrucibleClient(
            api_url=flask.current_app.config['CRUCIBLE_API_URL'],
            api_key=key,
        )
    return flask.g.user_client
```

- [ ] **Step 4: Rename `app.crucible_client` → `app.admin_client` in the main app**

In `crucible_graph_explore_flask_app.py`, change line 33:

```python
# Before
app.crucible_client = CrucibleClient(api_url=crucible_api_url, api_key=crucible_api_key)
app.config['CRUCIBLE_API_URL'] = crucible_api_url

# After
app.admin_client = CrucibleClient(api_url=crucible_api_url, api_key=crucible_api_key)
app.config['CRUCIBLE_API_URL'] = crucible_api_url
```

- [ ] **Step 5: Update the three admin-only call sites in the main app**

`_crucible_user_exists` (line ~98):
```python
app.admin_client.users.get(orcid)
```

`account_setup` POST handler (line ~178):
```python
app.admin_client.users.create({
    'unique_id':  orcid,
    'first_name': first_name,
    'last_name':  last_name,
    'email':      email or None,
}, project_ids=[])
```

`update_profile` (line ~232):
```python
app.crucible_client.users.update(orcid, **updates)
```
→
```python
app.admin_client.users.update(orcid, **updates)
```

- [ ] **Step 6: Run tests — should pass now**

```bash
pytest tests/test_auth.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 7: Commit**

```bash
git add utils/auth.py tests/test_auth.py crucible_graph_explore_flask_app.py
git commit -m "feat: introduce get_user_client() helper and rename admin_client"
```

---

## Task 2: Fetch user API key after OIDC login

**Files:**
- Modify: `crucible_graph_explore_flask_app.py` — add `_fetch_user_api_key()`, update `login_go` and `require_login`
- Modify: `tests/test_auth.py` — add tests

The Crucible API exposes `GET /user_apikey` which reads the `crucible_user_token` cookie set by the platform and returns `{"crucible_apikey": "..."}`. The Flask app forwards the browser's cookies to this endpoint.

- [ ] **Step 1: Add tests for `_fetch_user_api_key`**

Add to `tests/test_auth.py`:

```python
from unittest.mock import patch, MagicMock


def test_fetch_user_api_key_stores_in_session(app):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {'crucible_apikey': 'user-key-xyz'}

    with app.test_request_context('/', headers={'Cookie': 'crucible_user_token=tok'}):
        with patch('crucible_graph_explore_flask_app.requests.get', return_value=mock_resp):
            from crucible_graph_explore_flask_app import _fetch_user_api_key
            _fetch_user_api_key()
            assert flask.session.get('crucible_apikey') == 'user-key-xyz'


def test_fetch_user_api_key_skips_if_already_set(app):
    with app.test_request_context('/'):
        flask.session['crucible_apikey'] = 'existing-key'
        with patch('crucible_graph_explore_flask_app.requests.get') as mock_get:
            from crucible_graph_explore_flask_app import _fetch_user_api_key
            _fetch_user_api_key()
            mock_get.assert_not_called()


def test_fetch_user_api_key_tolerates_failure(app):
    with app.test_request_context('/'):
        with patch('crucible_graph_explore_flask_app.requests.get', side_effect=Exception('timeout')):
            from crucible_graph_explore_flask_app import _fetch_user_api_key
            _fetch_user_api_key()  # must not raise
            assert flask.session.get('crucible_apikey') is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_auth.py::test_fetch_user_api_key_stores_in_session -v
```

Expected: `ImportError` — `_fetch_user_api_key` does not exist yet

- [ ] **Step 3: Add `_fetch_user_api_key()` to the main app**

Insert before the `require_login` function in `crucible_graph_explore_flask_app.py`:

```python
def _fetch_user_api_key() -> None:
    """Fetch the user's personal Crucible API key and store it in the session.

    Calls GET /user_apikey forwarding the browser's cookies (the Crucible
    platform sets crucible_user_token which the API uses for identification).
    Silently logs and returns on any failure so login is never blocked.
    """
    if flask.session.get('crucible_apikey'):
        return
    try:
        resp = requests.get(
            f"{crucible_api_url}/user_apikey",
            cookies=request.cookies,
            timeout=5,
        )
        if resp.ok:
            key = resp.json().get('crucible_apikey')
            if key:
                flask.session['crucible_apikey'] = key
    except Exception as e:
        app.logger.warning("Could not fetch user API key: %s", e)
```

- [ ] **Step 4: Call `_fetch_user_api_key()` in `login_go` and `require_login`**

Update `login_go`:
```python
@app.route('/login/go')
@auth.oidc_auth('orcid')
def login_go():
    _fetch_user_api_key()
    return redirect('/')
```

Update `require_login` — add the lazy fetch just before returning for authenticated users:
```python
@app.before_request
def require_login():
    path = request.path
    if any(path == p or path.startswith(p) for p in ('/static/', '/redirect_uri')):
        return
    if path in _LOGIN_EXEMPT:
        return
    try:
        user_session = UserSession(flask.session)
        if user_session.userinfo:
            if path not in _ACCOUNT_SETUP_PATHS:
                orcid = user_session.userinfo.get('sub')
                if orcid and not _crucible_user_exists(orcid):
                    return redirect(url_for('account_setup'))
            # Ensure the user's API key is in the session (lazy fallback)
            if not flask.session.get('crucible_apikey'):
                _fetch_user_api_key()
            return
    except Exception:
        pass
    return redirect(url_for('login'))
```

- [ ] **Step 5: Run all auth tests**

```bash
pytest tests/test_auth.py -v
```

Expected: all 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add crucible_graph_explore_flask_app.py tests/test_auth.py
git commit -m "feat: fetch and cache per-user Crucible API key after OIDC login"
```

---

## Task 3: Per-user project cache

**Files:**
- Modify: `utils/cache.py` — all functions

The cache currently uses `(project_id, include_metadata)` as key. Adding `orcid` as the first component means each user gets their own isolated cache slice. The `is_user_in_project` function also switches from the admin client to the user client.

**Important:** `warm_project_caches` runs in a background thread — `flask.g` and `flask.session` are unavailable there. The `orcid` and `client` must be passed in explicitly (already the case for `client`; `orcid` is being added now).

- [ ] **Step 1: Write failing tests for updated cache signatures**

Create `tests/test_cache.py`:

```python
import time
import pytest
import flask
from unittest.mock import MagicMock, patch


@pytest.fixture
def app():
    from crucible_graph_explore_flask_app import app as _app
    _app.config['TESTING'] = True
    return _app


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.projects.list.return_value = [{'project_id': 'proj-a'}]
    return client


def test_get_project_cache_isolated_per_orcid(app, mock_client):
    from utils.cache import get_project, _project_cache
    _project_cache.clear()

    fake_data = {'samples': [], 'datasets': []}
    with patch('utils.cache.generate_project_cache', return_value=fake_data):
        with app.test_request_context('/'):
            get_project('proj-a', 'orcid-1', client=mock_client)
            get_project('proj-a', 'orcid-2', client=mock_client)

    # Each orcid has its own cache entry
    assert ('orcid-1', 'proj-a', False) in _project_cache
    assert ('orcid-2', 'proj-a', False) in _project_cache


def test_clear_project_cache_clears_for_orcid(app, mock_client):
    from utils.cache import get_project, clear_project_cache, _project_cache
    _project_cache.clear()

    fake_data = {'samples': [], 'datasets': []}
    with patch('utils.cache.generate_project_cache', return_value=fake_data):
        with app.test_request_context('/'):
            get_project('proj-a', 'orcid-1', client=mock_client)

    clear_project_cache('proj-a', 'orcid-1')
    assert ('orcid-1', 'proj-a', False) not in _project_cache


def test_is_user_in_project_uses_user_client(app):
    from utils.cache import is_user_in_project, _project_membership_cache
    _project_membership_cache.clear()

    mock_user_client = MagicMock()
    mock_user_client.projects.list.return_value = [{'project_id': 'proj-a'}]

    with app.test_request_context('/'):
        flask.session['crucible_apikey'] = 'key'
        with patch('utils.cache.get_user_client', return_value=mock_user_client):
            result = is_user_in_project('proj-a', orcid='orcid-1')

    assert result is True
    mock_user_client.projects.list.assert_called_once_with(orcid='orcid-1')
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_cache.py -v
```

Expected: `TypeError` — `get_project()` missing `orcid` argument (old signature)

- [ ] **Step 3: Rewrite `utils/cache.py`**

```python
import threading
import time
import flask
from flask import current_app
from flask_pyoidc.user_session import UserSession

_project_cache: dict = {}             # {(orcid, project_id, include_metadata): (data, timestamp)}
_project_membership_cache: dict = {}  # {orcid: (frozenset[project_id], timestamp)}
_PROJECT_CACHE_TTL = 1200             # seconds (20 min)


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


def is_user_in_project(project_id: str, orcid: str | None = None) -> bool:
    """Check project membership, caching the project list per ORCID for 20 min."""
    if not orcid:
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
    now = time.time()
    cached = _project_membership_cache.get(orcid)
    if cached and now - cached[1] < _PROJECT_CACHE_TTL:
        return project_id in cached[0]
    from utils.auth import get_user_client
    projects = get_user_client().projects.list(orcid=orcid)
    project_ids = frozenset(p['project_id'] for p in projects)
    _project_membership_cache[orcid] = (project_ids, now)
    return project_id in project_ids
```

- [ ] **Step 4: Run cache tests**

```bash
pytest tests/test_cache.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add utils/cache.py tests/test_cache.py
git commit -m "feat: isolate project cache per user ORCID, use user client for membership check"
```

---

## Task 4: Update `utils/graph.py`

**Files:**
- Modify: `utils/graph.py:13,17`

- [ ] **Step 1: Update `utils/graph.py`**

```python
import networkx as nx
from utils.auth import get_user_client


def _to_nx(data: dict) -> nx.DiGraph:
    """Handle both networkx >=3.0 ('edges') and <3.0 ('links') node-link format."""
    if 'edges' in data and 'links' not in data:
        data = {**data, 'links': data['edges']}
    return nx.node_link_graph(data)


def get_entity_graph_nx(entity_id: str) -> nx.DiGraph:
    return _to_nx(get_user_client().graphs.get(entity_id, recursive=True))


def get_project_graph(project_id: str) -> nx.DiGraph:
    return _to_nx(get_user_client().graphs.project(project_id))
```

- [ ] **Step 2: Commit**

```bash
git add utils/graph.py
git commit -m "feat: graph helpers use per-user client"
```

---

## Task 5: Update `routes/projects.py`

**Files:**
- Modify: `routes/projects.py`

Four routes need updating. The `dashboard_stats` route also reads `_project_cache` directly and must use the updated key format.

- [ ] **Step 1: Add import at top of `routes/projects.py`**

Replace:
```python
from utils.cache import (
    _project_cache, _PROJECT_CACHE_TTL,
    get_project, is_user_in_project, warm_project_caches,
)
```
With:
```python
from utils.auth import get_user_client
from utils.cache import (
    _project_cache, _PROJECT_CACHE_TTL,
    get_project, is_user_in_project, warm_project_caches,
)
```

- [ ] **Step 2: Update `list_projects`**

```python
@bp.route("/")
@auth.oidc_auth('orcid')
def list_projects():
    client = get_user_client()
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

    warm_project_caches([p['project_id'] for p in user_projects], client, orcid)

    return render_template('project_list.html', projects=user_projects, user_name=user_name)
```

- [ ] **Step 3: Update `dashboard_stats`**

The direct `_project_cache` key lookup must include `orcid`:

```python
@bp.route("/api/dashboard-stats")
@auth.oidc_auth('orcid')
def dashboard_stats():
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
```

- [ ] **Step 4: Update `project_overview`**

```python
@bp.route("/<project_id>/")
@auth.oidc_auth('orcid')
def project_overview(project_id):
    import views.projects as project_views
    client = get_user_client()
    user_session = UserSession(flask.session)
    orcid = user_session.userinfo['sub']
    user_projects = client.projects.list(orcid=orcid)
    project_meta = next((p for p in user_projects if p['project_id'] == project_id), None)
    if project_meta is None:
        abort(403)
    # ... rest of function unchanged, uses local `client` variable already
```

- [ ] **Step 5: Update `project_api_overview_data` and `project_api_sample_types`**

```python
@bp.route("/<project_id>/api/overview-data")
@auth.oidc_auth('orcid')
def project_api_overview_data(project_id):
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
```

Also update any remaining routes in `projects.py` that use `flask.current_app.crucible_client` — replace with `get_user_client()`. Confirm by running:

```bash
grep -n "crucible_client" routes/projects.py
```

Expected: no matches.

- [ ] **Step 6: Commit**

```bash
git add routes/projects.py
git commit -m "feat: projects routes use per-user client, cache key includes orcid"
```

---

## Task 6: Update remaining routes (datasets, graphs, search, samples, users, chat)

**Files:**
- Modify: `routes/datasets.py`, `routes/graphs.py`, `routes/search.py`, `routes/samples.py`, `routes/users.py`, `routes/chat.py`

The pattern for each file is identical:
1. Add `from utils.auth import get_user_client` to imports
2. Replace every `client = flask.current_app.crucible_client` with `client = get_user_client()`
3. For `samples.py`: also pass `orcid` to `get_project()` and `clear_project_cache()`
4. For `users.py`: keep admin client for privileged ops, user client for data reads
5. For `chat.py`: update the two `current_app.crucible_client` call sites

- [ ] **Step 1: Update `routes/datasets.py`**

Add import:
```python
from utils.auth import get_user_client
```

Replace all three occurrences of `client = flask.current_app.crucible_client` with:
```python
client = get_user_client()
```

Also update `get_project` calls — add `orcid` parameter. For each call site, add:
```python
user_session = UserSession(flask.session)
orcid = user_session.userinfo['sub']
# ...
pc = get_project(project_id, orcid, client=client)
```

Verify no remaining usages:
```bash
grep -n "crucible_client" routes/datasets.py
```
Expected: no matches.

- [ ] **Step 2: Update `routes/graphs.py`**

Add import:
```python
from utils.auth import get_user_client
```

Replace both `client = flask.current_app.crucible_client` with:
```python
client = get_user_client()
```

```bash
grep -n "crucible_client" routes/graphs.py
```
Expected: no matches.

- [ ] **Step 3: Update `routes/search.py`**

Add import:
```python
from utils.auth import get_user_client
```

Replace `client = flask.current_app.crucible_client` with:
```python
client = get_user_client()
```

Also update `get_project` calls to pass `orcid`:
```python
user_session = UserSession(flask.session)
orcid = user_session.userinfo['sub']
pc = get_project(project_id, orcid, client=client)
```

- [ ] **Step 4: Update `routes/samples.py`**

Add import:
```python
from utils.auth import get_user_client
```

Replace all `client = flask.current_app.crucible_client` with:
```python
client = get_user_client()
```

For `get_project` calls — add orcid:
```python
user_session = UserSession(flask.session)
orcid = user_session.userinfo['sub']
pc = get_project(project_id, orcid, client=client)
```

For `clear_project_cache` calls — add orcid:
```python
clear_project_cache(project_id, orcid)
```

- [ ] **Step 5: Update `routes/users.py`**

Add import:
```python
from utils.auth import get_user_client
```

Data-access routes (`users_overview`, `user_detail`) — replace `client = flask.current_app.crucible_client` with:
```python
client = get_user_client()
```

No privileged admin operations exist in this file, so all usages switch to user client.

- [ ] **Step 6: Update `routes/chat.py`**

Add import near top:
```python
from utils.auth import get_user_client
```

Line ~311 (`current_app.crucible_client.datasets.get_thumbnails`):
```python
thumbs = get_user_client().datasets.get_thumbnails(dsid)
```

Line ~324 (passing client to `execute_chat_tool`):
```python
get_user_client(), pc,
```

- [ ] **Step 7: Verify no remaining stale references**

```bash
grep -rn "crucible_client" routes/ utils/
```

Expected: **zero matches**. If any remain, fix them before committing.

- [ ] **Step 8: Commit**

```bash
git add routes/datasets.py routes/graphs.py routes/search.py \
        routes/samples.py routes/users.py routes/chat.py
git commit -m "feat: all data-access routes use per-user Crucible API client"
```

---

## Task 7: End-to-end smoke test

No automated test can cover the full OIDC flow, so verify manually:

- [ ] **Step 1: Start the app**

```bash
cd /home/roncofaber/software/crucible_graph_explorer
flask run --port 8000
```

- [ ] **Step 2: Log in via ORCID and confirm key fetch**

After login, check Flask logs for either:
- `INFO - Fetched user API key successfully` (success path)
- `WARNING - Could not fetch user API key: ...` (fallback — investigate if seen)

- [ ] **Step 3: Confirm project listing works**

Navigate to `/`. Projects should load. If the user's key has restricted access, they should only see their own projects — not all projects in the system.

- [ ] **Step 4: Confirm 403 on unauthorized project**

Try accessing a project the user is not a member of directly via URL (e.g. `/some-other-project/`). Should get 403, not project data.

- [ ] **Step 5: Confirm admin operations still work**

- Create a new account via `/account/setup` (uses admin client)
- Update profile (uses admin client)
- Both should still function

- [ ] **Step 6: Final grep — confirm zero stale references**

```bash
grep -rn "crucible_client" . --include="*.py" | grep -v ".pyc"
```

Expected: **zero matches** across the entire codebase.

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat: complete per-user API key migration — admin client for privileged ops only"
```
