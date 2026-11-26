"""증빙 파일 → 쪽 그림(PNG) 만들기, 여러 쪽을 한 칸에 넣을 모음 그림 만들기, 한글·엑셀 경고창 자동 허용.

- PDF: 쪽마다 그림(암호가 걸려 있으면 넣어 둔 비밀번호 1~3을 차례로 넣어 본다)
- 한글(hwp·hwpx): 한글로 PDF를 만든 뒤 쪽마다 그림
- 엑셀(xls·xlsx·xlsm·csv): 엑셀로 PDF를 만든 뒤 쪽마다 그림(비밀번호 1~3)
- 워드(doc·docx): 워드가 있으면 PDF로
- 그림(jpg·png 등): 그대로
엑셀·한글·워드에서 만든 PDF는 그림으로 바꾸기 전에 이름·동호수·연락처를 000으로 가린다(privacy.mask_pdf).
모음 그림: A4 세로 쪽 2장(나란히) 또는 4장(2×2)을 한 그림으로 붙이고, 쪽마다 아래에 회색 설명 띠를 그린다.
"""
from __future__ import annotations

import os
import re
import threading
import time

from PIL import Image, ImageDraw, ImageFont

IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff")
HWP_EXT = (".hwp", ".hwpx")
XL_EXT = (".xls", ".xlsx", ".xlsm", ".csv")
DOC_EXT = (".doc", ".docx")
MAX_PAGES = 30            # 한 파일에서 넣을 최대 쪽 수
MAX_XL_PAGES = 6          # 엑셀은 앞 6쪽까지(전국 목록 같은 큰 표가 수십 쪽이 되지 않게)
DPI = 110
FONT = r"C:\Windows\Fonts\malgun.ttf"
BLANK = "-공란-"
NO_PW = "__no_password__"   # 비밀번호 없이 열어 볼 때 넣는 값(암호가 걸린 파일이면 묻는 창 없이 바로 실패)


def natural_key(p: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p)]


def clean_title(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r"^\d+\s*[.)]\s*", "", stem)            # '01. ' 같은 앞 번호
    stem = re.sub(r"\((암호|스캔본)·가리지 못함\)", "", stem)
    return stem.strip() or os.path.basename(path)


# ---------------- PDF ----------------
def pdf_pages(pdf: str, out_dir: str, passwords=(), limit: int = MAX_PAGES) -> tuple[list[str], str]:
    """PDF 쪽 그림 목록과 상태('', 'locked')."""
    import pymupdf
    out = []
    with pymupdf.open(pdf) as doc:
        if doc.needs_pass:
            if not any(p and doc.authenticate(p) for p in passwords):
                return [], "locked"
        for i, page in enumerate(doc):
            if i >= limit:
                break
            p = os.path.join(out_dir, f"{len(os.listdir(out_dir)):04d}.png")
            page.get_pixmap(dpi=DPI).save(p)
            out.append(p)
    return out, ""


# ---------------- 오피스 → PDF ----------------
def hwp_to_pdf(hwp, src: str, dst: str, passwords=()) -> bool:
    """한글 자동화(hwp_report.Hwp)로 한글 파일을 PDF로. 양식을 열기 전에 부른다(열린 문서를 닫는다)."""
    h = hwp.h
    for pw in ("", *[p for p in passwords if p]):
        try:
            arg = "forceopen:true;suspendpassword:true" + (f";password:{pw}" if pw else "")
            ok = h.Open(src, "", arg)
            if ok:
                h.SaveAs(dst, "PDF", "")
            h.Clear(1)
            if ok and os.path.isfile(dst):
                return True
        except Exception:
            try:
                h.Clear(1)
            except Exception:
                pass
    return False


def excel_to_pdf(src: str, dst: str, passwords=()) -> str:
    """엑셀로 PDF. 돌려주는 값: ''(성공) · 'locked'(비밀번호가 맞지 않음) · 'fail'."""
    try:
        import pythoncom
        import win32com.client as w
    except ImportError:
        return "fail"
    pythoncom.CoInitialize()
    try:
        xl = w.DispatchEx("Excel.Application")
    except Exception:
        return "fail"
    xl.Visible = False
    xl.DisplayAlerts = False
    try:
        locked = False
        for pw in ("", *[p for p in passwords if p]):
            try:
                kw = {"UpdateLinks": 0, "ReadOnly": True, "IgnoreReadOnlyRecommended": True}
                if pw:
                    kw["Password"] = pw
                else:
                    kw["Password"] = NO_PW           # 암호가 있으면 바로 실패하게(묻는 창 없이)
                wb = xl.Workbooks.Open(src, **kw)
            except Exception:
                locked = True
                continue
            try:
                _fit_sheets(wb)
                wb.ExportAsFixedFormat(0, dst)
            finally:
                wb.Close(False)
            return "" if os.path.isfile(dst) else "fail"
        return "locked" if locked else "fail"
    finally:
        try:
            xl.Quit()
        except Exception:
            pass


