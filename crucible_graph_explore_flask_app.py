import flask
from flask import Flask, render_template,jsonify, abort, redirect
from pycrucible import CrucibleClient
import json
from networkx.readwrite import json_graph
import networkx as nx
import networkx.readwrite
import json
import os
from flask_qrcode import QRcode

from flask_pyoidc.user_session import UserSession
from flask_pyoidc import OIDCAuthentication
from flask_pyoidc.provider_configuration import ProviderConfiguration, ClientMetadata


from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__, template_folder="flask_templates")
QRcode(app)

app.project_cache = {}

crucible_api_key = os.getenv("CRUCIBLE_API_KEY")
app.crucible_client = CrucibleClient(
    api_url="https://crucible.lbl.gov/testapi",
    api_key=crucible_api_key # v3
)

app.config.update(
    OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI"), #'http://127.0.0.1:8000/redirect_uri',
    SECRET_KEY = os.getenv("PYOIDC_SECRET")
)

PROVIDER_NAME = 'orcid'
CLIENT_META = ClientMetadata(client_id=os.getenv("ORCID_CLIENT_ID"), client_secret=os.getenv("ORCID_CLIENT_SECRET"))
PROVIDER_CONFIG = ProviderConfiguration(issuer='https://orcid.org/', client_metadata=CLIENT_META)

auth = OIDCAuthentication({PROVIDER_NAME: PROVIDER_CONFIG}, app)

def generate_project_cache(project_id, include_metadata=False):
    """Creates and saves project cache (returns None)"""
    pc = dict(project_id=project_id)

    print('getting samples and datasets from Crucible')
    pc['samples'] = app.crucible_client.list_samples(project_id=project_id)
    pc['datasets'] = app.crucible_client.list_datasets(project_id=project_id)

    pc['samples_by_id'] = {s['unique_id']:s for s in pc['samples']}
    pc['samples_by_name'] = {s['sample_name']:s for s in pc['samples']}

    pc['datasets_by_id'] = {ds['unique_id']: ds for ds in pc['datasets']}
    # find some datasets assocated with project samples, but datasets not in project
    for sid, s in pc['samples_by_id'].items():
        for ds in s['datasets']:
            if not ds['unique_id'] in pc['datasets_by_id']:
                pc['datasets_by_id'][ds['unique_id']] = ds
                pc['datasets'].append(ds)

    # load scientific metadata
    if include_metadata:
        print('loading scientific metadata')
        for dsid, ds in pc['datasets_by_id'].items():
                resp = app.crucible_client.get_scientific_metadata(ds['unique_id'])
                if resp:
                    ds['scientific_metadata'] = resp['scientific_metadata']
                else:
                    print('sci meta data missing', dsid, resp)

        print('done')
    # save cache
    fname = cache_filename(project_id)
    with open(fname,'w') as jsonf:
        json.dump( pc, jsonf, indent=4)

def generate_project_graph(project_id):
    # Generate directed graph of sample relationships, using unique_id
    G = nx.DiGraph()
    # start with all samples in the project
    pc = get_project(project_id)
    queue = [s['unique_id'] for s in pc['samples']]
    print(queue)

    visited = set()

    while queue:
        sample_id = queue.pop(0)
        print(f"Graphing {sample_id}")
        if sample_id in visited:
            continue # skip if already in graph

        try:
            #sample = pc['samples_by_id'][sample_id]
            #print(sample_name, sample['unique_id'])
            G.add_node(sample_id)
            visited.add(sample_id)

            children_response = app.crucible_client.list_samples(parent_id=sample_id)
            children = [r['unique_id'] for r in children_response]
            #print(f"Children of {sample['sample_name']}: {children}")
            for child in children:
                G.add_edge(sample_id, child)
                #if sample list incomplete, then recursvive search using a queue is required
                queue.append(child) 
        except Exception as err:
            print(f"Failed to read children of {sample_id}: {err}")


    #save graph as a Node Link JSON
    node_link_data = nx.readwrite.json_graph.node_link_data(G)
    with open(f'cache/{project_id}_project_sample_graph.json') as jsonf:
       json.dump( node_link_data, jsonf)
    #pc['sample_graph_nodelink'] = node_link_data
    return G   

