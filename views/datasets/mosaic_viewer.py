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
from datetime import datetime, timezone

from flask import (Blueprint, abort, current_app, jsonify, render_template,
                   request, send_from_directory, session, url_for)
from flask_pyoidc.user_session import UserSession

from overlays import adapter_measurements, get_adapter
from overlays.base import open_h5_cloud, open_h5_local
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

# Annotations are persisted in a single PROJECT-SHARED CHILD dataset per mosaic
# (v4) — the mosaic itself is never mutated. The child is a metadata-only dataset
# whose scientific_metadata holds the annotation blob under ANNOT_KEY. Writes are
# mediated by the admin client and merged item-wise so collaborators share one
# canvas non-destructively.
ANNOT_MEASUREMENT = 'mosaic_annotations'
ANNOT_KEY = 'viewer_annotations'


def _find_annotation_child(client, parent_dsid):
    """The single PROJECT-SHARED mosaic_annotations child of parent_dsid, or None.

    v4 makes annotations project-shared (one child per mosaic, not per-user), so
    the ORCID filter is gone — every collaborator reads/writes the same child.
    Crucible ids are time-ordered, so we deterministically adopt the OLDEST match
    as the canonical shared child. Any per-user children left by the old v3 scheme
    are simply not returned (they go inert; adopt-oldest migration, plan §7c).
    """
    try:
        children = client.datasets.list_children(
            parent_dsid, measurement=ANNOT_MEASUREMENT)
    except Exception:
        children = None
    matches = []
    for ch in children or []:
        # Lenient: skip only on a POSITIVE mismatch (a record may omit the field
        # if the endpoint already honored the measurement query filter).
        m = ch.get('measurement')
        if m is not None and m != ANNOT_MEASUREMENT:
            continue
        matches.append(ch)
    if not matches:
        return None
    return min(matches, key=lambda ch: ch.get('unique_id') or '')


def _create_annotation_child(admin_client, parent_dsid, creator_orcid, blob):
    """Create + link the PROJECT-SHARED annotation child holding the blob; return id.

    Written through the admin (service-account) client so the child's ACL can be
    granted the project access-group with write=True — Crucible authorizes
    metadata writes by access-group, and the GET ACL endpoint doesn't expose the
    create-time default, so we set it explicitly. The child inherits the parent
    mosaic's project and sample(s); the mosaic itself is never modified.
    """
    from crucible.models import Dataset

    parent = admin_client.datasets.get(parent_dsid)
    parent = parent if isinstance(parent, dict) else {}
    parent_name = parent.get('dataset_name') or parent_dsid
    project_id = parent.get('project_id')
    ds = Dataset(
        dataset_name=f'annotations_{parent_name}',
        project_id=project_id,
        measurement=ANNOT_MEASUREMENT,
        data_type=ANNOT_MEASUREMENT,
        owner_orcid=creator_orcid,
    )
    # No files_to_upload → metadata-only dataset. Blob lands in scientific_metadata.
    record = admin_client.datasets.create(
        dataset=ds, scientific_metadata={ANNOT_KEY: blob})
    child_id = record['dsid']
    admin_client.datasets.link_parent_child(parent_dsid, child_id)
    # Make the project group's write access explicit so any project member's save
    # (mediated by admin_client) is consistent with the ACL model. Admin-only call.
    if project_id:
        try:
            admin_client.datasets.add_access_group(
                child_id, project_id, read=True, write=True)
        except Exception:
            pass
    # Propagate the sample(s) so the annotation child sits in the same group as the
    # mosaic. Non-fatal — the parent/child link is what actually matters.
    try:
        for s in (admin_client.samples.list(dataset_id=parent_dsid) or []):
            sid = s.get('unique_id')
            if sid:
                admin_client.datasets.add_sample(child_id, sid)
    except Exception:
        pass
    return child_id


# ── Item-level merge (shared, non-destructive persistence) ─────────────────────
# Shared annotations must merge item-wise so two collaborators' concurrent saves
# don't clobber each other: markers/areas and overlays are keyed by `id`, and the
# copy with the newer per-item `updated` wins. A `deleted:true` tombstone is
# retained (never dropped) so a delete stays deleted even after a stale draft
# reloads. Absence of an item in the incoming blob never deletes it (the poster
# may simply not have loaded another author's item).

