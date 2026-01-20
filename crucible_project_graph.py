import json
from networkx.readwrite import json_graph
import networkx as nx
import networkx.readwrite
import os

def get_project(project_id, crucible_client):
    # if project_id in app.project_cache:
    #     return app.project_cache[project_id]
    try:
        return load_project_cache(project_id)
    except Exception as err:
        print(f"failed to load project cache for {project_id}, regenerating...")
        generate_project_cache(project_id, crucible_client)
        return load_project_cache(project_id)
    
def clear_project_cache(project_id):
    fname = cache_filename(project_id)
    if os.path.exists(fname):
        os.remove(fname)
    # remove in memory cache
    # if project_id in app.project_cache:
    #     del app.project_cache[project_id]    

def generate_project_cache(project_id, crucible_client, include_metadata=False):
    """Creates and saves project cache (returns None)"""
    pc = dict(project_id=project_id)

    print('getting samples and datasets from Crucible')
    pc['samples'] = crucible_client.list_samples(project_id=project_id)
    pc['datasets'] = crucible_client.list_datasets(project_id=project_id)

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
                resp = crucible_client.get_scientific_metadata(ds['unique_id'])
                if resp:
                    ds['scientific_metadata'] = resp['scientific_metadata']
                else:
                    print('sci meta data missing', dsid, resp)

        print('done')
    # save cache
    fname = cache_filename(project_id)
    with open(fname,'w') as jsonf:
        json.dump( pc, jsonf, indent=4)

def generate_project_graph(project_id, crucible_client):
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

            children_response = crucible_client.list_samples(parent_id=sample_id)
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

def generate_sample_graph(sample_id, crucible_client):
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

            children_response = crucible_client.list_children_of_sample(sample_id)
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

            parents_response = crucible_client.list_parents_of_sample(sample_id)
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

def cache_filename(project_id):
    # clean up to make a filename
    fname = str(project_id)  
    fname = fname.replace('.','-')
    fname = fname.replace('/','-')
    fname = f'cache/{fname}.json'
    return fname