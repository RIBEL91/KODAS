"""주거행복지원 서비스 품질평가 평가표(엑셀) 읽기·쓰기와 항목별 증빙 폴더.

평가표 '항목별평가표' 시트 구조 (2026년 양식 기준, 해마다 같은 모양):
- A 평가부문, B 평가영역, C 평가지표 (병합 셀이라 윗칸에만 값), D 번호(1-1 등, 병합)
- E 평가항목('◦'로 시작) / 다음 줄 E '[평가기준] …'
- F 배점, G 평가점수, H 준비서류, I 평가 근거(문서번호 등), J 점검자 의견
증빙 폴더(폴더링)는 평가표가 있는 폴더 아래 '폴더링\\번호\\k. 항목' 모양이다.
4권(임대운영)·본지사 협조도는 번호 폴더가 바로 '폴더링' 아래에, 다른 부문은
번호가 겹치므로 '폴더링\\부문\\번호' 아래에 만든다.
"""
from __future__ import annotations

import datetime as dt
import glob
import os
import re
import shutil
import unicodedata
from functools import lru_cache
from dataclasses import dataclass, field

SHEET = "항목별평가표"
SUMMARY = "총괄표"
FOLDER = "폴더링"
REPORT4_PARTS = ("임대운영", "본.지사업무협조도")       # 4권(임대운영) 보고서 범위 → 폴더링 바로 아래
_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]+')


@dataclass
class Item:
    row: int                     # 엑셀 줄 번호(평가점수·근거를 쓸 줄)
    part: str                    # 평가부문 (유지관리, 임대운영 …)
    area: str                    # 평가영역
    indicator: str               # 평가지표
    no: str                      # 번호 (1-1 등, 가감점은 '' 일 수 있음)
    seq: int                     # 같은 번호 안에서 몇 번째 항목인지 (1부터) → 증빙 폴더 'k. …'
    text: str                    # 평가항목
    criteria: str = ""           # 평가기준
    max_score: float | None = None   # 배점 (가감점은 None)
    score: float | None = None   # 평가점수
    docs: str = ""               # 준비서류
    basis: str = ""              # 평가 근거
    reason: str = ""             # 점수 불인정 사유(점검자 의견, J열)
    flag: bool = False           # 작년과 비교해 없는 문서가 있어 노란색으로 표시
    evidence: list = field(default_factory=list)   # 증빙 파일 경로
    notes: list = field(default_factory=list)      # 파일 없이 이름만 둔 메모 폴더(예: '예비자 없음')
    auto_why: str = ""           # [점수 자동 매기기]로 넣은 점수의 까닭(화면에만, 저장 안 함)
    added: list = field(default_factory=list)   # 작년과 비교해 새로 들어간 근거 줄(엑셀에서 노란 글씨)

    @property
    def label(self) -> str:
        return f"{self.no} {self.text}".strip()


BONUS = "가감점"
_NA = re.compile(r"^\s*해당\s*(사항)?\s*없음")


def _is_na(text: str) -> bool:
    return bool(_NA.match(text or ""))


def auto_score(it: Item, prev: Item | None) -> tuple[float | None, str]:
    """항목 하나의 점수를 매긴다 → (점수, 까닭). 매길 수 없으면 (None, 까닭).

    - 올해 평가 근거·증빙이 하나도 없으면 매기지 않는다(직접 넣도록 빈칸).
    - 근거가 '해당없음': 작년에도 해당없음이면 작년 점수, 가감점이면 0점, 아니면 매기지 않는다.
    - 근거가 있으면 작년 같은 항목(부문·번호·순서) 점수를 그대로(배점 넘지 않게).
      작년 점수가 없으면 배점 만점, 가감점은 근거만으로 알 수 없어 매기지 않는다.
    - 작년보다 없는 문서가 있는 항목(노란 줄)은 점수는 위와 같이 넣되 '확인 필요'를 붙인다.
    """
    body = "\n".join(x for x in (it.basis or "").split("\n") if not x.startswith(MISS_MARK)).strip()   # '✗ 없음' 줄 빼고
    has_basis = bool(body) or bool(it.evidence) or bool(it.notes)
    if not has_basis:
        return None, "평가 근거·증빙이 없어 매기지 않았습니다"
    prev_score = prev.score if prev is not None else None
    if _is_na(it.basis) and not it.evidence:
        if prev is not None and _is_na(prev.basis) and prev_score is not None:
            return prev_score, f"해당없음 — 작년(해당없음)과 같이 {prev_score:g}점"
        if it.part == BONUS:
            return 0.0, "해당없음 — 가감점 0점"
        return None, "근거가 '해당없음'이라 매기지 않았습니다(배점 기준 확인)"
    if prev_score is not None:
        score = min(prev_score, it.max_score) if it.max_score is not None and prev_score >= 0 else prev_score
        why = f"작년 같은 항목 점수 {prev_score:g}점"
    elif it.part == BONUS or it.max_score is None:
        return None, "가감점은 근거만으로 점수를 알 수 없어 매기지 않았습니다"
    else:
        score, why = it.max_score, f"근거 있음 — 배점 만점 {it.max_score:g}점"
    if it.flag:
        why += " · 작년보다 없는 문서가 있어 확인 필요"
    return score, why


