import json
import os
import networkx as nx
import flask
import pandas
from flask import Flask, render_template,jsonify, abort, redirect
from flask_qrcode import QRcode
from flask_pyoidc.user_session import UserSession
from flask_pyoidc import OIDCAuthentication
from flask_pyoidc.provider_configuration import ProviderConfiguration, ClientMetadata
from pycrucible import CrucibleClient
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__, template_folder="flask_templates")
QRcode(app)

# import project_views.proj10k_perovskite_views

# app.register_blueprint(project_views.proj10k_perovskite_views.proj_views, 
#                       url_prefix='/10k-views')

app.project_cache = {}
app.project_sample_graphs = {}

crucible_api_key = os.getenv("CRUCIBLE_API_KEY")
app.crucible_client = CrucibleClient(
    api_url="https://crucible.lbl.gov/testapi",
    api_key=crucible_api_key # v3
)

#flask-pyoidc config
app.config.update(
    OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI"), #'http://127.0.0.1:8000/redirect_uri',
    SECRET_KEY = os.getenv("PYOIDC_SECRET")
)
PROVIDER_NAME = 'orcid'
CLIENT_META = ClientMetadata(client_id=os.getenv("ORCID_CLIENT_ID"), client_secret=os.getenv("ORCID_CLIENT_SECRET"))
PROVIDER_CONFIG = ProviderConfiguration(issuer='https://orcid.org/', client_metadata=CLIENT_META)

auth = OIDCAuthentication({PROVIDER_NAME: PROVIDER_CONFIG}, app)


from crucible_project_graph import \
    load_project_cache, \
    generate_project_cache, cache_filename, cache_sample_graph_filename,\
    generate_sample_graph, load_project_sample_graph,\
    generate_project_sample_graph

def get_project(project_id):
    if project_id in app.project_cache:
        return app.project_cache[project_id]
    try:
        return load_project_cache(project_id)
    except Exception as err:
        print(f"failed to load project cache for {project_id}, regenerating...")
        generate_project_cache(project_id, app.crucible_client)
        return load_project_cache(project_id)
    
def get_project_sample_graph(project_id):
    if project_id in app.project_cache:
        return app.project_sample_graphs[project_id]
    try:
        return load_project_sample_graph(project_id)
    except Exception as err:
        print(f"failed to load project cache for {project_id}, regenerating...")
        G = generate_project_sample_graph(project_id,app.crucible_client)
        app.project_sample_graphs[project_id] = G
        return G

    
def clear_project_cache(project_id):
    fname = cache_filename(project_id)
    if os.path.exists(fname):
        os.remove(fname)
    fname = cache_sample_graph_filename(project_id)
    if os.path.exists(fname):
        os.remove(fname)
    # remove in memory cache
    if project_id in app.project_cache:
        del app.project_cache[project_id]
    if project_id in app.project_sample_graphs:
        del app.project_sample_graphs[project_id]

def is_user_in_project(project_id, orcid=None):
    """Look up user from session unless orcid is defined"""
    if not orcid:
        user_session = UserSession(flask.session)
        orcid=user_session.userinfo['sub']
    projects=app.crucible_client.list_projects(orcid=orcid)
    project_names = [p['project_id'] for p in projects]
    return project_id in project_names


# ROUTES

@app.route("/")
@auth.oidc_auth('orcid')
def list_projects():
    #return render_template('project_list.html', projects=app.crucible_client.list_projects())
    user_session = UserSession(flask.session)
    orcid=user_session.userinfo['sub']
    user_projects = app.crucible_client.list_projects(orcid=orcid)
    return render_template('project_list.html', projects=user_projects)

@app.route("/<project_id>/")
@auth.oidc_auth('orcid')
def project_overview(project_id):
    if not is_user_in_project(project_id):
        abort(403)
    pc = generate_project_cache(project_id, app.crucible_client, include_metadata=True)
    pc = get_project(project_id)
    return render_template('project_overview.html', pc=pc,
                        sample_info=sorted(pc['samples_by_name'].values(), key=lambda x:x['sample_name']))

