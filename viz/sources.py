"""그래프 데이터 소스.

* neo4j 소스 — n10s 로 적재된 Neo4j 를 읽습니다. 기본 경로입니다.
* ttl 소스   — ontology/*.ttl 을 직접 읽습니다. Neo4j 없이 그림만 확인
  하거나 CI 에서 렌더러를 검증할 때 씁니다(rdflib 필요).

Cypher 쿼리는 `handleVocabUris` 설정에 의존하지 않도록 썼습니다. 라벨과
프로퍼티 키를 그대로 받아 파이썬에서 `ns0__` 접두사를 떼기 때문에
'IGNORE' 로 적재했든 'SHORTEN' 으로 적재했든 같은 그림이 나옵니다.
"""

from .model import Edge, Graph, Node, local_name, normalize_key, pick_name, resolve_roots


def _not_schema(var):
    """스키마 노드(:Class/:Relationship/:Property)를 제외하는 조건절."""
    return " AND ".join(f"NOT {var}:{label}"
                        for label in ("Class", "Relationship", "Property"))

Q_CLASSES = """
MATCH (c:Class)
OPTIONAL MATCH (c)-[:SCO]->(sup:Class)
RETURN elementId(c)        AS id,
       properties(c)       AS props,
       collect(elementId(sup)) AS supers
"""

Q_OBJECT_PROPERTIES = """
MATCH (r:Relationship)-[:DOMAIN]->(d:Class)
MATCH (r)-[:RANGE]->(g:Class)
RETURN properties(r)  AS props,
       elementId(d)   AS domain,
       elementId(g)   AS range
"""

Q_CLASS_HIERARCHY = """
MATCH (c:Class)-[:SCO]->(p:Class)
RETURN properties(c) AS child, properties(p) AS parent
"""

Q_INSTANCES = f"""
MATCH (n:Resource)
WHERE {_not_schema('n')}
RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props
"""

Q_INSTANCE_EDGES = f"""
MATCH (a:Resource)-[r]->(b:Resource)
WHERE ({_not_schema('a')})
  AND ({_not_schema('b')})
RETURN elementId(a) AS source, type(r) AS kind, elementId(b) AS target
"""


def _clean_props(props):
    return {normalize_key(k): v for k, v in props.items()}


# ----------------------------------------------------------------- neo4j

def neo4j_schema(session):
    """T-Box — 클래스 계층 + 오브젝트 프로퍼티의 domain/range."""
    nodes, edges = [], []
    parent_of, name_of = {}, {}

    for rec in session.run(Q_CLASSES):
        props = _clean_props(rec["props"])
        name = pick_name(props, local_name(rec["id"]))
        name_of[rec["id"]] = name
        nodes.append(Node(id=rec["id"], name=name, classes=(name,), props=props))
        for sup in rec["supers"]:
            if sup is not None:
                edges.append(Edge(source=rec["id"], target=sup, kind="SCO"))

    # 색·형태를 결정할 최상위 클래스는 SCO 를 끝까지 따라가 정합니다.
    for edge in edges:
        if edge.kind == "SCO":
            parent_of[name_of[edge.source]] = name_of[edge.target]
    resolve_roots(nodes, parent_of)

    for rec in session.run(Q_OBJECT_PROPERTIES):
        props = _clean_props(rec["props"])
        edges.append(Edge(source=rec["domain"],
                          target=rec["range"],
                          kind=pick_name(props, "property"),
                          dashed=True))

    graph = Graph(nodes=nodes, edges=edges,
                  title="샘플 온톨로지 스키마 (T-Box)",
                  subtitle="실선 = rdfs:subClassOf · 점선 = 오브젝트 프로퍼티 "
                           "(domain → range)")
    return graph.drop_dangling_edges()


