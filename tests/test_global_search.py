from unittest.mock import MagicMock

from routes.search import _global_search_results, _project_search_results


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
