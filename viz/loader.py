"""Neo4j 적재. Turtle 본문을 **쿼리 파라미터로** 넘깁니다.

Turtle 본문에는 따옴표가 들어 있어 Cypher 문자열 리터럴로 인라인하면
이스케이프가 번거롭고 깨지기 쉽습니다. 파라미터 바인딩을 쓰면 그 문제가
없고, 파일이 컨테이너 안에 마운트되어 있지 않아도 됩니다(원격 Neo4j 에도
그대로 동작).
"""

GRAPH_CONFIG = {
    "handleVocabUris": "IGNORE",
    "handleMultival": "OVERWRITE",
    "keepLangTag": False,
    "handleRDFTypes": "LABELS",
    "applyNeo4jNaming": False,
}

# scripts/02_load_sample.cypher 과 같은 값 — 모두 n10s 기본값이지만
# sources.py 의 Cypher 쿼리가 이 이름에 의존하므로 명시합니다.
ONTO_OPTIONS = {
    "classLabel": "Class",
    "objectPropertyLabel": "Relationship",
    "dataTypePropertyLabel": "Property",
    "subClassOfRel": "SCO",
    "subPropertyOfRel": "SPO",
    "domainRel": "DOMAIN",
    "rangeRel": "RANGE",
}

CONSTRAINT = ("CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS "
              "FOR (r:Resource) REQUIRE r.uri IS UNIQUE")


def init(session, log=print):
    """제약조건 + 그래프 구성. 이미 초기화되어 있으면 set 으로 갱신한다."""
    session.run(CONSTRAINT).consume()
    try:
        session.run("CALL n10s.graphconfig.init($cfg)", cfg=GRAPH_CONFIG).consume()
        log("graphconfig: 초기화 완료")
    except Exception as exc:
        # init 은 데이터가 이미 있거나 구성이 존재하면 실패합니다.
        session.run("CALL n10s.graphconfig.set($cfg)", cfg=GRAPH_CONFIG).consume()
        log(f"graphconfig: 기존 구성 갱신 (init 실패: {type(exc).__name__})")


def clear(session, log=print):
    """적재된 리소스와 그래프 구성을 모두 지운다."""
    summary = session.run("MATCH (n:Resource) DETACH DELETE n").consume()
    log(f"삭제된 노드: {summary.counters.nodes_deleted}")
    try:
        session.run("CALL n10s.graphconfig.drop()").consume()
        log("graphconfig: 삭제")
    except Exception as exc:
        log(f"graphconfig: 삭제 생략 ({type(exc).__name__})")


def _report(procedure, data, log):
    log(f"{procedure}: terminationStatus={data.get('terminationStatus')} "
        f"triplesLoaded={data.get('triplesLoaded')} "
        f"triplesParsed={data.get('triplesParsed')}")
    if data.get("extraInfo"):
        log(f"  extraInfo: {data['extraInfo']}")


def load_ontology(session, turtle, log=print):
    """T-Box 적재."""
    record = session.run(
        "CALL n10s.onto.import.inline($payload, 'Turtle', $opts)",
        payload=turtle, opts=ONTO_OPTIONS,
    ).single()
    data = record.data() if record else {}
    _report("n10s.onto.import.inline", data, log)
    return data


def load_data(session, turtle, log=print):
    """A-Box 적재."""
    record = session.run(
        "CALL n10s.rdf.import.inline($payload, 'Turtle')",
        payload=turtle,
    ).single()
    data = record.data() if record else {}
    _report("n10s.rdf.import.inline", data, log)
    return data
