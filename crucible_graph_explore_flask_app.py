import logging
import os
import re

import flask
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_pyoidc import OIDCAuthentication
from flask_pyoidc.provider_configuration import ClientMetadata, ProviderConfiguration
from flask_pyoidc.redirect_uri_config import RedirectUriConfig
from flask_pyoidc.user_session import UserSession
from flask_qrcode import QRcode
from flask_vite import Vite
from werkzeug.middleware.proxy_fix import ProxyFix
from crucible import CrucibleClient

from utils.auth import attach_request_logging, get_user_client
from utils.cache import (
    clear_project_cache, clear_user_projects_cache, get_project, is_user_in_project,
)
from utils.graph import get_entity_graph_nx, get_project_graph
from utils.helpers import abbrev_name, humanize_size

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder="flask_templates")


class PrefixMiddleware:
    """Mount the app under a URL path prefix (e.g. /explore) behind a reverse proxy.

    Sets SCRIPT_NAME so Flask's url_for() (and static/Flask-Vite assets) generate
    prefixed URLs, and strips the prefix from PATH_INFO when the proxy passes it
    through. A no-op when URL_PREFIX is unset, so local dev still serves at /.
    """

    def __init__(self, wsgi_app, prefix=""):
        self.wsgi_app = wsgi_app
        self.prefix = "/" + prefix.strip("/") if prefix.strip("/") else ""

    def __call__(self, environ, start_response):
        if not self.prefix:
            return self.wsgi_app(environ, start_response)

        environ["SCRIPT_NAME"] = self.prefix
        path = environ.get("PATH_INFO", "")
        if path.startswith(self.prefix):
            environ["PATH_INFO"] = path[len(self.prefix):] or "/"

        # flask-pyoidc redirects to request.full_path, which lacks SCRIPT_NAME;
        # re-add the prefix to internal-absolute redirect targets so the proxy can route them.
        def _fixup_start_response(status, headers, exc_info=None):
            if status.startswith("3"):
                headers = [
                    (k, self.prefix + v if k.lower() == "location"
                        and v.startswith("/") and not v.startswith("//")
                        and not v.startswith(self.prefix + "/") and v != self.prefix
                        else v)
                    for k, v in headers
                ]
            return start_response(status, headers, exc_info)

        return self.wsgi_app(environ, _fixup_start_response)


# Honor X-Forwarded-Proto/Host from Cloud Run; PrefixMiddleware owns the path prefix.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.wsgi_app = PrefixMiddleware(app.wsgi_app, os.getenv("URL_PREFIX", ""))

QRcode(app)
Vite(app)

app.config.update(
    OIDC_REDIRECT_URI=os.getenv("OIDC_REDIRECT_URI"),
    SECRET_KEY=os.getenv("PYOIDC_SECRET"),
)

crucible_api_url = os.getenv("CRUCIBLE_API_URL", "https://crucible.lbl.gov/api/v3")
crucible_api_key = os.getenv("CRUCIBLE_API_KEY")
app.admin_client = CrucibleClient(api_url=crucible_api_url, api_key=crucible_api_key)
attach_request_logging(app.admin_client, tag="crucible-admin")
app.config['CRUCIBLE_API_URL'] = crucible_api_url

PROVIDER_NAME = 'orcid'
CLIENT_META = ClientMetadata(
    client_id=os.getenv("ORCID_CLIENT_ID"),
    client_secret=os.getenv("ORCID_CLIENT_SECRET"),
)
PROVIDER_CONFIG = ProviderConfiguration(issuer='https://orcid.org/', client_metadata=CLIENT_META)
# Register the redirect route at the internal endpoint `/redirect_uri` (matched after
# SCRIPT_NAME stripping) while sending the full external URI — which may include the
# /explore prefix — to ORCID. Default parsing would register the route at the full path.
_REDIRECT_URI_CONFIG = RedirectUriConfig(os.getenv("OIDC_REDIRECT_URI"), "redirect_uri")
auth = OIDCAuthentication({PROVIDER_NAME: PROVIDER_CONFIG}, app,
                          redirect_uri_config=_REDIRECT_URI_CONFIG)


