"""
Deep-zoom mosaic viewer for stitched_mosaic datasets (pyramidal OME-TIFF).

Method A (client-side): the browser reads the tiled, factor-2 pyramid OME-TIFF
directly via HTTP Range with geotiff.js and renders it in OpenSeadragon, so the
Flask server stays out of the image-data path. This module therefore only:
  - serves the viewer page, and
  - hands the browser a URL to the OME-TIFF that supports Range requests.

Production path: a short-lived signed URL to the file in GCS (browser → GCS
directly; requires bucket CORS for the serving origin — see cors.json).

Local dev path: drop an ``.ome.tif`` into ``test_data/`` and open
``/dataset-view/mosaic/local/<filename>``. The file is served same-origin (with
Range support), so the whole viewer can be tested on your machine with no GCS or
CORS setup.
"""

import json
import os

from flask import (Blueprint, abort, jsonify, render_template, request,
                   send_from_directory, session, url_for)
from flask_pyoidc.user_session import UserSession

from utils.auth import get_user_client


def _current_orcid():
    """ORCID of the logged-in user (OIDC 'sub'), or None if unavailable."""
    try:
        return UserSession(session).userinfo.get('sub')
    except Exception:
        return None

MEASUREMENT_TYPES = ['stitched_mosaic']
URL_PREFIX = '/dataset-view/mosaic'
LABEL = 'Mosaic Viewer'

# Annotations are persisted in a per-(mosaic, user) CHILD dataset — the mosaic
# itself is never mutated. The child is a metadata-only dataset whose
# scientific_metadata holds the annotation blob under ANNOT_KEY.
ANNOT_MEASUREMENT = 'mosaic_annotations'
ANNOT_KEY = 'viewer_annotations'


def _find_annotation_child(client, parent_dsid, orcid):
    """The logged-in user's mosaic_annotations child of parent_dsid, or None.

    There should be at most one such child per (mosaic, user), but a past
    find-or-create race could have left duplicates behind (two beacons/POSTs
    creating in parallel before either committed). To stay stable we always
    return the SAME one — the oldest. Crucible ids are time-ordered, so the
    lexicographically smallest id is the first created; picking it deterministically
    makes the GET (load) and every POST (save) converge on a single canonical child
    instead of bouncing between duplicates.
    """
    try:
        children = client.datasets.list_children(
            parent_dsid, measurement=ANNOT_MEASUREMENT, owner_orcid=orcid)
    except Exception:
        children = None
    matches = []
    for ch in children or []:
        # Lenient: skip only on a POSITIVE mismatch. If the children endpoint
        # honored the measurement/owner_orcid query filters, the list is already
        # correct and a record may omit those fields — rejecting on absence would
        # miss the existing child and create a duplicate on every save.
        m = ch.get('measurement')
        if m is not None and m != ANNOT_MEASUREMENT:
            continue
        owner = ch.get('owner_orcid')
        if orcid and owner is not None and owner != orcid:
            continue
        matches.append(ch)
    if not matches:
        return None
    return min(matches, key=lambda ch: ch.get('unique_id') or '')


def _create_annotation_child(client, parent_dsid, orcid, blob):
    """Create + link a metadata-only annotation child holding the blob; return id.

    The child inherits the parent mosaic's project and sample(s) so it groups with
    it. The mosaic (parent) is never modified — only a new child is created and
    linked via link_parent_child.
    """
    from crucible.models import Dataset

    parent = client.datasets.get(parent_dsid)
    parent = parent if isinstance(parent, dict) else {}
    parent_name = parent.get('dataset_name') or parent_dsid
    orcid_short = (orcid or 'anon').split('-')[-1][:8]
    ds = Dataset(
        dataset_name=f'annotations_{parent_name}_{orcid_short}',
        project_id=parent.get('project_id'),
        measurement=ANNOT_MEASUREMENT,
        data_type=ANNOT_MEASUREMENT,
    )
    # The metadata-only dataset stores its blob in scientific_metadata.
    record = client.datasets.create(dataset=ds, scientific_metadata={ANNOT_KEY: blob})
    child_id = record['dataset_mfid']
    client.datasets.link_parent_child(parent_dsid, child_id)
    # Propagate the sample(s) so the annotation child sits in the same group as the
    # mosaic. Non-fatal — the parent/child link is what actually matters.
    try:
        for s in (client.samples.list(dataset_mfid=parent_dsid) or []):
            sid = s.get('unique_id')
            if sid:
                client.datasets.add_sample(child_id, sid)
    except Exception:
        pass
    return child_id