def auto_scores(items: list[Item], prev_items: list[Item] | None = None) -> list[tuple[Item, float | None, str]]:
    """items 전체에 auto_score를 돌린다. 작년 항목은 (부문, 번호, 순서)로 짝짓는다."""
    by_key = {(p.part, p.no, p.seq): p for p in (prev_items or [])}
    return [(it, *auto_score(it, by_key.get((it.part, it.no, it.seq)))) for it in items]


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _short(part: str) -> str:
    """'임대운영 \\n(18)' → '임대운영'."""
    return re.sub(r"\s*\(.*$", "", _s(part).replace("\n", " ")).replace(" ", "")


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        return None           # 수식(=SUM…) 등


def _merged_top(ws):
    """병합 셀의 윗칸 값을 아래 칸에서도 찾을 수 있게 {(행, 열): 값}."""
    out = {}
    for rng in ws.merged_cells.ranges:
        v = ws.cell(rng.min_row, rng.min_col).value
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                out[(r, c)] = v
    return out


def load(path: str) -> list[Item]:
    """평가표에서 평가항목을 읽는다."""
    from openpyxl import load_workbook
    wb = load_workbook(path, rich_text=True)        # 평가 근거의 빨간·노란 글씨를 읽으려고
    if SHEET not in wb.sheetnames:
        raise ValueError(f"'{SHEET}' 시트가 없습니다. 품질평가 평가표 엑셀이 맞는지 확인해 주세요.")
    ws = wb[SHEET]
    merged = _merged_top(ws)

    def val(r, c):
        v = ws.cell(r, c).value
        return merged.get((r, c), v) if v is None else v

    items: list[Item] = []
    part = area = ind = no = ""
    seq = 0
    for r in range(5, ws.max_row + 1):
        a, b, c, d = (_s(ws.cell(r, i).value) for i in (1, 2, 3, 4))
        if a and a not in ("평가점수", "총점"):
            part, area, ind = a, "", ""
        if b:
            area, ind = b, ""
        if c:
            ind = c
        text = _s(ws.cell(r, 5).value)
        if d:
            d = unicodedata.normalize("NFKC", d)
        if d and d != no:
            no, seq = d, 0
        if not text:
            continue
        if text.startswith("[평가기준]"):
            if items and items[-1].row == r - 1:
                items[-1].criteria = text.replace("[평가기준]", "", 1).strip()
            continue
        is_item = text.startswith("◦") or re.match(r"^1\.\s", text)
        if not is_item:
            continue
        if not part or part.startswith(("평가점수", "총점")):
            continue
        seq += 1
        basis = _s(val(r, 9))
        items.append(Item(row=r, part=_short(part), area=_short(area), indicator=_short(ind), no=no, seq=seq,
                          text=text.lstrip("◦").strip(), max_score=_num(ws.cell(r, 6).value),
                          score=_num(val(r, 7)), docs=_s(ws.cell(r, 8).value), basis=basis,
                          reason=_s(val(r, 10)),
                          flag=_is_flag(ws, r) or any(x.startswith(MISS_MARK) for x in basis.split("\n")),
                          added=_colored_lines(ws.cell(*_top_left(ws, r, 9)).value, ADDED_COLOR)))
    if not items:
        raise ValueError("평가항목을 찾지 못했습니다. 평가표 양식이 바뀌었는지 확인해 주세요.")
    for it in items:
        _migrate_reason(it)
    return items


OLD_LACK = "작년과 비교해 없는 항목: "             # 예전에 점수 불인정 사유 칸에 적던 머리말
OLD_SUP_LACK = re.compile(r"^(?P<label>.*?)\s*작성분과 비교해 없는 항목: (?P<rest>.*)$")


