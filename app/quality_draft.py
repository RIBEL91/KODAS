"""품질평가 초안 작성: 참고 평가표(전년도 등)의 '평가 근거'를 바탕으로 고른 해의 기록물등록대장에서 같은
종류의 문서를 찾아, 초안 평가표의 평가 근거를 채운다.

1) 참고 근거에서 문서 참조를 읽는다. 쓰는 사람마다 모양이 달라 여러 모양을 받는다:
   '264 (26.2.9.)', '계약안내-1936(25.09.15)', '1월-120(25.01.13)', '127(26.1.19.) 3월',
   '광주양림2- 1050(05.09) 지하저수조 청소'(연도 없는 날짜 → 참고 평가표의 평가년도, 뒤의 글은 설명).
2) 그 해 대장에서 등록번호로 문서 제목을 찾고, 날짜·월·연도·차수를 뺀 '제목 열쇠'를 만든다.
3) 고른 해 대장에서 열쇠가 같은 문서를 모두 찾아 같은 모양(앞글자·날짜 꼴·설명)으로 적는다.
   문서번호가 없는 근거('11월 말 기준 적정', '화면 캡처')는 그대로 옮긴다.
   참고 근거에는 있는데 고른 해에 없는 문서는 Result.lacking에 모아(점수 불인정 사유·노란 표시용) 알린다.
대장 읽기(홈넷)는 ledger.year_rows가 하고, 여기는 글자 처리만 한다(시험 가능).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from collector import similar_key

# [N월-][앞글자-]번호[ ](yy.m.d. | yyyy.m.d | m.d)[ N월]
REF_RE = re.compile(
    r"(?:(?P<mon>\d{1,2})\s*월\s*-\s*)?"
    r"(?:(?P<pre>[가-힣A-Za-z][가-힣A-Za-z0-9]*)(?P<presep>\s*[-_]\s*))?"
    r"(?P<seq>\d{1,5})(?P<sp>\s*)\(\s*(?:(?P<y>\d{4}|\d{2})\s*[.\-]\s*)?(?P<m>\d{1,2})\s*[.\-]\s*(?P<d>\d{1,2})"
    r"\s*(?P<dot>\.)?\s*\)"
    r"(?:[ \t]*(?P<suf>\d{1,2})\s*월(?![\s\d]*-))?")
NUM_RE = re.compile(r"^(?P<office>.+?)-(?P<seq>\d+)$")
# 날짜 없이 번호만: '광주양림2-239,1435,688' · '광주양림2관리소-219, 804' (번호 뒤에 괄호 날짜가 오면 아님)
NUM_LIST_RE = re.compile(r"(?<![가-힣A-Za-z0-9])[가-힣A-Za-z][가-힣A-Za-z0-9]*\s*-\s*"
                         r"(?P<nums>\d{1,5}(?:\s*,\s*\d{1,5})*)(?![\d.]|\s*\()")
LACK_PREFIX = "작년과 비교해 없는 항목: "


def draft_key(title: str) -> str:
    """같은 종류 문서인지 견줄 열쇠: similar_key(날짜·월·연도·동호수 뺌)에 차수('1차')도 뺀다."""
    return similar_key(re.sub(r"\d+\s*차", "", title or ""))


def _ratio(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class Doc:
    seq: int
    number: str
    title: str
    date: dt.date | None
    key: str = ""

    def __post_init__(self):
        if not self.key:
            self.key = draft_key(self.title)


@dataclass
class Ref:
    raw: str
    seq: int
    date: dt.date
    mon: str = ""          # 앞에 붙은 'N월-'
    pre: str = ""          # 앞에 붙은 '계약안내' / '광주양림2'
    presep: str = "-"      # 앞글자와 번호 사이('-', '- ', '_ ')
    suf: str = ""          # 뒤에 붙은 'N월'
    pad: bool = False      # 25.01.21 처럼 두 자리
    dot: bool = False      # 26.1.19. 처럼 끝에 점
    space: bool = False    # '264 (26.2.9.)' 처럼 번호와 괄호 사이 띄움
    ylen: int = 2          # 날짜의 연도 자리: 0(없음) · 2 · 4
    desc: str = ""         # 뒤에 적은 설명('지하저수조 청소')


@dataclass
class Result:
    basis: str
    found: int = 0                 # 고른 해 문서를 찾아 넣은 수
    missing: list = field(default_factory=list)   # 못 찾은 것 설명(기록용)
    lacking: list = field(default_factory=list)   # 참고 근거에는 있고 고른 해에는 없는 문서(설명 또는 제목)
    carried: bool = False          # 문서번호 없는 근거를 그대로 옮김


def parse_refs(text: str, default_year: int | None = None) -> list[Ref]:
    """근거 글에서 문서 참조를 읽는다. 연도 없는 날짜는 default_year(없으면 건너뜀)."""
    text = text or ""
    ms = list(REF_RE.finditer(text))
    out = []
    for i, m in enumerate(ms):
        if m["y"]:
            y = int(m["y"])
            y = y + 2000 if y < 100 else y
        elif default_year:
            y = default_year
        else:
            continue
        try:
            d = dt.date(y, int(m["m"]), int(m["d"]))
        except ValueError:
            continue
        nxt = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        tail = text[m.end():nxt].split("\n")[0]
        desc = tail.strip(" ,/\t")
        if desc and not tail[:1].isspace():           # 붙어 있는 글은 설명으로 보지 않음
            desc = ""
        out.append(Ref(raw=m.group(0).strip(), seq=int(m["seq"]), date=d, mon=m["mon"] or "", pre=m["pre"] or "",
                       presep=m["presep"] or "-", suf=m["suf"] or "",
                       pad=(len(m["m"]) == 2 and m["m"].startswith("0")) or (len(m["d"]) == 2 and m["d"].startswith("0")),
                       dot=bool(m["dot"]), space=bool(m["sp"]), ylen=len(m["y"] or ""), desc=desc))
    return out


def fmt_ref(doc: Doc, style: Ref, with_pre: bool = True) -> str:
    d = doc.date
    md = f"{d.month:02d}.{d.day:02d}" if style.pad else f"{d.month}.{d.day}"
    ds = {4: f"{d.year}.{md}", 0: md}.get(style.ylen, f"{d:%y}.{md}")
    if style.dot:
        ds += "."
    s = f"{doc.seq}{' ' if style.space else ''}({ds})"
    if style.pre and with_pre:
        s = f"{style.pre}{style.presep}{s}"
    if style.mon or style.suf:
        # 참고 문서와 같은 간격(예: 1월 문서 → '2월' 신고분)을 지키는 월. 제목에 그 간격의 'N월'이 있으면
        # 그것(제목에 '재임대 12월, 갱신 2월'처럼 여럿이어도 맞는 것), 없으면 문서 날짜 + 간격.
        gap = (int(style.mon or style.suf) - style.date.month) % 12
        cands = [int(x) for x in re.findall(r"(\d{1,2})\s*월", doc.title) if 1 <= int(x) <= 12]
        month = next((m for m in cands if (m - d.month) % 12 == gap), (d.month - 1 + gap) % 12 + 1)
        if style.mon:
            s = f"{month}월-{s}"
        else:
            s += f" {month}월"
    if style.desc:
        s += f" {style.desc}"
    return s


def eval_year(text: str) -> int | None:
    m = re.search(r"(20\d\d)\s*년도", text or "")
    return int(m[1]) if m else None


def parse_ledger_rows(rows: list[dict], office_hint: str = "") -> list[Doc]:
    """기록물등록대장 목록 줄(ledger.list_rows) → Doc. 우리 등록번호(관리소-번호)와 그 다음 칸 제목."""
    docs = []
    for row in rows:
        texts = [str(t).strip() for t in row.get("text", [])]
        idx = None
        for i, t in enumerate(texts):
            m = NUM_RE.match(t)
            if m and ("관리소" in m["office"] or (office_hint and office_hint in m["office"])):
                idx = i
                break
        if idx is None:
            idx = next((i for i, t in enumerate(texts) if NUM_RE.match(t)), None)
        if idx is None or idx + 1 >= len(texts):
            continue
        number = texts[idx]
        title = texts[idx + 1]
        ud = row.get("userdata", "")
        m = re.search(r"<CREATE_REG_DATE>(\d{8})\d{6}</CREATE_REG_DATE>", ud)
        stamp = m[1] if m else next((t[:8] for t in texts if re.fullmatch(r"\d{14}", t)), "")
        date = dt.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])) if stamp else None
        docs.append(Doc(seq=int(NUM_RE.match(number)["seq"]), number=number, title=title, date=date))
    return docs


def _sep(text: str) -> str:
    for s in (" / ", ", ", "/", ","):
        if s in text:
            return s
    return ", "                     # 한 문서였던 줄이 여러 문서가 되면 쉼표로


PERIODS = ((r"(\d)\s*/\s*4\s*분기", "분기"), (r"(\d)\s*분기", "분기"), (r"(상|하)\s*반기", "반기"),
           (r"(\d{1,2})\s*월", "월"), (r"(\d+)\s*차", "차"))


def period(title: str):
    """제목의 기간 표시: ('분기', '1') · ('월', '3') · ('반기', '상') … 없으면 None."""
    for pat, unit in PERIODS:
        m = re.search(pat, title or "")
        if m:
            return unit, m.group(1)
    return None


def _swap_period(desc: str, old_title: str, new_title: str) -> str:
    """설명의 기간 글자를 새 문서에 맞게: '1분기 재난대응훈련'(1/4분기 문서) → '2분기 …'(2/4분기 문서)."""
    a, b = period(old_title), period(new_title)
    if not desc or not a or not b or a[0] != b[0] or a[1] == b[1]:
        return desc
    if a[0] == "반기":
        return re.sub(rf"{a[1]}(\s*반기)", rf"{b[1]}\1", desc, count=1)
    unit = {"분기": r"(\s*(?:/\s*4\s*)?분기)", "월": r"(\s*월)", "차": r"(\s*차)"}[a[0]]
    return re.sub(rf"(?<!\d){a[1]}{unit}", rf"{b[1]}\1", desc, count=1)


def _shift_years(text: str, delta: int) -> str:
    """'2024년' 같은 연도 글자를 delta해 옮긴다(참고 평가년도 → 고른 해)."""
    if not text or not delta:
        return text
    return re.sub(r"(?<!\d)(20\d\d)(\s*년)", lambda m: f"{int(m[1]) + delta}{m[2]}", text)


def _related(desc: str, title: str) -> bool:
    """근거에 적은 설명과 대장 제목이 관련 있는지(두 글자 이상 겹침). 설명이 없으면 True."""
    plain = re.sub(r"\d+\s*(?:/\s*4\s*)?(분기|월|차)|(상|하)\s*반기|\(.*?\)", "", desc or "")   # 기간만 적은 설명은 빼고 본다
    a, b = draft_key(plain), draft_key(title)
    if len(a) < 2:
        return True
    from difflib import SequenceMatcher
    m = SequenceMatcher(None, a, b).find_longest_match(0, len(a), 0, len(b))
    return m.size >= 2


def draft_basis(prev_basis: str, prev_year: int, cur_year: int, ledgers: dict,
                follow_offset: bool = False, item_text: str = "", with_title: bool = True) -> Result:
    """참고 초안의 근거 → 고른 해(cur_year) 근거. ledgers = {연도: [Doc, …]} (참고 문서의 해들과 고른 해).

    follow_offset=True면 참고 문서가 평가년도 다음 해 문서일 때(1~2월분 등) 그만큼 뒤의 해 대장에서 찾는다.
    찾는 순서: 제목 열쇠가 같은 문서 → 아주 비슷한 제목 → 근거에 적은 설명이 제목에 든 문서 →
    평가항목 이름(item_text)이 제목에 든 문서. 참고 근거에 이미 있던 그 해 문서는 원래 적은 글자 그대로 둔다.
    참고 근거의 문서 중 고른 해에 같은 종류(분기·월 같은 기간까지)가 없는 것은 Result.lacking에 모은다."""
    refs = parse_refs(prev_basis, prev_year)
    pad_any = any(r.pad for r in refs)          # 한 칸이라도 25.01.21처럼 썼으면 모두 두 자리로
    if not refs and not NUM_LIST_RE.search(prev_basis or ""):
        return Result(basis=(prev_basis or "").strip(), carried=bool((prev_basis or "").strip()))
    by_seq = {y: {d.seq: d for d in docs} for y, docs in ledgers.items()}
    by_key: dict = {}
    for y, docs in ledgers.items():
        for d in docs:
            by_key.setdefault((y, d.key), []).append(d)

    def near(doc, r, days=7):
        if not (doc and doc.date):
            return False
        try:
            return abs((doc.date - r.date.replace(year=doc.date.year)).days) <= days
        except ValueError:                       # 2월 29일
            return False

    def lookup(r):
        """참조가 가리키는 문서: 그 해 대장에서 번호가 같고 날짜가 맞는(±7일) 것. 연도 없는 날짜면 다음·앞 해도.
        번호를 잘못 적어 설명과 제목이 딴판이면, 설명이 제목에 들고 날짜가 맞는 문서를 대신 찾는다."""
        years = [r.date.year] + ([r.date.year + 1, r.date.year - 1] if not r.ylen else [])
        for y in years:
            doc = by_seq.get(y, {}).get(r.seq)
            if near(doc, r) and _related(r.desc, doc.title):
                return doc
        core = draft_key(r.desc)
        if len(core) >= 3:
            for y in years:
                cands = [d for d in ledgers.get(y, []) if near(d, r, 10) and _related(r.desc, d.title)]
                if cands:
                    return max(cands, key=lambda d: _ratio(core, d.key))
        return None

    def same_kind(year, key):
        """고른 해 대장에서 열쇠가 같은 문서. 없으면 제목이 아주 비슷한 문서(0.85 이상, 가장 비슷한 무리)."""
        hit = by_key.get((year, key))
        if hit:
            return hit
        scored = [(_ratio(key, d.key), d) for d in ledgers.get(year, []) if d.key]
        best = max((r for r, _d in scored), default=0)
        if best < 0.85:
            return []
        return [d for r, d in scored if r >= best - 0.03]

    def same_period(year, doc):
        """기간(분기·월)이 같고 제목이 다섯 글자 이상 이어서 겹치는 문서 중 가장 비슷한 것
        ('2/4분기(우기) 안전점검 실시 보고' → '2/4분기(우기) 안전점검 시행')."""
        t = period(doc.title)
        if not t:
            return []
        from difflib import SequenceMatcher

        def lcs(a, b):
            return SequenceMatcher(None, a, b).find_longest_match(0, len(a), 0, len(b)).size
        need = max(5, (len(doc.key) + 1) // 2)        # 전년 제목의 절반 이상이 이어서 겹쳐야
        cands = [d for d in ledgers.get(year, []) if d.date and period(d.title) == t and lcs(doc.key, d.key) >= need]
        if not cands:
            return []

        def gap(d):                 # 'N월 갱신' 문서를 몇 달 앞서 보냈는지(전년과 같으면 같은 종류일 가능성이 큼)
            return (int(t[1]) - d.date.month) % 12 if t[0] == "월" and d.date else None
        g0 = gap(doc)
        best = max(cands, key=lambda d: (gap(d) == g0, lcs(doc.key, d.key), _ratio(doc.key, d.key)))
        return [d for d in cands if d.key == best.key and d.date == best.date]     # 같은 날 같은 제목(영구·국민) 함께

    def by_desc(year, desc, ref_key):
        """제목이 바뀌어 못 찾을 때: 근거에 적은 설명('수질검사')이 제목에 든 문서 중 전년 제목과 가장 가까운 무리."""
        core = draft_key(re.sub(r"\d+\s*(?:/\s*4\s*)?(분기|월|차)", "", desc or ""))
        if len(core) < 3:
            return []
        groups: dict = {}
        for d in ledgers.get(year, []):
            if core in d.key:
                groups.setdefault(d.key, []).append(d)
        if not groups:
            return []
        return groups[max(groups, key=lambda k: (_ratio(ref_key, k), len(groups[k])))]

    def by_item(year):
        """제목이 바뀌어 못 찾을 때: 평가항목 이름('주택소유정기검색 의뢰 여부' → '주택소유정기검색의뢰')이
        제목에 든 문서 중 가장 가까운 무리."""
        core = draft_key(re.sub(r"\s*(적정\s*)?(여부|유무)$", "", (item_text or "").strip()))
        if len(core) < 5:
            return []
        groups: dict = {}
        for d in ledgers.get(year, []):
            if core in d.key:
                groups.setdefault(d.key, []).append(d)
        if not groups:
            return []
        return groups[max(groups, key=lambda k: (_ratio(core, k), len(groups[k])))]

    def _num_list_line(line):
        """'광주양림2-239,1435,688'처럼 날짜 없이 번호만 적은 줄: 참고 평가년도 대장에서 번호로 제목을 찾아
        같은 종류의 고른 해 문서 번호로 바꾼다. 번호 대부분을 못 찾으면 None(그대로 둠)."""
        m = NUM_LIST_RE.search(line)
        if not m:
            return None
        seqs = [int(x) for x in re.findall(r"\d+", m["nums"])]
        docs = [by_seq.get(prev_year, {}).get(s) for s in seqs]
        known = [d for d in docs if d]
        if not known or len(known) * 2 < len(seqs):
            return None
        year = cur_year
        new_seqs, lack = [], []
        for key in dict.fromkeys(d.key for d in known):
            news = [d for d in same_kind(year, key) if d.date and (year, d.seq) not in used]
            if not news:
                lack.append(next(d.title for d in known if d.key == key))
                continue
            for d in news:
                used.add((year, d.seq))
                new_seqs.append(d)
        for t in lack:
            res.lacking.append(t)
            res.missing.append(f"{year}년 대장에 '{t}' 같은 문서가 없음")
        if not new_seqs:
            notes.extend(lack)
            return ""
        res.found += len(new_seqs)
        if with_title:                     # 번호(날짜) 공문 제목 — 한 줄에 하나씩
            head = line[:m.start("nums")]
            return "\n".join(f"{head}{d.seq}({d.date:%y.%m.%d}) {d.title}"
                              for d in sorted(new_seqs, key=lambda d: (d.date, d.seq)))
        joiner = ", " if ", " in m["nums"] else ","
        nums = joiner.join(str(d.seq) for d in sorted(new_seqs, key=lambda d: (d.date, d.seq)))
        return (line[:m.start("nums")] + nums + line[m.end("nums"):]).strip()

    item_used = False
    lines = (prev_basis or "").replace("\r", "").split("\n")
    res = Result(basis="")
    notes: list = []
    used: set = set()
    lack_cands: list = []           # (없는 항목 이름, 참고 문서, 해) — 항목을 다 본 뒤 판단
    all_news: list = []             # 이 항목에 적은 고른 해 문서들
    resolved = []                   # (줄 번호, 참조, 참고 문서)
    key_lines: dict = {}            # 열쇠 → 그 열쇠가 나온 줄들(한 줄에 하나씩 적었는지)
    key_refs: dict = {}             # 열쇠 → [(참조, 참고 문서)] (분기·월마다 따로 적은 것들)
    for li, line in enumerate(lines):
        for r in parse_refs(line, prev_year):
            r.pad = r.pad or pad_any
            doc = lookup(r)
            if doc and doc.date and not r.ylen:
                r.date = doc.date                       # 연도 없는 날짜는 대장 날짜로 확정
            resolved.append((li, r, doc))
            if doc:
                key_lines.setdefault(doc.key, set()).add(li)
                key_refs.setdefault(doc.key, []).append((r, doc))
    raw_of = {(doc.date.year, doc.seq): r for (_li, r, doc) in resolved if doc and doc.date}

    done_keys, out_lines = set(), []
    for li, line in enumerate(lines):
        mine = [(r, doc) for (lj, r, doc) in resolved if lj == li]
        if not mine:
            listed = _num_list_line(line)
            if listed is not None:
                out_lines.append(listed)
            elif line.strip():
                out_lines.append(line.strip())
            continue
        lead = REF_RE.sub("\0", line).split("\0")[0].strip(" ,/")    # 번호 앞 글자(예: '해약처리현황 캡처')
        lead = _shift_years(lead, cur_year - prev_year)              # '2024년 하반기' → '2025년 하반기'
        sep = _sep(REF_RE.sub("X", line))
        entries, multiline, unknown = [], False, []
        for r, doc in mine:
            if not doc:
                unknown.append(f"{r.raw}{(' ' + r.desc) if r.desc else ''}(확인 필요)")
                res.missing.append(f"대장에서 {r.seq}번({r.date:%m.%d}) 문서를 찾지 못함")
                continue
            if doc.key in done_keys:
                continue
            done_keys.add(doc.key)
            group = key_refs.get(doc.key, [(r, doc)])
            year = cur_year + (r.date.year - prev_year if follow_offset else 0)
            def fresh(ds):
                seen = set()
                return [d for d in ds if d.date and (year, d.seq) not in used
                        and not (d.seq in seen or seen.add(d.seq))]
            exact = fresh(same_kind(year, doc.key))
            news = exact
            if len(news) * 2 < len(group) or not news:
                # 분기·월마다 따로 적은 것: 그 기간마다 제목이 이어서 겹치는 문서를 찾아 보탠다
                news = fresh(exact + [d for _gr, gdoc in group for d in same_period(year, gdoc)])
            if not exact:
                # 제목이 바뀐 경우: 평가항목 이름이 든 문서('…정기검색 의뢰')가 있으면 그것을 먼저,
                # 아니면 설명으로 찾은 것과 견줘 더 많은 쪽
                item_docs = fresh(by_item(year)) if not item_used else []
                if item_docs and len(item_docs) * 5 >= len(news) * 4:
                    news, item_used = item_docs, True
                elif len(news) * 2 < len(group) and r.desc:
                    desc_docs = fresh(by_desc(year, r.desc, doc.key))
                    if len(desc_docs) > len(news):
                        news = desc_docs
            # 작년에는 있었는데 올해 없는 것: 같은 종류가 하나도 없거나, 그 분기·월만 없는 경우
            got = {period(d.title) for d in news}
            for gr, gdoc in group:
                t = period(gdoc.title)
                if not news or (t and t not in got and len(group) > 1):
                    lack_cands.append((gr.desc or gdoc.title, gdoc, year))     # 끝에서 항목 전체로 다시 본다
            if not news:
                notes.append(doc.title)
                continue
            # 설명을 붙여 한 줄에 하나씩 적었거나, 전년도에도 여러 줄이었으면 한 줄에 하나씩
            multiline = multiline or with_title or bool(r.desc) or len(key_lines.get(doc.key, ())) > 1
            by_period = {period(gdoc.title): (gr, gdoc) for gr, gdoc in group if period(gdoc.title)}
            for d in news:
                used.add((year, d.seq))
                all_news.append(d)
                gr, gdoc = by_period.get(period(d.title), (r, doc))
                desc = d.title if with_title else _shift_years(_swap_period(gr.desc, gdoc.title, d.title),
                                                              cur_year - prev_year)   # 공문 제목 그대로
                style = Ref(**{**gr.__dict__, "desc": desc})
                entries.append((d, style))
        entries.sort(key=lambda e: (e[0].date, e[0].seq))
        res.found += len(entries)
        pre_ref = next((r for r, _doc in mine if r.pre), None)
        texts = []
        for i, (d, r) in enumerate(entries):
            with_pre = multiline or i == 0                  # 한 줄에 이어 쓸 때 앞글자는 맨 앞에만
            style = r if r.pre or not pre_ref else Ref(**{**r.__dict__, "pre": pre_ref.pre, "presep": pre_ref.presep})
            same = raw_of.get((d.date.year, d.seq)) if d.date else None
            if same is not None and not follow_offset:      # 참고 근거에 이미 있던 문서: 적은 그대로
                raw = same.raw
                if same.pre and not with_pre:
                    raw = raw[raw.index(same.pre) + len(same.pre):].lstrip(" -_")
                elif style.pre and with_pre and not same.pre:
                    raw = f"{style.pre}{style.presep}{raw}"
                tail = d.title if with_title else same.desc
                texts.append(raw + (f" {tail}" if tail else ""))
                continue
            texts.append(fmt_ref(d, style, with_pre))
        body = ("\n" if multiline else sep).join(texts + unknown)
        if body:
            out_lines.append(f"{lead} {body}".strip() if lead else body)
        elif lead and not re.fullmatch(r"[가-힣A-Za-z0-9]+\s*[-_]?", lead):
            out_lines.append(lead)
    if notes and not res.found:                 # 하나도 못 찾았을 때만 근거 칸에 표시
        out_lines.append(f"※ {cur_year}년 대장에서 확인 필요: " + ", ".join(dict.fromkeys(notes)))
    for label, gdoc, year in lack_cands:
        # 다른 줄에서 같은 기간(분기·월)의 비슷한 문서를 이미 찾았으면 없는 것이 아니다
        t = period(gdoc.title)
        if t and any(period(d.title) == t and _ratio(gdoc.key, d.key) >= 0.6 for d in all_news):
            continue
        res.lacking.append(label)
        res.missing.append(f"{year}년 대장에 '{gdoc.title}' 같은 문서가 없음")
    res.lacking = list(dict.fromkeys(res.lacking))
    res.basis = "\n".join(x for x in out_lines if x)
    return res


def needed_years(prev_items, prev_year: int, cur_year: int, follow_offset: bool = False) -> tuple[set, set]:
    """읽어야 할 대장 연도: (참고 근거에 나온 해들, 새 문서를 찾을 해들 — 기본은 고른 해 하나).
    연도 없이 적은 날짜는 평가년도로 보되, 1~2월 문서가 다음 해일 수 있어 다음 해도 함께 읽는다."""
    old = set()
    for it in prev_items:
        for r in parse_refs(it.basis, prev_year):
            old.add(r.date.year)
            if not r.ylen:
                old.add(r.date.year + 1)
        if NUM_LIST_RE.search(it.basis or ""):          # 날짜 없이 번호만 적은 근거는 평가년도 대장에서 찾는다
            old.add(prev_year)
    old = {y for y in old if y <= dt.date.today().year}
    if not old:
        return old, set()
    return old, ({cur_year + (y - prev_year) for y in old} if follow_offset else {cur_year})


def _match_key(it) -> tuple:
    return (it.part, it.no, it.seq)


def lack_reason(lacking: list) -> str:
    """점수 불인정 사유 칸에 적을 글."""
    return LACK_PREFIX + ", ".join(dict.fromkeys(lacking)) if lacking else ""


def make_draft(prev_items, cur_items, prev_year: int, cur_year: int, ledgers: dict,
               only=None, with_title: bool = True) -> list[tuple]:
    """초안 항목(cur_items)의 근거를 채운다. only(항목→bool)로 범위를 줄일 수 있다.
    참고 근거에 있던 문서가 고른 해에 없으면 항목의 reason(점수 불인정 사유)과 flag(노란 표시)를 단다.
    돌려주는 값: [(항목, Result)] — 근거나 사유를 바꾼 항목만."""
    prev_by = {_match_key(p): p for p in prev_items}
    prev_by_text = {similar_key(p.text): p for p in prev_items}
    out = []
    for it in cur_items:
        if only and not only(it):
            continue
        p = prev_by.get(_match_key(it))
        if p is None or similar_key(p.text) != similar_key(it.text):
            p = prev_by_text.get(similar_key(it.text), p)
        if p is None or not p.basis.strip():
            continue
        res = draft_basis(p.basis, prev_year, cur_year, ledgers, item_text=it.text, with_title=with_title)
        reason = lack_reason(res.lacking)
        old_reason = getattr(it, "reason", "") or ""
        mine = "\n".join(x for x in old_reason.split("\n") if not x.startswith(LACK_PREFIX)).strip()
        new_reason = "\n".join(x for x in (mine, reason) if x)          # 직접 적은 사유는 살린다
        flag = bool(res.lacking)
        changed = (res.basis and res.basis != it.basis) or new_reason != old_reason or flag != getattr(it, "flag", False)
        if res.basis:
            it.basis = res.basis
        it.reason, it.flag = new_reason, flag
        if changed:
            out.append((it, res))
    return out


def docs_to_json(docs: list[Doc]) -> list:
    return [[d.seq, d.number, d.title, d.date.isoformat() if d.date else ""] for d in docs]


def docs_from_json(rows: list) -> list[Doc]:
    return [Doc(seq=r[0], number=r[1], title=r[2], date=dt.date.fromisoformat(r[3]) if r[3] else None)
            for r in rows]


def cached_ledgers(years, cache_dir: str):
    """오늘 쓸 수 있는 저장 목록만으로 모두 채워지면 {연도: [Doc]}, 하나라도 없으면 None(홈넷에서 읽어야 함).
    지난해 목록은 계속 쓰고, 올해 목록은 그날 읽은 것만 쓴다."""
    import json
    import os
    today = dt.date.today()
    out = {}
    for y in years:
        try:
            with open(os.path.join(cache_dir, f"{y}.json"), encoding="utf-8") as f:
                c = json.load(f)
        except (OSError, ValueError):
            return None
        if not c.get("docs") or not (y < today.year or c.get("date") == today.isoformat()):
            return None
        out[y] = docs_from_json(c["docs"])
    return out


def load_ledgers(driver, years, cache_dir: str, log=print, stop=None, office: str = "") -> tuple[dict, list]:
    """홈넷 기록물등록대장에서 years 해의 문서 목록을 읽는다(읽기만). 지난해 목록은 저장해 두고 다시 쓰고,
    올해 목록은 그날 처음 한 번만 새로 읽는다. 돌려주는 값: ({연도: [Doc]}, 대장이 없던 해들)."""
    import json
    import os

    import ledger
    today = dt.date.today()
    ledgers, missing_years = {}, []
    for y in sorted(years):
        cache = os.path.join(cache_dir, f"{y}.json")
        try:
            with open(cache, encoding="utf-8") as f:
                c = json.load(f)
            if (y < today.year or c.get("date") == today.isoformat()) and c.get("docs"):
                ledgers[y] = docs_from_json(c["docs"])
                log(f"  {y}년 대장: 저장해 둔 목록 사용 ({len(ledgers[y])}건)")
                continue
        except (OSError, ValueError):
            pass
        if stop is not None and stop.is_set():
            break
        try:
            rows = ledger.year_rows(driver, y, log, stop)
        except ledger.LedgerError as ex:
            log(f"  ⚠️ {ex}")
            missing_years.append(y)
            ledgers[y] = []
            continue
        docs = parse_ledger_rows(rows, office)
        ledgers[y] = docs
        if docs and not (stop is not None and stop.is_set()):
            with open(cache, "w", encoding="utf-8") as f:
                json.dump({"date": today.isoformat(), "docs": docs_to_json(docs)}, f, ensure_ascii=False)
        log(f"  {y}년 대장 {len(docs)}건을 읽었습니다.")
    return ledgers, missing_years
