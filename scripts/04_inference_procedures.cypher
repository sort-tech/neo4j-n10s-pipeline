// ---------------------------------------------------------------------
// n10s 추론 프로시저 버전 (선택)
//
// 03_explore.cypher 의 5번 / 6번 질의와 결과가 같습니다. 차이는 SCO/SPO
// 순회를 직접 쓰지 않고 n10s 내장 프로시저에 맡긴다는 점입니다.
//
// 프로시저 시그니처는 n10s 버전에 따라 달라질 수 있으므로 메인 스크립트
// (03_explore.cypher)와 분리해 두었습니다. 여기서 오류가 나더라도
// 03 번의 순수 Cypher 질의는 그대로 동작합니다.
//
// 사용 가능한 추론 프로시저 확인:
//   SHOW PROCEDURES YIELD name, signature
//   WHERE name STARTS WITH 'n10s.inference';
//
// 실행:
//   docker compose exec -T neo4j \
//     cypher-shell -u neo4j -p password < scripts/04_inference_procedures.cypher
// ---------------------------------------------------------------------

// 1. 하위 클래스를 포함한 카테고리 조회 — 03번 5번 질의와 동일
CALL n10s.inference.nodesInCategory('Person', {
  catLabel:    'Class',
  catNameProp: 'name',
  subCatRel:   'SCO'
})
YIELD node
RETURN node.label AS person
ORDER BY person;

// 2. 하위 프로퍼티를 포함한 관계 조회 — 03번 6번 질의와 동일
//
// getRels 는 시작 노드를 인자로 받으므로 Person 인스턴스를 먼저 모읍니다.
MATCH (:Class {name: 'Person'})<-[:SCO*0..]-(sub:Class)
WITH collect(sub.name) AS personClasses
MATCH (p:Resource)
WHERE any(l IN labels(p) WHERE l IN personClasses)
CALL n10s.inference.getRels(p, 'affiliatedWith', {
  relLabel:    'Relationship',
  relNameProp: 'name',
  subRelRel:   'SPO'
})
YIELD rel
RETURN p.label            AS person,
       type(rel)          AS storedAs,
       endNode(rel).label AS organization
ORDER BY person;
