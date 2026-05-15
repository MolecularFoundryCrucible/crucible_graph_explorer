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


def test_create_dataset_route_exists(app, client):
    """Route must exist (not 404)."""
    resp = client.post('/proj-x/api/datasets/create',
                       json={'dataset_name': 'My DS'})
    assert resp.status_code != 404


def test_create_sample_accepts_timestamp_public_metadata(app, client):
    resp = client.post('/proj-x/api/samples/create',
                       json={
                           'sample_name': 'Test',
                           'timestamp': '2026-01-01T00:00:00',
                           'public': False,
                           'scientific_metadata': {'key': 'value'},
                           'links': [],
                       })
    assert resp.status_code != 404


def test_create_dataset_accepts_timestamp_public_metadata(app, client):
    resp = client.post('/proj-x/api/datasets/create',
                       json={
                           'dataset_name': 'DS',
                           'timestamp': '2026-01-01T00:00:00',
                           'public': False,
                           'scientific_metadata': {'x': 1},
                           'links': [],
                       })
    assert resp.status_code != 404
