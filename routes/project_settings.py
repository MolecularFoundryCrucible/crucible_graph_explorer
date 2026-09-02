import logging

from flask import Blueprint, abort, jsonify, render_template, request
from flask_pyoidc.user_session import UserSession
from werkzeug.exceptions import HTTPException

import flask

from utils.api_errors import api_error_response
from utils.auth import get_user_client
from utils.cache import clear_project_cache, clear_user_projects_cache

logger = logging.getLogger(__name__)

_PROJECT_ROLES = ('viewer', 'contributor', 'editor', 'admin')
_PROJECT_ROLE_ORDER = {
    'owner': 0,
    'admin': 1,
    'editor': 2,
    'contributor': 3,
    'viewer': 4,
}
_PROJECT_UPDATE_FIELDS = {'project_id', 'organization', 'status', 'title'}


def _member_dict(member):
    return member.model_dump() if hasattr(member, 'model_dump') else dict(member)


def _allowed_roles(capabilities):
    maximum = capabilities.get('max_grant_role')
    if maximum not in _PROJECT_ROLES:
        return []
    return list(_PROJECT_ROLES[:_PROJECT_ROLES.index(maximum) + 1])


def _project_context(client, project_id):
    project = client.projects.get(project_id=project_id, include_members=True)
    capabilities = project.get('capabilities') or {}
    members = [_member_dict(member) for member in (project.get('members') or [])]
    return project, capabilities, members


def _sort_members(members):
    return sorted(members, key=lambda member: (
        _PROJECT_ROLE_ORDER.get(
            member.get('role'), len(_PROJECT_ROLE_ORDER)
        ),
        (member.get('last_name') or '').casefold(),
        (member.get('first_name') or '').casefold(),
        member.get('unique_id') or '',
    ))


def _management_context(client, project_id):
    project, capabilities, members = _project_context(client, project_id)
    if not capabilities.get('can_manage_access'):
        abort(403)
    return project, capabilities, _sort_members(members)


