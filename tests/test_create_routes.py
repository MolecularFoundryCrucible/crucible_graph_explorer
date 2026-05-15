import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def app():
    from crucible_graph_explore_flask_app import app as _app
    _app.config['TESTING'] = True
    return _app


@pytest.fixture
def client(app):
    return app.test_client()


def test_measurements_route_exists(app, client):
    """Route must exist (not 404) — auth redirect (302) or 200 is acceptable."""
    resp = client.get('/proj-x/api/measurements')
    assert resp.status_code != 404


def test_instruments_json_route_exists(app, client):
    """Route must exist (not 404)."""
    resp = client.get('/api/instruments')
    assert resp.status_code != 404


def test_create_sample_route_exists(app, client):
    """Route must exist (not 404)."""
    resp = client.post('/proj-x/api/samples/create',
                       json={'sample_name': 'Test'})
    assert resp.status_code != 404