def _migrate_reason(it: Item) -> None:
    """예전 방식(사유 칸에 '작년과 비교해 없는 항목: …' + 노란 칸)을 평가 근거의 '✗ …' 줄(빨간 글씨)로 옮긴다."""
    keep, miss = [], []
    for line in (it.reason or "").split("\n"):
        m = OLD_SUP_LACK.match(line)
        if line.startswith(OLD_LACK):
            miss += [f"{MISS_MARK}작년에 있고 올해 없음: {x.strip()}" for x in line[len(OLD_LACK):].split(", ") if x.strip()]
        elif m:
            miss += [f"{MISS_MARK}{m['label']} 작성분에 있고 올해 없음: {x.strip()}"
                     for x in m["rest"].split(", ") if x.strip()]
        else:
            keep.append(line)
    if not miss:
        return
    have = set(it.basis.split("\n"))
    it.basis = "\n".join(x for x in [it.basis.strip()] + [x for x in miss if x not in have] if x)
    it.reason = "\n".join(keep).strip()
    it.flag = True


def complex_name(path: str) -> str:
    """'○ 단지명 : 광주양림2' 칸에서 단지명."""
    from openpyxl import load_workbook
    ws = load_workbook(path, read_only=True)[SHEET]
    for row in ws.iter_rows(min_row=1, max_row=4, values_only=True):
        for v in row:
            m = re.match(r"\s*○\s*단지명\s*:\s*(.*)", _s(v))
            if m:
                return m.group(1).strip()
    return ""


def save(path: str, items: list[Item], complex_label: str = "", backup_dir: str = "") -> str:
    """평가점수(G)·평가 근거(I)를 평가표에 쓴다. 단지명이 비어 있으면 채운다.

    엑셀에서 파일을 열어 둔 상태면 PermissionError. 쓰기 전에 backup_dir에 원본을 복사해 둔다.
    돌려주는 값은 백업 파일 경로(없으면 '').
    """
    from openpyxl import load_workbook
    bak = ""
    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(path))[0]
        bak = os.path.join(backup_dir, f"{stem}_{dt.datetime.now():%Y%m%d_%H%M%S}.xlsx")
        shutil.copy2(path, bak)
        _trim_backups(backup_dir, stem)
    wb = load_workbook(path, rich_text=True)        # 다른 칸의 글자 꾸밈도 그대로 둔다
    ws = wb[SHEET]
    for it in items:
        _put(ws, it.row, 7, it.score)
        _put(ws, it.row, 9, _basis_value(ws, it) if it.basis else None)
        _put(ws, it.row, 10, it.reason or None)
        for col in (9, 10):                 # 예전 방식의 노란 칸 칠은 지운다(없는 문서는 이제 빨간 글씨 줄로)
            _fill(ws, it.row, col, False)
        if it.basis or it.reason:           # 근거·사유: 줄 바꿈·왼쪽 맞춤, 글자가 다 보이게 행 높이
            _tidy(ws, it.row, [c for c, v in ((9, it.basis), (10, it.reason)) if v])
    if complex_label:
        for r in range(1, 5):
            for c in range(1, ws.max_column + 1):
                v = _s(ws.cell(r, c).value)
                if re.fullmatch(r"○\s*단지명\s*:\s*", v):
                    ws.cell(r, c).value = f"○ 단지명 : {complex_label}"
        if SUMMARY in wb.sheetnames:
            s = wb[SUMMARY]
            if not _s(s["B5"].value):
                s["B5"].value = complex_label
    wb.save(path)
    return bak


FLAG_COLOR = "FFFFF200"          # (예전) 노란 칸 표시 — 이 색일 때만 우리가 칠한 것으로 보고 지운다
MISS_MARK = "✗ "                 # 평가 근거의 '작년에 있고 올해 없는 문서' 줄 (quality_draft.MISS_MARK와 같게)
MISS_COLOR = "FFFF0000"          # 없는 문서 줄: 빨간 글씨
ADDED_COLOR = "FFFFC000"         # 작년과 비교해 새로 들어간 줄: 노란 글씨(흰 바탕에서 읽히는 진한 노랑)


