from unittest.mock import MagicMock

import pytest
from flask import Flask

from routes.project_settings import _allowed_roles, _sort_members, create_blueprint


class _Auth:
    def oidc_auth(self, *args, **kwargs):
        return lambda function: function


@pytest.fixture
def settings_app():
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(create_blueprint(_Auth()))
    return app


@pytest.fixture
def management_client(monkeypatch, settings_app):
    client = MagicMock()
    client.projects.get.return_value = {
        'project_id': 'project-1',
        'capabilities': {
            'can_edit': True,
            'can_manage_access': True,
            'can_transfer': True,
            'max_grant_role': 'admin',
        },
        'members': [
            {
                'unique_id': 'user-existing',
                'username': 'existing',
                'first_name': 'Existing',
                'last_name': 'Member',
                'role': 'contributor',
            },
        ],
    }
    monkeypatch.setattr('routes.project_settings.get_user_client', lambda: client)
    monkeypatch.setattr('routes.project_settings.clear_user_projects_cache', MagicMock())
    return client


def test_allowed_roles_respects_api_grant_ceiling():
    assert _allowed_roles({'max_grant_role': 'contributor'}) == [
        'viewer', 'contributor'
    ]
    assert _allowed_roles({'max_grant_role': 'editor'}) == [
        'viewer', 'contributor', 'editor'
    ]
    assert _allowed_roles({'max_grant_role': 'admin'}) == [
        'viewer', 'contributor', 'editor', 'admin'
    ]
    assert _allowed_roles({'max_grant_role': None}) == []


def test_sort_members_orders_roles_then_names():
    members = [
        {'unique_id': 'viewer', 'last_name': 'Zulu', 'role': 'viewer'},
        {'unique_id': 'editor-z', 'last_name': 'Zulu', 'role': 'editor'},
        {'unique_id': 'lead', 'last_name': 'Lead', 'role': 'owner'},
        {'unique_id': 'admin', 'last_name': 'Admin', 'role': 'admin'},
        {'unique_id': 'editor-a', 'last_name': 'Alpha', 'role': 'editor'},
    ]

    assert [member['unique_id'] for member in _sort_members(members)] == [
        'lead', 'admin', 'editor-a', 'editor-z', 'viewer'
    ]


def test_updates_project_fields_and_redirects_after_slug_change(
        monkeypatch, settings_app, management_client):
    management_client.projects.update.return_value = {
        **management_client.projects.get.return_value,
        'project_id': 'project-renamed',
        'title': 'Renamed project',
    }
    clear_project = MagicMock()
    clear_users = MagicMock()
    monkeypatch.setattr(
        'routes.project_settings.clear_project_cache', clear_project
    )
    monkeypatch.setattr(
        'routes.project_settings.clear_user_projects_cache', clear_users
    )

    response = settings_app.test_client().patch(
        '/project-1/api/settings',
        json={
            'project_id': 'project-renamed',
            'title': 'Renamed project',
            'organization': 'LBL',
            'status': 'active',
        },
    )

    assert response.status_code == 200
    assert response.get_json()['redirect_url'] == '/project-renamed/settings'
    management_client.projects.update.assert_called_once_with(
        'project-1',
        project_id='project-renamed',
        title='Renamed project',
        organization='LBL',
        status='active',
    )
    assert clear_project.call_args_list[0].args == ('project-1',)
    assert clear_project.call_args_list[1].args == ('project-renamed',)
    clear_users.assert_called_once_with('user-existing')


def test_project_update_rejects_unsupported_fields(
        settings_app, management_client):
    response = settings_app.test_client().patch(
        '/project-1/api/settings',
        json={'description': 'Not part of ProjectUpdate'},
    )

    assert response.status_code == 422
    management_client.projects.update.assert_not_called()


def test_member_candidates_searches_users_and_marks_existing(
        settings_app, management_client):
    management_client.users.search.return_value = [
        {
            'unique_id': 'user-existing',
            'username': 'existing',
            'first_name': 'Existing',
            'last_name': 'Member',
        },
        {
            'unique_id': 'user-new',
            'username': 'new-user',
            'first_name': 'New',
            'last_name': 'Member',
        },
    ]

    response = settings_app.test_client().get(
        '/project-1/api/member-candidates?q=mem'
    )

    assert response.status_code == 200
    assert response.get_json()[0]['already_member'] is True
    assert response.get_json()[1]['already_member'] is False
    management_client.users.search.assert_called_once_with('mem', limit=10)


def test_member_candidates_require_three_characters(settings_app):
    response = settings_app.test_client().get(
        '/project-1/api/member-candidates?q=ab'
    )

    assert response.status_code == 400
    assert response.get_json()['error'] == 'Enter at least 3 characters'


def test_member_management_requires_api_capability(
        settings_app, management_client):
    management_client.projects.get.return_value['capabilities'][
        'can_manage_access'
    ] = False

    response = settings_app.test_client().get(
        '/project-1/api/member-candidates?q=member'
    )

    assert response.status_code == 403


def test_member_removal_defers_self_or_owner_authorization_to_api(
        settings_app, management_client):
    management_client.projects.get.return_value['capabilities'][
        'can_manage_access'
    ] = False
    management_client.projects.remove_user.return_value = []

    response = settings_app.test_client().delete(
        '/project-1/api/members/user-existing'
    )

    assert response.status_code == 200
    management_client.projects.remove_user.assert_called_once_with(
        project_id='project-1', user_unique_id='user-existing'
    )


def test_add_update_and_remove_member(
        monkeypatch, settings_app, management_client):
    members = [
        {
            'unique_id': 'user-new',
            'username': 'new-user',
            'first_name': 'New',
            'last_name': 'Member',
            'role': 'contributor',
        },
    ]
    management_client.projects.add_user.return_value = members
    management_client.projects.update_user_role.return_value = members
    management_client.projects.remove_user.return_value = []
    clear_cache = MagicMock()
    monkeypatch.setattr(
        'routes.project_settings.clear_user_projects_cache', clear_cache
    )
    browser = settings_app.test_client()

    add_response = browser.post(
        '/project-1/api/members',
        json={'user_id': 'user-new', 'role': 'contributor'},
    )
    update_response = browser.patch(
        '/project-1/api/members/user-new',
        json={'role': 'editor'},
    )
    remove_response = browser.delete(
        '/project-1/api/members/user-new'
    )

    assert add_response.status_code == 200
    assert update_response.status_code == 200
    assert remove_response.status_code == 200
    management_client.projects.add_user.assert_called_once_with(
        user_unique_id='user-new', project_id='project-1', role='contributor'
    )
    management_client.projects.update_user_role.assert_called_once_with(
        'project-1', 'user-new', 'editor'
    )
    management_client.projects.remove_user.assert_called_once_with(
        project_id='project-1', user_unique_id='user-new'
    )
    assert clear_cache.call_count == 3


def test_rejects_role_above_api_grant_ceiling(
        settings_app, management_client):
    management_client.projects.get.return_value['capabilities'][
        'max_grant_role'
    ] = 'editor'

    response = settings_app.test_client().post(
        '/project-1/api/members',
        json={'user_id': 'user-new', 'role': 'admin'},
    )

    assert response.status_code == 403
    management_client.projects.add_user.assert_not_called()
