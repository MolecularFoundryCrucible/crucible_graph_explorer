from unittest.mock import MagicMock

from routes.projects import _dashboard_project_stats
from utils.cache import _project_cache


def test_dashboard_project_stats_combines_cached_and_api_counts():
    client = MagicMock()
    client.datasets.count.return_value = 12
    client.samples.count.return_value = 7
    _project_cache[('user-one', 'cached-project', False)] = {
        'datasets': [{}, {}],
        'samples': [{}],
    }

    result = _dashboard_project_stats(
        client,
        ['cached-project', 'api-project'],
        'user-one',
    )

    assert result == {
        'cached-project': {'datasets': 2, 'samples': 1},
        'api-project': {'datasets': 12, 'samples': 7},
    }
    client.datasets.count.assert_called_once_with(project_id='api-project')
    client.samples.count.assert_called_once_with(project_id='api-project')
    _project_cache.pop(('user-one', 'cached-project', False), None)


def test_dashboard_project_stats_keeps_partial_failures():
    client = MagicMock()
    client.datasets.count.side_effect = RuntimeError('unavailable')
    client.samples.count.return_value = 3

    result = _dashboard_project_stats(client, ['project-one'], 'user-one')

    assert result == {
        'project-one': {'datasets': None, 'samples': 3},
    }