def _basis_value(ws, it: Item):
    """평가 근거 칸에 쓸 값: 없는 문서 줄은 빨간 글씨, 새로 들어간 줄은 노란 글씨, 나머지는 칸 글꼴 그대로."""
    lines = it.basis.split("\n")
    added = set(it.added or [])
    if not any(x.startswith(MISS_MARK) or x in added for x in lines):
        return it.basis
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    from openpyxl.cell.text import InlineFont
    f = ws.cell(*_top_left(ws, it.row, 9)).font
    name, size = f.name or "맑은 고딕", f.sz or 11

    def font(color=None):
        return InlineFont(rFont=name, sz=size, color=color)
    parts = []
    for i, line in enumerate(lines):
        text = line + ("\n" if i < len(lines) - 1 else "")
        color = MISS_COLOR if line.startswith(MISS_MARK) else ADDED_COLOR if line in added else None
        parts.append(TextBlock(font(color), text))
    return CellRichText(parts)


def _colored_lines(value, color: str) -> list:
    """글자 꾸밈이 있는 칸에서 줄 전체가 color 글씨인 줄들."""
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    if not isinstance(value, CellRichText):
        return []
    chars = []                       # 글자마다 (글자, 이 색인지)
    for part in value:
        if isinstance(part, TextBlock):
            c = part.font.color.rgb if part.font is not None and part.font.color is not None else None
            on = str(c or "").upper() == color
            chars += [(ch, on) for ch in part.text]
        else:
            chars += [(ch, False) for ch in str(part)]
    out, cur, all_on = [], "", True
    for ch, on in chars + [("\n", True)]:
        if ch == "\n":
            if cur.strip() and all_on:
                out.append(cur.strip())
            cur, all_on = "", True
            continue
        cur += ch
        all_on = all_on and on
    return out


def _top_left(ws, row: int, col: int) -> tuple:
    for rng in ws.merged_cells.ranges:
        if rng.min_row <= row <= rng.max_row and rng.min_col <= col <= rng.max_col:
            return rng.min_row, rng.min_col
    return row, col


FONT_FILES = {"맑은 고딕": "malgun.ttf", "Malgun Gothic": "malgun.ttf", "굴림": "gulim.ttc", "돋움": "gulim.ttc",
              "바탕": "batang.ttc", "궁서": "batang.ttc"}


@lru_cache(maxsize=16)
def _pil_font(name: str, px: int, bold: bool):
    """글자 폭을 재는 글꼴(윈도 글꼴 폴더). 없으면 None → 어림셈."""
    try:
        from PIL import ImageFont
        fname = FONT_FILES.get(name or "", "malgun.ttf")
        if bold and fname == "malgun.ttf":
            fname = "malgunbd.ttf"
        return ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", fname), px)
    except Exception:
        return None


def _px(text: str, font, size_pt: float) -> float:
    """화면(96dpi)에서 text가 차지하는 폭(픽셀)."""
    if font is not None:
        return font.getlength(text)
    import unicodedata
    em = size_pt * 96 / 72
    return sum(em if unicodedata.east_asian_width(ch) in ("W", "F") else em * 0.55 for ch in text)


def _wrap_lines(text: str, width_px: float, font, size_pt: float) -> int:
    """엑셀처럼 띄어쓰기에서 줄을 바꿔(한 낱말이 너무 길면 글자 단위로) 몇 줄이 되는지."""
    n = 0
    for para in text.split("\n"):
        line, count = "", 1
        for word in para.split(" "):
            trial = f"{line} {word}" if line else word
            if _px(trial, font, size_pt) <= width_px:
                line = trial
                continue
            if line:
                count += 1
            line = word
            while _px(line, font, size_pt) > width_px and len(line) > 1:   # 낱말 하나가 칸보다 길 때
                cut = len(line)
                while cut > 1 and _px(line[:cut], font, size_pt) > width_px:
                    cut -= 1
                line = line[cut:]
                count += 1
        n += count
    return n


def _col_px(width_chars: float, mdw: int = 8) -> float:
    """엑셀 열 너비(글자 수) → 픽셀. 기본 글꼴(맑은 고딕 11pt)의 숫자 폭 mdw=8px."""
    return int(width_chars * mdw + 5)


def _merged_range(ws, row: int, col: int) -> tuple:
    for rng in ws.merged_cells.ranges:
        if rng.min_row <= row <= rng.max_row and rng.min_col <= col <= rng.max_col:
            return rng.min_row, rng.max_row, rng.min_col, rng.max_col
    return row, row, col, col


