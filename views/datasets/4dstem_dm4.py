import os

import numpy as np
from cachetools import TTLCache
from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request
from werkzeug.exceptions import NotFound

from utils.auth import get_user_client

MEASUREMENT_TYPES = ['4D_STEM', 'TEM NANOPROBE']
URL_PREFIX = '/dataset-view/4dstem-dm4'
LABEL = '4D-STEM Viewer'

_DOWNLOAD_DIR = os.environ.get('CRUCIBLE_DOWNLOAD_DIR', 'crucible-downloads')

# dsid → dict with 'f' (fileDM), 'mm' (memmap), 'vbf', shape info
# Evicted after 1 h or when more than 16 datasets are held simultaneously.
_dm4_cache: TTLCache = TTLCache(maxsize=16, ttl=3600)


def _get_dm4(dsid, crucible_client):
    """Return a cached entry for dsid, downloading the DM4 on first access.

    Mirrors the pattern in hyperspec_picam_mcl.py: files live under
    {CRUCIBLE_DOWNLOAD_DIR}/{dsid}/{basename}.  If already on disk (e.g. from a
    previous run or another worker) the download is skipped.
    """
    if dsid in _dm4_cache:
        return _dm4_cache[dsid]

    dsid_dir = os.path.join(_DOWNLOAD_DIR, dsid)

    # Fast path: file already on disk
    if os.path.isdir(dsid_dir):
        existing = [f for f in os.listdir(dsid_dir) if f.lower().endswith('.dm4')]
        if existing:
            local_path = os.path.join(dsid_dir, existing[0])
            return _open_dm4(dsid, local_path)

    # Slow path: ask API for filename then download
    associated_files = crucible_client.datasets.list_files(dsid)
    dm4_file = next(
        (f for f in associated_files if f['filename'].lower().endswith('.dm4')), None
    )
    if not dm4_file:
        abort(404)

    filename = os.path.basename(dm4_file['filename'])
    crucible_client.datasets.download(dsid, file_name=f'{dsid}/{filename}',
                                      output_dir=_DOWNLOAD_DIR)
    local_path = os.path.join(dsid_dir, filename)
    return _open_dm4(dsid, local_path)


def _open_dm4(dsid, local_path):
    """Parse header, build memmap and VBF, store in cache, return entry."""
    import ncempy.io.dm as dm_io
    f = dm_io.fileDM(local_path, on_memory=False)
    f.parseHeader()
    mm = f.getMemmap(0)  # shape: (det_rows, det_cols, scan_rows, scan_cols)

    if mm.ndim != 4:
        abort(400)  # not a 4D dataset

    det_rows, det_cols, scan_rows, scan_cols = (int(s) for s in mm.shape)

    # Extract per-dimension scale/unit/origin from the DM4 header.
    # ncempy stores them flat across all objects; reverse to match C-order.
    ii = 1 if f.numObjects > 1 else 0
    jj = sum(f.dataShape[0:ii])
    n  = f.dataShape[ii]
    scales  = list(f.scale[jj:jj + n])[::-1]   # [det_row, det_col, scan_row, scan_col]
    units   = list(f.scaleUnit[jj:jj + n])[::-1]
    origins = list(f.origin[jj:jj + n])[::-1]

    def _axis(size, scale, origin):
        return [float((i - origin) * scale) for i in range(size)]

    scan_y_axis = _axis(scan_rows, scales[2], origins[2])
    scan_x_axis = _axis(scan_cols, scales[3], origins[3])
    det_y_axis  = _axis(det_rows,  scales[0], origins[0])
    det_x_axis  = _axis(det_cols,  scales[1], origins[1])

    scan_unit = units[2] or 'px'
    det_unit  = units[0] or 'px'

    # Virtual bright-field: sum over all detector pixels (computed once, cached)
    vbf = mm.sum(axis=(0, 1)).astype(np.float32)

    _dm4_cache[dsid] = {
        'f': f, 'mm': mm, 'vbf': vbf,
        'scan_rows': scan_rows, 'scan_cols': scan_cols,
        'det_rows':  det_rows,  'det_cols':  det_cols,
        'scan_y_axis': scan_y_axis, 'scan_x_axis': scan_x_axis, 'scan_unit': scan_unit,
        'det_y_axis':  det_y_axis,  'det_x_axis':  det_x_axis,  'det_unit':  det_unit,
    }
    return _dm4_cache[dsid]


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_4dstem_dm4', __name__)
    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds = get_user_client().datasets.get(dsid)
        try:
            entry = _get_dm4(dsid, get_user_client())
        except NotFound:
            return render_template(
                'dataset_views/4dstem_dm4.html',
                project_id=project_id, ds=ds,
                error='No DM4 file is associated with this dataset.',
            )
        return render_template(
            'dataset_views/4dstem_dm4.html',
            project_id=project_id,
            ds=ds,
            scan_rows=entry['scan_rows'],
            scan_cols=entry['scan_cols'],
            det_rows=entry['det_rows'],
            det_cols=entry['det_cols'],
            det_y_axis=entry['det_y_axis'],
            det_x_axis=entry['det_x_axis'],
            det_unit=entry['det_unit'],
        )

    @bp.route('/<project_id>/<dsid>/map')
    @auth.oidc_auth('orcid')
    def map_data(project_id, dsid):
        """Return the virtual bright-field spatial map (sum over all detector pixels)."""
        if not is_user_in_project(project_id):
            abort(403)
        entry = _get_dm4(dsid, get_user_client())
        return jsonify({
            'scan_rows':   entry['scan_rows'],
            'scan_cols':   entry['scan_cols'],
            'det_rows':    entry['det_rows'],
            'det_cols':    entry['det_cols'],
            'map_data':    entry['vbf'].tolist(),
            'scan_y_axis': entry['scan_y_axis'],
            'scan_x_axis': entry['scan_x_axis'],
            'scan_unit':   entry['scan_unit'],
        })

    @bp.route('/<project_id>/<dsid>/diffraction')
    @auth.oidc_auth('orcid')
    def diffraction(project_id, dsid):
        """Return the diffraction pattern at a given probe position as raw float32 bytes.

        Query params:
            row – scan row index (required)
            col – scan column index (required)
        """
        if not is_user_in_project(project_id):
            abort(403)

        row = request.args.get('row', type=int)
        col = request.args.get('col', type=int)
        if row is None or col is None:
            abort(400)

        entry = _get_dm4(dsid, get_user_client())
        if not (0 <= row < entry['scan_rows'] and 0 <= col < entry['scan_cols']):
            abort(400)

        dp = entry['mm'][:, :, row, col]  # shape (det_rows, det_cols)
        return Response(dp.astype(np.float32).tobytes(), mimetype='application/octet-stream')

    return bp
