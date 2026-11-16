"""전자결재 → 대장관리 → 기록물등록대장에서 '주택소유 전산검색 결과 통보(N차 …)'를 찾는다(읽기만).

목록 한 줄 예(GetItemText 열):
  … | 접수 | 20260903132534(등록일자) | 광주양림2관리소-1685(등록번호) |
  주택소유 전산검색 결과 통보(34차, ~ 26. 8. 25. 요청건) | 담당자 | 주거복지실/본사/본사 |
  20260903090901(시행일자) | 편철 | 결재권자 | | 주거복지실-2044(발신 문서번호)
열 순서는 화면 설정에 따라 바뀔 수 있어 값의 모양으로 고른다.
"""
import datetime as dt
import json
import re
import time
from dataclasses import dataclass

NOTICE_TITLE = "주택소유 전산검색 결과 통보"
MENU_ID = "menu_tenon_register"          # 대장관리 → 기록물등록대장

_JS_ROWS = r"""
var o = window.DocumentList, rows = [];
if (!o) return null;
for (var i = 0; i < o.GetListCount(); i++) {
  var txt = []; for (var c = 0; c < 20; c++) { try { txt.push(String(o.GetItemText(i, c))); } catch (e) { break; } }
  rows.push({text: txt, userdata: String(o.GetUserData(i) || '')});
}
return JSON.stringify(rows);
"""


class LedgerError(Exception):
    """사용자에게 보여줄 수 있는 조회 실패."""


@dataclass
class Notice:
    round_no: int
    title: str
    doc_number: str            # 발신 문서번호(예: 주거복지실-2044)
    enforce_date: dt.date      # 시행일자 = 통보일
    request_date: dt.date | None   # 제목의 '~ 26. 8. 25. 요청건'


def _date14(s: str) -> dt.date | None:
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})\d{6}", s.strip())
    return dt.date(int(m[1]), int(m[2]), int(m[3])) if m else None


def _request_date(title: str) -> dt.date | None:
    m = re.search(r"~\s*(\d{2,4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*요청", title)
    if not m:
        return None
    y = int(m[1])
    return dt.date(y + 2000 if y < 100 else y, int(m[2]), int(m[3]))


def pick_notice(rows: list[dict], round_no: int) -> Notice | None:
    """검색 결과 줄들에서 N차 결과 통보를 고른다. '요청건' 문서를 먼저, 같으면 최신(위쪽)."""
    pat = re.compile(rf"{re.escape(NOTICE_TITLE)}\s*\(\s*{round_no}\s*차\s*[,)]")
    found = []
    for row in rows:
        texts = [t.strip() for t in row.get("text", []) if t and t.strip() not in ("null", "-1")]
        title = next((t for t in texts if pat.search(t)), "")
        if not title:
            continue
        ud = row.get("userdata", "")
        m = re.search(r"<CREATE_REG_DATE>(\d{14})</CREATE_REG_DATE>", ud)
        reg = m[1] if m else ""
        stamps = [t for t in texts if re.fullmatch(r"\d{14}", t)]
        enforce = next((t for t in stamps if t != reg), stamps[-1] if stamps else "")
        nums = [t for t in texts if re.fullmatch(r"[^\s|]+-\d+", t)]
        if not nums or not enforce:
            continue
        found.append(Notice(round_no, title, nums[-1], _date14(enforce), _request_date(title)))
    found.sort(key=lambda n: n.request_date is None)      # 요청건(요청일 있음) 먼저, 순서는 유지
    return found[0] if found else None


