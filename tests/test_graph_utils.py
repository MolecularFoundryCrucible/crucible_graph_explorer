import networkx as nx
import pytest


def _build_path(G, src, dst, names_by_id):
    """Mirrors the path-building logic in routes/samples.py after the fix."""
    try:
        path = nx.shortest_path(G, src, dst)
        return [names_by_id.get(x, x) for x in path]
    except nx.NetworkXNoPath:
        return None


def test_shortest_path_returns_correct_path():
    G = nx.DiGraph()
    G.add_edges_from([('a', 'b'), ('b', 'c')])
    names = {'a': 'Alpha', 'b': 'Beta', 'c': 'Gamma'}
    result = _build_path(G, 'a', 'c', names)
    assert result == ['Alpha', 'Beta', 'Gamma']


def test_shortest_path_returns_none_when_disconnected():
    G = nx.DiGraph()
    G.add_nodes_from(['a', 'b'])
    result = _build_path(G, 'a', 'b', {})
    assert result is None


def test_shortest_path_direct_edge():
    G = nx.DiGraph()
    G.add_edge('parent', 'child')
    names = {'parent': 'Parent Sample', 'child': 'Child Sample'}
    result = _build_path(G, 'parent', 'child', names)
    assert result == ['Parent Sample', 'Child Sample']
