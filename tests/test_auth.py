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
