-- 1. n10s 프로시저 로드 확인
SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'n10s';

-- 2. URI 고유 제약조건 생성 (RDF 임포트 필수 조건)
CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS
FOR (r:Resource) REQUIRE r.uri IS UNIQUE;

-- 3. 기본 그래프 구성 초기화
CALL n10s.graphconfig.init();
