import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
import requests
from flask import Flask

from routes.projects import create_blueprint
from routes.datasets import create_blueprint as create_datasets_blueprint
from routes.instruments import create_blueprint as create_instruments_blueprint
from routes.samples import create_blueprint as create_samples_blueprint


class PassThroughAuth:
    def oidc_auth(self, *args, **kwargs):
        return lambda func: func


def http_error(status, detail):
    response = requests.Response()
    response.status_code = status
    response.reason = 'API error'
    response.headers['Content-Type'] = 'application/json'
    response._content = json.dumps({'detail': detail}).encode()
    return requests.HTTPError(f'{status} API error', response=response)


@pytest.fixture
def creation_client():
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='test')
    app.register_blueprint(create_blueprint(PassThroughAuth()))
    api = MagicMock()
    api.samples.get.return_value = {
        'unique_id': 'sample-1',
        'project_id': 'project-1',
    }
    api.datasets.get.return_value = {
        'unique_id': 'dataset-1',
        'project_id': 'project-1',
    }
    session = MagicMock()
    session.userinfo = {'sub': 'user-1'}
    with (
        patch('routes.projects.get_user_client', return_value=api),
        patch('routes.projects.UserSession', return_value=session),
        patch('routes.projects.clear_project_cache'),
    ):
        yield app.test_client(), api


def test_sample_creation_preserves_created_sample_when_relationship_fails(creation_client):
    client, api = creation_client
    api.samples.list.return_value = []
    api.samples.create.return_value = {
        'unique_id': 'sample-1',
        'sample_name': 'Sample',
    }
    api.samples.link.side_effect = RuntimeError('relationship failed')

    response = client.post('/project-1/api/samples/create', json={
        'sample_name': 'Sample',
        'links': [{'type': 'sample_parent', 'id': 'parent-1', 'name': 'Parent'}],
    })

    assert response.status_code == 201
    assert response.json['id'] == 'sample-1'
    assert response.json['partial'] is True
    assert response.json['retry']['links'] == [
        {'type': 'sample_parent', 'id': 'parent-1', 'name': 'Parent'},
    ]
    api.samples.create.assert_called_once()

    api.samples.link.side_effect = None
    retry = client.post('/project-1/api/samples/create', json={
        'sample_name': 'Sample',
        'resume_id': 'sample-1',
        'links': response.json['retry']['links'],
    })

    assert retry.status_code == 200
    assert retry.json['partial'] is False
    api.samples.create.assert_called_once()
    api.samples.link.assert_called_with('parent-1', 'sample-1')


def test_dataset_creation_preserves_created_dataset_when_metadata_fails(creation_client):
    client, api = creation_client
    api.datasets.create.return_value = {'dataset_mfid': 'dataset-1'}
    api.datasets.update_scientific_metadata.side_effect = RuntimeError('metadata failed')

    response = client.post('/project-1/api/datasets/create', json={
        'dataset_name': 'Dataset',
        'scientific_metadata': {'temperature': 300},
    })

    assert response.status_code == 201
    assert response.json['id'] == 'dataset-1'
    assert response.json['partial'] is True
    assert response.json['retry']['scientific_metadata'] == {'temperature': 300}
    api.datasets.create.assert_called_once()
    assert api.datasets.create.call_args.args[0].dataset_name == 'Dataset'
    assert api.datasets.create.call_args.kwargs == {}

    api.datasets.update_scientific_metadata.side_effect = None
    retry = client.post('/project-1/api/datasets/create', json={
        'dataset_name': 'Dataset',
        'resume_id': 'dataset-1',
        'scientific_metadata': response.json['retry']['scientific_metadata'],
    })

    assert retry.status_code == 200
    assert retry.json['partial'] is False
    api.datasets.create.assert_called_once()
    api.datasets.update_scientific_metadata.assert_called_with(
        'dataset-1', {'temperature': 300}
    )


def test_sample_create_preserves_api_validation_status_and_detail(creation_client):
    client, api = creation_client
    detail = [{
        'type': 'extra_forbidden',
        'loc': ['body', 'dataset_type'],
        'msg': 'Extra inputs are not permitted',
        'input': 'Sputtering Parameters',
    }]
    api.samples.list.return_value = []
    api.samples.create.side_effect = http_error(422, detail)

    response = client.post('/project-1/api/samples/create', json={
        'sample_name': 'Sample',
    })

    assert response.status_code == 422
    assert response.json['error'] == 'body.dataset_type: Extra inputs are not permitted'
    assert response.json['detail'] == detail


def test_dataset_update_preserves_permission_denial_status(creation_client):
    client, api = creation_client
    api.datasets.update.side_effect = http_error(403, 'Dataset edit permission required')

    response = client.patch('/project-1/api/datasets/dataset-1/update', json={
        'dataset_name': 'Updated',
    })

    assert response.status_code == 403
    assert response.json == {
        'detail': 'Dataset edit permission required',
        'error': 'Dataset edit permission required',
    }


