import json
import time

import networkx as nx
import pandas
import plotly.express as px
import flask

from flask import Blueprint, render_template, request, jsonify
from flask_pyoidc.user_session import UserSession

from utils.auth import get_user_client

PROJECT_ID = '10k_perovskites'


def classify_fields(df):
    """Split DataFrame columns into (numeric, categorical) lists.

    A column is numeric if at least half its non-null values parse as numbers.
    """
    numeric, categorical = [], []
    for col in df.columns:
        non_null = df[col].dropna()
        parsed = pandas.to_numeric(non_null, errors='coerce')
        if len(non_null) and parsed.notna().mean() >= 0.5:
            numeric.append(col)
        else:
            categorical.append(col)
    return sorted(numeric), sorted(categorical)


_THINFILM_CACHE = {}
_THINFILM_CACHE_TTL = 300  # seconds


def load_thinfilm_frame(client):
    """Pull thin-film samples and build the metrics DataFrame, cached briefly.

    The pull (all samples + metadata) dominates request time and the data is
    identical between dropdown changes, so cache it per project with a short TTL.
    Returns (df, fields, numeric_fields, categorical_fields).
    """
    cached = _THINFILM_CACHE.get(PROJECT_ID)
    if cached and time.time() - cached['ts'] < _THINFILM_CACHE_TTL:
        return cached['df'], cached['fields'], cached['numeric'], cached['categorical']

    tfs = client.samples.list(
        project_id=PROJECT_ID,
        sample_type='thin film',
        include_metadata=True,
        limit=None,
    )
    tf_dict = {}
    for t in tfs:
        meta = t.get('scientific_metadata')
        if not meta:
            continue
        meta.update({
            'creation_time': t['creation_time'],
            'modification_time': t['modification_time'],
            'timestamp': t['timestamp'],
        })
        tf_dict[t['sample_name']] = meta

    df = pandas.DataFrame.from_dict(tf_dict, orient='index')
    df.index.name = 'sample_name'
    df = df.reset_index()

    fields = sorted(df.columns)
    numeric, categorical = classify_fields(df)
    _THINFILM_CACHE[PROJECT_ID] = {
        'ts': time.time(), 'df': df, 'fields': fields,
        'numeric': numeric, 'categorical': categorical,
    }
    return df, fields, numeric, categorical


VIEWS = [
    {'label': 'Overview',          'url': '/overview',         'icon': 'bi-bar-chart'},
    {'label': 'Thin Film Gallery', 'url': '/thinfilm-gallery', 'icon': 'bi-images'},
    {'label': 'Thin Film Metrics', 'url': '/thinfilm-metrics', 'icon': 'bi-graph-up'},
]


