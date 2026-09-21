"""viz 패키지 테스트.

    python3 -m unittest discover -s tests -v

Neo4j 서버 없이 전부 돌아갑니다. Neo4j 경로는 n10s 가 내놓는 레코드
모양을 흉내낸 가짜 세션으로 검증합니다 — 쿼리 결과를 Graph 로 옮기는
변환(네임스페이스 접두사 제거, 표시 이름 선택, 최상위 클래스 확정)이
실제로 깨지기 쉬운 부분이기 때문입니다.
"""

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from viz import layout, sources  # noqa: E402
from viz.model import Edge, Graph, Node, pick_name, resolve_roots  # noqa: E402
from viz.palette import CLASS_ORDER, SERIES, assign_colors, assign_shapes  # noqa: E402
from viz.render import LABEL_LIMIT, Renderer, radius_fn  # noqa: E402

ONTOLOGY = ROOT / "ontology" / "sample-ontology.ttl"
DATA = ROOT / "ontology" / "sample-data.ttl"
SVG_NS = "{http://www.w3.org/2000/svg}"


class FakeResult:
    """session.run() 이 돌려주는 것 중 테스트가 쓰는 부분만."""

    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def single(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """쿼리 문자열의 특징으로 준비된 레코드를 돌려주는 가짜 세션."""

    def __init__(self, table):
        self.table = table
        self.seen = []

    def run(self, query, **params):
        self.seen.append(query)
        for marker, rows in self.table.items():
            if marker in query:
                return FakeResult(rows)
        raise AssertionError(f"준비되지 않은 쿼리:\n{query}")


# n10s 를 기본값(handleVocabUris='SHORTEN')으로 적재했을 때의 모양.
# 라벨과 프로퍼티 키에 `ns0__` 접두사가 붙습니다.
SHORTEN_TABLE = {
    "MATCH (c:Class)-[:SCO]->(p:Class)": [
        {"child": {"ns0__name": "Engineer"}, "parent": {"ns0__name": "Employee"}},
        {"child": {"ns0__name": "Employee"}, "parent": {"ns0__name": "Person"}},
        {"child": {"ns0__name": "Company"}, "parent": {"ns0__name": "Organization"}},
    ],
    "MATCH (n:Resource)": [
        {"id": "4:a:1", "labels": ["Resource", "ns0__Engineer"],
         "props": {"ns0__label": "Alice Kim", "ns0__email": "alice@sort.tech",
                   "uri": "https://sort.tech/resource/alice"}},
        {"id": "4:a:2", "labels": ["Resource", "ns0__Company"],
         "props": {"ns0__label": "SORT Tech",
                   "uri": "https://sort.tech/resource/sortTech"}},
        # rdfs:label 이 없는 노드 — uri 의 로컬 이름으로 떨어져야 합니다.
        {"id": "4:a:3", "labels": ["Resource", "ns0__Employee"],
         "props": {"uri": "https://sort.tech/resource/nameless"}},
    ],
    "MATCH (a:Resource)-[r]->(b:Resource)": [
        {"source": "4:a:1", "kind": "ns0__worksFor", "target": "4:a:2"},
        # 양 끝 중 한쪽이 노드 집합에 없는 간선 — 버려져야 합니다.
        {"source": "4:a:1", "kind": "ns0__worksFor", "target": "4:a:99"},
    ],
    "MATCH (c:Class)\nOPTIONAL MATCH": [
        {"id": "c1", "props": {"ns0__name": "Person"}, "supers": []},
        {"id": "c2", "props": {"ns0__name": "Employee"}, "supers": ["c1"]},
        {"id": "c3", "props": {"ns0__name": "Organization"}, "supers": []},
    ],
    "MATCH (r:Relationship)-[:DOMAIN]->": [
        {"props": {"ns0__name": "worksFor"}, "domain": "c2", "range": "c3"},
    ],
}


class TestPalette(unittest.TestCase):
    def test_four_slots_only(self):
        """색상 슬롯은 4개 — all-pairs 검증을 통과한 상한입니다."""
        self.assertEqual(len(SERIES), 4)
        self.assertEqual(len(CLASS_ORDER), 4)
        self.assertEqual(set(SERIES), set(CLASS_ORDER))

    def test_fixed_order_survives_filtering(self):
        """클래스 수가 줄어도 남은 클래스의 색은 그대로여야 한다."""
        full = assign_colors(list(CLASS_ORDER))
        subset = assign_colors(["Person", "Skill"])
        self.assertEqual(full["Person"], subset["Person"])
        self.assertEqual(full["Skill"], subset["Skill"])

    def test_fifth_class_folds_to_neutral(self):
        """5번째 최상위 클래스는 새 색을 만들지 않고 중립색으로 접힌다."""
        colors = assign_colors(list(CLASS_ORDER) + ["Event"])
        self.assertEqual(colors["Event"], ("#898781", "#898781"))
        for name in CLASS_ORDER:
            self.assertEqual(colors[name], SERIES[name])

    def test_shapes_are_distinct(self):
        """색이 CVD 경고 구간에 있으므로 형태가 서로 달라야 한다."""
        shapes = assign_shapes(list(CLASS_ORDER))
        self.assertEqual(len(set(shapes.values())), 4)


class TestModel(unittest.TestCase):
    def test_pick_name_prefers_label_then_uri(self):
        self.assertEqual(pick_name({"label": "Alice"}, "x"), "Alice")
        self.assertEqual(pick_name({"ns0__label": "Bob"}, "x"), "Bob")
        self.assertEqual(pick_name({"uri": "http://e.org/ns#Thing"}, "x"), "Thing")
        self.assertEqual(pick_name({}, "fallback"), "fallback")
        self.assertEqual(pick_name({"label": ["First", "Second"]}, "x"), "First")

    def test_resolve_roots_climbs_hierarchy(self):
        nodes = [Node(id="1", name="a", classes=("Engineer",))]
        resolve_roots(nodes, {"Engineer": "Employee", "Employee": "Person"})
        self.assertEqual(nodes[0].root, "Person")

    def test_resolve_roots_survives_a_cycle(self):
        nodes = [Node(id="1", name="a", classes=("A",))]
        resolve_roots(nodes, {"A": "B", "B": "A"})
        self.assertIn(nodes[0].root, {"A", "B"})

    def test_drop_dangling_edges(self):
        g = Graph(nodes=[Node(id="1", name="a")],
                  edges=[Edge("1", "missing", "rel")])
        self.assertEqual(g.drop_dangling_edges().edges, [])


class TestTurtleSource(unittest.TestCase):
    def test_schema_matches_the_ontology_file(self):
        g = sources.ttl_schema(ONTOLOGY)
        self.assertEqual(len(g.nodes), 14)
        # 10 subClassOf + 12 오브젝트 프로퍼티
        self.assertEqual(sum(1 for e in g.edges if e.kind == "SCO"), 10)
        self.assertEqual(sum(1 for e in g.edges if e.kind != "SCO"), 12)
        self.assertEqual(g.roots(), ["Organization", "Person", "Project", "Skill"])

    def test_symmetric_properties_become_self_loops(self):
        """domain 과 range 가 같은 프로퍼티는 자기 참조 간선이 된다."""
        g = sources.ttl_schema(ONTOLOGY)
        loops = {e.kind for e in g.edges if e.source == e.target}
        self.assertEqual(loops, {"collaboratesWith", "dependsOn", "relatedTo"})

    def test_instances_match_the_data_file(self):
        g = sources.ttl_instances(ONTOLOGY, DATA)
        self.assertEqual(len(g.nodes), 28)
        self.assertEqual(len(g.edges), 73)
        by_name = {n.name: n for n in g.nodes}
        # 하위 클래스 인스턴스가 최상위 클래스로 올라붙어야 한다.
        self.assertEqual(by_name["Alice Kim"].classes, ("Engineer",))
        self.assertEqual(by_name["Alice Kim"].root, "Person")
        self.assertEqual(by_name["Graph Memory"].root, "Project")
        self.assertEqual(by_name["Python"].root, "Skill")
        self.assertEqual(by_name["KAIST"].root, "Organization")
        # 리터럴 프로퍼티는 툴팁용으로 실려 온다.
        self.assertEqual(by_name["Alice Kim"].props["yearsOfExperience"], "9")

    def test_every_root_class_is_populated(self):
        g = sources.ttl_instances(ONTOLOGY, DATA)
        self.assertEqual(g.roots(), ["Organization", "Person", "Project", "Skill"])


class TestNeo4jSource(unittest.TestCase):
    """handleVocabUris='SHORTEN' 로 적재된 DB 도 그대로 읽혀야 한다."""

    def test_instances_strip_namespace_prefixes(self):
        session = FakeSession(SHORTEN_TABLE)
        g = sources.neo4j_instances(session)
        self.assertEqual(len(g.nodes), 3)
        by_name = {n.name: n for n in g.nodes}
        self.assertEqual(by_name["Alice Kim"].classes, ("Engineer",))
        self.assertEqual(by_name["Alice Kim"].root, "Person")
        self.assertEqual(by_name["Alice Kim"].props["email"], "alice@sort.tech")
        self.assertEqual(by_name["SORT Tech"].root, "Organization")
        # rdfs:label 이 없으면 uri 의 로컬 이름으로.
        self.assertIn("nameless", by_name)
        # 관계 타입도 접두사가 벗겨지고, 매달린 간선은 버려진다.
        self.assertEqual([e.kind for e in g.edges], ["worksFor"])

    def test_schema_builds_hierarchy_and_property_edges(self):
        session = FakeSession(SHORTEN_TABLE)
        g = sources.neo4j_schema(session)
        self.assertEqual({n.name for n in g.nodes},
                         {"Person", "Employee", "Organization"})
        sco = [(e.source, e.target) for e in g.edges if e.kind == "SCO"]
        self.assertEqual(sco, [("c2", "c1")])
        prop = [e for e in g.edges if e.kind == "worksFor"]
        self.assertEqual(len(prop), 1)
        self.assertTrue(prop[0].dashed)
        # Employee 는 SCO 를 타고 Person 계열로 색이 정해져야 한다.
        self.assertEqual({n.name: n.root for n in g.nodes}["Employee"], "Person")


class TestLayout(unittest.TestCase):
    def setUp(self):
        self.g = sources.ttl_instances(ONTOLOGY, DATA)

    def test_force_layout_is_deterministic(self):
        a = sources.ttl_instances(ONTOLOGY, DATA)
        b = sources.ttl_instances(ONTOLOGY, DATA)
        layout.force_layout(a, 1180, 760, iterations=120)
        layout.force_layout(b, 1180, 760, iterations=120)
        self.assertEqual([(round(n.x, 6), round(n.y, 6)) for n in a.nodes],
                         [(round(n.x, 6), round(n.y, 6)) for n in b.nodes])

    def test_everything_stays_on_canvas(self):
        layout.force_layout(self.g, 1180, 760, iterations=120)
        for n in self.g.nodes:
            self.assertGreaterEqual(n.x, 0)
            self.assertGreaterEqual(n.y, 0)
            self.assertLessEqual(n.x, 1180)
            self.assertLessEqual(n.y, 760)

    def test_layered_layout_puts_roots_on_top(self):
        g = sources.ttl_schema(ONTOLOGY)
        layout.layered_layout(g, 1180, 560)
        depths = {n.name: n.depth for n in g.nodes}
        self.assertEqual(depths["Person"], 0)
        self.assertEqual(depths["Employee"], 1)
        self.assertEqual(depths["Engineer"], 2)
        rows = {n.depth: n.y for n in g.nodes}
        self.assertLess(rows[0], rows[1])
        self.assertLess(rows[1], rows[2])

    def test_relax_overlaps_separates_labels(self):
        """라벨 상시 노출이 대비 완화의 조건이므로 겹침이 남으면 안 된다."""
        layout.force_layout(self.g, 1180, 760, iterations=300)
        radius_of = radius_fn(self.g)
        before = self._overlaps(self.g, radius_of)
        layout.relax_overlaps(self.g, radius_of, label_limit=LABEL_LIMIT,
                              bounds=(14, 46, 1166, 734))
        after = self._overlaps(self.g, radius_of)
        self.assertLess(after, before)
        self.assertEqual(after, 0)

    @staticmethod
    def _overlaps(graph, radius_of, char_w=6.3):
        def box(node):
            chars = min(len(node.name), LABEL_LIMIT)
            return (max(radius_of(node) + 2.0, 0.5 * char_w * chars + 2.0),
                    radius_of(node) + 15.0)

        count = 0
        nodes = graph.nodes
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                ha, hb = box(a), box(b)
                if (abs(b.x - a.x) < ha[0] + hb[0]
                        and abs(b.y - a.y) < ha[1] + hb[1]):
                    count += 1
        return count


class TestRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = sources.ttl_schema(ONTOLOGY)
        layout.layered_layout(cls.schema, 1180, 560)
        cls.instances = sources.ttl_instances(ONTOLOGY, DATA)
        layout.force_layout(cls.instances, 1180, 760, iterations=200)

    def test_standalone_svg_is_well_formed(self):
        svg = Renderer(self.schema, height=560, edge_labels=True).to_svg()
        root = ET.fromstring(svg)
        self.assertEqual(root.tag, f"{SVG_NS}svg")
        marks = root.findall(f".//{SVG_NS}g[@class='node']")
        self.assertEqual(len(marks), 14)

    def test_every_node_gets_a_mark_and_a_label(self):
        r = Renderer(self.instances)
        root = ET.fromstring(r.svg_body(interactive=True))
        nodes = root.findall(f".//{SVG_NS}g[@class='node']")
        labels = root.findall(f".//{SVG_NS}text[@class='label']")
        self.assertEqual(len(nodes), len(self.instances.nodes))
        self.assertEqual(len(labels), len(self.instances.nodes))
        # 모든 마크는 class="mark" 여야 한다. 채움색 규칙이 여기에만
        # 걸리므로, 빠지면 형태 채널이 투명 히트 타깃에 가려집니다.
        for node in nodes:
            kinds = [child.get("class") for child in node]
            self.assertIn("mark", kinds)
            self.assertIn("hit", kinds)

    def test_shape_channel_actually_varies(self):
        """색이 CVD 경고 구간이라 형태가 실제로 달라야 한다."""
        root = ET.fromstring(Renderer(self.instances).svg_body())
        shapes = set()
        for node in root.findall(f".//{SVG_NS}g[@class='node']"):
            mark = node[0]
            shapes.add(mark.tag.replace(SVG_NS, "")
                       if mark.tag.endswith("circle")
                       else mark.get("d", "")[:1] + str(len(mark.get("d", ""))))
        self.assertGreaterEqual(len(shapes), 4)

    def test_all_edges_are_drawn_including_self_loops(self):
        r = Renderer(self.schema, height=560, edge_labels=True)
        root = ET.fromstring(r.svg_body())
        paths = root.findall(f".//{SVG_NS}path[@class='edge']")
        self.assertEqual(len(paths), len(self.schema.edges))

    def test_hierarchy_edges_are_not_labelled(self):
        """SCO 를 열 번 반복해 적지 않는다 (선별적 직접 라벨)."""
        r = Renderer(self.schema, height=560, edge_labels=True)
        root = ET.fromstring(r.svg_body())
        kinds = [t.get("data-kind")
                 for t in root.findall(f".//{SVG_NS}text[@class='edge-label']")]
        self.assertNotIn("SCO", kinds)
        self.assertEqual(len(kinds), 12)
        self.assertIn("collaboratesWith", kinds)

    def test_html_is_self_contained(self):
        doc = Renderer(self.instances).to_html()
        self.assertNotIn("http://", doc.replace('xmlns="http://www.w3.org/2000/svg"', ""))
        self.assertNotIn("https://cdn", doc)
        self.assertNotIn("<script src", doc)

    def test_html_has_legend_filters_and_table(self):
        doc = Renderer(self.instances).to_html()
        for root in self.instances.roots():
            self.assertIn(f">{root}</span>", doc)          # 범례
        for kind in self.instances.kinds():
            self.assertIn(f'data-kind="{kind}"', doc)      # 필터 칩
        self.assertIn("노드 표로 보기", doc)                 # 표 대안
        self.assertIn('data-theme="dark"', doc)            # 다크 모드

    def test_dark_mode_is_declared_under_both_scopes(self):
        """OS 설정과 토글 양쪽에서 다크가 적용되어야 한다."""
        doc = Renderer(self.instances).to_html()
        self.assertIn("@media (prefers-color-scheme: dark)", doc)
        self.assertIn(':root:where(:not([data-theme="light"]))', doc)
        self.assertIn(':root[data-theme="dark"]', doc)

    def test_long_names_are_trimmed(self):
        doc = Renderer(self.instances).to_html()
        self.assertIn("Seoul National Univer…", doc)


if __name__ == "__main__":
    unittest.main()