def test_dataset_update_ignores_instrument_changes(creation_client):
    client, api = creation_client
    api.datasets.update.return_value = {
        'unique_id': 'dataset-1',
        'dataset_name': 'Updated',
    }

    response = client.patch('/project-1/api/datasets/dataset-1/update', json={
        'dataset_name': 'Updated',
        'instrument_name': 'Another Instrument',
        'instrument_id': 'another-instrument',
    })

    assert response.status_code == 200
    api.datasets.update.assert_called_once_with('dataset-1', dataset_name='Updated')


def test_dataset_update_rejects_wrong_project_context(creation_client):
    client, api = creation_client
    api.datasets.get.return_value = {
        'unique_id': 'dataset-1',
        'project_id': 'project-2',
    }

    response = client.patch('/project-1/api/datasets/dataset-1/update', json={
        'dataset_name': 'Updated',
    })

    assert response.status_code == 409
    assert response.json == {
        'error': 'Dataset belongs to project-2, not project-1.',
        'resource_project_id': 'project-2',
        'url': '/project-2/datasets/dataset-1',
    }
    api.datasets.update.assert_not_called()


def test_relationship_checks_source_but_allows_cross_project_target(creation_client):
    client, api = creation_client
    api.datasets.get.return_value = {
        'unique_id': 'dataset-1',
        'project_id': 'project-1',
    }

    response = client.post('/project-1/api/relationships', json={
        'link_type': 'linked_sample',
        'source_id': 'dataset-1',
        'target_id': 'sample-in-project-2',
    })

    assert response.status_code == 200
    api.datasets.add_sample.assert_called_once_with(
        'dataset-1', 'sample-in-project-2'
    )
    api.samples.get.assert_not_called()


def test_relationship_rejects_source_from_wrong_project(creation_client):
    client, api = creation_client
    api.samples.get.return_value = {
        'unique_id': 'sample-1',
        'project_id': 'project-2',
    }

    response = client.post('/project-1/api/relationships', json={
        'link_type': 'sample_child',
        'source_id': 'sample-1',
        'target_id': 'sample-2',
    })

    assert response.status_code == 409
    api.samples.update.assert_not_called()


@pytest.mark.parametrize(
    ('link_type', 'expected_parent', 'expected_child'),
    [
        ('sample_parent', 'sample-2', 'sample-1'),
        ('sample_child', 'sample-1', 'sample-2'),
    ],
)
def test_sample_relationship_add_uses_direct_link(
    creation_client, link_type, expected_parent, expected_child
):
    client, api = creation_client
    api.samples.get.return_value = {
        'unique_id': 'sample-1',
        'project_id': 'project-1',
    }

    response = client.post('/project-1/api/relationships', json={
        'link_type': link_type,
        'source_id': 'sample-1',
        'target_id': 'sample-2',
    })

    assert response.status_code == 200
    api.samples.link.assert_called_once_with(expected_parent, expected_child)
    api.samples.update.assert_not_called()


def test_creation_retry_rejects_resource_moved_to_another_project(creation_client):
    client, api = creation_client
    api.datasets.get.return_value = {
        'unique_id': 'dataset-1',
        'project_id': 'project-2',
    }

    response = client.post('/project-1/api/datasets/create', json={
        'dataset_name': 'Dataset',
        'resume_id': 'dataset-1',
        'scientific_metadata': {'temperature': 300},
    })

    assert response.status_code == 409
    api.datasets.update_scientific_metadata.assert_not_called()


def test_dataset_upload_rejects_wrong_project_context():
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='test')
    app.register_blueprint(create_datasets_blueprint(PassThroughAuth()))
    api = MagicMock()
    api.datasets.get.return_value = {
        'unique_id': 'dataset-1',
        'project_id': 'project-2',
    }

    with patch('routes.datasets.get_user_client', return_value=api):
        response = app.test_client().post(
            '/project-1/api/datasets/dataset-1/upload-file',
            data={'file': (BytesIO(b'data'), 'data.bin')},
        )

    assert response.status_code == 409
    api.datasets.add_file.assert_not_called()


def test_dataset_upload_uses_native_server_selected_ingestion():
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='test')
    app.register_blueprint(create_datasets_blueprint(PassThroughAuth()))
    api = MagicMock()
    api.datasets.get.return_value = {
        'unique_id': 'dataset-1',
        'project_id': 'project-1',
    }

    with patch('routes.datasets.get_user_client', return_value=api):
        response = app.test_client().post(
            '/project-1/api/datasets/dataset-1/upload-file',
            data={'file': (BytesIO(b'data'), 'data.bin')},
        )

    assert response.status_code == 200
    args = api.datasets.add_file.call_args.args
    kwargs = api.datasets.add_file.call_args.kwargs
    assert args[0] == 'dataset-1'
    assert args[1].endswith('/data.bin')
    assert kwargs == {'wait_for_ingestion_response': False}