def neo4j_instances(session):
    """A-Box — 개체와 개체 사이의 관계."""
    parent_of = {}
    for rec in session.run(Q_CLASS_HIERARCHY):
        child = pick_name(_clean_props(rec["child"]), "")
        par = pick_name(_clean_props(rec["parent"]), "")
        if child and par:
            parent_of[child] = par

    nodes = []
    for rec in session.run(Q_INSTANCES):
        props = _clean_props(rec["props"])
        classes = tuple(sorted(
            normalize_key(l) for l in rec["labels"] if normalize_key(l) != "Resource"
        ))
        nodes.append(Node(id=rec["id"],
                          name=pick_name(props, local_name(rec["id"])),
                          classes=classes,
                          props=props))
    resolve_roots(nodes, parent_of)

    # 관계 타입도 라벨과 마찬가지로 접두사를 뗍니다. 안 그러면
    # 필터 칩과 간선 라벨에 `ns0__worksFor` 가 그대로 노출됩니다.
    edges = [Edge(source=rec["source"], target=rec["target"],
                  kind=normalize_key(rec["kind"]))
             for rec in session.run(Q_INSTANCE_EDGES)]

    graph = Graph(nodes=nodes, edges=edges,
                  title="샘플 온톨로지 인스턴스 그래프 (A-Box)",
                  subtitle="색과 형태 = 최상위 클래스 · 노드에 올리면 프로퍼티 표시")
    return graph.drop_dangling_edges()


# ------------------------------------------------------------------- ttl

def _rdflib_graphs(onto_path, data_path=None):
    from rdflib import Graph as RDFGraph

    onto = RDFGraph()
    onto.parse(str(onto_path), format="turtle")
    data = None
    if data_path is not None:
        data = RDFGraph()
        data.parse(str(data_path), format="turtle")
    return onto, data


def _parent_map(onto):
    from rdflib import RDFS

    return {local_name(str(s)): local_name(str(o))
            for s, o in onto.subject_objects(RDFS.subClassOf)}


def ttl_schema(onto_path):
    """Neo4j 없이 온톨로지 파일에서 T-Box 그래프를 만든다."""
    from rdflib import OWL, RDF, RDFS

    onto, _ = _rdflib_graphs(onto_path)
    parent_of = _parent_map(onto)

    nodes, edges = [], []
    for cls in sorted(onto.subjects(RDF.type, OWL.Class), key=str):
        name = local_name(str(cls))
        label = onto.value(cls, RDFS.label)
        comment = onto.value(cls, RDFS.comment)
        props = {"name": name, "uri": str(cls)}
        if label:
            props["label"] = str(label)
        if comment:
            props["comment"] = str(comment)
        nodes.append(Node(id=str(cls), name=str(label) if label else name,
                          classes=(name,), props=props))

    for cls, sup in onto.subject_objects(RDFS.subClassOf):
        edges.append(Edge(source=str(cls), target=str(sup), kind="SCO"))

    for prop in sorted(onto.subjects(RDF.type, OWL.ObjectProperty), key=str):
        dom = onto.value(prop, RDFS.domain)
        rng = onto.value(prop, RDFS.range)
        if dom is None or rng is None:
            continue
        edges.append(Edge(source=str(dom), target=str(rng),
                          kind=local_name(str(prop)), dashed=True))

    resolve_roots(nodes, parent_of)
    graph = Graph(nodes=nodes, edges=edges,
                  title="샘플 온톨로지 스키마 (T-Box)",
                  subtitle="실선 = rdfs:subClassOf · 점선 = 오브젝트 프로퍼티 "
                           "(domain → range)")
    return graph.drop_dangling_edges()


def ttl_instances(onto_path, data_path):
    """Neo4j 없이 데이터 파일에서 A-Box 그래프를 만든다."""
    from rdflib import OWL, RDF, RDFS, URIRef

    onto, data = _rdflib_graphs(onto_path, data_path)
    parent_of = _parent_map(onto)
    object_props = {p for p in onto.subjects(RDF.type, OWL.ObjectProperty)}

    nodes = []
    for subj in sorted(set(data.subjects(RDF.type, None)), key=str):
        classes = tuple(sorted(local_name(str(t))
                               for t in data.objects(subj, RDF.type)))
        props = {"uri": str(subj)}
        for pred, obj in data.predicate_objects(subj):
            if isinstance(obj, URIRef) or pred == RDF.type:
                continue
            props[local_name(str(pred))] = str(obj)
        label = data.value(subj, RDFS.label)
        nodes.append(Node(id=str(subj),
                          name=str(label) if label else local_name(str(subj)),
                          classes=classes,
                          props=props))
    resolve_roots(nodes, parent_of)

    edges = []
    for prop in sorted(object_props, key=str):
        for s, o in data.subject_objects(prop):
            edges.append(Edge(source=str(s), target=str(o),
                              kind=local_name(str(prop))))

    graph = Graph(nodes=nodes, edges=edges,
                  title="샘플 온톨로지 인스턴스 그래프 (A-Box)",
                  subtitle="색과 형태 = 최상위 클래스 · 노드에 올리면 프로퍼티 표시")
    return graph.drop_dangling_edges()
