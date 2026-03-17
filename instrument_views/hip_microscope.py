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
from crucible.models import BaseDataset

INSTRUMENT_TYPES = ['hip_microscope']
URL_PREFIX = '/instrument-view/hip-microscope'
VIEWS = [{'label': 'Upload Dataset', 'url': '/upload', 'icon': 'bi-upload'}]

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


def _run_job(job_id, tmpfile_path, project_id, dataset_name, measurement, sample_id, app):
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
                    BaseDataset(
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
                    client.add_sample_to_dataset(dataset_id, sample_id)

            _push(job_id, {
                'type': 'done',
                'dataset_id': dataset_id,
                'dataset_name': dataset_name,
                'measurement': measurement,
                'project_id': project_id,
                'dry_run': DRY_RUN,
            })

        except Exception as exc:
            app.logger.exception('hip_microscope upload job failed')
            _push(job_id, {'type': 'error', 'message': str(exc)})
        finally:
            _jobs[job_id]['done'] = True
            tmpdir = os.path.dirname(tmpfile_path)
            threading.Timer(600, lambda d=tmpdir: shutil.rmtree(d, ignore_errors=True)).start()


def create_blueprint(auth, helpers):
    bp = Blueprint('iview_hip_microscope', __name__)
    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/upload', methods=['GET'])
    @auth.oidc_auth('orcid')
    def upload():
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        projects = current_app.crucible_client.list_projects(orcid=orcid)
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
            args=(job_id, tmpfile_path, project_id, dataset_name, measurement, sample_id, app),
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

    @bp.route('/api/samples')
    @auth.oidc_auth('orcid')
    def api_samples():
        project_id = request.args.get('project_id', '').strip()
        q = request.args.get('q', '').lower()
        if not project_id or not is_user_in_project(project_id):
            abort(403)
        samples = current_app.crucible_client.list_samples(project_id=project_id)
        if q:
            samples = [s for s in samples if q in (s.get('sample_name') or '').lower()]
        return jsonify([{'id': s['unique_id'], 'name': s['sample_name']} for s in samples[:20]])

    return bp