# Local .ome.tif files for the /local dev route (not used in production).
_TEST_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'test_data')

def _find_mosaic_file(associated_files):
    """Return the mosaic TIFF file record to view, or None.

    Prefers our pipeline's plain IFD-pyramid ``.tif`` over a legacy SubIFD
    ``.ome.tif`` when both are present on a re-stitched dataset: browser
    geotiff.js can read the IFD pyramid but not the SubIFD one. Falls back to any
    TIFF (so a not-yet-re-stitched legacy child still resolves to *something*).
    """
    tifs = [f for f in associated_files
            if f['filename'].lower().endswith(('.tif', '.tiff'))]
    if not tifs:
        return None
    plain = [f for f in tifs
             if not f['filename'].lower().endswith(('.ome.tif', '.ome.tiff'))]
    return (plain or tifs)[0]


# ── Cross-microscope dataset links (marker/area annotations) ───────────────────
# A marker or area can link to OTHER Crucible datasets — e.g. an SEM, Raman, or
# PL scan of the same physical sample taken on a different instrument. The link
# picker (sample-datasets route) lists every dataset on this mosaic's Crucible
# sample(s); the stored link keeps only the dataset id (source of truth) plus
# cached display fields so the marker panel renders instantly and offline.

def _dataset_link_payload(ds, sample_name=None):
    """Shape a dataset record for the link picker / a stored link's display.

    Includes a page_url to the standard dataset page (which itself surfaces that
    dataset's own custom viewers, so a linked mosaic gets its Mosaic Viewer link
    for free). page_url is None when the project isn't known.
    """
    dsid = ds.get('unique_id')
    proj = ds.get('project_id')
    payload = {
        'dsid': dsid,
        'project_id': proj,
        'dataset_name': ds.get('dataset_name'),
        'measurement': ds.get('measurement'),
        'instrument': ds.get('instrument_name'),
        'timestamp': ds.get('timestamp'),
        'sample_name': sample_name,
        'page_url': None,
    }
    if dsid and proj:
        try:
            payload['page_url'] = url_for(
                'datasets.dataset', project_id=proj, dsid=dsid)
        except Exception:
            pass
    return payload


# ── Offline test harness (test_data/) ─────────────────────────────────────────
# The /local routes mirror the cloud ones so the FULL multi-magnification flow
# (detail regions + activation) can be tested with no GCS/CORS/login. Drop the
# mosaic TIFFs into test_data/ and, next to each, a `<file>.json` sidecar holding
# that dataset's scientific_metadata (stage_origin_mm, mm_per_px, y_axis_up,
# magnification, stage_bbox_mm). download_test_mosaics.py writes both for you.
# All TIFFs present are treated as ONE sample group.

def _local_meta(filename):
    """Geometry sidecar for a local file (<filename>.json), or {} if absent/bad."""
    p = os.path.join(_TEST_DATA_DIR, filename + '.json')
    if os.path.isfile(p):
        try:
            with open(p, encoding='utf-8') as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def _local_tifs():
    if not os.path.isdir(_TEST_DATA_DIR):
        return []
    return sorted(f for f in os.listdir(_TEST_DATA_DIR)
                  if f.lower().endswith(('.tif', '.tiff')))