def create_blueprint(auth, helpers):
    bp = Blueprint(f'proj_{PROJECT_ID}', __name__)

    get_project = helpers['get_project']
    get_project_graph = helpers['get_project_graph']

    @bp.route('/overview')
    @auth.oidc_auth('orcid')
    def overview():
        orcid = UserSession(flask.session).userinfo['sub']
        pc = get_project(PROJECT_ID, orcid, include_metadata=True)
        G = get_project_graph(PROJECT_ID)

        thin_films = [s for s in pc['samples'] if s['sample_name'].startswith('TF')]
        thin_films.sort(key=lambda x: x['sample_name'])

        rows = []
        for s in thin_films:
            ancestors = [pc['samples_by_id'][sid] for sid in nx.ancestors(G, s['unique_id']) if sid in pc['samples_by_id']]
            descendants = [pc['samples_by_id'][sid] for sid in nx.descendants(G, s['unique_id']) if sid in pc['samples_by_id']]

            solid_precursors = [s for s in ancestors if s['sample_name'].startswith('SP')]
            precursor_compositions = []
            try:
                for sp in solid_precursors:
                    for ds in sp['datasets']:
                        full_ds = pc['datasets_by_id'].get(ds['unique_id'])
                        if full_ds and full_ds.get('measurement') == 'Solid Precursor synthesis':
                            if full_ds.get('scientific_metadata'):
                                precursor_compositions.append(full_ds['scientific_metadata'].get('name'))
            except Exception as err:
                print(f"Failed to get solid precursor details {s['sample_name']}: {err}")

            if len(precursor_compositions) < 2:
                precursor_compositions += [None] * (2 - len(precursor_compositions))

            sr = [ds for ds in s['datasets']
                  if pc['datasets_by_id'].get(ds['unique_id'], {}).get('measurement') == 'spin_run']
            if sr:
                sr = pc['datasets_by_id'].get(sr[0]['unique_id'])
                anneal_temp = sr['scientific_metadata'].get('heater_sv_temp', '?') if sr else '?'
            else:
                anneal_temp = '?'

            rows.append({
                'thin_film_sample_name': s['sample_name'],
                'thin_film_unique_id': s['unique_id'],
                'sp_A': precursor_compositions[0],
                'sp_B': precursor_compositions[1],
                'anneal_temp': anneal_temp,
            })

        df = pandas.DataFrame(rows)
        return render_template('proj10k_templates/overview.html', pc=pc, tfs=thin_films, df=df)

    @bp.route('/thinfilm-gallery')
    @auth.oidc_auth('orcid')
    def thinfilm_gallery():
        orcid = UserSession(flask.session).userinfo['sub']
        pc = get_project(PROJECT_ID, orcid)

        thin_films = [s for s in pc['samples'] if s['sample_name'].startswith('TF')]
        thin_films.sort(key=lambda x: x['sample_name'])

        img_dsid = {
            tf['unique_id']: next(
                (ds['unique_id'] for ds in tf['datasets']
                 if pc['datasets_by_id'].get(ds['unique_id'], {}).get('measurement') == 'sample well image'),
                None
            )
            for tf in thin_films
        }
        batch = {}
        dataset_ids = [dsid for dsid in img_dsid.values() if dsid]
        if dataset_ids:
            try:
                batch = get_user_client()._request(
                    "POST", "/datasets/first_thumbnails", json=dataset_ids
                )
            except Exception:
                pass

        tf_thumbs = []
        for tf in thin_films:
            dsid = img_dsid.get(tf['unique_id'])
            tn = dict(batch.get(dsid, {})) if dsid else {}
            tn['sample_name'] = tf['sample_name']
            tn['sample_url'] = f'/{PROJECT_ID}/samples/{tf["unique_id"]}'
            tf_thumbs.append(tn)

        return render_template('proj10k_templates/thinfilm-gallery.html',
                               tf_thumbs=tf_thumbs, project_id=PROJECT_ID)
    
    
    @bp.route('/thinfilm-metrics')
    @auth.oidc_auth('orcid')
    def view_thinfilm_metadata():
        orcid = UserSession(flask.session).userinfo['sub']
        pc = get_project(PROJECT_ID, orcid)

        # rga outgassing calc
        return render_template('proj10k_templates/thinfilm-metrics.html',
                               project_id=PROJECT_ID)


    @bp.route('/thinfilm-metrics/data')
    @auth.oidc_auth('orcid')
    def gather_thinfilm_metadata():
        # 1. PULL — one row per thin-film sample, columns = metadata fields (cached)
        df, fields, numeric_fields, categorical_fields = load_thinfilm_frame(get_user_client())

        # 2. READ CONTROLS (with safe fallbacks so first load always works)
        plot_type = request.args.get('plot_type', 'box')
        # box X must be categorical; scatter X can be any field
        x_pool    = categorical_fields if plot_type == 'box' else fields

        def pick(preferred, pool):
            return preferred if preferred in pool else (pool[0] if pool else None)

        x_col     = request.args.get('x') or pick('organic_salt_name', x_pool)
        y_col     = request.args.get('y') or pick('outgas_area', numeric_fields)
        top_n     = request.args.get('top', default=10, type=int)
        sort_by   = request.args.get('sort', 'median_desc')

        # 3. BUILD FIGURE — branch on plot type; px.* returns a Plotly figure
        fig, error = None, None
        try:
            if plot_type == 'box':
                d = df.copy()
                d[y_col] = pandas.to_numeric(d[y_col], errors='coerce')
                d = d.dropna(subset=[x_col, y_col])
                medians = d.groupby(x_col)[y_col].median()
                # selection: desc picks highest medians, asc picks lowest
                keep = list(medians.sort_values(ascending=(sort_by == 'median_asc'))
                                   .head(top_n).index)
                # display: always ascending by median, left to right
                display_order = list(medians[keep].sort_values().index)
                d = d[d[x_col].isin(keep)]
                # annotate each category with its sample count: "TF-A (n=12)"
                counts = d[x_col].value_counts()
                label = {c: f'{c} (n={counts[c]})' for c in display_order}
                d['_xlabel'] = d[x_col].map(label)
                fig = px.box(d, x='_xlabel', y=y_col,
                             category_orders={'_xlabel': [label[c] for c in display_order]},
                             labels={'_xlabel': x_col})

            elif plot_type == 'scatter':
                d = df.copy()
                d[y_col] = pandas.to_numeric(d[y_col], errors='coerce')
                x_num = pandas.to_numeric(d[x_col], errors='coerce')
                if x_num.notna().any():            # treat x as numeric only if it parses
                    d[x_col] = x_num
                d = d.dropna(subset=[x_col, y_col])
                fig = px.scatter(d, x=x_col, y=y_col, hover_name='sample_name')

            else:
                error = f'Unknown plot type: {plot_type}'
        except Exception as err:
            error = str(err)

        # 4. RETURN — fig.to_json() handles numpy; field list drives the dropdowns
        return jsonify({
            'fields': fields,
            'numeric_fields': numeric_fields,
            'categorical_fields': categorical_fields,
            'figure': json.loads(fig.to_json()) if fig is not None else None,
            'error': error,
        })

    return bp
