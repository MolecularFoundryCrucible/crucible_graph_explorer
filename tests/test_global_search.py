from unittest.mock import MagicMock

import pytest
from flask import Flask

from routes.search import (
    _global_search_results,
    _project_search_results,
    _resource_path,
    create_blueprint,
)


MFID = '01h' + ('0' * 23)


class _Auth:
    def oidc_auth(self, *args, **kwargs):
        return lambda function: function


@pytest.fixture
def search_app():
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(create_blueprint(_Auth()))
    return app


def test_global_search_uses_v3_search_endpoints():
    client = MagicMock()
    client.projects.search.return_value = [{
        'unique_id': 'project-mfid',
        'project_id': 'project-one',
        'title': 'Alpha project',
    }]
    client.samples.search.return_value = [{
        'unique_id': 'sample-one',
        'sample_name': 'Alpha sample',
        'project_id': 'project-one',
    }]
    client.datasets.search.return_value = [{
        'unique_id': 'dataset-one',
        'dataset_name': 'Alpha dataset',
        'project_id': 'project-one',
    }]
    client.instruments.search.return_value = [{
        'unique_id': 'instrument-mfid',
        'instrument_id': 'instrument-one',
        'instrument_name': 'Alpha instrument',
    }]

    results, failures = _global_search_results(client, 'alpha')

    client.projects.search.assert_called_once_with('alpha', limit=20)
    client.samples.search.assert_called_once_with('alpha', limit=20)
    client.datasets.search.assert_called_once_with('alpha', limit=20)
    client.instruments.search.assert_called_once_with('alpha', limit=20)
    assert results['projects'][0]['_url'] == '/project-one/'
    assert results['samples'][0]['_url'] == '/project-one/samples/sample-one'
    assert results['datasets'][0]['_url'] == '/project-one/datasets/dataset-one'
    assert results['instruments'][0]['_url'] == '/instrument/instrument-mfid'
    assert failures == []


def test_global_search_preserves_partial_results():
    client = MagicMock()
    client.samples.search.side_effect = RuntimeError('unavailable')
    client.projects.search.return_value = []
    client.datasets.search.return_value = [{
        'unique_id': 'dataset-one',
        'dataset_name': 'Alpha dataset',
        'project_id': 'project-one',
    }]
    client.instruments.search.return_value = []

    results, failures = _global_search_results(client, 'alpha')

    assert results['samples'] == []
    assert len(results['datasets']) == 1
    assert failures == ['samples']


def test_project_search_uses_scoped_v3_endpoints():
    client = MagicMock()
    client.samples.search.return_value = []
    client.datasets.search.return_value = []

    results, failures = _project_search_results(client, 'alpha', 'project-one')

    client.samples.search.assert_called_once_with(
        'alpha',
        project_id='project-one',
        limit=20,
    )
    client.datasets.search.assert_called_once_with(
        'alpha',
        project_id='project-one',
        limit=20,
    )
    assert results == {'samples': [], 'datasets': []}
    assert failures == []


@pytest.mark.parametrize(('resource', 'expected'), [
    (
        {'resource_type': 'dataset', 'unique_id': 'dataset-mfid', 'project_id': 'project-one'},
        '/project-one/datasets/dataset-mfid',
    ),
    (
        {'resource_type': 'sample', 'unique_id': 'sample-mfid', 'project_id': 'project-one'},
        '/project-one/samples/sample-mfid',
    ),
    (
        {'resource_type': 'instrument', 'unique_id': 'instrument-mfid'},
        '/instrument/instrument-mfid',
    ),
    (
        {'resource_type': 'project', 'unique_id': 'project-mfid', 'project_id': 'project-one'},
        '/project-one/',
    ),
])
def test_resource_path_maps_supported_resources(resource, expected):
    assert _resource_path(resource) == expected


def test_resource_location_resolves_mfid_with_user_client(
        monkeypatch, search_app):
    client = MagicMock()
    client.get.return_value = {
        'resource_type': 'dataset',
        'unique_id': MFID,
        'project_id': 'project-one',
    }
    monkeypatch.setattr('routes.search.get_user_client', lambda: client)

    response = search_app.test_client().get(
        f'/api/resource-location/{MFID}',
        environ_overrides={'SCRIPT_NAME': '/explore'},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        'resource_type': 'dataset',
        'url': f'/explore/project-one/datasets/{MFID}',
    }
    client.get.assert_called_once_with(MFID, include_owner=False)


def test_resource_location_rejects_non_mfid_without_api_call(
        monkeypatch, search_app):
    client = MagicMock()
    monkeypatch.setattr('routes.search.get_user_client', lambda: client)

    response = search_app.test_client().get('/api/resource-location/not-an-mfid')

    assert response.status_code == 400
    client.get.assert_not_called()
