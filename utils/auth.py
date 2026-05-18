import flask
from crucible import CrucibleClient


def get_user_client() -> CrucibleClient:
    """Return a per-request CrucibleClient using the logged-in user's API key.

    Cached on flask.g so it is created at most once per request.
    Aborts with 401 if no key is present in the session.
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
