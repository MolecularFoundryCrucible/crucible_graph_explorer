import logging
import os

import flask
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_pyoidc import OIDCAuthentication
from flask_pyoidc.provider_configuration import ClientMetadata, ProviderConfiguration
from flask_pyoidc.user_session import UserSession
from flask_qrcode import QRcode
from flask_vite import Vite
from crucible import CrucibleClient

from utils.cache import clear_project_cache, get_project
from utils.graph import get_entity_graph_nx, get_project_graph
from utils.helpers import abbrev_name, humanize_size

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder="flask_templates")
QRcode(app)
Vite(app)

app.config.update(
    OIDC_REDIRECT_URI=os.getenv("OIDC_REDIRECT_URI"),
    SECRET_KEY=os.getenv("PYOIDC_SECRET"),
)

crucible_api_url = os.getenv("CRUCIBLE_API_URL", "https://crucible.lbl.gov/api/v2")
crucible_api_key = os.getenv("CRUCIBLE_API_KEY")
app.admin_client = CrucibleClient(api_url=crucible_api_url, api_key=crucible_api_key)
app.config['CRUCIBLE_API_URL'] = crucible_api_url

PROVIDER_NAME = 'orcid'
CLIENT_META = ClientMetadata(
    client_id=os.getenv("ORCID_CLIENT_ID"),
    client_secret=os.getenv("ORCID_CLIENT_SECRET"),
)
PROVIDER_CONFIG = ProviderConfiguration(issuer='https://orcid.org/', client_metadata=CLIENT_META)
auth = OIDCAuthentication({PROVIDER_NAME: PROVIDER_CONFIG}, app)


@app.template_filter('humanize_size')
def humanize_size_filter(n):
    return humanize_size(n)


@app.template_filter('humanize_date')
def humanize_date_filter(value):
    if not value:
        return None
    s = str(value)
    # ISO datetime: take just the date part, format nicely
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return dt.strftime('%b %-d, %Y')
    except Exception:
        return s[:10] if len(s) >= 10 else s


app.jinja_env.globals['abbrev_name'] = abbrev_name


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
_ACCOUNT_SETUP_PATHS = {'/account/setup', '/account/profile'}


def _fetch_user_api_key() -> None:
    """Fetch the user's personal Crucible API key and store it in the session.

    Calls GET /users/{orcid}/apikey via the admin client. Returns 404 if the
    user has no token yet. Silently logs and returns on any failure so login
    is never blocked.
    """
    if flask.session.get('crucible_apikey'):
        return
    try:
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        result = app.admin_client._request("GET", f"/users/{orcid}/apikey")
        key = result.get('api_key')
        if key:
            flask.session['crucible_apikey'] = key
    except Exception as e:
        app.logger.warning("Could not fetch user API key for %s: %s",
                           getattr(e, 'status_code', ''), e)


def _crucible_user_exists(orcid):
    """Return True if the ORCID has a Crucible account. Result cached in session."""
    if flask.session.get('crucible_user_ok'):
        return True
    try:
        app.admin_client.users.get(orcid)
        flask.session['crucible_user_ok'] = True
        return True
    except Exception as e:
        err = str(e).lower()
        if '404' in err or 'not found' in err:
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
            return redirect('/')
    except Exception:
        pass
    return render_template('login.html')


@app.route('/login/go')
@auth.oidc_auth('orcid')
def login_go():
    _fetch_user_api_key()
    return redirect('/')


@app.route('/logout')
def logout():
    user_session = UserSession(flask.session)
    user_session.clear()
    flask.session.clear()
    return redirect(url_for('login'))


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
        email      = request.form.get('email', '').strip()
        error = None
        if not first_name:
            error = 'First name is required.'
        elif not last_name:
            error = 'Last name is required.'
        if not error:
            try:
                app.admin_client.users.create({
                    'unique_id':  orcid,
                    'first_name': first_name,
                    'last_name':  last_name,
                    'email':      email or None,
                }, project_ids=[])
                flask.session['crucible_user_ok'] = True
                return redirect('/')
            except Exception as e:
                app.logger.error("Account creation failed for %s: %s", orcid, e)
                error = 'Account creation failed. Please try again.'
        return render_template('account_setup.html',
                               orcid=orcid,
                               first_name=first_name,
                               last_name=last_name,
                               email=email,
                               error=error)

    # GET — pre-fill from ORCID userinfo
    given  = userinfo.get('given_name', '')
    family = userinfo.get('family_name', '')
    if not given and not family:
        parts  = (userinfo.get('name') or '').rsplit(' ', 1)
        given  = parts[0] if len(parts) > 0 else ''
        family = parts[1] if len(parts) > 1 else ''
    return render_template('account_setup.html',
                           orcid=orcid,
                           first_name=given,
                           last_name=family,
                           email=userinfo.get('email', ''),
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
    email      = request.form.get('email', '').strip()

    updates = {}
    if first_name: updates['first_name'] = first_name
    if last_name:  updates['last_name']  = last_name
    updates['email'] = email or None

    try:
        app.admin_client.users.update(orcid, **updates)
        return redirect(f'/user/{orcid}?updated=1')
    except Exception as e:
        app.logger.error("Profile update failed for %s: %s", orcid, e)
        return redirect(f'/user/{orcid}?update_error=1')


@app.route('/profile')
def my_profile():
    try:
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
    except Exception:
        return redirect(url_for('login'))
    return redirect(f'/user/{orcid}')


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
}

# ── Route blueprints ──────────────────────────────────────────────────────────
from routes import register_routes
register_routes(app, auth, _plugin_helpers)

import views
views.register_all(app, auth, _plugin_helpers)