@app.template_filter('humanize_size')
def humanize_size_filter(n):
    return humanize_size(n)



app.jinja_env.globals['abbrev_name'] = abbrev_name


@app.context_processor
def inject_base():
    """Expose the URL path prefix (e.g. /explore) to templates as {{ base }}."""
    return {'base': request.script_root}


@app.context_processor
def inject_current_user():
    try:
        user_session = UserSession(flask.session)
        userinfo = user_session.userinfo
        orcid = userinfo.get('sub')
        name = (userinfo.get('name') or
                (userinfo.get('given_name', '') + ' ' + userinfo.get('family_name', '')).strip()
                or None)
        return {'current_user_orcid': orcid, 'current_user_name': name}
    except Exception:
        return {'current_user_orcid': None, 'current_user_name': None}


@app.route("/auth-test/")
@auth.oidc_auth('orcid')
def auth_test():
    user_session = UserSession(flask.session)
    return jsonify(access_token=user_session.access_token,
                   id_token=user_session.id_token,
                   userinfo=user_session.userinfo)


_LOGIN_EXEMPT       = {'/login', '/login/go', '/redirect_uri', '/auth-test/'}
_ACCOUNT_SETUP_PATHS = {'/account/setup', '/account/profile', '/api/check-username'}


def _fetch_user_api_key() -> None:
    """Fetch the user's personal Crucible API key and store it in the session.

    Calls POST /users/{orcid}/apikey via the admin client, which returns the
    user's key and mints one if they don't have it yet. Returns 404 only if the
    user has no Crucible account. Silently logs and returns on any failure so
    login is never blocked.
    """
    if flask.session.get('crucible_apikey'):
        return
    try:
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        result = app.admin_client._request("POST", f"/users/{orcid}/apikey")
        key = result.get('api_key')
        if key:
            flask.session['crucible_apikey'] = key
    except Exception as e:
        app.logger.warning("Could not fetch user API key for %s: %s",
                           getattr(e, 'status_code', ''), e)


def _sync_user_projects() -> None:
    """Refresh the user's project memberships from the MF proposal database.

    Best-effort — a proposal-DB outage must never block login.
    """
    if not flask.session.get('crucible_apikey'):
        return  # no Crucible account yet; account creation does the initial sync
    try:
        orcid = UserSession(flask.session).userinfo['sub']
        # Raw _request until client.account.sync_projects() ships in nano-crucible >=3.1.1
        result = get_user_client()._request('post', '/account/sync-projects') or {}
        added = result.get('projects_added')
        if added:
            app.logger.info("Synced %d new project(s) for %s: %s", len(added), orcid, added)
            clear_user_projects_cache(orcid)
    except Exception as e:
        app.logger.warning("Project sync failed: %s", e)


def _crucible_user_exists(orcid):
    """Return True if the ORCID has a Crucible account. Result cached in session."""
    if flask.session.get('crucible_user_ok'):
        return True
    try:
        if flask.session.get('crucible_apikey'):
            # API key already bootstrapped — use self-service route, no admin needed
            get_user_client().whoami()
        else:
            # First login: API key not in session yet, fall back to admin check.
            # GET /users/{orcid} returns 200 with a null body (not 404) for an
            # unknown ORCID, so an empty result means the account does not exist.
            if not app.admin_client.users.get(orcid):
                return False
        flask.session['crucible_user_ok'] = True
        return True
    except Exception as e:
        err = str(e).lower()
        if '404' in err or 'not found' in err or '401' in err:
            return False
        # Network / auth error — don't block login, log and proceed
        app.logger.warning("Could not verify Crucible account for %s: %s", orcid, e)
        return True


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
            # Lazy fallback: ensure key is in session
            if not flask.session.get('crucible_apikey'):
                _fetch_user_api_key()
            return
    except Exception:
        pass
    return redirect(url_for('login'))


