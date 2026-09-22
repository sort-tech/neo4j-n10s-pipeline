"""scripts/load_sample_bolt.py 테스트.

    python3 -m unittest discover -s tests -v

Neo4j 서버 없이 돌아갑니다. 스크립트가 **어떤 Cypher 와 어떤 파라미터를
보내는지**를 가짜 세션으로 붙잡아 검증합니다. 쿼리가 실제 서버에서
실행되는지는 여기서 확인할 수 없으므로(README 의 한계 항목 참고),
여기서는 구조 · 라벨 보간 · 행 내용 · 주입 차단을 봅니다.
"""

import datetime
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "load_sample_bolt.py"

# scripts/ 는 패키지가 아니므로 파일 경로로 직접 읽어 옵니다.
_spec = importlib.util.spec_from_file_location("load_sample_bolt", SCRIPT)
lsb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lsb)


class FakeSummary:
    def __init__(self):
        self.counters = type("C", (), {"nodes_deleted": 0})()


class FakeResult:
    def __init__(self, record=None):
        self._record = record

    def consume(self):
        return FakeSummary()

    def single(self):
        return self._record


class RecordingSession:
    """보낸 쿼리와 파라미터를 전부 기록하는 가짜 세션."""

    def __init__(self, counts=None):
        self.calls = []
        self.counts = counts or {}

    def run(self, query, **params):
        self.calls.append((" ".join(query.split()), params))
        return FakeResult({"n": self.counts.get(query, 0)})

    def queries_containing(self, needle):
        return [(q, p) for q, p in self.calls if needle in q]


class TestIdentifierGuard(unittest.TestCase):
    """라벨·관계 타입은 쿼리 문자열에 들어가므로 주입을 막아야 한다."""

    def test_accepts_plain_identifiers(self):
        for name in ("Person", "worksFor", "Class", "a_b1"):
            self.assertEqual(lsb.ident(name), name)

    def test_rejects_injection_attempts(self):
        bad = [
            "Person {} ) DETACH DELETE n //",
            "Person`",
            "Person:Other",
            "Person Name",
            "1Person",
            "",
            "n.prop",
            None,
            123,
        ]
        for name in bad:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    lsb.ident(name)

    def test_local_name(self):
        self.assertEqual(lsb.local_name("https://e.org/ns#Person"), "Person")
        self.assertEqual(lsb.local_name("https://e.org/res/alice"), "alice")
        self.assertEqual(lsb.local_name("Person"), "Person")


