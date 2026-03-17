import os
from datetime import datetime

import numpy as np
import requests
from flask import Blueprint, render_template, abort, current_app, jsonify

MEASUREMENT_TYPES = ['automated_RGA_TEY_run']
URL_PREFIX = '/dataset-view/rga-tey-run-plots'
LABEL = 'RGA/TEY Plots'


def create_blueprint(auth, helpers):
    bp = Blueprint('dview_rga_tey_run_plots', __name__)

    is_user_in_project = helpers['is_user_in_project']

    def _get_gcs_url(ds, associated_files, download_links, name_fragment):
        """Return the download URL for the first .txt file whose basename contains
        name_fragment *and* that actually has a download link."""
        for f in associated_files:
            basename = os.path.basename(f['filename'])
            if name_fragment in basename and basename.endswith('.txt'):
                url = download_links.get(f"{ds['unique_id']}/{basename}")
                if url:
                    return url
        return None

    def _fetch_context(dsid):
        ds = current_app.crucible_client.get_dataset(dsid)
        associated_files = current_app.crucible_client.get_associated_files(dsid)
        try:
            download_links = current_app.crucible_client.get_dataset_download_links(dsid)
        except Exception:
            download_links = {}
        return ds, associated_files, download_links

    @bp.route('/<project_id>/<dsid>')
    @auth.oidc_auth('orcid')
    def view(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)

        ds, associated_files, download_links = _fetch_context(dsid)
        tey_found = bool(_get_gcs_url(ds, associated_files, download_links, 'TEY'))
        rga_found = bool(_get_gcs_url(ds, associated_files, download_links, 'RGA_histogram'))

        return render_template(
            'dataset_views/rga_tey_run_plots.html',
            project_id=project_id,
            ds=ds,
            tey_found=tey_found,
            rga_found=rga_found,
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

    @bp.route('/<project_id>/<dsid>/tey-data')
    @auth.oidc_auth('orcid')
    def tey_data(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        return jsonify(_parse_tey(_fetch_text(dsid, 'TEY')))

    @bp.route('/<project_id>/<dsid>/rga-data')
    @auth.oidc_auth('orcid')
    def rga_data(project_id, dsid):
        if not is_user_in_project(project_id):
            abort(403)
        ds, associated_files, download_links = _fetch_context(dsid)

        rga_url = _get_gcs_url(ds, associated_files, download_links, 'RGA_histogram')
        if not rga_url:
            abort(404)
        rga_text = requests.get(rga_url, timeout=30).text

        shutter_spans = None
        tey_url = _get_gcs_url(ds, associated_files, download_links, 'TEY')
        if tey_url:
            try:
                tey_text = requests.get(tey_url, timeout=30).text
                shutter_spans = _parse_tey(tey_text)['shutter_spans']
            except Exception:
                pass

        return jsonify(_parse_rga(rga_text, shutter_spans))

    return bp
