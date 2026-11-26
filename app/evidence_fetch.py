"""폴더링에 증빙 파일 넣기: 초안 평가표의 '평가 근거'에 적힌 문서번호로 홈넷 기록물등록대장 문서를 찾아
본문 PDF와 첨부파일을 항목 폴더(폴더링\\번호\\k. 항목)에 받는다.

- 근거 글의 '264(26.2.9.)' · '계약안내-1936(25.09.15)' 같은 참조를 quality_draft.parse_refs로 읽고,
  그 해 대장 목록(quality_draft.load_ledgers, 저장해 둔 목록 재사용)에서 등록번호로 문서 제목을 찾는다.
- 대장에서 제목으로 검색해 그 번호의 줄을 열고(collector.open_first_doc), 본문을 읽어 PDF로 찍는다.
  이름·동호수·연락처는 000으로 가린다(KODAS 대장 문서 받기와 같다). 보안 문서는 홈넷 비밀번호로 연다.
- 첨부는 받아서 같은 폴더에 '{번호}. {제목} (첨부) 파일이름'으로 둔다(PDF 첨부는 000으로 가림).
- 이미 받은 문서(같은 이름으로 시작하는 파일이 있음)는 다시 받지 않는다 → 멈췄다가 다시 눌러도 이어진다.
- 받은 본문·첨부는 쪽마다 그림(PNG)으로 바꿔 두고 원본은 지운다(보고서 4권처럼 그림을 넣기 위한 폴더링).
  열리지 않는 파일(암호 등)·대장에서 못 찾은 문서는 건너뛰고, 그 이유를 항목 폴더의 REASON_NAME 파일에 적는다.
- WISE가 켜져 있으면 4권 작성방법대로 WISE 화면(해약처리현황·계약자입주일관리)을 메뉴 검색으로 열어 조회하고,
  계약자·주민번호를 지워 캡처해 넣는다(wise_capture).
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import time

import quality_draft as qd
import quality_eval as qe

_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]+')
REASON_NAME = "저장 안 된 파일(이유).txt"
OURS = re.compile(r"^\d{2}\.\s")          # 우리가 받은 파일 이름('01. 제목…')

# 4권(임대운영) 작성방법의 WISE 화면 캡처: (번호, 항목 순번) → [(파일 이름, wise_capture.SCREENS 키)]
# '00.'은 공문보다 먼저, '90.'은 공문 다음에 놓인다(보고서에 넣는 차례 = 파일 이름 차례).
WISE_SHOTS = {
    ("1-1", 1): [("90. 해약처리현황 화면 캡처(최근 3년 명도일 기준)", "해약처리현황"),
                 ("91. 계약자입주일관리 화면 캡처(최근 3년 최초계약일 기준)", "계약자입주일관리")],
    ("1-2", 2): [("00. 해약처리현황 화면 캡처(평가년도 명도일 기준)", "해약처리현황(평가년도)")],
    ("1-3", 3): [("02. WISE 분양권퇴거유예세대관리 화면 캡처(동호·퇴거여부 확대)", "분양권퇴거유예세대관리")],
    ("1-3", 4): [(f"0{q}. WISE 자격검색요청관리 주택소유정기검색 화면 캡처({m})", f"자격검색:{q}")
                 for q, m in ((1, "1~3월"), (2, "4~6월"), (3, "7~9월"), (4, "10~12월"))],
    ("1-4", 1): [("01. WISE 임대조건기초자료관리 단지별임대조건인상률 탭 캡처", "임대조건:인상률"),
                 ("02. WISE 임대조건기초자료관리 단지별법정영세민기본단가 탭 캡처", "임대조건:기본단가")],
}
# 대장 문서를 받지 않고 WISE 캡처만 넣는 항목(작성방법의 준비서류가 WISE 화면뿐) — 평가 근거의 문서번호는 무시
WISE_ONLY = {("1-3", 4), ("1-4", 1)}
# 대장 목록에서 내부결재만 남기지 않는 항목(구청 등으로 보낸 신고 공문) — 수신자 칸은 000으로 가림
LIST_ALL = {("1-4", 2)}
# 4권 작성방법에 있지만 자동으로 넣지 못하는 캡처(직접 넣을 것) — 이유 파일에 적어 둔다
MANUAL_SHOTS = {
    ("1-2", 1): ["홈넷 갱신계약 체결 안내 화면 캡처"],
    ("1-2", 2): ["계약안내 홈넷 화면 캡처"],
}

# 첨부서류 없이 증빙양식만 쓰는 항목(4권 작성방법): (번호, 순번) → (메모, [(넣을 그림 이름, assets/증빙 파일)])
# 메모는 빈 폴더 이름으로 넣는다(scan_evidence가 빈 폴더 이름을 메모로 읽음).
NOTE_ITEMS = {
    ("1-3", 1): ("첨부서류 없음", []),
    ("1-3", 2): ("첨부자료 없음", [("01. 증빙양식", "4권 1-3-2 증빙양식.png")]),
    ("1-3", 3): ("증빙양식 작성", [("01. 증빙양식", "4권 1-3-3 증빙양식.png")]),
    ("1-5", 1): ("첨부서류 없음", [("01. 증빙양식", "4권 1-5-1 증빙양식.png")]),
}


def put_notes(it: qe.Item, folder: str, log=print) -> int:
    """NOTE_ITEMS 항목에 메모(빈 폴더)와 증빙양식 그림을 넣는다. 새로 넣은 수."""
    if qe.volume_of(it.part) != 4 or (it.no, it.seq) not in NOTE_ITEMS:
        return 0
    import paths
    memo, pics = NOTE_ITEMS[(it.no, it.seq)]
    made = 0
    d = os.path.join(folder, _safe(memo, 80))
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
        made += 1
    for name, src in pics:
        dst = os.path.join(folder, name + os.path.splitext(src)[1])
        if os.path.exists(dst):
            continue
        for base in (paths.bundle_dir(), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
            f = os.path.join(base, "assets", "증빙", src)
            if os.path.exists(f):
                shutil.copyfile(f, dst)
                made += 1
                break
        else:
            log(f"   ⚠ 증빙양식 그림을 찾지 못함: {src}")
    if made:
        log(f"▶ {it.label}: 메모 [{memo}]" + (" + 증빙양식 그림" if pics else "") + " 넣음")
    return made


def _safe(s: str, n: int = 60) -> str:
    s = re.sub(r"\s+", " ", _BAD.sub(" ", s or "")).strip(" .")
    return s[:n].rstrip(" .") or "문서"


def item_refs(it: qe.Item, year: int) -> list[qd.Ref]:
    if (it.no, it.seq) in WISE_ONLY and qe.volume_of(it.part) == 4:
        return []
    return qd.parse_refs(qd.strip_miss(it.basis or ""), default_year=year)


def plan(items: list[qe.Item], year: int) -> tuple[dict, set]:
    """{항목: [Ref]}와 읽어야 할 대장 연도들."""
    out, years = {}, set()
    for it in items:
        refs = item_refs(it, year)
        if refs:
            out[id(it)] = refs
            years |= {r.date.year for r in refs}
    return out, years


def find_doc(ledgers: dict, ref: qd.Ref) -> qd.Doc | None:
    docs = [d for d in ledgers.get(ref.date.year, []) if d.seq == ref.seq]
    if not docs:
        return None
    exact = [d for d in docs if d.date == ref.date]
    if exact:
        return exact[0]
    return min(docs, key=lambda d: abs((d.date - ref.date).days) if d.date else 9999)


def _already(folder: str, base: str) -> bool:
    try:
        return any(n.startswith(base) for n in os.listdir(folder))
    except OSError:
        return False


_FOOTER = ("전화", "전송", "kohom", "시행", "http", "우 ")


def _resident_info(found, text: str) -> list:
    """가릴 것(found) 가운데 공문 꼬리(시행·우·전화·전송·누리집) 줄에만 있는 관리소 번호·메일은 뺀 나머지 —
    입주자 이름·동호수·연락처가 본문에 있는지."""
    lines = (text or "").splitlines()
    start = max((i for i, ln in enumerate(lines) if "시행" in ln), default=max(0, len(lines) - 6))
    body = lines[:start]                       # '시행 …' 줄부터 끝까지는 관리소 꼬리글(주소·전화·전송·메일)
    out = []
    for x in found or []:
        s = x[0] if isinstance(x, (list, tuple)) else str(x)
        in_body = [ln for ln in body if s and s in ln and not any(k in ln for k in _FOOTER)]
        if not in_body and any(s in ln for ln in lines[start:]):
            continue
        out.append(x)
    return out


def save_doc_image(driver, handle: str, folder: str, base: str, log=print) -> bool:
    """대장 문서 창(편철/대장)의 [PC저장 → 이미지저장] → '이미지 저장 선택'(전체 쪽, png) [확인]으로 받은 그림을
    folder/base.png(여러 쪽이면 base - n.png)로 둔다. 2026-11-20 사용자: "PC저장 누르고 이미지파일 받으면 돼"."""
    import glob
    import tempfile
    tmp = tempfile.mkdtemp(prefix="docimg_")
    try:
        driver.execute_cdp_cmd("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": tmp})
        driver.switch_to.window(handle)
        before = set(driver.window_handles)
        driver.execute_script("document.getElementById('nbutton_BtnPrintImage-button').click();")
        sel = None
        end = time.time() + 15
        while time.time() < end and sel is None:
            time.sleep(0.7)
            for wh in set(driver.window_handles) - before:
                driver.switch_to.window(wh)
                if "imageprint_select" in driver.current_url:
                    sel = wh
                    break
        if sel is None:
            return False
        time.sleep(1)
        driver.execute_script("var r=document.getElementById('saveall'); if(r) r.checked=true;"
                              "document.getElementById('nbutton_BtnSubmit-button').click();")
        driver.switch_to.window(handle)
        files = []
        end = time.time() + 40
        while time.time() < end:
            time.sleep(1)
            files = [f for f in glob.glob(os.path.join(tmp, "*")) if not f.endswith((".crdownload", ".tmp"))]
            if files and not glob.glob(os.path.join(tmp, "*.crdownload")):
                time.sleep(1)
                break
        if not files:
            return False
        imgs = []
        for f in files:
            if f.lower().endswith(".zip"):
                import zipfile
                with zipfile.ZipFile(f) as z:
                    z.extractall(tmp)
                imgs += [os.path.join(tmp, n) for n in z.namelist() if n.lower().endswith((".png", ".jpg"))]
            elif f.lower().endswith((".png", ".jpg", ".jpeg")):
                imgs.append(f)
        import page_images as pi
        imgs.sort(key=pi.natural_key)
        if not imgs:
            return False
        for i, f in enumerate(imgs, 1):
            ext = os.path.splitext(f)[1].lower()
            dst = os.path.join(folder, base + (ext if len(imgs) == 1 else f" - {i}{ext}"))
            shutil.move(f, dst)
        log(f"     이미지저장 {len(imgs)}장")
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _row_index(driver, doc: qd.Doc, keyword: str, kind: str = "title") -> int | None:
    """검색한 대장 목록(kind: 'title' 제목 · 'docnum' 등록번호)에서 그 등록번호 줄의 순서(0부터)."""
    import ledger
    ledger.open_register(driver)
    ledger.select_year(driver, doc.date.year)
    ledger.search_register(driver, keyword, kind)
    end = time.time() + 20
    rows = []
    while time.time() < end:
        time.sleep(1)
        try:
            rows = ledger.list_rows(driver)
        except Exception:
            continue
        if rows:
            break
    driver.switch_to.default_content()
    for i, row in enumerate(rows):
        if any(str(t).strip() == doc.number for t in row.get("text", [])):
            return i
    return None


def save_doc(driver, doc: qd.Doc, folder: str, base: str, homnet_pw: str, office: str, log, stop=None,
             attach: bool = True) -> dict:
    """대장 문서 하나를 열어 본문 PDF + 첨부를 folder에 둔다."""
    import collector as co
    import privacy
    out = {"pdf": False, "attach": 0, "note": ""}
    # 등록번호로 찾는다(대장 검색 '등록번호'에 번호만 — 제목의 괄호 때문에 제목 검색이 빗나가는 일이 없다)
    kw, kind = str(doc.seq), "docnum"
    idx = _row_index(driver, doc, kw, kind)
    if idx is None:                                   # 예전 방식(제목) — 등록번호 검색이 안 될 때만
        kind = "title"
        kw = re.sub(r"[\[\]()'\"%]", " ", doc.title).strip()[:40]
        idx = _row_index(driver, doc, kw)
        if idx is None:
            kw = re.sub(r"\s+", " ", kw)[:15]
            idx = _row_index(driver, doc, kw)
    if idx is None:
        out["note"] = "대장에서 등록번호로도 찾지 못함"
        return out
    known = frozenset(driver.window_handles)
    handle = co.open_first_doc(driver, kw, lambda _m: None, year=doc.date.year, password=homnet_pw, start_row=idx,
                               search_type=kind)
    try:
        driver.switch_to.window(handle)
        status, d = co.wait_new_doc(driver, "", log, password=homnet_pw, known=known)
        if status in ("encrypted", "same") or d is None:
            out["note"] = "문서를 열지 못함(암호 문서)" if status == "encrypted" else "문서를 읽지 못함"
            co.dismiss_password(driver)
            return out
        if d.get("viewer") and d["viewer"] != handle:
            co._close_window(driver, handle)
            handle = d["viewer"]
            driver.switch_to.window(handle)
        if status == "view":
            out["note"] = "본문 없는 '조회' 화면(접수 문서)"
            return out
        if d.get("unlocked"):
            d = co._mask_secure_doc(d)
        text = d.get("text", "")
        if str(doc.seq) not in text and doc.title[:8] not in text:
            log(f"      ⚠ 연 문서가 '{doc.number}'인지 확인하지 못했습니다(그대로 저장).")
        os.makedirs(folder, exist_ok=True)
        html, found = co.masked_pdf_html(d.get("html", ""), text, doc.title)
        saved_img = False
        resident = _resident_info(found, text)
        if not resident and not d.get("unlocked"):     # 입주자 이름·동호수 등이 없으면 문서 창 [PC저장 → 이미지저장]
            try:
                saved_img = save_doc_image(driver, handle, folder, base, log)
            except Exception as ex:
                log(f"      (이미지저장 실패 — PDF로 받습니다: {type(ex).__name__})")
                saved_img = False
            finally:
                try:
                    driver.switch_to.window(handle)
                except Exception:
                    pass
        if not saved_img:                              # 가릴 것이 있거나 이미지저장이 안 되면 000으로 가린 PDF
            pdf = os.path.join(folder, base + ".pdf")
            co.html_to_pdf(driver, html, pdf)
            left = [x for x in found if x[0] in privacy.pdf_text(pdf)]
            if left:
                tmp = pdf + ".tmp"
                os.replace(pdf, tmp)
                privacy.mask_pdf(tmp, pdf, (), (), found)
                os.remove(tmp)
        out["pdf"] = True
        if not attach or (stop is not None and stop.is_set()):     # 본문만 넣는 항목
            return out
        tmpdir = os.path.join(folder, "_받는중")
        try:
            files = co.download_attachments(driver, handle, tmpdir, log)
            if files:
                known_p = privacy.find_private(text)
                adir = os.path.join(tmpdir, "_가림")
                co.mask_attachments(files, adir, log, known=known_p)
                for n in sorted(os.listdir(adir)):
                    dst = os.path.join(folder, f"{base} (첨부) {n}")
                    k = 2
                    while os.path.exists(dst):
                        stem, ext = os.path.splitext(n)
                        dst = os.path.join(folder, f"{base} (첨부) {stem} ({k}){ext}")
                        k += 1
                    shutil.move(os.path.join(adir, n), dst)
                    out["attach"] += 1
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            try:
                driver.switch_to.window(handle)
                driver.switch_to.default_content()
            except Exception:
                pass
        return out
    finally:
        co._close_window(driver, handle)


def _is_img(name: str) -> bool:
    import page_images as pi
    return os.path.splitext(name)[1].lower() in pi.IMG_EXT


class Converter:
    """받은 파일 → 쪽 그림(PNG). 한글 파일 변환용 한글 프로그램은 처음 필요할 때 한 번만 연다."""

    def __init__(self, passwords=(), log=print, center: str = ""):
        import tempfile
        self.passwords, self.log = tuple(p for p in passwords if p), log
        self.center = center                  # 전국 목록 엑셀은 이 단지 줄만 한 장으로
        self.tmp = tempfile.mkdtemp(prefix="qfold_")
        self._hwp = None

    def _hwp_obj(self):
        if self._hwp is None:
            import hwp_report
            self._hwp = hwp_report.Hwp(visible=False)
        return self._hwp

    def to_images(self, path: str) -> str:
        """path를 같은 폴더의 '이름.png'(여러 쪽이면 '이름 - 1.png' …)로 바꾸고 원본을 지운다.
        성공하면 '', 못 하면 이유(원본은 지운다 — 보고서에 넣지 않는다)."""
        import page_images as pi
        folder, name = os.path.split(path)
        stem, ext = os.path.splitext(name)
        ext = ext.lower()
        if ext in pi.IMG_EXT:
            return ""
        work = os.path.join(self.tmp, f"w{len(os.listdir(self.tmp))}")
        os.makedirs(work)
        if ext in pi.XL_EXT and self.center and self._center_excel(path, work, stem, folder):
            _remove(path)
            return ""
        try:
            hwp = self._hwp_obj() if ext in pi.HWP_EXT else None
            pages, st = pi.file_pages(path, work, self.passwords, hwp, self.log)
        except Exception as ex:
            pages, st = [], f"fail:{type(ex).__name__}"
        if not pages:
            why = {"locked": "암호가 걸려 있거나 열리지 않음", "skip": f"그림으로 바꿀 수 없는 형식({ext or '확장자 없음'})",
                   "fail": "파일이 열리지 않음"}.get(st, f"파일이 열리지 않음({st})" if st else "쪽이 없음")
            _remove(path)
            return why
        if len(pages) > 1 and ext == ".pdf" and "(첨부)" not in stem:     # 공문 본문은 한 장으로(넘친 꼬리글까지)
            merged = os.path.join(work, "_merged.png")
            pi.stack_pages(pages, merged)
            pages = [merged]
        for i, p in enumerate(pages, 1):
            dst = os.path.join(folder, f"{stem}.png" if len(pages) == 1 else f"{stem} - {i}.png")
            if os.path.abspath(p) != os.path.abspath(dst):
                shutil.copy2(p, dst) if p == path else shutil.move(p, dst)
        _remove(path)
        return ""

    def _center_excel(self, path: str, work: str, stem: str, folder: str) -> bool:
        """전국 목록 엑셀에 우리 단지 줄이 있으면 제목·머리글+우리 단지 줄만 그림 한 장으로(2025 보고서 4권처럼)."""
        import page_images as pi
        short = os.path.join(work, "_src" + os.path.splitext(path)[1])      # 엑셀 경로 길이 제한(218자)
        shutil.copy2(path, short)
        pdf = os.path.join(work, "_center.pdf")
        try:
            st = pi.excel_center_pdf(short, pdf, self.center, self.passwords)
        except Exception:
            st = "fail"
        if st:
            return False
        try:
            import privacy
            masked = pdf[:-4] + "_가림.pdf"
            privacy.mask_pdf(pdf, masked)
            pdf = masked
        except Exception:
            pass
        import pymupdf
        with pymupdf.open(pdf) as doc:
            if not len(doc):
                return False
            out = os.path.join(folder, f"{stem} ({self.center}).png")
            doc[0].get_pixmap(dpi=150).save(out)
        pi.trim_white(out)
        self.log(f"     🖼 엑셀에서 {self.center} 줄만 그림 한 장: {os.path.basename(out)}")
        return True

    def close(self):
        if self._hwp is not None:
            self._hwp.quit()
            self._hwp = None
        shutil.rmtree(self.tmp, ignore_errors=True)


def _center_name(office: str) -> str:
    """'광주양림2관리소' → '광주양림2'(엑셀 단지명 칸과 맞춤)."""
    return re.sub(r"\s*(관리소|주거행복지원센터|센터)$", "", (office or "").strip())


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _stopped(stop) -> bool:
    return stop is not None and stop.is_set()


def convert_folder(folder: str, conv: Converter, log=print, stop=None) -> list[str]:
    """폴더에 남은 우리 파일('01. …')을 그림으로 바꾼다. 못 바꾼 파일의 이유 목록."""
    out = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for n in names:
        if _stopped(stop):
            break
        p = os.path.join(folder, n)
        if not os.path.isfile(p) or not OURS.match(n) or _is_img(n) or n == REASON_NAME:
            continue
        log(f"     🖼 그림으로: {n}")
        why = conv.to_images(p)
        if why:
            out.append(f"{n} — {why}")
            log(f"     ✗ 건너뜀: {n} ({why})")
    return out


def wise_targets(name: str, key: str, complex_code: str, basic_codes=()) -> list[tuple[str, str]]:
    """WISE 캡처 하나가 만들 (파일 이름, 단지코드) 목록. 영세민 기본단가 탭은 [기본단가 단지]에 적은 단지마다
    한 장('… - 1', '… - 2'), 적지 않았으면 WISE 단지코드로 한 장."""
    codes = [c for c in basic_codes if c] if key == "임대조건:기본단가" else []
    if not codes:
        return [(name, complex_code)]
    if len(codes) == 1:
        return [(name, codes[0])]
    return [(f"{name} - {n}", c) for n, c in enumerate(codes, 1)]


def wise_shots(it: qe.Item, folder: str, log=print, year: int = 0, complex_code: str = "",
               basic_codes=(), stop=None) -> tuple[int, list[str]]:
    """4권 작성방법의 WISE 화면 캡처를 넣는다(WISE에서 조회·개인정보 지움). (새로 찍은 수, 못 넣은 이유 목록)."""
    import datetime as _dt
    import wise_capture
    wise_capture.STOP = stop
    out, made = [], 0
    for name0, key in WISE_SHOTS.get((it.no, it.seq), []):
        for name, code in wise_targets(name0, key, complex_code, basic_codes):
            if _stopped(stop):
                return made, out
            dst = os.path.join(folder, name + ".png")
            if os.path.exists(dst):
                continue
            log(f"     📷 WISE: {name}" + (f" ({code})" if code != complex_code else ""))
            if key == "분양권퇴거유예세대관리":
                why = wise_capture.capture_bunyang(dst, code, log)
            elif key.startswith("자격검색:"):
                why = wise_capture.capture_jagyeok(int(key.split(":")[1]), dst, year or _dt.date.today().year,
                                                   code, log)
            elif key.startswith("임대조건:"):
                why = wise_capture.capture_imdae(key.split(":")[1], dst, code, log)
            else:
                why = wise_capture.capture(key, dst, year or _dt.date.today().year, code, log)
            if _stopped(stop):                     # 멈춘 것은 이유 파일에 적지 않는다(다시 폴더링하면 다시 찍음)
                return made, out
            if why:
                out.append(f"{name} — {why}")
                log(f"     ✗ {name}: {why}")
            else:
                made += 1
                log(f"     📷 WISE 캡처: {name}")
    return made, out


def write_reasons(folder: str, it: qe.Item, reasons: list[str]) -> None:
    """항목 폴더에 저장 안 된 파일과 그 이유를 적는다(없으면 예전 이유 파일을 지운다)."""
    p = os.path.join(folder, REASON_NAME)
    manual = MANUAL_SHOTS.get((it.no, it.seq), [])
    try:
        has_list = any("홈넷" in n and _is_img(n) for n in os.listdir(folder))   # 대장 목록 캡처를 넣었으면
    except OSError:
        has_list = False
    if has_list:
        manual = [m for m in manual if "홈넷" not in m]
    if not reasons and not manual:
        _remove(p)
        return
    lines = [it.label, f"폴더링 만든 때: {time.strftime('%Y-%m-%d %H:%M')}", ""]
    if reasons:
        lines += ["■ 저장하지 못한 파일과 이유"] + [f"  - {r}" for r in reasons] + [""]
    if manual:
        lines += ["■ 보고서 4권 예시에 있지만 자동으로 넣지 못하는 화면 캡처(직접 캡처해 이 폴더에 넣어 주세요)"]
        lines += [f"  - {m}" for m in manual]
    try:
        with open(p, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass


def finish(items: list[qe.Item], root: str, reasons: dict, passwords=(), log=print, stop=None,
           year: int = 0, complex_code: str = "", center: str = "", basic_codes=()) -> dict:
    """대장에서 받은 뒤(또는 받을 것이 없을 때): 남은 파일을 그림으로, WISE 캡처, 이유 파일."""
    res = {"converted_fail": 0, "wise": 0, "wise_fail": 0}
    conv = Converter(passwords, log, center)
    try:
        for it in items:
            if _stopped(stop):
                break
            folder = qe.item_dir(root, it, create=True)
            why = reasons.get(id(it), [])
            bad = convert_folder(folder, conv, log, stop)
            if _stopped(stop):
                break
            res["converted_fail"] += len(bad)
            put_notes(it, folder, log)
            if WISE_SHOTS.get((it.no, it.seq)):
                made, wbad = wise_shots(it, folder, log, year, complex_code, basic_codes, stop)
                res["wise"] += made
                res["wise_fail"] += len(wbad)
                bad += wbad
                if _stopped(stop):
                    break
            write_reasons(folder, it, why + bad)
    finally:
        conv.close()
    return res


# ---------------- 매월 문서: 대장 검색 목록 캡처 ----------------
MONTHLY_MIN = 2            # 같은 제목(날짜·숫자 빼고)의 근거 문서가 이만큼 있으면 매월 문서로 본다
MAX_LIST_PAGES = 6


def title_key(title: str) -> str:
    """제목에서 연도·월·차수·숫자·괄호를 뺀 모양('2025년 12월 갱신계약 대상세대 계약 체결 안내' → '갱신계약 대상세대 계약 체결 안내')."""
    t = re.sub(r"[(\[{（].*?[)\]}）]", " ", title or "")
    t = re.sub(r"\d+\s*(년도|년|월|차|분기|회|일)", " ", t)
    t = re.sub(r"[\d~.,·:/\-]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def search_word(titles: list[str]) -> str:
    """여러 제목에 모두 들어 있는 가장 긴 글(대장 제목 검색어). 앞뒤 공백·조사 정리, 최대 20자."""
    keys = [title_key(t) for t in titles if title_key(t)]
    if not keys:
        return ""
    common = keys[0]
    for k in keys[1:]:
        m = difflib.SequenceMatcher(None, common, k, autojunk=False).find_longest_match(0, len(common), 0, len(k))
        common = common[m.a:m.a + m.size]
    common = common.strip()
    if len(common.replace(" ", "")) < 4:
        return ""
    if len(common) > 20:                     # 낱말 중간에서 끊지 않는다
        cut = common[:21].rfind(" ")
        common = common[:cut] if cut >= 6 else common[:20]
    return common.strip()


def monthly_groups(refs: list, ledgers: dict, least: int = 0) -> list[tuple[int, str, int, set]]:
    """근거 문서 중 매월 보내는 같은 제목 묶음 → [(첫 순번, 검색어, 연도, {등록번호})]."""
    groups: dict[tuple[str, int], list] = {}
    for k, ref in enumerate(refs, 1):
        doc = find_doc(ledgers, ref)
        if doc is None or not doc.date:
            continue
        key = title_key(doc.title)
        if key:
            groups.setdefault((key, doc.date.year), []).append((k, doc))
    out = []
    for (key, yr), lst in groups.items():
        nums = {d.number for _k, d in lst}
        if len(nums) < (least or MONTHLY_MIN):
            continue
        kw = search_word([d.title for _k, d in lst]) or key[:20]
        out.append((lst[0][0], kw, yr, nums))
    return sorted(out)


def _back_to_main(driver) -> None:
    try:
        import homnet
        driver.switch_to.window(homnet.main_window(driver))
        driver.switch_to.default_content()
    except Exception:
        pass


# 목록 화면(프레임) 안의 스크롤 칸을 다 펼쳐 한 번에 찍히게 한다. 펼친 문서 높이를 돌려준다.
_JS_UNROLL = r"""
var els = document.querySelectorAll('*'), n = 0;
for (var i = 0; i < els.length; i++) {
  var e = els[i];
  if (e.scrollHeight > e.clientHeight + 4 && e.clientHeight > 40) {
    var st = getComputedStyle(e);
    if (/(auto|scroll|hidden)/.test(st.overflowY) && e !== document.body && e !== document.documentElement) {
      e.style.height = e.scrollHeight + 'px'; e.style.maxHeight = 'none'; e.style.overflowY = 'visible'; n++;
    }
  }
}
var fr = arguments[0] ? document.getElementById(arguments[0]) : null;
if (fr && arguments[1]) { fr.style.height = arguments[1] + 'px'; fr.setAttribute('height', arguments[1]); }
document.documentElement.style.height = 'auto'; document.body.style.height = 'auto';
document.documentElement.style.overflow = 'visible'; document.body.style.overflow = 'visible';
var r = fr ? fr.getBoundingClientRect() : null;
return {h: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight),
        w: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
        rect: r ? {x: r.left + window.scrollX, y: r.top + window.scrollY, w: r.width, h: r.height} : null, n: n};
