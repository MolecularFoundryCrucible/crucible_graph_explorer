import glob
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import flask
import pandas as pd
import yaml
from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request, stream_with_context
from flask_pyoidc.user_session import UserSession
from crucible.models import Dataset

INSTRUMENT_TYPES = ['als-bl12012']
URL_PREFIX = '/instrument-view/als-bl12012'
VIEWS = [{'label': 'Upload Run', 'url': '/upload', 'icon': 'bi-upload'}]

DRY_RUN = True  # set False to actually create Crucible datasets

# In-memory job store: job_id -> {events, done, lock}
_jobs: dict = {}


def _push(job_id: str, event: dict):
    job = _jobs.get(job_id)
    if job:
        with job['lock']:
            job['events'].append(event)


def _save_files(files, tmpdir):
    """Save werkzeug FileStorage list to tmpdir, stripping the leading folder component."""
    for f in files:
        rel = f.filename.replace('\\', '/')
        parts = rel.split('/', 1)
        rel_path = parts[1] if len(parts) > 1 else parts[0]
        dest = os.path.join(tmpdir, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        f.save(dest)


def _run_job(job_id, tmpdir, project_id, dataset_name, app):
    """Background thread: run upload and push SSE progress events."""
    with app.app_context():
        client = app.crucible_client
        try:
            # 1. existing ID from crucible.yaml
            existing_id = None
            yaml_path = os.path.join(tmpdir, 'crucible.yaml')
            if os.path.exists(yaml_path):
                with open(yaml_path) as fh:
                    info = yaml.safe_load(fh) or {}
                existing_id = info.get('unique_id')

            # 2. parse position table
            _push(job_id, {'type': 'info', 'message': '[DRY RUN] Parsing sample position file…' if DRY_RUN else 'Parsing sample position file…'})
            pos_files = sorted(
                glob.glob(os.path.join(tmpdir, 'sample_holder_position_readout_*.txt')),
                reverse=True,
            )
            if not pos_files:
                raise ValueError("No sample_holder_position_readout_*.txt file found.")
            df = pd.concat([pd.read_csv(f, sep='\t') for f in pos_files], ignore_index=True)

            # 3. match samples
            _push(job_id, {'type': 'info', 'message': f'Matching {len(df)} samples to Crucible project…'})
            samples = client.samples.list(project_id=project_id)
            by_name = {s['sample_name']: s for s in samples}
            df['sample_id'] = df['sample_name'].map(lambda n: by_name.get(n, {}).get('unique_id'))
            unmatched = df[df['sample_id'].isna()]['sample_name'].tolist()

            # 4. batch dataset
            _push(job_id, {'type': 'info', 'message': 'Creating batch dataset…'})
            if DRY_RUN:
                time.sleep(0.5)
                batch_id = existing_id or f'dry-run-batch-{uuid.uuid4().hex[:8]}'
            else:
                client.get_or_add_instrument('ALS-BL12012', 'ALS-Building6',
                                             instrument_owner='esbarnard@lbl.gov')
                batch_result = client.datasets.create_from_files(
                    Dataset(
                        unique_id=existing_id,
                        dataset_name=dataset_name,
                        instrument_name='ALS-BL12012',
                        measurement='automated_RGA_TEY_batch_run',
                        project_id=project_id,
                    ),
                    files_to_upload=pos_files,
                    wait_for_ingestion_response=False,
                )
                batch_id = batch_result['created_record']['unique_id']
            _push(job_id, {'type': 'batch', 'dataset_id': batch_id, 'dataset_name': dataset_name,
                           'project_id': project_id, 'n_samples': len(df), 'dry_run': DRY_RUN})

            # 5. per-sample child datasets
            rows = list(df.iterrows())
            children = []

            def _upload_sample(row):
                sample_name = row['sample_name']
                spot = row['sample spot']
                sample_id = row.get('sample_id')

                txt_files = glob.glob(os.path.join(tmpdir, f'{sample_name}_*.txt'))
                # also include png thumbnails if present
                png_files = glob.glob(os.path.join(tmpdir, '**', f'{sample_name}_*.png'), recursive=True)
                all_files = txt_files + png_files

                if not all_files:
                    ev = {'type': 'sample', 'spot': spot, 'sample_name': sample_name,
                          'skipped': True, 'dataset_id': None}
                    _push(job_id, ev)
                    return ev

                if DRY_RUN:
                    time.sleep(0.1)
                    sds_id = f'dry-run-{uuid.uuid4().hex[:8]}'
                else:
                    sds_result = client.datasets.create_from_files(
                        Dataset(
                            dataset_name=f'RGATEY_{dataset_name}_{spot}_{sample_name}',
                            instrument_name='ALS-BL12012',
                            measurement='automated_RGA_TEY_run',
                            project_id=project_id,
                        ),
                        files_to_upload=all_files,
                        wait_for_ingestion_response=False,
                    )
                    sds_id = sds_result['created_record']['unique_id']
                    client.datasets.link_parent_child(batch_id, sds_id)
                    if sample_id:
                        client.datasets.add_sample(sds_id, sample_id)

                ev = {'type': 'sample', 'spot': spot, 'sample_name': sample_name,
                      'skipped': False, 'dataset_id': sds_id}
                _push(job_id, ev)
                return ev

            with ThreadPoolExecutor(max_workers=4) as ex:
                futures = [ex.submit(_upload_sample, row) for _, row in rows]
                for fut in as_completed(futures):
                    children.append(fut.result())

            children.sort(key=lambda c: c['spot'])
            _push(job_id, {
                'type': 'done',
                'batch_id': batch_id,
                'dataset_name': dataset_name,
                'project_id': project_id,
                'children': children,
                'unmatched': unmatched,
                'dry_run': DRY_RUN,
            })

        except Exception as exc:
            app.logger.exception('ALS-BL12012 upload job failed')
            _push(job_id, {'type': 'error', 'message': str(exc)})
        finally:
            _jobs[job_id]['done'] = True
            # clean up temp dir after 10 min
            threading.Timer(600, lambda: shutil.rmtree(tmpdir, ignore_errors=True)).start()


def create_blueprint(auth, helpers):
    bp = Blueprint('iview_als_bl12012', __name__)
    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/upload', methods=['GET'])
    @auth.oidc_auth('orcid')
    def upload():
        user_session = UserSession(flask.session)
        orcid = user_session.userinfo['sub']
        projects = current_app.crucible_client.projects.list(orcid=orcid)
        return render_template('instrument_views/als_bl12012_upload.html', projects=projects)

    @bp.route('/upload', methods=['POST'])
    @auth.oidc_auth('orcid')
    def upload_post():
        project_id = request.form.get('project_id', '').strip()
        if not project_id or not is_user_in_project(project_id):
            abort(403)

        uploaded_files = request.files.getlist('files')
        if not uploaded_files or not any(f.filename for f in uploaded_files):
            return jsonify({'error': 'No files received.'}), 400

        first = uploaded_files[0].filename.replace('\\', '/')
        dataset_name = first.split('/')[0] if '/' in first else 'RGA_TEY_upload'

        tmpdir = tempfile.mkdtemp()
        _save_files(uploaded_files, tmpdir)

        job_id = str(uuid.uuid4())
        _jobs[job_id] = {'events': [], 'done': False, 'lock': threading.Lock()}

        app = current_app._get_current_object()
        t = threading.Thread(
            target=_run_job,
            args=(job_id, tmpdir, project_id, dataset_name, app),
            daemon=True,
        )
        t.start()
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

    return bp
