import logging
import time
from concurrent.futures import ThreadPoolExecutor

import flask
from flask import Blueprint, abort, jsonify, render_template, request
from flask_pyoidc.user_session import UserSession
from crucible.models import Dataset

from utils.auth import get_user_client
from utils.cache import (
    _project_cache,
    clear_project_cache, get_project, get_user_projects, warm_project_caches,
)
from utils.helpers import abbrev_name

logger = logging.getLogger(__name__)


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

        warm_project_caches([p['project_id'] for p in user_projects], client, orcid)

        return render_template('project_list.html', projects=user_projects, user_name=user_name)

    @bp.route("/api/dashboard-stats")
    @auth.oidc_auth('orcid')
    def dashboard_stats():
        """Return dataset/sample counts for requested projects (async dashboard endpoint)."""
        client = get_user_client()
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        ids = [i.strip() for i in request.args.get('ids', '').split(',') if i.strip()]
        if not ids:
            return jsonify({})

        def get_stats(pid):
            cached = _project_cache.get((orcid, pid, False))
            if cached is not None:
                return pid, len(cached.get('datasets', [])), len(cached.get('samples', []))
            try:
                with ThreadPoolExecutor(max_workers=2) as inner:
                    f_ds = inner.submit(client.datasets.count, project_id=pid)
                    f_s  = inner.submit(client.samples.count,  project_id=pid)
                return pid, f_ds.result(), f_s.result()
            except Exception:
                return pid, None, None

        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(get_stats, ids))

        return jsonify({pid: {'datasets': ds, 'samples': s} for pid, ds, s in results})

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

        owner_map: dict = {}
        project_users: list = []
        try:
            for u in (client.projects.get_users(project_id) or []):
                uid = u.get('unique_id')
                if not uid:
                    continue
                first    = u.get('first_name') or ''
                last     = u.get('last_name')  or ''
                name     = (first + ' ' + last).strip()
                email    = u.get('email')    or ''
                username = u.get('username') or ''
                owner_map[uid] = name or username or email or uid
                project_users.append({
                    'orcid':    uid,
                    'name':     name,
                    'username': username,
                    'email':    email,
                    'initials': ((first[:1] if first else '') + (last[:1] if last else '')).upper() or '?',
                })
            project_users.sort(key=lambda u: u['name'].lower() or u['orcid'])
        except Exception:
            pass
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
        sci_meta    = data.get('scientific_metadata') or None
        links       = data.get('links') or []

        parents         = [{'unique_id': l['id']} for l in links if l.get('type') == 'sample_parent'  and l.get('id')]
        children        = [{'unique_id': l['id']} for l in links if l.get('type') == 'sample_child'   and l.get('id')]
        linked_datasets = [l['id']               for l in links if l.get('type') == 'linked_dataset'  and l.get('id')]

        try:
            client = get_user_client()

            if not data.get('allow_duplicate'):
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

            result = client.samples.create(
                sample_name=sample_name,
                sample_type=sample_type,
                description=description,
                project_id=project_id,
                owner_orcid=orcid,
                timestamp=timestamp,
                public=public_val,
                parents=parents,
                children=children,
                scientific_metadata=sci_meta,
            )

            uid = result.get('unique_id', '')
            for did in linked_datasets:
                client.datasets.add_sample(did, uid)
        except Exception as exc:     
            return jsonify({'error': str(exc)}), 500

        clear_project_cache(project_id, orcid)
        return jsonify({
            'id':   uid,
            'name': result.get('sample_name', sample_name),
            'url':  f'{flask.request.script_root}/{project_id}/samples/{uid}',
        })

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
        instrument   = (data.get('instrument_name') or '').strip() or None
        data_type    = (data.get('data_type')       or '').strip() or None
        timestamp    = (data.get('timestamp')       or '').strip() or None
        public_val   = data.get('public')
        sci_meta     = data.get('scientific_metadata') or None
        links        = data.get('links') or []

        linked_samples  = [l['id'] for l in links if l.get('type') == 'linked_sample' and l.get('id')]
        parent_datasets = [l['id'] for l in links if l.get('type') == 'dataset_parent' and l.get('id')]
        child_datasets  = [l['id'] for l in links if l.get('type') == 'dataset_child' and l.get('id')]

        ds = Dataset(
            dataset_name=dataset_name,
            project_id=project_id,
            measurement=measurement,
            session_name=session_name,
            instrument_name=instrument,
            data_type=data_type,
            owner_orcid=orcid,
            timestamp=timestamp,
            public=public_val,
        )

        try:
            client = get_user_client()
            result = client.datasets.create(ds, scientific_metadata=sci_meta or {})
            uid = result['dsid']
            for sid in linked_samples:
                client.datasets.add_sample(uid, sid)
            for pid in parent_datasets:
                client.datasets.link_parent_child(pid, uid)
            for cid in child_datasets:
                client.datasets.link_parent_child(uid, cid)
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

        clear_project_cache(project_id, orcid)
        return jsonify({
            'id':   uid,
            'name': dataset_name,
            'url':  f'{flask.request.script_root}/{project_id}/datasets/{uid}',
        })

    @bp.route("/<project_id>/api/samples/<sample_id>/update", methods=['PATCH'])
    @auth.oidc_auth('orcid')
    def api_sample_update(project_id, sample_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        data = request.get_json(silent=True) or {}

        update_kwargs = {}
        for field in ('sample_name', 'sample_type', 'description', 'timestamp'):
            val = data.get(field)
            if val is not None:
                update_kwargs[field] = val.strip() if isinstance(val, str) else val

        public_val = data.get('public')
        if public_val is not None:
            update_kwargs['public'] = public_val

        sci_meta = data.get('scientific_metadata')

        try:
            client = get_user_client()
            result = client.samples.update(sample_id, **update_kwargs)
            if sci_meta is not None:
                client.samples.update_scientific_metadata(
                    sample_id, sci_meta, overwrite=True
                )
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

        clear_project_cache(project_id, orcid)
        uid = result.get('unique_id', sample_id)
        return jsonify({
            'id':   uid,
            'name': result.get('sample_name', ''),
            'url':  f'{flask.request.script_root}/{project_id}/samples/{uid}',
        })

    @bp.route("/<project_id>/api/datasets/<dataset_id>/update", methods=['PATCH'])
    @auth.oidc_auth('orcid')
    def api_dataset_update(project_id, dataset_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        data = request.get_json(silent=True) or {}

        update_kwargs = {}
        for field in ('dataset_name', 'measurement', 'session_name',
                      'instrument_name', 'data_type', 'timestamp'):
            val = data.get(field)
            if val is not None:
                update_kwargs[field] = val.strip() if isinstance(val, str) else val

        public_val = data.get('public')
        if public_val is not None:
            update_kwargs['public'] = public_val

        sci_meta = data.get('scientific_metadata')

        try:
            client = get_user_client()
            result = client.datasets.update(dataset_id, **update_kwargs)
            if sci_meta is not None:
                client.datasets.update_scientific_metadata(
                    dataset_id, sci_meta, overwrite=True
                )
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

        clear_project_cache(project_id, orcid)
        return jsonify({
            'id':   dataset_id,
            'name': result.get('dataset_name', ''),
            'url':  f'{flask.request.script_root}/{project_id}/datasets/{dataset_id}',
        })

    @bp.route("/<project_id>/api/resources/<resource_id>/request-deletion", methods=['POST'])
    @auth.oidc_auth('orcid')
    def api_request_deletion(project_id, resource_id):
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        data = request.get_json(silent=True) or {}
        reason = (data.get('reason') or '').strip() or None
        try:
            get_user_client().deletions.request(resource_id, reason=reason)
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500
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
            if link_type == 'sample_parent':
                client.samples.update(source_id, parents=[{'unique_id': target_id}])
            elif link_type == 'sample_child':
                client.samples.update(source_id, children=[{'unique_id': target_id}])
            elif link_type == 'linked_dataset':
                client.datasets.add_sample(target_id, source_id)
            elif link_type == 'dataset_parent':
                client.datasets.link_parent_child(target_id, source_id)
            elif link_type == 'dataset_child':
                client.datasets.link_parent_child(source_id, target_id)
            elif link_type == 'linked_sample':
                client.datasets.add_sample(source_id, target_id)
            else:
                return jsonify({'error': f'Unknown link_type: {link_type}'}), 400
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

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
            else:
                return jsonify({'error': f'Unknown link_type: {link_type}'}), 400
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

        clear_project_cache(project_id, orcid)
        return jsonify({'ok': True})

    return bp
