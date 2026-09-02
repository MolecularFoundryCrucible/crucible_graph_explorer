import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import flask
from flask import Blueprint, abort, jsonify, render_template, request
from flask_pyoidc.user_session import UserSession
from crucible.models import Dataset, Sample
from pydantic import ValidationError

from utils.auth import get_user_client
from utils.api_errors import api_error_payload, api_error_response, validation_error_response
from utils.cache import (
    _project_cache,
    clear_project_cache, get_project, get_user_projects,
)
from utils.helpers import abbrev_name
from utils.creation_validation import validate_creation_extras, validate_scientific_metadata
from utils.resource_scope import project_scope_conflict

logger = logging.getLogger(__name__)
_DASHBOARD_PROJECT_LIMIT = 100
_PROJECT_ROLE_ORDER = {
    'owner': 0,
    'admin': 1,
    'editor': 2,
    'contributor': 3,
    'viewer': 4,
}


def _slim_sample(s):
    return {
        'unique_id':   s['unique_id'],
        'sample_name': s.get('sample_name') or '',
        'sample_type': s.get('sample_type') or '',
        'owner_orcid': s.get('owner_orcid') or '',
        'timestamp':   s.get('timestamp') or '',
    }


def _slim_dataset(ds):
    return {
        'unique_id':       ds['unique_id'],
        'dataset_name':    ds.get('dataset_name') or '',
        'measurement':     ds.get('measurement') or '',
        'instrument_name': ds.get('instrument_name') or '',
        'session_name':    ds.get('session_name') or '',
        'data_format':     ds.get('data_format') or '',
        'owner_orcid':     ds.get('owner_orcid') or '',
        'timestamp':       ds.get('timestamp') or '',
        'cross_project':   bool(ds.get('cross_project')),
    }


def _project_member_display(members):
    owner_map = {}
    project_users = []
    for member in members or []:
        user = member.model_dump() if hasattr(member, 'model_dump') else member
        uid = user.get('unique_id')
        if not uid:
            continue
        first = (user.get('first_name') or '').strip()
        last = (user.get('last_name') or '').strip()
        full_name = f'{first} {last}'.strip()
        name = abbrev_name(first, last)
        email = user.get('email') or ''
        username = user.get('username') or ''
        owner_map[uid] = full_name or username or email or uid
        project_users.append({
            'orcid': uid,
            'name': name,
            'username': username,
            'email': email,
            'role': user.get('role') or '',
            'initials': (first[:1] + last[:1]).upper() or '?',
        })
    project_users.sort(key=lambda user: (
        _PROJECT_ROLE_ORDER.get(user['role'], len(_PROJECT_ROLE_ORDER)),
        user['name'].casefold() or user['orcid'],
    ))
    return owner_map, project_users


def _dashboard_project_stats(client, project_ids, orcid):
    stats = {}
    uncached = []
    for project_id in project_ids:
        cached = _project_cache.get((orcid, project_id, False))
        if cached is not None:
            stats[project_id] = {
                'datasets': len(cached.get('datasets', [])),
                'samples': len(cached.get('samples', [])),
            }
        else:
            stats[project_id] = {'datasets': None, 'samples': None}
            uncached.append(project_id)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {}
        for project_id in uncached:
            futures[executor.submit(
                client.datasets.count,
                project_id=project_id,
            )] = (project_id, 'datasets')
            futures[executor.submit(
                client.samples.count,
                project_id=project_id,
            )] = (project_id, 'samples')

        for future in as_completed(futures):
            project_id, resource_type = futures[future]
            try:
                stats[project_id][resource_type] = future.result()
            except Exception:
                pass

    return stats


