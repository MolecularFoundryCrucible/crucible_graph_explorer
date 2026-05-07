import json
import os
import shutil
import tempfile
import threading
import time
import uuid

import flask
import h5py
from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request, stream_with_context
from flask_pyoidc.user_session import UserSession
from crucible.models import Dataset

INSTRUMENT_TYPES = ['hip_microscope']
URL_PREFIX = '/instrument-view/hip-microscope'
VIEWS = [
    {'label': 'Upload Dataset', 'url': '/upload', 'icon': 'bi-upload'},
    {'label': 'Upload Session', 'url': '/upload/session', 'icon': 'bi-folder-plus'},
]

DRY_RUN = False  # set False to actually create Crucible datasets

# In-memory job store
_jobs: dict = {}

# Cache: file_token -> tmpfile_path (kept from /upload/parse so we don't re-upload)
_parse_cache: dict = {}


def _h5str(val):
    return val.decode() if isinstance(val, bytes) else str(val)


def _parse_h5_meta(path: str) -> dict:
    """Extract metadata from a ScopeFoundry H5 file."""
    with h5py.File(path, 'r') as f:
        # measurement type = name of the group under measurement/
        meas_group = f.get('measurement', {})
        measurement = next(iter(meas_group), None)

        # sample name from app/settings
        sample_name = ''
        app_settings = f.get('app/settings')
        if app_settings is not None:
            raw = app_settings.attrs.get('sample', '')
            sample_name = _h5str(raw)

        # proposal / orcid from mf_crucible hardware
        proposal = ''
        orcid = ''
        crucible_hw = f.get('hardware/mf_crucible/settings')
        if crucible_hw is not None:
            raw_p = crucible_hw.attrs.get('proposal', '')
            proposal = _h5str(raw_p)
            raw_o = crucible_hw.attrs.get('orcid', '')
            orcid = _h5str(raw_o)

    return {
        'measurement': measurement or '',
        'sample_name': sample_name,
        'proposal': proposal,
        'orcid': orcid,
    }


def _push(job_id: str, event: dict):
    job = _jobs.get(job_id)
    if job:
        with job['lock']:
            job['events'].append(event)


def _run_job(job_id, tmpfile_path, project_id, dataset_name, measurement, sample_id, app, clear_cache=None):
    """Background thread: upload single H5 file and push SSE progress events."""
    with app.app_context():
        client = app.crucible_client
        try:
            _push(job_id, {'type': 'info',
                           'message': '[DRY RUN] Creating dataset…' if DRY_RUN else 'Creating dataset…'})

            if DRY_RUN:
                time.sleep(1.0)
                dataset_id = f'dry-run-{uuid.uuid4().hex[:8]}'
            else:
                result = client.datasets.create_from_files(
                    Dataset(
                        dataset_name=dataset_name,
                        instrument_name='hip_microscope',
                        measurement=measurement,
                        project_id=project_id,
                    ),
                    files_to_upload=[tmpfile_path],
                    wait_for_ingestion_response=True,
                    ingestor=None,  # use default ingestor based on file type
                )
                dataset_id = result['created_record']['unique_id']

                if sample_id:
                    _push(job_id, {'type': 'info', 'message': 'Linking to sample…'})
                    client.datasets.add_sample(dataset_id, sample_id)

            _push(job_id, {
                'type': 'done',
                'dataset_id': dataset_id,
                'dataset_name': dataset_name,
                'measurement': measurement,
                'project_id': project_id,
                'dry_run': DRY_RUN,
            })
            if not DRY_RUN and clear_cache:
                clear_cache(project_id)

        except Exception as exc:
            app.logger.exception('hip_microscope upload job failed')
            _push(job_id, {'type': 'error', 'message': str(exc)})
        finally:
            _jobs[job_id]['done'] = True
            tmpdir = os.path.dirname(tmpfile_path)
            threading.Timer(600, lambda d=tmpdir: shutil.rmtree(d, ignore_errors=True)).start()


