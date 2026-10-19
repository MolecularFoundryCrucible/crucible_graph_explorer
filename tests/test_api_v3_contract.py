from unittest.mock import Mock

from crucible import CrucibleClient
from crucible.models import Dataset, Sample


MFID = '01h00000000000000000000000'


def make_client():
    return CrucibleClient(api_url='https://example.invalid/api/v3', api_key='test')


def test_dataset_create_uses_api_v3_fields():
    client = make_client()
    client.datasets._request = Mock(return_value={'unique_id': MFID, 'public': False})

    client.datasets.create(Dataset(
        dataset_name='Sputtering Parameters',
        project_id='project-1',
        data_type='Sputtering Parameters',
        instrument_id='als-bl12012',
    ))

    payload = client.datasets._request.call_args.kwargs['json']
    assert payload['data_type'] == 'Sputtering Parameters'
    assert payload['instrument_id'] == 'als-bl12012'
    assert 'instrument_name' not in payload
    assert 'dataset_type' not in payload


def test_sample_create_uses_model_payload():
    client = make_client()
    client.samples._request = Mock(return_value={
        'unique_id': MFID,
        'sample_name': 'Sample',
    })

    client.samples.create(Sample(sample_name='Sample', project_id='project-1'))

    payload = client.samples._request.call_args.kwargs['json']
    assert payload['sample_name'] == 'Sample'
    assert payload['project_id'] == 'project-1'


def test_instrument_create_omits_response_only_model_fields():
    client = make_client()
    client.instruments._request = Mock(side_effect=[
        {'items': [], 'total': 0},
        {
            'unique_id': MFID,
            'instrument_id': 'als-bl12012',
            'instrument_name': 'ALS-BL12012',
            'owner_orcid': '0000-0000-0000-0000',
            'location': 'ALS-Building6',
        },
    ])

    client.instruments.create({
        'instrument_id': 'als-bl12012',
        'instrument_name': 'ALS-BL12012',
        'location': 'ALS-Building6',
        'owner': 'owner@example.org',
    })

    payload = client.instruments._request.call_args_list[1].kwargs['json']
    assert set(payload) == {'instrument_id', 'instrument_name', 'location', 'owner'}
