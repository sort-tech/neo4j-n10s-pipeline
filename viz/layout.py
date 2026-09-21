"""좌표 계산. 외부 의존성 없이 순수 파이썬으로 구현합니다.

두 가지 배치를 씁니다.

* force_layout  — 인스턴스 그래프(A-Box). Fruchterman-Reingold 방식.
* layered_layout — 스키마 그래프(T-Box). subClassOf 깊이를 y축에,
  최상위 클래스 계열을 x축 띠(band)로 나눠 계층이 위에서 아래로 읽히게
  합니다.

두 배치 모두 시드를 고정해 같은 입력이면 같은 그림이 나옵니다.
"""

import math
import random


def force_layout(graph, width, height, iterations=600, seed=20260921):
    """Fruchterman-Reingold. 노드가 수백 개 수준일 때 충분합니다."""
    nodes = graph.nodes
    if not nodes:
        return graph
    if len(nodes) == 1:
        nodes[0].x, nodes[0].y = width / 2, height / 2
        return graph

    rng = random.Random(seed)
    index = {n.id: i for i, n in enumerate(nodes)}
    n = len(nodes)

    # 원 위에 균등 배치한 뒤 약간 흔들어 시작 — 대칭 고착을 막습니다.
    pos = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        pos.append([
            width / 2 + (width / 3) * math.cos(angle) + rng.uniform(-8, 8),
            height / 2 + (height / 3) * math.sin(angle) + rng.uniform(-8, 8),
        ])

    # 같은 노드 쌍을 잇는 간선이 여러 개(관계 타입이 다른 경우)면 한 번만
    # 당기도록 묶습니다. 안 그러면 hasSkill 이 많은 쌍이 과도하게 붙습니다.
    pairs = {}
    for e in graph.edges:
        a, b = index[e.source], index[e.target]
        if a != b:
            pairs[(min(a, b), max(a, b))] = True
    springs = list(pairs)

    area = width * height
    k = math.sqrt(area / n)          # 이상적인 노드 간 거리
    temperature = width / 8.0
    cooling = temperature / (iterations + 1)

    for _ in range(iterations):
        disp = [[0.0, 0.0] for _ in range(n)]

        # 반발력 — 모든 쌍
        for i in range(n):
            xi, yi = pos[i]
            for j in range(i + 1, n):
                dx, dy = xi - pos[j][0], yi - pos[j][1]
                dist2 = dx * dx + dy * dy
                if dist2 < 1e-9:
                    dx, dy = rng.uniform(-1, 1), rng.uniform(-1, 1)
                    dist2 = dx * dx + dy * dy
                dist = math.sqrt(dist2)
                force = (k * k) / dist
                ux, uy = dx / dist, dy / dist
                disp[i][0] += ux * force
                disp[i][1] += uy * force
                disp[j][0] -= ux * force
                disp[j][1] -= uy * force

        # 인장력 — 간선으로 이어진 쌍
        for a, b in springs:
            dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
            dist = math.sqrt(dx * dx + dy * dy) or 1e-6
            force = (dist * dist) / k
            ux, uy = dx / dist, dy / dist
            disp[a][0] -= ux * force
            disp[a][1] -= uy * force
            disp[b][0] += ux * force
            disp[b][1] += uy * force

        # 이동량을 온도로 제한하고 캔버스 안에 가둡니다.
        for i in range(n):
            dx, dy = disp[i]
            dist = math.sqrt(dx * dx + dy * dy) or 1e-6
            step = min(dist, temperature)
            pos[i][0] = min(width, max(0.0, pos[i][0] + dx / dist * step))
            pos[i][1] = min(height, max(0.0, pos[i][1] + dy / dist * step))

        temperature -= cooling

    for node in nodes:
        node.x, node.y = pos[index[node.id]]
    return _fit(graph, width, height,
                pad_top=max(height * 0.06, self_loop_headroom(graph)))


