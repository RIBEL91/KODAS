"""임대업무 일정표: 할 일 목록(추가·삭제·체크)을 KODAS 안에 따로 저장한다.

업무 구분
- 일반    : 한 번 하면 끝나는 일. 체크 하나.
- 매월    : 달마다 하는 일. 보고 있는 달(예: 2026-11)마다 따로 체크한다.
- 분기별  : 1~4분기 체크칸. 해마다 따로 체크한다.
- 정해진 달: 고른 달(예: 3·5·7·9·11월)마다 체크칸. 해마다 따로 체크한다.

저장 파일: %APPDATA%\\공문작성기\\업무일정.json
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import os
import re
import uuid

import paths

STORE_NAME = "업무일정.json"
MYDOCS_NAME = "나의공문.json"     # [나의 공문 작성]: 내가 고른 서식 + 일정(같은 구조, 줄마다 'tpl' = 서식 파일)
MYWORK_NAME = "나의업무일정.json"  # [나의 공문 작성 → 나의 업무 일정표]: 내 할 일(처음엔 빈 목록)
KINDS = ("일반", "매월", "분기별", "정해진 달")


def store_path() -> str:
    return os.path.join(paths.data_dir(), STORE_NAME)


def mywork_path() -> str:
    return os.path.join(paths.data_dir(), MYWORK_NAME)


# ---------------- 나의 일정표 목록(탭 여러 개) ----------------
# [나의 공문 작성]에 사용자가 만든 일정표 탭들: [{"name": 탭 이름, "file": KODAS 데이터 안 파일 이름}]
BOARDS_NAME = "나의일정표목록.json"


def boards_path() -> str:
    return os.path.join(paths.data_dir(), BOARDS_NAME)


def board_file(entry: dict) -> str:
    return os.path.join(paths.data_dir(), entry["file"])


def load_boards() -> list[dict]:
    """내가 만든 일정표 목록. 목록 파일이 없으면 '나의 업무 일정표' 하나(나의업무일정.json)."""
    try:
        with open(boards_path(), encoding="utf-8") as f:
            raw = json.load(f)
        out = [{"name": str(b["name"]).strip(), "file": os.path.basename(str(b["file"]))}
               for b in raw.get("boards", []) if isinstance(b, dict) and b.get("name") and b.get("file")]
        return out
    except (OSError, ValueError, AttributeError, KeyError):
        return [{"name": "나의 업무 일정표", "file": MYWORK_NAME}]


def save_boards(boards: list[dict]) -> None:
    path = boards_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"boards": boards}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def new_board(name: str, boards: list[dict]) -> dict:
    """새 일정표 항목(파일 이름은 겹치지 않게 만든다)."""
    used = {b["file"] for b in boards}
    while True:
        fn = f"나의일정표_{uuid.uuid4().hex[:8]}.json"
        if fn not in used and not os.path.exists(os.path.join(paths.data_dir(), fn)):
            return {"name": name.strip(), "file": fn}


def mydocs_path() -> str:
    return os.path.join(paths.data_dir(), MYDOCS_NAME)


# ---------------- 나의 공문 + 임대업무 일정표 (한 목록) ----------------
# 2026-11-26: 두 탭을 하나로 합쳤다. 공문 줄('tpl' 있음)은 [✎ 작성], 업무 줄은 체크만.
MERGED_NAME = "나의공문일정.json"


def merged_path() -> str:
    return os.path.join(paths.data_dir(), MERGED_NAME)


def merged_defaults() -> list[dict]:
    """합친 파일이 처음 없을 때: 예전 나의공문.json 공문 + 업무일정.json 업무(없으면 기본 업무)를 한 목록으로.
    예전 두 파일은 지우지 않고 그대로 둔다."""
    docs = load(mydocs_path(), list)
    work = load(store_path(), default_tasks)
    seen = {t["id"] for t in docs}
    out = docs + [t for t in work if t["id"] not in seen]
    try:                                   # 바로 저장해 둔다(다시 읽을 때 기본 업무 id가 바뀌지 않게)
        save(out, merged_path())
    except OSError:
        pass
    return out


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
    due = _norm_due(t.get("due"), kind)
    if due is not None:
        out["due"] = due
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


# ---------------- 기한(언제까지) ----------------
# 'due': 일반 업무는 날짜 "2026-12-05", 매월·분기별·정해진 달은 그 달 며칠까지(1~31, 0 = 말일).
DUE_SOON, DUE_NEAR, DUE_OVER = "soon", "near", "over"      # 7일 안·3일 안·지남
DUE_COLORS = {DUE_SOON: "#c99700", DUE_NEAR: "#ee7a00", DUE_OVER: "#d93025"}   # 노랑·주황·빨강 글씨


def _norm_due(v, kind):
    if v in (None, ""):
        return None
    if kind == "일반":
        try:
            return dt.date.fromisoformat(str(v)).isoformat()
        except ValueError:
            return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 31 else None


def parse_due(text: str, kind: str, today: dt.date | None = None):
    """입력한 기한 글자 → 저장 값. 빈 글자 → None(기한 없음). 알아볼 수 없으면 ValueError.
    일반: 2026-12-05 · 2026.12.5 · 12-5 · 12/5 · 12월 5일. 그 밖: 15 · 15일 · 말일."""
    s = (text or "").strip()
    if not s:
        return None
    today = today or dt.date.today()
    if kind != "일반":
        if s in ("말일", "말", "0"):
            return 0
        m = re.fullmatch(r"(?:매월\s*)?(\d{1,2})\s*일?(?:까지)?", s)
        if not m or not 1 <= int(m.group(1)) <= 31:
            raise ValueError("며칠까지인지 1~31 사이 숫자나 '말일'로 넣어 주세요. 예: 15")
        return int(m.group(1))
    nums = [int(x) for x in re.findall(r"\d+", s)]
    try:
        if len(nums) == 3:
            y = nums[0] + (2000 if nums[0] < 100 else 0)
            d = dt.date(y, nums[1], nums[2])
        elif len(nums) == 2:
            d = dt.date(today.year, nums[0], nums[1])
            if d < today - dt.timedelta(days=180):          # 1월에 12월 날짜를 넣으면 지난해가 아니라 다음 해
                d = d.replace(year=today.year + 1)
        else:
            raise ValueError
    except ValueError:
        raise ValueError("날짜를 2026-12-05 또는 12-5처럼 넣어 주세요.") from None
    return d.isoformat()


def due_date(task: dict, year: int, month: int) -> dt.date | None:
    """보는 달 기준 그 업무의 기한 날짜(없거나 그 달에 할 일이 아니면 None)."""
    due = task.get("due")
    if due is None:
        return None
    if task.get("kind") == "일반":
        return dt.date.fromisoformat(due)
    if current_slot(task, year, month) is None:
        return None
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, last if due == 0 else min(due, last))


def due_label(task: dict) -> str:
    due = task.get("due")
    if due is None:
        return ""
    if task.get("kind") == "일반":
        d = dt.date.fromisoformat(due)
        return f"{d.month}/{d.day}까지"
    return "말일까지" if due == 0 else f"{due}일까지"


def urgency(d: dt.date | None, today: dt.date | None = None) -> str | None:
    """기한이 지났으면 over, 3일 안이면 near, 7일 안이면 soon, 아니면 None."""
    if d is None:
        return None
    left = (d - (today or dt.date.today())).days
    if left < 0:
        return DUE_OVER
    if left <= 3:
        return DUE_NEAR
    if left <= 7:
        return DUE_SOON
    return None


def all_board_paths() -> list[tuple[str, str]]:
    """[(일정표 이름, 저장 파일)] — 나의 공문·업무 일정표 + 내가 만든 일정표."""
    return [("나의 공문·업무 일정표", merged_path())] + [(b["name"], board_file(b)) for b in load_boards()]


def month_due(today: dt.date | None = None) -> list[dict]:
    """[홈 → 이달 작성해야 할 문서]: 기한을 넣은 것 중 아직 안 끝낸 이번 달(지난 일반 업무 포함) 일.
    [{"title", "date", "urgency", "task", "board"}] 기한 빠른 순."""
    today = today or dt.date.today()
    last = dt.date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    out = []
    for name, path in all_board_paths():
        if not os.path.exists(path):
            continue
        for t in load(path, list):
            d = due_date(t, today.year, today.month)
            key = current_slot(t, today.year, today.month)
            if d is None or key is None or is_done(t, key) or d > last:
                continue
            out.append({"title": render(t["title"], today.year, today.month), "date": d,
                        "urgency": urgency(d, today), "task": t, "board": name})
    out.sort(key=lambda x: x["date"])
    return out
