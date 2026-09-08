# Neo4j + n10s (neosemantics) + APOC Starter

Neo4j 5.26 Community Edition 환경에서 **n10s(neosemantics)** 및 **APOC** 플러그인을 손쉽게 구성하고 사용할 수 있는 Docker 기반 스타터 템플릿입니다.

---

## 📌 구성 환경

- **Neo4j:** `5.26-community`
- **n10s (neosemantics):** `v5.26.0` (RDF, 온톨로지, 시맨틱 웹 연동 지원)
- **APOC:** Neo4j 공식 이미지 내장 APOC 자동 설치 및 로드
- **포트:**
  - `7474`: Neo4j Browser / HTTP API
  - `7687`: Bolt 프로토콜

---

## 📂 디렉터리 구조

```text
neo4j-n10s-starter/
├── docker-compose.yml          # Neo4j 컨테이너 구성 및 환경변수 설정
├── .gitignore                  # 런타임 데이터, 로그, 플러그인 바이너리 제외
├── README.md                   # 프로젝트 사용 설명서
├── data/                       # Neo4j 데이터베이스 영구 저장소 (Git 제외)
├── logs/                       # Neo4j 서버 로그 저장소 (Git 제외)
├── plugins/                    # n10s 및 APOC 플러그인 저장소 (Git 제외)
└── scripts/                    # Cypher 초기화 및 유틸리티 스크립트
    └── 01_init_n10s.cypher     # n10s 필수 제약조건 및 초기 설정 스크립트
```

---

## 🚀 빠른 시작 가이드

### 1. 사전 요구사항

- [Docker](https://docs.docker.com/get-docker/) 및 [Docker Compose](https://docs.docker.com/compose/)가 설치되어 있어야 합니다.

### 2. 저장소 클론 및 n10s 플러그인 다운로드

저장소를 클론한 후 `plugins/` 디렉터리에 호환되는 n10s JAR 파일을 다운로드합니다:

```bash
# 디렉터리 생성 (클론 시 이미 존재할 수 있음)
mkdir -p plugins data logs scripts

# n10s v5.26.0 JAR 다운로드 및 권한 설정
curl -L -o plugins/neosemantics-5.26.0.jar \
  https://github.com/neo4j-labs/neosemantics/releases/download/5.26.0/neosemantics-5.26.0.jar

chmod 644 plugins/neosemantics-5.26.0.jar
```

> **참고:** APOC 플러그인은 `docker-compose.yml`의 `NEO4J_PLUGINS=["apoc"]` 설정에 의해 컨테이너 시작 시 자동으로 다운로드 및 적용됩니다.

### 3. 컨테이너 실행

백그라운드로 Neo4j 컨테이너를 구동합니다:

```bash
docker compose up -d
```

기동 로그 확인:

```bash
docker compose logs -f neo4j
```

로그에 `Started.` 문구가 표시되면 정상적으로 시작된 것입니다.

### 4. n10s 초기화 설정

n10s를 사용하기 위해서는 **고유 URI 제약조건 생성**과 **기본 그래프 구성 초기화** 작업이 필수적입니다.

#### 방법 A: Neo4j Browser에서 직접 실행 (권장)

1. 웹 브라우저에서 **[http://localhost:7474](http://localhost:7474)** 접속
2. 접속 정보:
   - **Connect URL:** `neo4j://localhost:7687` (또는 `bolt://localhost:7687`)
   - **Username:** `neo4j`
   - **Password:** `password`
3. 아래 쿼리를 순서대로 실행:

```cypher
-- 1. n10s 프로시저 로드 확인
SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'n10s';

-- 2. URI 고유 제약조건 생성 (RDF 임포트 필수 조건)
CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS
FOR (r:Resource) REQUIRE r.uri IS UNIQUE;

-- 3. 기본 그래프 구성 초기화
CALL n10s.graphconfig.init();
```

#### 방법 B: CLI (cypher-shell)로 일괄 실행

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p password < scripts/01_init_n10s.cypher
```

---

## 🧪 간단한 n10s RDF 임포트 테스트

초기화 완료 후 인라인 RDF Turtle 데이터를 Neo4j로 가져오는 테스트를 진행할 수 있습니다:

```cypher
CALL n10s.rdf.import.inline('
  @prefix ex: <http://example.org/> .
  @prefix foaf: <http://xmlns.com/foaf/0.1/> .

  ex:Alice a foaf:Person ;
      foaf:name "Alice" ;
      foaf:knows ex:Bob .

  ex:Bob a foaf:Person ;
      foaf:name "Bob" .
', 'Turtle');
```

임포트 결과 확인:

```cypher
MATCH (n:Resource)
RETURN n;
```

---

## 🛠 유용한 명령어

| 작업 | 명령어 |
| :--- | :--- |
| 컨테이너 시작 | `docker compose up -d` |
| 컨테이너 중지 | `docker compose down` |
| 컨테이너 재시작 | `docker compose restart` |
| 로그 실시간 조회 | `docker compose logs -f neo4j` |
| Cypher Shell 접속 | `docker compose exec neo4j cypher-shell -u neo4j -p password` |
| 전체 데이터 초기화 | `docker compose down -v` 후 `rm -rf data/*` |
