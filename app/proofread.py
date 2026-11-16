"""올바른 문서 만들기 — 공문서 작성 규칙(행정업무운영 편람)에 맞지 않는 곳을 찾아 고친다.

fix(본문) → (고친 본문, 고친 곳 목록), fix_title(제목) → (고친 제목, 고친 곳 목록).
고친 곳은 (규칙 이름, 고치기 전, 고친 뒤).

- 날짜: 2026.10.8 · 2026-10-08 · 2026. 10. 8 → 2026. 10. 8.   (요일은 붙여서 2026. 10. 8.(목))
- 시간: 오후 2시 30분 · 14시 30분 → 14:30
- 금액: 1250000원 → 1,250,000원, 금 1,250,000원 → 금1,250,000원(금일백이십오만원)
- 항목 기호: 1. → 가. → 1) → 가) → (1) → (가) 순서의 번호가 건너뛰거나 겹치면 바로잡고, 기호 뒤를 한 칸 띈다
- 붙임: '붙임:' · '붙임 1.' → '붙임  1.', 붙임 줄 끝의 '1부' → '1부.'
- 끝 표시: 본문 끝에 '  끝.'(두 칸 띄고)이 없으면 붙인다(표로 끝나면 다음 줄에 '끝.')
- 행정용어: 익일 → 다음 날, 금일 → 오늘, 상기 → 위, 하기와 같이 → 아래와 같이, 에 의거 → 에 따라 …
- 겹친 빈칸: 문장 가운데 두 칸 이상 빈칸은 한 칸으로(붙임·끝 앞은 두 칸 그대로)

{이름}·{날짜:…} 같은 빈칸 자리와 [문서링크: …] 자리는 건드리지 않는다.
"""
import re

_PROTECT = re.compile(r"\{[^{}\n]*\}|\[문서링크[^\]\n]*\]|https?://\S+|⟦[^⟧]*⟧")
_BASE = 0xE100          # 지킬 자리를 잠시 바꿔 두는 글자(사용자 영역)
_HELD = f"[{chr(_BASE)}-{chr(0xF8FF)}]"   # 지켜 둔 자리 글자(정규식)


def _protect(text: str) -> tuple[str, list[str]]:
    kept: list[str] = []

    def keep(m):
        kept.append(m.group(0))
        return chr(_BASE + len(kept) - 1)
    return _PROTECT.sub(keep, text), kept


def _restore(text: str, kept: list[str]) -> str:
    return re.sub(_HELD, lambda m: kept[ord(m.group(0)) - _BASE]
                  if ord(m.group(0)) - _BASE < len(kept) else m.group(0), text)


# ---------------- 날짜·시간·금액 ----------------
_DATE = re.compile(r"(?<![\d.\-/])((?:19|20)\d{2})\s*([.\-/])\s*(\d{1,2})\s*\2\s*(\d{1,2})(\s*\.)?(?![\d])")
_DAY_SPACE = re.compile(r"((?:19|20)\d{2}\. \d{1,2}\. \d{1,2}\.)\s+(\([월화수목금토일]\))")
_TIME_AMPM = re.compile(r"(오전|오후)\s*(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?(?!간)")
_TIME_HM = re.compile(r"(?<![\d가-힣])(\d{1,2})\s*시\s*(\d{1,2})\s*분")
_WON_PLAIN = re.compile(r"(?<![\d,.])(\d{4,})(?=\s*원)")
_WON_GEUM = re.compile(r"금\s+(?=\d|" + _HELD + r"\s*원)")
_WON_HANGUL = re.compile(r"금(\d{1,3}(?:,\d{3})+|\d{1,3})원(?!\s*\()")

_DIGITS = "영일이삼사오육칠팔구"


def won_hangul(n: int) -> str:
    """113560 → 일십일만삼천오백육십 (공문 금액 표기: 1도 '일'로 쓴다)."""
    if n <= 0:
        return ""
    out, big = [], ["", "만", "억", "조"]
    k = 0
    while n and k < len(big):
        n, part = divmod(n, 10000)
        if part:
            s = ""
            for unit, d in zip(("천", "백", "십", ""), f"{part:04d}"):
                if d != "0":
                    s += _DIGITS[int(d)] + unit
            out.append(s + big[k])
        k += 1
    return "".join(reversed(out))


def _fix_date(m) -> str:
    y, mo, d = int(m.group(1)), int(m.group(3)), int(m.group(4))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return m.group(0)
    return f"{y}. {mo}. {d}."


def _fix_ampm(m) -> str:
    h, mi = int(m.group(2)), int(m.group(3) or 0)
    if m.group(1) == "오후" and h < 12:
        h += 12
    if m.group(1) == "오전" and h == 12:
        h = 0
    if h > 24 or mi > 59:
        return m.group(0)
    return f"{h:02d}:{mi:02d}"


def _fix_hm(m) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 24 or mi > 59:
        return m.group(0)
    return f"{h:02d}:{mi:02d}"


def _comma(m) -> str:
    return f"{int(m.group(1)):,}"