@app.route('/login')
def login():
    try:
        user_session = UserSession(flask.session)
        if user_session.userinfo:
            return redirect(request.script_root + '/')
    except Exception:
        pass
    return render_template('login.html')


@app.route('/login/go')
@auth.oidc_auth('orcid')
def login_go():
    _fetch_user_api_key()
    _sync_user_projects()
    return redirect(request.script_root + '/')


@app.route('/logout')
def logout():
    user_session = UserSession(flask.session)
    user_session.clear()
    flask.session.clear()
    return redirect(url_for('login'))


_USERNAME_RE = re.compile(r'^[a-z0-9_-]{3,32}$')


def _suggest_username(admin_client, email: str, first: str, last: str) -> str:
    """Return the first available username derived from email or name."""
    if email and '@' in email:
        base = email.split('@')[0].lower()
    else:
        base = f"{first}_{last}".lower() if first or last else ''
    base = re.sub(r'[^a-z0-9_-]', '_', base)
    base = re.sub(r'_+', '_', base).strip('_')[:28]
    if len(base) < 3:
        return ''
    for i in range(1, 4):
        candidate = base if i == 1 else f'{base}{i}'
        try:
            results = admin_client.users.search(candidate)
            if not any(r.get('username') == candidate for r in (results or [])):
                return candidate
        except Exception:
            return candidate
    return base


@app.route('/account/setup', methods=['GET', 'POST'])
def account_setup():
    try:
        user_session = UserSession(flask.session)
        userinfo = user_session.userinfo
    except Exception:
        return redirect(url_for('login'))
    if not userinfo:
        return redirect(url_for('login'))

    orcid = userinfo.get('sub', '')

    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name  = request.form.get('last_name',  '').strip()
        email      = request.form.get('email',    '').strip()
        username   = request.form.get('username', '').strip()
        error = None
        if not first_name:
            error = 'First name is required.'
        elif not last_name:
            error = 'Last name is required.'
        elif username and not _USERNAME_RE.match(username):
            error = 'Username must be 3–32 characters: lowercase letters, digits, hyphens, underscores.'
        if not error:
            try:
                app.admin_client.users.create({
                    'unique_id':  orcid,
                    'first_name': first_name,
                    'last_name':  last_name,
                    'email':      email    or None,
                    'username':   username or None,
                }, project_ids=[])
                flask.session['crucible_user_ok'] = True
                return redirect(request.script_root + '/')
            except Exception as e:
                app.logger.error("Account creation failed for %s: %s", orcid, e)
                resp = getattr(e, 'response', None)
                status = getattr(resp, 'status_code', 0) if resp else 0
                if username and status == 409:
                    error = f'Username @{username} is already taken — please choose a different one.'
                else:
                    error = 'Account creation failed. Please try again.'
        return render_template('account_setup.html',
                               orcid=orcid,
                               first_name=first_name,
                               last_name=last_name,
                               email=email,
                               username=username,
                               error=error)

    # GET — pre-fill from ORCID userinfo and suggest a username
    given  = userinfo.get('given_name', '')
    family = userinfo.get('family_name', '')
    if not given and not family:
        parts  = (userinfo.get('name') or '').rsplit(' ', 1)
        given  = parts[0] if len(parts) > 0 else ''
        family = parts[1] if len(parts) > 1 else ''
    email = userinfo.get('email', '')
    suggested_username = _suggest_username(app.admin_client, email, given, family)
    return render_template('account_setup.html',
                           orcid=orcid,
                           first_name=given,
                           last_name=family,
                           email=email,
                           username=suggested_username,
                           error=None)


