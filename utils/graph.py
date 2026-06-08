import networkx as nx

from utils.auth import get_user_client


def get_entity_graph_nx(entity_id: str) -> nx.DiGraph:
    return get_user_client().graphs.get(entity_id, recursive=True, as_networkx=True)


def get_project_graph(project_id: str) -> nx.DiGraph:
    return get_user_client().graphs.project(project_id, as_networkx=True)