@pytest.mark.parametrize('links', [
    'sample-1',
    ['sample-1'],
    [{'type': 'sample_parent'}],
    [{'type': 'unknown', 'id': 'sample-1'}],
    [{'type': 'sample_parent', 'id': 'sample-1', 'unexpected': True}],
])
def test_sample_create_rejects_malformed_links_before_creation(creation_client, links):
    client, api = creation_client

    response = client.post('/project-1/api/samples/create', json={
        'sample_name': 'Sample',
        'links': links,
    })

    assert response.status_code == 422
    assert response.json['detail'][0]['loc'][0] == 'links'
    api.samples.list.assert_not_called()
    api.samples.create.assert_not_called()


def test_dataset_create_rejects_non_object_metadata_before_creation(creation_client):
    client, api = creation_client

    response = client.post('/project-1/api/datasets/create', json={
        'dataset_name': 'Dataset',
        'scientific_metadata': ['not', 'an', 'object'],
    })

    assert response.status_code == 422
    assert response.json['detail'][0]['loc'] == ['scientific_metadata']
    api.datasets.create.assert_not_called()


def test_dataset_create_deduplicates_identical_relationships(creation_client):
    client, api = creation_client
    api.datasets.create.return_value = {'dataset_mfid': 'dataset-1'}
    link = {
        'type': 'linked_sample',
        'id': 'sample-1',
        'name': 'Sample',
        'label': 'Linked Sample',
    }

    response = client.post('/project-1/api/datasets/create', json={
        'dataset_name': 'Dataset',
        'links': [link, link],
    })

    assert response.status_code == 201
    api.datasets.add_sample.assert_called_once_with('dataset-1', 'sample-1')


def test_dataset_create_uses_registered_instrument_slug(creation_client):
    client, api = creation_client
    api.datasets.create.return_value = {'dataset_mfid': 'dataset-1'}

    response = client.post('/project-1/api/datasets/create', json={
        'dataset_name': 'Dataset',
        'instrument_id': 'als-bl12012',
    })

    assert response.status_code == 201
    dataset = api.datasets.create.call_args.args[0]
    assert dataset.instrument_id == 'als-bl12012'
    assert dataset.instrument_name is None


def test_dataset_create_rejects_display_name_as_identifier(creation_client):
    client, api = creation_client

    response = client.post('/project-1/api/datasets/create', json={
        'dataset_name': 'Dataset',
        'instrument_name': 'ALS-BL12012',
    })

    assert response.status_code == 422
    api.datasets.create.assert_not_called()


def test_instrument_options_expose_slug_name_and_mfid():
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='test')
    app.register_blueprint(create_instruments_blueprint(PassThroughAuth()))
    api = MagicMock()
    api.instruments.list.return_value = [{
        'unique_id': '01h00000000000000000000000',
        'instrument_id': 'als-bl12012',
        'instrument_name': 'ALS-BL12012',
    }]

    with patch('routes.instruments.get_user_client', return_value=api):
        response = app.test_client().get('/api/instruments')

    assert response.status_code == 200
    assert response.json == [{
        'instrument_id': 'als-bl12012',
        'mfid': '01h00000000000000000000000',
        'name': 'ALS-BL12012',
    }]


def test_legacy_sample_get_routes_redirect_to_active_pages():
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='test')
    app.register_blueprint(create_samples_blueprint(PassThroughAuth()))
    client = app.test_client()

    create_response = client.get('/project-1/samples/new')
    edit_response = client.get('/project-1/samples/sample-1/edit')

    assert create_response.status_code == 302
    assert create_response.headers['Location'] == '/project-1/'
    assert edit_response.status_code == 302
    assert edit_response.headers['Location'] == '/project-1/samples/sample-1'


@pytest.mark.parametrize('path', [
    '/project-1/samples/new',
    '/project-1/samples/sample-1/edit',
])
def test_legacy_sample_post_routes_are_removed(path):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='test')
    app.register_blueprint(create_samples_blueprint(PassThroughAuth()))

    response = app.test_client().post(path, data={'sample_name': 'Sample'})

    assert response.status_code == 405


