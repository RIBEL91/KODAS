"""비슷한 공문 찾기: 검색어와 서식(이름·제목·구분·묶음·본문)이 얼마나 닮았는지 점수를 매긴다.

- 낱말 일치: 검색어를 띄어쓰기로 나눈 낱말이 이름·제목에 있으면 높게, 구분·묶음은 중간, 본문은 낮게.
- 글자 닮음: 띄어쓰기를 무시한 두 글자 조각(바이그램)이 얼마나 겹치는지(예: '승강기점검' ↔ '승강기 자체점검').
점수가 0보다 크면 결과에 넣고, 높은 차례로 돌려준다.
"""
import re

_SPLIT = re.compile(r"[\s,·/()\[\]「」『』_\-]+")
_FIELD = re.compile(r"\{[^{}]*\}")


def _plain(s: str) -> str:
    return (s or "").replace(" ", "")


def _bigrams(s: str) -> set:
    s = _plain(s)
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else ({s} if s else set())


def _dice(a: set, b: set) -> float:
    return 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.0


def clean_line(line: str) -> str:
    """본문 한 줄을 사람이 읽기 좋게: {빈칸} → ○○, 표 칸막이·여분 공백 정리."""
    line = _FIELD.sub("○○", line)
    line = line.replace("|", " ").replace("<br>", " ")
    return re.sub(r"\s+", " ", line).strip(" -^<")


def tokens(q: str) -> list[str]:
    return [w for w in _SPLIT.split(q or "") if w]


def score(t, q: str) -> tuple[float, str, str]:
    """(점수, 어디서 맞았는지 '제목'/'분류'/'내용'/'비슷', 본문 한 줄 미리보기)."""
    words = tokens(q)
    if not words:
        return 0.0, "", ""
    name = f"{t.label} {t.title}"
    kind = f"{t.group} {t.bundle} {t.area}"
    body = t.body or ""
    s, where = 0.0, ""
    pn, pk, pb = _plain(name), _plain(kind), _plain(body)
    whole = _plain(q)
    if len(whole) >= 2 and whole in pn:
        s += 6
        where = "제목"
    for w in words:
        if w in pn:
            s += 3
            where = where or "제목"
        elif w in pk:
            s += 2
            where = where or "분류"
        elif w in pb:
            s += 1 + min(2, pb.count(w) - 1) * 0.3
            where = where or "내용"
    d = _dice(_bigrams(whole), _bigrams(t.label.partition(". ")[2] or t.label))
    if d >= 0.3:
        s += d * 4
        where = where or "비슷"
    snippet = ""
    if s > 0:
        for line in body.splitlines():
            if any(w in _plain(line) for w in words):
                snippet = clean_line(line)
                break
    return s, where, snippet


def search(items, q: str, limit: int | None = None) -> list[tuple]:
    """[(번호, 서식) …] 중 비슷한 것을 [(번호, 서식, 점수, 맞은 곳, 미리보기) …] 높은 점수부터."""
    found = []
    for n, t in items:
        s, where, snip = score(t, q)
        if s > 0:
            found.append((n, t, s, where, snip))
    found.sort(key=lambda r: (-r[2], r[1].area, r[1].sort_key))
    return found[:limit] if limit else found