@app.route("/<project_id>/update-cache")
@auth.oidc_auth('orcid')
def regen_project_cache(project_id):
    if not is_user_in_project(project_id):
        abort(403)
    clear_project_cache(project_id)
    generate_project_cache(project_id, app.crucible_client)
    pc = get_project(project_id)
    #return (f"Regenerated Cache for {project_id}. {len(pc['samples'])} Samples and {len(pc['datasets'])} Datasets")
    return redirect(f"/{project_id}/")

@app.route("/<project_id>/sample-graph/<sample_id>")
@auth.oidc_auth('orcid')
def sample_graph(project_id, sample_id):
    if not is_user_in_project(project_id):
        abort(403)
    pc = get_project(project_id)

    print(f"sample_graph")
    G = generate_sample_graph(sample_id, app.crucible_client)

    #sample_name = pc['samples_by_id'][sample_id]['sample_name']
    #print(sample_name)
    descendants = nx.descendants(G, sample_id)
    ancestors = nx.ancestors(G, sample_id)

    # find any samples not in cache:
    for sid in G.nodes:
        if not ( sid in pc['samples_by_id']):
            print(f"found missing sample in graph {sid}")
            pc['samples_by_id'][sid] = app.crucible_client.get_sample(sid)

    # find any dataset metadata not in cache:
#    for sid in G.nodes:
#        sid.get_


    # need to translate these to names from ids
    descendants_path = {}
    for sid in descendants:
        paths = list(nx.all_simple_paths(G, sample_id, sid))
        name = pc['samples_by_id'][sid]['sample_name']
        descendants_path[name] = [pc['samples_by_id'][x]['sample_name'] for x in paths[0]]

    ancestors_path = {}
    for sid in ancestors:
        paths = list(nx.all_simple_paths(G, sid, sample_id))
        name = pc['samples_by_id'][sid]['sample_name']
        ancestors_path[name] = [pc['samples_by_id'][x]['sample_name'] for x in paths[0]]

    # time sort ancestors using the unique mfid  as a proxy for time
    ancestors_info = sorted([pc['samples_by_id'][sample_id] for sample_id in ancestors], key=lambda x: x['unique_id'])
    self_info = pc['samples_by_id'][sample_id]
    descendants_info = sorted([pc['samples_by_id'][sample_id] for sample_id in descendants], key=lambda x: x['unique_id'])

    return render_template('sample_graph.html',
                           pc=pc,
                           ancestors_info=ancestors_info,
                           self_info=self_info,
                           descendants_info=descendants_info,
                           ancestors_path=ancestors_path,
                           descendants_path = descendants_path,
                           client=app.crucible_client,
                           datasets_by_id = pc['datasets_by_id']
                           )

@app.route("/<project_id>/dataset/<dsid>")
@auth.oidc_auth('orcid')
def dataset(project_id, dsid):
    if not is_user_in_project(project_id):
        abort(403)
    pc = get_project(project_id)
    ds = app.crucible_client.get_dataset(dsid, include_metadata=True)
    #ds = pc['datasets_by_id'][dsid] #cache
    samples = app.crucible_client.list_samples(dataset_id=dsid)

    thumbnails = app.crucible_client.get_thumbnails(dsid)

    associated_files = app.crucible_client.get_associated_files(dsid)
    print(associated_files)

    download_links = app.crucible_client.get_dataset_download_links(dsid)

    return render_template("dataset.html", 
                           pc=pc, ds=ds, 
                           samples=samples,
                            files=associated_files,
                            download_links=download_links,
                           thumbnails=thumbnails)

@app.route("/auth-test/")
@auth.oidc_auth('orcid')
def auth_test():
    user_session = UserSession(flask.session)
    return jsonify(access_token=user_session.access_token,
                   id_token=user_session.id_token,
                   userinfo=user_session.userinfo)