def generate_sample_graph(sample_id):
    # Generate directed graph of sample relationships, using unique_id
    G = nx.DiGraph()
    # start with all samples in the project
    queue = [sample_id]
    visited = set()
    while queue:
        sample_id = queue.pop(0)
        if sample_id in visited:
            print(f"\tskipping {sample_id}")
            continue # skip if already in graph

        try:
            #sample = pc['samples_by_id'][sample_id]
            #print(sample_name, sample['unique_id'])
            print(f"Graphing {sample_id}")
            G.add_node(sample_id)
            visited.add(sample_id)

            children_response = app.crucible_client.list_children_of_sample(sample_id)
            children = [r['unique_id'] for r in children_response]
            print(f"\t children {children}")
            for child in children:
                G.add_edge(sample_id, child)
                queue.append(child)

        except Exception as err:
            print(f"Failed to read children of {sample_id}: {err}")

    queue = [sample_id]
    visited = set()
    while queue:
        sample_id = queue.pop(0)
        if sample_id in visited:
            print(f"\tskipping {sample_id}")
            continue # skip if already in graph

        try:
            #sample = pc['samples_by_id'][sample_id]
            #print(sample_name, sample['unique_id'])
            print(f"Graphing {sample_id}")
            G.add_node(sample_id)
            visited.add(sample_id)

            parents_response = app.crucible_client.list_parents_of_sample(sample_id)
            parents = [r['unique_id'] for r in parents_response]
            print(f"\tparents {parents}")
            for parent in parents:
                G.add_edge(parent, sample_id)
                queue.append(parent)
        except Exception as err:
            print(f"Failed to read parents of {sample_id}: {err}")

    print(G)
    return G

def load_project_cache(project_id):
    """Loads existing project cache into dictionary"""
    fname = cache_filename(project_id)
    with open(fname, 'r') as jsonf:
        pc = json.load(jsonf)
    #pc['sample_graph'] = nx.readwrite.json_graph.node_link_graph(pc['sample_graph_nodelink'])
    return pc

def get_project(project_id):
    if project_id in app.project_cache:
        return app.project_cache[project_id]
    try:
        return load_project_cache(project_id)
    except Exception as err:
        print(f"failed to load project cache for {project_id}, regenerating...")
        generate_project_cache(project_id)
        return load_project_cache(project_id)
    
def cache_filename(project_id):
    # clean up to make a filename
    fname = str(project_id)  
    fname = fname.replace('.','-')
    fname = fname.replace('/','-')
    fname = f'cache/{fname}.json'
    return fname

def clear_project_cache(project_id):
    fname = cache_filename(project_id)
    if os.path.exists(fname):
        os.remove(fname)
    # remove in memory cache
    if project_id in app.project_cache:
        del app.project_cache[project_id]

def is_user_in_project(project_id, orcid=None):
    """Look up user from session unless orcid is defined"""
    if not orcid:
        user_session = UserSession(flask.session)
        orcid=user_session.userinfo['sub']
    projects=app.crucible_client.list_projects(orcid=orcid)
    project_names = [p['project_id'] for p in projects]
    return project_id in project_names


@app.route("/")
@auth.oidc_auth('orcid')
def list_projects():
    #return render_template('project_list.html', projects=app.crucible_client.list_projects())
    user_session = UserSession(flask.session)
    orcid=user_session.userinfo['sub']
    return render_template('project_list.html', projects=app.crucible_client.list_projects(orcid=orcid))

@app.route("/<project_id>/")
@auth.oidc_auth('orcid')
def project_overview(project_id):
    if not is_user_in_project(project_id):
        abort(403)
    pc = get_project(project_id)
    print(pc.keys())
    return render_template('project_overview.html', pc=pc,
                        sample_info=sorted(pc['samples_by_name'].values(), key=lambda x:x['sample_name']))

@app.route("/<project_id>/update-cache")
@auth.oidc_auth('orcid')
def regen_project_cache(project_id):
    if not is_user_in_project(project_id):
        abort(403)
    clear_project_cache(project_id)
    generate_project_cache(project_id)
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
    G = generate_sample_graph(sample_id)

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

    return render_template("dataset.html", 
                           pc=pc, ds=ds, samples=samples, thumbnails=thumbnails)

@app.route("/auth-test/")
@auth.oidc_auth('orcid')
def auth_test():
    user_session = UserSession(flask.session)
    return jsonify(access_token=user_session.access_token,
                   id_token=user_session.id_token,
                   userinfo=user_session.userinfo)


# @app.route('/redirect_uri')
# def redirect_uri():
#     return redirect('/')

@auth.error_view
def error(error=None, error_description=None):
    if error == 'login_required':
            user_session = UserSession(flask.session)
            user_session.clear()
            return redirect('/')

    return jsonify({'error': error, 'message': error_description})