def open_register(driver) -> None:
    """홈넷 본 창에서 전자결재 → 대장관리 → 기록물등록대장을 열고 목록 화면(contentview) 안으로 들어간다."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC

    import homnet
    import homnet_draft as hd
    driver.switch_to.window(homnet.main_window(driver))
    driver.switch_to.default_content()
    driver.get(hd.DRAFT_URL)
    hd._wait(driver, EC.frame_to_be_available_and_switch_to_it((By.ID, "linkageIframe")), 30,
             "전자결재 화면이 열리지 않았습니다.")
    menu = hd._wait(driver, lambda d: d.find_element(By.ID, MENU_ID), 20,
                    "'기록물등록대장' 메뉴를 찾지 못했습니다.")
    driver.execute_script("(arguments[0].querySelector('div,span')||arguments[0]).click();", menu)
    time.sleep(2)
    hd._wait(driver, EC.frame_to_be_available_and_switch_to_it((By.ID, "contentview")), 30,
             "기록물등록대장 화면이 열리지 않았습니다.")
    hd._wait(driver, lambda d: d.execute_script(
        "return !!(window.DocumentList && document.getElementById('editSearchCondition') && window.DoSearch)"),
        30, "기록물등록대장 검색칸이 준비되지 않았습니다.")
    time.sleep(1)


_JS_SELECT_YEAR = r"""
var o = window.CreateYearCombo, want = String(arguments[0]), ids = [];
if (!o) return {ok: false, ids: ids};
for (var i = 0; i < o.GetItemCount(); i++) ids.push(String(o.GetID(i)));
var idx = ids.indexOf(want);
if (idx < 0) return {ok: false, ids: ids};
if (o.GetCurSel() !== idx) { o.SetCurSel(idx); CreateYearCombo_changed(); }   // 바꾼 뒤 목록을 다시 읽는다
return {ok: true, ids: ids};
"""


def select_year(driver, year: int | str) -> None:
    """기록물등록대장의 생산연도를 고른다(open_register 뒤, contentview 안에서). 없는 해면 LedgerError."""
    res = driver.execute_script(_JS_SELECT_YEAR, str(year)) or {}
    if not res.get("ok"):
        have = res.get("ids") or []
        raise LedgerError(f"기록물등록대장에 {year}년 대장이 없습니다."
                          + (f" (고를 수 있는 해: {have[-1]}～{have[0]})" if have else ""))
    end = time.time() + 15                # 그 해 목록이 다 그려질 때까지
    while time.time() < end:
        time.sleep(0.7)
        try:
            if str(driver.execute_script("return String(window.currentLedgerYear)")) == str(year):
                break
        except Exception:
            pass
    time.sleep(1.5)


def list_rows(driver) -> list[dict]:
    return json.loads(driver.execute_script(_JS_ROWS) or "[]")


def total_pages(driver) -> int:
    try:
        return int(driver.execute_script("return parseInt(window.totalPage, 10) || 1;") or 1)
    except Exception:
        return 1


def go_page(driver, page: int, words: str = "") -> list[dict]:
    """기록물등록대장 목록의 page쪽(1부터, 한 쪽 50줄)을 연다. 검색어가 있으면 그 검색 결과의 page쪽.
    그 쪽의 줄들을 돌려준다."""
    before = [r.get("text") for r in list_rows(driver)[:2]]
    driver.execute_script("document.getElementById('searchType').value = 'title';"
                          "document.getElementById('editSearchCondition').value = arguments[0];"
                          "searchMode = 1; search(arguments[1], arguments[1]);", words, int(page))
    end, rows = time.time() + 20, []
    while time.time() < end:
        time.sleep(0.8)
        try:
            rows = list_rows(driver)
        except Exception:
            continue
        if rows and ([r.get("text") for r in rows[:2]] != before or page == 1):
            break
    time.sleep(1)
    return list_rows(driver)


def search_register(driver, words: str) -> None:
    """기록물등록대장 목록을 제목으로 검색한다(open_register 뒤, contentview 안에서)."""
    driver.execute_script("document.getElementById('searchType').value = 'title';"
                          "document.getElementById('editSearchCondition').value = arguments[0]; DoSearch();",
                          words)


def find_notice(driver, round_no: int, log) -> Notice:
    """기록물등록대장에서 N차 결과 통보를 찾는다. 목록만 읽고 아무것도 바꾸지 않는다."""
    log(f"기록물등록대장에서 '{NOTICE_TITLE}({round_no}차' 를 찾습니다...")
    open_register(driver)
    search_register(driver, f"{NOTICE_TITLE}({round_no}차")
    notice, end = None, time.time() + 20
    while time.time() < end:
        time.sleep(1)
        rows = json.loads(driver.execute_script(_JS_ROWS) or "[]")
        notice = pick_notice(rows, round_no)
        if notice:
            break
    driver.switch_to.default_content()
    if not notice:
        raise LedgerError(f"기록물등록대장(올해)에서 '{NOTICE_TITLE}({round_no}차…' 문서를 찾지 못했습니다.")
    log(f"✅ {round_no}차 결과 통보: {notice.doc_number}, 통보일 {notice.enforce_date}, "
        f"요청일 {notice.request_date or '-'}")
    return notice


REVIEW_TITLE = "입주자격심사 결과"


@dataclass
class Review:
    round_no: int
    title: str
    doc_number: str            # 등록번호(예: 광주양림2관리소-1899)
    renewal_month: dt.date     # 제목의 갱신월(그달 1일)


def pick_review(rows: list[dict], round_no: int) -> Review | None:
    """검색 결과 줄들에서 '입주자격심사 결과(2026년 12월 갱신, N차)'를 고른다. 같으면 최신(위쪽)."""
    pat = re.compile(rf"{REVIEW_TITLE}\s*\(\s*(\d{{4}})년\s*(\d{{1,2}})월\s*갱신\s*,\s*{round_no}\s*차\s*[,)]")
    for row in rows:
        texts = [t.strip() for t in row.get("text", []) if t and t.strip() not in ("null", "-1")]
        title = next((t for t in texts if pat.search(t)), "")
        if not title:
            continue
        m = pat.search(title)
        nums = [t for t in texts if re.fullmatch(r"[^\s|]+-\d+", t)]
        return Review(round_no, title, nums[0] if nums else "", dt.date(int(m[1]), int(m[2]), 1))
    return None


def find_review(driver, round_no: int, log) -> Review:
    """기록물등록대장에서 N차 입주자격심사 결과를 찾는다. 목록만 읽고 아무것도 바꾸지 않는다."""
    log(f"기록물등록대장에서 '{REVIEW_TITLE}(… {round_no}차)' 를 찾습니다...")
    open_register(driver)
    search_register(driver, f"갱신, {round_no}차")
    review, end = None, time.time() + 20
    while time.time() < end:
        time.sleep(1)
        rows = json.loads(driver.execute_script(_JS_ROWS) or "[]")
        review = pick_review(rows, round_no)
        if review:
            break
    driver.switch_to.default_content()
    if not review:
        raise LedgerError(f"기록물등록대장(올해)에서 '{REVIEW_TITLE}(… {round_no}차)' 문서를 찾지 못했습니다.")
    log(f"✅ {round_no}차 입주자격심사 결과: {review.doc_number}, 갱신월 {review.renewal_month:%Y-%m}")
    return review


def year_rows(driver, year: int, log=print, stop=None) -> list[dict]:
    """기록물등록대장 year년 목록을 처음부터 끝까지 읽는다(한 쪽 50줄). 읽기만 한다.
    그 해 대장이 없으면 LedgerError. stop(threading.Event)이 서면 그때까지 읽은 줄을 돌려준다."""
    open_register(driver)
    select_year(driver, year)
    pages = total_pages(driver)
    log(f"  {year}년 기록물등록대장 {pages}쪽을 읽습니다...")
    rows = list_rows(driver)
    for page in range(2, pages + 1):
        if stop is not None and stop.is_set():
            break
        rows += go_page(driver, page, "")
        if page % 5 == 0 or page == pages:
            log(f"  {year}년 대장 {page}/{pages}쪽")
    driver.switch_to.default_content()
    return rows
