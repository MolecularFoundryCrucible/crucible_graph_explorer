from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def app():
    from crucible_graph_explore_flask_app import app as flask_app
    flask_app.config['TESTING'] = True
    return flask_app


def test_instrument_detail_uses_mfid_and_limits_recent_datasets(app):
    client = MagicMock()
    client.instruments.get.return_value = {
        'unique_id': '0instrument000000000000000',
        'instrument_id': 'instrument-one',
        'instrument_name': 'Instrument One',
    }
    client.datasets.list.return_value = []
    client.datasets.count.return_value = 0

    with app.test_request_context('/instrument/0instrument000000000000000'):
        with patch('routes.instruments.get_user_client', return_value=client), \
                patch('routes.instruments.render_template', return_value='rendered'):
            response = app.view_functions['instruments_routes.instrument_detail'](
                '0instrument000000000000000'
            )

    assert response == 'rendered'
    client.datasets.list.assert_called_once_with(
        instrument_mfid='0instrument000000000000000',
        limit=50,
    )
    client.datasets.count.assert_called_once_with(
        instrument_mfid='0instrument000000000000000'
    )