def _fit_sheets(wb) -> None:
    """엑셀 시트를 가로 한 쪽 너비에 맞춘다(넓은 표는 가로 방향, 쪽당 32~48줄쯤)."""
    for ws in wb.Worksheets:
        try:
            if ws.Visible != -1:
                continue
            ps = ws.PageSetup
            ur = ws.UsedRange
            wide = ur.Columns.Count > 8
            ps.Zoom = False
            ps.FitToPagesWide = 1
            ps.FitToPagesTall = max(1, -(-ur.Rows.Count // (32 if wide else 48)))
            if wide:
                ps.Orientation = 2
        except Exception:
            pass


# ---------------- 엑셀: 우리 단지 줄만 ----------------
def _runs(nums: list[int]) -> list[tuple[int, int]]:
    """[3,4,5,9] → [(3,5),(9,9)]"""
    out = []
    for n in sorted(nums):
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def center_layout(path: str, center: str) -> dict | None:
    """전국 목록 엑셀에서 우리 단지 줄만 보이게 할 자리: {sheet, hide_rows, hide_cols, last_row, last_col}.
    '단지명' 머리글이 있고 그 칸에 center가 든 줄이 있는 시트만. 없으면 None.
    보이는 것: 제목·머리글 줄 + 우리 단지 줄, 칸은 '단지명'부터 '검증'(없으면 머리글 끝)까지
    (2025 보고서 4권 '예비입주자 모집 계획 엑셀파일 캡처'와 같은 모양)."""
    from openpyxl import load_workbook
    key = re.sub(r"\s+", "", center or "")
    if not key:
        return None
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            head = name_col = None
            for r, row in enumerate(rows[:60], 1):
                for c, v in enumerate(row, 1):
                    if isinstance(v, str) and re.sub(r"\s+", "", v) == "단지명":
                        head, name_col = r, c
                        break
                if head:
                    break
            if not head:
                continue
            nm = lambda row: re.sub(r"\s+", "", str(row[name_col - 1])) if len(row) >= name_col and row[name_col - 1] else ""
            mine = [r for r, row in enumerate(rows, 1) if r > head and key in nm(row)]
            if not mine:
                continue
            data_start = next((r for r, row in enumerate(rows, 1) if r > head and nm(row)), head + 1)
            keep = set(mine)
            for r in range(1, data_start):
                txt = " ".join(str(v) for v in rows[r - 1] if v not in (None, ""))
                if r >= head or 0 < len(txt) <= 120:      # 머리글은 다, 그 위는 빈 줄·긴 '작성요령' 줄을 뺀다
                    keep.add(r)
            last_row = max(mine)
            hide_rows = [r for r in range(1, last_row + 1) if r not in keep]
            width = max(len(row) for row in rows[:data_start]) if data_start > 1 else len(rows[head - 1])
            end_col = width
            for r in range(head, data_start):
                for c, v in enumerate(rows[r - 1], 1):
                    if isinstance(v, str) and re.sub(r"\s+", "", v) == "검증":
                        end_col = c
            titles = [r for r in range(1, head) if r in keep and any(v not in (None, "") for v in rows[r - 1])]
            return {"sheet": ws.title, "hide_rows": hide_rows, "hide_cols": list(range(1, name_col)),
                    "last_row": last_row, "last_col": end_col, "rows": len(mine), "name_col": name_col,
                    "titles": titles}
    finally:
        wb.close()
    return None


def excel_center_pdf(src: str, dst: str, center: str, passwords=()) -> str:
    """전국 목록 엑셀에서 우리 단지 줄만 한 쪽 PDF로. ''(성공) · 'none'(우리 단지 줄 없음) · 'locked' · 'fail'."""
    try:
        lay = center_layout(src, center)
    except Exception:
        lay = None
    if not lay:
        return "none"
    try:
        import pythoncom
        import win32com.client as w
        from openpyxl.utils import get_column_letter as L
    except ImportError:
        return "fail"
    pythoncom.CoInitialize()
    try:
        xl = w.DispatchEx("Excel.Application")
    except Exception:
        return "fail"
    xl.Visible = False
    xl.DisplayAlerts = False
    try:
        try:
            wb = xl.Workbooks.Open(src, UpdateLinks=0, ReadOnly=True, IgnoreReadOnlyRecommended=True,
                                   Password=passwords[0] if passwords else NO_PW)
        except Exception:
            return "locked"
        try:
            ws = wb.Worksheets(lay["sheet"])
            for a, b in _runs(lay["hide_rows"]):
                ws.Range(f"A{a}:A{b}").EntireRow.Hidden = True
            for a, b in _runs(lay["hide_cols"]):
                ws.Range(f"{L(a)}1:{L(b)}1").EntireColumn.Hidden = True
            nc = lay["name_col"]
            for r in lay["titles"]:                  # 제목(넓게 병합된 칸)은 보이는 첫 칸에 왼쪽 맞춤으로 옮겨 잘리지 않게
                for c in range(1, lay["last_col"] + 1):
                    cell = ws.Cells(r, c)
                    if not cell.MergeCells:
                        continue
                    area = cell.MergeArea
                    first = area.Cells(1, 1)
                    text = first.Value
                    if not text:
                        continue
                    size, bold, font = first.Font.Size, first.Font.Bold, first.Font.Name
                    area.UnMerge()
                    first.Value = ""
                    dst_cell = ws.Cells(r, nc)
                    dst_cell.Value = text
                    dst_cell.Font.Size, dst_cell.Font.Bold, dst_cell.Font.Name = size, bold, font
                    dst_cell.HorizontalAlignment = -4131          # 왼쪽
                    dst_cell.WrapText = False
                    break
            ps = ws.PageSetup
            ps.PrintArea = f"$A$1:${L(lay['last_col'])}${lay['last_row']}"
            ps.Orientation = 2
            ps.Zoom = False
            ps.FitToPagesWide = 1
            ps.FitToPagesTall = 1
            ws.ExportAsFixedFormat(0, dst)
        finally:
            wb.Close(False)
        return "" if os.path.isfile(dst) else "fail"
    finally:
        try:
            xl.Quit()
        except Exception:
            pass


def stack_pages(paths: list[str], out: str, gap: int = 10) -> str:
    """여러 쪽 그림의 글자 부분만 잘라 위아래로 이어 붙여 한 장으로(공문 본문이 2쪽으로 넘친 경우)."""
    from PIL import ImageChops
    parts = []
    for p in paths:
        im = Image.open(p).convert("RGB")
        box = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255))).getbbox()
        if box:
            parts.append(im.crop((0, max(0, box[1] - gap), im.width, min(im.height, box[3] + gap))))
    if not parts:
        Image.open(paths[0]).save(out)
        return out
    first = Image.open(paths[0])
    w = max(p.width for p in parts)
    top = parts[0]
    h = sum(p.height for p in parts)
    canvas = Image.new("RGB", (w, max(h, first.height if len(parts) == 1 else h)), "white")
    y = 0
    for p in parts:
        canvas.paste(p, (0, y))
        y += p.height
    canvas.save(out)
    return out