def _tidy(ws, row: int, cols: list) -> None:
    """근거·사유 칸을 줄 바꿈·왼쪽 맞춤(세로 가운데)으로 하고, 글자가 다 보이도록 행 높이를 늘린다.
    병합된 칸(항목 줄 + 평가기준 줄)은 줄 높이 합으로 보고, 모자라면 항목 줄을 늘린다(줄이지는 않음)."""
    from openpyxl.styles import Alignment
    from openpyxl.utils import get_column_letter
    default_h = ws.sheet_format.defaultRowHeight or 15
    need, span = 0.0, None
    for col in cols:
        r0, r1, c0, c1 = _merged_range(ws, row, col)
        cell = ws.cell(r0, c0)
        cell.alignment = Alignment(wrap_text=True, horizontal="left", vertical="center")
        text = str(cell.value or "")
        if not text:
            continue
        width_px = sum(_col_px(ws.column_dimensions[get_column_letter(c)].width or 8.43) for c in range(c0, c1 + 1))
        size = float(cell.font.sz or 11)
        font = _pil_font(cell.font.name or "맑은 고딕", round(size * 96 / 72), bool(cell.font.b))
        lines = _wrap_lines(text, width_px - 8, font, size)           # 칸 안쪽 여백 몇 픽셀
        need = max(need, lines * size * 1.5 + 6)          # 맑은 고딕 한 줄 높이 ≈ 글자 크기 × 1.5pt
        span = (r0, r1)
    if not span:
        return
    r0, r1 = span
    have = sum((ws.row_dimensions[r].height or default_h) for r in range(r0, r1 + 1))
    lack = need - have
    for r in range(r0, r1 + 1):                 # 항목 줄부터 늘리고, 한 줄 한도(409pt)를 넘으면 다음 줄로
        if lack <= 0:
            break
        cur = ws.row_dimensions[r].height or default_h
        new = min(409.0, cur + lack)
        ws.row_dimensions[r].height = round(new, 2)
        lack -= new - cur


def _fill(ws, row: int, col: int, on: bool) -> None:
    from openpyxl.styles import PatternFill
    r, c = _top_left(ws, row, col)
    cell = ws.cell(r, c)
    cur = (cell.fill.fgColor.rgb if cell.fill and cell.fill.fill_type == "solid" else "") or ""
    if on:
        cell.fill = PatternFill("solid", fgColor=FLAG_COLOR)
    elif str(cur).upper() == FLAG_COLOR:
        cell.fill = PatternFill(fill_type=None)


def _is_flag(ws, row: int) -> bool:
    r, c = _top_left(ws, row, 9)
    f = ws.cell(r, c).fill
    return bool(f and f.fill_type == "solid" and str(f.fgColor.rgb).upper() == FLAG_COLOR)


def _put(ws, row: int, col: int, value) -> None:
    """병합된 칸이면 그 병합 영역의 첫 칸에 쓴다(양식마다 병합 모양이 조금씩 다름)."""
    for rng in ws.merged_cells.ranges:
        if rng.min_row <= row <= rng.max_row and rng.min_col <= col <= rng.max_col:
            row, col = rng.min_row, rng.min_col
            break
    ws.cell(row, col).value = value


def _trim_backups(folder: str, stem: str, keep: int = 20) -> None:
    olds = sorted(glob.glob(os.path.join(glob.escape(folder), glob.escape(stem) + "_*.xlsx")))
    for p in olds[:-keep]:
        try:
            os.remove(p)
        except OSError:
            pass


# ---------------- 증빙 폴더 ----------------
def evidence_root(xlsx_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(xlsx_path)), FOLDER)


def _no_dir(root: str, it: Item) -> str:
    no = it.no or "가감점"
    if it.part in REPORT4_PARTS:
        return os.path.join(root, no)
    return os.path.join(root, _BAD.sub(" ", it.part), no)


def item_dir(root: str, it: Item, create: bool = False) -> str:
    """항목 증빙 폴더. 'k. …'로 시작하는 폴더가 있으면 그것(이름은 양식마다 조금씩 다름)."""
    base = _no_dir(root, it)
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            if os.path.isdir(os.path.join(base, name)) and re.match(rf"^{it.seq}\s*[.)]", name):
                return os.path.join(base, name)
    title = _BAD.sub(" ", re.sub(r"^\d+(-\d+)*\.\s*", "", it.text)).strip()
    title = re.sub(r"\s+", " ", title)[:40].rstrip(" .")
    path = os.path.join(base, f"{it.seq}. {title}")
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def scan_evidence(root: str, items: list[Item]) -> None:
    """항목마다 증빙 파일 목록을 채운다(하위 폴더 포함, 빈 폴더 이름만 있는 것은 파일 아님)."""
    for it in items:
        d = item_dir(root, it)
        files, notes = [], []
        if os.path.isdir(d):
            for base, dirs, names in os.walk(d):
                notes += [n for n in dirs if not os.listdir(os.path.join(base, n))]
                files += [os.path.join(base, n) for n in names if not n.startswith(("~$", "."))
                          and n.lower() != "thumbs.db"]
        it.evidence = sorted(files)
        it.notes = notes


