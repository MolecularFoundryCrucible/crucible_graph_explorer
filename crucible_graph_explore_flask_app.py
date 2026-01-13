from flask import Flask, render_template
from pycrucible import CrucibleClient
import json
from networkx.readwrite import json_graph
import networkx as nx
import os

app = Flask(__name__, template_folder="flask_templates")

from dotenv import load_dotenv
load_dotenv()

crucible_api_key = os.getenv("CRUCIBLE_API_KEY")
app.crucible_client = CrucibleClient(
    api_url="https://crucible.lbl.gov/testapi",
    api_key=crucible_api_key # v3
)


app.sample_info = app.crucible_client.list_samples(project_id="10k_perovskites")
app.datasets = app.crucible_client.list_datasets(project_id="10k_perovskites")


app.sample_info_by_id = {s['unique_id']:s for s in app.sample_info}
app.sample_info_by_name = {s['sample_name']:s for s in app.sample_info}

app.datasets_by_id = {ds['unique_id']: ds for ds in app.datasets}

for sid, s in app.sample_info_by_id.items():
    for ds in s['datasets']:
        if not ds['unique_id'] in app.datasets_by_id:
            app.datasets_by_id[ds['unique_id']] = ds

for dsid, ds in app.datasets_by_id.items():
    try:
        ds['scientific_metadata'] = app.crucible_client.get_scientific_metadata(ds['unique_id'])['scientific_metadata']
    except Exception as err:
        ds['scientific_metadata'] = dict()
        print('sci meta data fail', dsid, ds, err)

with open('10k_perovskite_project_sample_graph.json', 'r') as jsonf:
    j = json.load(jsonf)
app.sample_graph  = json_graph.node_link_graph(j) # sample name-based connectivity graph


@app.route("/")
def hello_world():
    return render_template('index.html', sample_info=sorted(app.sample_info_by_name.values(), key=lambda x:x['sample_name']))

@app.route("/sample-graph/<sample_id>")
def sample_graph(sample_id):
    sample_name = app.sample_info_by_id[sample_id]['sample_name']
    print(sample_name)
    descendants = nx.descendants(app.sample_graph, sample_name)
    ancestors = nx.ancestors(app.sample_graph, sample_name)

    descendants_path = {}
    for x in descendants:
        paths = list(nx.all_simple_paths(app.sample_graph, sample_name, x))
        descendants_path[x] = paths[0]

    ancestors_path = {}
    for x in ancestors:
        paths = list(nx.all_simple_paths(app.sample_graph, x, sample_name))
        ancestors_path[x] = paths[0]

    # time sort ancestors using the unique mfid  as a proxy for time
    ancestors_info = sorted([app.sample_info_by_name[name] for name in ancestors], key=lambda x: x['unique_id'])
    self_info = app.sample_info_by_name[sample_name]
    descendants_info = sorted([app.sample_info_by_name[name] for name in descendants], key=lambda x: x['unique_id'])

    return render_template('sample_graph.html', 
                           ancestors_info=ancestors_info,
                           self_info=self_info,
                           descendants_info=descendants_info,
                           ancestors_path=ancestors_path,
                           descendants_path = descendants_path,
                           client=app.crucible_client,
                           datasets_by_id = app.datasets_by_id
                           )

@app.route("/dataset/<dsid>")
def dataset(dsid):
    return render_template("dataset.html", ds=app.datasets_by_id[dsid])