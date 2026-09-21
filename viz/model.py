"""데이터 소스와 렌더러 사이의 중간 표현.

Neo4j 에서 읽든 Turtle 파일에서 읽든 같은 Graph 를 만들고, 렌더러는
이 Graph 만 봅니다.
"""

from dataclasses import dataclass, field


# 노드 표시 이름을 고를 때의 프로퍼티 우선순위.
#
# n10s 의 handleVocabUris 설정에 따라 프로퍼티 키가 달라질 수 있습니다
# ('IGNORE' -> `label`, 'SHORTEN' -> `ns0__label`). normalize_key() 로
# 접두사를 떼고 나면 아래 이름들로 수렴합니다.
NAME_KEYS = ("label", "name", "prefLabel", "title", "fullName", "orgName")


def normalize_key(key):
    """n10s 가 붙인 네임스페이스 접두사(`ns0__label`)를 제거한다."""
    return key.split("__", 1)[1] if "__" in key else key


def local_name(uri):
    """URI 에서 로컬 이름만 남긴다."""
    for sep in ("#", "/", ":"):
        if sep in uri:
            uri = uri.rsplit(sep, 1)[1] or uri
    return uri


@dataclass
class Node:
    id: str
    name: str
    classes: tuple = ()      # 직접 부여된 클래스(라벨). 예: ("Engineer",)
    root: str = "Other"      # 색상 · 형태를 결정하는 최상위 클래스
    props: dict = field(default_factory=dict)
    depth: int = 0           # 스키마 뷰에서의 subClassOf 깊이
    x: float = 0.0
    y: float = 0.0


@dataclass
class Edge:
    source: str
    target: str
    kind: str                # 관계 타입. 예: "worksFor", "SCO"
    dashed: bool = False


@dataclass
class Graph:
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    title: str = ""
    subtitle: str = ""

    def by_id(self):
        return {n.id: n for n in self.nodes}

    def roots(self):
        """등장하는 최상위 클래스를 CLASS_ORDER 와 무관하게 수집한다."""
        return sorted({n.root for n in self.nodes})

    def kinds(self):
        return sorted({e.kind for e in self.edges})

    def drop_dangling_edges(self):
        """양 끝이 모두 노드 집합에 있는 간선만 남긴다."""
        ids = set(self.by_id())
        self.edges = [e for e in self.edges
                      if e.source in ids and e.target in ids]
        return self

    def degree(self):
        deg = {n.id: 0 for n in self.nodes}
        for e in self.edges:
            deg[e.source] = deg.get(e.source, 0) + 1
            deg[e.target] = deg.get(e.target, 0) + 1
        return deg


def pick_name(props, fallback):
    """프로퍼티 사전에서 표시 이름을 고른다."""
    clean = {normalize_key(k): v for k, v in props.items()}
    for key in NAME_KEYS:
        value = clean.get(key)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    uri = clean.get("uri")
    if isinstance(uri, str) and uri.strip():
        return local_name(uri.strip())
    return fallback


def resolve_roots(nodes, parent_of):
    """각 노드의 최상위 클래스를 SCO 계층에서 확정한다.

    parent_of: 클래스 이름 -> 상위 클래스 이름. 사이클이 있어도 멈춥니다.
    """
    cache = {}

    def climb(cls):
        if cls in cache:
            return cache[cls]
        seen, cur = set(), cls
        while cur in parent_of and parent_of[cur] not in seen:
            seen.add(cur)
            cur = parent_of[cur]
        for name in seen | {cls}:
            cache[name] = cur
        return cur

    for node in nodes:
        # 노드에 여러 클래스가 붙어 있으면 이름 순으로 결정 — 같은 입력에
        # 대해 항상 같은 색이 나오도록.
        for cls in sorted(node.classes):
            root = climb(cls)
            if root:
                node.root = root
                break
    return nodes
