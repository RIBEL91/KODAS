"""단지기본정보 — 관리소명·평형처럼 여러 공문에 되풀이해 들어가는 값.

서식에서는 {단지:관리소명}, {단지:평형1}처럼 쓴다. 공문마다 입력하지 않고
[단지기본정보] 화면(예전 환경 설정과 합침)에 한 번 넣어 두면 모든 공문에 자동으로 들어간다.
관리소명·단지명은 관리소 정보 칸({관리소}·{단지명})과 같은 값을 쓴다.

저장: settings.json의 "complex_info" (계정과 달리 암호화하지 않는다)
"""
import re

PREFIX = "단지:"
MAX_TYPES = 6          # 평형(전용면적) 칸 기본 수 — [➕ 평형 추가]로 TYPE_LIMIT까지 늘린다
TYPE_LIMIT = 20        # 평형 칸 최대 수

# (키, 화면 이름, 처음 값, 설명) — 처음 값은 서식을 만든 광주우산3 기준
BASIC = [
    ("관리소명", "관리소명", "광주우산3관리소", "공문 관련 문서번호 앞에 붙습니다. 예: 광주우산3관리소-1764"),
    ("단지명", "단지명", "광주우산3", "예: 광주우산3"),
    ("단지약칭", "단지 약칭", "우산3", "예: 우산3 (우산3마이홈, 우산3단지 입주민)"),
    ("공급유형", "공급유형", "영구임대", "예: 영구임대, 국민임대"),
    ("총세대수", "총세대수", "", "비우면 평형별 세대수를 더해 자동으로 넣습니다"),
    ("주거행복지원센터", "주거행복지원센터", "광주우산3 주거행복지원센터", ""),
    ("주거복지상담실", "주거복지상담실", "광주우산3주거복지상담실", ""),
]
ACCOUNT = [
    ("계좌번호", "계좌번호", "농협 052-01-096795 주택관리공단㈜ 광주우산3", "관리비예치금 청구 등"),
    ("사업자등록번호", "사업자등록번호", "409-85-12020", ""),
    ("경비용역업체", "경비용역 업체", "신서림에스앤에스(주)", "외상매입금 설정 등"),
    ("청소용역업체", "청소용역 업체", "(주)정상에스앤에스", ""),
    ("승강기유지업체", "승강기유지 업체", "한국미쓰비시 엘리베이터", ""),
]
TYPES_DEFAULT = [("39.85", "588"), ("39.87", "149"), ("43.92", "239"), ("45.26", "298")]

# 자동으로 만들어지는 값(직접 입력하지 않음)
DERIVED = [
    ("평형수", "평형 개수"),
    ("평형목록", "평형 목록 (39.85㎡, 39.87㎡ …)"),
    ("평형별세대", "평형별 세대수 (39.85㎡ 588세대 …)"),
]


def defaults() -> dict:
    d = {k: v for k, _, v, _ in BASIC + ACCOUNT}
    for i, (area, n) in enumerate(TYPES_DEFAULT, 1):
        d[f"평형{i}"], d[f"평형{i}세대수"] = area, n
    d["추가항목"] = ""
    return d


# 단지명 하나로 관리소명·단지약칭을 만든다(예: 광주우산3 → 광주우산3관리소 · 우산3).
REGIONS = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
           "충북", "충남", "전북", "전남", "경북", "경남", "제주")


def _base(name: str) -> str:
    name = re.sub(r"\s+", "", str(name or ""))
    return name[:-2] if name.endswith("단지") and len(name) > 2 else name


def office_name(complex_name: str) -> str:
    """단지명 → 관리소명(문서번호 앞 이름). 광주우산3 → 광주우산3관리소"""
    b = _base(complex_name)
    return "" if not b else (b if b.endswith("관리소") else b + "관리소")


def short_name(complex_name: str) -> str:
    """단지명 → 단지 약칭(앞의 지역 이름을 뗀다). 광주우산3 → 우산3"""
    b = _base(complex_name)
    for r in REGIONS:
        if b.startswith(r) and len(b) > len(r):
            return b[len(r):]
    return b


def _num(s) -> float:
    s = re.sub(r"[^\d.]", "", str(s or ""))
    try:
        return float(s) if s not in ("", ".") else 0.0
    except ValueError:
        return 0.0


def extra_items(text: str) -> dict:
    """'이름=값' 줄들 → dict (사용자가 직접 추가하는 항목)"""
    out = {}
    for line in (text or "").splitlines():
        k, eq, v = line.partition("=")
        k = re.sub(r"[{}|:=\s]+", "", k)
        if eq and k:
            out[k] = v.strip()
    return out


def type_count(info: dict | None) -> int:
    """평형 칸 수: 기본 6칸, 그보다 뒤 칸(평형7 …)에 값이 있으면 그 칸까지."""
    n = MAX_TYPES
    for i in range(MAX_TYPES + 1, TYPE_LIMIT + 1):
        if str((info or {}).get(f"평형{i}", "") or "").strip() or str((info or {}).get(f"평형{i}세대수", "") or "").strip():
            n = i
    return n


def resolve(info: dict) -> dict:
    """저장된 단지기본정보 → 서식에 넣을 값 전체(자동 계산 값 포함). 키에는 '단지:'를 붙이지 않는다."""
    info = {**defaults(), **(info or {})}
    out = {k: str(info.get(k, "") or "").strip() for k, *_ in BASIC + ACCOUNT}
    types = []
    for i in range(1, type_count(info) + 1):
        area = str(info.get(f"평형{i}", "") or "").strip().replace("㎡", "")
        n = str(info.get(f"평형{i}세대수", "") or "").strip()
        out[f"평형{i}"], out[f"평형{i}세대수"] = area, (f"{int(_num(n)):,}" if n else "")
        if area:
            types.append((area, n))
    if not out["총세대수"] and any(n for _, n in types):
        out["총세대수"] = f"{int(sum(_num(n) for _, n in types)):,}"
    elif out["총세대수"]:
        out["총세대수"] = f"{int(_num(out['총세대수'])):,}"
    out["평형수"] = str(len(types)) if types else ""
    out["평형목록"] = ", ".join(f"{a}㎡" for a, _ in types)
    out["평형별세대"] = ", ".join(f"{a}㎡ {int(_num(n)):,}세대" if n else f"{a}㎡" for a, n in types)
    out.update(extra_items(info.get("추가항목", "")))
    return out


def all_names() -> list[str]:
    names = [k for k, *_ in BASIC + ACCOUNT]
    for i in range(1, TYPE_LIMIT + 1):
        names += [f"평형{i}", f"평형{i}세대수"]
    return names + [k for k, _ in DERIVED]
