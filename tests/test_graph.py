from codegraph.graph import build_graph, graph_stats
from codegraph.parser import parse_repo


def test_build_graph_matches_parse_result(make_repo):
    repo = make_repo({
        "a.py": '''
class Base:
    def run(self):
        pass


class Child(Base):
    def go(self):
        return self.run()
'''
    })
    result = parse_repo(repo)
    g = build_graph(result)

    assert set(g.nodes) == set(result.nodes)
    assert g.number_of_edges() == len(result.edges)
    assert g.nodes["a.Base"]["kind"] == "class"


def test_graph_stats_counts_by_kind(make_repo):
    repo = make_repo({
        "a.py": "def f():\n    pass\n\n\nclass C:\n    pass\n",
    })
    g = build_graph(parse_repo(repo))
    stats = graph_stats(g)

    assert stats["nodes_by_kind"] == {"module": 1, "function": 1, "class": 1}
    assert stats["num_nodes"] == 3