@auth.error_view
def error(error=None, error_description=None):
    if error == 'login_required':
        user_session = UserSession(flask.session)
        user_session.clear()
        return redirect('/')

    print("error", {'error': error, 'message': error_description})
    return redirect('/')
    #return jsonify({'error': error, 'message': error_description})


# 10_perovskite specific views

project_id = "10k_perovskites"
@app.route(f"/10k_perovskites/view/overview")
@auth.oidc_auth('orcid')
def overview10k():
    pc = get_project(project_id)
    G = get_project_sample_graph(project_id)

    if not is_user_in_project(project_id):
        abort(403)

    thin_films = [s for s in pc['samples'] 
                  if s['sample_name'].startswith('TF')]
    thin_films.sort(key= lambda x: x['sample_name'])

    rows = []

    for s in thin_films:

        # all ancestors
        ancestors = nx.ancestors(G, s['unique_id'])
        ancestors = [pc['samples_by_id'][sid] for sid in ancestors]
        # all descendants
        descendants = nx.descendants(G, s['unique_id'])
        descendants = [pc['samples_by_id'][sid] for sid in descendants]

        # Find the solid precursor samples that were used to make this thin film sample
        solid_precursors = [sample for sample in ancestors if sample['sample_name'].startswith('SP')]
        
        # Capture their compositions from the 'Solid Precursor synthesis' dataset
        precursor_compositions = []
        try:
            for sp in solid_precursors:
                for ds in sp['datasets']:
                    if ds['measurement'] == 'Solid Precursor synthesis':
                        full_ds = pc['datasets_by_id'][ds['unique_id']]
                        material = full_ds['scientific_metadata']['name']
                        precursor_compositions.append(material)
        except Exception as err:
            print(f"Failed to get solid precursor details {s['sample_name']}: {err}")
        
        if len(precursor_compositions) != 2:
            #print(f"Warning: expected 2 solid precursors for {s['sample_name']}, found {len(precursor_compositions)}")
            if len(precursor_compositions) < 2:
                precursor_compositions += [None] * (2 - len(precursor_compositions))
        
        sr = [ds for ds in s['datasets'] if ds['measurement'] == 'spin_run']
        if sr:
            print(sr)
            sr = pc['datasets_by_id'][sr[0]['unique_id']]
            anneal_temp = sr['scientific_metadata']['heater_sv_temp']
        else: 
            anneal_temp = '?'

        row = {
            'thin_film_sample_name': s['sample_name'],
            'thin_film_unique_id': s['unique_id'],
            'sp_A': precursor_compositions[0],
            'sp_B': precursor_compositions[1],
            'anneal_temp': anneal_temp,
        }
        #print(row)
        rows.append(row)    

    df = pandas.DataFrame(rows)

    return render_template(f'proj10k_templates/overview.html', 
                           pc=pc,
                           tfs=thin_films, df=df)

@app.route(f"/10k_perovskites/view/thinfilm-gallery")
@auth.oidc_auth('orcid')
def thinfilm_gallery_10k():
    project_id = "10k_perovskites"
    if not is_user_in_project(project_id):
        abort(403)
    pc = get_project(project_id)

    thin_films = [s for s in pc['samples'] 
                  if s['sample_name'].startswith('TF')]
    thin_films.sort(key= lambda x: x['sample_name'])

    tf_thumbs = []
    # get the thumbnail of the 
    for tf in thin_films:
        print(tf['sample_name'])
        img_datasets = [ds for ds in tf['datasets'] if ds['measurement'] == 'sample well image']
        
        if img_datasets:
            ds = img_datasets[0]
            dsid = ds['unique_id']
            thumbnails = app.crucible_client.get_thumbnails(dsid)    
            tn  = thumbnails[0]
        else:
            tn = {}
        tn['sample_name'] = tf['sample_name']
        tn['sample_url'] = f"/10k_perovskites/sample-graph/{tf['unique_id']}"
        tf_thumbs.append(tn)
            



    return render_template('proj10k_templates/thinfilm-gallery.html', tf_thumbs=tf_thumbs)
