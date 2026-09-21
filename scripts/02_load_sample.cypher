// ---------------------------------------------------------------------
// 샘플 온톨로지(T-Box) + 인스턴스(A-Box) 적재 — cypher-shell 경로
//
// 실행 전 준비:
//   docker-compose.yml 이 ./ontology 를 컨테이너의 /ontology 로
//   마운트하고 있어야 합니다 (이 저장소의 compose 파일에 포함되어 있음).
//
// 실행:
//   docker compose exec -T neo4j \
//     cypher-shell -u neo4j -p password < scripts/02_load_sample.cypher
//
// 참고: Turtle 본문에 따옴표가 포함되어 있어 Cypher 문자열 리터럴로
// 인라인하면 이스케이프가 번거롭습니다. 그래서 여기서는 파일을 직접 읽는
// `*.fetch` 프로시저를 사용합니다. 파라미터 바인딩으로 본문을 그대로
// 넘기는 방식은 `python3 -m viz load` 쪽을 참고하세요.
// ---------------------------------------------------------------------

// 1. T-Box 적재
//
// 온톨로지 임포터는 클래스/프로퍼티를 데이터 노드가 아닌 스키마 노드로
// 만듭니다. 아래 옵션은 모두 n10s 기본값이며, viz 쪽 Cypher 쿼리가
// 이 이름에 의존하므로 명시해 둡니다.
CALL n10s.onto.import.fetch('file:///ontology/sample-ontology.ttl', 'Turtle', {
  classLabel: 'Class',
  objectPropertyLabel: 'Relationship',
  dataTypePropertyLabel: 'Property',
  subClassOfRel: 'SCO',
  subPropertyOfRel: 'SPO',
  domainRel: 'DOMAIN',
  rangeRel: 'RANGE'
});

// 2. A-Box 적재
CALL n10s.rdf.import.fetch('file:///ontology/sample-data.ttl', 'Turtle');
