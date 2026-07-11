import logging
import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import flask
import requests
from flask import Blueprint, abort, jsonify, render_template, request
from flask_pyoidc.user_session import UserSession

from utils.auth import get_user_client
from utils.cache import get_project, get_user_name, get_user_projects
from utils.helpers import render_markdown

logger = logging.getLogger(__name__)

# Ingestion classes selectable in the "Request ingestion" dropdown.
INGESTION_CLASSES = [
    'AFMIngestor',
    'BcfIngestor',
    'BerkeleyEmdIngestor',
    'BioGlowIngestor',
    'CanonCaptureScopeFoundryH5Ingestor',
    'CLHyperspecIngestor',
    'CLSyncRasterScanIngestor',
    'CziIngestor',
    'DigitalMicrographIngestor',
    'EmiIngestor',
    'H5Ingestor',
    'HyperspecScopeFoundryH5Ingestor',
    'HyperspecSweepScopeFoundryH5Ingestor',
    'ImageIngestor',
    'InSituPlIngestor',
    'NirvanaMultiPosLineScanIngestor',
    'PtychographyH5Ingestor',
    'QSpleemARRESEKIngestor',
    'QSpleemARRESMMIngestor',
    'QSpleemImageIngestor',
    'QSpleemSVRampIngestor',
    'RgaTeyBatchIngestor',
    'ScopeFoundryH5Ingestor',
    'SerIngestor',
    'SimpleTiledImageScopeFoundryH5Ingestor',
    'SingleSpecScopeFoundryH5Ingestor',
    'SpinbotCameraCaptureIngestor',
    'SpinbotPhotoRunIngestor',
    'SpinbotSpecLineIngestor',
    'SpinbotSpecRunIngestor',
    'ToupcamLiveScopeFoundryH5Ingestor',
    'VeloxEmdIngestor',

]