class TestReadOntology(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = lsb.read_ontology(lsb.ONTOLOGY, lsb.DATA)

    def test_counts_match_the_turtle_files(self):
        p = self.plan
        self.assertEqual(len(p["classes"]), 14)
        self.assertEqual(len(p["object_properties"]), 12)
        self.assertEqual(len(p["data_properties"]), 5)
        self.assertEqual(len(p["sco"]), 10)
        self.assertEqual(len(p["spo"]), 3)
        self.assertEqual(len(p["domain"]), 12)
        self.assertEqual(len(p["range"]), 12)
        self.assertEqual(sum(len(v) for v in p["instances"].values()), 28)
        self.assertEqual(sum(len(v) for v in p["relationships"].values()), 73)

    def test_literals_keep_native_types(self):
        """n10s 와 같게 정수 · 날짜로 저장되어야 한다 (문자열 아님)."""
        rows = [r for rows in self.plan["instances"].values() for r in rows]
        alice = next(r for r in rows if r.get("label") == "Alice Kim")
        self.assertEqual(alice["yearsOfExperience"], 9)
        self.assertIsInstance(alice["yearsOfExperience"], int)

        memory = next(r for r in rows if r.get("label") == "Graph Memory")
        self.assertEqual(memory["startedOn"], datetime.date(2024, 3, 1))

        kaist = next(r for r in rows if r.get("label") == "KAIST")
        self.assertIsInstance(kaist["foundedIn"], int)

    def test_rdfs_label_lands_on_the_label_key(self):
        """viz/model.py 의 NAME_KEYS 가 `label` 을 먼저 봅니다."""
        rows = [r for rows in self.plan["instances"].values() for r in rows]
        self.assertTrue(all("label" in r for r in rows))
        self.assertTrue(all("uri" in r for r in rows))

    def test_object_properties_are_not_stored_as_literals(self):
        """hasSkill 같은 오브젝트 프로퍼티는 관계로만 나가야 한다."""
        rows = [r for rows in self.plan["instances"].values() for r in rows]
        for row in rows:
            self.assertNotIn("hasSkill", row)
            self.assertNotIn("worksFor", row)

    def test_label_groups_are_class_local_names(self):
        groups = set(self.plan["instances"])
        self.assertIn(("Engineer",), groups)
        self.assertIn(("Company",), groups)
        self.assertIn(("ProductProject",), groups)

    def test_relationship_types_are_local_names(self):
        self.assertEqual(
            sorted(self.plan["relationships"]),
            ["collaboratesWith", "contributesTo", "dependsOn", "hasSkill",
             "leads", "ownedBy", "relatedTo", "requiresSkill", "studiesAt",
             "worksFor"],
        )
        self.assertEqual(len(self.plan["relationships"]["hasSkill"]), 22)


class TestWriteQueries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = lsb.read_ontology(lsb.ONTOLOGY, lsb.DATA)

    def _run_all(self):
        session = RecordingSession()
        noop = lambda *_: None
        lsb.write_schema(session, self.plan, noop)
        lsb.write_instances(session, self.plan, noop)
        lsb.write_relationships(session, self.plan, noop)
        return session

    def test_schema_nodes_merge_on_uri_then_set_label(self):
        """라벨까지 포함해 MERGE 하면 기존 노드를 못 찾아 중복이 생깁니다."""
        session = self._run_all()
        q, params = session.queries_containing("SET n:Class")[0]
        self.assertIn("MERGE (n:Resource {uri: row.uri})", q)
        self.assertIn("UNWIND $rows AS row", q)
        self.assertEqual(len(params["rows"]), 14)
        self.assertIn({"uri": "https://sort.tech/ontology/demo#Person",
                       "name": "Person"}, params["rows"])

    def test_hierarchy_edges_match_on_the_right_label(self):
        session = self._run_all()
        sco = session.queries_containing("MERGE (a)-[:SCO]->(b)")[0]
        self.assertIn("MATCH (a:Class {uri: row.child})", sco[0])
        self.assertEqual(len(sco[1]["rows"]), 10)

        spo = session.queries_containing("MERGE (a)-[:SPO]->(b)")[0]
        self.assertIn("MATCH (a:Relationship {uri: row.child})", spo[0])
        self.assertEqual(len(spo[1]["rows"]), 3)

    def test_domain_and_range_are_separate_queries(self):
        """관계 타입은 파라미터로 바인딩할 수 없어 타입마다 쿼리가 나뉩니다."""
        session = self._run_all()
        self.assertEqual(len(session.queries_containing("[:DOMAIN]")), 1)
        self.assertEqual(len(session.queries_containing("[:RANGE]")), 1)

    def test_instances_are_grouped_by_label_set(self):
        session = self._run_all()
        instance_queries = session.queries_containing("n += row")
        self.assertEqual(len(instance_queries), len(self.plan["instances"]))
        total = sum(len(p["rows"]) for _, p in instance_queries)
        self.assertEqual(total, 28)
        engineer = [q for q, _ in instance_queries if "SET n:Engineer," in q]
        self.assertEqual(len(engineer), 1)

    def test_one_query_per_relationship_type(self):
        session = self._run_all()
        rel_queries = session.queries_containing("MATCH (a:Resource {uri: row.source})")
        self.assertEqual(len(rel_queries), len(self.plan["relationships"]))
        total = sum(len(p["rows"]) for _, p in rel_queries)
        self.assertEqual(total, 73)
        works = [(q, p) for q, p in rel_queries if "[:worksFor]" in q]
        self.assertEqual(len(works), 1)
        self.assertEqual(len(works[0][1]["rows"]), 7)

    def test_every_query_passes_data_as_parameters(self):
        """행 데이터는 절대 쿼리 문자열에 끼워 넣지 않는다."""
        session = self._run_all()
        for query, params in session.calls:
            self.assertIn("rows", params)
            self.assertNotIn("sort.tech", query)

    def test_all_referenced_uris_exist_as_nodes(self):
        """MATCH 로 잇는 관계이므로, 없는 uri 를 참조하면 조용히 누락됩니다."""
        known = {r["uri"] for rows in self.plan["instances"].values()
                 for r in rows}
        for kind, rows in self.plan["relationships"].items():
            for row in rows:
                self.assertIn(row["source"], known, f"{kind} source")
                self.assertIn(row["target"], known, f"{kind} target")

        classes = {c["uri"] for c in self.plan["classes"]}
        props = {p["uri"] for p in self.plan["object_properties"]}
        for row in self.plan["sco"]:
            self.assertIn(row["child"], classes)
            self.assertIn(row["parent"], classes)
        for row in self.plan["spo"]:
            self.assertIn(row["child"], props)
            self.assertIn(row["parent"], props)
        for key in ("domain", "range"):
            for row in self.plan[key]:
                self.assertIn(row["prop"], props)
                self.assertIn(row["cls"], classes)


class TestVerifyQueries(unittest.TestCase):
    def test_each_verify_query_is_standalone(self):
        """집계를 체이닝하지 않으므로 빈 DB 에서도 각각 한 행을 돌려준다."""
        session = RecordingSession()
        counts = lsb.verify(session, lambda *_: None)
        self.assertEqual(len(session.calls), len(lsb.VERIFY_QUERIES))
        self.assertEqual(set(counts), {name for name, _ in lsb.VERIFY_QUERIES})
        for query in (q for _, q in lsb.VERIFY_QUERIES):
            self.assertIn("count(", query)

    def test_instance_counts_exclude_schema_nodes(self):
        for name, query in lsb.VERIFY_QUERIES:
            if name in ("개체", "개체 간 관계"):
                self.assertIn("NOT", query)
                self.assertIn(":Class", query)


class TestShapeMatchesVizExpectations(unittest.TestCase):
    """이 스크립트로 넣은 데이터를 viz 가 읽을 수 있어야 한다.

    viz/sources.py 의 Cypher 가 기대하는 라벨 · 관계 이름과 이 스크립트가
    쓰는 이름이 어긋나면 그림이 비게 되므로 양쪽을 맞춰 둡니다.
    """

    def test_schema_labels_and_rels_line_up(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from viz import sources

        # (:Property) 는 스키마 뷰가 읽지 않고 인스턴스 쿼리에서 제외
        # 조건으로만 쓰입니다. 그래서 전체 쿼리를 합쳐 놓고 봅니다.
        all_queries = "".join((
            sources.Q_CLASSES, sources.Q_OBJECT_PROPERTIES,
            sources.Q_CLASS_HIERARCHY, sources.Q_INSTANCES,
            sources.Q_INSTANCE_EDGES,
        ))
        for needle in (":Class", ":Relationship", ":Property",
                       ":SCO", ":DOMAIN", ":RANGE", ":Resource"):
            self.assertIn(needle, all_queries)

        session = RecordingSession()
        plan = lsb.read_ontology(lsb.ONTOLOGY, lsb.DATA)
        lsb.write_schema(session, plan, lambda *_: None)
        written = " ".join(q for q, _ in session.calls)
        for needle in ("SET n:Class", "SET n:Relationship", "SET n:Property",
                       "[:SCO]", "[:DOMAIN]", "[:RANGE]", "[:SPO]"):
            self.assertIn(needle, written)

    def test_instances_carry_resource_label(self):
        """viz 의 인스턴스 쿼리가 (n:Resource) 로 시작합니다."""
        session = RecordingSession()
        plan = lsb.read_ontology(lsb.ONTOLOGY, lsb.DATA)
        lsb.write_instances(session, plan, lambda *_: None)
        for query, _ in session.calls:
            self.assertIn("MERGE (n:Resource {uri: row.uri})", query)


# --------------------------------------------------------------- 왕복 검증

class SimulatedStore:
    """이 스크립트의 쓰기를 적용한 뒤 viz 의 읽기 쿼리에 답하는 가짜 Neo4j.

    실제 서버를 대신할 수는 없지만(쿼리 실행 자체는 검증되지 않습니다),
    **넣는 쪽과 읽는 쪽의 라벨 · 관계 · 프로퍼티 이름이 맞물리는지**는
    여기서 확인됩니다. 어긋나면 그림이 조용히 비어 버리는 종류의 버그라
    잡아 둘 값이 있습니다.
    """

    def __init__(self, plan):
        self.nodes = {}     # uri -> {"labels": set, "props": dict}
        self.rels = []      # (source_uri, type, target_uri)
        self._apply(plan)

    def _node(self, uri):
        return self.nodes.setdefault(uri, {"labels": {"Resource"}, "props": {}})

    def _apply(self, plan):
        for label, key in (("Class", "classes"),
                           ("Relationship", "object_properties"),
                           ("Property", "data_properties")):
            for row in plan[key]:
                node = self._node(row["uri"])
                node["labels"].add(label)
                node["props"].update({"uri": row["uri"], "name": row["name"]})

        for rel, key in (("SCO", "sco"), ("SPO", "spo")):
            for row in plan[key]:
                self.rels.append((row["child"], rel, row["parent"]))
        for rel, key in (("DOMAIN", "domain"), ("RANGE", "range")):
            for row in plan[key]:
                self.rels.append((row["prop"], rel, row["cls"]))

        for labels, rows in plan["instances"].items():
            for row in rows:
                node = self._node(row["uri"])
                node["labels"].update(labels)
                node["props"].update(row)

        for kind, rows in plan["relationships"].items():
            for row in rows:
                self.rels.append((row["source"], kind, row["target"]))

    # --- viz/sources.py 의 읽기 쿼리에 대한 응답
    SCHEMA = {"Class", "Relationship", "Property"}

    def _is_schema(self, uri):
        return bool(self.nodes[uri]["labels"] & self.SCHEMA)

    def _targets(self, uri, rel):
        return [t for s, r, t in self.rels if s == uri and r == rel]

    def run(self, query, **params):
        from viz import sources

        q = query.strip()
        if q == sources.Q_CLASSES.strip():
            return FakeIter([
                {"id": uri, "props": n["props"],
                 "supers": self._targets(uri, "SCO")}
                for uri, n in self.nodes.items() if "Class" in n["labels"]
            ])
        if q == sources.Q_OBJECT_PROPERTIES.strip():
            rows = []
            for uri, n in self.nodes.items():
                if "Relationship" not in n["labels"]:
                    continue
                for dom in self._targets(uri, "DOMAIN"):
                    for rng in self._targets(uri, "RANGE"):
                        rows.append({"props": n["props"],
                                     "domain": dom, "range": rng})
            return FakeIter(rows)
        if q == sources.Q_CLASS_HIERARCHY.strip():
            return FakeIter([
                {"child": self.nodes[s]["props"],
                 "parent": self.nodes[t]["props"]}
                for s, r, t in self.rels
                if r == "SCO" and "Class" in self.nodes[s]["labels"]
            ])
        if q == sources.Q_INSTANCES.strip():
            return FakeIter([
                {"id": uri, "labels": sorted(n["labels"]), "props": n["props"]}
                for uri, n in self.nodes.items() if not self._is_schema(uri)
            ])
        if q == sources.Q_INSTANCE_EDGES.strip():
            return FakeIter([
                {"source": s, "kind": r, "target": t}
                for s, r, t in self.rels
                if s in self.nodes and t in self.nodes
                and not self._is_schema(s) and not self._is_schema(t)
            ])
        raise AssertionError(f"처리하지 않은 쿼리:\n{query}")


class FakeIter:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class TestRoundTrip(unittest.TestCase):
    """plain-Cypher 적재 -> viz 읽기 가 TTL 경로와 같은 그래프를 내는지."""

    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(ROOT))
        from viz import sources

        cls.sources = sources
        cls.store = SimulatedStore(lsb.read_ontology(lsb.ONTOLOGY, lsb.DATA))

    def test_instance_graph_matches_the_ttl_path(self):
        from_bolt = self.sources.neo4j_instances(self.store)
        from_ttl = self.sources.ttl_instances(lsb.ONTOLOGY, lsb.DATA)

        self.assertEqual(sorted(n.name for n in from_bolt.nodes),
                         sorted(n.name for n in from_ttl.nodes))
        self.assertEqual({n.name: n.root for n in from_bolt.nodes},
                         {n.name: n.root for n in from_ttl.nodes})
        self.assertEqual({n.name: n.classes for n in from_bolt.nodes},
                         {n.name: n.classes for n in from_ttl.nodes})
        self.assertEqual(sorted(e.kind for e in from_bolt.edges),
                         sorted(e.kind for e in from_ttl.edges))
        self.assertEqual(from_bolt.roots(), from_ttl.roots())

    def test_schema_graph_matches_the_ttl_path(self):
        from_bolt = self.sources.neo4j_schema(self.store)
        from_ttl = self.sources.ttl_schema(lsb.ONTOLOGY)

        self.assertEqual(sorted(n.name for n in from_bolt.nodes),
                         sorted(n.name for n in from_ttl.nodes))
        self.assertEqual({n.name: n.root for n in from_bolt.nodes},
                         {n.name: n.root for n in from_ttl.nodes})
        self.assertEqual(sorted(e.kind for e in from_bolt.edges),
                         sorted(e.kind for e in from_ttl.edges))

    def test_the_drawing_actually_renders(self):
        """비어 있지 않은 그림이 나오는지까지 확인한다."""
        from viz import layout
        from viz.render import Renderer

        graph = self.sources.neo4j_instances(self.store)
        layout.force_layout(graph, 1180, 760, iterations=60)
        html = Renderer(graph).to_html()
        self.assertIn("Alice Kim", html)
        self.assertIn('data-kind="worksFor"', html)
        self.assertEqual(html.count('class="node"'), 28)


if __name__ == "__main__":
    unittest.main()
