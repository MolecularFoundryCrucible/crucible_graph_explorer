import pytest
import flask
from unittest.mock import patch, MagicMock
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


def test_session_cookie_is_isolated(app):
    assert app.config['SESSION_COOKIE_NAME'] == 'crucible_explorer_session'
    assert app.config['SESSION_COOKIE_PATH'] == '/'
    assert app.config['SESSION_COOKIE_HTTPONLY'] is True
    assert app.config['SESSION_COOKIE_SECURE'] is False
    assert app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'


@pytest.mark.parametrize(('prefix', 'expected'), [
    ('', ''),
    ('/', ''),
    ('explore', '/explore'),
    ('/explore/', '/explore'),
])
def test_url_prefix_normalization(prefix, expected):
    from crucible_graph_explore_flask_app import _normalize_url_prefix

    assert _normalize_url_prefix(prefix) == expected


def test_fetch_user_api_key_stores_in_session(app):
    mock_us = MagicMock()
    mock_us.userinfo = {'sub': '0000-0001-2345-6789'}
    with app.test_request_context('/'):
        with patch('crucible_graph_explore_flask_app.UserSession', return_value=mock_us):
            with patch.object(app.admin_client, '_request', return_value={'api_key': 'user-key-xyz'}):
                from crucible_graph_explore_flask_app import _fetch_user_api_key
                _fetch_user_api_key()
                assert flask.session.get('crucible_apikey') == 'user-key-xyz'


def test_fetch_user_api_key_skips_if_already_set(app):
    with app.test_request_context('/'):
        flask.session['crucible_apikey'] = 'existing-key'
        with patch.object(app.admin_client, '_request') as mock_req:
            from crucible_graph_explore_flask_app import _fetch_user_api_key
            _fetch_user_api_key()
            mock_req.assert_not_called()


def test_fetch_user_api_key_tolerates_failure(app):
    mock_us = MagicMock()
    mock_us.userinfo = {'sub': '0000-0001-2345-6789'}
    with app.test_request_context('/'):
        with patch('crucible_graph_explore_flask_app.UserSession', return_value=mock_us):
            with patch.object(app.admin_client, '_request', side_effect=Exception('timeout')):
                from crucible_graph_explore_flask_app import _fetch_user_api_key
                _fetch_user_api_key()  # must not raise
                assert flask.session.get('crucible_apikey') is None
