import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
import networkx as nx
import flask
import pandas
import markdown
import requests
from flask import Flask, render_template, jsonify, abort, redirect, request
from flask_qrcode import QRcode
from flask_vite import Vite
from flask_pyoidc.user_session import UserSession
from flask_pyoidc import OIDCAuthentication
from flask_pyoidc.provider_configuration import ProviderConfiguration, ClientMetadata
from pycrucible import CrucibleClient
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__, template_folder="flask_templates")
QRcode(app)
vite = Vite(app)

# import project_views.proj10k_perovskite_views

# app.register_blueprint(project_views.proj10k_perovskite_views.proj_views, 
#                       url_prefix='/10k-views')

app.project_cache = {}
app.project_sample_graphs = {}

crucible_api_key = os.getenv("CRUCIBLE_API_KEY")
app.crucible_client = CrucibleClient(
    api_url="https://crucible.lbl.gov/api/v1",
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
     generate_project_cache
    #load_project_cache, \
#, cache_filename, cache_sample_graph_filename,\
#    generate_sample_graph, load_project_sample_graph,\
#    generate_project_sample_graph

def get_project(project_id,  include_metadata=False):
    return generate_project_cache(project_id, app.crucible_client,include_metadata=include_metadata, save=False)
    if project_id in app.project_cache:
        return app.project_cache[project_id]
    try:
        return load_project_cache(project_id)
    except Exception as err:
        print(f"failed to load project cache for {project_id}, regenerating...")
        generate_project_cache(project_id, app.crucible_client)
        return load_project_cache(project_id)
    
def get_project_sample_graph(project_id):
    node_link_data = app.crucible_client._request("GET",f"/projects/{project_id}/sample_graph")
    G = nx.node_link_graph(node_link_data)
    return G
    # if project_id in app.project_cache:
    #     return app.project_sample_graphs[project_id]
    # try:
    #     return load_project_sample_graph(project_id)
    # except Exception as err:
    #     print(f"failed to load project cache for {project_id}, regenerating...")
    #     G = generate_project_sample_graph(project_id,app.crucible_client)
    #     app.project_sample_graphs[project_id] = G
    #     return G

    
# def clear_project_cache(project_id):
#     fname = cache_filename(project_id)
#     if os.path.exists(fname):
#         os.remove(fname)
#     fname = cache_sample_graph_filename(project_id)
#     if os.path.exists(fname):
#         os.remove(fname)
#     # remove in memory cache
#     if project_id in app.project_cache:
#         del app.project_cache[project_id]
#     if project_id in app.project_sample_graphs:
#         del app.project_sample_graphs[project_id]

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
    #pc = generate_project_cache(project_id, app.crucible_client, include_metadata=True)
    pc = get_project(project_id)

    # samples by type
    samples_by_type = dict()
    for s in pc['samples']:
        stype = s['sample_type']
        if not stype in samples_by_type:
            samples_by_type[stype] = []
        samples_by_type[stype].append(s)

    # Sort samples within each type by sample_name
    for stype in samples_by_type:
        samples_by_type[stype].sort(key=lambda x: x['sample_name'])

    # datasets by type
    #measurement_types = set([ds['measurement'] for ds in pc['datasets']])
    datasets_by_type = dict()
    for ds in pc['datasets']:
        mtype = ds['measurement']
        if not mtype in datasets_by_type:
            datasets_by_type[mtype] = []
        datasets_by_type[mtype].append(ds)

    return render_template('project_overview.html', pc=pc,
                        sample_info=sorted(pc['samples_by_name'].values(), key=lambda x:x['sample_name']),
                        samples_by_type=samples_by_type,
                        datasets_by_type=datasets_by_type,
                        )

# @app.route("/<project_id>/update-cache")
# @auth.oidc_auth('orcid')
# def regen_project_cache(project_id):
#     if not is_user_in_project(project_id):
#         abort(403)
#     clear_project_cache(project_id)
#     generate_project_cache(project_id, app.crucible_client)
#     pc = get_project(project_id)
#     #return (f"Regenerated Cache for {project_id}. {len(pc['samples'])} Samples and {len(pc['datasets'])} Datasets")
#     return redirect(f"/{project_id}/")

@app.route("/<project_id>/sample-graph/<sample_id>")
@auth.oidc_auth('orcid')
def sample_graph(project_id, sample_id):
    if not is_user_in_project(project_id):
        abort(403)
    pc = get_project(project_id)

    print(f"sample_graph")
    #G = generate_sample_graph(sample_id, app.crucible_client)
    #Gproject = generate_project_sample_graph(project_id, app.crucible_client)
    G = get_project_sample_graph(project_id)
    #G = nx.ego_graph(Gproject,sample_id)
    #print(G)

    #sample_name = pc['samples_by_id'][sample_id]['sample_name']
    #print(sample_name)
    descendants = nx.descendants(G, sample_id)
    ancestors = nx.ancestors(G, sample_id)

    # # find any samples not in cache:
    # for sid in G.nodes:
    #     if not ( sid in pc['samples_by_id']):
    #         print(f"found missing sample in graph {sid}")
    #         pc['samples_by_id'][sid] = app.crucible_client.get_sample(sid)


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

@app.route("/<project_id>/api/sample-graph-data/<sample_id>")
@auth.oidc_auth('orcid')
def sample_graph_data(project_id, sample_id):
    """API endpoint that returns graph data as JSON for visualization"""
    if not is_user_in_project(project_id):
        abort(403)

    pc = get_project(project_id)
    G = get_project_sample_graph(project_id)

    # Get the subgraph containing the sample and all its ancestors and descendants
    descendants = nx.descendants(G, sample_id)
    ancestors = nx.ancestors(G, sample_id)
    all_nodes = ancestors | descendants | {sample_id}

    # Create subgraph with only relevant nodes
    subgraph = G.subgraph(all_nodes)

    # Build nodes list
    nodes = []
    for node_id in subgraph.nodes():
        sample = pc['samples_by_id'].get(node_id, {})
        nodes.append({
            'id': node_id,
            'label': sample.get('sample_name', node_id),
            'name': sample.get('sample_name', node_id),
            'description': sample.get('description', '')
        })

    # Build edges list
    edges = []
    for source, target in subgraph.edges():
        edges.append({
            'source': source,
            'target': target
        })

    return jsonify({
        'nodes': nodes,
        'edges': edges,
        'centerNodeId': sample_id
    })

@app.route("/<project_id>/dataset/<dsid>")
@auth.oidc_auth('orcid')
def dataset(project_id, dsid):
    if not is_user_in_project(project_id):
        abort(403)
    #pc = get_project(project_id)
    ds = app.crucible_client.get_dataset(dsid, include_metadata=True)
    #ds = pc['datasets_by_id'][dsid] #cache
    samples = app.crucible_client.list_samples(dataset_id=dsid)

    thumbnails = app.crucible_client.get_thumbnails(dsid)

    associated_files = app.crucible_client.get_associated_files(dsid)
    print(associated_files)

    download_links = app.crucible_client.get_dataset_download_links(dsid)

    child_datasets = app.crucible_client.list_children_of_dataset(dsid)
    parent_datasets = app.crucible_client.list_parents_of_dataset(dsid)

    # Handle MDNote measurement type
    markdown_html = None
    if ds.get('measurement') == 'MDNote':
        # Find markdown file in associated files
        md_file = None
        for file in associated_files:
            if file['filename'].endswith('.md'):
                md_file = file
                break

        if md_file:
            # Transform filename to download link key: dataset_unique_id/basename
            md_basename = os.path.basename(md_file['filename'])
            download_key = f"{ds['unique_id']}/{md_basename}"

            if download_key in download_links:
                try:
                    # Fetch the markdown content from the download link
                    response = requests.get(download_links[download_key])
                    if response.status_code == 200:
                        md_content = response.text

                        # Convert wiki-style links to proper markdown links
                        # [[dataset:ID|Name]] -> [Name](/<project_id>/dataset/ID)
                        # [[dataset:ID]] -> [Dataset ID](/<project_id>/dataset/ID)
                        def replace_dataset_link(match):
                            dataset_id = match.group(1)
                            name = match.group(2) if match.group(2) else f'Dataset-{dataset_id}'
                            return f'[{name}](/{project_id}/dataset/{dataset_id})'

                        md_content = re.sub(
                            r'\[\[dataset:([^\]|]+)(?:\|([^\]]+))?\]\]',
                            replace_dataset_link,
                            md_content
                        )

                        # [[sample:ID|Name]] -> [Name](/<project_id>/sample-graph/ID)
                        # [[sample:ID]] -> [Sample-ID](/<project_id>/sample-graph/ID)
                        def replace_sample_link(match):
                            sample_id = match.group(1)
                            name = match.group(2) if match.group(2) else f'Sample-{sample_id}'
                            return f'[{name}](/{project_id}/sample-graph/{sample_id})'

                        md_content = re.sub(
                            r'\[\[sample:([^\]|]+)(?:\|([^\]]+))?\]\]',
                            replace_sample_link,
                            md_content
                        )

                        # Convert markdown to HTML
                        markdown_html = markdown.markdown(md_content, extensions=['extra', 'codehilite', 'tables'])
                except Exception as err:
                    print(f"Failed to fetch/render markdown for {dsid}: {err}")

    return render_template("dataset.html",
                           project_id=project_id, ds=ds,
                           child_datasets = child_datasets,
                           parent_datasets = parent_datasets,
                           samples=samples,
                            files=associated_files,
                            download_links=download_links,
                           thumbnails=thumbnails,
                           markdown_html=markdown_html)

@app.route("/<project_id>/entity-graph/<entity_type>/<entity_id>")
@auth.oidc_auth('orcid')
def entity_graph(project_id, entity_type, entity_id):
    if entity_type not in ('sample', 'dataset'):
        abort(400)
    if not is_user_in_project(project_id):
        abort(403)
    pc = get_project(project_id)
    if entity_type == 'sample':
        entity = pc['samples_by_id'].get(entity_id, {})
        entity_name = entity.get('sample_name', entity_id[:13])
    else:
        entity = pc['datasets_by_id'].get(entity_id, {})
        entity_name = entity.get('dataset_name', entity_id[:13])
    return render_template('entity_graph.html',
                           pc=pc,
                           entity_type=entity_type,
                           entity_id=entity_id,
                           entity_name=entity_name)


@app.route("/<project_id>/api/entity-graph-data/<entity_type>/<entity_id>")
@auth.oidc_auth('orcid')
def entity_graph_data(project_id, entity_type, entity_id):
    if entity_type not in ('sample', 'dataset'):
        abort(400)
    if not is_user_in_project(project_id):
        abort(403)

    pc = get_project(project_id)
    G = get_project_sample_graph(project_id)

    # Determine focal sample(s)
    if entity_type == 'sample':
        focal_sample_ids = {entity_id}
    else:
        focal_sample_ids = {s['unique_id'] for s in app.crucible_client.list_samples(dataset_id=entity_id)}

    # Expand to ancestors + descendants for each focal sample
    all_sample_ids = set()
    for sid in focal_sample_ids:
        if sid in G:
            all_sample_ids |= nx.ancestors(G, sid) | nx.descendants(G, sid) | {sid}
        else:
            all_sample_ids.add(sid)

    subgraph = G.subgraph(all_sample_ids)
    nodes = []
    edges = []
    seen = set()

    # Sample nodes
    for sid in all_sample_ids:
        seen.add(sid)
        sample = pc['samples_by_id'].get(sid, {})
        nodes.append({
            'id': sid,
            'label': sample.get('sample_name', sid[:13]),
            'type': 'sample',
            'description': sample.get('description', ''),
            'url': f'/{project_id}/sample-graph/{sid}'
        })

    # Sample-sample edges
    for source, target in subgraph.edges():
        edges.append({'source': source, 'target': target})

    # Collect unique dataset IDs and edges in one pass
    dataset_meta = {}  # dsid -> ds dict
    for sid in all_sample_ids:
        sample = pc['samples_by_id'].get(sid, {})
        for ds_ref in sample.get('datasets', []):
            dsid = ds_ref['unique_id']
            edges.append({'source': sid, 'target': dsid})
            if dsid not in seen:
                seen.add(dsid)
                dataset_meta[dsid] = pc['datasets_by_id'].get(dsid, ds_ref)

    # Fetch all thumbnails in parallel
    def fetch_thumbnail(dsid):
        try:
            thumbs = app.crucible_client.get_thumbnails(dsid)
            if thumbs:
                return dsid, f"data:image/png;base64,{thumbs[0]['thumbnail_b64str']}"
        except Exception:
            pass
        return dsid, None

    thumbnails = {}
    if dataset_meta:
        with ThreadPoolExecutor(max_workers=min(len(dataset_meta), 10)) as executor:
            for dsid, thumb in executor.map(fetch_thumbnail, dataset_meta):
                thumbnails[dsid] = thumb

    # Build dataset nodes
    for dsid, ds in dataset_meta.items():
        nodes.append({
            'id': dsid,
            'label': ds.get('dataset_name', dsid[:13]),
            'type': 'dataset',
            'measurement': ds.get('measurement', ''),
            'url': f'/{project_id}/dataset/{dsid}',
            'thumbnail': thumbnails.get(dsid)
        })

    return jsonify({
        'nodes': nodes,
        'edges': edges,
        'centerNodeId': entity_id,
        'centerNodeType': entity_type
    })


@app.route("/<project_id>/api/samples")
@auth.oidc_auth('orcid')
def api_samples(project_id):
    if not is_user_in_project(project_id):
        abort(403)
    q = request.args.get('q', '').lower()
    pc = get_project(project_id)
    samples = pc['samples']
    if q:
        samples = [s for s in samples if q in s['sample_name'].lower() or q in s['unique_id'].lower()]
    return jsonify([{'id': s['unique_id'], 'name': s['sample_name']} for s in samples[:20]])


@app.route("/<project_id>/api/datasets")
@auth.oidc_auth('orcid')
def api_datasets(project_id):
    if not is_user_in_project(project_id):
        abort(403)
    q = request.args.get('q', '').lower()
    pc = get_project(project_id)
    datasets = pc['datasets']
    if q:
        datasets = [d for d in datasets if q in d['dataset_name'].lower() or q in d['unique_id'].lower()]
    return jsonify([{'id': d['unique_id'], 'name': d['dataset_name']} for d in datasets[:20]])


@app.route("/<project_id>/dataset/<dsid>/mdnote-edit", methods=['GET', 'POST'])
@auth.oidc_auth('orcid')
def mdnote_edit(project_id, dsid):
    if not is_user_in_project(project_id):
        abort(403)
    ds = app.crucible_client.get_dataset(dsid, include_metadata=True)

    if request.method == 'POST':
        md_content = request.json.get('content', '')
        associated_files = app.crucible_client.get_associated_files(dsid)
        md_filename = 'note.md'
        for file in associated_files:
            if file['filename'].endswith('.md'):
                md_filename = os.path.basename(file['filename'])
                break
        tmp_dir = tempfile.mkdtemp()
        tmp_path = os.path.join(tmp_dir, md_filename)
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(md_content)
            result = app.crucible_client.upload_dataset_file(dsid, tmp_path, verbose=True)
            print("Upload result:", result)
        finally:
            os.unlink(tmp_path)
            os.rmdir(tmp_dir)
        return jsonify({'status': 'ok'})

    # GET: load current markdown content
    associated_files = app.crucible_client.get_associated_files(dsid)
    download_links = app.crucible_client.get_dataset_download_links(dsid)
    md_content = ''
    for file in associated_files:
        if file['filename'].endswith('.md'):
            md_basename = os.path.basename(file['filename'])
            download_key = f"{ds['unique_id']}/{md_basename}"
            if download_key in download_links:
                response = requests.get(download_links[download_key])
                if response.status_code == 200:
                    md_content = response.text
            break

    return render_template('mdnote_edit.html',
                           project_id=project_id,
                           ds=ds,
                           md_content=md_content)


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
    pc = get_project(project_id, include_metadata=True)
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
