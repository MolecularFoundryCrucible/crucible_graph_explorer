from flask import Flask, render_template
from pycrucible import CrucibleClient
import json
from networkx.readwrite import json_graph
import networkx as nx
import networkx.readwrite
import json
import os
from typing import List,Dict, Any


from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__, template_folder="flask_templates")
app.project_cache = {}

crucible_api_key = os.getenv("CRUCIBLE_API_KEY")
app.crucible_client = CrucibleClient(
    api_url="https://crucible.lbl.gov/testapi",
    api_key=crucible_api_key # v3
)

def generate_project_cache(project_id):
    """Creates and saves project cache (returns None)"""
    pc = dict(project_id=project_id)

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
    for dsid, ds in pc['datasets_by_id'].items():
        try:
            ds['scientific_metadata'] = app.crucible_client.get_scientific_metadata(
                                                                ds['unique_id'])['scientific_metadata']
        except Exception as err:
            ds['scientific_metadata'] = dict()
            print('sci meta data fail', dsid, ds, err)

    # Generate directed graph of sample relationships, using unique_id
    G = nx.DiGraph()
    # start with all samples in the project
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


    # save graph as a Node Link JSON
    node_link_data = nx.readwrite.json_graph.node_link_data(G)
    #with open(f'cache/{project_id}/project_sample_graph.json') as jsonf:
    #    json.dump( node_link_data, jsonf)
    pc['sample_graph_nodelink'] = node_link_data
    
    # save cache
    with open(f'cache/{project_id}.json','w') as jsonf:
        json.dump( pc, jsonf, indent=4)

def load_project_cache(project_id):
    """Loads existing project cache into dictionary"""
    with open(f'cache/{project_id}.json', 'r') as jsonf:
        pc = json.load(jsonf)
    pc['sample_graph'] = nx.readwrite.json_graph.node_link_graph(pc['sample_graph_nodelink'])
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

@app.route("/")
def list_projects():
    return render_template('project_list.html', projects=app.crucible_client.list_projects())

@app.route("/<project_id>/")
def project_overview(project_id):
    pc = get_project(project_id)
    print(pc.keys())
    return render_template('project_overview.html', pc=pc,
                           sample_info=sorted(pc['samples_by_name'].values(), key=lambda x:x['sample_name']))

@app.route("/<project_id>/sample-graph/<sample_id>")
def sample_graph(project_id, sample_id):
    pc = get_project(project_id)

    #sample_name = pc['samples_by_id'][sample_id]['sample_name']
    #print(sample_name)
    descendants = nx.descendants(pc['sample_graph'], sample_id)
    ancestors = nx.ancestors(pc['sample_graph'], sample_id)

    descendants_path = {}
    for x in descendants:
        paths = list(nx.all_simple_paths(pc['sample_graph'], sample_id, x))
        descendants_path[x] = paths[0]

    ancestors_path = {}
    for x in ancestors:
        paths = list(nx.all_simple_paths(pc['sample_graph'], x, sample_id))
        ancestors_path[x] = paths[0]

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
def dataset(project_id, dsid):
    pc = get_project(project_id)
    samples = app.crucible_client.list_samples(dataset_id=dsid)
    return render_template("dataset.html", 
                           pc=pc, ds=pc['datasets_by_id'][dsid], samples=samples)