def _save_files(files, tmpdir):
    """Save werkzeug FileStorage list to tmpdir, stripping the leading folder component."""
    for f in files:
        rel = f.filename.replace('\\', '/')
        parts = rel.split('/', 1)
        rel_path = parts[1] if len(parts) > 1 else parts[0]
        dest = os.path.join(tmpdir, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        f.save(dest)


def _run_session_job(job_id, tmpdir, project_id, dataset_name, sample_id, app, clear_cache=None):
    """Background thread: upload session folder as parent + per-H5 child datasets."""
    with app.app_context():
        client = app.crucible_client
        try:
            h5_files = sorted(
                os.path.join(root, fname)
                for root, _, fnames in os.walk(tmpdir)
                for fname in fnames
                if fname.lower().endswith(('.h5', '.hdf5'))
            )
            all_files = [
                os.path.join(root, fname)
                for root, _, fnames in os.walk(tmpdir)
                for fname in fnames
            ]

            # ── parent session dataset ──────────────────────────────────
            _push(job_id, {'type': 'info',
                           'message': f'{"[DRY RUN] " if DRY_RUN else ""}Creating session dataset ({len(h5_files)} measurements)…'})
            if DRY_RUN:
                time.sleep(0.5)
                session_id = f'dry-run-session-{uuid.uuid4().hex[:8]}'
            else:
                result = client.datasets.create_from_files(
                    Dataset(
                        dataset_name=dataset_name,
                        instrument_name='hip_microscope',
                        measurement='hip_microscope_session',
                        project_id=project_id,
                    ),
                    files_to_upload=all_files,
                    wait_for_ingestion_response=False,
                )
                session_id = result['created_record']['unique_id']
                if sample_id:
                    client.datasets.add_sample(session_id, sample_id)

            _push(job_id, {
                'type': 'session',
                'dataset_id': session_id,
                'dataset_name': dataset_name,
                'project_id': project_id,
                'n_files': len(h5_files),
                'dry_run': DRY_RUN,
            })

            # ── per-H5 child datasets ───────────────────────────────────
            children = []
            for h5_path in h5_files:
                h5_name = os.path.splitext(os.path.basename(h5_path))[0]
                try:
                    measurement = _parse_h5_meta(h5_path).get('measurement') or 'hip_microscope_measurement'
                except Exception:
                    measurement = 'hip_microscope_measurement'

                if DRY_RUN:
                    time.sleep(0.1)
                    child_id = f'dry-run-{uuid.uuid4().hex[:8]}'
                else:
                    child_result = client.datasets.create_from_files(
                        Dataset(
                            dataset_name=h5_name,
                            instrument_name='hip_microscope',
                            measurement=measurement,
                            project_id=project_id,
                        ),
                        files_to_upload=[h5_path],
                        wait_for_ingestion_response=False,
                        ingestor=None,  # use default ingestor based on file type
                    )
                    child_id = child_result['created_record']['unique_id']
                    client.datasets.link_parent_child(session_id, child_id)
                    if sample_id:
                        client.datasets.add_sample(child_id, sample_id)

                ev = {'type': 'child', 'dataset_id': child_id,
                      'dataset_name': h5_name, 'measurement': measurement}
                _push(job_id, ev)
                children.append(ev)

            _push(job_id, {
                'type': 'done',
                'dataset_id': session_id,
                'dataset_name': dataset_name,
                'project_id': project_id,
                'children': children,
                'dry_run': DRY_RUN,
            })
            if not DRY_RUN and clear_cache:
                clear_cache(project_id)

        except Exception as exc:
            app.logger.exception('hip_microscope session upload job failed')
            _push(job_id, {'type': 'error', 'message': str(exc)})
        finally:
            _jobs[job_id]['done'] = True
            threading.Timer(600, lambda d=tmpdir: shutil.rmtree(d, ignore_errors=True)).start()


def create_blueprint(auth, helpers):
    bp = Blueprint('iview_hip_microscope', __name__)
    is_user_in_project = helpers['is_user_in_project']
    clear_project_cache = helpers.get('clear_project_cache')

    @bp.route('/upload', methods=['GET'])
    @auth.oidc_auth('orcid')
    def upload():
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        projects = current_app.crucible_client.projects.list(orcid=orcid)
        return render_template('instrument_views/hip_microscope_upload.html', projects=projects)

    @bp.route('/upload/parse', methods=['POST'])
    @auth.oidc_auth('orcid')
    def upload_parse():
        """Receive an H5 file, parse its metadata, cache the file, return JSON + file_token."""
        f = request.files.get('file')
        if not f or not f.filename:
            return jsonify({'error': 'No file.'}), 400
        filename = os.path.basename(f.filename) or 'upload.h5'
        tmpdir = tempfile.mkdtemp()
        tmp = os.path.join(tmpdir, filename)
        f.save(tmp)
        try:
            meta = _parse_h5_meta(tmp)
        except Exception as exc:
            shutil.rmtree(tmpdir, ignore_errors=True)
            return jsonify({'error': str(exc)}), 400
        # keep the file cached so the actual upload doesn't need to re-send it
        token = uuid.uuid4().hex
        _parse_cache[token] = tmp
        def _expire_token(t=token, d=tmpdir):
            _parse_cache.pop(t, None)
            shutil.rmtree(d, ignore_errors=True)
        threading.Timer(600, _expire_token).start()
        meta['dataset_name'] = os.path.splitext(os.path.basename(f.filename))[0]
        meta['file_token'] = token
        return jsonify(meta)

    @bp.route('/upload', methods=['POST'])
    @auth.oidc_auth('orcid')
    def upload_post():
        project_id = request.form.get('project_id', '').strip()
        if not project_id or not is_user_in_project(project_id):
            abort(403)

        token = request.form.get('file_token', '').strip()
        if token and token in _parse_cache:
            tmpfile_path = _parse_cache.pop(token)
            filename = os.path.basename(tmpfile_path)
        else:
            f = request.files.get('file')
            if not f or not f.filename:
                return jsonify({'error': 'No file received.'}), 400
            filename = os.path.basename(f.filename) or 'upload.h5'
            _tmpdir = tempfile.mkdtemp()
            tmpfile_path = os.path.join(_tmpdir, filename)
            f.save(tmpfile_path)

        dataset_name = request.form.get('dataset_name', '').strip() or os.path.splitext(filename)[0]
        measurement  = request.form.get('measurement', '').strip() or 'hip_microscope_measurement'
        sample_id    = request.form.get('sample_id', '').strip() or None

        job_id = str(uuid.uuid4())
        _jobs[job_id] = {'events': [], 'done': False, 'lock': threading.Lock()}

        app = current_app._get_current_object()
        threading.Thread(
            target=_run_job,
            args=(job_id, tmpfile_path, project_id, dataset_name, measurement, sample_id, app, clear_project_cache),
            daemon=True,
        ).start()

        return jsonify({'job_id': job_id})

    @bp.route('/upload/stream/<job_id>')
    @auth.oidc_auth('orcid')
    def upload_stream(job_id):
        def generate():
            cursor = 0
            while True:
                job = _jobs.get(job_id)
                if job is None:
                    yield f'data: {json.dumps({"type": "error", "message": "Job not found."})}\n\n'
                    return
                with job['lock']:
                    new_events = job['events'][cursor:]
                    is_done = job['done']
                for ev in new_events:
                    yield f'data: {json.dumps(ev)}\n\n'
                cursor += len(new_events)
                if is_done and not new_events:
                    return
                time.sleep(0.3)

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    @bp.route('/upload/session', methods=['GET'])
    @auth.oidc_auth('orcid')
    def upload_session():
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        projects = current_app.crucible_client.projects.list(orcid=orcid)
        return render_template('instrument_views/hip_microscope_session_upload.html', projects=projects)

    @bp.route('/upload/session/parse', methods=['POST'])
    @auth.oidc_auth('orcid')
    def upload_session_parse():
        """Parse a single H5 file from the folder for metadata — no caching."""
        f = request.files.get('file')
        if not f or not f.filename:
            return jsonify({'error': 'No file.'}), 400
        suffix = os.path.splitext(f.filename)[1] or '.h5'
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        f.save(tmp)
        try:
            meta = _parse_h5_meta(tmp)
        except Exception as exc:
            return jsonify({'error': str(exc)}), 400
        finally:
            os.unlink(tmp)
        return jsonify(meta)

    @bp.route('/upload/session', methods=['POST'])
    @auth.oidc_auth('orcid')
    def upload_session_post():
        project_id = request.form.get('project_id', '').strip()
        if not project_id or not is_user_in_project(project_id):
            abort(403)

        uploaded_files = request.files.getlist('files')
        if not uploaded_files or not any(f.filename for f in uploaded_files):
            return jsonify({'error': 'No files received.'}), 400

        first = uploaded_files[0].filename.replace('\\', '/')
        folder_name = first.split('/')[0] if '/' in first else 'hip_microscope_session'
        dataset_name = request.form.get('dataset_name', '').strip() or folder_name
        sample_id = request.form.get('sample_id', '').strip() or None

        tmpdir = tempfile.mkdtemp()
        _save_files(uploaded_files, tmpdir)

        job_id = str(uuid.uuid4())
        _jobs[job_id] = {'events': [], 'done': False, 'lock': threading.Lock()}

        app = current_app._get_current_object()
        threading.Thread(
            target=_run_session_job,
            args=(job_id, tmpdir, project_id, dataset_name, sample_id, app, clear_project_cache),
            daemon=True,
        ).start()

        return jsonify({'job_id': job_id})

    @bp.route('/api/samples')
    @auth.oidc_auth('orcid')
    def api_samples():
        project_id = request.args.get('project_id', '').strip()
        q = request.args.get('q', '').lower()
        if not project_id or not is_user_in_project(project_id):
            abort(403)
        samples = current_app.crucible_client.samples.list(project_id=project_id)
        if q:
            samples = [s for s in samples if q in (s.get('sample_name') or '').lower()]
        return jsonify([{'id': s['unique_id'], 'name': s['sample_name']} for s in samples[:20]])

    return bp
