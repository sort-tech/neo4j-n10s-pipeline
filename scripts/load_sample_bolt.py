#!/usr/bin/env python3
"""bolt 로 접속해 샘플 데이터를 넣는 독립 스크립트 — 순수 Cypher, n10s 불필요.

사용법
    python3 scripts/load_sample_bolt.py              # 적재
    python3 scripts/load_sample_bolt.py --clear      # 기존 데이터 삭제 후 적재
    python3 scripts/load_sample_bolt.py --drop-only  # 삭제만
    python3 scripts/load_sample_bolt.py --uri bolt://host:7687 --password secret
    python3 scripts/load_sample_bolt.py --dry-run    # 접속 없이 만들 내용만 출력

왜 별도로 두는가
    `python3 -m viz load` 는 n10s 프로시저(`n10s.rdf.import.inline` 등)로
    RDF 를 적재합니다. neosemantics 플러그인 JAR 이 필요하고, 적재 결과가
    n10s 설정(handleVocabUris 등)에 딸려 갑니다.

    이 스크립트는 **같은 모양의 그래프를 순수 Cypher 로 직접 씁니다.**

      * 플러그인 없는 바닐라 Neo4j 에서도 돌아갑니다.
      * n10s 가 대신 해 주는 일이 Cypher 로 드러나 보입니다.
      * 결과 모양이 n10s 와 같으므로 `python3 -m viz draw` 와
        `scripts/03_explore.cypher` 가 그대로 동작합니다.

만들어지는 그래프 (n10s 적재 결과와 같은 모양)
    T-Box  (:Class:Resource        {uri, name})  -[:SCO]->    (:Class)
           (:Relationship:Resource {uri, name})  -[:DOMAIN]-> (:Class)
                                                 -[:RANGE]->  (:Class)
                                                 -[:SPO]->    (:Relationship)
           (:Property:Resource     {uri, name})   데이터타입 프로퍼티
    A-Box  (:Resource:<클래스명>    {uri, label, ...리터럴})
           (:Resource)-[:<프로퍼티명>]->(:Resource)

    리터럴은 rdflib 의 `toPython()` 으로 네이티브 타입이 됩니다
    (xsd:integer -> int, xsd:date -> datetime.date). n10s 와 마찬가지로
    Neo4j 에 정수/날짜로 저장됩니다.

여러 번 실행해도 안전합니다 — 전부 uri 기준 MERGE 입니다.

필요 패키지: neo4j, rdflib  (pip install -r viz/requirements.txt)
"""

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY = ROOT / "ontology" / "sample-ontology.ttl"
DATA = ROOT / "ontology" / "sample-data.ttl"

# 사용자가 준 샘플 접속 정보가 기본값입니다.
DEFAULT_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
DEFAULT_USER = os.environ.get("NEO4J_USER", "neo4j")
DEFAULT_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")

CONSTRAINT = ("CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS "
              "FOR (r:Resource) REQUIRE r.uri IS UNIQUE")

# 라벨과 관계 타입은 쿼리 파라미터로 바인딩할 수 없어 쿼리 문자열에 직접
# 넣어야 합니다. 온톨로지에서 온 이름이라 신뢰할 만하지만, 주입을 원천
# 차단하기 위해 식별자 형태만 통과시킵니다.
_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def ident(name, kind="식별자"):
    """Cypher 라벨·관계 타입으로 안전한 이름인지 확인하고 그대로 돌려준다."""
    if not isinstance(name, str) or not _IDENT.match(name):
        raise ValueError(f"{kind}로 쓸 수 없는 이름입니다: {name!r}")
    return name


def local_name(uri):
    """URI 에서 로컬 이름만 남긴다. (http://e.org/ns#Person -> Person)"""
    for sep in ("#", "/", ":"):
        if sep in uri:
            uri = uri.rsplit(sep, 1)[1] or uri
    return uri


# --------------------------------------------------------------- 온톨로지 읽기

