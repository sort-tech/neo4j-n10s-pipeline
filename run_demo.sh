#!/usr/bin/env bash
#
# 샘플 온톨로지 데모 전체 실행.
#
#   ./run_demo.sh            컨테이너 기동 -> 적재 -> 그림 생성
#   ./run_demo.sh --draw     이미 적재된 DB 에서 그림만 다시 생성
#   ./run_demo.sh --offline  Neo4j 없이 .ttl 에서 바로 그림 생성
#
set -euo pipefail

cd "$(dirname "$0")"

N10S_VERSION="5.26.0"
N10S_JAR="plugins/neosemantics-${N10S_VERSION}.jar"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-password}"
WAIT_SECONDS="${WAIT_SECONDS:-180}"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

draw() {
  step "그림 생성 (out/)"
  python3 -m viz draw "$@"
  echo
  echo "브라우저로 열어 보세요:"
  echo "  out/schema.html     클래스 계층 + 프로퍼티 (T-Box)"
  echo "  out/instances.html  개체 그래프 — 관계 타입 필터 · 호버 (A-Box)"
  echo "  out/*.svg           문서 삽입용 정적 그림 (다크 모드 대응)"
}

# --- Neo4j 없이 .ttl 에서 바로 -------------------------------------------
if [[ "${1:-}" == "--offline" ]]; then
  draw --source ttl
  exit 0
fi

# --- 적재된 DB 에서 그림만 ------------------------------------------------
if [[ "${1:-}" == "--draw" ]]; then
  draw
  exit 0
fi

# --- 전체 경로 ------------------------------------------------------------
step "n10s 플러그인 확인"
if [[ -f "$N10S_JAR" ]]; then
  echo "이미 있음: $N10S_JAR"
else
  echo "다운로드: neosemantics ${N10S_VERSION}"
  mkdir -p plugins
  curl -fSL -o "$N10S_JAR" \
    "https://github.com/neo4j-labs/neosemantics/releases/download/${N10S_VERSION}/neosemantics-${N10S_VERSION}.jar"
  chmod 644 "$N10S_JAR"
fi

step "Neo4j 컨테이너 기동"
docker compose up -d

step "Neo4j 준비 대기 (최대 ${WAIT_SECONDS}초)"
deadline=$((SECONDS + WAIT_SECONDS))
until docker compose exec -T neo4j \
        cypher-shell -u neo4j -p "$NEO4J_PASSWORD" 'RETURN 1' >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "시간 초과. 로그를 확인하세요: docker compose logs neo4j" >&2
    exit 1
  fi
  sleep 3
done
echo "준비 완료."

step "n10s 프로시저 확인"
docker compose exec -T neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'n10s' RETURN count(*) AS n10s_procedures;"

step "샘플 온톨로지 + 데이터 적재"
# Turtle 본문을 쿼리 파라미터로 넘기므로 이스케이프 문제가 없습니다.
# cypher-shell 로 하고 싶다면 scripts/02_load_sample.cypher 를 쓰세요.
python3 -m viz load

step "확인 쿼리"
docker compose exec -T neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  < scripts/03_explore.cypher

draw