def create_blueprint(auth):
    bp = Blueprint('project_settings', __name__)

    @bp.route('/<project_id>/settings')
    @auth.oidc_auth('orcid')
    def project_general_settings(project_id):
        client = get_user_client()
        try:
            project, capabilities, _ = _project_context(client, project_id)
            if not capabilities.get('can_edit'):
                abort(403)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Could not load project settings for %s: %s",
                           project_id, exc)
            return api_error_response(exc)

        return render_template(
            'project_settings.html',
            project=project,
            project_id=project_id,
            capabilities=capabilities,
        )

    @bp.route('/<project_id>/api/settings', methods=['PATCH'])
    @auth.oidc_auth('orcid')
    def update_project_settings(project_id):
        data = request.get_json(silent=True) or {}
        extra_fields = set(data) - _PROJECT_UPDATE_FIELDS
        if extra_fields:
            return jsonify({
                'error': f"Unsupported project fields: {', '.join(sorted(extra_fields))}"
            }), 422

        updates = {}
        for field in _PROJECT_UPDATE_FIELDS:
            if field not in data:
                continue
            value = data[field]
            if isinstance(value, str):
                value = value.strip()
            if field in {'project_id', 'organization'} and not value:
                return jsonify({'error': f'{field} cannot be empty'}), 422
            updates[field] = value or None

        try:
            client = get_user_client()
            project, capabilities, members = _project_context(client, project_id)
            if not capabilities.get('can_edit'):
                abort(403)
            updates = {
                field: value for field, value in updates.items()
                if project.get(field) != value
            }
            result = (
                client.projects.update(project_id, **updates)
                if updates else project
            )
        except HTTPException:
            raise
        except (TypeError, ValueError) as exc:
            return jsonify({'error': str(exc)}), 422
        except Exception as exc:
            return api_error_response(exc)

        new_project_id = result.get('project_id') or project_id
        if updates:
            clear_project_cache(project_id)
            if new_project_id != project_id:
                clear_project_cache(new_project_id)
            for member in members:
                if member.get('unique_id'):
                    clear_user_projects_cache(member['unique_id'])

        return jsonify({
            'changed': bool(updates),
            'project': result,
            'redirect_url': (
                f'{request.script_root}/{new_project_id}/settings'
                if new_project_id != project_id else None
            ),
        })

    @bp.route('/<project_id>/settings/members')
    @auth.oidc_auth('orcid')
    def project_members(project_id):
        client = get_user_client()
        try:
            project, capabilities, members = _project_context(client, project_id)
            members = _sort_members(members)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Could not load project membership settings for %s: %s",
                           project_id, exc)
            return api_error_response(exc)

        current_user = UserSession(flask.session).userinfo.get('sub', '')
        return render_template(
            'project_members.html',
            project=project,
            project_id=project_id,
            members=members,
            capabilities=capabilities,
            allowed_roles=_allowed_roles(capabilities),
            current_user=current_user,
        )

    @bp.route('/<project_id>/api/member-candidates')
    @auth.oidc_auth('orcid')
    def member_candidates(project_id):
        query = request.args.get('q', '').strip()
        if len(query) < 3:
            return jsonify({'error': 'Enter at least 3 characters'}), 400
        try:
            client = get_user_client()
            _, _, members = _management_context(client, project_id)
            existing_ids = {member.get('unique_id') for member in members}
            candidates = client.users.search(query, limit=10)
        except HTTPException:
            raise
        except Exception as exc:
            return api_error_response(exc)

        return jsonify([
            {
                'unique_id': candidate.get('unique_id'),
                'username': candidate.get('username'),
                'first_name': candidate.get('first_name'),
                'last_name': candidate.get('last_name'),
                'already_member': candidate.get('unique_id') in existing_ids,
            }
            for candidate in candidates
            if candidate.get('unique_id')
        ])

    @bp.route('/<project_id>/api/members', methods=['POST'])
    @auth.oidc_auth('orcid')
    def add_member(project_id):
        data = request.get_json(silent=True) or {}
        user_id = (data.get('user_id') or '').strip()
        role = (data.get('role') or '').strip()
        if not user_id:
            return jsonify({'error': 'Select a user'}), 400
        try:
            client = get_user_client()
            _, capabilities, _ = _management_context(client, project_id)
            if role not in _allowed_roles(capabilities):
                return jsonify({'error': 'You cannot grant that role'}), 403
            members = client.projects.add_user(
                user_unique_id=user_id,
                project_id=project_id,
                role=role,
            )
        except HTTPException:
            raise
        except Exception as exc:
            return api_error_response(exc)
        clear_user_projects_cache(user_id)
        return jsonify({'members': [_member_dict(member) for member in members]})

    @bp.route('/<project_id>/api/members/<user_id>', methods=['PATCH'])
    @auth.oidc_auth('orcid')
    def update_member_role(project_id, user_id):
        data = request.get_json(silent=True) or {}
        role = (data.get('role') or '').strip()
        try:
            client = get_user_client()
            _, capabilities, _ = _management_context(client, project_id)
            if role not in _allowed_roles(capabilities):
                return jsonify({'error': 'You cannot grant that role'}), 403
            members = client.projects.update_user_role(project_id, user_id, role)
        except HTTPException:
            raise
        except Exception as exc:
            return api_error_response(exc)
        clear_user_projects_cache(user_id)
        return jsonify({'members': [_member_dict(member) for member in members]})

    @bp.route('/<project_id>/api/members/<user_id>', methods=['DELETE'])
    @auth.oidc_auth('orcid')
    def remove_member(project_id, user_id):
        try:
            client = get_user_client()
            _project_context(client, project_id)
            members = client.projects.remove_user(
                project_id=project_id,
                user_unique_id=user_id,
            )
        except HTTPException:
            raise
        except Exception as exc:
            return api_error_response(exc)
        clear_user_projects_cache(user_id)
        return jsonify({'members': [_member_dict(member) for member in members]})

    return bp