def read_ontology(onto_path, data_path):
    """Turtle 두 파일에서 적재할 행(row) 들을 뽑아낸다.

    `.ttl` 이 단일 진실 공급원입니다. 여기서 만든 행은 아래 write_* 함수가
    그대로 UNWIND 파라미터로 씁니다.
    """
    try:
        from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef
    except ImportError:
        sys.exit("rdflib 가 필요합니다: pip install -r viz/requirements.txt")

    onto = Graph()
    onto.parse(str(onto_path), format="turtle")
    data = Graph()
    data.parse(str(data_path), format="turtle")

    def named(uri):
        return {"uri": str(uri), "name": ident(local_name(str(uri)), "클래스/프로퍼티")}

    classes = [named(c) for c in sorted(onto.subjects(RDF.type, OWL.Class), key=str)]
    object_props = sorted(onto.subjects(RDF.type, OWL.ObjectProperty), key=str)
    data_props = sorted(onto.subjects(RDF.type, OWL.DatatypeProperty), key=str)

    sco = [{"child": str(c), "parent": str(p)}
           for c, p in sorted(onto.subject_objects(RDFS.subClassOf), key=str)]
    spo = [{"child": str(c), "parent": str(p)}
           for c, p in sorted(onto.subject_objects(RDFS.subPropertyOf), key=str)]

    domain, range_ = [], []
    for prop in object_props:
        for cls in onto.objects(prop, RDFS.domain):
            domain.append({"prop": str(prop), "cls": str(cls)})
        for cls in onto.objects(prop, RDFS.range):
            range_.append({"prop": str(prop), "cls": str(cls)})

    # --- A-Box: 개체와 리터럴 프로퍼티
    #
    # 라벨 조합이 같은 개체끼리 묶습니다. 라벨은 쿼리 문자열에 들어가므로
    # 조합마다 쿼리가 하나씩 나옵니다 (샘플 규모에서는 14개 이하).
    instances = {}
    for subj in sorted(set(data.subjects(RDF.type, None)), key=str):
        labels = tuple(sorted(
            ident(local_name(str(t)), "클래스") for t in data.objects(subj, RDF.type)
        ))
        props = {"uri": str(subj)}
        for pred, obj in data.predicate_objects(subj):
            if pred == RDF.type or not isinstance(obj, Literal):
                continue
            key = "label" if pred == RDFS.label else local_name(str(pred))
            # toPython() 이 xsd 타입을 파이썬 네이티브 타입으로 바꿔 줍니다.
            props[ident(key, "프로퍼티 키")] = obj.toPython()
        instances.setdefault(labels, []).append(props)

    # --- A-Box: 개체 사이의 관계. 관계 타입별로 묶습니다.
    relationships = {}
    for prop in object_props:
        name = ident(local_name(str(prop)), "관계 타입")
        rows = [{"source": str(s), "target": str(o)}
                for s, o in sorted(data.subject_objects(prop), key=str)
                if isinstance(o, URIRef)]
        if rows:
            relationships[name] = rows

    return {
        "classes": classes,
        "object_properties": [named(p) for p in object_props],
        "data_properties": [named(p) for p in data_props],
        "sco": sco,
        "spo": spo,
        "domain": domain,
        "range": range_,
        "instances": instances,
        "relationships": relationships,
    }


# ------------------------------------------------------------------ 적재 쿼리

def write_schema(session, plan, log):
    """T-Box — n10s.onto.import 가 만드는 것과 같은 스키마 노드."""
    for label, key in (("Class", "classes"),
                       ("Relationship", "object_properties"),
                       ("Property", "data_properties")):
        rows = plan[key]
        session.run(
            f"UNWIND $rows AS row "
            f"MERGE (n:Resource {{uri: row.uri}}) "
            f"SET n:{ident(label)}, n.name = row.name",
            rows=rows,
        ).consume()
        log(f"  (:{label}) {len(rows)}개")

    for rel, key, node in (("SCO", "sco", "Class"),
                           ("SPO", "spo", "Relationship")):
        rows = plan[key]
        session.run(
            f"UNWIND $rows AS row "
            f"MATCH (a:{ident(node)} {{uri: row.child}}) "
            f"MATCH (b:{ident(node)} {{uri: row.parent}}) "
            f"MERGE (a)-[:{ident(rel)}]->(b)",
            rows=rows,
        ).consume()
        log(f"  [:{rel}] {len(rows)}개")

    for rel, key in (("DOMAIN", "domain"), ("RANGE", "range")):
        rows = plan[key]
        session.run(
            f"UNWIND $rows AS row "
            f"MATCH (r:Relationship {{uri: row.prop}}) "
            f"MATCH (c:Class {{uri: row.cls}}) "
            f"MERGE (r)-[:{ident(rel)}]->(c)",
            rows=rows,
        ).consume()
        log(f"  [:{rel}] {len(rows)}개")


def write_instances(session, plan, log):
    """A-Box — 개체와 리터럴 프로퍼티."""
    total = 0
    for labels, rows in sorted(plan["instances"].items()):
        # MERGE 는 라벨까지 포함해 매칭하므로, uri 로만 MERGE 한 뒤
        # SET 으로 라벨을 붙입니다. 이미 있는 노드도 안전하게 갱신됩니다.
        set_labels = "".join(f":{ident(l, '클래스')}" for l in labels)
        session.run(
            f"UNWIND $rows AS row "
            f"MERGE (n:Resource {{uri: row.uri}}) "
            f"SET n{set_labels}, n += row",
            rows=rows,
        ).consume()
        total += len(rows)
        log(f"  (:{':'.join(labels)}) {len(rows)}개")
    log(f"  개체 합계 {total}개")