"""


# 대장 목록(YUI 표)에서 수신자(발신자) 칸 글자를 가리고(입주자 이름·주소), 아래 '미리보기' 칸을 접는다.
# 돌려주는 값: 수신자 칸 수, 가려진 칸 수(같아야 저장한다).
_JS_PRIVATE = r"""
if (!document.getElementById('__qhide')) {
  var st = document.createElement('style'); st.id = '__qhide';
  st.textContent = 'td.yui-dt-col-RECEIPIENT .yui-dt-liner{visibility:hidden !important}';
  document.head.appendChild(st);
}
var all = document.querySelectorAll('td.yui-dt-col-RECEIPIENT .yui-dt-liner'), hid = 0;
all.forEach(function(e){ if (getComputedStyle(e).visibility === 'hidden') hid++; });
var walker = document.evaluate("//*[contains(text(),'미리보기 영역')]", document, null, 7, null);
for (var i = 0; i < walker.snapshotLength; i++) {
  var e = walker.snapshotItem(i), p = e;
  while (p && p.parentElement && p.parentElement !== document.body && p.getBoundingClientRect().height < 150) p = p.parentElement;
  if (p) p.style.display = 'none';
}
window.dispatchEvent(new Event('resize'));
return [all.length, hid];
"""


def _shot(driver, path: str) -> None:
    """지금 기록물등록대장 목록(contentview 안에 들어와 있는 상태)을 다 펼쳐 path(PNG)로 찍는다.
    수신자(발신자) 칸은 가린다 — 못 가리면 저장하지 않고 LedgerError. 끝나면 다시 contentview 안으로 돌아온다."""
    import base64

    import ledger
    n_all, n_hid = driver.execute_script(_JS_PRIVATE)
    if n_all == 0 or n_hid < n_all:
        raise ledger.LedgerError("대장 목록의 수신자 칸(입주자 이름·주소)을 가리지 못해 캡처를 저장하지 않음")
    _shot_inner(driver, path, base64)


_JS_GRID_OPEN = r"""
var n = 0;
document.querySelectorAll('.yui-dt-bd').forEach(function(e){
  var h = e.scrollHeight; if (h > e.clientHeight) { e.style.height = (h + 4) + 'px'; e.style.maxHeight = 'none';
  e.style.overflowY = 'visible'; n++; }
  var p = e.parentElement;                                 // 감싼 칸들도 줄이 다 들어가게
  for (var k = 0; k < 6 && p && p !== document.body; k++, p = p.parentElement) {
    if (p.clientHeight && p.scrollHeight > p.clientHeight) { p.style.height = 'auto'; p.style.maxHeight = 'none';
      p.style.overflow = 'visible'; }
  }
});
return n;
"""


def crop_list(path: str) -> None:
    """대장 목록 그림에서 글자 있는 윗부분(목록·쪽 번호까지)만 남긴다 — 아래 빈 칸·미리보기 칸은 잘라 가로로 긴 그림."""
    from PIL import Image
    im = Image.open(path).convert("L")
    w, h = im.size
    px = im.load()
    blank_run, start = 0, None
    for y in range(min(h, 120), h):
        dark = sum(1 for x in range(0, w, 3) if px[x, y] < 200)
        if dark == 0:
            blank_run += 1
            if blank_run == 1:
                start = y
            if blank_run >= 60:                 # 60줄 넘게 비면 목록이 끝난 것
                Image.open(path).crop((0, 0, w, min(h, start + 8))).save(path)
                return
        else:
            blank_run = 0


def _shot_inner(driver, path: str, base64) -> None:
    driver.execute_script(_JS_GRID_OPEN)                      # 표 안 스크롤을 펼쳐 50줄이 다 보이게
    time.sleep(0.5)
    inner = driver.execute_script(_JS_UNROLL, "", 0)
    driver.switch_to.parent_frame()                         # linkageIframe 안
    mid = driver.execute_script(_JS_UNROLL, "contentview", inner["h"])
    driver.switch_to.parent_frame()                         # 본 화면
    top = driver.execute_script(_JS_UNROLL, "linkageIframe", mid["h"])
    cv, lk = mid["rect"], top["rect"]
    x, y = lk["x"] + cv["x"], lk["y"] + cv["y"]
    w, h = min(cv["w"], max(inner["w"], 800)), inner["h"]
    data = driver.execute_cdp_cmd("Page.captureScreenshot", {
        "format": "png", "captureBeyondViewport": False,       # 화면을 이미 길게 해 둠(넘겨 찍으면 표가 다시 접힘)
        "clip": {"x": x, "y": y, "width": w, "height": h, "scale": 1}})
    with open(path, "wb") as f:
        f.write(base64.b64decode(data["data"]))
    crop_list(path)
    driver.switch_to.frame("linkageIframe")
    driver.switch_to.frame("contentview")


def list_shots(driver, kw: str, year: int, folder: str, base: str, log=print, internal: bool = True) -> tuple[int, str]:
    """대장 year년을 kw로 제목 검색한 목록을 쪽(50건)마다 한 장씩 찍는다. (찍은 장 수, 못 찍은 이유)."""
    import ledger
    # 대장을 열기 전에 화면을 길게 해 둔다 — 목록 표 높이가 열 때 창 높이로 정해지므로(50줄이 다 보이게)
    try:
        return _list_shots(driver, kw, year, folder, base, log, internal)
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass


# [목록인쇄] 창(content 프레임의 table.normal)을 찍는다. 글자는 옮기지 않되, 모두 빈 칸은 숨겨 꽉 차게(사용자 2026-11-21).
# 수신자(발신자) 칸에는 입주자 주소·이름이 있어 그 칸 글자만 제자리에서 "000"으로 가린다.
LIST_ROWS = 30             # 목록 한 장에 넣을 줄 수 — 넘으면 머리줄을 붙여 다음 장으로 끊는다
_MASK_COLS = ("수신자(발신자)",)
_JS_PRINT_TABLE = r"""
var t = document.querySelector('table.normal') || document.querySelector('table');
if (!t || !t.rows.length) return null;
var mask = [], hdr = t.rows[0];
for (var i = 0; i < hdr.cells.length; i++) {
  var x = (hdr.cells[i].innerText || '').replace(/\s+/g, '');
  if (arguments[0].indexOf(x) >= 0) mask.push(i);
}
var dc = -1;
for (var i = 0; i < hdr.cells.length; i++) if ((hdr.cells[i].innerText || '').replace(/\s+/g, '') === '등록일자') dc = i;
var left = 0, shown = 0;
for (var r = 1; r < t.rows.length; r++) {
  var row = t.rows[r];
  if (row.cells.length !== hdr.cells.length) continue;
  if (!row.dataset.q) {               // 처음 한 번만: 내부결재만이면 수신자가 있는 줄(발송 문서)을 숨긴다
    row.dataset.q = '1';
    var ext = mask.some(function(i){ return (row.cells[i].innerText || '').trim(); });
    if (arguments[1] && ext) row.style.display = 'none';
  }
  if (row.style.display === 'none') continue;
  shown++;
  mask.forEach(function(i){ var c = row.cells[i];
    if ((c.innerText || '').trim()) c.innerText = '000';
    var v = (c.innerText || '').trim(); if (v && v !== '000') left++; });
}
// 보이는 줄이 모두 빈 칸(수신자·배부번호·반송 등)은 숨겨 옆 칸을 당긴다(사용자 2026-11-21 "꽉 차게")
for (var i = 0; i < hdr.cells.length; i++) {
  var empty = true;
  for (var r = 1; r < t.rows.length && empty; r++) {
    var row = t.rows[r];
    if (row.cells.length !== hdr.cells.length || row.style.display === 'none') continue;
    if ((row.cells[i].innerText || '').trim()) empty = false;
  }
  if (empty && shown) Array.from(t.rows).forEach(function(row){
    if (row.cells.length === hdr.cells.length) row.cells[i].style.display = 'none'; });
}
document.documentElement.style.overflow = 'visible'; document.body.style.overflow = 'visible';
var b = t.getBoundingClientRect();
var rows = [], dates = [];
Array.from(t.rows).forEach(function(r, k){
  if (r.style.display === 'none') return;
  var q = r.getBoundingClientRect(); rows.push([q.top - b.top, q.bottom - b.top]);
  if (k > 0 && dc >= 0 && r.cells.length === hdr.cells.length) dates.push((r.cells[dc].innerText || '').replace(/\s+/g, ' ').trim());
});
var dq = dc >= 0 ? hdr.cells[dc].getBoundingClientRect() : null;
return {masked: mask.length, left: left, shown: shown, x: b.left + scrollX, y: b.top + scrollY, w: b.width, h: b.height,
        rows: rows, dates: dates, dcol: dq ? [dq.left - b.left, dq.right - b.left] : null,
        doc: document.documentElement.scrollHeight, docw: document.documentElement.scrollWidth};
