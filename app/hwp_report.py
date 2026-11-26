"""품질평가 보고서(1~4권) 한글파일 작성.

양식(한글)을 복사해 아래를 채운다. 양식은 해마다 비슷한 모양이라 글자·표 모양으로 자리를 찾는다.
  - 표지·서약서: 평가년도('2026년도'), 제출 연월('2027. 2.'), 센터 이름(양식 예시 단지명), 관리소장 성명
  - 항목 쪽: 머리 표의 '득점:' 뒤에 그 번호(1-1 등)의 점수 합계, [점검내용] 표의 '점검결과' 칸에 항목 점수(평가표 G열)
  - 증빙 쪽: 머리칸이 '1-1. 제목'인 표의 사진칸(높이 40mm 넘는 칸)에 폴더링\\번호\\k. 항목 안의 파일을 쪽 그림으로 넣는다.
    PDF·한글·엑셀·워드는 쪽마다 그림으로 바꾸고(잠긴 파일은 비밀번호 1~3을 넣어 봄), 설명은 '문서 제목 - 쪽'.
    A4 세로 쪽은 넓은 칸에 2장(나란히)·큰 칸에 4장(2×2), 큰 칸의 가로 화면은 2장(위아래)씩 넣는데, 그림을 합치지 않고
    칸 안에 작은 표를 만들어 한 칸에 하나씩 넣고 그림마다 제목 칸을 단다(빈 자리는 '-공란-'). 칸이 모자라면 증빙 쪽을 복사해 늘리고,
    양식에 그 번호의 증빙 쪽이 없으면 다른 증빙 쪽을 복사해 머리칸을 그 번호로 바꿔 만든다.
양식 예시 사진(다른 단지 것)은 사진을 넣는 칸에서 지운다. 한글·엑셀 경고창은 [모두 허용]을 대신 누른다.
한글(HWPFrame.HwpObject)이 설치돼 있어야 한다.
"""
from __future__ import annotations

import difflib
import glob
import os
import re
import shutil
import sys
import tempfile

import page_images as pi
import paths
import quality_eval as qe

PHOTO_MIN_MM = 40          # 이보다 높은 칸을 사진칸으로 본다
TALL_MM = 150              # 이보다 높은 사진칸은 큰 칸(2×2)
NARROW_MM = 120            # 이보다 좁은 사진칸은 그림 하나씩
MM = 283.465               # HWPUNIT per mm
SAMPLE_CENTER = "목포상동1"  # 양식에 들어 있는 예시 단지명
SAMPLE_CHIEF = "김 동 준"
SAMPLE_YEAR = "2026"

_HEAD = re.compile(r"^(\d+-\d+)\.\s*(.+?)\s*\(([^()]*)\)\s*(\||$)")      # 1-1. 제목(3) | … 득점:
_EVID = re.compile(r"^(\d+-\d+)\.\s*([^()|\t]+?)\s*$")                       # 1-1. 제목 (증빙 쪽 머리칸)


class ReportError(Exception):
    pass


# ---------------- 양식·증빙 쪽 그림 ----------------
def template_path(vol: int, extra_dirs: list[str] = ()) -> str:
    """양식: exe 옆(또는 평가표 폴더)에 '(양식)…(N권)….hwp'가 있으면 그것(가장 최근), 없으면 프로그램에 든 것."""
    found = []
    for d in [paths.program_dir(), os.path.join(paths.program_dir(), "품평 한글파일 작성전"), *extra_dirs]:
        if d and os.path.isdir(d):
            found += [p for p in glob.glob(os.path.join(glob.escape(d), "*.hwp"))
                      if "양식" in os.path.basename(p) and f"({vol}권)" in os.path.basename(p)]
    if found:
        return max(found, key=os.path.getmtime)
    p = os.path.join(paths.bundle_dir(), "assets", "양식", f"{vol}권.hwp")
    if not os.path.isfile(p):
        raise ReportError(f"{vol}권 양식을 찾지 못했습니다.")
    return p