def write_relationships(session, plan, log):
    """A-Box — 개체 사이의 관계."""
    total = 0
    for kind, rows in sorted(plan["relationships"].items()):
        session.run(
            f"UNWIND $rows AS row "
            f"MATCH (a:Resource {{uri: row.source}}) "
            f"MATCH (b:Resource {{uri: row.target}}) "
            f"MERGE (a)-[:{ident(kind, '관계 타입')}]->(b)",
            rows=rows,
        ).consume()
        total += len(rows)
        log(f"  [:{kind}] {len(rows)}개")
    log(f"  관계 합계 {total}개")


def drop_all(session, log):
    summary = session.run("MATCH (n:Resource) DETACH DELETE n").consume()
    log(f"삭제한 노드 {summary.counters.nodes_deleted}개")


# 확인 쿼리. 하나로 합치는 대신 따로 둡니다 — 집계를 체이닝하면 중간에
# 매칭이 0건일 때 결과 행 자체가 사라지고, COUNT {} 서브쿼리는 Neo4j
# 버전을 더 요구합니다. 각각은 항상 정확히 한 행을 돌려줍니다.
_NOT_SCHEMA = "NOT {v}:Class AND NOT {v}:Relationship AND NOT {v}:Property"

VERIFY_QUERIES = (
    ("(:Class)", "MATCH (c:Class) RETURN count(c) AS n"),
    ("(:Relationship)", "MATCH (r:Relationship) RETURN count(r) AS n"),
    ("(:Property)", "MATCH (p:Property) RETURN count(p) AS n"),
    ("개체", "MATCH (n:Resource) WHERE " + _NOT_SCHEMA.format(v="n")
             + " RETURN count(n) AS n"),
    ("개체 간 관계",
     "MATCH (a:Resource)-[e]->(b:Resource) "
     "WHERE (" + _NOT_SCHEMA.format(v="a") + ") "
     "AND (" + _NOT_SCHEMA.format(v="b") + ") RETURN count(e) AS n"),
)


def verify(session, log):
    """적재 결과를 세어 본다 — viz/sources.py 가 쓰는 조건절과 같은 패턴."""
    counts = {}
    for name, query in VERIFY_QUERIES:
        record = session.run(query).single()
        counts[name] = record["n"] if record else 0
        log(f"  {name} {counts[name]}")
    return counts


# ----------------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--clear", action="store_true",
                        help="적재 전에 기존 :Resource 노드를 모두 삭제")
    parser.add_argument("--drop-only", action="store_true",
                        help="삭제만 하고 끝낸다")
    parser.add_argument("--dry-run", action="store_true",
                        help="접속하지 않고 적재할 내용만 출력")
    args = parser.parse_args(argv)

    def log(msg):
        print(msg)

    plan = read_ontology(ONTOLOGY, DATA)

    if args.dry_run:
        log("적재 계획 (접속하지 않음)")
        log(f"  (:Class) {len(plan['classes'])} · "
            f"(:Relationship) {len(plan['object_properties'])} · "
            f"(:Property) {len(plan['data_properties'])}")
        log(f"  [:SCO] {len(plan['sco'])} · [:SPO] {len(plan['spo'])} · "
            f"[:DOMAIN] {len(plan['domain'])} · [:RANGE] {len(plan['range'])}")
        log(f"  개체 {sum(len(v) for v in plan['instances'].values())}개 "
            f"(라벨 조합 {len(plan['instances'])}종)")
        log(f"  관계 {sum(len(v) for v in plan['relationships'].values())}개 "
            f"(타입 {len(plan['relationships'])}종)")
        return

    try:
        from neo4j import GraphDatabase
    except ImportError:
        sys.exit("neo4j 드라이버가 필요합니다: pip install -r viz/requirements.txt")

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    try:
        log(f"접속: {args.uri} (database={args.database})")
        with driver.session(database=args.database) as session:
            if args.clear or args.drop_only:
                log("기존 데이터 삭제")
                drop_all(session, log)
                if args.drop_only:
                    return

            session.run(CONSTRAINT).consume()
            log("uri 고유 제약조건 확인")

            log("T-Box 적재")
            write_schema(session, plan, log)
            log("A-Box 적재")
            write_instances(session, plan, log)
            write_relationships(session, plan, log)

            log("확인")
            verify(session, log)
    except Exception as exc:                        # noqa: BLE001
        name = type(exc).__name__
        if name in ("ServiceUnavailable", "SessionExpired"):
            sys.exit(f"Neo4j 에 연결할 수 없습니다: {args.uri}\n"
                     "  - 컨테이너 상태: docker compose ps\n"
                     "  - 접속 없이 계획만 보려면: --dry-run")
        if name in ("AuthError", "AuthConfigurationError"):
            sys.exit(f"인증 실패 (user={args.user}). --password 를 확인하세요.")
        raise
    finally:
        driver.close()

    log("\n완료. 이제 그림을 그릴 수 있습니다:")
    log("  python3 -m viz draw")


if __name__ == "__main__":
    main()
