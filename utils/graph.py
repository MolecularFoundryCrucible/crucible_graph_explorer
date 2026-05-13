import networkx as nx
from utils.auth import get_user_client


def _to_nx(data: dict) -> nx.DiGraph:
    """Handle both networkx >=3.0 ('edges') and <3.0 ('links') node-link format."""
    if 'edges' in data and 'links' not in data:
        data = {**data, 'links': data['edges']}
    return nx.node_link_graph(data)


def get_entity_graph_nx(entity_id: str) -> nx.DiGraph:
    return _to_nx(get_user_client().graphs.get(entity_id, recursive=True))


def get_project_graph(project_id: str) -> nx.DiGraph:
    return _to_nx(get_user_client().graphs.project(project_id))
