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


def find_notice(driver, round_no: int, log) -> Notice:
    """기록물등록대장에서 N차 결과 통보를 찾는다. 목록만 읽고 아무것도 바꾸지 않는다."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC

    import homnet_draft as hd
    driver.switch_to.window(driver.window_handles[0])
    driver.switch_to.default_content()
    log(f"기록물등록대장에서 '{NOTICE_TITLE}({round_no}차' 를 찾습니다...")
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
    driver.execute_script("document.getElementById('searchType').value = 'title';"
                          "document.getElementById('editSearchCondition').value = arguments[0]; DoSearch();",
                          f"{NOTICE_TITLE}({round_no}차")
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
