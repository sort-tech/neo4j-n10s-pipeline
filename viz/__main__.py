"""샘플 온톨로지 적재 · 시각화 CLI.

    python3 -m viz load            # Neo4j 에 샘플 온톨로지 + 데이터 적재
    python3 -m viz draw            # Neo4j 에서 읽어 out/ 에 그림 생성
    python3 -m viz draw --source ttl   # Neo4j 없이 .ttl 파일에서 바로 생성
    python3 -m viz clear           # 적재한 데이터 삭제

접속 정보는 --uri/--user/--password 또는 환경변수
NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD 로 줍니다.
"""

import argparse
import os
import sys
from pathlib import Path

from . import layout, sources
from .render import LABEL_LIMIT, Renderer, radius_fn

ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY = ROOT / "ontology" / "sample-ontology.ttl"
DATA = ROOT / "ontology" / "sample-data.ttl"

DEFAULT_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
DEFAULT_USER = os.environ.get("NEO4J_USER", "neo4j")
DEFAULT_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")


def _driver(args):
    try:
        from neo4j import GraphDatabase
    except ImportError:
        sys.exit("neo4j 드라이버가 없습니다: pip install -r viz/requirements.txt")
    return GraphDatabase.driver(args.uri, auth=(args.user, args.password))


# --------------------------------------------------------------- commands

def cmd_load(args):
    from . import loader

    with _driver(args) as driver, driver.session(database=args.database) as s:
        loader.init(s)
        loader.load_ontology(s, ONTOLOGY.read_text(encoding="utf-8"))
        loader.load_data(s, DATA.read_text(encoding="utf-8"))
    print("적재 완료. 다음: python3 -m viz draw")


def cmd_clear(args):
    from . import loader

    with _driver(args) as driver, driver.session(database=args.database) as s:
        loader.clear(s)


def _build(view, args):
    """요청한 뷰의 Graph 를 만들고 좌표를 채운다."""
    if args.source == "ttl":
        graph = (sources.ttl_schema(ONTOLOGY) if view == "schema"
                 else sources.ttl_instances(ONTOLOGY, DATA))
    else:
        with _driver(args) as driver, driver.session(database=args.database) as s:
            graph = (sources.neo4j_schema(s) if view == "schema"
                     else sources.neo4j_instances(s))

    if not graph.nodes:
        raise SystemExit(
            f"'{view}' 뷰에 그릴 노드가 없습니다."
            + ("" if args.source == "ttl" else
               " 먼저 `python3 -m viz load` 를 실행하세요.")
        )

    if args.relation:
        keep = set(args.relation)
        graph.edges = [e for e in graph.edges if e.kind in keep]
        linked = {e.source for e in graph.edges} | {e.target for e in graph.edges}
        graph.nodes = [n for n in graph.nodes if n.id in linked]
        graph.subtitle = "관계 필터: " + ", ".join(sorted(keep))
        if not graph.nodes:
            raise SystemExit(f"'{view}' 뷰에 해당 관계가 없습니다: "
                             f"{', '.join(sorted(keep))}")

    # 스키마 뷰는 계층 단계 수만큼만 높이를 씁니다. force 배치와 같은
    # 높이를 주면 단계 사이가 과도하게 벌어져 간선이 길어집니다.
    height = args.height
    if view == "schema":
        layout.layered_layout(graph, args.width, height)
        ranks = max(n.depth for n in graph.nodes) + 1
        height = min(height, 150 + 145 * ranks)
        layout.layered_layout(graph, args.width, height)
    else:
        layout.force_layout(graph, args.width, height,
                            iterations=args.iterations)
        # force 배치는 마크만 보므로 이름이 긴 노드끼리 라벨이 겹칩니다.
        top = max(height * 0.06, layout.self_loop_headroom(graph))
        layout.relax_overlaps(
            graph, radius_fn(graph), label_limit=LABEL_LIMIT,
            bounds=(14, top, args.width - 14, height - 26))
    return graph, height


def cmd_draw(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    views = ["schema", "instances"] if args.view == "both" else [args.view]

    for view in views:
        graph, height = _build(view, args)
        # 스키마 뷰는 간선이 적고 프로퍼티 이름이 핵심이라 라벨을 답니다.
        # 인스턴스 뷰는 간선이 많아 정적 그림에 라벨을 달면 뭉개지므로
        # HTML 의 호버/필터로 대신합니다 (--relation 으로 좁히면 표시).
        edge_labels = view == "schema" or bool(args.relation)
        renderer = Renderer(graph, width=args.width, height=height,
                            edge_labels=edge_labels)

        for ext, text in (("html", renderer.to_html()),
                          ("svg", renderer.to_svg())):
            if args.format not in (ext, "both"):
                continue
            path = out / f"{view}.{ext}"
            path.write_text(text, encoding="utf-8")
            print(f"{path}  ({len(graph.nodes)} 노드 / "
                  f"{len(graph.edges)} 간선, {len(text) // 1024} KB)")


# ------------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python3 -m viz", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("load", help="샘플 온톨로지 + 데이터를 Neo4j 에 적재")
    sub.add_parser("clear", help="적재한 리소스 삭제")

    draw = sub.add_parser("draw", help="그래프 그리기")
    draw.add_argument("--view", choices=("schema", "instances", "both"),
                      default="both")
    draw.add_argument("--source", choices=("neo4j", "ttl"), default="neo4j",
                      help="neo4j: 적재된 DB 에서 읽기(기본). "
                           "ttl: ontology/*.ttl 에서 직접 읽기")
    draw.add_argument("--format", choices=("html", "svg", "both"),
                      default="both")
    draw.add_argument("--relation", action="append", metavar="TYPE",
                      help="이 관계 타입만 그린다 (여러 번 지정 가능)")
    draw.add_argument("--out", default=str(ROOT / "out"))
    draw.add_argument("--width", type=int, default=1180)
    draw.add_argument("--height", type=int, default=760)
    draw.add_argument("--iterations", type=int, default=600,
                      help="force 배치 반복 횟수 (인스턴스 뷰)")

    args = parser.parse_args(argv)
    command = {"load": cmd_load, "clear": cmd_clear, "draw": cmd_draw}[args.command]
    try:
        command(args)
    except Exception as exc:                       # noqa: BLE001
        _explain(exc, args)
        raise SystemExit(1)


def _explain(exc, args):
    """드라이버 예외를 사람이 읽을 수 있는 안내로 바꾼다."""
    name = type(exc).__name__
    if name in ("ServiceUnavailable", "SessionExpired"):
        sys.stderr.write(
            f"Neo4j 에 연결할 수 없습니다: {args.uri}\n"
            "  - 컨테이너가 떠 있는지: docker compose ps\n"
            "  - 기동 로그: docker compose logs -f neo4j\n"
            "  - 다른 주소면: --uri bolt://host:7687 또는 NEO4J_URI\n"
            "  - Neo4j 없이 그림만 보려면: "
            "python3 -m viz draw --source ttl\n")
    elif name in ("AuthError", "AuthConfigurationError"):
        sys.stderr.write(
            f"인증 실패 (user={args.user}). --password 또는 "
            "NEO4J_PASSWORD 를 확인하세요.\n")
    elif "n10s" in str(exc) and "no procedure" in str(exc).lower():
        sys.stderr.write(
            "n10s 프로시저를 찾을 수 없습니다. plugins/ 에 neosemantics JAR 을\n"
            "넣고 컨테이너를 재시작하세요 (README 2단계 참고).\n")
    else:
        sys.stderr.write(f"{name}: {exc}\n")


if __name__ == "__main__":
    main()
