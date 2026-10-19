from unittest.mock import MagicMock

from crucible.models import ProjectMember

from routes.users import _project_members


def test_project_members_converts_v3_models_to_dicts():
    client = MagicMock()
    client.projects.get_users.return_value = [ProjectMember(
        unique_id='0000-0001-1111-1111',
        username='member_user',
        first_name='Team',
        last_name='Member',
        role='contributor',
    )]

    members = _project_members(client, 'project-one')

    assert members == [{
        'unique_id': '0000-0001-1111-1111',
        'username': 'member_user',
        'first_name': 'Team',
        'last_name': 'Member',
        'email': None,
        'is_service_account': None,
        'role': 'contributor',
    }]


def test_project_members_handles_api_failure():
    client = MagicMock()
    client.projects.get_users.side_effect = RuntimeError('unavailable')

    assert _project_members(client, 'project-one') == []