def trim_white(path: str, pad: int = 12) -> None:
    """그림 둘레의 흰 여백을 잘라 낸다."""
    from PIL import ImageChops
    im = Image.open(path).convert("RGB")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    box = ImageChops.difference(im, bg).getbbox()
    if box:
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(im.width, box[2] + pad), min(im.height, box[3] + pad))
        im.crop(box).save(path)


def word_to_pdf(src: str, dst: str, passwords=()) -> str:
    try:
        import pythoncom
        import win32com.client as w
    except ImportError:
        return "fail"
    pythoncom.CoInitialize()
    try:
        wd = w.DispatchEx("Word.Application")
    except Exception:
        return "fail"
    wd.Visible = False
    wd.DisplayAlerts = 0
    try:
        for pw in ("", *[p for p in passwords if p]):
            try:
                doc = wd.Documents.Open(src, ReadOnly=True, PasswordDocument=pw or NO_PW, AddToRecentFiles=False)
            except Exception:
                continue
            try:
                doc.ExportAsFixedFormat(dst, 17)
            finally:
                doc.Close(False)
            return "" if os.path.isfile(dst) else "fail"
        return "locked"
    finally:
        try:
            wd.Quit()
        except Exception:
            pass


def file_pages(path: str, tmp: str, passwords=(), hwp=None, log=None) -> tuple[list[str], str]:
    """증빙 파일 하나 → 쪽 그림 목록. 상태: ''·'locked'·'skip'."""
    ext = os.path.splitext(path)[1].lower()
    if ext in IMG_EXT:
        return [path], ""
    pdf = path if ext == ".pdf" else os.path.join(tmp, f"_conv{len(os.listdir(tmp))}.pdf")
    if ext in HWP_EXT + XL_EXT + DOC_EXT:       # 엑셀은 경로가 218자를 넘으면 못 연다 → 짧은 곳에 복사해 연다
        import shutil
        short = os.path.join(tmp, f"_src{len(os.listdir(tmp))}{ext}")
        shutil.copy2(path, short)
        path = short
    if ext in HWP_EXT:
        if hwp is None or not hwp_to_pdf(hwp, path, pdf, passwords):
            return [], "locked"
    elif ext in XL_EXT:
        st = excel_to_pdf(path, pdf, passwords)
        if st:
            return [], st
    elif ext in DOC_EXT:
        st = word_to_pdf(path, pdf, passwords)
        if st:
            return [], st
    elif ext != ".pdf":
        return [], "skip"
    if pdf != path:                       # 엑셀·한글·워드에서 만든 PDF도 이름·동호수·연락처를 000으로 가린다
        try:
            import privacy
            masked = pdf[:-4] + "_가림.pdf"
            privacy.mask_pdf(pdf, masked)
            pdf = masked
        except Exception as ex:
            if log:
                log(f"    개인정보를 가리지 못함: {os.path.basename(path)} ({type(ex).__name__})")
    try:
        return pdf_pages(pdf, tmp, passwords, MAX_XL_PAGES if ext in XL_EXT else MAX_PAGES)
    except Exception as ex:
        if log:
            log(f"    그림으로 바꾸지 못함: {os.path.basename(path)} ({type(ex).__name__})")
        return [], "fail"


