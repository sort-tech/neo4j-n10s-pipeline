"""Graph -> SVG / 단일 파일 HTML 렌더러.

외부 의존성이 없고 CDN 도 쓰지 않습니다. 출력물은 그 자체로 완결된
한 개의 파일입니다.

마크 규격
    * 노드는 최상위 클래스별로 색과 **형태**가 함께 달라집니다. 색만으로
      정체성을 싣지 않기 위한 보조 부호화입니다(palette.py 참고).
    * 겹치는 마크가 서로를 삼키지 않도록 노드마다 2px 서피스 링을 둡니다.
    * 노드 이름은 상시 노출하되 시리즈 색이 아니라 잉크 토큰을 입습니다.
    * 간선은 2px, 격자/축과 같은 열후퇴(recessive) 색입니다.
    * 시리즈가 2개 이상이므로 범례가 항상 있고, 4개 이하이므로 직접
      라벨도 함께 답니다 — 정체성이 색 하나에 기대지 않습니다.
"""

import html
import re

from .palette import FONT_STACK, INK, assign_colors, assign_shapes

LIGHT, DARK = 0, 1


def slug(text):
    """CSS 커스텀 프로퍼티 · 클래스 이름으로 안전한 토큰."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", text) or "x"


def _shape_path(shape, x, y, r):
    """노드 형태를 SVG path 문자열로."""
    if shape == "square":
        s = r * 0.92
        return (f"M{x - s:.1f},{y - s:.1f}h{2 * s:.1f}v{2 * s:.1f}"
                f"h{-2 * s:.1f}Z")
    if shape == "diamond":
        d = r * 1.28
        return (f"M{x:.1f},{y - d:.1f}L{x + d:.1f},{y:.1f}"
                f"L{x:.1f},{y + d:.1f}L{x - d:.1f},{y:.1f}Z")
    if shape == "hexagon":
        import math
        pts = []
        for i in range(6):
            a = math.pi / 6 + i * math.pi / 3
            pts.append(f"{x + r * 1.12 * math.cos(a):.1f},"
                       f"{y + r * 1.12 * math.sin(a):.1f}")
        return "M" + "L".join(pts) + "Z"
    return None  # circle -> <circle> 로 그립니다


BASE_RADIUS = 9.0
LABEL_LIMIT = 22


def radius_fn(graph, base=BASE_RADIUS):
    """노드 -> 반지름 함수. 차수가 큰 노드를 조금 크게 그립니다.

    배치 단계의 라벨 겹침 제거(layout.relax_overlaps)와 렌더 단계가
    같은 크기를 써야 하므로 여기서 한 번만 정의합니다.
    """
    deg = graph.degree()
    top = max(deg.values()) if deg else 1
    top = top or 1
    return lambda node: base + 5.0 * (deg.get(node.id, 0) / top) ** 0.5


def _trim(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tooltip_lines(node):
    lines = [node.name]
    if node.classes:
        lines.append("클래스: " + ", ".join(node.classes))
    skip = {"uri", "label", "name"}
    for key in sorted(node.props):
        if key in skip:
            continue
        value = node.props[key]
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value)
        lines.append(f"{key}: {value}")
    return lines


class Renderer:
    def __init__(self, graph, width=1180, height=760, mode=LIGHT,
                 node_radius=BASE_RADIUS, label_limit=LABEL_LIMIT,
                 edge_labels=False):
        self.g = graph
        self.w = width
        self.h = height
        self.mode = mode
        self.label_limit = label_limit
        self.edge_labels = edge_labels

        roots = graph.roots()
        self.colors = assign_colors(roots)
        self.shapes = assign_shapes(roots)
        self.deg = graph.degree()
        self._radius = radius_fn(graph, base=node_radius)

    # ------------------------------------------------------------ helpers

    def ink(self, role):
        return INK[role][self.mode]

    def color(self, root):
        return self.colors[root][self.mode]

    def radius(self, node):
        return self._radius(node)

    # --------------------------------------------------------------- svg

    def svg_body(self, interactive=False):
        """HTML 안에 넣을 <svg> 요소 하나."""
        return (f'<svg class="graph" viewBox="0 0 {self.w} {self.h}" '
                f'width="100%" role="img" '
                f'aria-label="{html.escape(self.g.title)}" '
                f'xmlns="http://www.w3.org/2000/svg">'
                f"{self._inner(interactive)}</svg>")

    def _inner(self, interactive=False):
        """defs + 간선 + 노드 + 라벨. <svg> 래퍼는 호출자가 답니다."""
        pos = self.g.by_id()
        out = [
            "<defs>",
            '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M0,1L9,5L0,9z" fill="{self.ink("baseline")}"/></marker>',
            "</defs>",
        ]

        # --- 간선 (노드보다 먼저 = 아래에 깔림)
        #
        # 같은 노드 쌍을 잇는 간선이 여러 개면 곡률을 달리해 겹치지 않게
        # 하고, 라벨은 각 호(arc)의 정점에 둡니다. 직선 하나에 라벨을 모두
        # 쌓으면 서로 덧그려집니다.
        labels = []
        out.append('<g class="edges" fill="none">')
        for group in self._edge_groups():
            # 계층(SCO)은 직선으로 두고, 나머지만 곡률을 나눠 갖습니다.
            spread = [i for i, e in enumerate(group) if e.kind != "SCO"]
            for i, e in enumerate(group):
                a, b = pos[e.source], pos[e.target]
                dash = ' stroke-dasharray="5 4"' if e.dashed else ""
                rank = spread.index(i) if i in spread else None
                if e.source == e.target:
                    path, lx, ly = self._self_loop(a, rank or 0)
                else:
                    curve = self._curve(a, b, rank, len(spread))
                    path, lx, ly = self._arc(a, b, curve)
                out.append(
                    f'<path class="edge" data-kind="{html.escape(e.kind)}" '
                    f'data-a="{html.escape(e.source)}" '
                    f'data-b="{html.escape(e.target)}" '
                    f'd="{path}" stroke="{self.ink("baseline")}" '
                    f'stroke-width="2"{dash} marker-end="url(#arrow)"/>'
                )
                # 라벨은 선별적으로. 계층 간선은 실선/점선 구분과 부제로
                # 이미 설명되므로 "SCO" 를 열 번 반복해 적지 않습니다.
                if self.edge_labels and e.kind != "SCO":
                    labels.append(
                        f'<text class="edge-label" '
                        f'data-kind="{html.escape(e.kind)}" '
                        f'x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle">'
                        f"{html.escape(e.kind)}</text>"
                    )
        out.append("</g>")

        # 간선 라벨은 선 위·노드 아래. 서피스 색 외곽선으로 선을 뚫습니다.
        if labels:
            out.append(f'<g class="edge-labels" font-size="9.5" '
                       f'font-family=\'{FONT_STACK}\' '
                       f'fill="{self.ink("muted")}" paint-order="stroke" '
                       f'stroke="{self.ink("surface")}" stroke-width="3.5" '
                       f'stroke-linejoin="round">')
            out.extend(labels)
            out.append("</g>")

        # --- 노드
        out.append('<g class="nodes">')
        for node in self.g.nodes:
            fill = self.color(node.root)
            shape = self.shapes[node.root]
            r = self.radius(node)
            path = _shape_path(shape, node.x, node.y, r)
            tip = html.escape("\n".join(_tooltip_lines(node)))
            attrs = (f'class="node" data-id="{html.escape(node.id)}" '
                     f'data-root="{html.escape(node.root)}" '
                     f'data-tip="{tip}"')
            out.append(f"<g {attrs}>")
            # 2px 서피스 링 — 마크가 겹쳐도 경계가 남습니다.
            # class="mark" 로 채움색 규칙의 대상을 마크로 한정합니다.
            # (투명 히트 타깃까지 칠해지면 형태 채널이 가려집니다.)
            ring = self.ink("surface")
            if path:
                out.append(f'<path class="mark" d="{path}" fill="{fill}" '
                           f'stroke="{ring}" stroke-width="2"/>')
            else:
                out.append(f'<circle class="mark" cx="{node.x:.1f}" '
                           f'cy="{node.y:.1f}" r="{r:.1f}" fill="{fill}" '
                           f'stroke="{ring}" stroke-width="2"/>')
            if not interactive:
                out.append("</g>")
                continue
            # 히트 타깃은 마크보다 크게.
            out.append(f'<circle class="hit" cx="{node.x:.1f}" '
                       f'cy="{node.y:.1f}" r="{max(r + 8, 16):.1f}" '
                       f'fill="transparent"/>')
            out.append("</g>")
        out.append("</g>")

        # --- 직접 라벨. 노드 위가 아니라 옆/아래에 두고 잉크 색을 씁니다.
        out.append(f'<g class="labels" font-family=\'{FONT_STACK}\' '
                   f'font-size="11" fill="{self.ink("primary")}" '
                   f'paint-order="stroke" stroke="{self.ink("surface")}" '
                   f'stroke-width="3" stroke-linejoin="round">')
        for node in self.g.nodes:
            dy = self.radius(node) + 12
            out.append(
                f'<text class="label" data-id="{html.escape(node.id)}" '
                f'x="{node.x:.1f}" y="{node.y + dy:.1f}" '
                f'text-anchor="middle">'
                f'{html.escape(_trim(node.name, self.label_limit))}</text>'
            )
        out.append("</g>")
        return "\n".join(out)

    # ------------------------------------------------------- edge geometry

    def _edge_groups(self):
        """같은 노드 쌍을 잇는 간선끼리 묶는다. 순서는 안정적."""
        groups, order = {}, []
        for e in self.g.edges:
            key = (min(e.source, e.target), max(e.source, e.target))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(e)
        return [groups[key] for key in order]

    def _curve(self, a, b, rank, count):
        """간선의 곡률 크기(픽셀). rank 가 None(=계층 간선)이면 직선.

        방향은 _arc 가 정합니다. 같은 쌍의 간선이 여럿이면 위로 겹겹이
        중첩되게 크기만 키웁니다 — 아래로 내려보내면 노드 이름 라벨과
        겹칩니다(라벨은 항상 마크 아래에 있습니다).
        """
        if rank is None:
            return 0.0
        length = ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5
        # 긴 간선은 더 크게 휘게 — 같은 행에 놓인 간선들의 라벨이 행
        # 축에서 멀어져 서로, 그리고 노드와 겹치지 않습니다.
        base = 22.0 + 0.055 * length
        return base * (1.0 + 0.85 * rank)

    def _arc(self, a, b, curve):
        """(path, label_x, label_y). curve=0 이면 직선.

        호는 항상 **위쪽**으로 부풀립니다. 노드 이름 라벨이 마크 아래에
        있으므로 위로 휘어야 라벨 띠를 비켜갑니다.
        """
        dx, dy = b.x - a.x, b.y - a.y
        dist = (dx * dx + dy * dy) ** 0.5 or 1.0
        ux, uy = dx / dist, dy / dist
        ra, rb = self.radius(a) + 1.5, self.radius(b) + 5.0
        ax, ay = a.x + ux * ra, a.y + uy * ra
        bx, by = b.x - ux * rb, b.y - uy * rb
        if abs(curve) < 0.5:
            return (f"M{ax:.1f},{ay:.1f}L{bx:.1f},{by:.1f}",
                    (ax + bx) / 2, (ay + by) / 2 - 5)
        # 중점에서 수직으로 밀어낸 제어점 하나 (2차 베지어).
        px, py = -uy, ux
        if py > 0 or (abs(py) < 1e-9 and px > 0):
            px, py = -px, -py          # 항상 위(수직선이면 왼쪽)로
        cx = (ax + bx) / 2 + px * curve
        cy = (ay + by) / 2 + py * curve
        # t=0.5 지점 = (A + 2C + B) / 4
        return (f"M{ax:.1f},{ay:.1f}Q{cx:.1f},{cy:.1f} {bx:.1f},{by:.1f}",
                (ax + 2 * cx + bx) / 4, (ay + 2 * cy + by) / 4 - 5)

    def _self_loop(self, node, index=0):
        """자기 자신을 가리키는 간선(예: 대칭 프로퍼티)을 작은 고리로."""
        import math

        r = self.radius(node)
        size = 26.0 + 15.0 * index
        a1, a2 = math.radians(-58), math.radians(-122)
        x1, y1 = node.x + r * math.cos(a1), node.y + r * math.sin(a1)
        x2, y2 = node.x + r * math.cos(a2), node.y + r * math.sin(a2)
        c1x, c1y = x1 + size, y1 - size * 1.9
        c2x, c2y = x2 - size, y2 - size * 1.9
        path = (f"M{x1:.1f},{y1:.1f}C{c1x:.1f},{c1y:.1f} "
                f"{c2x:.1f},{c2y:.1f} {x2:.1f},{y2:.1f}")
        # 3차 베지어의 t=0.5 = (P0 + 3C1 + 3C2 + P3) / 8
        return (path,
                (x1 + 3 * c1x + 3 * c2x + x2) / 8,
                (y1 + 3 * c1y + 3 * c2y + y2) / 8 - 4)

    # ---------------------------------------------------------- documents

    # 제목 영역과 범례 영역의 높이.
    HEAD_H, FOOT_H = 68, 34

    def to_svg(self):
        """단독 .svg 파일. OS 다크 모드를 따라갑니다."""
        light = {role: INK[role][LIGHT] for role in INK}
        dark = {role: INK[role][DARK] for role in INK}
        total_h = self.h + self.HEAD_H + self.FOOT_H

        css = [
            f".bg{{fill:{light['surface']}}}",
            "@media (prefers-color-scheme: dark){"
            f".bg{{fill:{dark['surface']}}}"
            f".labels{{fill:{dark['primary']};stroke:{dark['surface']}}}"
            f".edge{{stroke:{dark['baseline']}}}"
            # 화살촉과 마크의 서피스 링도 함께 넘어가야 합니다. 링은
            # 겹친 마크를 갈라 주는 장치이므로 밝게 남으면 후광이 됩니다.
            f"#arrow > path{{fill:{dark['baseline']}}}"
            f".mark{{stroke:{dark['surface']}}}"
            f".edge-labels{{fill:{dark['muted']};stroke:{dark['surface']}}}"
            f".ink-muted{{fill:{dark['muted']}}}"
            f".ink-primary{{fill:{dark['primary']}}}"
            f".ink-secondary{{fill:{dark['secondary']}}}"
            "}",
        ]
        # 노드 채움색은 모드별로 다르므로 다크용 규칙을 얹습니다.
        # 범례 스와치도 같은 data-root 를 갖고 있어 함께 바뀝니다.
        for root, (lo, hi) in self.colors.items():
            if lo != hi:
                css.append("@media (prefers-color-scheme: dark){"
                           f'[data-root="{root}"] > .mark,'
                           f'.mark[data-root="{root}"]'
                           f"{{fill:{hi}}}}}")

        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {self.w} {total_h}" '
            f'width="{self.w}" height="{total_h}" '
            f"font-family='{FONT_STACK}'>"
            f"<style>{''.join(css)}</style>"
            f'<rect class="bg" width="100%" height="100%"/>'
            f'<text class="ink-primary" x="24" y="32" font-size="17" '
            f'font-weight="600" fill="{light["primary"]}">'
            f"{html.escape(self.g.title)}</text>"
            f'<text class="ink-secondary" x="24" y="53" font-size="12" '
            f'fill="{light["secondary"]}">'
            f"{html.escape(self.g.subtitle)}</text>"
            f'<g transform="translate(0,{self.HEAD_H})">'
            f"{self._inner(interactive=False)}</g>"
            f"{self._svg_legend(y=self.h + self.HEAD_H + 22)}"
            f"</svg>"
        )

    def _svg_legend(self, y):
        """정적 SVG 용 범례. 시리즈가 2개 이상이면 항상 존재합니다."""
        parts = ['<g font-size="11.5">']
        x = 24.0
        for root in self.g.roots():
            shape = self.shapes[root]
            path = _shape_path(shape, x + 6, y - 4, 6)
            fill = self.colors[root][LIGHT]
            if path:
                parts.append(f'<path data-root="{html.escape(root)}" '
                             f'd="{path}" fill="{fill}"/>')
            else:
                parts.append(f'<circle data-root="{html.escape(root)}" '
                             f'cx="{x + 6:.1f}" cy="{y - 4:.1f}" r="6" '
                             f'fill="{fill}"/>')
            parts.append(f'<text class="ink-secondary" x="{x + 18:.1f}" '
                         f'y="{y:.1f}" fill="{INK["secondary"][LIGHT]}">'
                         f"{html.escape(root)}</text>")
            x += 28 + 7.4 * len(root)
        parts.append("</g>")
        return "".join(parts)

    def to_html(self):
        """단일 파일 HTML. 테마 토글 · 호버 툴팁 · 관계 타입 필터 포함."""
        kinds = self.g.kinds()
        chips = "\n".join(
            f'<button class="chip" data-kind="{html.escape(k)}" '
            f'aria-pressed="true">{html.escape(k)}</button>' for k in kinds
        )
        legend = "\n".join(
            f'<span class="legend-item">'
            f'<span class="swatch swatch-{slug(root)}" '
            f'data-shape="{self.shapes[root]}"></span>{html.escape(root)}'
            f"</span>"
            for root in self.g.roots()
        )
        series_css = "\n".join(
            f"  --series-{slug(root)}: {self.colors[root][LIGHT]};"
            for root in self.g.roots()
        )
        series_css_dark = "\n".join(
            f"    --series-{slug(root)}: {self.colors[root][DARK]};"
            for root in self.g.roots()
        )
        fills = "\n".join(
            f'.node[data-root="{html.escape(root)}"] > .mark'
            f"{{fill:var(--series-{slug(root)})}}"
            f".swatch-{slug(root)}{{background:var(--series-{slug(root)})}}"
            for root in self.g.roots()
        )
        table_rows = "\n".join(
            f"<tr><td>{html.escape(node.name)}</td>"
            f"<td>{html.escape(', '.join(node.classes) or '-')}</td>"
            f"<td>{html.escape(node.root)}</td>"
            f"<td>{self.deg.get(node.id, 0)}</td></tr>"
            for node in sorted(self.g.nodes, key=lambda n: (n.root, n.name))
        )
        ink_light = "\n".join(f"  --{role}: {INK[role][LIGHT]};" for role in INK)
        ink_dark = "\n".join(f"    --{role}: {INK[role][DARK]};" for role in INK)

        return _HTML_TEMPLATE.format(
            title=html.escape(self.g.title),
            subtitle=html.escape(self.g.subtitle),
            font=FONT_STACK,
            ink_light=ink_light,
            ink_dark=ink_dark,
            series_css=series_css,
            series_css_dark=series_css_dark,
            fills=fills,
            svg=self.svg_body(interactive=True),
            chips=chips,
            legend=legend,
            table_rows=table_rows,
            node_count=len(self.g.nodes),
            edge_count=len(self.g.edges),
        )


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  color-scheme: light;
{ink_light}
{series_css}
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    color-scheme: dark;
{ink_dark}
{series_css_dark}
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
{ink_dark}
{series_css_dark}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 24px 16px 48px;
  background: var(--plane); color: var(--primary);
  font-family: {font};
}}
.wrap {{ max-width: 1240px; margin: 0 auto; }}
header {{ display: flex; flex-wrap: wrap; gap: 12px 16px;
  align-items: baseline; justify-content: space-between; }}
h1 {{ font-size: 19px; margin: 0; font-weight: 600; }}
.sub {{ color: var(--secondary); font-size: 13px; margin: 6px 0 0; }}
.meta {{ color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }}
button {{ font: inherit; cursor: pointer; }}
.toolbar {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  margin: 18px 0 10px; }}
.toolbar .spacer {{ flex: 1 1 auto; }}
.chip {{
  border: 1px solid var(--baseline); background: var(--surface);
  color: var(--secondary); border-radius: 999px;
  padding: 4px 11px; font-size: 12px; line-height: 1.5;
}}
.chip[aria-pressed="false"] {{ color: var(--muted); opacity: .55; }}
.chip:hover {{ border-color: var(--muted); }}
.ghost {{ border: 1px solid var(--baseline); background: var(--surface);
  color: var(--secondary); border-radius: 8px; padding: 5px 11px; font-size: 12px; }}
.panel {{
  position: relative; margin-top: 8px; background: var(--surface);
  border: 1px solid var(--gridline); border-radius: 12px; padding: 4px;
}}
.graph {{ display: block; width: 100%; height: auto; }}
/* 인라인 속성은 light 값으로 굽혀져 있으므로 테마 토글이 따라오도록
   역할(role) 토큰으로 덮어씁니다. CSS 는 presentation attribute 를
   이깁니다. */
.edge {{ stroke: var(--baseline); }}
#arrow > path {{ fill: var(--baseline); }}
.mark {{ stroke: var(--surface); }}
.labels {{ fill: var(--primary); stroke: var(--surface); }}
.edge-labels {{ fill: var(--muted); stroke: var(--surface); }}
.edge {{ transition: opacity .12s; }}
.edge.off, .edge-label.off {{ opacity: 0; pointer-events: none; }}
.edge.dim {{ opacity: .12; }}
.node {{ cursor: pointer; }}
.node.dim {{ opacity: .22; }}
.label.dim {{ opacity: .22; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 12px 2px 0;
  font-size: 12.5px; color: var(--secondary); }}
.legend-item {{ display: inline-flex; align-items: center; gap: 7px; }}
.swatch {{ width: 12px; height: 12px; display: inline-block; }}
.swatch[data-shape="circle"] {{ border-radius: 50%; }}
.swatch[data-shape="square"] {{ border-radius: 2px; }}
.swatch[data-shape="diamond"] {{ transform: rotate(45deg) scale(.86); }}
.swatch[data-shape="hexagon"] {{
  clip-path: polygon(25% 3%, 75% 3%, 100% 50%, 75% 97%, 25% 97%, 0% 50%); }}
#tip {{
  position: fixed; z-index: 10; pointer-events: none; opacity: 0;
  transition: opacity .1s; max-width: 280px;
  background: var(--surface); color: var(--primary);
  border: 1px solid var(--baseline); border-radius: 8px;
  padding: 8px 10px; font-size: 12px; line-height: 1.5;
  white-space: pre-line; box-shadow: 0 4px 16px rgba(0,0,0,.14);
}}
#tip.on {{ opacity: 1; }}
details {{ margin-top: 18px; font-size: 13px; color: var(--secondary); }}
summary {{ cursor: pointer; }}
table {{ border-collapse: collapse; margin-top: 10px; width: 100%;
  font-size: 12.5px; }}
th, td {{ text-align: left; padding: 5px 10px;
  border-bottom: 1px solid var(--gridline); }}
th {{ color: var(--secondary); font-weight: 600; }}
td:last-child {{ font-variant-numeric: tabular-nums; }}
@media (max-width: 640px) {{
  body {{ padding: 16px 16px 40px; }}
  h1 {{ font-size: 17px; }}
}}
{fills}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>{title}</h1>
      <p class="sub">{subtitle}</p>
    </div>
    <div class="meta">노드 {node_count} · 간선 {edge_count}</div>
  </header>

  <div class="toolbar" role="group" aria-label="관계 타입 필터">
    {chips}
    <span class="spacer"></span>
    <button class="ghost" id="all">전체</button>
    <button class="ghost" id="theme">테마</button>
  </div>

  <div class="panel">{svg}</div>

  <div class="legend">{legend}</div>

  <details>
    <summary>노드 표로 보기</summary>
    <table>
      <thead><tr><th>이름</th><th>클래스</th><th>최상위 클래스</th>
      <th>연결 수</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </details>
</div>
<div id="tip" role="tooltip"></div>
<script>
const tip = document.getElementById('tip');
const edges = [...document.querySelectorAll('.edge')];
const edgeLabels = [...document.querySelectorAll('.edge-label')];
const nodes = [...document.querySelectorAll('.node')];
const labels = [...document.querySelectorAll('.label')];
const chips = [...document.querySelectorAll('.chip')];

/* --- 관계 타입 필터. 색은 엔티티에 고정이므로 필터를 걸어도
       남은 노드의 색은 바뀌지 않습니다. --- */
const active = new Set(chips.map(c => c.dataset.kind));
function applyFilter() {{
  for (const el of edges.concat(edgeLabels)) {{
    el.classList.toggle('off', !active.has(el.dataset.kind));
  }}
  const live = new Set();
  for (const e of edges) {{
    if (active.has(e.dataset.kind)) {{ live.add(e.dataset.a); live.add(e.dataset.b); }}
  }}
  const full = active.size === chips.length;
  for (const n of nodes) n.classList.toggle('dim', !full && !live.has(n.dataset.id));
  for (const l of labels) l.classList.toggle('dim', !full && !live.has(l.dataset.id));
}}
for (const chip of chips) {{
  chip.addEventListener('click', () => {{
    const on = chip.getAttribute('aria-pressed') === 'true';
    chip.setAttribute('aria-pressed', String(!on));
    if (on) active.delete(chip.dataset.kind); else active.add(chip.dataset.kind);
    applyFilter();
  }});
}}
document.getElementById('all').addEventListener('click', () => {{
  for (const chip of chips) {{
    chip.setAttribute('aria-pressed', 'true');
    active.add(chip.dataset.kind);
  }}
  applyFilter();
}});

/* --- 노드 호버: 툴팁 + 이웃 강조 --- */
function showTip(evt, text) {{
  tip.textContent = text;
  tip.classList.add('on');
  const pad = 14, box = tip.getBoundingClientRect();
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + box.width > innerWidth - 8) x = evt.clientX - box.width - pad;
  if (y + box.height > innerHeight - 8) y = evt.clientY - box.height - pad;
  tip.style.left = Math.max(8, x) + 'px';
  tip.style.top = Math.max(8, y) + 'px';
}}
for (const node of nodes) {{
  const id = node.dataset.id;
  const move = evt => showTip(evt, node.dataset.tip);
  node.addEventListener('pointermove', move);
  node.addEventListener('pointerenter', evt => {{
    move(evt);
    const near = new Set([id]);
    for (const e of edges) {{
      if (e.classList.contains('off')) continue;
      if (e.dataset.a === id) near.add(e.dataset.b);
      if (e.dataset.b === id) near.add(e.dataset.a);
    }}
    for (const e of edges) {{
      if (e.classList.contains('off')) continue;
      e.classList.toggle('dim', e.dataset.a !== id && e.dataset.b !== id);
    }}
    for (const n of nodes) n.classList.toggle('dim', !near.has(n.dataset.id));
    for (const l of labels) l.classList.toggle('dim', !near.has(l.dataset.id));
  }});
  node.addEventListener('pointerleave', () => {{
    tip.classList.remove('on');
    for (const e of edges) e.classList.remove('dim');
    applyFilter();
  }});
}}

/* --- 테마 토글 --- */
document.getElementById('theme').addEventListener('click', () => {{
  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  const now = document.documentElement.dataset.theme || (dark ? 'dark' : 'light');
  document.documentElement.dataset.theme = now === 'dark' ? 'light' : 'dark';
}});
</script>
</body>
</html>
"""