def _add_hangul(m) -> str:
    n = int(m.group(1).replace(",", ""))
    h = won_hangul(n)
    return f"금{m.group(1)}원(금{h}원)" if h else m.group(0)


# ---------------- 행정용어 ----------------
# (찾을 정규식, 바꿀 말, 이름). 한자 숫자 금액(금일십…원) 속 글자는 건드리지 않는다
_AMOUNT_NEXT = "십백천만억조원일이삼사오육칠팔구영"
TERMS = [
    (re.compile(rf"(?<![가-힣])익일(?![{_AMOUNT_NEXT}])"), "다음 날"),
    (re.compile(rf"(?<![가-힣])금일(?![{_AMOUNT_NEXT}])"), "오늘"),
    (re.compile(r"(?<![가-힣])명일(?![가-힣])"), "내일"),
    (re.compile(r"(?<![가-힣])작일(?![가-힣])"), "어제"),
    (re.compile(r"(?<![가-힣])상기와 같이"), "위와 같이"),
    (re.compile(r"(?<![가-힣])상기(?=\s|의\s)"), "위"),
    (re.compile(r"(?<![가-힣])하기와 같이"), "아래와 같이"),
    (re.compile(r"에\s*의거하여"), "에 따라"),
    (re.compile(r"에\s*의거(?![가-힣])"), "에 따라"),
    (re.compile(r"(?<![가-힣])기\s(?=(?:통보|안내|제출|시행|보고|발송|요청)한)"), "이미 "),
    (re.compile(r"시건장치"), "잠금장치"),
    (re.compile(r"(?<![가-힣])가료(?![가-힣])"), "치료"),
]


# ---------------- 항목 기호 ----------------
_GANADA = "가나다라마바사아자차카타파하"
_MARKERS = [  # (정규식, 수준) — 1. → 가. → 1) → 가) → (1) → (가)
    (re.compile(r"(\d{1,2})\.(?!\d)"), 0),
    (re.compile(rf"([{_GANADA}])\.(?![가-힣\d])"), 1),
    (re.compile(r"(\d{1,2})\)"), 2),
    (re.compile(rf"([{_GANADA}])\)"), 3),
    (re.compile(r"\((\d{1,2})\)"), 4),
    (re.compile(rf"\(([{_GANADA}])\)"), 5),
]


def _marker(line: str):
    """줄 앞의 항목 기호 → (들여쓰기, 수준, 번호(1부터), 기호 글자, 기호 뒤 나머지) 또는 None."""
    m = re.match(r"(\s*)", line)
    lead, rest = m.group(1), line[m.end():]
    for rx, level in _MARKERS:
        mm = rx.match(rest)
        if not mm:
            continue
        v = mm.group(1)
        num = int(v) if v.isdigit() else _GANADA.index(v) + 1
        return lead, level, num, mm.group(0), rest[mm.end():]
    return None


def _marker_text(level: int, num: int) -> str | None:
    if level in (1, 3, 5) and num > len(_GANADA):
        return None
    v = str(num) if level in (0, 2, 4) else _GANADA[num - 1]
    return (f"{v}.", f"{v}.", f"{v})", f"{v})", f"({v})", f"({v})")[level]


def _is_table(line: str) -> bool:
    return line.strip().startswith("|")


def _is_attach(line: str) -> bool:
    return bool(re.match(r"\s*붙\s*임(?![가-힣])", line))


# ---------------- 고치기 ----------------
def _sub(rx, repl, text: str, rule: str, changes: list) -> str:
    def one(m):
        new = repl(m) if callable(repl) else m.expand(repl)
        if new != m.group(0):
            changes.append((rule, m.group(0), new))
        return new
    return rx.sub(one, text)


def _inline(text: str, changes: list) -> str:
    """한 줄 안에서 고치는 규칙(날짜·시간·금액·행정용어)."""
    text = _sub(_DATE, _fix_date, text, "날짜 표기", changes)
    text = _sub(_DAY_SPACE, r"\1\2", text, "날짜와 요일 붙여 쓰기", changes)
    text = _sub(_TIME_AMPM, _fix_ampm, text, "시간 표기(24시각)", changes)
    text = _sub(_TIME_HM, _fix_hm, text, "시간 표기(24시각)", changes)
    text = _sub(_WON_PLAIN, _comma, text, "금액 쉼표", changes)
    text = _sub(_WON_GEUM, "금", text, "금액 표기(금 붙여 쓰기)", changes)
    text = _sub(_WON_HANGUL, _add_hangul, text, "금액 한글 병기", changes)
    for rx, word in TERMS:
        text = _sub(rx, word, text, "행정용어 순화", changes)
    return text