"""


def print_list_shot(driver, path: str, internal: bool = True) -> list:
    """지금 대장 목록을 [목록인쇄] 창으로 열어 표를 화면 그대로 찍는다(여러 쪽이면 첫~마지막 쪽 한 번에).
    LIST_ROWS줄이 넘으면 머리줄을 붙여 path " - 1.png", " - 2.png" …로 끊어 저장하고 만든 파일 목록을 돌려준다.
    internal이면 내부결재(수신자 칸이 빈 줄)만 남긴다(사용자: "안내문은 내부결재만"). 장마다 등록일자 확대 칸을 겹친다.
    수신자(발신자) 칸을 가리지 못하면 저장하지 않고 LedgerError. 끝나면 대장 contentview로 돌아온다."""
    import base64

    import ledger
    main = driver.current_window_handle
    before = set(driver.window_handles)
    driver.execute_script("document.getElementById('nbutton_BtnPrint-button').click();")
    win = None
    end = time.time() + 15
    while time.time() < end and win is None:
        time.sleep(0.7)
        new = [h for h in driver.window_handles if h not in before]
        win = new[0] if new else None
    if win is None:
        raise ledger.LedgerError("대장 [목록인쇄] 창이 열리지 않음")
    try:
        driver.switch_to.window(win)
        names = [x.replace(" ", "") for x in _MASK_COLS]
        info = None
        picked = False
        end = time.time() + 40                     # 목록이 길면 창이 늦게 그려진다
        while time.time() < end and not info:
            time.sleep(1.5)
            for h in [x for x in driver.window_handles if x not in before]:
                try:
                    driver.switch_to.window(h)
                    driver.switch_to.default_content()
                except Exception:
                    continue
                if not picked and "인쇄영역" in (driver.title or "") + driver.execute_script(
                        "return document.body ? document.body.innerText.slice(0,40) : ''"):
                    # 여러 쪽이면 '인쇄영역선택' — 첫 쪽 ~ 마지막 쪽을 골라 한 번에
                    driver.execute_script(
                        "var ss=document.querySelectorAll('select'); if(ss.length>=2){ss[0].selectedIndex=0;"
                        "ss[1].selectedIndex=ss[1].options.length-1; ss[1].dispatchEvent(new Event('change'));}"
                        "var b=Array.from(document.querySelectorAll('button,input[type=button]'))"
                        ".find(e=>(e.innerText||e.value||'').trim()==='확인'); if(b) b.click();")
                    picked = True
                    continue
                try:
                    driver.switch_to.frame("content")
                    info = driver.execute_script(_JS_PRINT_TABLE, names, internal)
                    if info:
                        win = h
                        break
                except Exception:
                    info = None
        if not info or not info["masked"] or info["left"]:
            raise ledger.LedgerError("목록인쇄 표의 수신자 칸(입주자 주소·이름)을 가리지 못해 저장하지 않음"
                                     + (" (표가 열리지 않음)" if not info else ""))
        if not info.get("shown"):
            raise ledger.LedgerError("검색 목록에 내부결재 문서가 없음" if internal else "검색 결과가 없음")
        driver.switch_to.default_content()
        fr = driver.execute_script("var f=document.getElementsByName('content')[0]||document.getElementById('content');"
                                   "var r=f.getBoundingClientRect(); return {x:r.left, y:r.top};")
        tall = int(fr["y"] + info["doc"] + 60)
        wide = int(fr["x"] + max(info["docw"], info["x"] + info["w"]) + 40)
        driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride",
                               {"width": max(1920, wide), "height": max(900, tall), "deviceScaleFactor": 1,
                                "mobile": False})
        time.sleep(1.5)
        driver.switch_to.frame("content")
        info = driver.execute_script(_JS_PRINT_TABLE, names, internal)
        driver.switch_to.default_content()
        data = driver.execute_cdp_cmd("Page.captureScreenshot", {
            "format": "png", "captureBeyondViewport": False,
            "clip": {"x": fr["x"] + info["x"], "y": fr["y"] + info["y"], "width": info["w"] + 2,
                     "height": info["h"] + 2, "scale": 1}})
        tmp = path + ".tmp.png"
        with open(tmp, "wb") as f:
            f.write(base64.b64decode(data["data"]))
        return split_rows(tmp, path, info["rows"], LIST_ROWS, info.get("dates"), info.get("dcol"))
    finally:
        try:
            driver.execute_cdp_cmd("Emulation.clearDeviceMetricsOverride", {})
        except Exception:
            pass
        for h in [x for x in driver.window_handles if x not in before]:
            try:
                driver.switch_to.window(h)
                driver.close()
            except Exception:
                pass
        driver.switch_to.window(main)
        driver.switch_to.default_content()
        driver.switch_to.frame("linkageIframe")
        driver.switch_to.frame("contentview")


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    for name in (("malgunbd.ttf", "malgun.ttf") if bold else ("malgun.ttf",)):
        try:
            return ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name), size)
        except OSError:
            continue
    return ImageFont.load_default()


def date_inset(sheet, dates: list, x: int, y: int = 6):
    """등록일자를 크게 쓴 칸(검은 테두리)을 표 위 x 자리에 겹쳐 붙인다 — 한글파일 예시처럼 날짜가 잘 보이게.
    칸이 표 아래로 넘치면 그림을 아래로 늘린다."""
    from PIL import Image, ImageDraw
    if not dates:
        return sheet
    fh, fr = _font(26, True), _font(24)
    pad, rh, hh, bd = 22, 46, 50, 4
    tw = max(int(fr.getlength(d)) for d in dates)
    w = max(tw, int(fh.getlength("등록일자"))) + pad * 2
    h = hh + rh * len(dates)
    box = Image.new("RGB", (w, h), "white")
    g = ImageDraw.Draw(box)
    g.rectangle((0, 0, w, hh), fill=(232, 232, 232))
    g.text((w / 2, hh / 2), "등록일자", font=fh, fill=(40, 40, 40), anchor="mm")
    for i, d in enumerate(dates):
        top = hh + rh * i
        g.line((0, top, w, top), fill=(200, 200, 200), width=1)
        g.text((w / 2, top + rh / 2), d, font=fr, fill=(0, 0, 0), anchor="mm")
    x = max(0, min(int(x), sheet.width - w - bd * 2))
    out = Image.new("RGB", (sheet.width, max(sheet.height, y + h + bd * 2 + 6)), "white")
    out.paste(sheet, (0, 0))
    ImageDraw.Draw(out).rectangle((x, y, x + w + bd * 2 - 1, y + h + bd * 2 - 1), fill=(0, 0, 0))
    out.paste(box, (x + bd, y + bd))
    return out


def split_rows(src: str, path: str, rows: list, per: int = LIST_ROWS, dates: list | None = None,
               dcol: list | None = None) -> list:
    """표 그림 src(머리줄 + 줄들, rows = 줄마다 [위, 아래] 픽셀)를 per줄씩 끊어 머리줄을 붙여 저장한다.
    per줄 이하이면 path 한 장, 넘으면 path에 " - 1", " - 2" …를 붙인다. src는 지운다.
    dates(줄마다 등록일자)와 dcol(등록일자 칸 [왼쪽, 오른쪽])이 있으면 장마다 날짜 확대 칸을 겹친다."""
    from PIL import Image
    with Image.open(src) as f:
        im = f.convert("RGB")
    os.remove(src)
    body = rows[1:]
    dates = list(dates or [])
    if len(dates) != len(body):
        dates = []
    stem, ext = os.path.splitext(path)
    top = int(round(rows[0][1])) if rows else 0          # 머리줄 아래 끝
    head = im.crop((0, 0, im.width, top))
    chunks = [(k, body[k:k + per]) for k in range(0, len(body), per)] or [(0, [])]
    out = []
    for k, part in chunks:
        if len(chunks) == 1:
            sheet = im
        else:
            y0, y1 = int(round(part[0][0])), min(im.height, int(round(part[-1][1])) + 1)
            piece = im.crop((0, y0, im.width, y1))
            sheet = Image.new("RGB", (im.width, head.height + piece.height), "white")
            sheet.paste(head, (0, 0))
            sheet.paste(piece, (0, head.height))
        if dates and dcol:
            sheet = date_inset(sheet, dates[k:k + len(part)], dcol[0] + 4)
        p = path if len(chunks) == 1 else f"{stem} - {len(out) + 1}{ext}"
        sheet.save(p)
        out.append(p)
    return out


def _list_shots(driver, kw: str, year: int, folder: str, base: str, log=print, internal: bool = True) -> tuple[int, str]:
    import ledger
    ledger.open_register(driver)
    ledger.select_year(driver, year)
    rows = ledger.go_page(driver, 1, kw)
    if not rows:
        driver.switch_to.default_content()
        return 0, "검색 결과가 없음"
    os.makedirs(folder, exist_ok=True)
    try:
        made = len(print_list_shot(driver, os.path.join(folder, base + ".png"), internal))
    except ledger.LedgerError as ex:
        driver.switch_to.default_content()
        return 0, str(ex)
    driver.switch_to.default_content()
    return made, ""


# ---------------- 자료집계(제출완료함) 취합자료 ----------------
# (번호, 순번) → (제출완료함 자료명 검색어, 저장 이름) — 받은 엑셀은 우리 단지 줄만 그림 한 장으로(Converter)
MOUMI_SOURCES = {
    ("1-1", 1): ("예비입주자 모집공고 계획", "01. 예비입주자 모집 계획 엑셀파일 캡처"),
}
# (번호, 순번) → 받을 대장 문서 제목 조건과 첨부 받기 여부(2026-11-20 사용자: 1-1 정기검색은 결과 공문만)
_half_year_result = qd.half_year_result      # 판별은 quality_draft에 (KODAS 초안 작성도 같이 씀)


# (번호, 순번) → 받을 대장 문서 규칙. 'ledger' = 근거 번호가 아니라 평가년도 대장에서 제목으로 고름, 'attach' = 첨부도 받기
def _half_of(doc) -> tuple[str | None, str | None]:
    """(날짜로 본 반기, 제목에 적힌 반기). 정기검색은 1월·7월 의뢰 → 결과 공문은 1~6월이면 상반기, 7~12월이면 하반기.
    예: '주택소유 심사 결과(26년 예비자 정기(상), 29차)' 7.29. → 제목은 상반기지만 날짜로는 하반기(2026-11-20 사용자)."""
    by_date = None if not doc.date else ("상반기" if doc.date.month <= 6 else "하반기")
    s = re.sub(r"\s+", "", doc.title or "")
    by_title = "상반기" if re.search(r"\(상\)|상반기", s) else "하반기" if re.search(r"\(하\)|하반기", s) else None
    m = re.search(r"(\d{2,4})년", s)
    if m and doc.date:
        y = int(m.group(1))
        if (y + 2000 if y < 100 else y) != doc.date.year:
            by_title = None                 # '2024년 하반기'(2025.2. 공문)처럼 지난해 예비자 이야기 — 견주지 않는다
    return by_date, by_title


DOC_RULES = {
    ("1-1", 2): {"attach": False, "half": _half_of},   # 평가 근거의 심사 결과 공문(번호로 찾음), 본문만·상하반기 표시
}


def ledger_docs(driver, it, rule, docs, root, homnet_pw, office, reasons, res, log=print, stop=None) -> None:
    """평가년도 대장에서 rule['ledger'] 제목에 맞는 문서를 날짜순으로 받는다(본문만)."""
    why = reasons.setdefault(id(it), [])
    folder = qe.item_dir(root, it, create=True)
    hits = sorted((d for d in docs if rule["ledger"](d.title)), key=lambda d: (d.date or 0, d.seq))
    log(f"▶ {it.label}  (대장에서 고른 문서 {len(hits)}건)")
    if not hits:
        why.append("평가년도 대장에 예비자 정기 주택소유 심사 결과 공문이 없음")
        return
    for k, doc in enumerate(hits, 1):
        if stop is not None and stop.is_set():
            return
        half = rule.get("half")
        tag = ""
        if half:
            by_date, by_title = half(doc)
            if by_date is None:
                why.append(f"{doc.number} {doc.title} — 날짜가 없어 상반기·하반기를 가리지 못해 넣지 않음")
                continue
            if by_title and by_title != by_date:     # 공문 제목이 잘못 적힌 경우: 날짜로 가려 넣고 적어 둔다
                why.append(f"(참고) {doc.number} {doc.title} — 제목은 {by_title}이지만 "
                           f"날짜({doc.date:%y.%m.%d.})로 보아 {by_date} 공문으로 넣음")
            tag = f"{by_date} "
        base = f"{k:02d}. {tag}{_safe(doc.title)}"
        if _already(folder, base):
            res["skipped"] += 1
            continue
        log(f"   ↓ {doc.number} {doc.title}")
        try:
            r = save_doc(driver, doc, folder, base, homnet_pw, office, log, stop, rule.get("attach", True))
        except Exception as ex:
            r = {"pdf": False, "attach": 0, "note": f"{type(ex).__name__}: {ex}"[:120]}
            _back_to_main(driver)
        if r["pdf"]:
            res["docs"] += 1
            res["attach"] += r["attach"]
        else:
            res["failed"].append(f"{it.no} {doc.number} {doc.title[:20]} — {r['note']}")
            why.append(f"{doc.number} {doc.title} — {r['note']}")


def moumi_fetch(driver, items: list[qe.Item], root: str, year: int, reasons: dict, log=print) -> None:
    import moumi
    try:
        main, win = moumi.open_moumi(driver)
    except Exception as ex:
        for it in items:
            reasons.setdefault(id(it), []).append(f"자료집계를 열지 못함 — {ex}")
        return
    try:
        for it in items:
            word, name = MOUMI_SOURCES[(it.no, it.seq)]
            folder = qe.item_dir(root, it, create=True)
            if _already(folder, name):
                log(f"   = 이미 받음: 자료집계 '{word}'")
                continue
            log(f"▶ {it.label}: 자료집계 제출완료함에서 '{word}' ({year}년) 찾기…")
            rows = moumi.find_submitted(driver, word, year)
            hit = [r for r in rows if str(year) in r[0] or f"({str(year)[2:]}." in r[0]]
            if not hit:
                reasons.setdefault(id(it), []).append(
                    f"자료집계 제출완료함에 '{year}년 {word}' 제출 자료가 없음" + (f"(있는 것: {rows[0][0]})" if rows else ""))
                log(f"   ✗ 제출완료함에 {year}년 '{word}' 없음")
                continue
            import tempfile
            tmp = tempfile.mkdtemp(prefix="moumi_")
            title, files = moumi.download_attachments(driver, hit[0][1], tmp, log)
            xls = [f for f in files if f.lower().endswith((".xlsx", ".xls", ".xlsm"))]
            if not xls:
                reasons.setdefault(id(it), []).append(f"자료집계 '{hit[0][0]}'에 엑셀 첨부가 없음")
                shutil.rmtree(tmp, ignore_errors=True)
                continue
            dst = os.path.join(folder, name + os.path.splitext(xls[0])[1])
            shutil.move(xls[0], dst)
            shutil.rmtree(tmp, ignore_errors=True)
            log(f"   ↓ 자료집계 첨부: {os.path.basename(xls[0])}")
    finally:
        moumi.close(driver, win, main)


def fetch(driver, items: list[qe.Item], root: str, year: int, cache_dir: str, homnet_pw: str = "",
          office: str = "", log=print, stop=None, passwords=(), complex_code: str = "", basic_codes=()) -> dict:
    """items의 평가 근거 문서를 대장에서 받아 폴더링에 그림으로 넣는다. 결과 요약."""
    res = {"docs": 0, "attach": 0, "skipped": 0, "failed": [], "not_found": [], "no_ref": []}
    reasons: dict[int, list[str]] = {}
    refs_of, years = plan(items, year)
    for it in items:
        qe.item_dir(root, it, create=True)
        if (it.no, it.seq) in MOUMI_SOURCES:
            refs_of.pop(id(it), None)               # 대장 공문은 받지 않는다(취합자료 엑셀만)
            continue
        if "ledger" in DOC_RULES.get((it.no, it.seq), {}):
            refs_of.pop(id(it), None)               # 근거 번호 대신 평가년도 대장에서 제목으로 고른다
            years.add(year)
            continue
        planned = (it.no, it.seq) in WISE_SHOTS or (it.no, it.seq) in NOTE_ITEMS     # WISE 캡처·메모만 넣는 항목
        if id(it) not in refs_of and (it.basis or "").strip() and not (planned and qe.volume_of(it.part) == 4):
            res["no_ref"].append(it.label)
            reasons.setdefault(id(it), []).append("평가 근거에 문서번호(예: 264(26.2.9.))가 없어 대장에서 받을 문서가 없음")
    ledgers = {}
    if years:
        log(f"대장 목록을 읽습니다({', '.join(map(str, sorted(years)))}년)…")
        ledgers, missing = qd.load_ledgers(driver, years, cache_dir, log, stop, office)
        if missing:
            log(f"  ⚠ 대장이 없는 해: {', '.join(map(str, missing))}")
    else:
        log("평가 근거에 문서번호(예: 264(26.2.9.))가 없어 대장에서 받을 문서가 없습니다.")
    moumi_items = [it for it in items if (it.no, it.seq) in MOUMI_SOURCES]
    if moumi_items and driver is not None:
        moumi_fetch(driver, moumi_items, root, year, reasons, log)
    for it in items:
        rule = DOC_RULES.get((it.no, it.seq), {})
        if "ledger" in rule:
            ledger_docs(driver, it, rule, ledgers.get(year, []), root, homnet_pw, office, reasons, res, log, stop)
            continue
        refs = refs_of.get(id(it), [])
        if not refs:
            continue
        why = reasons.setdefault(id(it), [])
        folder = qe.item_dir(root, it, create=True)
        log(f"▶ {it.label}  ({len(refs)}건)")
        # 매월 보내는 같은 제목의 문서(MONTHLY_MIN건 이상)는 하나씩 받지 않고, 대장을 그 제목으로 검색한
        # 목록(등록일자가 보이게)을 화면 그대로 찍어 넣는다 — LIST_ROWS(30)줄이 넘으면 끊어서 여러 장
        in_list = set()
        list_only = (it.no == "1-2" or (it.no, it.seq) in LIST_ALL) and qe.volume_of(it.part) == 4     # 4권 1-2: 대장 검색 목록만(한글파일 예시처럼)
        for k0, kw, yr, nums in monthly_groups(refs, ledgers, 1 if list_only else 0):
            if stop is not None and stop.is_set():
                log("멈췄습니다.")
                return res
            in_list |= nums
            base = f"{k0:02d}. 홈넷 {_safe(kw, 30)} 화면 캡처 ({yr})"
            if _already(folder, base):
                res["skipped"] += 1
                log(f"   = 이미 찍음: 대장 '{kw}' 목록 ({yr}년)")
                continue
            log(f"   📷 대장을 '{kw}'(으)로 검색한 {yr}년 목록을 찍습니다({len(nums)}건 근거)…")
            try:
                n, note = list_shots(driver, kw, yr, folder, base, log, (it.no, it.seq) not in LIST_ALL)
            except Exception as ex:
                n, note = 0, f"{type(ex).__name__}: {ex}"[:120]
                _back_to_main(driver)
            if n:
                res["lists"] = res.get("lists", 0) + n
                log(f"     목록 그림 {n}장")
            else:                                # 하나씩 받지 않는다(사용자 2026-11-20) — 다시 폴더링하면 다시 찍는다
                why.append(f"대장 '{kw}' 검색 목록({yr}년)을 찍지 못함 — {note} (다시 폴더링하면 다시 찍습니다)")
                log(f"     ✗ 목록을 찍지 못함: {note}")
        seen = set()
        for k, ref in enumerate(refs, 1):
            if stop is not None and stop.is_set():
                log("멈췄습니다.")
                return res
            doc = find_doc(ledgers, ref)
            if doc is not None and doc.number in in_list:
                continue
            if doc is None:
                res["not_found"].append(f"{it.no} {ref.raw}")
                why.append(f"{ref.raw} — 대장에서 그 번호의 문서를 찾지 못함")
                log(f"   ✗ 대장에서 못 찾음: {ref.raw}")
                continue
            if doc.number in seen:
                continue
            seen.add(doc.number)
            rule = DOC_RULES.get((it.no, it.seq), {})
            if rule.get("title") and not rule["title"](doc.title):
                log(f"   - 넣지 않음(이 항목은 결과 공문만): {doc.title}")
                continue
            tag = ""
            if rule.get("half"):
                by_date, by_title = rule["half"](doc)
                if by_date and by_title and by_title != by_date:
                    why.append(f"(참고) {doc.number} {doc.title} — 제목은 {by_title}이지만 날짜({doc.date:%y.%m.%d.})로 보아 {by_date} 공문")
                tag = f"{by_date} " if by_date else ""
            base = f"{k:02d}. {tag}{_safe(doc.title)}"
            if _already(folder, base):
                res["skipped"] += 1
                log(f"   = 이미 받음: {doc.title}")
                continue
            log(f"   ↓ {doc.number} {doc.title}")
            try:
                r = save_doc(driver, doc, folder, base, homnet_pw, office, log, stop, rule.get("attach", True))
            except Exception as ex:
                r = {"pdf": False, "attach": 0, "note": f"{type(ex).__name__}: {ex}"[:120]}
                try:
                    import homnet
                    driver.switch_to.window(homnet.main_window(driver))
                    driver.switch_to.default_content()
                except Exception:
                    pass
            if r["pdf"]:
                res["docs"] += 1
                res["attach"] += r["attach"]
                log("     본문" + (f" + 첨부 {r['attach']}개" if r["attach"] else ""))
            else:
                res["failed"].append(f"{it.no} {doc.number} {doc.title[:20]} — {r['note']}")
                why.append(f"{doc.number} {doc.title} — {r['note']}")
                log(f"     ✗ {r['note']}")
    log("받은 파일을 쪽 그림으로 바꾸고, WISE 화면을 캡처합니다…")
    if _stopped(stop):
        log("멈췄습니다.")
        return res
    res.update(finish(items, root, reasons, passwords, log, stop, year, complex_code, _center_name(office),
                      basic_codes))
    return res
