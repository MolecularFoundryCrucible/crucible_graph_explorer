import logging

import flask
from crucible import CrucibleClient
from flask_pyoidc.user_session import UserSession

logger = logging.getLogger(__name__)


def _make_response_logger(tag: str, user_id: str = "-"):
    """Build a requests 'response' hook that logs one line per Crucible API call.

    Captures every HTTP request the client makes — including the client's
    internal pagination pages — since they all flow through the session.

    user_id is captured at client-creation time and closed over here, because
    the hook may fire from ThreadPoolExecutor workers that have no Flask
    request context to read the user from.
    """
    def _log(response, *args, **kwargs):
        req = response.request
        size = response.headers.get('Content-Length', '?')
        logger.info(
            "%s user=%s %s %s -> %s %sB %.3fs",
            tag, user_id, req.method, req.path_url, response.status_code,
            size, response.elapsed.total_seconds(),
        )
    return _log


def attach_request_logging(client: CrucibleClient, tag: str = "crucible",
                           user_id: str = "-") -> CrucibleClient:
    """Log every Crucible API call this client makes (method, path, status, size, timing)."""
    client._session.hooks['response'].append(_make_response_logger(tag, user_id))
    return client


def get_user_client() -> CrucibleClient:
    """Return a per-request CrucibleClient using the logged-in user's API key.

    Cached on flask.g so it is created at most once per request.
    Aborts with 401 if no key is present in the session.
    """
    if 'user_client' not in flask.g:
        key = flask.session.get('crucible_apikey')
        if not key:
            flask.abort(401)
        try:
            orcid = UserSession(flask.session).userinfo.get('sub') or "-"
        except Exception:
            orcid = "-"
        client = CrucibleClient(
            api_url=flask.current_app.config['CRUCIBLE_API_URL'],
            api_key=key,
        )
        attach_request_logging(client, tag="crucible", user_id=orcid)
        flask.g.user_client = client
    return flask.g.user_client
