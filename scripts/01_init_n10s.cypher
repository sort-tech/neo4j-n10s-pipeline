// ---------------------------------------------------------------------
// n10s 초기화
//
// 주의: Cypher 주석은 `//` 또는 `/* */` 입니다. `--` 는 문법 오류입니다.
// ---------------------------------------------------------------------

// 1. n10s 프로시저 로드 확인
SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'n10s';

// 2. URI 고유 제약조건 생성 (RDF 임포트 필수 조건)
CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS
FOR (r:Resource) REQUIRE r.uri IS UNIQUE;

// 3. 그래프 구성 초기화
//
// handleVocabUris: 'IGNORE'
//   네임스페이스를 버리고 로컬 이름만 남깁니다. 기본값 'SHORTEN' 을 쓰면
//   라벨과 프로퍼티가 `ns0__Person`, `ns0__email` 형태가 되어 데모 쿼리가
//   읽기 어려워집니다. 단일 어휘(vocabulary)만 적재하는 데모이므로 이름
//   충돌 위험이 없어 IGNORE 가 안전합니다. 여러 어휘를 섞어 적재할 때는
//   'SHORTEN' 또는 'MAP' 을 사용하세요.
// handleMultival: 'OVERWRITE' (기본값)
//   샘플 데이터의 리터럴 프로퍼티는 모두 단일값이므로 배열 변환이 필요
//   없습니다. 다중값 리터럴을 보존해야 한다면 'ARRAY' 와 함께
//   multivalPropList 를 지정하세요 (생략하면 모든 프로퍼티가 배열이 됩니다).
// handleRDFTypes: 'LABELS'
//   rdf:type 을 노드 라벨로 변환합니다.
CALL n10s.graphconfig.init({
  handleVocabUris: 'IGNORE',
  handleMultival: 'OVERWRITE',
  keepLangTag: false,
  handleRDFTypes: 'LABELS',
  applyNeo4jNaming: false
});
