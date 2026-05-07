import networkx as nx
from flask import current_app


def _to_nx(data: dict) -> nx.DiGraph:
    """Handle both networkx >=3.0 ('edges') and <3.0 ('links') node-link format."""
    if 'edges' in data and 'links' not in data:
        data = {**data, 'links': data['edges']}
    return nx.node_link_graph(data)


def get_project_sample_graph(project_id: str) -> nx.DiGraph:
    return _to_nx(current_app.crucible_client.graphs.project(project_id))


def get_sample_lineage_graph(sample_id: str) -> nx.DiGraph:
    data = current_app.crucible_client._request("GET", f"/samples/{sample_id}/sample_graph_cte")
    return _to_nx(data)


def get_entity_graph_nx(entity_id: str) -> nx.DiGraph:
    return _to_nx(current_app.crucible_client.graphs.get(entity_id, recursive=True))
