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
├── run_demo.sh                 # 샘플 온톨로지 데모 전체 실행
├── .gitignore                  # 런타임 데이터, 로그, 플러그인 바이너리 제외
├── README.md                   # 프로젝트 사용 설명서
├── data/                       # Neo4j 데이터베이스 영구 저장소 (Git 제외)
├── logs/                       # Neo4j 서버 로그 저장소 (Git 제외)
├── plugins/                    # n10s 및 APOC 플러그인 저장소 (Git 제외)
├── ontology/                   # 샘플 온톨로지 (RDF Turtle)
│   ├── sample-ontology.ttl     # T-Box — 클래스 계층 및 프로퍼티 정의
│   └── sample-data.ttl         # A-Box — 개체 28개
├── scripts/                    # Cypher 초기화 및 유틸리티 스크립트
│   ├── 01_init_n10s.cypher     # n10s 필수 제약조건 및 초기 설정
│   ├── 02_load_sample.cypher   # 샘플 온톨로지 · 데이터 적재
│   ├── 03_explore.cypher       # 적재 확인 및 온톨로지 활용 질의
│   └── 04_inference_procedures.cypher  # n10s 추론 프로시저 예제 (선택)
├── viz/                        # 적재 · 시각화 도구 (Python)
│   ├── palette.py              # 검증된 색 · 형태 토큰
│   ├── model.py                # 소스와 렌더러 사이의 중간 표현
│   ├── layout.py               # 좌표 계산 (force / layered)
│   ├── sources.py              # Neo4j · Turtle 데이터 소스
│   ├── render.py               # SVG · 단일 파일 HTML 렌더러
│   ├── loader.py               # Neo4j 적재
│   └── requirements.txt
├── tests/                      # viz 테스트 (Neo4j 불필요)
└── out/                        # 생성된 그림 (Git 제외)
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

> **참고:** Cypher의 주석은 `//` 또는 `/* */` 입니다. `--`는 문법 오류입니다.

```cypher
// 1. n10s 프로시저 로드 확인
SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'n10s';

// 2. URI 고유 제약조건 생성 (RDF 임포트 필수 조건)
CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS
FOR (r:Resource) REQUIRE r.uri IS UNIQUE;

// 3. 그래프 구성 초기화
//
// 기본값 handleVocabUris:'SHORTEN' 을 쓰면 라벨과 프로퍼티가
// `ns0__Person`, `ns0__email` 형태가 됩니다. 단일 어휘만 적재하는
// 데모에서는 'IGNORE' 가 훨씬 읽기 좋습니다.
CALL n10s.graphconfig.init({
  handleVocabUris: 'IGNORE',
  handleMultival: 'OVERWRITE',
  keepLangTag: false,
  handleRDFTypes: 'LABELS',
  applyNeo4jNaming: false
});
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

## 🎨 샘플 온톨로지 데모 — 데이터 만들고 그리기

`ontology/` 의 샘플 온톨로지를 Neo4j에 적재하고, 그 결과를 그림으로 뽑는
전체 경로입니다.

### 한 줄 실행

```bash
./run_demo.sh
```

플러그인 다운로드 → 컨테이너 기동 → 대기 → 적재 → 확인 질의 → 그림 생성까지
한 번에 수행합니다.

| 명령 | 하는 일 |
| :--- | :--- |
| `./run_demo.sh` | 전체 경로 |
| `./run_demo.sh --draw` | 이미 적재된 DB에서 그림만 다시 생성 |
| `./run_demo.sh --offline` | **Neo4j 없이** `.ttl` 에서 바로 그림 생성 |

### 샘플 온톨로지 구성

최상위 클래스 4종과 그 하위 클래스, 오브젝트/데이터타입 프로퍼티로 이루어진
기술 조직 지식 그래프입니다.

| 구분 | 내용 |
| :--- | :--- |
| 클래스 | 14개 — `Person`(→`Employee`→`Engineer`/`Researcher`, `Student`), `Organization`(→`Company`/`University`), `Project`(→`ProductProject`/`ResearchProject`), `Skill`(→`ProgrammingLanguage`/`KnowledgeDomain`) |
| 오브젝트 프로퍼티 | 12개 — `worksFor`·`studiesAt`(⊑`affiliatedWith`), `leads`(⊑`contributesTo`), `employs`(`owl:inverseOf worksFor`), `hasSkill`, `requiresSkill`, `ownedBy`, `collaboratesWith`·`relatedTo`(대칭), `dependsOn`(추이) |
| 데이터타입 프로퍼티 | 5개 — `email`, `yearsOfExperience`, `foundedIn`, `startedOn`, `proficiencyLevel` |
| 인스턴스 | 28개 / 관계 73개 |

하위 클래스 계층과 하위 프로퍼티를 일부러 넣어 두었습니다. n10s가 T-Box를
`[:SCO]`/`[:SPO]` 관계로 적재하므로, 라벨을 추가하지 않고도 계층을 타고
추론 질의를 할 수 있습니다 (`scripts/03_explore.cypher` 5·6번 질의).

### 단계별 실행

```bash
# 1. 적재 — Turtle 본문을 쿼리 파라미터로 넘깁니다(이스케이프 문제 없음)
pip install -r viz/requirements.txt
python3 -m viz load