def make_folders(root: str, items: list[Item]) -> int:
    """항목별 증빙 폴더를 만든다. 새로 만든 폴더 수."""
    made = 0
    for it in items:
        d = item_dir(root, it)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            made += 1
    return made


def is_sheet(path: str) -> bool:
    """품질평가 평가표 엑셀인지 — 파일 이름과 상관없이 '항목별평가표' 시트가 있는지 본다(빨리: 압축 안의 목록만)."""
    import zipfile
    if not path.lower().endswith(".xlsx") or os.path.basename(path).startswith("~$"):
        return False
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("xl/workbook.xml").decode("utf-8", "ignore")
    except Exception:
        return False
    return re.search(rf'<sheet\b[^>]*\bname="{re.escape(SHEET)}"', xml) is not None


def scan_sheets(folders: list[str], depth: int = 4, limit: int = 3000) -> list[str]:
    """폴더들(하위 depth단계까지)에서 품질평가 평가표 엑셀만 찾는다(최근 수정 순, 같은 파일은 한 번)."""
    return sorted(iter_sheets(folders, depth, limit), key=os.path.getmtime, reverse=True)


def quick_year(path: str) -> int | None:
    """목록에 보일 평가년도: 파일 이름의 '2026년도'를 먼저(빠름), 없으면 시트 제목에서."""
    m = re.search(r"(20\d\d)\s*년도", os.path.basename(path))
    return int(m[1]) if m else sheet_year(path)


def iter_sheets(folders: list[str], depth: int = 4, limit: int = 3000):
    """scan_sheets와 같되 찾는 대로 하나씩 내준다(고르기 창이 바로바로 보여 주게).
    살펴볼 엑셀이 limit개를 넘으면 거기까지만 본다."""
    seen, looked = set(), 0
    for top in folders:
        if not top or not os.path.isdir(top):
            continue
        for base, dirs, names in os.walk(top):
            if base.count(os.sep) - top.count(os.sep) >= depth:
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith((".", "$")) and d not in ("node_modules", "AppData")]
            for n in names:
                if not n.lower().endswith(".xlsx") or n.startswith("~$"):
                    continue
                p = os.path.normcase(os.path.abspath(os.path.join(base, n)))
                if p in seen:
                    continue
                seen.add(p)
                looked += 1
                if looked > limit:
                    return
                if is_sheet(p):
                    yield os.path.join(base, n)


def find_sheets(folders: list[str], year: int | None = None) -> list[str]:
    """바탕화면 등에서 품질평가 평가표 엑셀을 찾는다(최근 수정 순). year가 있으면 그 해 파일 우선."""
    found = []
    for top in folders:
        if not os.path.isdir(top):
            continue
        for base, dirs, names in os.walk(top):
            if base.count(os.sep) - top.count(os.sep) >= 4:
                dirs[:] = []
            for n in names:
                if n.lower().endswith(".xlsx") and "품질평가" in n and "평가표" in n and not n.startswith("~$"):
                    found.append(os.path.join(base, n))
    found.sort(key=lambda p: (str(year) in os.path.basename(p) if year else False, os.path.getmtime(p)),
               reverse=True)
    return found


def sheet_year(path: str) -> int | None:
    """평가년도: 시트 제목('2026년도 주거행복지원 …') 또는 파일 이름에서."""
    from openpyxl import load_workbook
    try:
        ws = load_workbook(path, read_only=True)[SHEET]
        for row in ws.iter_rows(min_row=1, max_row=2, values_only=True):
            for v in row:
                m = re.search(r"(20\d\d)\s*년도", _s(v))
                if m:
                    return int(m[1])
    except Exception:
        pass
    m = re.search(r"(20\d\d)\s*년도", os.path.basename(path))
    return int(m[1]) if m else None


def save_as(src: str, dst: str, items: list[Item], complex_label: str = "") -> str:
    """src 평가표를 dst로 복사하고 점수·근거를 써 넣는다(완성본 내려받기). src는 그대로."""
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy2(src, dst)
    save(dst, items, complex_label)
    return dst