def _caption(path: str, folder_title: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    if re.fullmatch(r"[\d\s_()\-.]+", stem) or stem.startswith(("화면 캡처", "스크린샷", "KakaoTalk", "IMG_")):
        return folder_title
    return pi.clean_title(path)


def number_pages(root: str, items: list[qe.Item], tmp: str, passwords=(), hwp=None, log=None,
                 res: dict | None = None) -> list[tuple[str, str]]:
    """한 번호의 항목들(seq 순) 폴더의 증빙 파일 → (쪽 그림, 설명) 목록."""
    out = []
    for it in sorted(items, key=lambda i: i.seq):
        d = qe.item_dir(root, it)
        if not os.path.isdir(d):
            continue
        title = re.sub(r"^\d+\s*[.)]\s*", "", os.path.basename(d))
        files = []
        for base, _dirs, names in os.walk(d):
            files += [os.path.join(base, n) for n in names
                      if not n.startswith(("~$", ".")) and n.lower() != "thumbs.db" and not n.endswith("(이유).txt")]
        for f in sorted(files, key=pi.natural_key):
            pages, st = pi.file_pages(f, tmp, passwords, hwp, log)
            if st == "locked" and res is not None:
                res["locked"].append(os.path.basename(f))
            if st == "skip":
                continue
            cap = _caption(f, title)
            if len(pages) == 1:
                out.append((pages[0], cap))
            else:
                out += [(p, f"{cap} - {i}") for i, p in enumerate(pages, 1)]
    return out


# ---------------- 한글 ----------------
class Hwp:
    def __init__(self, visible: bool = False):
        try:
            import pythoncom
            import win32com.client as w
        except ImportError as ex:
            raise ReportError("한글 연결 모듈(pywin32)이 없습니다.") from ex
        pythoncom.CoInitialize()
        try:
            self.h = w.gencache.EnsureDispatch("HWPFrame.HwpObject")
        except Exception:
            try:
                self.h = w.Dispatch("HWPFrame.HwpObject")
            except Exception as ex:
                raise ReportError("한글 프로그램을 열지 못했습니다. 한글이 설치돼 있는지 확인해 주세요.") from ex
        self.h.XHwpWindows.Item(0).Visible = visible
        try:
            self.h.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception:
            pass
        try:
            self.h.SetMessageBoxMode(0x00020021)     # 묻는 창은 기본값(확인/예)으로 넘긴다
        except Exception:
            pass

    def run(self, name: str):
        return self.h.HAction.Run(name)

    def open(self, path: str):
        if not self.h.Open(path, "HWP", "forceopen:true"):
            raise ReportError(f"양식을 열지 못했습니다: {path}")

    def save_as(self, path: str):
        self.h.SaveAs(path, "HWP", "")

    def quit(self):
        try:
            self.h.Clear(1)
            self.h.Quit()
        except Exception:
            pass

    def replace_all(self, find: str, repl: str) -> None:
        h = self.h
        h.MovePos(2)
        pset = h.HParameterSet.HFindReplace
        h.HAction.GetDefault("AllReplace", pset.HSet)
        pset.FindString = find
        pset.ReplaceString = repl
        pset.IgnoreMessage = 1
        pset.Direction = 0
        pset.FindType = 1
        pset.WholeWordOnly = 0
        pset.MatchCase = 0
        pset.SeveralWords = 0
        pset.UseWildCards = 0
        pset.AllWordForms = 0
        pset.FindRegExp = 0
        pset.ReplaceMode = 1
        h.HAction.Execute("AllReplace", pset.HSet)

    def cell_text(self) -> str:
        self.run("Cancel")
        self.run("SelectAll")                         # 칸 안에서는 그 칸 내용만 고른다
        t = self.h.GetTextFile("UNICODE", "saveblock") or ""
        self.run("Cancel")
        return t.replace("\r\n", "\n").strip()

    def cell_size(self) -> tuple[float, float]:
        pset = self.h.HParameterSet.HShapeObject
        self.h.HAction.GetDefault("TablePropertyDialog", pset.HSet)
        c = pset.ShapeTableCell
        return c.Width / MM, c.Height / MM

    def clear_cell(self) -> None:
        self.run("Cancel")
        self.run("SelectAll")
        self.run("Delete")
        self.run("Cancel")

    def _insert_text(self, text: str) -> None:
        self.h.HAction.GetDefault("InsertText", self.h.HParameterSet.HInsertText.HSet)
        self.h.HParameterSet.HInsertText.Text = text
        self.h.HAction.Execute("InsertText", self.h.HParameterSet.HInsertText.HSet)

    def set_cell(self, text: str) -> None:
        self.clear_cell()
        self._insert_text(text)

    def append_cell(self, text: str) -> None:
        self.run("Cancel")
        self.run("MoveListEnd")
        self._insert_text(text)

    def pos(self):
        return self.h.GetPos()

    def enter_table(self, ctrl) -> bool:
        self.h.SetPosBySet(ctrl.GetAnchorPos(0))
        if not self.h.FindCtrl():
            return False
        ok = bool(self.run("ShapeObjTableSelCell"))
        self.run("Cancel")
        return ok

    def leave_table(self):
        self.run("Cancel")
        self.run("CloseEx")

    def table_cells(self, ctrl) -> list[dict]:
        """표의 칸들을 차례로: [{list, w, h, text}] (첫 칸부터 오른쪽·다음 줄 순)."""
        if not self.enter_table(ctrl):
            return []
        cells, seen = [], set()
        for _ in range(80):
            lid = self.pos()[0]
            if lid in seen:
                break
            seen.add(lid)
            w, hgt = self.cell_size()
            cells.append({"list": lid, "w": w, "h": hgt, "text": self.cell_text()})
            self.run("TableRightCell")
        self.leave_table()
        return cells

    def goto_cell(self, lid: int) -> None:
        self.h.SetPos(lid, 0, 0)

    def lower_cell_of(self, lid: int) -> int | None:
        self.goto_cell(lid)
        self.run("TableLowerCell")
        n = self.pos()[0]
        return None if n == lid else n

    def right_cell_of(self, lid: int) -> int | None:
        self.goto_cell(lid)
        self.run("TableRightCell")
        n = self.pos()[0]
        return None if n == lid else n

    def insert_picture(self, path: str) -> None:
        self.run("ParagraphShapeAlignCenter")
        # sizeoption 3: 칸에 맞추되 그림 비율 유지(칸 크기는 그대로)
        self.h.InsertPicture(path, True, 3, False, False, 0, 0, 0)

    def _cell_style(self, fill: bool, left: bool, right: bool, top: bool, bottom: bool) -> None:
        """지금 칸의 테두리(가는 실선/없음)와 회색 바탕."""
        h = self.h
        self.run("TableCellBlock")
        p = h.HParameterSet.HCellBorderFill
        h.HAction.GetDefault("CellBorderFill", p.HSet)
        solid, none = h.HwpLineType("Solid"), h.HwpLineType("None")
        p.BorderTypeLeft = solid if left else none
        p.BorderTypeRight = solid if right else none
        p.BorderTypeTop = solid if top else none
        p.BorderTypeBottom = solid if bottom else none
        for side in ("Left", "Right", "Top", "Bottom"):
            setattr(p, f"BorderWidth{side}", h.HwpLineWidth("0.12mm"))
            # 한글 쪽 이름이 왼쪽만 'BorderCorlorLeft'(오타)다
            setattr(p, "BorderCorlorLeft" if side == "Left" else f"BorderColor{side}", h.RGBColor(160, 160, 160))
        if fill:
            p.FillAttr.type = h.BrushType("NullBrush|WinBrush")
            p.FillAttr.WinBrushFaceColor = h.RGBColor(220, 220, 220)
            p.FillAttr.WinBrushHatchColor = h.RGBColor(153, 153, 153)
            p.FillAttr.WinBrushFaceStyle = h.HatchStyle("None")
            p.FillAttr.WindowsBrush = 1
        h.HAction.Execute("CellBorderFill", p.HSet)
        self.run("Cancel")

    def _create_grid(self, cols: int, nrow: int, W: float, H: float, cap_h: float, n_caps: int, rows: int) -> list[int]:
        """지금 칸에 작은 표를 만들고 그 칸 번호들(왼쪽→오른쪽, 위→아래)을 돌려준다."""
        h = self.h
        photo_h = (H - cap_h * n_caps) / rows
        heights = [photo_h if i % 2 == 0 else cap_h for i in range(nrow)]
        self.run("ParagraphShapeAlignCenter")
        pc = h.HParameterSet.HTableCreation
        h.HAction.GetDefault("TableCreate", pc.HSet)
        pc.Rows, pc.Cols, pc.WidthType, pc.HeightType = nrow, cols, 2, 1
        pc.WidthValue = h.MiliToHwpUnit(W)
        pc.HeightValue = h.MiliToHwpUnit(H)
        pc.CreateItemArray("ColWidth", cols)
        for c in range(cols):
            pc.ColWidth.SetItem(c, h.MiliToHwpUnit(W / cols))
        pc.CreateItemArray("RowHeight", nrow)
        for i, v in enumerate(heights):
            pc.RowHeight.SetItem(i, h.MiliToHwpUnit(v))
        pc.TableProperties.TreatAsChar = 1
        if not h.HAction.Execute("TableCreate", pc.HSet):
            raise ReportError("사진칸 나누기에 실패했습니다.")
        grid = []
        for _ in range(nrow * cols):
            grid.append(self.pos()[0])
            self.run("TableRightCell")
        return grid

    def _fit_picture(self, path: str) -> None:
        """지금 칸 안쪽에 꼭 맞는 크기로 그림을 넣는다(칸에 맞춤으로 넣으면 칸이 조금 늘어난다)."""
        from PIL import Image
        cw, ch = self.cell_size()
        bw, bh = max(cw - 5.0, 10), max(ch - 3.0, 10)
        with Image.open(path) as im:
            iw, ih = im.size
        k = min(bw / iw, bh / ih)
        self.run("ParagraphShapeAlignCenter")
        self.h.InsertPicture(path, True, 1, False, False, 0, int(iw * k), int(ih * k))

    def picture_grid(self, pics: list, cols: int, rows: int, w_mm: float, h_mm: float) -> str:
        """지금 칸 안에 작은 표를 만들어 그림을 한 칸에 하나씩 넣고, 그림마다 아래에 제목 칸을 둔다.
        한 줄짜리(cols=1)는 마지막 그림의 제목을 바깥 표의 제목 칸에 쓰도록 돌려준다(사용자 2026-11-23)."""
        inner_last_cap = cols > 1
        nrow = rows * 2 - (0 if inner_last_cap else 1)
        n_caps = rows if inner_last_cap else rows - 1
        outer = self.pos()[0]
        W, H = w_mm - 4.0, h_mm - 3.0
        grid = self._create_grid(cols, nrow, W, H, 8.0, n_caps, rows)
        self.goto_cell(outer)                    # 바깥 칸이 늘었으면 그만큼 줄여 다시 만든다(쪽이 넘치지 않게)
        grown = self.cell_size()[1] - h_mm
        if grown > 0.2:
            self.clear_cell()
            grid = self._create_grid(cols, nrow, W, H - grown - 0.5, 8.0, n_caps, rows)
        for i, lid in enumerate(grid):
            r, c = divmod(i, cols)
            is_cap = r % 2 == 1
            self.goto_cell(lid)
            self._cell_style(fill=is_cap, left=c > 0, right=c < cols - 1,
                             top=is_cap or r > 0, bottom=is_cap)
        for k, (path, cap) in enumerate(pics[:rows * cols]):
            r, c = divmod(k, cols)
            self.goto_cell(grid[(r * 2) * cols + c])
            if path:
                self._fit_picture(path)
            else:
                self._insert_text(pi.BLANK)
                self.run("ParagraphShapeAlignCenter")
            if r * 2 + 1 < nrow:
                self.goto_cell(grid[(r * 2 + 1) * cols + c])
                self._insert_text(cap or pi.BLANK)
                self.run("ParagraphShapeAlignCenter")
        self.run("Cancel")
        if inner_last_cap:                       # 바깥 제목 칸에는 모은 제목
            return _join_caps([(p, c) for p, c in pics if p])
        return pics[rows - 1][1] or pi.BLANK

    def duplicate_after(self, src, after):
        """src 표를 복사해 after 표 다음 쪽에 붙인다. 새 표 컨트롤."""
        h = self.h
        h.SetPosBySet(src.GetAnchorPos(0))
        h.FindCtrl()
        self.run("Copy")
        self.run("Cancel")
        a = after.GetAnchorPos(0)
        # 표 바로 뒤로(문단 끝으로 가면 여러 쪽을 건너뛸 수 있고, MoveRight는 표 칸 안으로 들어간다)
        h.SetPos(a.Item("List"), a.Item("Para"), a.Item("Pos") + 1)
        self.run("BreakPage")
        self.run("Paste")
        c = after.Next
        while c is not None and not (c.CtrlID == "tbl" and _top_level(c)):
            c = c.Next                           # after 안의 작은 표는 건너뛴다(붙인 쪽 = 다음 본문 표)
        return c

    def page(self) -> int:
        try:
            return int(self.h.KeyIndicator()[3])
        except Exception:
            return 0

    def delete_page(self, t) -> None:
        """증빙 쪽 표를 지우고 그 앞 쪽 나눔도 지운다(빈 쪽이 남지 않게)."""
        self.h.SetPosBySet(t.GetAnchorPos(0))
        if self.h.FindCtrl():
            self.run("Delete")
            self.run("DeleteBack")


def _top_level(c) -> bool:
    try:
        return c.GetAnchorPos(0).Item("List") == 0
    except Exception:
        return True


# ---------------- 점수 ----------------
def _fmt(v) -> str:
    return "" if v is None else f"{v:g}"


def _norm(s: str) -> str:
    return re.sub(r"[\s‧·ㆍ․.,()\[\]0-9]", "", s or "")


def _match(row_text: str, cands: list[qe.Item]) -> qe.Item | None:
    best, score = None, 0.0
    a = _norm(row_text.split("\n")[0])
    for it in cands:
        r = difflib.SequenceMatcher(None, a, _norm(it.text)[:len(a) + 10]).ratio()
        if r > score:
            best, score = it, r
    return best if score >= 0.45 else None


def _fill_check_table(hw: Hwp, t, cands: list[qe.Item], res: dict) -> list[qe.Item]:
    found: list[qe.Item] = []
    if not hw.enter_table(t):
        return found
    head = hw.pos()[0]
    hw.leave_table()
    lid, used = hw.lower_cell_of(head), set()
    for _ in range(8):
        if lid is None:
            break
        hw.goto_cell(lid)
        txt = hw.cell_text()
        if not txt or txt.startswith(("【", "※", "*")):
            break
        it = _match(txt, [c for c in cands if id(c) not in used])
        if it is None and len(cands) == 1 and not used:
            it = cands[0]
        if it is not None and it.score is not None:
            right = hw.right_cell_of(lid)
            if right is not None:
                hw.goto_cell(right)
                hw.set_cell(_fmt(it.score))
                hw.run("ParagraphShapeAlignCenter")
                res["scores"] += 1
            used.add(id(it))
            found.append(it)
        elif it is None:
            res["unmatched"].append(txt.split("\n")[0][:30])
        nxt = hw.lower_cell_of(lid)
        if nxt is None or nxt == lid:
            break
        lid = nxt
    hw.leave_table()
    return found


# ---------------- 증빙 채우기 ----------------
def _slots(cells: list[dict]) -> list[dict]:
    return [c for c in cells[1:] if c["h"] >= PHOTO_MIN_MM]


def _take_unit(queue: list, slot: dict, tmp: str) -> tuple[list, int, int] | None:
    """사진칸 하나에 넣을 그림들과 배치: ([(그림 또는 None, 설명)], 가로 수, 세로 수).
    여러 장이면 그림을 합치지 않고 칸을 나눠 한 칸에 하나씩 넣는다(사용자 2026-11-23)."""
    if not queue:
        return None
    w, h = slot["w"], slot["h"]
    path, cap = queue[0]
    if w < NARROW_MM or not pi.is_portrait(path):
        if h >= TALL_MM and w >= NARROW_MM:
            # 큰 칸: 가로 화면 2장 위아래. 1장뿐이면 위에 넣고 아래는 '-공란-'(사용자 2026-11-23)
            pages = [queue.pop(0)]
            if queue and not pi.is_portrait(queue[0][0]):
                pages.append(queue.pop(0))
            return pages + [(None, pi.BLANK)] * (2 - len(pages)), 1, 2
        queue.pop(0)
        return [(path, cap)], 1, 1
    run = 0
    while run < len(queue) and run < 3 and pi.is_portrait(queue[run][0]):
        run += 1
    if h >= TALL_MM and run <= 2:                                  # 공문 1~2장: 한 칸에 한 장씩 크게(사용자 2026-11-21)
        queue.pop(0)
        out = os.path.join(tmp, f"u{len(os.listdir(tmp)):04d}.png")
        shutil.copyfile(path, out)
        pi.trim_white(out, 6)
        return [(out, cap)], 1, 1
    n = 4 if h >= TALL_MM else 2
    pages = []
    while queue and len(pages) < n and pi.is_portrait(queue[0][0]):
        pages.append(queue.pop(0))
    pages += [(None, pi.BLANK)] * (n - len(pages))
    return pages, 2, n // 2


def _join_caps(pages) -> str:
    caps = [c for _p, c in pages]
    if len(caps) == 1:
        return caps[0]
    base = [re.sub(r"\s*-\s*\d+$", "", c) for c in caps]
    if len(set(base)) == 1:
        nums = [re.search(r"-\s*(\d+)$", c) for c in caps]
        if all(nums) and len(nums) > 1:
            return f"{base[0]} - {nums[0][1]}~{nums[-1][1]}"
        return base[0]
    return " / ".join(dict.fromkeys(caps))


def _fill_table(hw: Hwp, t, queue: list, tmp: str, res: dict, stop) -> tuple[bool, int]:
    """표 하나의 사진칸을 채운다. (사진칸이 있었는지, 넣은 그림 수)."""
    cells = hw.table_cells(t)
    n_slots = len(_slots(cells))
    placed = 0
    for k in range(n_slots):
        if stop is not None and stop.is_set():
            raise ReportError("멈췄습니다.")
        s = _slots(cells)[k]
        unit = _take_unit(queue, s, tmp)
        below = hw.lower_cell_of(s["list"])
        cb = next((c for c in cells if c["list"] == below), None) if below is not None else None
        if unit is None:
            if res.get("_dup") or not s["text"]:   # 양식 예시 사진(글자 없는 사진칸)·복사한 쪽의 남은 칸은 비운다
                hw.goto_cell(s["list"])
                hw.clear_cell()
                if cb is not None and cb["h"] < PHOTO_MIN_MM and res.get("_dup"):
                    hw.goto_cell(below)
                    hw.set_cell(pi.BLANK)
                    hw.run("ParagraphShapeAlignCenter")
            continue
        pics, cols, rows = unit
        hw.goto_cell(s["list"])
        hw.clear_cell()
        if len(pics) == 1:
            hw.insert_picture(pics[0][0])
            cap = pics[0][1]
        else:
            cap = hw.picture_grid(pics, cols, rows, s["w"], s["h"])
            cells = hw.table_cells(t)                # 칸 안에 표를 만들면 뒤 칸들의 번호가 바뀐다
            below = hw.lower_cell_of(s["list"])
            cb = next((c for c in cells if c["list"] == below), None) if below is not None else None
        res["photos"] += sum(1 for p, _c in pics if p)
        placed += 1
        if cb is not None and cb["h"] < PHOTO_MIN_MM:
            hw.goto_cell(below)
            hw.set_cell(cap)
            hw.run("ParagraphShapeAlignCenter")
    hw.leave_table()
    return bool(n_slots), placed


def _best_proto(tabs: list, hw: Hwp):
    """복사해 늘릴 증빙 쪽: 큰 사진칸(2×2를 넣을 수 있는 칸)이 있는 표를 먼저."""
    best, score = None, -1
    for t in tabs:
        slots = _slots(hw.table_cells(t))
        if not slots:
            continue
        sc = max(s["h"] for s in slots) * 10 + len(slots)
        if sc > score:
            best, score = t, sc
    return best


def build(vol: int, items: list[qe.Item], xlsx_path: str, out_dir: str, year: int, center: str,
          chief: str = "", log=print, stop=None, template: str = "", passwords=()) -> tuple[str, dict]:
    """vol권 보고서를 만들어 저장한 경로와 결과 요약을 돌려준다."""
    say = log or (lambda _m: None)
    vitems = [i for i in items if qe.volume_of(i.part) == vol]
    by_no: dict[str, list[qe.Item]] = {}
    for it in vitems:
        by_no.setdefault(it.no, []).append(it)
    root = qe.evidence_root(xlsx_path) if xlsx_path else ""
    src = template or template_path(vol, [os.path.dirname(xlsx_path)] if xlsx_path else [])
    name = f"{year}년도 주거행복지원센터 서비스 품질평가 보고서({vol}권)" + (f"_{center}" if center else "")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, name + ".hwp")
    n = 2
    while os.path.exists(out):
        out = os.path.join(out_dir, f"{name} ({n}).hwp")
        n += 1
    tmp = tempfile.mkdtemp(prefix="qhwp_")
    res = {"scores": 0, "photos": 0, "pages_added": 0, "no_page": [], "unmatched": [], "locked": [], "files": 0}
    hw = None
    with pi.AutoAllow(say):
        try:
            hw = Hwp(visible=False)
            # 1) 증빙 파일 → 쪽 그림 (양식을 열기 전에: 한글 파일 변환이 같은 한글을 쓴다)
            pages: dict[str, list] = {}
            if root and os.path.isdir(qe.volume_dir(root, vol)):
                say("폴더링의 증빙 파일을 쪽 그림으로 바꿉니다…")
                ptmp = os.path.join(tmp, "pages")
                os.makedirs(ptmp)
                for no, its in by_no.items():
                    if stop is not None and stop.is_set():
                        raise ReportError("멈췄습니다.")
                    pages[no] = {it.seq: number_pages(root, [it], ptmp, passwords, hw, say, res)
                                 for it in sorted(its, key=lambda i: i.seq)}
                    cnt = sum(len(v) for v in pages[no].values())
                    if cnt:
                        say(f"  {no}: {cnt}쪽")
            else:
                say("폴더링이 없어 증빙은 넣지 않습니다.")
            res["files"] = sum(len(x) for v in pages.values() for x in v.values())
            shutil.copy2(src, out)
            say(f"한글에서 {vol}권 양식을 엽니다…")
            hw.open(out)
            # 2) 표지·서약서 글자
            hw.replace_all(f"{SAMPLE_YEAR}년도", f"{year}년도")
            hw.replace_all(f"{int(SAMPLE_YEAR) + 1}. 2.", f"{year + 1}. 2.")
            hw.replace_all(f"{SAMPLE_YEAR}년    월", f"{year}년    월")
            if center:
                hw.replace_all(SAMPLE_CENTER, center)
            if chief:
                hw.replace_all(SAMPLE_CHIEF, " ".join(chief.replace(" ", "")))
            # 3) 표 훑기: 점수 넣기, 증빙 쪽 모으기
            say("점수를 넣습니다…")
            tables, top = [], set()
            c = hw.h.HeadCtrl
            while c is not None:
                if c.CtrlID == "tbl":
                    tables.append(c)
                    try:
                        if c.GetAnchorPos(0).Item("List") == 0:      # 본문에 바로 놓인 표(다른 표 안이 아님)
                            top.add(len(tables) - 1)
                    except Exception:
                        top.add(len(tables) - 1)
                c = c.Next
            evid: dict[tuple, list] = {}          # (번호, 항목 순번 또는 None) → 증빙 쪽 표들
            last: dict[str, object] = {}
            anchor: dict[tuple, object] = {}      # (번호, 순번) → 그 항목 구역의 마지막 본문 표(증빙 쪽을 붙일 자리)
            titles: dict[str, str] = {}
            cur_no, cur_seq, last_top = "", None, None
            done_seq: dict[str, list] = {}

            def mark(no, ti, t):
                if ti in top:
                    last[no] = t
                    if cur_seq is not None and no == cur_no:
                        anchor[(no, cur_seq)] = t

            for ti, t in enumerate(tables):
                if stop is not None and stop.is_set():
                    raise ReportError("멈췄습니다.")
                if ti in top:
                    last_top = t
                if not hw.enter_table(t):
                    continue
                first = hw.cell_text()
                hw.leave_table()
                line = first.split("\n")[0].strip()
                m = _HEAD.match(first.replace("\n", " | "))
                if m and "득점" in first:
                    cur_no, cur_seq = m.group(1), None           # 다음 점검내용 표에서 어느 항목인지 정해진다
                    titles.setdefault(cur_no, m.group(2).strip())
                    mark(cur_no, ti, t)
                    total = [i.score for i in by_no.get(cur_no, []) if i.score is not None]
                    if total:
                        hw.enter_table(t)
                        hw.append_cell(_fmt(sum(total)))
                        hw.leave_table()
                    continue
                is_check = line.startswith("점검내용")
                if not is_check and cur_no and line.startswith(f"{cur_no}.") and "\n" not in first.strip():
                    cs = hw.table_cells(t)                       # 1-5처럼 머리칸이 '1-5. 기타 업무 | 점검결과'인 점검표
                    is_check = len(cs) > 1 and "점검결과" in cs[1]["text"]
                if is_check and cur_no:
                    got = _fill_check_table(hw, t, by_no.get(cur_no, []), res)
                    seqs = sorted(i.seq for i in by_no.get(cur_no, []))
                    used = done_seq.setdefault(cur_no, [])
                    if got:
                        cur_seq = min(i.seq for i in got)
                    else:                                        # 못 맞추면 아직 안 나온 다음 항목
                        cur_seq = next((q for q in seqs if q not in used), None)
                    if cur_seq is not None:
                        used.append(cur_seq)
                        if last_top is not None:
                            anchor[(cur_no, cur_seq)] = last_top
                    mark(cur_no, ti, t)
                    continue
                em = _EVID.match(line)
                if em and "\n" not in first.strip():
                    eno = em.group(1)
                    evid.setdefault((eno, cur_seq if eno == cur_no else None), []).append(t)
                    mark(eno, ti, t)
                    titles[em.group(1)] = em.group(2).strip()
                elif cur_no:
                    mark(cur_no, ti, t)
            # 4) 증빙 쪽 — 항목마다 그 점검내용 쪽 뒤의 증빙 쪽에 그 항목 폴더의 파일을 넣는다(사용자 2026-11-21)
            all_evid = [t for ts in evid.values() for t in ts]
            proto_any = _best_proto(all_evid, hw) if all_evid else None
            unused = []
            for no, its in by_no.items():
                seqs = sorted(i.seq for i in its)
                per = pages.get(no, {})
                for seq in seqs:
                    queue = list(per.get(seq, []))
                    tabs = list(evid.get((no, seq), []))
                    if seq == seqs[0]:
                        tabs = list(evid.get((no, None), [])) + tabs
                    if queue:
                        say(f"{no} {seq}번 증빙 {len(queue)}쪽을 넣습니다…")
                    for t in tabs:
                        _has, placed = _fill_table(hw, t, queue, tmp, res, stop)
                        if _has and not placed:
                            unused.append(t)                 # 넣을 파일이 없는 양식 증빙 쪽 — 나중에 지운다
                    if not queue:
                        continue
                    proto = _best_proto([t for t in tabs if t not in unused], hw) or proto_any
                    after = next((t for t in reversed(tabs) if t not in unused), None) \
                        or anchor.get((no, seq)) or last.get(no)
                    if proto is None or after is None:
                        res["no_page"].append(f"{no} {seq}번 ({len(queue)}쪽)")
                        continue
                    res["_dup"] = True
                    while queue:
                        new = hw.duplicate_after(proto, after)
                        if new is None:
                            res["no_page"].append(f"{no} {seq}번 ({len(queue)}쪽)")
                            break
                        res["pages_added"] += 1
                        cells = hw.table_cells(new)
                        if cells and not cells[0]["text"].startswith(f"{no}."):
                            hw.goto_cell(cells[0]["list"])
                            hw.set_cell(f" {no}. {titles.get(no, '')}")
                            hw.leave_table()
                        has, _placed = _fill_table(hw, new, queue, tmp, res, stop)
                        if not has:
                            break
                        after = new
                    res["_dup"] = False
            for t in reversed(unused):                       # 빈 증빙 쪽 지우기(뒤에서부터)
                try:
                    hw.delete_page(t)
                    res["pages_removed"] = res.get("pages_removed", 0) + 1
                except Exception:
                    pass
            hw.save_as(out)
        finally:
            if hw is not None:
                hw.quit()
            shutil.rmtree(tmp, ignore_errors=True)
    res.pop("_dup", None)
    return out, res


OUT_SUB = "품평 한글파일 작성 후"      # 만든 한글 보고서를 두는 곳(프로그램 폴더 안)
FORM_SUB = "품평 한글파일 작성전"     # 양식을 두는 곳(프로그램 폴더 안)


def default_out_dir(xlsx_path: str) -> str:
    """만든 보고서를 둘 폴더: 초안이 있으면 그 옆 '품질평가 작성'(폴더링과 같은 곳).
    초안 없이 만들 때는 exe면 프로그램 폴더의 '품평 한글파일 작성 후', 아니면 바탕화면."""
    if xlsx_path:
        d = qe.work_dir(xlsx_path)
    elif paths.frozen():
        d = os.path.join(paths.program_dir(), OUT_SUB)
    else:
        return os.path.join(os.path.expanduser("~"), "Desktop")
    os.makedirs(d, exist_ok=True)
    return d


if __name__ == "__main__":       # 시험: python hwp_report.py 4 평가표.xlsx 출력폴더
    v, x, o = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    its = qe.load(x)
    print(build(v, its, x, o, qe.sheet_year(x) or 2026, "광주양림2", "홍길동"))