# 2. 확인 질의
docker compose exec -T neo4j cypher-shell -u neo4j -p password < scripts/03_explore.cypher

# 3. 그림 생성 -> out/
python3 -m viz draw
```

`cypher-shell`만으로 적재하려면 `scripts/02_load_sample.cypher` 를 쓰세요.
이 스크립트는 `file:///ontology/...` 를 읽으므로 `docker-compose.yml` 의
`./ontology:/ontology:ro` 마운트가 필요합니다 (이미 포함되어 있습니다).

### 생성되는 그림

| 파일 | 내용 |
| :--- | :--- |
| `out/schema.html` | **T-Box** — 클래스 계층(실선)과 프로퍼티의 domain→range(점선). 계층 깊이를 y축에 두어 위에서 아래로 읽힙니다. |
| `out/instances.html` | **A-Box** — 개체 그래프. 관계 타입 필터, 노드 호버 시 프로퍼티 툴팁과 이웃 강조. |
| `out/*.svg` | 문서 삽입용 정적 그림. OS 다크 모드를 따라갑니다. |

HTML은 CDN 없이 단일 파일로 완결되어 그대로 공유·커밋할 수 있습니다.

```bash
# 특정 관계만 좁혀서 정적 그림 뽑기 (이때는 간선 라벨도 표시)
python3 -m viz draw --view instances --format svg \
  --relation worksFor --relation studiesAt

# 원격 Neo4j
python3 -m viz draw --uri bolt://host:7687 --password secret

# 적재한 데이터 삭제
python3 -m viz clear
```

### 읽기 방식에 대한 메모

- 노드의 **색과 형태**가 함께 최상위 클래스를 나타냅니다. 색만 쓰지 않는
  이유는 `viz/palette.py` 의 docstring에 검증 수치와 함께 적어 두었습니다.
  같은 이유로 색상 슬롯은 4개가 상한이며, 5번째 최상위 클래스는 새 색을
  만들지 않고 중립색으로 접힙니다.
- Cypher 질의는 `handleVocabUris` 설정에 의존하지 않습니다. `'IGNORE'`로
  적재했든 `'SHORTEN'`으로 적재했든 같은 그림이 나옵니다.

### 테스트

Neo4j 없이 전부 돌아갑니다. Neo4j 경로는 n10s가 내놓는 레코드 모양을 흉내낸
가짜 세션으로 검증합니다.

```bash
python3 -m unittest discover -s tests -v
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
| 샘플 데모 전체 실행 | `./run_demo.sh` |
| 샘플 적재 / 삭제 | `python3 -m viz load` / `python3 -m viz clear` |
| 그림만 다시 생성 | `python3 -m viz draw` |
| Neo4j 없이 그림 생성 | `python3 -m viz draw --source ttl` |
| viz 테스트 | `python3 -m unittest discover -s tests` |
