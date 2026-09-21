"""색상 · 형태 토큰.

색상 슬롯은 검증된 카테고리 팔레트에서 골랐습니다. 노드-링크 다이어그램은
어떤 두 노드든 나란히 놓일 수 있으므로 인접 쌍이 아니라 **전체 쌍**
(all-pairs) 기준으로 통과해야 합니다. 8슬롯 기본 팔레트에서 두 모드 모두
all-pairs 를 통과하는 최대 조합이 4개였고, 아래 blue/yellow/magenta/green
이 그 중 하나입니다:

    light (surface #fcfcfb)  CVD ΔE 13.0 · 정상시야 ΔE 19.6 · 전 항목 PASS
    dark  (surface #1a1a19)  CVD ΔE  6.9 · 정상시야 ΔE 19.3 · 전 항목 PASS

두 가지 완화 조치가 위 수치에 딸려 옵니다.

* dark 모드 CVD ΔE 6.9 는 6~8 구간이므로 **보조 부호화가 필수**입니다.
  그래서 최상위 클래스마다 색과 함께 노드 **형태**(SHAPES)를 다르게
  주고, 모든 노드에 이름 라벨을 상시 노출합니다.
* light 모드에서 yellow(2.11:1) 와 magenta(2.62:1) 는 3:1 미만이므로
  **relief 규칙**(라벨 상시 노출)이 적용됩니다. 위와 같은 조치로 충족됩니다.

따라서 색상 슬롯은 4개를 넘기지 않습니다. 5번째 이후의 최상위 클래스는
색을 새로 만들지 않고 중립색 'Other' 로 접습니다(fold).

색상 슬롯은 엔티티(최상위 클래스)에 고정 순서로 배정되며, 필터로 클래스
수가 줄어도 남은 클래스의 색은 바뀌지 않습니다.
"""

# 최상위 클래스 -> 색상 슬롯 배정 순서. 고정이며 순환하지 않습니다.
CLASS_ORDER = ("Person", "Organization", "Project", "Skill")

# (light, dark) 쌍. 위 docstring 의 검증 결과에 대응합니다.
SERIES = {
    "Person":       ("#2a78d6", "#3987e5"),  # slot 1 blue
    "Organization": ("#eda100", "#c98500"),  # slot 4 yellow
    "Project":      ("#e87ba4", "#d55181"),  # slot 5 magenta
    "Skill":        ("#008300", "#008300"),  # slot 6 green
}

# 색상 슬롯을 다 쓴 뒤 접어 넣을 중립색.
OTHER = ("#898781", "#898781")

# 보조 부호화 채널. 색만으로 정체성을 싣지 않기 위한 것이므로
# SERIES 와 같은 키를 갖습니다.
SHAPES = {
    "Person":       "circle",
    "Organization": "square",
    "Project":      "diamond",
    "Skill":        "hexagon",
}
OTHER_SHAPE = "circle"

# 차트 크롬 · 잉크. 텍스트는 절대 시리즈 색을 입지 않고 잉크 토큰만 씁니다.
INK = {
    "surface":   ("#fcfcfb", "#1a1a19"),
    "plane":     ("#f9f9f7", "#0d0d0d"),
    "primary":   ("#0b0b0b", "#ffffff"),
    "secondary": ("#52514e", "#c3c2b7"),
    "muted":     ("#898781", "#898781"),
    "gridline":  ("#e1e0d9", "#2c2c2a"),
    "baseline":  ("#c3c2b7", "#383835"),
}

FONT_STACK = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def assign_colors(roots):
    """최상위 클래스 이름 목록을 (light, dark) 색 쌍에 매핑한다.

    CLASS_ORDER 에 있는 이름이 먼저, 고정 순서로 슬롯을 받는다. 나머지는
    이름 순으로 남은 슬롯을 채우고, 슬롯이 다하면 OTHER 로 접는다.
    """
    known = [name for name in CLASS_ORDER if name in roots]
    extra = sorted(set(roots) - set(CLASS_ORDER))
    free = [SERIES[name] for name in CLASS_ORDER if name not in roots]

    mapping = {name: SERIES[name] for name in known}
    for name in extra:
        mapping[name] = free.pop(0) if free else OTHER
    return mapping


def assign_shapes(roots):
    """최상위 클래스 이름 목록을 노드 형태에 매핑한다."""
    known = [name for name in CLASS_ORDER if name in roots]
    extra = sorted(set(roots) - set(CLASS_ORDER))
    free = [SHAPES[name] for name in CLASS_ORDER if name not in roots]

    mapping = {name: SHAPES[name] for name in known}
    for name in extra:
        mapping[name] = free.pop(0) if free else OTHER_SHAPE
    return mapping