def _ts(s):
    """Parse an ISO-8601 timestamp to epoch seconds; 0.0 on absence/parse error."""
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(
            str(s).replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0.0


def _merge_item_lists(base_items, incoming_items):
    """Union two item lists by `id`; per-item newer `updated` wins (ties → incoming)."""
    by_id = {}
    order = []
    for src in (base_items or [], incoming_items or []):
        incoming = src is incoming_items
        for it in src:
            if not isinstance(it, dict):
                continue
            iid = it.get('id')
            key = iid if iid is not None else ('__anon__', id(it))
            prev = by_id.get(key)
            if prev is None:
                by_id[key] = it
                order.append(key)
            elif incoming and _ts(it.get('updated')) >= _ts(prev.get('updated')):
                by_id[key] = it
    return [by_id[k] for k in order]


def _merge_blobs(base, incoming):
    """Merge a posted blob into the current server blob (item-wise; §7b).

    Item lists (`annotations`, `overlays`) merge by id; all other top-level fields
    (origin, detail_overrides, …) come from whichever blob has the newer top-level
    `updated`. Returns the merged blob so the client can reconcile.
    """
    if not isinstance(base, dict):
        return incoming
    if not isinstance(incoming, dict):
        return base
    merged = dict(base)
    merged['annotations'] = _merge_item_lists(
        base.get('annotations'), incoming.get('annotations'))
    merged['overlays'] = _merge_item_lists(
        base.get('overlays'), incoming.get('overlays'))
    newer = incoming if _ts(incoming.get('updated')) >= _ts(base.get('updated')) else base
    for k in ('schema', 'version', 'dataset_id', 'origin', 'origin_user_set',
              'detail_overrides', 'updated', 'author'):
        if k in newer:
            merged[k] = newer[k]
    return merged


def _reduce_params():
    """Common overlay-reduce query params, shared by the cloud and /local routes."""
    return {
        'reduction': request.args.get('reduction'),
        'x_axis':    request.args.get('x_axis'),
        'spec_min':  request.args.get('spec_min', type=float),
        'spec_max':  request.args.get('spec_max', type=float),
    }

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


def _local_h5s():
    """Local .h5 files in test_data/ — the offline harness's overlay-source stand-ins."""
    if not os.path.isdir(_TEST_DATA_DIR):
        return []
    return sorted(f for f in os.listdir(_TEST_DATA_DIR)
                  if f.lower().endswith('.h5'))


def _local_overlay_measurement(filename):
    """Guess a local h5's measurement from its filename (offline picker only).

    Cloud datasets carry a real ``measurement``; local files don't, so match the
    filename against the registered adapter measurement types (the hyperspec test
    file is named ``…_hyperspec_picam_mcl.h5``).
    """
    low = filename.lower()
    for meas in adapter_measurements():
        if meas.lower() in low:
            return meas
    return None


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
            # Measurement types that have an overlay adapter — the "Add overlay"
            # picker shows only sample datasets whose measurement is in this set.
            overlay_measurements=adapter_measurements(),
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
            samples = client.samples.list(dataset_id=dsid)
        except Exception as e:
            return jsonify({'error': str(e)}), 502

        seen = {dsid}          # never return the currently-open mosaic
        out = []
        for sample in samples or []:
            sid = sample.get('unique_id')
            if not sid:
                continue
            for ds in client.datasets.list(sample_id=sid, include_metadata=True):
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
            samples = client.samples.list(dataset_id=dsid)
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
                members = client.datasets.list(sample_id=sid)
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

    # ── annotation persistence (project-shared child dataset) ─────────────────
    @bp.route('/<project_id>/<dsid>/annotations')
    @auth.oidc_auth('orcid')
    def get_annotations(project_id, dsid):
        """Return the PROJECT-SHARED annotation blob for this mosaic (or null).

        Response: {'annotations': <blob|null>, 'annotation_dsid': <id|null>}. Read
        through admin_client so an adopted v3 child (whose ACL predates the shared
        grant) is still readable by every project member.
        """
        if not is_user_in_project(project_id):
            abort(403)
        # Service-account client: shared-annotation reads are mediated through it
        # so an adopted v3 child (whose ACL predates the shared grant) is still
        # readable by every project member. The gate above is the auth boundary.
        admin_client = current_app.admin_client
        child = _find_annotation_child(admin_client, dsid)
        if not child:
            return jsonify({'annotations': None, 'annotation_dsid': None})
        child_id = child.get('unique_id')
        try:
            meta = admin_client.datasets.get_scientific_metadata(child_id) or {}
        except Exception as e:
            return jsonify({'error': str(e)}), 502
        return jsonify({'annotations': meta.get(ANNOT_KEY),
                        'annotation_dsid': child_id})

    @bp.route('/<project_id>/<dsid>/annotations', methods=['POST'])
    @auth.oidc_auth('orcid')
    def save_annotations(project_id, dsid):
        """Merge the posted blob into the project-shared annotation child (§7).

        Read-modify-write with item-level merge so concurrent collaborators don't
        clobber each other: markers/areas and overlays merge by id (newer wins),
        deletes are tombstoned. Writes are mediated by admin_client; the mosaic
        itself is never modified. Returns the merged blob so the client reconciles.
        Accepts both fetch() (application/json) and sendBeacon() bodies.
        """
        if not is_user_in_project(project_id):
            abort(403)
        # Writes are mediated by the service-account client (Crucible authorizes
        # metadata writes by access-group). The gate above is the auth boundary.
        admin_client = current_app.admin_client
        blob = request.get_json(force=True, silent=True)
        if not isinstance(blob, dict):
            return jsonify({'error': 'Expected a JSON annotation blob.'}), 400
        orcid = _current_orcid()
        try:
            child = _find_annotation_child(admin_client, dsid)
            if child:
                child_id = child.get('unique_id')
                current = (admin_client.datasets.get_scientific_metadata(child_id)
                           or {}).get(ANNOT_KEY)
                merged = _merge_blobs(current, blob) if current else blob
                admin_client.datasets.update_scientific_metadata(
                    child_id, {ANNOT_KEY: merged})
            else:
                merged = blob
                child_id = _create_annotation_child(
                    admin_client, dsid, orcid, merged)
        except Exception as e:
            return jsonify({'error': str(e)}), 502
        return jsonify({'annotation_dsid': child_id,
                        'annotations': merged,
                        'updated': merged.get('updated')})

    # ── correlative overlays (adapter-backed reductions) ──────────────────────
    # Other-modality datasets (starting with hyperspec Raman/PL) register onto the
    # mosaic as blended layers. The reduction is computed server-side by the
    # target's overlay adapter and returned as a small JSON scalar field — the raw
    # cube never reaches the browser.

    def _cloud_adapter(target_dsid):
        """(adapter, dataset) for a target dataset, or (None, ds) if not overlay-able."""
        try:
            ds = get_user_client().datasets.get(target_dsid)
        except Exception:
            return None, None
        meas = ds.get('measurement') if isinstance(ds, dict) else None
        return get_adapter(meas), ds

    @bp.route('/<project_id>/<dsid>/overlay/<target_dsid>/descriptor')
    @auth.oidc_auth('orcid')
    def overlay_descriptor(project_id, dsid, target_dsid):
        if not is_user_in_project(project_id):
            abort(403)
        adapter, _ = _cloud_adapter(target_dsid)
        if not adapter:
            return jsonify({'error': 'No overlay adapter for this dataset.'}), 404
        try:
            h5 = open_h5_cloud(target_dsid, get_user_client())
            return jsonify(adapter.descriptor(h5))
        except Exception as e:
            return jsonify({'error': str(e)}), 502

    @bp.route('/<project_id>/<dsid>/overlay/<target_dsid>/reduce')
    @auth.oidc_auth('orcid')
    def overlay_reduce(project_id, dsid, target_dsid):
        if not is_user_in_project(project_id):
            abort(403)
        adapter, _ = _cloud_adapter(target_dsid)
        if not adapter:
            return jsonify({'error': 'No overlay adapter for this dataset.'}), 404
        try:
            h5 = open_h5_cloud(target_dsid, get_user_client())
            return jsonify(adapter.reduce(h5, _reduce_params()))
        except Exception as e:
            return jsonify({'error': str(e)}), 502

    @bp.route('/<project_id>/<dsid>/overlay/<target_dsid>/probe')
    @auth.oidc_auth('orcid')
    def overlay_probe(project_id, dsid, target_dsid):
        if not is_user_in_project(project_id):
            abort(403)
        adapter, _ = _cloud_adapter(target_dsid)
        if not adapter:
            return jsonify({'error': 'No overlay adapter for this dataset.'}), 404
        xi = request.args.get('xi', type=int)
        yi = request.args.get('yi', type=int)
        if xi is None or yi is None:
            return jsonify({'error': 'xi and yi are required.'}), 400
        try:
            h5 = open_h5_cloud(target_dsid, get_user_client())
            pr = adapter.probe(h5, xi, yi)
            if pr is None:
                return jsonify({'error': 'Pixel out of range.'}), 404
            return jsonify(pr)
        except Exception as e:
            return jsonify({'error': str(e)}), 502

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
            overlay_measurements=adapter_measurements(),
        )

    @bp.route('/local/<string:filename>/siblings')
    @auth.oidc_auth('orcid')
    def local_siblings(filename):
        return jsonify({'siblings': _local_siblings(filename)})

    @bp.route('/local/<string:filename>/sample-datasets')
    @auth.oidc_auth('orcid')
    def local_sample_datasets(filename):
        # Offline picker: every other local TIFF stands in for a sample dataset,
        # and every local .h5 stands in for an overlay-source dataset (so the
        # "Add overlay" picker, which filters by adapter measurement, finds it).
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
        for f in _local_h5s():
            out.append({
                'dsid': f, 'project_id': None, 'dataset_name': f,
                'measurement': _local_overlay_measurement(f) or 'unknown',
                'instrument': 'local (h5)',
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
        # The sidecar is inherently shared (one file), so apply the same item-level
        # merge as the cloud tier for parity — a stale draft can't resurrect a
        # deleted item or clobber a newer edit.
        p = _local_annot_path(filename)
        current = None
        if os.path.isfile(p):
            try:
                with open(p, encoding='utf-8') as fh:
                    current = json.load(fh)
            except Exception:
                current = None
        merged = _merge_blobs(current, blob) if current else blob
        try:
            with open(p, 'w', encoding='utf-8') as fh:
                json.dump(merged, fh, indent=2)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        return jsonify({'annotation_dsid': filename, 'annotations': merged,
                        'updated': merged.get('updated')})

    # ── local overlay routes (adapter reads test_data/<file>.h5 directly) ──────
    def _local_adapter(target):
        """(adapter, abspath) for a local overlay target, or (None, None)."""
        path = os.path.join(_TEST_DATA_DIR, target)
        if not os.path.isfile(path):
            return None, None
        return get_adapter(_local_overlay_measurement(target)), path

    @bp.route('/local/<string:filename>/overlay/<path:target>/descriptor')
    @auth.oidc_auth('orcid')
    def local_overlay_descriptor(filename, target):
        adapter, path = _local_adapter(target)
        if not adapter:
            return jsonify({'error': 'No overlay adapter for this file.'}), 404
        try:
            return jsonify(adapter.descriptor(open_h5_local(path)))
        except Exception as e:
            return jsonify({'error': str(e)}), 502

    @bp.route('/local/<string:filename>/overlay/<path:target>/reduce')
    @auth.oidc_auth('orcid')
    def local_overlay_reduce(filename, target):
        adapter, path = _local_adapter(target)
        if not adapter:
            return jsonify({'error': 'No overlay adapter for this file.'}), 404
        try:
            return jsonify(adapter.reduce(open_h5_local(path), _reduce_params()))
        except Exception as e:
            return jsonify({'error': str(e)}), 502

    @bp.route('/local/<string:filename>/overlay/<path:target>/probe')
    @auth.oidc_auth('orcid')
    def local_overlay_probe(filename, target):
        adapter, path = _local_adapter(target)
        if not adapter:
            return jsonify({'error': 'No overlay adapter for this file.'}), 404
        xi = request.args.get('xi', type=int)
        yi = request.args.get('yi', type=int)
        if xi is None or yi is None:
            return jsonify({'error': 'xi and yi are required.'}), 400
        try:
            pr = adapter.probe(open_h5_local(path), xi, yi)
            if pr is None:
                return jsonify({'error': 'Pixel out of range.'}), 404
            return jsonify(pr)
        except Exception as e:
            return jsonify({'error': str(e)}), 502

    return bp
