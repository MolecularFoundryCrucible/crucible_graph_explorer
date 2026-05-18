import os
from datetime import datetime

import numpy as np
import requests
from flask import Blueprint, render_template, abort, current_app, jsonify

from utils.auth import get_user_client

MEASUREMENT_TYPES = ['automated_RGA_TEY_run']
URL_PREFIX = '/dataset-view/rga-tey-run-plots'
LABEL = 'RGA/TEY Plots'


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_rga_tey_run_plots', __name__)

    is_user_in_project = helpers['is_user_in_project']

    def _get_gcs_url(ds, associated_files, download_links, name_fragment, exclude_fragment=None):
        """Return the download URL for the first .txt file whose basename contains
        name_fragment (and optionally does not contain exclude_fragment)."""
        for f in associated_files:
            basename = os.path.basename(f['filename'])
            if name_fragment in basename and basename.endswith('.txt'):
                if exclude_fragment and exclude_fragment in basename:
                    continue
                url = download_links.get(f['mfid']) # download_links now is keyed by file MFID
                if url:
                    return url
        return None

    def _fetch_context(dsid):
        ds = get_user_client().datasets.get(dsid)
        associated_files = get_user_client().datasets.get_associated_files(dsid)
        try:
            download_links = get_user_client().datasets.get_download_links(dsid)
        except Exception:
            download_links = {}
        return ds, associated_files, download_links

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)

        ds, associated_files, download_links = _fetch_context(dsid)
        tey_found = bool(_get_gcs_url(ds, associated_files, download_links, 'TEY', exclude_fragment='TEY_normalized'))
        rga_found = bool(_get_gcs_url(ds, associated_files, download_links, 'RGA_histogram'))
        ms_t_found = bool(_get_gcs_url(ds, associated_files, download_links, 'MS_t', exclude_fragment='MS_t_averaged'))

        return render_template(
            'dataset_views/rga_tey_run_plots.html',
            project_id=project_id,
            ds=ds,
            tey_found=tey_found,
            rga_found=rga_found,
            ms_t_found=ms_t_found,
        )

    def _fetch_text(dsid, name_fragment):
        ds, associated_files, download_links = _fetch_context(dsid)
        gcs_url = _get_gcs_url(ds, associated_files, download_links, name_fragment)
        if not gcs_url:
            abort(404)
        resp = requests.get(gcs_url, timeout=30)
        resp.raise_for_status()
        return resp.text

    def _parse_tey(text):
        """Parse tab-separated TEY file. Returns dict ready for JSON."""
        lines = text.strip().split('\n')
        time, tey, shutter = [], [], []
        for line in lines[1:]:
            parts = line.split('\t')
            if len(parts) < 3:
                continue
            time.append(float(parts[0]))
            tey.append(float(parts[1]))
            shutter.append(int(float(parts[2])))

        spans = []
        span_start = None
        for i, s in enumerate(shutter):
            if s == 1 and span_start is None:
                span_start = time[i]
            elif s != 1 and span_start is not None:
                spans.append({'x0': span_start, 'x1': time[i - 1]})
                span_start = None
        if span_start is not None:
            spans.append({'x0': span_start, 'x1': time[-1]})

        return {'time': time, 'tey': tey, 'shutter_spans': spans}

    def _parse_rga(text, shutter_spans=None):
        """Parse RGA histogram file. Returns dict ready for JSON.

        If shutter_spans is provided, the mean spectrum uses only shutter-open
        rows. All rows are included in the heatmap.
        """
        lines = text.strip().split('\n')
        mass_labels = [int(h) for h in lines[1].split('\t')[1:]]

        timestamps, rows = [], []
        for line in lines[2:]:
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            ts_str = parts[0].strip()
            try:
                dt = datetime.strptime(ts_str, '%Y/%m/%d %H:%M:%S.%f')
            except ValueError:
                dt = datetime.strptime(ts_str, '%Y/%m/%d %H:%M:%S')
            timestamps.append(dt.timestamp())
            rows.append([float(v) for v in parts[1:]])

        t0 = timestamps[0]
        elapsed = [t - t0 for t in timestamps]
        raw = np.array(rows)  # (n_time, n_mass)
        z_log = np.log10(np.maximum(raw.T, 1e-13)).tolist()  # (n_mass, n_time)

        # Mean spectrum: shutter-open rows only (if spans available), else all rows
        if shutter_spans:
            open_mask = np.array([
                any(s['x0'] <= t <= s['x1'] for s in shutter_spans)
                for t in elapsed
            ])
            open_rows = raw[open_mask]
        else:
            open_rows = raw
        mean = np.mean(np.maximum(open_rows, 0), axis=0).tolist()

        return {
            'elapsed': elapsed,
            'mass_labels': mass_labels,
            'z_log': z_log,
            'mean': mean,
            'shutter_spans': shutter_spans or [],
        }

    def _parse_tey_normalized(text):
        """Parse background-subtracted, normalized TEY file (2 columns: time, normalized_tey)."""
        lines = text.strip().split('\n')
        time, tey = [], []
        for line in lines[1:]:
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            time.append(float(parts[0]))
            tey.append(float(parts[1]))
        return {'time': time, 'tey': tey}

    def _parse_ms_t(text, shutter_spans=None):
        """Parse background-subtracted MS_t file.

        Header: Time(s)  MZ1(Torr)  Std1(Torr)  MZ2(Torr)  Std2(Torr) ...
        MZ columns are at indices 1, 3, 5, ... (Std at 2, 4, 6, ...).
        Returns the same shape as _parse_rga output.
        """
        lines = text.strip().split('\n')
        headers = lines[0].split('\t')
        # Identify MZ column indices and extract mass numbers
        mz_indices = []
        mass_labels = []
        for i, h in enumerate(headers[1:], start=1):
            h = h.strip()
            if h.startswith('MZ') and '(' in h:
                try:
                    mass = int(h[2:h.index('(')])
                    mz_indices.append(i)
                    mass_labels.append(mass)
                except ValueError:
                    pass

        elapsed, rows = [], []
        for line in lines[1:]:
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            elapsed.append(float(parts[0]))
            rows.append([float(parts[j]) if j < len(parts) else 0.0 for j in mz_indices])

        raw = np.array(rows)  # (n_time, n_mass)
        z_log = np.log10(np.maximum(raw.T, 1e-13)).tolist()  # (n_mass, n_time)

        if shutter_spans:
            open_mask = np.array([
                any(s['x0'] <= t <= s['x1'] for s in shutter_spans)
                for t in elapsed
            ])
            open_rows = raw[open_mask] if open_mask.any() else raw
        else:
            open_rows = raw
        mean = np.mean(np.maximum(open_rows, 0), axis=0).tolist()

        return {
            'elapsed': elapsed,
            'mass_labels': mass_labels,
            'z_log': z_log,
            'mean': mean,
            'shutter_spans': shutter_spans or [],
            'corrected': True,
        }

    @bp.route('/<project_id>/<dsid>/tey-data')
    @auth.oidc_auth('orcid')
    def tey_data(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds, associated_files, download_links = _fetch_context(dsid)

        raw_url = _get_gcs_url(ds, associated_files, download_links, 'TEY', exclude_fragment='TEY_normalized')
        if not raw_url:
            abort(404)
        raw_text = requests.get(raw_url, timeout=30).text
        result = _parse_tey(raw_text)

        norm_url = _get_gcs_url(ds, associated_files, download_links, 'TEY_normalized', exclude_fragment='TEY_normalized_averaged')
        if norm_url:
            try:
                norm_text = requests.get(norm_url, timeout=30).text
                norm = _parse_tey_normalized(norm_text)
                result['normalized_time'] = norm['time']
                result['normalized_tey'] = norm['tey']
            except Exception:
                pass

        return jsonify(result)

    @bp.route('/<project_id>/<dsid>/rga-data')
    @auth.oidc_auth('orcid')
    def rga_data(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds, associated_files, download_links = _fetch_context(dsid)

        shutter_spans = None
        tey_url = _get_gcs_url(ds, associated_files, download_links, 'TEY', exclude_fragment='TEY_normalized')
        if tey_url:
            try:
                tey_text = requests.get(tey_url, timeout=30).text
                shutter_spans = _parse_tey(tey_text)['shutter_spans']
            except Exception:
                pass

        ms_t_url = _get_gcs_url(ds, associated_files, download_links, 'MS_t', exclude_fragment='MS_t_averaged')
        if ms_t_url:
            try:
                ms_t_text = requests.get(ms_t_url, timeout=30).text
                return jsonify(_parse_ms_t(ms_t_text, shutter_spans))
            except Exception:
                pass

        rga_url = _get_gcs_url(ds, associated_files, download_links, 'RGA_histogram')
        if not rga_url:
            abort(404)
        rga_text = requests.get(rga_url, timeout=30).text
        return jsonify(_parse_rga(rga_text, shutter_spans))

    return bp