def create_blueprint(auth):
    bp = Blueprint('datasets', __name__)

    @bp.route("/<project_id>/datasets/<dsid>")
    @auth.oidc_auth('orcid')
    def dataset(project_id, dsid):
        import views.datasets as dataset_views
        client = get_user_client()
        t0 = time.perf_counter()


        orcid = UserSession(flask.session).userinfo['sub']

        def _safe(future, name, default):
            try:
                return future.result()
            except Exception as err:
                logger.warning("dataset %s: %s failed: %s", dsid, name, err)
                return default

        # Project list is served from cache — no need to put it in the thread pool
        all_projects = get_user_projects(orcid, client)
        with ThreadPoolExecutor() as ex:
            f_pc       = ex.submit(get_project, project_id, orcid, client=client)
            f_ds       = ex.submit(client.datasets.get, dsid, include_metadata=True)
            f_samples  = ex.submit(client.samples.list, dataset_id=dsid)
            f_thumbs   = ex.submit(client.datasets.get_thumbnails, dsid)
            f_files    = ex.submit(client.datasets.get_associated_files, dsid)
            f_children = ex.submit(client.datasets.list_children, dsid)
            f_parents  = ex.submit(client.datasets.list_parents, dsid)
            f_ingreqs  = ex.submit(client.datasets.get_ingestion_requests, dsid=dsid)

        # Critical: let HTTPError propagate so Flask returns a proper error page.
        # Other exceptions are logged and re-raised as 500.
        pc               = f_pc.result()
        ds               = f_ds.result()
        # Non-critical: degrade gracefully so a single failing sub-request doesn't
        # bring down the whole page.
        samples          = _safe(f_samples,  'samples',          [])
        thumbnails       = _safe(f_thumbs,   'thumbnails',       [])
        associated_files = _safe(f_files,    'files',            [])
        child_datasets   = _safe(f_children, 'list_children',    [])
        parent_datasets  = _safe(f_parents,  'list_parents',     [])
        # Normalize the ingestion-requests response to a list of dicts. The API
        # may return a bare list, a paginated wrapper, or a single record.
        _ingreqs_raw = _safe(f_ingreqs, 'ingestion_requests', [])
        if isinstance(_ingreqs_raw, dict):
            for _key in ('items', 'results', 'ingestion_requests', 'data'):
                if isinstance(_ingreqs_raw.get(_key), list):
                    _ingreqs_raw = _ingreqs_raw[_key]
                    break
            else:
                _ingreqs_raw = [_ingreqs_raw]
        ingestion_requests = [r for r in (_ingreqs_raw or []) if isinstance(r, dict)]
        # all_projects already fetched from cache above
        logger.debug("dataset parallel fetch=%.3fs", time.perf_counter() - t0)

        # Build an ordered column list from whatever keys the API returns, so the
        # table adapts to the (unmodeled) ingestion-request schema.
        ingestion_request_columns = []
        if ingestion_requests:
            preferred = ['status', 'ingestion_class', 'filename', 'file_id',
                         'time_created', 'time_submitted', 'time_completed', 'id']
            seen = []
            for r in ingestion_requests:
                for k in r.keys():
                    if k not in seen:
                        seen.append(k)
            ingestion_request_columns = ([k for k in preferred if k in seen]
                                         + [k for k in seen if k not in preferred])

        # Probe download availability for each file in parallel. A file is
        # considered downloadable unless get_download_link returns 404
        # (transient errors are treated optimistically as downloadable).
        if associated_files:
            with ThreadPoolExecutor() as ex:
                link_futures = {
                    f['mfid']: ex.submit(client.files.get_download_link, f['mfid'])
                    for f in associated_files
                }
            for f in associated_files:
                fut = link_futures.get(f['mfid'])
                try:
                    fut.result()
                    f['has_download_link'] = True
                except Exception as err:
                    status = getattr(getattr(err, 'response', None), 'status_code', None)
                    if status == 404:
                        f['has_download_link'] = False
                    else:
                        logger.warning("download_link probe failed for %s: %s", f['mfid'], err)
                        f['has_download_link'] = True

        child_dataset_thumbnails = {}
        if child_datasets:
            with ThreadPoolExecutor() as ex:
                child_thumb_futures = {
                    cd['unique_id']: ex.submit(client.datasets.get_thumbnails, cd['unique_id'])
                    for cd in child_datasets
                }
            for uid, fut in child_thumb_futures.items():
                child_dataset_thumbnails[uid] = _safe(fut, f'child_thumbnails/{uid}', [])

        markdown_html = None
        if ds.get('measurement') == 'MDNote':
            md_file = next((f for f in associated_files if f['filename'].endswith('.md')), None)
            if md_file and md_file.get('storage_path'):
                try:
                    url = client.files.get_download_link(md_file['mfid'])
                    response = requests.get(url)
                    response.raise_for_status()
                    markdown_html = render_markdown(response.text, project_id)
                except Exception as err:
                    logger.warning("Failed to render markdown for %s: %s", dsid, err)

        group_by  = request.args.get('dgb', 'measurement')
        group_val = ds.get(group_by)
        if group_val:
            ds_siblings = sorted(
                [d for d in pc['datasets'] if d.get(group_by) == group_val],
                key=lambda x: x.get('dataset_name') or ''
            )
        else:
            ds_siblings = [ds]
        ds_sibling_idx = next((i for i, d in enumerate(ds_siblings) if d['unique_id'] == dsid), 0)
        prev_sibling = ds_siblings[ds_sibling_idx - 1] if ds_sibling_idx > 0 else None
        next_sibling = ds_siblings[ds_sibling_idx + 1] if ds_sibling_idx < len(ds_siblings) - 1 else None

        owner_name = get_user_name(ds.get('owner_orcid'))

        return render_template("dataset.html",
                               project_id=project_id, pc=pc, ds=ds,
                               owner_name=owner_name,
                               child_datasets=child_datasets,
                               parent_datasets=parent_datasets,
                               samples=samples,
                               files=associated_files,
                               thumbnails=thumbnails,
                               child_dataset_thumbnails=child_dataset_thumbnails,
                               markdown_html=markdown_html,
                               custom_views=dataset_views.get_views(ds.get('measurement'), ds.get('data_type'), project_id, dsid),
                               prev_sibling=prev_sibling,
                               next_sibling=next_sibling,
                               sibling_index=ds_sibling_idx + 1,
                               sibling_count=len(ds_siblings),
                               siblings=ds_siblings,
                               sibling_label=group_val or '',
                               available_ingestors=INGESTION_CLASSES,
                               ingestion_requests=ingestion_requests,
                               ingestion_request_columns=ingestion_request_columns,
                               all_projects=all_projects)

    @bp.route("/<project_id>/datasets/<dsid>/mdnote-edit", methods=['GET', 'POST'])
    @auth.oidc_auth('orcid')
    def mdnote_edit(project_id, dsid):
        client = get_user_client()
        ds = client.datasets.get(dsid, include_metadata=True)

        if request.method == 'POST':
            md_content = request.json.get('content', '')
            associated_files = client.datasets.get_associated_files(dsid)
            md_filename = 'note.md'
            for file in associated_files:
                if file['filename'].endswith('.md'):
                    md_filename = os.path.basename(file['filename'])
                    break
            tmp_dir = tempfile.mkdtemp()
            tmp_path = os.path.join(tmp_dir, md_filename)
            try:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    f.write(md_content)
                client.datasets.add_file_to_dataset(dsid, tmp_path,
                                                    ingestion_class='ApiUploadIngestor',
                                                    wait_for_ingestion_response=True)
            finally:
                os.unlink(tmp_path)
                os.rmdir(tmp_dir)
            return jsonify({'status': 'ok'})

        associated_files = client.datasets.get_associated_files(dsid)
        md_content = ''
        for file in associated_files:
            if file['filename'].endswith('.md'):
                if file.get('storage_path'):
                    try:
                        url = client.files.get_download_link(file['mfid'])
                        response = requests.get(url)
                        response.raise_for_status()
                        md_content = response.text
                    except Exception as err:
                        logger.warning("Failed to fetch md content for %s: %s", dsid, err)
                break

        return render_template('mdnote_edit.html',
                               project_id=project_id, ds=ds, md_content=md_content)

    @bp.route("/<project_id>/api/datasets/<dsid>/upload-file", methods=['POST'])
    @auth.oidc_auth('orcid')
    def api_dataset_upload_file(project_id, dsid):
        f = request.files.get('file')
        if not f or not f.filename:
            return jsonify({'error': 'No file received'}), 400
        filename = os.path.basename(f.filename) or 'upload'
        tmpdir = tempfile.mkdtemp()
        tmpfile = os.path.join(tmpdir, filename)
        f.save(tmpfile)
        try:
            get_user_client().datasets.add_file_to_dataset(
                dsid, tmpfile,
                ingestion_class='ApiUploadIngestor',
                wait_for_ingestion_response=False,
            )
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({'ok': True, 'filename': filename})

    @bp.route("/<project_id>/api/datasets/<dsid>/request-ingestion", methods=['POST'])
    @auth.oidc_auth('orcid')
    def api_dataset_request_ingestion(project_id, dsid):
        client = get_user_client()
        body = request.get_json(silent=True) or {}
        requested_ids = body.get('file_ids')  # None/empty => all files
        ingestion_class = (body.get('ingestion_class') or '').strip()  # '' => server default
        if ingestion_class and ingestion_class not in INGESTION_CLASSES:
            return jsonify({'error': f'Unknown ingestion class: {ingestion_class}'}), 400

        associated_files = client.datasets.get_associated_files(dsid)
        by_id = {f['mfid']: f for f in associated_files}
        if requested_ids:
            targets = [by_id[fid] for fid in requested_ids if fid in by_id]
        else:
            targets = associated_files
        if not targets:
            return jsonify({'error': 'No files to ingest'}), 400

        results = []
        for f in targets:
            ingest_params = {'filename': f['filename'], 'file_size': f.get('size')}
            if ingestion_class:
                ingest_params['ingestion_class'] = ingestion_class
            try:
                req = client._request(
                    'post',
                    f"/datasets/{dsid}/files/{f['mfid']}/ingest",
                    params=ingest_params,
                )
                results.append({'mfid': f['mfid'], 'ok': True,
                                'request_id': (req or {}).get('id')})
            except Exception as exc:
                logger.warning("ingest request failed for %s: %s", f['mfid'], exc)
                results.append({'mfid': f['mfid'], 'ok': False, 'error': str(exc)})

        return jsonify({
            'requested': sum(1 for r in results if r['ok']),
            'total': len(results),
            'results': results,
        })

    @bp.route("/<project_id>/api/datasets/<dsid>/request-insitu-aggregation", methods=['POST'])
    @auth.oidc_auth('orcid')
    def api_dataset_request_insitu_aggregation(project_id, dsid):
        try:
            result = get_user_client().datasets.request_insitu_aggregation(dsid)
        except Exception as exc:
            logger.warning("insitu aggregation request failed for %s: %s", dsid, exc)
            return jsonify({'error': str(exc)}), 500
        return jsonify({'ok': True, 'result': result})

    @bp.route("/<project_id>/api/datasets/<dsid>/request-rga-analysis", methods=['POST'])
    @auth.oidc_auth('orcid')
    def api_dataset_request_rga_analysis(project_id, dsid):
        try:
            result = get_user_client().datasets.request_rga_analysis(dsid)
        except Exception as exc:
            logger.warning("rga analysis request failed for %s: %s", dsid, exc)
            return jsonify({'error': str(exc)}), 500
        return jsonify({'ok': True, 'result': result})

    @bp.route("/<project_id>/api/datasets/<dsid>/request-carrier-segmentation", methods=['POST'])
    @auth.oidc_auth('orcid')
    def api_dataset_request_carrier_segmentation(project_id, dsid):
        try:
            result = get_user_client().datasets.request_carrier_segmentation(dsid)
        except Exception as exc:
            logger.warning("carrier segmentation request failed for %s: %s", dsid, exc)
            return jsonify({'error': str(exc)}), 500
        return jsonify({'ok': True, 'result': result})

    @bp.route("/<project_id>/datasets/<dsid>/files/<file_id>/download_link")
    @auth.oidc_auth('orcid')
    def file_download_link(project_id, dsid, file_id):
        client = get_user_client()
        try:
            url = client.files.get_download_link(file_id)
            return jsonify({'url': url})
        except Exception as err:
            status = getattr(getattr(err, 'response', None), 'status_code', None)
            if status == 404:
                abort(404)
            logger.warning("download_link error for file %s: %s", file_id, err)
            abort(502)

    return bp