def create_blueprint(auth):
    bp = Blueprint('projects', __name__)

    @bp.route("/")
    @auth.oidc_auth('orcid')
    def list_projects():
        client = get_user_client()
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        info = user_session.userinfo
        user_name = info.get('given_name') or info.get('name') or orcid
        user_projects = get_user_projects(orcid, client, force_refresh=True)

        for p in user_projects:
            lead = p.get('lead') or {}
            first = (lead.get('first_name') or '').strip()
            last  = (lead.get('last_name')  or '').strip()
            email = lead.get('email') or p.get('project_lead_email') or ''
            p['project_lead_email'] = email
            p['project_lead_name']  = abbrev_name(first, last) or email

        return render_template('project_list.html', projects=user_projects, user_name=user_name)

    @bp.route("/api/dashboard-stats")
    @auth.oidc_auth('orcid')
    def dashboard_stats():
        """Return dataset/sample counts for requested projects (async dashboard endpoint)."""
        client = get_user_client()
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        ids = list(dict.fromkeys(
            value.strip()
            for value in request.args.get('ids', '').split(',')
            if value.strip()
        ))
        if not ids:
            return jsonify({})
        if len(ids) > _DASHBOARD_PROJECT_LIMIT:
            return jsonify({
                'error': f'At most {_DASHBOARD_PROJECT_LIMIT} projects may be requested'
            }), 400

        return jsonify(_dashboard_project_stats(client, ids, orcid))

    @bp.route("/<project_id>/")
    @auth.oidc_auth('orcid')
    def project_overview(project_id):
        import views.projects as project_views
        _t0 = time.perf_counter()
        client = get_user_client()
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        _t_client = time.perf_counter()

        user_projects = get_user_projects(orcid, client)
        _t_projects = time.perf_counter()

        project_meta = next((p for p in user_projects if p['project_id'] == project_id), None)
        if project_meta is None:
            abort(403)

        try:
            project_with_members = client.projects.get(
                project_id=project_id,
                include_members=True,
            )
            owner_map, project_users = _project_member_display(
                project_with_members.get('members')
            )
            project_capabilities = project_with_members.get('capabilities') or {}
        except Exception as exc:
            logger.warning("Could not load members for project %s: %s", project_id, exc)
            owner_map, project_users = {}, []
            project_capabilities = {}
        _t_users = time.perf_counter()

        logger.info(
            "project_overview %s timing: client=%.3fs get_user_projects=%.3fs "
            "get_users=%.3fs total=%.3fs",
            project_id,
            _t_client - _t0,
            _t_projects - _t_client,
            _t_users - _t_projects,
            _t_users - _t0,
        )

        # Samples and datasets are loaded asynchronously by the page JS
        # via /api/overview-data — no get_project() call here.
        return render_template('project_overview.html',
                               pc={'project_id': project_id},
                               project_meta=project_meta,
                               owner_map=owner_map,
                               project_users=project_users,
                               project_capabilities=project_capabilities,
                               all_projects=user_projects,
                               custom_views=project_views.get_views(project_id))

    @bp.route("/<project_id>/api/overview-data")
    @auth.oidc_auth('orcid')
    def project_api_overview_data(project_id):
        """Return slim samples + datasets JSON for async project overview loading."""
        _t0 = time.perf_counter()
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        client = get_user_client()

        if request.args.get('refresh'):
            clear_project_cache(project_id, orcid)
        cache_hit = (orcid, project_id, False) in _project_cache
        pc = get_project(project_id, orcid, client=client)
        _t_get = time.perf_counter()

        payload = {
            'samples':  [_slim_sample(s)   for s in pc['samples']],
            'datasets': [_slim_dataset(ds) for ds in pc['datasets']],
        }
        _t_slim = time.perf_counter()

        logger.info(
            "overview-data %s timing: cache_hit=%s get_project=%.3fs slim=%.3fs "
            "total=%.3fs (samples=%d datasets=%d)",
            project_id, cache_hit,
            _t_get - _t0,
            _t_slim - _t_get,
            _t_slim - _t0,
            len(pc['samples']), len(pc['datasets']),
        )
        return jsonify(payload)

    @bp.route("/<project_id>/api/sample-types")
    @auth.oidc_auth('orcid')
    def project_api_sample_types(project_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        q = request.args.get('q', '').lower()
        pc = get_project(project_id, orcid)
        types = sorted({s.get('sample_type') for s in pc['samples'] if s.get('sample_type')})
        if q:
            types = [t for t in types if q in t.lower()]
        return jsonify(types)

    @bp.route("/<project_id>/api/samples")
    @auth.oidc_auth('orcid')
    def api_samples(project_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        q = request.args.get('q', '').lower()
        pc = get_project(project_id, orcid)
        samples = pc['samples']
        if q:
            samples = [s for s in samples
                       if q in (s.get('sample_name') or '').lower()
                       or q in (s.get('unique_id') or '').lower()]
        return jsonify([
            {'id': s['unique_id'], 'name': s['sample_name'], 'type': s.get('sample_type') or ''}
            for s in samples[:20]
        ])

    @bp.route("/<project_id>/api/datasets")
    @auth.oidc_auth('orcid')
    def api_datasets(project_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        q = request.args.get('q', '').lower()
        pc = get_project(project_id, orcid)
        datasets = pc['datasets']
        if q:
            datasets = [d for d in datasets
                        if q in (d.get('dataset_name') or '').lower()
                        or q in (d.get('unique_id') or '').lower()]
        return jsonify([{'id': d['unique_id'], 'name': d['dataset_name']} for d in datasets[:20]])

    @bp.route("/<project_id>/api/measurements")
    @auth.oidc_auth('orcid')
    def project_api_measurements(project_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        q = request.args.get('q', '').lower()
        pc = get_project(project_id, orcid)
        types = sorted({
            ds.get('measurement')
            for ds in pc['datasets']
            if ds.get('measurement')
        })
        if q:
            types = [t for t in types if q in t.lower()]
        return jsonify(types)

    @bp.route("/<project_id>/api/samples/create", methods=['POST'])
    @auth.oidc_auth('orcid')
    def api_sample_create(project_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        data = request.get_json(silent=True) or {}

        sample_name = (data.get('sample_name') or '').strip()
        if not sample_name:
            return jsonify({'error': 'sample_name is required'}), 400

        sample_type = (data.get('sample_type') or '').strip() or None
        description = (data.get('description') or '').strip() or None
        timestamp   = (data.get('timestamp')   or '').strip() or None
        public_val  = data.get('public')
        try:
            links, sci_meta = validate_creation_extras(data, 'sample')
        except ValidationError as exc:
            return validation_error_response(exc)
        resume_id   = (data.get('resume_id') or '').strip() or None

        try:
            client = get_user_client()

            if not resume_id and not data.get('allow_duplicate'):
                existing = client.samples.list(sample_name=sample_name, project_id=project_id)
                if existing:
                    return jsonify({'conflict': True, 'matches': [
                        {
                            'id':   s['unique_id'],
                            'name': s['sample_name'],
                            'type': s.get('sample_type') or '',
                            'url':  f"{flask.request.script_root}/{project_id}/samples/{s['unique_id']}",
                        }
                        for s in existing
                    ]}), 409

            if resume_id:
                conflict = project_scope_conflict(
                    client.samples.get(resume_id), project_id, 'sample'
                )
                if conflict:
                    return conflict
                uid = resume_id
                result = {'unique_id': uid, 'sample_name': sample_name}
            else:
                result = client.samples.create(Sample(
                    sample_name=sample_name,
                    sample_type=sample_type,
                    description=description,
                    project_id=project_id,
                    timestamp=timestamp,
                    public=public_val,
                ))
                uid = result['unique_id']
        except Exception as exc:
            return api_error_response(exc)

        failed_links = []
        warnings = []
        metadata_failed = False

        if sci_meta:
            try:
                client.samples.update_scientific_metadata(uid, sci_meta)
            except Exception as exc:
                metadata_failed = True
                warning, status = api_error_payload(exc)
                warnings.append({'step': 'scientific_metadata', 'status': status, **warning})

        for link in links:
            link_type = link.get('type')
            link_id = link.get('id')
            if not link_id:
                continue
            try:
                if link_type == 'sample_parent':
                    client.samples.link(link_id, uid)
                elif link_type == 'sample_child':
                    client.samples.link(uid, link_id)
                elif link_type == 'linked_dataset':
                    client.datasets.add_sample(link_id, uid)
            except Exception as exc:
                failed_links.append(link)
                warning, status = api_error_payload(exc)
                warnings.append({'step': 'relationship', 'target_id': link_id, 'status': status, **warning})

        clear_project_cache(project_id, orcid)
        response = {
            'created': True,
            'id':   uid,
            'name': result.get('sample_name', sample_name),
            'url':  f'{flask.request.script_root}/{project_id}/samples/{uid}',
            'partial': bool(warnings),
            'warnings': warnings,
            'retry': {
                'links': failed_links,
                'scientific_metadata': sci_meta if metadata_failed else None,
            },
        }
        return jsonify(response), 200 if resume_id else 201

    @bp.route("/<project_id>/api/datasets/create", methods=['POST'])
    @auth.oidc_auth('orcid')
    def api_dataset_create(project_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        data = request.get_json(silent=True) or {}

        dataset_name = (data.get('dataset_name') or '').strip()
        if not dataset_name:
            return jsonify({'error': 'dataset_name is required'}), 400

        measurement  = (data.get('measurement')     or '').strip() or None
        session_name = (data.get('session_name')    or '').strip() or None
        instrument_id = (data.get('instrument_id') or '').strip() or None
        if data.get('instrument_name'):
            return jsonify({
                'error': 'instrument_name is display-only; submit instrument_id instead'
            }), 422
        data_type    = (data.get('data_type')       or '').strip() or None
        timestamp    = (data.get('timestamp')       or '').strip() or None
        public_val   = data.get('public')
        try:
            links, sci_meta = validate_creation_extras(data, 'dataset')
        except ValidationError as exc:
            return validation_error_response(exc)
        resume_id    = (data.get('resume_id') or '').strip() or None

        ds = Dataset(
            dataset_name=dataset_name,
            project_id=project_id,
            measurement=measurement,
            session_name=session_name,
            instrument_id=instrument_id,
            data_type=data_type,
            timestamp=timestamp,
            public=public_val,
        )

        try:
            client = get_user_client()
            if resume_id:
                conflict = project_scope_conflict(
                    client.datasets.get(resume_id), project_id, 'dataset'
                )
                if conflict:
                    return conflict
                uid = resume_id
            else:
                result = client.datasets.create(ds)
                uid = result['dataset_mfid']
        except Exception as exc:
            return api_error_response(exc)

        failed_links = []
        warnings = []
        metadata_failed = False

        if sci_meta:
            try:
                client.datasets.update_scientific_metadata(uid, sci_meta)
            except Exception as exc:
                metadata_failed = True
                warning, status = api_error_payload(exc)
                warnings.append({'step': 'scientific_metadata', 'status': status, **warning})

        for link in links:
            link_type = link.get('type')
            link_id = link.get('id')
            if not link_id:
                continue
            try:
                if link_type == 'linked_sample':
                    client.datasets.add_sample(uid, link_id)
                elif link_type == 'dataset_parent':
                    client.datasets.link_parent_child(link_id, uid)
                elif link_type == 'dataset_child':
                    client.datasets.link_parent_child(uid, link_id)
            except Exception as exc:
                failed_links.append(link)
                warning, status = api_error_payload(exc)
                warnings.append({'step': 'relationship', 'target_id': link_id, 'status': status, **warning})

        clear_project_cache(project_id, orcid)
        response = {
            'created': True,
            'id':   uid,
            'name': dataset_name,
            'url':  f'{flask.request.script_root}/{project_id}/datasets/{uid}',
            'partial': bool(warnings),
            'warnings': warnings,
            'retry': {
                'links': failed_links,
                'scientific_metadata': sci_meta if metadata_failed else None,
            },
        }
        return jsonify(response), 200 if resume_id else 201

    @bp.route("/<project_id>/api/samples/<sample_id>/update", methods=['PATCH'])
    @auth.oidc_auth('orcid')
    def api_sample_update(project_id, sample_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        data = request.get_json(silent=True) or {}

        update_kwargs = {}
        for field in ('sample_name', 'sample_type', 'description', 'timestamp'):
            if field in data:
                val = data[field]
                update_kwargs[field] = val.strip() if isinstance(val, str) else val

        public_val = data.get('public')
        if public_val is not None:
            update_kwargs['public'] = public_val

        metadata_only = data.get('metadata_only') is True
        try:
            sci_meta = (
                validate_scientific_metadata(data.get('scientific_metadata'))
                if 'scientific_metadata' in data else None
            )
        except ValidationError as exc:
            return validation_error_response(exc)
        if metadata_only and sci_meta is None:
            return jsonify({'error': 'scientific_metadata is required for metadata retry'}), 400

        try:
            client = get_user_client()
            current = client.samples.get(sample_id, include_metadata=True)
            conflict = project_scope_conflict(current, project_id, 'sample')
            if conflict:
                return conflict
            if not metadata_only:
                update_kwargs = {
                    key: value for key, value in update_kwargs.items()
                    if current.get(key) != value
                }
            core_changed = bool(update_kwargs) and not metadata_only
            if core_changed and any(value is None for value in update_kwargs.values()):
                result = client.samples._request(
                    'patch', f'/samples/{sample_id}', json=update_kwargs
                )
            elif core_changed:
                result = client.samples.update(sample_id, **update_kwargs)
            else:
                result = current
        except Exception as exc:
            return api_error_response(exc)

        warnings = []
        metadata_failed = False
        metadata_changed = (
            'scientific_metadata' in data
            and sci_meta is not None
            and current.get('scientific_metadata') != sci_meta
        )
        if metadata_changed:
            try:
                client.samples.update_scientific_metadata(
                    sample_id, sci_meta, overwrite=True
                )
            except Exception as exc:
                metadata_failed = True
                warning, status = api_error_payload(exc)
                warnings.append({'step': 'scientific_metadata', 'status': status, **warning})

        if core_changed or (metadata_changed and not metadata_failed):
            clear_project_cache(project_id, orcid)
        uid = result.get('unique_id', sample_id)
        return jsonify({
            'id':   uid,
            'name': result.get('sample_name', ''),
            'url':  f'{flask.request.script_root}/{project_id}/samples/{uid}',
            'partial': metadata_failed,
            'changed': core_changed or (metadata_changed and not metadata_failed),
            'warnings': warnings,
            'retry': {
                'scientific_metadata': sci_meta if metadata_failed else None,
            },
        })

    @bp.route("/<project_id>/api/datasets/<dataset_id>/update", methods=['PATCH'])
    @auth.oidc_auth('orcid')
    def api_dataset_update(project_id, dataset_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        data = request.get_json(silent=True) or {}

        update_kwargs = {}
        for field in ('dataset_name', 'measurement', 'session_name',
                      'data_type', 'timestamp'):
            if field in data:
                val = data[field]
                update_kwargs[field] = val.strip() if isinstance(val, str) else val

        public_val = data.get('public')
        if public_val is not None:
            update_kwargs['public'] = public_val

        metadata_only = data.get('metadata_only') is True
        try:
            sci_meta = (
                validate_scientific_metadata(data.get('scientific_metadata'))
                if 'scientific_metadata' in data else None
            )
        except ValidationError as exc:
            return validation_error_response(exc)
        if metadata_only and sci_meta is None:
            return jsonify({'error': 'scientific_metadata is required for metadata retry'}), 400

        try:
            client = get_user_client()
            current = client.datasets.get(dataset_id, include_metadata=True)
            conflict = project_scope_conflict(current, project_id, 'dataset')
            if conflict:
                return conflict
            if not metadata_only:
                update_kwargs = {
                    key: value for key, value in update_kwargs.items()
                    if current.get(key) != value
                }
            core_changed = bool(update_kwargs) and not metadata_only
            result = (
                client.datasets.update(dataset_id, **update_kwargs)
                if core_changed else current
            )
        except Exception as exc:
            return api_error_response(exc)

        warnings = []
        metadata_failed = False
        metadata_changed = (
            'scientific_metadata' in data
            and sci_meta is not None
            and current.get('scientific_metadata') != sci_meta
        )
        if metadata_changed:
            try:
                client.datasets.update_scientific_metadata(
                    dataset_id, sci_meta, overwrite=True
                )
            except Exception as exc:
                metadata_failed = True
                warning, status = api_error_payload(exc)
                warnings.append({'step': 'scientific_metadata', 'status': status, **warning})

        if core_changed or (metadata_changed and not metadata_failed):
            clear_project_cache(project_id, orcid)
        return jsonify({
            'id':   dataset_id,
            'name': result.get('dataset_name', ''),
            'url':  f'{flask.request.script_root}/{project_id}/datasets/{dataset_id}',
            'partial': metadata_failed,
            'changed': core_changed or (metadata_changed and not metadata_failed),
            'warnings': warnings,
            'retry': {
                'scientific_metadata': sci_meta if metadata_failed else None,
            },
        })

    @bp.route("/<project_id>/api/resources/<resource_id>/request-deletion", methods=['POST'])
    @auth.oidc_auth('orcid')
    def api_request_deletion(project_id, resource_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        data = request.get_json(silent=True) or {}
        reason = (data.get('reason') or '').strip() or None
        try:
            client = get_user_client()
            resource = client._request('get', f'/resources/{resource_id}')
            conflict = project_scope_conflict(resource, project_id)
            if conflict:
                return conflict
            client.deletions.request(resource_id, reason=reason)
        except Exception as exc:
            return api_error_response(exc)
        clear_project_cache(project_id, orcid)
        return jsonify({'ok': True})

    @bp.route("/<project_id>/api/relationships", methods=['POST'])
    @auth.oidc_auth('orcid')
    def api_relationship_add(project_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        data = request.get_json(silent=True) or {}

        link_type = data.get('link_type', '')
        source_id = data.get('source_id', '')
        target_id = data.get('target_id', '')

        if not link_type or not source_id or not target_id:
            return jsonify({'error': 'link_type, source_id, and target_id are required'}), 400

        try:
            client = get_user_client()
            sample_link_types = {'sample_parent', 'sample_child', 'linked_dataset'}
            dataset_link_types = {'dataset_parent', 'dataset_child', 'linked_sample'}
            if link_type in sample_link_types:
                source = client.samples.get(source_id)
                source_type = 'sample'
            elif link_type in dataset_link_types:
                source = client.datasets.get(source_id)
                source_type = 'dataset'
            else:
                return jsonify({'error': f'Unknown link_type: {link_type}'}), 400
            conflict = project_scope_conflict(source, project_id, source_type)
            if conflict:
                return conflict

            if link_type == 'sample_parent':
                client.samples.link(target_id, source_id)
            elif link_type == 'sample_child':
                client.samples.link(source_id, target_id)
            elif link_type == 'linked_dataset':
                client.datasets.add_sample(target_id, source_id)
            elif link_type == 'dataset_parent':
                client.datasets.link_parent_child(target_id, source_id)
            elif link_type == 'dataset_child':
                client.datasets.link_parent_child(source_id, target_id)
            elif link_type == 'linked_sample':
                client.datasets.add_sample(source_id, target_id)
        except Exception as exc:
            return api_error_response(exc)

        clear_project_cache(project_id, orcid)
        return jsonify({'ok': True})

    @bp.route("/<project_id>/api/relationships", methods=['DELETE'])
    @auth.oidc_auth('orcid')
    def api_relationship_delete(project_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        data = request.get_json(silent=True) or {}

        link_type = data.get('link_type', '')
        source_id = data.get('source_id', '')
        target_id = data.get('target_id', '')

        if not link_type or not source_id or not target_id:
            return jsonify({'error': 'link_type, source_id, and target_id are required'}), 400

        try:
            client = get_user_client()
            sample_link_types = {'sample_parent', 'sample_child', 'linked_dataset'}
            dataset_link_types = {'dataset_parent', 'dataset_child', 'linked_sample'}
            if link_type in sample_link_types:
                source = client.samples.get(source_id)
                source_type = 'sample'
            elif link_type in dataset_link_types:
                source = client.datasets.get(source_id)
                source_type = 'dataset'
            else:
                return jsonify({'error': f'Unknown link_type: {link_type}'}), 400
            conflict = project_scope_conflict(source, project_id, source_type)
            if conflict:
                return conflict

            if link_type == 'sample_parent':
                # source=child sample, target=parent sample → remove parent
                client.samples.remove_child(target_id, source_id)
            elif link_type == 'sample_child':
                # source=parent sample, target=child sample → remove child
                client.samples.remove_child(source_id, target_id)
            elif link_type == 'linked_dataset':
                # source=sample, target=dataset → unlink
                client.samples.remove_dataset(source_id, target_id)
            elif link_type == 'dataset_parent':
                # source=child dataset, target=parent dataset → remove parent
                client.datasets.remove_child(target_id, source_id)
            elif link_type == 'dataset_child':
                # source=parent dataset, target=child dataset → remove child
                client.datasets.remove_child(source_id, target_id)
            elif link_type == 'linked_sample':
                # source=dataset, target=sample → unlink
                client.datasets.remove_sample(source_id, target_id)
        except Exception as exc:
            return api_error_response(exc)

        clear_project_cache(project_id, orcid)
        return jsonify({'ok': True})

    return bp
