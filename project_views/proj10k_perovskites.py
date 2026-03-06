import networkx as nx
import pandas
from flask import Blueprint, render_template, abort, current_app

PROJECT_ID = '10k_perovskites'

VIEWS = [
    {'label': 'Overview',          'url': '/overview',         'icon': 'bi-bar-chart'},
    {'label': 'Thin Film Gallery', 'url': '/thinfilm-gallery', 'icon': 'bi-images'},
]


def create_blueprint(auth, helpers):
    bp = Blueprint(f'proj_{PROJECT_ID}', __name__)

    get_project = helpers['get_project']
    is_user_in_project = helpers['is_user_in_project']
    get_project_sample_graph = helpers['get_project_sample_graph']

    @bp.route('/overview')
    @auth.oidc_auth('orcid')
    def overview():
        if not is_user_in_project(PROJECT_ID):
            abort(403)
        pc = get_project(PROJECT_ID, include_metadata=True)
        G = get_project_sample_graph(PROJECT_ID)

        thin_films = [s for s in pc['samples'] if s['sample_name'].startswith('TF')]
        thin_films.sort(key=lambda x: x['sample_name'])

        rows = []
        for s in thin_films:
            ancestors = [pc['samples_by_id'][sid] for sid in nx.ancestors(G, s['unique_id'])]
            descendants = [pc['samples_by_id'][sid] for sid in nx.descendants(G, s['unique_id'])]

            solid_precursors = [s for s in ancestors if s['sample_name'].startswith('SP')]
            precursor_compositions = []
            try:
                for sp in solid_precursors:
                    for ds in sp['datasets']:
                        if ds['measurement'] == 'Solid Precursor synthesis':
                            full_ds = pc['datasets_by_id'][ds['unique_id']]
                            precursor_compositions.append(full_ds['scientific_metadata']['name'])
            except Exception as err:
                print(f"Failed to get solid precursor details {s['sample_name']}: {err}")

            if len(precursor_compositions) < 2:
                precursor_compositions += [None] * (2 - len(precursor_compositions))

            sr = [ds for ds in s['datasets'] if ds['measurement'] == 'spin_run']
            if sr:
                sr = pc['datasets_by_id'][sr[0]['unique_id']]
                anneal_temp = sr['scientific_metadata']['heater_sv_temp']
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
        if not is_user_in_project(PROJECT_ID):
            abort(403)
        pc = get_project(PROJECT_ID)

        thin_films = [s for s in pc['samples'] if s['sample_name'].startswith('TF')]
        thin_films.sort(key=lambda x: x['sample_name'])

        img_dsid = {
            tf['unique_id']: next(
                (ds['unique_id'] for ds in tf['datasets'] if ds['measurement'] == 'sample well image'),
                None
            )
            for tf in thin_films
        }
        batch = {}
        dataset_ids = [dsid for dsid in img_dsid.values() if dsid]
        if dataset_ids:
            try:
                batch = current_app.crucible_client._request(
                    "POST", "/datasets/first_thumbnails", json=dataset_ids
                )
            except Exception:
                pass

        tf_thumbs = []
        for tf in thin_films:
            dsid = img_dsid.get(tf['unique_id'])
            tn = dict(batch.get(dsid, {})) if dsid else {}
            tn['sample_name'] = tf['sample_name']
            tn['sample_url'] = f'/{PROJECT_ID}/sample-graph/{tf["unique_id"]}'
            tf_thumbs.append(tn)

        return render_template('proj10k_templates/thinfilm-gallery.html', tf_thumbs=tf_thumbs)

    return bp