@app.route('/account/profile', methods=['POST'])
def update_profile():
    try:
        user_session = UserSession(flask.session)
        userinfo = user_session.userinfo
    except Exception:
        return redirect(url_for('login'))
    if not userinfo:
        return redirect(url_for('login'))

    orcid      = userinfo.get('sub', '')
    first_name = request.form.get('first_name', '').strip()
    last_name  = request.form.get('last_name',  '').strip()
    email      = request.form.get('email',    '').strip()
    username   = request.form.get('username', '').strip()

    if username and not _USERNAME_RE.match(username):
        return redirect(f'{request.script_root}/user/{orcid}?update_error=1&error_msg=invalid_username')

    updates = {}
    if first_name: updates['first_name'] = first_name
    if last_name:  updates['last_name']  = last_name
    updates['email']    = email    or None
    updates['username'] = username or None

    try:
        get_user_client().account.update_profile(**updates)
        return redirect(f'{request.script_root}/user/{orcid}?updated=1')
    except Exception as e:
        app.logger.error("Profile update failed for %s: %s", orcid, e)
        resp = getattr(e, 'response', None)
        status = getattr(resp, 'status_code', 0) if resp else 0
        if username and status == 409:
            return redirect(f'{request.script_root}/user/{orcid}?update_error=1&error_msg=username_taken')
        return redirect(f'{request.script_root}/user/{orcid}?update_error=1')


@app.route('/api/check-username')
@auth.oidc_auth('orcid')
def check_username():
    q = request.args.get('q', '').strip().lower()
    if not _USERNAME_RE.match(q):
        return jsonify({'available': False})
    try:
        user_session = UserSession(flask.session)
        own_orcid = (user_session.userinfo or {}).get('sub', '')
        results = app.admin_client.users.search(q) or []
        # A match on your own ORCID is not "taken" — it's your current username
        taken = any(r.get('username') == q and r.get('unique_id') != own_orcid for r in results)
        return jsonify({'available': not taken})
    except Exception as e:
        app.logger.warning("check_username failed for %r: %s", q, e)
        return jsonify({'available': None})


@app.route('/profile')
def my_profile():
    try:
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
    except Exception:
        return redirect(url_for('login'))
    return redirect(f'{request.script_root}/user/{orcid}')


@app.route('/account/apikey')
def get_my_api_key():
    key = flask.session.get('crucible_apikey')
    if not key:
        return jsonify({'error': 'No API key in session'}), 404
    return jsonify({'api_key': key})


@auth.error_view
def error(error=None, error_description=None):
    if error == 'login_required':
        user_session = UserSession(flask.session)
        user_session.clear()
        return redirect(url_for('login'))
    app.logger.error("OIDC error: %s — %s", error, error_description)
    return redirect(url_for('login'))


# ── Error handlers ────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

_HTTP_MESSAGES = {
    403: "You don't have permission to access this resource.",
    404: "The resource you're looking for doesn't exist or has been removed.",
    500: "An unexpected error occurred. Please try again later.",
}

@app.errorhandler(requests.exceptions.HTTPError)
def handle_api_http_error(e):
    code = e.response.status_code if e.response is not None else 500
    logger.warning("API HTTPError %s: %s", code, e)
    message = _HTTP_MESSAGES.get(code, str(e))
    return render_template('error.html', code=code, message=message), code

@app.errorhandler(403)
def handle_403(e):
    return render_template('error.html', code=403, message=_HTTP_MESSAGES[403]), 403

@app.errorhandler(404)
def handle_404(e):
    return render_template('error.html', code=404, message=_HTTP_MESSAGES[404]), 404

@app.errorhandler(500)
def handle_500(e):
    logger.exception("Unhandled server error")
    return render_template('error.html', code=500, message=_HTTP_MESSAGES[500]), 500


# ── Plugin helpers passed to blueprints and view packages ─────────────────────
_plugin_helpers = {
    'get_project':              get_project,
    'get_entity_graph_nx':      get_entity_graph_nx,
    'get_project_graph':        get_project_graph,
    'clear_project_cache':      clear_project_cache,
    'is_user_in_project':       is_user_in_project,
}

# ── Route blueprints ──────────────────────────────────────────────────────────
from routes import register_routes
register_routes(app, auth, _plugin_helpers)

import views
views.register_all(app, auth, _plugin_helpers)