def test_sample_update_retries_metadata_without_repeating_core_patch(creation_client):
    client, api = creation_client
    api.samples.update.return_value = {
        'unique_id': 'sample-1',
        'sample_name': 'Updated',
    }
    api.samples.update_scientific_metadata.side_effect = http_error(
        503, 'Metadata service unavailable'
    )

    response = client.patch('/project-1/api/samples/sample-1/update', json={
        'sample_name': 'Updated',
        'scientific_metadata': {'temperature': 300},
    })

    assert response.status_code == 200
    assert response.json['partial'] is True
    assert response.json['warnings'][0]['status'] == 503
    assert response.json['retry']['scientific_metadata'] == {'temperature': 300}
    api.samples.update.assert_called_once_with('sample-1', sample_name='Updated')

    api.samples.update_scientific_metadata.side_effect = None
    retry = client.patch('/project-1/api/samples/sample-1/update', json={
        'metadata_only': True,
        'scientific_metadata': response.json['retry']['scientific_metadata'],
    })

    assert retry.status_code == 200
    assert retry.json['partial'] is False
    api.samples.update.assert_called_once()
    api.samples.update_scientific_metadata.assert_called_with(
        'sample-1', {'temperature': 300}, overwrite=True
    )


def test_dataset_update_reports_metadata_failure_as_partial_success(creation_client):
    client, api = creation_client
    api.datasets.update.return_value = {
        'unique_id': 'dataset-1',
        'dataset_name': 'Updated',
    }
    api.datasets.update_scientific_metadata.side_effect = http_error(
        403, 'Metadata edit permission required'
    )

    response = client.patch('/project-1/api/datasets/dataset-1/update', json={
        'dataset_name': 'Updated',
        'scientific_metadata': {'temperature': 300},
    })

    assert response.status_code == 200
    assert response.json['partial'] is True
    assert response.json['warnings'][0] == {
        'detail': 'Metadata edit permission required',
        'error': 'Metadata edit permission required',
        'status': 403,
        'step': 'scientific_metadata',
    }
    api.datasets.update.assert_called_once_with('dataset-1', dataset_name='Updated')


def test_update_rejects_invalid_metadata_before_core_patch(creation_client):
    client, api = creation_client

    response = client.patch('/project-1/api/datasets/dataset-1/update', json={
        'dataset_name': 'Updated',
        'scientific_metadata': ['not', 'an', 'object'],
    })

    assert response.status_code == 422
    assert response.json['detail'][0]['loc'] == ['scientific_metadata']
    api.datasets.get.assert_not_called()
    api.datasets.update.assert_not_called()


def test_dataset_update_skips_unchanged_fields(creation_client):
    client, api = creation_client
    api.datasets.get.return_value = {
        'unique_id': 'dataset-1',
        'project_id': 'project-1',
        'dataset_name': 'Dataset',
        'measurement': 'XRD',
        'public': False,
        'scientific_metadata': {'temperature': 300},
    }

    response = client.patch('/project-1/api/datasets/dataset-1/update', json={
        'dataset_name': 'Dataset',
        'measurement': 'XRD',
        'public': False,
        'scientific_metadata': {'temperature': 300},
    })

    assert response.status_code == 200
    assert response.json['changed'] is False
    api.datasets.update.assert_not_called()
    api.datasets.update_scientific_metadata.assert_not_called()


def test_dataset_update_preserves_explicit_null_to_clear_field(creation_client):
    client, api = creation_client
    api.datasets.get.return_value = {
        'unique_id': 'dataset-1',
        'project_id': 'project-1',
        'dataset_name': 'Dataset',
        'session_name': 'Session',
    }
    api.datasets.update.return_value = {
        'unique_id': 'dataset-1',
        'dataset_name': 'Dataset',
        'session_name': None,
    }

    response = client.patch('/project-1/api/datasets/dataset-1/update', json={
        'session_name': None,
    })

    assert response.status_code == 200
    assert response.json['changed'] is True
    api.datasets.update.assert_called_once_with('dataset-1', session_name=None)


def test_sample_update_preserves_explicit_null_to_clear_field(creation_client):
    client, api = creation_client
    api.samples.get.return_value = {
        'unique_id': 'sample-1',
        'project_id': 'project-1',
        'sample_name': 'Sample',
        'description': 'Description',
    }
    api.samples._request.return_value = {
        'unique_id': 'sample-1',
        'sample_name': 'Sample',
        'description': None,
    }

    response = client.patch('/project-1/api/samples/sample-1/update', json={
        'description': None,
    })

    assert response.status_code == 200
    assert response.json['changed'] is True
    api.samples.update.assert_not_called()
    api.samples._request.assert_called_once_with(
        'patch', '/samples/sample-1', json={'description': None}
    )


def test_update_can_clear_metadata_without_core_patch(creation_client):
    client, api = creation_client
    api.samples.get.return_value = {
        'unique_id': 'sample-1',
        'project_id': 'project-1',
        'sample_name': 'Sample',
        'scientific_metadata': {'temperature': 300},
    }

    response = client.patch('/project-1/api/samples/sample-1/update', json={
        'scientific_metadata': {},
    })

    assert response.status_code == 200
    assert response.json['changed'] is True
    api.samples.update.assert_not_called()
    api.samples.update_scientific_metadata.assert_called_once_with(
        'sample-1', {}, overwrite=True
    )
