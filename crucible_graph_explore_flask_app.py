import logging
import os

import flask
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template
from flask_pyoidc import OIDCAuthentication
from flask_pyoidc.provider_configuration import ClientMetadata, ProviderConfiguration
from flask_pyoidc.user_session import UserSession
from flask_qrcode import QRcode
from flask_vite import Vite
from crucible import CrucibleClient

from utils.cache import clear_project_cache, get_project, is_user_in_project
from utils.graph import get_entity_graph_nx, get_project_sample_graph, get_sample_lineage_graph
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
app.crucible_client = CrucibleClient(api_url=crucible_api_url, api_key=crucible_api_key)

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
        orcid = user_session.userinfo.get('sub')
        return {'current_user_orcid': orcid}
    except Exception:
        return {'current_user_orcid': None}


@auth.oidc_auth('orcid')
@app.route("/auth-test/")
def auth_test():
    user_session = UserSession(flask.session)
    return jsonify(access_token=user_session.access_token,
                   id_token=user_session.id_token,
                   userinfo=user_session.userinfo)


@auth.error_view
def error(error=None, error_description=None):
    if error == 'login_required':
        user_session = UserSession(flask.session)
        user_session.clear()
        return redirect('/')
    app.logger.error("OIDC error: %s — %s", error, error_description)
    return redirect('/')


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
    'is_user_in_project':       is_user_in_project,
    'get_project_sample_graph': get_project_sample_graph,
    'get_sample_lineage_graph': get_sample_lineage_graph,
    'get_entity_graph_nx':      get_entity_graph_nx,
    'clear_project_cache':      clear_project_cache,
}

# ── Route blueprints ──────────────────────────────────────────────────────────
from routes import register_routes
register_routes(app, auth, _plugin_helpers)

import views
views.register_all(app, auth, _plugin_helpers)
