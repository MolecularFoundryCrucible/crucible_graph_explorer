import io
import math
import os

import h5py
import numpy as np
import requests
from flask import Blueprint, abort, current_app, jsonify, render_template

from utils.auth import get_user_client

MEASUREMENT_TYPES = ['pollux_oospec_multipos_line_scan']
URL_PREFIX = '/dataset-view/pollux-oospec'
LABEL = 'Spectra Plot'


def _h5str(val):
    """Decode h5py string datasets which may be bytes or str depending on file version."""
    return val.decode() if isinstance(val, bytes) else str(val)


def _safe_1d(arr):
    return [None if not math.isfinite(v) else v for v in arr.tolist()]


def _safe_2d(arr):
    return [[None if not math.isfinite(v) else v for v in row] for row in arr.tolist()]


def _open_h5(content_bytes):
    return h5py.File(io.BytesIO(content_bytes), 'r')


def _get_refs(meas, all_positions, new_format):
    """Return (dark_1d, safe_denom_1d, reference_indices) for the new format,
    or (None, None, set()) for the old format."""
    if not new_format:
        return None, None, set()
    settings_attrs = meas['settings'].attrs
    dark_idx  = int(settings_attrs.get('dark_idx',  0))
    blank_idx = int(settings_attrs.get('blank_idx', 1))
    dark  = np.mean(all_positions[dark_idx][1]['spectral_data'][:],  axis=0)
    blank = np.mean(all_positions[blank_idx][1]['spectral_data'][:], axis=0)
    safe_denom = np.where(np.abs(blank - dark) > 1e-6, blank - dark, np.nan)
    return dark, safe_denom, {dark_idx, blank_idx}


def _position_arrays(grp, dark, safe_denom, new_format):
    """Return (raw, dark_1d, safe_denom) for one position group."""
    if new_format:
        raw = grp['spectral_data'][:]
    else:
        raw        = grp['raw_intensities'][:]
        dark_arr   = grp['dark_intensities'][:]
        blank_arr  = grp['blank_intensities'][:]
        dark       = dark_arr
        safe_denom = np.where(np.abs(blank_arr - dark_arr) > 1e-6, blank_arr - dark_arr, np.nan)
    return raw, dark, safe_denom


def _position_meta(grp, pos_name, new_format):
    if new_format:
        return {
            'pos_name':    pos_name,
            'sample_name': _h5str(grp['sample_name'][()]),
            'x_center':    float(grp['x_center'][()]),
            'y_center':    float(grp['y_center'][()]),
        }
    attrs = dict(grp.attrs)
    return {
        'pos_name':    pos_name,
        'sample_name': str(attrs.get('sample_name', pos_name)),
        'x_center':    float(attrs.get('x_center', 0)),
        'y_center':    float(attrs.get('y_center', 0)),
    }


def _parse_h5_overview(content_bytes):
    """Return wavelengths + per-position metadata and mean spectra only.
    Individual line-scan spectra are omitted — fetch via /data/<pos_name>.
    """
    with _open_h5(content_bytes) as f:
        meas = f['measurement/pollux_oospec_multipos_line_scan']
        wavelengths = meas['wavelengths'][:].tolist()
        all_positions = sorted(meas['positions'].items())
        new_format = 'spectral_data' in all_positions[0][1]
        dark, safe_denom, ref_indices = _get_refs(meas, all_positions, new_format)

        positions_out = []
        for i, (pos_name, grp) in enumerate(all_positions):
            if i in ref_indices:
                continue
            raw, d, sd = _position_arrays(grp, dark, safe_denom, new_format)
            refl = (raw - d) / sd
            meta = _position_meta(grp, pos_name, new_format)
            meta.update({
                'mean_raw':            np.nanmean(raw, axis=0).tolist(),
                'mean_dark_corrected': np.nanmean(raw - d, axis=0).tolist(),
                'mean_reflectance':    _safe_1d(np.nanmean(refl, axis=0)),
            })
            positions_out.append(meta)

    return {'wavelengths': wavelengths, 'positions': positions_out}


def _parse_h5_position(content_bytes, pos_name):
    """Return all individual line-scan spectra for one named position."""
    with _open_h5(content_bytes) as f:
        meas = f['measurement/pollux_oospec_multipos_line_scan']
        all_positions = sorted(meas['positions'].items())
        new_format = 'spectral_data' in all_positions[0][1]
        dark, safe_denom, _ = _get_refs(meas, all_positions, new_format)

        grp = meas['positions'][pos_name]
        raw, d, sd = _position_arrays(grp, dark, safe_denom, new_format)
        refl = (raw - d) / sd

    return {
        'all_raw':            raw.tolist(),
        'all_dark_corrected': (raw - d).tolist(),
        'all_reflectance':    _safe_2d(refl),
    }


def _fetch_h5_bytes(dsid):
    """Fetch the first .h5 associated file for the dataset and return its bytes."""
    ds = get_user_client().datasets.get(dsid)
    associated_files = get_user_client().datasets.get_associated_files(dsid)
    try:
        download_links = get_user_client().datasets.get_download_links(dsid)
    except Exception:
        download_links = {}

    h5_file = next(
        (f for f in associated_files if f['filename'].endswith('.h5')),
        None
    )
    if not h5_file:
        return None, 'No .h5 file found for this dataset.'

    url = download_links.get(h5_file['mfid'])
    if not url:
        return None, 'Download link not available for the .h5 file.'

    resp = requests.get(url, timeout=60)
    if resp.status_code != 200:
        return None, f'Failed to download .h5 file (HTTP {resp.status_code}).'

    return resp.content, None


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_pollux_oospec', __name__)

    is_user_in_project = helpers['is_user_in_project']

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds = get_user_client().datasets.get(dsid)
        return render_template('dataset_views/pollux_oospec.html',
                               project_id=project_id, ds=ds)

    @bp.route('/<project_id>/<dsid>/data')
    @auth.oidc_auth('orcid')
    def data(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        try:
            content, error = _fetch_h5_bytes(dsid)
            if error:
                return jsonify({'error': error}), 404
            return jsonify(_parse_h5_overview(content))
        except Exception as e:
            current_app.logger.exception('pollux_oospec /data failed for dsid=%s', dsid)
            return jsonify({'error': str(e)}), 500

    @bp.route('/<project_id>/<dsid>/data/<pos_name>')
    @auth.oidc_auth('orcid')
    def data_position(project_id, dsid, pos_name):
        if not is_user_in_project(project_id):
            abort(403)
        try:
            content, error = _fetch_h5_bytes(dsid)
            if error:
                return jsonify({'error': error}), 404
            return jsonify(_parse_h5_position(content, pos_name))
        except Exception as e:
            current_app.logger.exception(
                'pollux_oospec /data/%s failed for dsid=%s', pos_name, dsid)
            return jsonify({'error': str(e)}), 500

    return bp
