"""임대업무 일정표: 할 일 목록(추가·삭제·체크)을 KODAS 안에 따로 저장한다.

업무 구분
- 일반    : 한 번 하면 끝나는 일. 체크 하나.
- 매월    : 달마다 하는 일. 보고 있는 달(예: 2026-11)마다 따로 체크한다.
- 분기별  : 1~4분기 체크칸. 해마다 따로 체크한다.
- 정해진 달: 고른 달(예: 3·5·7·9·11월)마다 체크칸. 해마다 따로 체크한다.

저장 파일: %APPDATA%\\공문작성기\\업무일정.json
"""
from __future__ import annotations

import json
import os
import re
import uuid

import paths

STORE_NAME = "업무일정.json"
MYDOCS_NAME = "나의공문.json"     # [나의 공문 작성]: 내가 고른 서식 + 일정(같은 구조, 줄마다 'tpl' = 서식 파일)
KINDS = ("일반", "매월", "분기별", "정해진 달")


def store_path() -> str:
    return os.path.join(paths.data_dir(), STORE_NAME)


def mydocs_path() -> str:
    return os.path.join(paths.data_dir(), MYDOCS_NAME)


def new_task(title: str, kind: str = "일반", months=None) -> dict:
    kind = kind if kind in KINDS else "일반"
    t = {"id": uuid.uuid4().hex[:10], "title": title.strip(), "kind": kind, "done": {}}
    if kind == "정해진 달":
        t["months"] = sorted({int(m) for m in (months or []) if 1 <= int(m) <= 12})
    return t


def slots(task: dict, year: int, month: int) -> list[tuple[str, str]]:
    """그 업무의 체크칸들: [(저장 키, 화면 글자)]. 보고 있는 해·달에 따라 키가 바뀐다."""
    kind = task.get("kind")
    if kind == "매월":
        return [(f"{year}-{month:02d}", f"{month}월")]
    if kind == "분기별":
        return [(f"{year}-Q{q}", f"{q}분기") for q in range(1, 5)]
    if kind == "정해진 달":
        return [(f"{year}-{m:02d}", f"{m}월") for m in task.get("months") or []]
    return [("done", "")]


def is_done(task: dict, key: str) -> bool:
    return bool((task.get("done") or {}).get(key))


def set_done(task: dict, key: str, on: bool) -> None:
    d = task.setdefault("done", {})
    if on:
        d[key] = True
    else:
        d.pop(key, None)


def current_slot(task: dict, year: int, month: int) -> str | None:
    """지금(보고 있는 달)에 해당하는 칸 키: 분기별은 그 달의 분기, 정해진 달은 그 달(없으면 None)."""
    kind = task.get("kind")
    if kind == "분기별":
        return f"{year}-Q{(month - 1) // 3 + 1}"
    if kind == "정해진 달":
        return f"{year}-{month:02d}" if month in (task.get("months") or []) else None
    if kind == "매월":
        return f"{year}-{month:02d}"
    return "done"


def _norm(t) -> dict | None:
    if not isinstance(t, dict) or not str(t.get("title", "")).strip():
        return None
    kind = t.get("kind") if t.get("kind") in KINDS else "일반"
    out = {"id": str(t.get("id") or uuid.uuid4().hex[:10]), "title": str(t["title"]).strip(), "kind": kind,
           "done": {str(k): True for k, v in (t.get("done") or {}).items() if v}}
    if kind == "정해진 달":
        out["months"] = sorted({int(m) for m in t.get("months") or [] if str(m).isdigit() and 1 <= int(m) <= 12})
    if t.get("tpl"):
        out["tpl"] = str(t["tpl"])
    return out


def load(path: str | None = None, defaults=None) -> list[dict]:
    """저장한 목록. 파일이 없으면 defaults()(기본: 임대업무 기본 업무, path를 주면 빈 목록)."""
    if defaults is None:
        defaults = default_tasks if path is None else list
    try:
        with open(path or store_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return defaults()
    tasks = raw.get("tasks") if isinstance(raw, dict) else raw
    return [t for t in (_norm(x) for x in tasks or []) if t]


def save(tasks: list[dict], path: str | None = None) -> None:
    path = path or store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"tasks": tasks}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def default_tasks() -> list[dict]:
    """처음 열 때 넣어 두는 업무(임대 담당자 2026년 11월 메모). 달 글자는 보는 달에 따라 바뀐다.
    필요 없는 것은 지우면 된다."""
    out = [new_task(t, "매월") for t in (
        "예비입주자 순위안내",
        "{월} 입주자 주택소유 정기검색 의뢰",
        "{월} 입주자 주택소유 정기검색 결과",
        "{월} 갱신계약 환불세대 확인",
        "{연도월+2} 갱신계약자 보증금 인상분 납부안내",
        "{월-1} 입주자 변동정보 조회(매월 4일이전)",
        "임대차계약 신고(매월15일날 하기)",
        "갱신서류제출안내10일 ({년월+6}갱신)",
        "갱신세대 자격심사 의뢰({년월+5})",
        "갱신세대 소명안내({월+3})",
        "갱신세대 소명완료({월+3})",
        "갱신계약 안내 20일 ({년월+2} 갱신)<자동,서면>",
        "갱신완료 안내 말일({월-1}) -대장작성하기",
        "신규입주자들 WISE, 코넥스등록({월-1})",
        "신규입주자 실태조사 결과 10일 전 보고",
        "1일 신규입주세대 공가검침기록 및 입주일 기입",
        "10일 신규입주세대 공가검침기록 및 입주일 기입",
        "15일 신규입주세대 공가검침기록 및 입주일 기입",
    )]
    out.append(new_task("중복입주", "분기별"))
    out.append(new_task("통합정례화 모집", "정해진 달", [3, 5, 7, 9, 11]))
    return out


# ---------------- 달 글자 ----------------
# 업무 이름 안의 {월}·{월+3}·{월-1}, {년월+6}(→ 27.5월), {연도월+2}(→ 2027.1월)는 보는 달 기준으로 바뀐다.
MONTH_TOKEN_RE = re.compile(r"\{(월|년월|연도월)\s*([+-]\s*\d+)?\}")
TOKEN_HELP = ("달 글자: {월}=이번 달, {월+3}=3달 뒤, {월-1}=지난달, "
              "{년월+6}=27.5월처럼, {연도월+2}=2027.1월처럼 (보는 달에 따라 바뀝니다)")


def shift(year: int, month: int, n: int) -> tuple[int, int]:
    m = month - 1 + n
    return year + m // 12, m % 12 + 1


def render(title: str, year: int, month: int) -> str:
    """업무 이름의 달 글자를 보는 달(year, month) 기준으로 바꾼다."""
    def one(m):
        y, mo = shift(year, month, int((m.group(2) or "0").replace(" ", "")))
        if m.group(1) == "년월":
            return f"{y % 100:02d}.{mo}월"
        if m.group(1) == "연도월":
            return f"{y}.{mo}월"
        return f"{mo}월"
    return MONTH_TOKEN_RE.sub(one, title)


def move(tasks: list[dict], task: dict, step: int, kinds) -> bool:
    """같은 묶음(kinds) 안에서 task를 위(-1)·아래(+1)로 한 칸 옮긴다. 옮겼으면 True."""
    group = [i for i, t in enumerate(tasks) if t.get("kind") in kinds]
    try:
        pos = next(n for n, i in enumerate(group) if tasks[i] is task)
    except StopIteration:
        return False
    other = pos + step
    if not 0 <= other < len(group):
        return False
    a, b = group[pos], group[other]
    tasks[a], tasks[b] = tasks[b], tasks[a]
    return True
