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
    with patch('utils.project_graph.generate_project_cache', return_value=fake_data):
        with app.test_request_context('/'):
            get_project('proj-a', 'orcid-1', client=mock_client)
            get_project('proj-a', 'orcid-2', client=mock_client)

    assert ('orcid-1', 'proj-a', False) in _project_cache
    assert ('orcid-2', 'proj-a', False) in _project_cache


def test_clear_project_cache_clears_for_orcid(app, mock_client):
    from utils.cache import get_project, clear_project_cache, _project_cache
    _project_cache.clear()

    fake_data = {'samples': [], 'datasets': []}
    with patch('utils.project_graph.generate_project_cache', return_value=fake_data):
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
        with patch('utils.auth.get_user_client', return_value=mock_user_client):
            result = is_user_in_project('proj-a', orcid='orcid-1')

    assert result is True
    mock_user_client.projects.list.assert_called_once_with(orcid='orcid-1')
