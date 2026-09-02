from crucible.models import ProjectMember

from routes.projects import _project_member_display


def test_project_member_display_accepts_v3_member_dicts():
    owner_map, users = _project_member_display([
        {
            'unique_id': '0000-0001-1111-1111',
            'username': 'lead_user',
            'first_name': 'Project',
            'last_name': 'Lead',
            'role': 'owner',
        },
        {
            'unique_id': '0000-0002-2222-2222',
            'username': 'member_user',
            'first_name': 'Team',
            'last_name': 'Member',
            'role': 'contributor',
        },
    ])

    assert owner_map == {
        '0000-0001-1111-1111': 'Project Lead',
        '0000-0002-2222-2222': 'Team Member',
    }
    assert [user['orcid'] for user in users] == [
        '0000-0001-1111-1111',
        '0000-0002-2222-2222',
    ]
    assert users[0]['role'] == 'owner'
    assert [user['name'] for user in users] == ['P. Lead', 'T. Member']


def test_project_member_display_accepts_client_models():
    member = ProjectMember(
        unique_id='0000-0001-1111-1111',
        username='member_user',
        first_name='Team',
        last_name='Member',
        role='contributor',
    )

    owner_map, users = _project_member_display([member])

    assert owner_map[member.unique_id] == 'Team Member'
    assert users[0]['name'] == 'T. Member'
    assert users[0]['initials'] == 'TM'


def test_project_member_display_abbreviates_multiple_given_names():
    _, users = _project_member_display([{
        'unique_id': '0000-0003-3333-3333',
        'first_name': 'Jean Pierre',
        'last_name': 'Dupont',
        'role': 'viewer',
    }])

    assert users[0]['name'] == 'J. P. Dupont'


def test_project_member_display_sorts_by_role_then_name():
    _, users = _project_member_display([
        {'unique_id': 'viewer', 'first_name': 'Vera', 'last_name': 'Viewer', 'role': 'viewer'},
        {'unique_id': 'editor-z', 'first_name': 'Zoe', 'last_name': 'Editor', 'role': 'editor'},
        {'unique_id': 'owner', 'first_name': 'Olivia', 'last_name': 'Owner', 'role': 'owner'},
        {'unique_id': 'contributor', 'first_name': 'Chris', 'last_name': 'Contributor', 'role': 'contributor'},
        {'unique_id': 'admin', 'first_name': 'Alice', 'last_name': 'Admin', 'role': 'admin'},
        {'unique_id': 'editor-a', 'first_name': 'Amy', 'last_name': 'Editor', 'role': 'editor'},
    ])

    assert [user['orcid'] for user in users] == [
        'owner', 'admin', 'editor-a', 'editor-z', 'contributor', 'viewer'
    ]
