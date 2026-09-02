import flask
from flask import jsonify


def project_scope_conflict(resource, expected_project_id, resource_type=None):
    actual_project_id = resource.get('project_id')
    if actual_project_id == expected_project_id:
        return None

    if resource_type is None:
        resource_type = 'sample' if resource.get('sample_name') is not None else 'dataset'
    resource_id = resource.get('unique_id') or resource.get('dataset_mfid') or resource.get('sample_mfid')
    if actual_project_id:
        message = f'{resource_type.title()} belongs to {actual_project_id}, not {expected_project_id}.'
        url = f'{flask.request.script_root}/{actual_project_id}/{resource_type}s/{resource_id}'
    else:
        message = f'{resource_type.title()} is not associated with {expected_project_id}.'
        url = None

    payload = {
        'error': message,
        'resource_project_id': actual_project_id,
    }
    if url:
        payload['url'] = url
    return jsonify(payload), 409