def fix(body: str) -> tuple[str, list]:
    """본문을 공문서 규칙에 맞게 고친다. (고친 본문, [(규칙, 전, 후), …])."""
    changes: list = []
    text, kept = _protect(body.replace("\r\n", "\n"))
    lines = text.split("\n")

    # 1) 줄마다: 날짜·시간·금액·용어, 겹친 빈칸, 기호 뒤 띄기, 붙임
    out = []
    attach = False
    for line in lines:
        line = line.rstrip()
        line = _inline(line, changes)
        if _is_table(line):
            out.append(line)
            continue
        if _is_attach(line):
            attach = True
            new = re.sub(r"^(\s*)붙\s*임\s*[:：]?\s*", r"\1붙임  ", line)
            if new.strip() == "붙임":
                new = new.rstrip()
            if new != line:
                changes.append(("붙임 표기(붙임 뒤 두 칸)", line.strip(), new.strip()))
            line = new
        if attach and re.search(r"\d+\s*부\s*$", line):
            new = re.sub(r"(\d+)\s*부\s*$", r"\1부.", line)
            changes.append(("붙임 끝 마침표", line.strip(), new.strip()))
            line = new
        mk = _marker(line)
        if mk and mk[4] and not mk[4][0].isspace():
            new = mk[0] + mk[3] + " " + mk[4]
            changes.append(("항목 기호 뒤 띄어쓰기", line.strip(), new.strip()))
            line = new
        lead = re.match(r"\s*", line).group(0)
        body_part = line[len(lead):]
        squeezed = re.sub(r"(?<=\S) {2,}(?=\S)", lambda m: m.group(0) if _keep_two(body_part, m) else " ",
                          body_part)
        if squeezed != body_part:
            changes.append(("겹친 빈칸", body_part.strip(), squeezed.strip()))
            line = lead + squeezed
        out.append(line)

    # 2) 항목 번호 차례(붙임 줄부터는 붙임 번호라 보지 않는다)
    counters = [0] * 6
    for i, line in enumerate(out):
        if _is_attach(line):
            break
        if _is_table(line):
            continue
        mk = _marker(line)
        if not mk:
            continue
        lead, level, num, sym, rest = mk
        expected = counters[level] + 1
        if num == 1 or num == expected:
            counters[level] = num
        else:
            want = _marker_text(level, expected)
            if want:
                out[i] = lead + want + rest
                changes.append(("항목 번호 차례", f"{sym} {rest.strip()}"[:40], f"{want} {rest.strip()}"[:40]))
                counters[level] = expected
            else:
                counters[level] = num
        for k in range(level + 1, 6):
            counters[k] = 0

    # 3) 끝 표시
    out = _fix_end(out, changes)
    return _restore("\n".join(out), kept), [(r, _restore(a, kept), _restore(b, kept)) for r, a, b in changes]


def _keep_two(text: str, m) -> bool:
    """'붙임  1.'과 '…  끝.'의 두 칸은 그대로 둔다."""
    before, after = text[:m.start()], text[m.end():]
    return before.endswith("붙임") or after.startswith("끝.") or after == "끝"


def _fix_end(lines: list[str], changes: list) -> list[str]:
    last = len(lines) - 1
    while last >= 0 and not lines[last].strip():
        last -= 1
    if last < 0:
        return lines
    line = lines[last]
    if _is_table(line):
        if "끝" not in line:
            changes.append(("끝 표시", "(표로 끝남)", "다음 줄에 '끝.'"))
            return lines[:last + 1] + ["끝."]
        return lines
    stripped = line.rstrip()
    lead = re.match(r"\s*", stripped).group(0)
    m = re.search(r"(?:(?<=\s)|(?<=\.)|^)끝\s*\.?$", stripped.strip())
    if m:
        head = stripped.strip()[:m.start()].rstrip()
        if not head:
            new = lead + "끝."
        else:
            if re.search(r"\d+\s*부$", head):
                head += "."
            new = lead + head + "  끝."
        if new != stripped:
            changes.append(("끝 표시(두 칸 띄고 '끝.')", stripped.strip()[-30:], new.strip()[-30:]))
        lines[last] = new
        return lines[:last + 1]
    new = stripped + ("." if re.search(r"(다|\d\s*부)$", stripped) else "") + "  끝."
    changes.append(("끝 표시", stripped.strip()[-30:], new.strip()[-30:]))
    lines[last] = new
    return lines[:last + 1]


def fix_title(title: str) -> tuple[str, list]:
    """제목: 날짜·시간·금액·용어, 겹친 빈칸, 끝의 마침표."""
    changes: list = []
    text, kept = _protect(title)
    text = _inline(text, changes)
    new = re.sub(r" {2,}", " ", text).strip()
    if new != text.strip():
        changes.append(("제목 빈칸", text.strip(), new))
    if new.endswith(".") and not re.search(r"\d\.$", new):
        changes.append(("제목 끝 마침표 빼기", new, new[:-1]))
        new = new[:-1]
    return _restore(new, kept), [(r, _restore(a, kept), _restore(b, kept)) for r, a, b in changes]


def summary(changes: list, limit: int = 12) -> str:
    """고친 곳을 사람이 읽을 글로(같은 것은 한 번만)."""
    seen, lines = set(), []
    for rule, a, b in changes:
        key = (rule, a, b)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"• {rule}: {a}  →  {b}")
    more = len(lines) - limit
    return "\n".join(lines[:limit]) + (f"\n… 외 {more}곳" if more > 0 else "")
