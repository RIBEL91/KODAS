"""공문양식(.hwp) → 공문작성기 서식(.txt) 변환.

1) tools\\export_hml.ps1 로 한글(HWP)에서 공문양식을 HWPML(.hml)로 내보낸다.
2) python tools\\convert_hml.py <hml 폴더> <서식 폴더>

양식의 빈칸(○)을 공문마다 넣을 입력칸으로 바꾼다.
- 날짜(20○○. ○. ○. / 20○○년 ○월 …)   → {날짜:항목|형식}
- '항목: ○○부' 처럼 이름이 붙은 숫자     → {항목}
- 금○○○원(금○○○원)                   → {금액:항목}
- 이름을 알 수 없는 빈칸·표 안의 ○○○는 그대로 둔다(확인하기에서 빨간색, 직접 고침).
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

O = "○"
ITEM_RE = re.compile(r"^(\s*)(\d+\.|[가-하]\.|\d+\)|[가-하]\)|\(\d+\)|[※◦\-*])\s*")


def _text(p) -> str:
    out = []
    for t in p.iter():
        if t.tag == "CHAR" and t.text:
            out.append(t.text)
        elif t.tag in ("TAB",):
            out.append("  ")
        elif t.tag in ("FWSPACE", "NBSPACE"):
            out.append(" ")
    return "".join(out)


def _direct_text(p) -> str:
    """표 안 글자를 빼고 이 문단의 글자만."""
    out = []
    for text in p.findall("TEXT"):
        for ch in text:
            if ch.tag == "CHAR" and ch.text:
                out.append(ch.text)
            elif ch.tag in ("FWSPACE", "NBSPACE"):
                out.append(" ")
            elif ch.tag == "TAB":
                out.append("  ")
    return "".join(out)


def _table(tbl) -> list[list[str]]:
    rows, cols = int(tbl.get("RowCount")), int(tbl.get("ColCount"))
    grid = [["" for _ in range(cols)] for _ in range(rows)]
    for cell in tbl.iter("CELL"):
        r, c = int(cell.get("RowAddr")), int(cell.get("ColAddr"))
        rs, cs = int(cell.get("RowSpan", 1)), int(cell.get("ColSpan", 1))
        txt = "<br>".join(_text(p).strip() for p in cell.iter("P")).strip("<br>").replace("|", "/")
        grid[r][c] = txt or " "
        for dr in range(rs):
            for dc in range(cs):
                if dr or dc:
                    grid[r + dr][c + dc] = "^" if dc == 0 else "<"
    return grid


def _is_num(c: str) -> bool:
    return bool(re.fullmatch(r"[\d○,.\-%\s]*(원|건|명|개|%|장)?", c))


def split_flat(grid: list[list[str]]) -> list[list[str]] | None:
    """칸을 '  ·  '로 이어 붙인 1칸짜리 표를 여러 칸 표로 되돌린다. 모르겠으면 None."""
    if len(grid) != 1 or len(grid[0]) != 1 or "  ·  " not in grid[0][0]:
        return None
    cells = [c.strip() for c in grid[0][0].split("  ·  ")]
    best, best_sc = 0, 0.0
    for n in range(2, 16):
        rows = -(-len(cells) // n)
        if rows < 2 or len(cells) % n > 0 and n - len(cells) % n > n // 2:
            continue
        pad = cells + [""] * (rows * n - len(cells))
        if any(not h or _is_num(h) for h in pad[:n]):
            continue
        sc = 0.0
        for j in range(n):
            col = [_is_num(pad[r * n + j]) for r in range(1, rows)]
            sc += max(col.count(True), col.count(False)) / len(col)
        sc /= n
        if sc > best_sc + 1e-9:
            best, best_sc = n, sc
    if best_sc < 0.97:
        return None
    rows = -(-len(cells) // best)
    pad = cells + [""] * (rows * best - len(cells))
    return [pad[r * best:(r + 1) * best] for r in range(rows)]


def read_hml(path: str) -> tuple[str, list]:
    """(제목, 본문 블록[str | 표]) — 머리(기관명·수신)와 꼬리(결재란·시행)는 버린다."""
    root = ET.parse(path).getroot()
    margins = {}
    for ps in root.iter("PARASHAPE"):
        m = ps.find("PARAMARGIN")
        margins[ps.get("Id")] = int(m.get("Left", 0)) if m is not None else 0
    sec = root.find(".//SECTION")
    title, blocks, started = "", [], False
    for p in sec.findall("P"):
        tbls = p.findall(".//TABLE")
        line = _direct_text(p).rstrip()
        if not started:
            if line.startswith("제목"):
                title = re.sub(r"^제목\s*", "", line).strip()
                started = True
            continue
        if tbls:
            for t in tbls:
                g = _table(t)
                fixed = split_flat(g)
                blocks.append(fixed or g)
            continue
        # 결재란(직위 ○○○ …) 이후는 꼬리
        if re.match(r"^\S+ ○○○(\s|$)", line) or line.startswith("시행"):
            break
        blocks.append(line.strip())
    while blocks and isinstance(blocks[-1], str) and not blocks[-1].strip():
        blocks.pop()
    return title, indent(blocks)


LEVELS = [(re.compile(r"^\d+\.\s"), 0), (re.compile(r"^[가-하]\.\s"), 2), (re.compile(r"^\d+\)\s"), 4),
          (re.compile(r"^[가-하]\)\s"), 6), (re.compile(r"^\(\d+\)\s"), 8)]


def indent(blocks: list) -> list:
    """항목 기호로 들여쓰기를 다시 매긴다(1. 0칸 / 가. 2칸 / 1) 4칸 / 가) 6칸 / (1) 8칸,
    붙임 아래 항목은 '붙임  ' 너비 6칸, ※·- 같은 보조 줄은 바로 위 항목 글자 위치)."""
    out, in_att, text_col = [], False, 0
    for b in blocks:
        if not isinstance(b, str) or not b:
            out.append(b)
            in_att = in_att and b == "" and False
            continue
        if b.startswith("붙임"):
            b = re.sub(r"^붙임\s*:?\s*", "붙임  ", b)
            in_att, text_col = True, 0
            out.append(b)
            continue
        if in_att and re.match(r"^\d+\.\s", b):
            out.append(" " * 6 + b)
            continue
        in_att = False
        for rx, lv in LEVELS:
            if rx.match(b):
                out.append(" " * lv + b)
                text_col = lv + len(rx.match(b).group(0))
                break
        else:
            prev = out[-1] if out and isinstance(out[-1], str) else ""
            if re.match(r"^[※◦\-*○]", b) or b.strip() == "끝.":
                out.append(" " * (text_col if b.strip() != "끝." else 2) + b.strip())
            elif prev.strip() and text_col and not re.search(r"(다\.|\.)\s*$", prev):
                out.append(" " * text_col + b)        # 윗줄 항목이 이어지는 줄
            else:
                out.append(b)
                text_col = 0
    return out


# ---------------- 빈칸 → 입력칸 ----------------

MONTH_AFTER = {"부과": "부과월", "고지": "고지월", "갱신": "갱신월", "말": "기준월", "현재": "기준월",
               "분": "대상월", "활동": "대상월"}


class Namer:
    def __init__(self):
        self.used: dict[str, str] = {}   # 이름 → 종류(같은 이름을 다른 종류로 쓰지 않게)
        self.ref = 0

    def name(self, base: str, kind: str) -> str:
        """날짜는 같은 이름이면 같은 칸(한 번 입력), 글자·금액 칸은 나올 때마다 새 칸."""
        base = re.sub(r"[\s·()\[\]「」『』:,.\-]+", " ", base).strip() or "내용"
        base = base.replace(" ", "")
        n, i = base, 2
        while n in self.used and (self.used[n] != kind or kind != "date"):
            n, i = f"{base}{i}", i + 1
        self.used[n] = kind
        return n


def _label(line: str, pos: int) -> str:
    """빈칸 앞의 '항목:' 이름. 없으면 바로 앞 낱말."""
    head = line[:pos]
    m = re.search(r"([가-힣A-Za-z][가-힣A-Za-z\s]{0,14}?)\s*:\s*[^:]*$", head)
    if m:
        lab = ITEM_RE.sub("", m.group(1)).strip()
        lab = re.sub(r"^.*[(（]", "", lab)
        if lab:
            return lab
    words = re.findall(r"[가-힣A-Za-z]+", head)
    return words[-1] if words else ""


def _after_word(line: str, end: int) -> str:
    m = re.match(r"\s*([가-힣]+)", line[end:])
    return m.group(1) if m else ""


DATE_PATTERNS = [
    # (정규식, 형식, 종류)
    (re.compile(r"20○○\.\s*○\.\s*○\.(\s*\([^)]{1}\))?"), "공문", "day"),
    (re.compile(r"20○○년\s*○월\s*○일(\s*\([^)]{1}\))?"), "일", "day"),
    (re.compile(r"20○○\.\s*○\.?\s*월"), "점월", "month"),
    (re.compile(r"20○○\.\s*○\.(?!\s*○)"), "년월점", "month"),
    (re.compile(r"20○○년\s*○월"), "월", "month"),
    (re.compile(r"['’‘]○○년\s*○월"), "짧은년월", "month"),
    (re.compile(r"['’‘]○○\.?\s*○월"), "짧은월", "month"),
    (re.compile(r"['’‘]○○년"), "짧은년", "month"),
    (re.compile(r"20○○년"), "년", "month"),
    (re.compile(r"(?<![○\d])○월\s*○일(\s*\([^)]{1}\))?"), "월일", "day"),
    (re.compile(r"(?<![○\d])○분기"), "분기만", "month"),
    (re.compile(r"(?<![○\d年월])○월"), "월만", "month"),
]
UNIT = r"(부|건|명|회|세대|호|개|대|장|박스|Box|매|kg|㎏|톤|%|인|가구|동|일|시간|분)"
REFS: dict[str, str] = {}   # '주거복지실-3344' → '2023. 1. 5.' (원문 본문에서 읽음)


def load_refs(raw_dir: str) -> None:
    """원문 본문(txt)에서 '부서-번호(날짜)' 관련 문서 날짜를 모은다."""
    for name in os.listdir(raw_dir):
        if not name.endswith(".txt"):
            continue
        with open(os.path.join(raw_dir, name), encoding="utf-8-sig") as f:
            text = f.read()
        for m in re.finditer(r"([가-힣]+-\d+)\(\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*\)", text):
            REFS[m.group(1)] = f"{m.group(2)}. {int(m.group(3))}. {int(m.group(4))}."


def tidy(line: str) -> str:
    """공문 작성법에 맞춰 쌍점·띄어 쓴 항목명을 고친다: '일 시：' → '일시: '"""
    line = line.replace("：", ":")
    line = re.sub(r"(?<![가-힣])([가-힣])\s+([가-힣])\s+([가-힣])\s*:", r"\1\2\3:", line)
    line = re.sub(r"(?<![가-힣])([가-힣])\s+([가-힣])\s*:", r"\1\2:", line)
    line = re.sub(r"(?<=[가-힣)])\s+:(?=\s)", ":", line)
    line = re.sub(r"(?<=[가-힣)]):(?=\S)", ": ", line)
    return line


def convert_line(line: str, nm: Namer, month_name: dict) -> str:
    """한 줄의 빈칸을 입력칸으로 바꾼다."""
    line = tidy(line)
    out, i = [], 0
    # 날짜·시간·차수·금액·숫자를 앞에서부터 차례로 찾는다
    combined = re.compile(
        "|".join(f"(?P<d{k}>{p.pattern})" for k, (p, _, _) in enumerate(DATE_PATTERNS))
        + r"|(?P<time>○○:○○(\s*~\s*○○:○○)?)"
        + r"|(?P<cha>(?<![○\d])○+(?P<chau>차|회차|주차))"
        + r"|(?P<amt>금○○○원\(금○○○원\))"
        + rf"|(?P<num>(?<![○\d])○+\s*(?P<unit>{UNIT}))"
        + r"|(?P<blank>○{2,})")
    for m in combined.finditer(line):
        out.append(line[i:m.start()])
        i = m.end()
        g = m.lastgroup
        lab = _label(line, m.start())
        if g.startswith("d"):
            _, style, kind = DATE_PATTERNS[int(g[1:])]
            wd = re.search(r"\([^)]\)\s*$", m.group(0))
            if wd and style in ("공문", "일", "월일"):
                style += "요일"
            if kind == "month":
                after = _after_word(line, m.end())
                key = MONTH_AFTER.get(after, "")
                if not key and re.search(r"[가-힣]+-\d*$", line[:m.start()].rstrip("(")):
                    key = "관련문서월"
                key = key or "대상월"
                name = month_name.setdefault(key, nm.name(key, "date"))
            else:
                ref = re.search(r"([가-힣]+-\d+)\($", line[:m.start()])
                if ref and ref.group(1) in REFS:          # 관련 문서 날짜는 원문 날짜로 고정
                    out.append(REFS[ref.group(1)])
                    continue
                if ref:
                    nm.ref += 1
                    base = f"관련문서{nm.ref}일자"
                else:
                    base = lab if lab and not re.search(r"\d", lab) else "날짜"
                    if base in ("일시", "일자", "날짜"):
                        base = {"일시": "일시", "일자": "일자"}.get(base, "날짜")
                if re.search(r"~\s*$", line[:m.start()]):
                    base += "끝"
                name = nm.name(base, "day")          # 하루 날짜는 나올 때마다 따로 입력
            out.append(f"{{날짜:{name}|{style}}}")
        elif g == "time":
            out.append("{" + nm.name((lab or "").replace("일시", "") + "시간", "text") + "}")
        elif g == "cha":
            unit = m.group("chau")
            out.append("{" + nm.name({"차": "차수"}.get(unit, unit), "text") + "}" + unit)
        elif g == "amt":
            out.append("{금액:" + nm.name(lab or "금액", "amount") + "}")
        elif g == "num":
            unit = m.group("unit")
            base = lab or "수량"
            if base == unit:
                base = "수량"
            out.append("{" + nm.name(base, "text") + "}" + (" " if m.group(0)[:-len(unit)].endswith(" ") else "") + unit)
        else:
            out.append(m.group(0))       # 이름 모를 빈칸은 그대로(직접 고침)
    out.append(line[i:])
    return "".join(out)


GROUPS = [
    ("관리비·회계", r"관리비|운영자금|잡수입|부금|정산|선수금|적립|외상|출납|예치금|저장품|소모품|구입|보험료"),
    ("안전·시설", r"안전|승강기|보안|소방|보일러|전지|제초|대청소|환경정비|재활용|폐기물|당직"),
    ("교육·행사", r"교육|청렴|상호존중|친절|민원방지|지구의날|체조"),
    ("주거복지·마이홈", r"주거복지|마이홈|돌봄|폭염|클린데이|나누리|간담회|소식지|공동체|안심의 날|시니어|꾸러미|스트레스|생활지원|사회복무"),
    ("임대·계약", r"계약|갱신|임대"),
    ("보고·공개", r"공개|보고|현황|단지회보"),
]


def group_of(name: str) -> str:
    for g, pat in GROUPS:
        if re.search(pat, name):
            return g
    return "기타"


def to_template(title: str, blocks: list, file_label: str) -> str:
    nm, months = Namer(), {}
    t = convert_line(title, nm, months)
    body = []
    for b in blocks:
        if isinstance(b, str):
            body.append(convert_line(b, nm, months))
        else:
            for ri, row in enumerate(b):
                body.append("| " + " | ".join(c.strip() or " " for c in row) + " |")
                if ri == 0 and len(b) > 1:
                    body.append("|---|")
    head = [f"제목: {t}", "수신자: 내부결재", f"구분: {group_of(file_label)}"]
    return "\n".join(head) + "\n---\n" + "\n".join(body).strip("\n") + "\n"


def main(src: str, dst: str, raw_dir: str = "") -> int:
    os.makedirs(dst, exist_ok=True)
    if raw_dir:
        load_refs(raw_dir)
    n = 0
    for name in sorted(os.listdir(src)):
        if not name.endswith(".hml"):
            continue
        title, blocks = read_hml(os.path.join(src, name))
        if not title:
            print("제목 없음:", name)
            continue
        base = os.path.splitext(name)[0]
        cls, no, rest = (base.split("_", 2) + ["", ""])[:3]
        label = f"{cls}{no}_{rest}" if rest else base
        with open(os.path.join(dst, label + ".txt"), "w", encoding="utf-8") as f:
            f.write(to_template(title, blocks, rest or base))
        n += 1
    print(f"서식 {n}개 → {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