def layered_layout(graph, width, height, hierarchy_kind="SCO"):
    """계층형 배치. y = subClassOf 깊이, x = 최상위 클래스 계열별 띠."""
    nodes = graph.nodes
    if not nodes:
        return graph

    parent = {e.source: e.target
              for e in graph.edges if e.kind == hierarchy_kind}

    # 깊이 계산 — 사이클이 있어도 멈춥니다.
    def depth_of(node_id):
        seen, d, cur = set(), 0, node_id
        while cur in parent and parent[cur] not in seen:
            seen.add(cur)
            cur = parent[cur]
            d += 1
        return d

    for node in nodes:
        node.depth = depth_of(node.id)

    # 계열(최상위 클래스)을 안정된 순서로 나열하고, 각 계열의 폭을
    # "어느 깊이에서든 가장 많은 노드 수" 로 잡습니다.
    from .palette import CLASS_ORDER

    families = {}
    for node in nodes:
        families.setdefault(node.root, []).append(node)

    def family_key(name):
        known = CLASS_ORDER.index(name) if name in CLASS_ORDER else len(CLASS_ORDER)
        return (known, name)

    ordered = sorted(families, key=family_key)
    widths = {}
    for name in ordered:
        per_depth = {}
        for node in families[name]:
            per_depth[node.depth] = per_depth.get(node.depth, 0) + 1
        widths[name] = max(per_depth.values())

    total = sum(widths.values()) or 1
    max_depth = max(node.depth for node in nodes)
    row_gap = height / (max_depth + 1)

    cursor = 0.0
    for name in ordered:
        band = width * widths[name] / total
        per_depth = {}
        for node in sorted(families[name], key=lambda nd: (nd.depth, nd.name)):
            per_depth.setdefault(node.depth, []).append(node)
        for depth, row in per_depth.items():
            for i, node in enumerate(row):
                node.x = cursor + band * (i + 0.5) / len(row)
                node.y = row_gap * (depth + 0.5)
        cursor += band

    return _fit(graph, width, height,
                pad_top=max(height * 0.06, self_loop_headroom(graph)))


def relax_overlaps(graph, radius_of, bounds, label_limit=22, char_w=6.3,
                   iterations=120):
    """라벨 상자가 겹치지 않도록 노드를 조금씩 밀어낸다.

    force 배치는 마크만 보고 자리를 잡으므로 이름이 긴 노드끼리는 라벨이
    겹칩니다. 라벨을 상시 노출하는 것이 색 대비 완화(relief)와 보조
    부호화의 조건이므로, 겹친 라벨은 그냥 두면 안 됩니다.

    마크 자체는 배치가 이미 벌려 두었으므로 여기서는 라벨 상자만 보고
    축별로 최소 이동량만 적용합니다(표준 overlap removal). 결과를 다시
    정규화(_fit)하면 늘어난 만큼 다시 압축되어 겹침이 되살아나므로,
    대신 bounds 안으로 clamp 만 합니다.
    """
    x0, y0, x1, y1 = bounds
    nodes = graph.nodes
    boxes = []
    for node in nodes:
        chars = min(len(node.name), label_limit)
        half_w = max(radius_of(node) + 2.0, 0.5 * char_w * chars + 2.0)
        boxes.append((half_w, radius_of(node) + 15.0))

    for _ in range(iterations):
        moved = False
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                hw = boxes[i][0] + boxes[j][0]
                hh = boxes[i][1] + boxes[j][1]
                dx, dy = b.x - a.x, b.y - a.y
                ox, oy = hw - abs(dx), hh - abs(dy)
                if ox <= 0 or oy <= 0:
                    continue
                # 덜 움직이는 축으로만 밀어낸다.
                if ox < oy:
                    shift = (ox / 2 + 0.5) * (1 if dx >= 0 else -1)
                    a.x -= shift
                    b.x += shift
                else:
                    shift = (oy / 2 + 0.5) * (1 if dy >= 0 else -1)
                    a.y -= shift
                    b.y += shift
                moved = True
        for node in nodes:
            node.x = min(x1, max(x0, node.x))
            node.y = min(y1, max(y0, node.y))
        if not moved:
            break
    return graph


def _fit(graph, width, height, margin=0.06, pad_top=None):
    """좌표를 캔버스에 맞춰 여백을 두고 정규화한다.

    pad_top 은 위쪽 여백(픽셀)을 따로 지정합니다. 자기 자신을 가리키는
    간선(대칭 프로퍼티 등)은 노드 위로 고리를 그리므로 맨 윗줄에 그만큼
    자리를 비워 두지 않으면 잘립니다.
    """
    xs = [n.x for n in graph.nodes]
    ys = [n.y for n in graph.nodes]
    span_x = (max(xs) - min(xs)) or 1.0
    span_y = (max(ys) - min(ys)) or 1.0
    pad_x = width * margin
    pad_bottom = height * margin
    pad_top = pad_bottom if pad_top is None else pad_top
    inner_h = max(1.0, height - pad_top - pad_bottom)
    for node in graph.nodes:
        node.x = pad_x + (node.x - min(xs)) / span_x * (width - 2 * pad_x)
        node.y = pad_top + (node.y - min(ys)) / span_y * inner_h
    return graph


def self_loop_headroom(graph):
    """자기 참조 간선이 있으면 고리 높이만큼, 없으면 0."""
    return 78.0 if any(e.source == e.target for e in graph.edges) else 0.0