# ---------------- 모음 그림 ----------------
def is_portrait(path: str) -> bool:
    try:
        with Image.open(path) as im:
            w, h = im.size
        return h >= w * 1.1
    except Exception:
        return False


def _font(px: int):
    try:
        return ImageFont.truetype(FONT, px)
    except OSError:
        return ImageFont.load_default()


def compose(pages: list[tuple[str | None, str]], cols: int, rows: int, out: str, box_ratio: float) -> str:
    """pages [(그림 또는 None, 설명)]을 cols×rows로 붙인다. box_ratio = 넣을 칸의 가로/세로."""
    W = 2400
    H = int(W / box_ratio)
    gap = 24
    bar = 54
    cw, ch = (W - gap * (cols - 1)) // cols, (H - gap * (rows - 1)) // rows
    canvas = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(canvas)
    f = _font(30)
    for i, (p, cap) in enumerate(pages[:cols * rows]):
        x, y = (i % cols) * (cw + gap), (i // cols) * (ch + gap)
        if p:
            with Image.open(p) as im:
                im = im.convert("RGB")
                im.thumbnail((cw - 8, ch - bar - 8), Image.LANCZOS)
                canvas.paste(im, (x + (cw - im.width) // 2, y + (ch - bar - im.height) // 2))
                d.rectangle((x + (cw - im.width) // 2 - 1, y + (ch - bar - im.height) // 2 - 1,
                             x + (cw + im.width) // 2, y + (ch - bar + im.height) // 2), outline="#c8c8c8")
        else:
            t = BLANK
            tw = d.textlength(t, font=_font(40))
            d.text((x + (cw - tw) / 2, y + (ch - bar) / 2 - 20), t, font=_font(40), fill="#555555")
        d.rectangle((x, y + ch - bar, x + cw, y + ch), fill="#dcdcdc")
        cap = cap or BLANK
        while d.textlength(cap, font=f) > cw - 20 and len(cap) > 4:
            cap = cap[:-2]
        tw = d.textlength(cap, font=f)
        d.text((x + (cw - tw) / 2, y + ch - bar + 10), cap, font=f, fill="#222222")
    canvas.save(out)
    return out


# ---------------- 경고창 자동 허용 ----------------
ALLOW_WORDS = ("모두 허용", "모두허용", "접근 허용", "허용(&A)", "허용")
WATCH_PROCS = ("hwp", "excel", "winword")


def _wpf_allow(top: int, seen: dict) -> bool:
    """새 한글(WPF)의 '…파일에 접근하려는 시도…' 창(제목 '한글', 버튼 접근 허용·모두 허용·허용 안 함·모두 안 함)에서
    [모두 허용]을 누른다. 버튼이 창 핸들이 아니라 위치로 누른다(창 너비·높이 비율: 0.445, 0.806)."""
    import ctypes

    import win32gui
    title = win32gui.GetWindowText(top)
    if not title.endswith("글") or len(title) > 3:
        return False
    l, t, r, b = win32gui.GetWindowRect(top)
    w, h = r - l, b - t
    if not (420 <= w <= 900 and 150 <= h <= 300):
        return False
    last = seen.get(("wpf", top), 0)
    if time.time() - last < 3:                   # 방금 눌렀으면 잠깐 기다림
        return False
    seen[("wpf", top)] = time.time()
    u = ctypes.windll.user32
    try:
        u.keybd_event(0x12, 0, 0, 0)
        u.keybd_event(0x12, 0, 2, 0)
        win32gui.SetForegroundWindow(top)
    except Exception:
        pass
    time.sleep(0.2)
    u.SetCursorPos(int(l + w * 0.445), int(t + h * 0.806))
    time.sleep(0.05)
    u.mouse_event(0x2, 0, 0, 0, 0)
    u.mouse_event(0x4, 0, 0, 0, 0)
    return True


class AutoAllow:
    """한글·엑셀·워드가 띄우는 '접근 허용' 같은 경고창의 [모두 허용](없으면 [허용])을 대신 누른다."""

    def __init__(self, log=None):
        self.log = log
        self.stop = threading.Event()
        self.clicked = 0
        self.t = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.t.join(timeout=2)

    def _run(self):
        try:
            import psutil
            import win32con
            import win32gui
            import win32process
        except ImportError:
            return
        first_seen: dict = {}
        while not self.stop.wait(0.5):
            try:
                tops = []
                win32gui.EnumWindows(lambda h, acc: acc.append(h), tops)
                for top in tops:
                    if not win32gui.IsWindowVisible(top):
                        continue
                    cls = win32gui.GetClassName(top)
                    if cls.startswith("bosa_sdm") and "암호" in win32gui.GetWindowText(top):
                        # 엑셀·워드 '암호' 묻는 창이 남아 있으면 닫는다(넣어 둔 비밀번호로 못 연 파일은 건너뜀)
                        t0 = first_seen.setdefault(top, time.time())
                        if time.time() - t0 > 4:
                            win32gui.PostMessage(top, win32con.WM_CLOSE, 0, 0)
                            first_seen.pop(top, None)
                            if self.log:
                                self.log("   (비밀번호를 묻는 창을 닫았습니다 — 그 파일은 건너뜁니다)")
                        continue
                    if cls.lower().startswith("hwndwrapper[hwp.exe") and _wpf_allow(top, first_seen):
                        self.clicked += 1
                        if self.log:
                            self.log("   (한글 '접근 허용' 창 → [모두 허용] 눌렀습니다)")
                        continue
                    if cls != "#32770":
                        continue
                    _, pid = win32process.GetWindowThreadProcessId(top)
                    try:
                        name = psutil.Process(pid).name().lower()
                    except Exception:
                        continue
                    if not name.startswith(WATCH_PROCS):
                        continue
                    btns = []
                    win32gui.EnumChildWindows(top, lambda h, acc: acc.append(h), btns)
                    labels = {b: win32gui.GetWindowText(b).replace("&", "") for b in btns
                              if win32gui.GetClassName(b) == "Button"}
                    for word in ALLOW_WORDS:
                        hit = next((b for b, t in labels.items() if word.replace("&", "") in t), None)
                        if hit:
                            win32gui.PostMessage(hit, win32con.BM_CLICK, 0, 0)
                            self.clicked += 1
                            if self.log:
                                self.log(f"   (경고창 '{win32gui.GetWindowText(top)}' → [{labels[hit]}] 눌렀습니다)")
                            time.sleep(0.3)
                            break
            except Exception:
                pass