def _local_siblings(exclude):
    """Every other local mosaic TIFF (+ its sidecar geometry) — the sample set."""
    out = []
    for f in _local_tifs():
        if f == exclude:
            continue
        m = _local_meta(f)
        out.append({
            'dsid': f, 'dataset_name': f,
            'magnification': m.get('magnification'),
            'stage_bbox_mm': m.get('stage_bbox_mm'),
            'stage_origin_mm': m.get('stage_origin_mm'),
            'mm_per_px': m.get('mm_per_px'),
            'y_axis_up': m.get('y_axis_up'),
            'coord_frame': m.get('coord_frame'),
        })
    return out


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_mosaic', __name__)
    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds = get_user_client().datasets.get(dsid, include_metadata=True)
        # This mosaic's own pixel<->stage geometry anchors the detail-region
        # projection (siblings' stage bbox → this map's pixels). May be absent on
        # mosaics stitched before the geometry metadata existed.
        geometry = (ds.get('scientific_metadata') or {}) if isinstance(ds, dict) else {}
        return render_template(
            'dataset_views/mosaic_viewer.html',
            project_id=project_id, ds=ds,
            base_url=f'{request.script_root}{URL_PREFIX}/{project_id}/{dsid}',
            # None → the page fetches a fresh signed URL from the /file-url route.
            file_url=None,
            geometry=geometry,
            viewer_orcid=_current_orcid(),
            has_server=True,   # durable tier = Crucible child dataset
        )

    def _signed_mosaic_url(client, dsid):
        """(payload, status) for a fresh signed URL to a dataset's mosaic TIFF."""
        # nano-crucible 3.x: list_files(dsid) is the by-dataset file lookup and
        # returns dicts with mfid/filename (get_associated_files was the 2.1.2
        # workaround and is removed in 3.x).
        mosaic = _find_mosaic_file(client.datasets.list_files(dsid))
        if not mosaic:
            return {'error': 'No OME-TIFF file found for this dataset.'}, 404
        try:
            url = client.files.get_download_link(mosaic['mfid'])
        except Exception as e:
            return {'error': str(e)}, 502
        return {'url': url, 'filename': os.path.basename(mosaic['filename'])}, 200

    @bp.route('/<project_id>/<dsid>/file-url')
    @auth.oidc_auth('orcid')
    def file_url(project_id, dsid):
        """Return a fresh signed URL to the mosaic OME-TIFF for browser Range fetches."""
        if not is_user_in_project(project_id):
            abort(403)
        payload, status = _signed_mosaic_url(get_user_client(), dsid)
        return jsonify(payload), status

    @bp.route('/<project_id>/<dsid>/sibling-url/<target_dsid>')
    @auth.oidc_auth('orcid')
    def sibling_url(project_id, dsid, target_dsid):
        """Signed URL for another mosaic (a detail region) to swap in on activate.

        Same project gate as the base view; the target is a stitched_mosaic of the
        same sample (same inherited project), so the project membership check
        covers it. `dsid` is unused but keeps the URL shape uniform with the view.
        """
        if not is_user_in_project(project_id):
            abort(403)
        payload, status = _signed_mosaic_url(get_user_client(), target_dsid)
        return jsonify(payload), status

    @bp.route('/<project_id>/<dsid>/siblings')
    @auth.oidc_auth('orcid')
    def siblings(project_id, dsid):
        """Return the other stitched mosaics of the same sample(s), with the
        pixel<->stage geometry needed to place them as detail regions.

        Sample-grouped multi-magnification: all mosaics of one physical sample
        link to the same Crucible sample, so we gather every `stitched_mosaic`
        dataset across this dataset's sample(s). The viewer decides which is the
        base map (lowest magnification) and draws the higher-mag ones as boxes.
        """
        if not is_user_in_project(project_id):
            abort(403)
        client = get_user_client()
        try:
            samples = client.samples.list(dataset_mfid=dsid)
        except Exception as e:
            return jsonify({'error': str(e)}), 502

        seen = {dsid}          # never return the currently-open mosaic
        out = []
        for sample in samples or []:
            sid = sample.get('unique_id')
            if not sid:
                continue
            for ds in client.datasets.list(sample_mfid=sid, include_metadata=True):
                if ds.get('measurement') != MEASUREMENT_TYPES[0]:
                    continue
                other = ds.get('unique_id')
                if not other or other in seen:
                    continue
                seen.add(other)
                meta = ds.get('scientific_metadata') or {}
                out.append({
                    'dsid': other,
                    'dataset_name': ds.get('dataset_name'),
                    'magnification': meta.get('magnification'),
                    'stage_bbox_mm': meta.get('stage_bbox_mm'),
                    'stage_origin_mm': meta.get('stage_origin_mm'),
                    'mm_per_px': meta.get('mm_per_px'),
                    'y_axis_up': meta.get('y_axis_up'),
                    'coord_frame': meta.get('coord_frame'),
                })
        return jsonify({'siblings': out})

    @bp.route('/<project_id>/<dsid>/sample-datasets')
    @auth.oidc_auth('orcid')
    def sample_datasets(project_id, dsid):
        """Every OTHER dataset on this mosaic's sample(s) — the link-picker source.

        Broadened form of `siblings`: all measurements and instruments (not just
        stitched_mosaic), so a marker can link to datasets from other microscopes
        that imaged the same physical sample. Excludes the mosaic itself and the
        internal per-user annotation children.
        """
        if not is_user_in_project(project_id):
            abort(403)
        client = get_user_client()
        try:
            samples = client.samples.list(dataset_mfid=dsid)
        except Exception as e:
            return jsonify({'error': str(e)}), 502

        seen = {dsid}          # never offer the currently-open mosaic itself
        out = []
        for sample in samples or []:
            sid = sample.get('unique_id')
            if not sid:
                continue
            sname = sample.get('sample_name')
            try:
                members = client.datasets.list(sample_mfid=sid)
            except Exception:
                continue
            for ds in members or []:
                other = ds.get('unique_id')
                if not other or other in seen:
                    continue
                if ds.get('measurement') == ANNOT_MEASUREMENT:
                    continue   # internal annotation child, not a real dataset
                seen.add(other)
                out.append(_dataset_link_payload(ds, sample_name=sname))
        return jsonify({'datasets': out})

    @bp.route('/<project_id>/<dsid>/dataset-info/<target_dsid>')
    @auth.oidc_auth('orcid')
    def dataset_info(project_id, dsid, target_dsid):
        """Resolve a pasted dataset id → display fields (the picker's paste path).

        Membership is checked against the CURRENT project; the pasted target may
        live in another project the user can still read, so a failed get() is
        surfaced as 404 rather than 403.
        """
        if not is_user_in_project(project_id):
            abort(403)
        try:
            ds = get_user_client().datasets.get(target_dsid)
        except Exception:
            return jsonify({'error': 'Dataset not found or not accessible.'}), 404
        if not isinstance(ds, dict) or not ds.get('unique_id'):
            return jsonify({'error': 'Dataset not found.'}), 404
        return jsonify({'dataset': _dataset_link_payload(ds)})

    # ── annotation persistence (per-user child dataset) ───────────────────────
    @bp.route('/<project_id>/<dsid>/annotations')
    @auth.oidc_auth('orcid')
    def get_annotations(project_id, dsid):
        """Return the current user's saved annotation blob for this mosaic (or null).

        Response: {'annotations': <blob|null>, 'annotation_dsid': <id|null>}.
        """
        if not is_user_in_project(project_id):
            abort(403)
        client = get_user_client()
        child = _find_annotation_child(client, dsid, _current_orcid())
        if not child:
            return jsonify({'annotations': None, 'annotation_dsid': None})
        child_id = child.get('unique_id')
        try:
            meta = client.datasets.get_scientific_metadata(child_id) or {}
        except Exception as e:
            return jsonify({'error': str(e)}), 502
        return jsonify({'annotations': meta.get(ANNOT_KEY),
                        'annotation_dsid': child_id})

    @bp.route('/<project_id>/<dsid>/annotations', methods=['POST'])
    @auth.oidc_auth('orcid')
    def save_annotations(project_id, dsid):
        """Find-or-create this user's annotation child and store the posted blob.

        The mosaic itself is never modified. update_scientific_metadata MERGES, so
        only the ANNOT_KEY entry is written. Accepts both fetch() (application/json)
        and navigator.sendBeacon() (force-parsed) bodies.
        """
        if not is_user_in_project(project_id):
            abort(403)
        blob = request.get_json(force=True, silent=True)
        if not isinstance(blob, dict):
            return jsonify({'error': 'Expected a JSON annotation blob.'}), 400
        client = get_user_client()
        orcid = _current_orcid()
        try:
            child = _find_annotation_child(client, dsid, orcid)
            if child:
                child_id = child.get('unique_id')
                client.datasets.update_scientific_metadata(child_id, {ANNOT_KEY: blob})
            else:
                child_id = _create_annotation_child(client, dsid, orcid, blob)
        except Exception as e:
            return jsonify({'error': str(e)}), 502
        return jsonify({'annotation_dsid': child_id,
                        'updated': blob.get('updated')})




    # ── local dev routes: test the viewer against a file in test_data/ ─────────
    @bp.route('/localfile/<path:filename>')
    @auth.oidc_auth('orcid')
    def localfile(filename):
        # conditional=True → Flask honors Range requests, which geotiff.js needs.
        return send_from_directory(_TEST_DATA_DIR, filename, conditional=True)

    def _localfile_url(filename):
        return f'{request.script_root}{URL_PREFIX}/localfile/{filename}'

    # <string:...> (no slashes) so these don't shadow /localfile/<path:...> and so
    # the sub-routes below match ahead of the bare view.
    @bp.route('/local/<string:filename>')
    @auth.oidc_auth('orcid')
    def local_view(filename):
        if not os.path.isfile(os.path.join(_TEST_DATA_DIR, filename)):
            abort(404)
        return render_template(
            'dataset_views/mosaic_viewer.html',
            # unique_id = filename so the detail-region code has an identity to key
            # activation/overrides on (mirrors CURRENT_DSID in the cloud path).
            ds={'dataset_name': filename, 'unique_id': filename},
            project_id=None,
            base_url=f'{request.script_root}{URL_PREFIX}/local/{filename}',
            # Same-origin, Range-capable URL → page uses it directly, skips /file-url.
            file_url=_localfile_url(filename),
            geometry=_local_meta(filename),   # geometry from the sidecar JSON
            viewer_orcid=_current_orcid(),
            has_server=True,   # durable tier = dev-only .annot.json sidecar
        )

    @bp.route('/local/<string:filename>/siblings')
    @auth.oidc_auth('orcid')
    def local_siblings(filename):
        return jsonify({'siblings': _local_siblings(filename)})

    @bp.route('/local/<string:filename>/sample-datasets')
    @auth.oidc_auth('orcid')
    def local_sample_datasets(filename):
        # Offline picker: every other local TIFF stands in for a sample dataset.
        out = []
        for f in _local_tifs():
            if f == filename:
                continue
            m = _local_meta(f)
            out.append({
                'dsid': f, 'project_id': None, 'dataset_name': f,
                'measurement': 'stitched_mosaic',
                'instrument': m.get('coord_frame') or 'local',
                'timestamp': None, 'sample_name': 'local', 'page_url': None,
            })
        return jsonify({'datasets': out})

    @bp.route('/local/<string:filename>/dataset-info/<path:target>')
    @auth.oidc_auth('orcid')
    def local_dataset_info(filename, target):
        if not os.path.isfile(os.path.join(_TEST_DATA_DIR, target)):
            return jsonify({'error': f'No such local file: {target}'}), 404
        return jsonify({'dataset': {
            'dsid': target, 'project_id': None, 'dataset_name': target,
            'measurement': 'stitched_mosaic', 'instrument': 'local',
            'timestamp': None, 'sample_name': 'local', 'page_url': None,
        }})

    @bp.route('/local/<string:filename>/file-url')
    @auth.oidc_auth('orcid')
    def local_file_url(filename):
        # Return-to-overview path: urlForDsid(CURRENT_DSID) hits this.
        return jsonify({'url': _localfile_url(filename), 'filename': filename})

    @bp.route('/local/<string:filename>/sibling-url/<path:target>')
    @auth.oidc_auth('orcid')
    def local_sibling_url(filename, target):
        # Activation: swap to another local TIFF (same-origin, Range-capable).
        if not os.path.isfile(os.path.join(_TEST_DATA_DIR, target)):
            return jsonify({'error': f'No such local file: {target}'}), 404
        return jsonify({'url': _localfile_url(target), 'filename': target})

    # DEV-ONLY: mirror the annotation GET/POST against a test_data sidecar so the
    # full save/load/precedence UI can be exercised offline (no GCS/auth/dataset
    # creation). Blob is stored per file as <filename>.annot.json.
    def _local_annot_path(filename):
        return os.path.join(_TEST_DATA_DIR, filename + '.annot.json')

    @bp.route('/local/<string:filename>/annotations')
    @auth.oidc_auth('orcid')
    def local_get_annotations(filename):
        p = _local_annot_path(filename)
        if os.path.isfile(p):
            try:
                with open(p, encoding='utf-8') as fh:
                    return jsonify({'annotations': json.load(fh),
                                    'annotation_dsid': filename})
            except Exception:
                pass
        return jsonify({'annotations': None, 'annotation_dsid': None})

    @bp.route('/local/<string:filename>/annotations', methods=['POST'])
    @auth.oidc_auth('orcid')
    def local_save_annotations(filename):
        blob = request.get_json(force=True, silent=True)
        if not isinstance(blob, dict):
            return jsonify({'error': 'Expected a JSON annotation blob.'}), 400
        try:
            with open(_local_annot_path(filename), 'w', encoding='utf-8') as fh:
                json.dump(blob, fh, indent=2)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        return jsonify({'annotation_dsid': filename, 'updated': blob.get('updated')})

    return bp
