"""홈넷 웹기안기(전자결재 → 문서작성 → 표준기안문) 자동 작성 — 상신은 하지 않는다.

LeavePromotion homnet_draft.py에서 실제 DOM으로 검증한 구조와 처리 방법을 그대로 쓴다.
- 홈넷 `gwLinkageGwMenus.jstl?target=draft` → iframe #linkageIframe(gw SSO 브리지)
  → iframe #contentview(양식함). 서식 '표준기안문'을 누르면 새 창 '기안신규'
  (formfolder_dochandler.jsp)가 열리고, 결재정보 창(nsancdocinfodlg.jsp)이 자동으로 뜬다.
- 결재정보 창: 제목 #editTitle, 공개여부 ComboPublicType, 비공개 호 #OpeLevel1~8,
  열람등급 ComboSecurity, 결재선 설정(btnSelSancline_onclick), 편철 설정(btnSelCabinet_onclick),
  확인 #nbutton_BtnSubmit-button.
- 결재선 창(nsanclinedlg)의 수신자 탭: 콤보 RecvCombo 항목 ID '3'이 수기입력,
  #deptNameEdit에 쓰고 inputHandRecvHandler()로 추가.
- 기안신규 창 본문은 웹한글 기안기(iframe#WordController_* 안의 window.HwpCtrl).
  #nbutton_BtnSancSend-button(결재올림)은 절대 누르지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

DRAFT_URL = "https://homnet.kohom.or.kr/linkage/direct/gwLinkageGwMenus.jstl?target=draft"
FORM_NAME = "표준기안문"

PUBLIC_TYPES = ["공개", "비공개", "부분공개"]          # ComboPublicType 인덱스 1/2/3
SECURITY_GRADES = {"1등급[결재선+문서담당자열람]": "1", "2등급[부서열람]": "2",
                   "3등급[전체열람]": "3"}


class DraftError(Exception):
    """사용자에게 보여줄 수 있는 작성 실패."""


@dataclass
class DocInfo:
    """결재정보 창에 넣을 값."""
    title: str
    public_type: str = "비공개"           # 공개 / 비공개 / 부분공개
    closed_grades: list = field(default_factory=lambda: [6])   # 비공개 호(1~8)
    public_desc: str = ""                 # 부분공개 시 공개제한부분
    security: str = "1"                   # 열람등급 ID (1/2/3)
    binder: str = ""                      # 편철(기록물철명). 비우면 기본값 그대로


# ---------------- 공통 ----------------

def _wait(driver, cond, timeout=20, msg="화면 대기 시간 초과"):
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait
    try:
        return WebDriverWait(driver, timeout, poll_frequency=0.3).until(cond)
    except TimeoutException:
        raise DraftError(msg) from None


def _switch_new_window(driver, before: set, title_part: str = "", timeout=20,
                       url_part: str = "") -> str:
    """새로 뜬 창(제목에 title_part 또는 주소에 url_part 포함)으로 전환하고 핸들을 돌려준다."""
    def found(d):
        for h in set(d.window_handles) - before:
            d.switch_to.window(h)
            title, url = d.title or "", d.current_url or ""
            if ((not title_part and not url_part)
                    or (title_part and title_part in title)
                    or (url_part and url_part in url)):
                return h
        return False
    return _wait(driver, found, timeout, f"'{title_part or '새'}' 창이 열리지 않았습니다.")


def _click(driver, css: str, timeout=15):
    from selenium.webdriver.common.by import By
    el = _wait(driver, lambda d: d.find_element(By.CSS_SELECTOR, css), timeout,
               f"버튼을 찾지 못했습니다: {css}")
    driver.execute_script("arguments[0].click();", el)
    return el


def _accept_alert(driver) -> str:
    try:
        a = driver.switch_to.alert
        t = a.text
        a.accept()
        return t
    except Exception:
        return ""


def _find_window(driver, url_part: str) -> str | None:
    for h in driver.window_handles:
        driver.switch_to.window(h)
        if url_part in (driver.current_url or ""):
            return h
    return None


# ---------------- 1. 표준기안문 열기 ----------------

def open_form(driver, log) -> str:
    """전자결재 → 문서작성(양식함)에서 '표준기안문'을 열어 기안신규 창 핸들을 돌려준다."""
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    driver.switch_to.window(driver.window_handles[0])
    driver.switch_to.default_content()
    log("전자결재 → 문서작성(양식함)으로 이동합니다...")
    driver.get(DRAFT_URL)
    _wait(driver, EC.frame_to_be_available_and_switch_to_it((By.ID, "linkageIframe")), 30,
          "전자결재 화면(linkageIframe)이 열리지 않았습니다.")
    _wait(driver, EC.frame_to_be_available_and_switch_to_it((By.ID, "contentview")), 30,
          "양식함 화면(contentview)이 열리지 않았습니다.")

    xpath = (f"//td[contains(@class,'yui-dt-col-formName')]"
             f"//div[normalize-space(text())='{FORM_NAME}']")
    # 목록은 화면이 뜬 뒤 비동기로 채워진다. 먼저 충분히 기다리고, 그래도 없을 때만 검색.
    try:
        WebDriverWait(driver, 15, 0.3).until(lambda d: d.find_elements(By.XPATH, xpath))
    except TimeoutException:
        log(f"  목록에 '{FORM_NAME}'이 없어 서식명칭으로 검색합니다.")
        driver.execute_script(
            "document.getElementById('searchtitle').value = arguments[0]; ListNav_click();",
            FORM_NAME)
        _wait(driver, lambda d: d.find_elements(By.XPATH, xpath), 20,
              f"양식함에서 '{FORM_NAME}'을 찾지 못했습니다.")
    time.sleep(1)   # 목록 렌더링(이벤트 연결) 마무리 대기

    # 1) 양식함이 [열기]에 쓰는 함수(DoOpen)를 직접 부른다 — 마우스 클릭보다 확실하다.
    before = set(driver.window_handles)
    idx = driver.execute_script(_JS_OPEN_FORM, FORM_NAME)
    if idx is not None and idx >= 0:
        try:
            handle = _switch_new_window(driver, before, timeout=20, url_part="formfolder_dochandler")
            log(f"✅ '{FORM_NAME}' 기안 창이 열렸습니다.")
            return handle
        except DraftError:
            driver.switch_to.window(driver.window_handles[0])
            driver.switch_to.default_content()
            driver.switch_to.frame("linkageIframe")
            driver.switch_to.frame("contentview")
            log(f"  '{FORM_NAME}' 열기 재시도 (DoOpen 실패)")

    # 2) 안 되면 실제 마우스로 누른다.
    before = set(driver.window_handles)
    for how in ("click", "dblclick", "open", "click", "dblclick"):
        _click_form(driver, xpath, how)
        try:
            handle = _switch_new_window(driver, before, timeout=15,
                                        url_part="formfolder_dochandler")
            log(f"✅ '{FORM_NAME}' 기안 창이 열렸습니다.")
            return handle
        except DraftError:
            driver.switch_to.window(driver.window_handles[0])
            driver.switch_to.default_content()
            driver.switch_to.frame("linkageIframe")
            driver.switch_to.frame("contentview")
            log(f"  '{FORM_NAME}' 열기 재시도 ({how} 실패)")
    raise DraftError(f"'{FORM_NAME}'을 눌렀지만 기안 창이 열리지 않았습니다. "
                     "팝업 차단 여부를 확인하세요.")


_JS_OPEN_FORM = r"""
var name = arguments[0], cells = document.querySelectorAll('td.yui-dt-col-formName');
if (!window.DocumentList || typeof DoOpen !== 'function') return -2;
for (var i = 0; i < cells.length; i++) {
  if ((cells[i].innerText || '').trim() === name) {
    DocumentList.SetSelectedIndex(i);
    if (DocumentList.GetSelectedIndex() !== i) return -3;
    DoOpen();
    return i;
  }
}
return -1;
"""


def _click_form(driver, xpath: str, how: str) -> None:
    """양식 칸을 실제 마우스로 누른다. how: click / dblclick / open(선택 후 [열기])."""
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    cell = driver.find_element(By.XPATH, xpath)       # 매번 새로 찾는다(목록 갱신 대비)
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cell)
    actions = ActionChains(driver).move_to_element(cell)
    if how == "dblclick":
        actions.double_click(cell).perform()
    else:
        actions.click(cell).perform()
    if how == "open":
        time.sleep(0.3)
        ActionChains(driver).click(
            driver.find_element(By.ID, "nbutton_BtnOpen-button")).perform()


# ---------------- 2. 결재정보 ----------------

DOCINFO_URL = "nsancdocinfodlg"
SANCLINE_URL = "nsanclinedlg"
BINDER_URL = "spo_select_arrange_binder"
SEL_SANCLINE_BTN = "input[onclick^='btnSelSancline_onclick']"   # #imgSelSancLine
SEL_BINDER_BTN = "input[onclick^='btnSelCabinet_onclick']"      # #imgSelCabinet

_JS_DOCINFO = """
var a = arguments[0];
var t = document.getElementById('editTitle'); t.value = a.title;
ComboPublicType.SetCurSel(a.publicIdx); ComboPublicType_changed();
for (var i = 1; i <= 8; i++) {
  var c = document.getElementById('OpeLevel' + i);
  if (c && !c.disabled) c.checked = a.grades.indexOf(i) >= 0;
}
var d = document.getElementById('editPublicDesc');
if (d && !d.readOnly) d.value = a.desc;
var s = ComboSecurity.FindItemByID(a.security);
if (s >= 0) { ComboSecurity.SetCurSel(s); ComboSecurity_changed(); }
return [ComboPublicType.GetCurSelItemText(), ComboSecurity.GetCurSelItemText(),
        (document.getElementById('editCabinetName') || {}).value || ''];
"""


def find_or_open_docinfo(driver, draft_handle: str, log, wait_auto: float = 10) -> str:
    """서식을 열면 결재정보 창이 자동으로 뜬다. 그 창을 찾고, 없으면 [결재정보]로 연다."""
    end = time.time() + wait_auto
    while time.time() < end:
        h = _find_window(driver, DOCINFO_URL)
        if h:
            log("결재정보 창이 열렸습니다.")
            return h
        time.sleep(0.5)
    driver.switch_to.window(draft_handle)
    driver.switch_to.default_content()
    before = set(driver.window_handles)
    _click(driver, "#nbutton_BtnInfo-button")
    return _switch_new_window(driver, before, "결재정보", 20, url_part=DOCINFO_URL)


# 안이 둘 이상이면 결재정보 창 맨 위에 '안번호 | 제목' 목록이 생기고 1안 줄이 선택돼 있다.
# 제목·수신자는 선택된 안에 들어가므로 먼저 그 안의 줄을 누른다.
_JS_SUBCASE_ROW = r"""
var want = arguments[0] + '안', rows = document.querySelectorAll('tr');
for (var i = 0; i < rows.length; i++) {
  var c = rows[i].cells;
  if (c && c.length >= 2 && (c[0].innerText || '').replace(/\s+/g, '') === want) {
    return [rows[i], (c[1].innerText || '').trim(), /selected/.test(rows[i].className)];
  }
}
return null;
"""


def select_docinfo_subcase(driver, subcase: int, log) -> None:
    """결재정보 창의 안번호 목록에서 subcase(0이면 1안) 줄을 선택한다."""
    from selenium.webdriver.common.action_chains import ActionChains
    found = driver.execute_script(_JS_SUBCASE_ROW, subcase + 1)
    if not found:
        raise DraftError(f"결재정보 창에서 {subcase + 1}안 줄을 찾지 못했습니다.")
    row = found[0]
    if not found[2]:
        cell = row.find_elements("css selector", "td")[1]
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", cell)
        ActionChains(driver).move_to_element(cell).click(cell).perform()
        _wait(driver, lambda d: (d.execute_script(_JS_SUBCASE_ROW, subcase + 1) or [0, 0, False])[2], 10,
              f"결재정보 창에서 {subcase + 1}안을 선택하지 못했습니다.")
        time.sleep(0.5)
    log(f"  결재정보: {subcase + 1}안 선택")


def fill_docinfo(driver, handle: str, info: DocInfo, log, subcase: int = 0) -> None:
    """결재정보 창에 제목·공개여부·비공개 호·열람등급을 채운다. subcase: 채울 안(0이면 1안)."""
    from selenium.webdriver.common.by import By
    driver.switch_to.window(handle)
    _wait(driver, lambda d: d.find_element(By.ID, "editTitle"), 20, "결재정보 창을 읽지 못했습니다.")
    _wait(driver, lambda d: d.execute_script(
        "return !!window.ComboPublicType && !!window.ComboSecurity"),
        20, "결재정보 창이 준비되지 않았습니다.")
    if subcase:
        select_docinfo_subcase(driver, subcase, log)
    idx = PUBLIC_TYPES.index(info.public_type) + 1
    grades = info.closed_grades if info.public_type != "공개" else []
    pub, sec, binder = driver.execute_script(_JS_DOCINFO, {
        "title": info.title, "publicIdx": idx, "grades": grades,
        "desc": info.public_desc, "security": info.security})
    log(f"✅ 결재정보: 제목 「{info.title}」 · 공개여부({pub}"
        + (f" {','.join(f'{g}호' for g in grades)}" if grades else "") + f") · 열람등급({sec})")
    if binder:
        log(f"  현재 편철: {binder}")


_JS_RECV_ROWS = r"""
var out = [], rows = document.querySelectorAll('#recvList .yui-dt-data tr');
for (var i = 0; i < rows.length; i++) { out.push((rows[i].innerText || '').replace(/\s+/g, ' ').trim()); }
return out;
"""


def hand_receiver_text(receiver: str) -> str:
    """수기입력 칸은 쉼표를 받지 않으므로 가운뎃점으로 바꾼다."""
    return " ".join(receiver.replace(",", "·").split())


def _save_probe(driver, name: str) -> None:
    """자동화가 막힌 화면을 진단용으로 logs에 남긴다."""
    try:
        import paths
        with open(os.path.join(paths.sub_dir("logs"), name), "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    except Exception:
        pass


def upload_receivers(driver, sancline: str, path: str, log) -> None:
    """수신자 탭 '수기입력'의 [업로드]와 같은 일을 한다.

    [업로드](uploadExcel)는 수기입력일 때 숨은 파일 칸 #attachFileObj를 누르고, 파일을 고르면
    form1이 서버로 올라간 뒤 SendFileSuccess → 엑셀 sheet1 첫 열을 ';'로 이어 수기입력에 추가한다.
    파일 칸에 경로를 직접 넣으므로 윈도 파일 창은 뜨지 않는다.
    """
    from selenium.webdriver.common.by import By
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise DraftError(f"수신자 엑셀 파일이 없습니다: {path}")
    # 원본 대신 명단만 담은 새 엑셀을 올린다(문서보안으로 서버가 원본을 못 읽는 경우 대비)
    original = os.path.basename(path)
    try:
        import paths
        import roster
        path = roster.clean_upload_copy(path, paths.sub_dir("output", "upload"))
    except Exception as ex:
        raise DraftError(f"수신자 엑셀을 읽지 못했습니다: {ex}") from None
    driver.switch_to.window(sancline)
    driver.switch_to.default_content()
    # 수신자는 엑셀에 있는 사람만 — 이 안에 이미 들어 있던 수신자는 먼저 지운다([일괄삭제]).
    if driver.execute_script("return recvList.GetListCount();") > 0:
        driver.execute_script("BtnRecvRemoveAll_onclick();")
        end = time.time() + 10
        while time.time() < end and driver.execute_script("return recvList.GetListCount();") > 0:
            _accept_alert(driver)
            time.sleep(0.3)
        left = driver.execute_script("return recvList.GetListCount();")
        if left:
            raise DraftError(f"기존 수신자 {left}명을 지우지 못했습니다.")
        log("  기존 수신자를 지웠습니다(엑셀 명단만 넣음).")
    n0 = driver.execute_script("return recvList.GetListCount();")
    boxes = driver.find_elements(By.ID, "attachFileObj")
    if not boxes:
        _save_probe(driver, "recv_upload_probe.html")
        raise DraftError("수기입력 [업로드]의 파일 칸(attachFileObj)을 찾지 못했습니다.")
    boxes[0].send_keys(path)
    log(f"  수신자 엑셀 올림: {original} (명단만 새 파일로 옮겨 올림)")

    end = time.time() + 30
    n1 = n0
    while time.time() < end:
        msg = _accept_alert(driver)
        if msg:
            log(f"  업로드 메시지: {msg}")
        n1 = driver.execute_script("return recvList.GetListCount();")
        if n1 > n0:
            break
        time.sleep(0.5)
    if n1 <= n0:
        _save_probe(driver, "recv_upload_probe.html")
        raise DraftError("엑셀을 넣었지만 수신자 목록이 늘지 않았습니다. "
                         "홈넷 [샘플 다운로드] 양식에 맞는 파일인지 확인하세요.")
    # 명단이 다 들어올 때까지(수가 2초 동안 그대로일 때까지) 기다린다
    stable_since, end = time.time(), time.time() + 30
    while time.time() < end and time.time() - stable_since < 2:
        time.sleep(0.3)
        _accept_alert(driver)
        n = driver.execute_script("return recvList.GetListCount();")
        if n != n1:
            n1, stable_since = n, time.time()
    log(f"✅ 수신자(엑셀 업로드): {n1 - n0}명")


# 안이 둘 이상이면 결재선 창 수신자 목록 위에 안 선택 콤보(ComboSubcase)가 생긴다.
# 고르지 않으면 수신자가 1안에 들어가 "내부결재 문서는 1안에만 작성가능" 오류가 난다.
_JS_SUBCASE = r"""
var i = arguments[0];
if (!window.ComboSubcase) return [-1, -1, 'no combo'];
ComboSubcase.SetCurSel(i);
var fn = ['ComboSubcase_changed', 'ComboSubcase_onchange', 'OnChangeSubcase', 'ChangeSubCase']
  .filter(function (n) { return typeof window[n] === 'function'; })[0];
if (fn) window[fn]();
return [i, typeof m_nCurSubCase === 'undefined' ? -1 : Number(m_nCurSubCase), fn || 'no handler'];
"""


def set_receiver(driver, docinfo: str, receiver: str, log, upload_path: str = "",
                 subcase: int = 0) -> None:
    """결재선 창 → 수신자 탭 → '수기입력'으로 수신자를 넣고 [확인]한다.

    upload_path가 있으면 한 줄 입력 대신 [업로드]로 수신자 엑셀을 올린다.
    subcase: 수신자를 넣을 안(0이면 1안).
    """
    from selenium.webdriver.common.by import By
    text = hand_receiver_text(receiver)
    driver.switch_to.window(docinfo)
    before = set(driver.window_handles)
    _click(driver, SEL_SANCLINE_BTN)
    win = _switch_new_window(driver, before, timeout=20, url_part=SANCLINE_URL)
    _wait(driver, lambda d: d.execute_script(
        "return !!(window.recvList && window.RecvCombo)"), 30, "결재선 창이 준비되지 않았습니다.")
    time.sleep(1)
    tab = driver.find_elements(By.CSS_SELECTOR, "a[href='#yuiRecvList']")
    if tab:
        driver.execute_script("arguments[0].click();", tab[0])
        time.sleep(0.5)
    if subcase:
        sel, cur, how = driver.execute_script(_JS_SUBCASE, subcase)
        time.sleep(0.5)
        if cur != subcase:
            raise DraftError(f"결재선 창에서 {subcase + 1}안을 고르지 못했습니다({how}, 현재 {cur + 1}안).")
        log(f"  수신자 목록: {subcase + 1}안 선택")
    driver.execute_script(
        "var i = RecvCombo.FindItemByID ? RecvCombo.FindItemByID('3') : -1;"
        "RecvCombo.SetCurSel(i >= 0 ? i : 2); RecvCombo_changed();")
    _wait(driver, lambda d: d.find_element(By.ID, "deptNameEdit").is_displayed(), 10,
          "수신자 '수기입력' 칸이 열리지 않았습니다.")

    rows = driver.execute_script(_JS_RECV_ROWS) or []
    if upload_path:
        upload_receivers(driver, win, upload_path, log)
    elif any(text in r for r in rows):
        log(f"  - 수신자 '{text}': 이미 있음")
    else:
        n0 = driver.execute_script("return recvList.GetListCount();")
        driver.execute_script(
            "document.getElementById('deptNameEdit').value = arguments[0]; inputHandRecvHandler();",
            text)
        time.sleep(0.6)
        msg = _accept_alert(driver)
        n1 = driver.execute_script("return recvList.GetListCount();")
        if n1 <= n0:
            raise DraftError(f"수신자 '{text}'를 넣지 못했습니다{(' (' + msg + ')') if msg else ''}.")
        log(f"✅ 수신자(수기입력): {text}")

    # 결재정보 창에 반영됐는지 볼 표본: 목록 첫 줄에서 '구분'(외부 등)을 뺀 수신자 이름
    rows = driver.execute_script(_JS_RECV_ROWS) or []
    sample = rows[0].split(" ", 1)[-1] if rows else ""
    time.sleep(0.5)
    _click(driver, "#nbutton_BtnSubmit-button")
    end = time.time() + 20
    while time.time() < end and win in driver.window_handles:
        msg = _accept_alert(driver)
        if msg:
            log(f"  결재선 창 메시지: {msg}")
        time.sleep(0.5)
    if win in driver.window_handles:
        raise DraftError("결재선 창이 닫히지 않았습니다. 화면의 안내 메시지를 확인하세요.")
    log("✅ 결재선(수신자) [확인]")
    driver.switch_to.window(docinfo)
    if sample:
        try:
            _wait(driver, lambda d: sample in " ".join(
                (d.execute_script("return document.body.innerText") or "").split()), 15, "")
        except DraftError:
            raise DraftError("결재선 [확인] 뒤 결재정보 창에 수신자가 보이지 않습니다.") from None
        log("  결재정보 창에 수신자 반영 확인")


def _close_sancline(driver, docinfo: str) -> None:
    """자동 입력이 실패해 남은 결재선 창을 닫는다(바꾼 내용 버림). 사람이 처음부터 다시 하도록."""
    try:
        _accept_alert(driver)
        h = _find_window(driver, SANCLINE_URL)
        if h:
            driver.switch_to.window(h)
            _accept_alert(driver)
            driver.close()
    except Exception:
        pass
    driver.switch_to.window(docinfo)


def _cabinet(driver) -> str:
    return driver.execute_script(
        "return (document.getElementById('editCabinetName')||{}).value||'';") or ""


def set_binder(driver, docinfo: str, binder: str, log) -> None:
    """편철 [설정] → 기록물철 선택 창에서 철 이름으로 검색해 고른다."""
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By

    driver.switch_to.window(docinfo)
    if _cabinet(driver).strip() == binder:
        log(f"✅ 편철: 이미 '{binder}'")
        return
    before = set(driver.window_handles)
    _click(driver, SEL_BINDER_BTN)
    win = _switch_new_window(driver, before, timeout=20, url_part=BINDER_URL)
    _wait(driver, lambda d: d.find_elements(By.ID, "BINDERNAME"), 20, "기록물철 선택 창을 읽지 못했습니다.")
    time.sleep(1.5)
    driver.execute_script(
        "document.getElementById('BINDERNAME').value = arguments[0]; searchBinderGetList(1);", binder)
    xp_name = ("//div[@id='BinderList']//td[contains(@class,'yui-dt-col-NAME')]"
               f"//div[normalize-space(text())='{binder}']")

    def cancel():
        try:
            driver.execute_script("go_cancel();")
        except Exception:
            pass
        driver.switch_to.window(docinfo)

    try:
        _wait(driver, lambda d: d.find_elements(By.XPATH, xp_name), 15, "")
    except DraftError:
        cancel()
        raise DraftError(f"기록물철 '{binder}'을 찾지 못했습니다. 철 이름을 확인하세요.") from None
    time.sleep(0.5)
    cells = driver.find_elements(By.XPATH, xp_name)
    if len(cells) > 1:
        cancel()
        raise DraftError(f"기록물철 '{binder}'이 {len(cells)}개라 하나로 정할 수 없습니다.")
    row = cells[0].find_element(By.XPATH, "./ancestor::tr[1]")
    # 기록물철명 칸을 더블클릭하면 철 정보 창이 뜨므로 단위업무명 칸을 한 번만 클릭한다.
    target = (row.find_elements(By.CSS_SELECTOR, "td.yui-dt-col-UNITNAME") or [cells[0]])[0]
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", target)
    ActionChains(driver).move_to_element(target).click(target).perform()
    _wait(driver, lambda d: d.find_element(By.ID, "nbutton_BtnSubmit-button").is_enabled(), 10,
          "기록물철을 선택했지만 [확인]이 활성화되지 않았습니다.")
    _click(driver, "#nbutton_BtnSubmit-button")
    end = time.time() + 15
    while time.time() < end and win in driver.window_handles:
        msg = _accept_alert(driver)
        if msg:
            log(f"  편철 메시지: {msg}")
        time.sleep(0.5)
    if win in driver.window_handles:
        raise DraftError("기록물철 선택 창이 닫히지 않았습니다.")
    driver.switch_to.window(docinfo)
    try:
        _wait(driver, lambda d: binder in _cabinet(d), 10, "")
    except DraftError:
        raise DraftError(f"편철이 '{_cabinet(driver)}'로 남아 있습니다.") from None
    log(f"✅ 편철: {_cabinet(driver)}")


def submit_docinfo(driver, docinfo: str, log) -> bool:
    """결재정보 창 [확인]. 창이 닫히면 True, 안내 메시지 등으로 남아 있으면 False."""
    driver.switch_to.window(docinfo)
    _click(driver, "#nbutton_BtnSubmit-button")
    end = time.time() + 15
    while time.time() < end:
        msg = _accept_alert(driver)
        if msg:
            log(f"  결재정보 메시지: {msg}")
        if docinfo not in driver.window_handles:
            log("✅ 결재정보 [확인]")
            return True
        time.sleep(0.5)
    return False


def wait_window_closed(driver, handle: str, timeout: float, log) -> None:
    """사용자가 창에서 작업을 마치고 [확인]으로 닫을 때까지 기다린다."""
    end = time.time() + timeout
    last = 0.0
    while time.time() < end:
        if handle not in driver.window_handles:
            return
        if time.time() - last > 60:
            log("  …결재정보 창에서 [확인]을 기다리는 중")
            last = time.time()
        time.sleep(1)
    raise DraftError("결재정보 창 [확인]을 기다리다 시간이 초과되었습니다(15분). "
                     "본문은 미리보기에서 복사해 직접 붙여 넣어 주세요.")


# ---------------- 3. 본문 (웹한글) ----------------

def _enter_hwp_frame(driver, timeout=60):
    """기안신규 창에서 HwpCtrl이 준비된 iframe(WordController_*)으로 들어간다."""
    from selenium.webdriver.common.by import By

    def ready(d):
        d.switch_to.default_content()
        frames = d.find_elements(By.CSS_SELECTOR, "iframe[id^='WordController_']")
        if not frames:
            return False
        d.switch_to.frame(frames[0])
        return d.execute_script(
            "return !!(window.HwpCtrl && typeof HwpCtrl.GetFieldList === 'function');")
    _wait(driver, ready, timeout, "웹한글 기안기가 준비되지 않았습니다.")


_JS_FIELDS = """
var h = window.HwpCtrl, out = {fields: ''};
try { out.fields = String(h.GetFieldList(0, 0) || ''); } catch (e) { out.fieldsErr = String(e); }
out.variants = {};
[[0,1],[0,2],[1,0],[1,1],[2,0]].forEach(function (a) {
  try { out.variants[a.join(',')] = String(h.GetFieldList(a[0], a[1]) || ''); }
  catch (e) { out.variants[a.join(',')] = 'ERR ' + e; }
});
return JSON.stringify(out);
"""

_JS_INSERT = r"""
var html = arguments[0], field = arguments[1], done = arguments[arguments.length - 1];
var h = window.HwpCtrl, info = {};
function ftext() { try { return String(h.GetFieldText(field) || ''); } catch (e) { return ''; } }
function tail(t) { t = t.replace(/\s+$/, ''); return t.slice(-40); }
function countEnd(t) { var m = t.match(/끝\./g); return m ? m.length : 0; }
try {
  info.before = tail(ftext());
  // 1) 본문 누름틀 안의 기존 내용(빈 줄·서식의 '끝.')을 전부 선택해 지운다.
  try { h.MoveToField(field, true, true, true); h.Run('Delete'); } catch (e) { info.delErr = String(e); }
  if (ftext().replace(/\s/g, '').length > 0) {
    try { h.PutFieldText(field, ''); } catch (e) { info.putErr = String(e); }
  }
  info.cleared = tail(ftext());
  // 2) 누름틀 시작 위치에 본문을 넣는다.
  h.MoveToField(field, true, true, false);
  h.SetTextFile(html, 'HTML', 'insertfile', function (r) {
    info.r = String(r);
    var t = ftext();
    info.ends = countEnd(t);
    // 3) 그래도 '끝.'이 2개 이상이면(서식이 다시 붙인 경우) 커서(본문 끝) 뒤를 누름틀 끝까지 지운다.
    if (info.ends > 1) {
      try {
        var p = h.GetPos();
        h.MoveToField(field, true, false, false);
        var q = h.GetPos();
        h.SelectText(p.para, p.pos, q.para, q.pos);
        h.Run('Delete');
        var t2 = ftext();
        if (t2.indexOf('붙임') < 0 && t2.indexOf('끝.') < 0) { h.Run('Undo'); info.undo = true; }
        info.endsAfterTrim = countEnd(ftext());
      } catch (e) { info.trimErr = String(e); }
    }
    info.after = tail(ftext());
    done({ok: true, info: info});
  });
} catch (e) { done({ok: false, err: String(e), info: info}); }
"""

BODY_FIELD_HINTS = ("본문", "내용", "body", "BODY")


def probe_hwp(driver) -> dict:
    """웹한글 누름틀(필드) 목록. 진단용으로 파일에도 남긴다."""
    info = json.loads(driver.execute_script(_JS_FIELDS))
    raw = info.get("fields", "") or next(
        (v for v in info.get("variants", {}).values() if v and not v.startswith("ERR")), "")
    info["field_list"] = list(dict.fromkeys(
        f for f in raw.replace("\x02", "\n").split("\n") if f.strip()))
    try:
        import paths
        with open(os.path.join(paths.sub_dir("logs"), "hwpctrl_probe.json"), "w",
                  encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return info


def insert_body(driver, draft_handle: str, body_html: str, log, subcase: int = 0) -> bool:
    """본문 HTML을 웹한글에 넣는다. 본문 누름틀이 없으면 False(사용자가 붙여넣기).

    subcase: 0이면 1안. 안마다 본문 누름틀이 따로 있으면 그 순서로 고른다.
    """
    driver.switch_to.window(draft_handle)
    log("웹한글 기안기 준비를 기다립니다...")
    _enter_hwp_frame(driver)
    info = probe_hwp(driver)
    fields = info["field_list"]
    log(f"  누름틀: {', '.join(fields) if fields else '(없음)'}")
    bodies = [f for f in fields if any(h in f for h in BODY_FIELD_HINTS)]
    target = bodies[min(subcase, len(bodies) - 1)] if bodies else ""
    if not target:
        driver.switch_to.default_content()
        log("⚠️ 본문 위치(누름틀)를 찾지 못했습니다. 미리보기의 본문을 직접 붙여 넣어 주세요.")
        return False
    driver.set_script_timeout(30)
    res = driver.execute_async_script(_JS_INSERT, f"<html><body>{body_html}</body></html>", target)
    driver.switch_to.default_content()
    if not res or not res.get("ok"):
        log(f"⚠️ 본문 넣기 실패({(res or {}).get('err', '')}). 직접 붙여 넣어 주세요.")
        return False
    info = res.get("info") or {}
    log(f"✅ 본문 입력 ('{target}' 위치)")
    if (info.get("endsAfterTrim") or info.get("ends") or 0) > 1:
        log("⚠️ 본문 끝에 '끝.'이 2개 남았습니다. 아래쪽 '끝.'을 직접 지워 주세요.")
    _enter_hwp_frame(driver)
    try:
        # 붙여 넣은 HTML의 표식을 한글 서식으로 바꾼다(문단 여백·내어쓰기, 붙임 탭)
        apply_para_marks(driver, body_html, log)
        apply_tab_marks(driver, body_html, log, target)
    finally:
        driver.switch_to.default_content()
    return True


_JS_FIELD_HAS = """
try { return String(window.HwpCtrl.GetFieldText(arguments[0]) || '').indexOf(arguments[1]) >= 0; }
catch (e) { return null; }
"""


def apply_tab_marks(driver, body_html: str, log, field: str) -> None:
    """붙임 줄의 탭 표식을 진짜 탭으로 바꾼다(1. 2. 3.이 같은 탭 위치에 온다).
    탭 글자로 바꿔 보고, 남아 있으면 한글의 탭 기호 ^t로, 그래도 남으면 빈칸으로 바꾼다."""
    import doc_template as dtpl
    mark = dtpl.TAB_MARK
    if mark not in body_html:
        return
    for repl in ("\t", "^t"):
        driver.execute_script(_JS_REPLACE_MARK, mark, repl)
        left = driver.execute_script(_JS_FIELD_HAS, field, mark)
        if left is False:
            log("✅ 붙임 탭 맞춤")
            return
        if left is not None:
            continue
        log("✅ 붙임 탭 맞춤(확인 못 함 — 붙임 열을 한번 봐 주세요)")
        return
    driver.execute_script(_JS_REPLACE_MARK, mark, "    ")
    log("⚠️ 붙임 탭을 넣지 못해 빈칸으로 띄웠습니다. 2. 3. 앞에서 Tab을 눌러 맞춰 주세요.")


# 문단 표식(【문단:왼쪽:내어쓰기】, 1/100pt)을 찾아 선택하고 [문단 모양]을 준다.
_JS_PARA_MARKS = """
var h = window.HwpCtrl, marks = arguments[0], out = {per: {}, errs: []};
function pos() { try { return JSON.stringify(h.GetSelectedPos ? h.GetSelectedPos() : h.GetPos()); } catch (e) { return ''; } }
for (var k = 0; k < marks.length; k++) {
  var mk = marks[k][0], left = marks[k][1], ind = marks[k][2], n = 0, last = null;
  try {
    h.MovePos(2);                                   // 문서 처음부터 앞으로 찾는다
    for (var i = 0; i < 400; i++) {
      var f = h.CreateAction('RepeatFind'), fs = f.CreateSet(); f.GetDefault(fs);
      fs.SetItem('FindString', mk); fs.SetItem('IgnoreMessage', 1); fs.SetItem('Direction', 0);
      var r = f.Execute(fs);
      if (!r || String(r) === 'false' || String(r) === '0') break;
      var p = pos();
      if (p && p === last) break;                   // 더 찾지 못하고 같은 자리에 머문다
      last = p;
      var a = h.CreateAction('ParagraphShape'), s = a.CreateSet(); a.GetDefault(s);
      s.SetItem('LeftMargin', left); s.SetItem('Indentation', ind);
      a.Execute(s);
      n++;
    }
  } catch (e) { out.errs.push(mk + ' ' + e); }
  out.per[mk] = n;
}
return JSON.stringify(out);
"""


def apply_para_marks(driver, body_html: str, log) -> None:
    """본문의 문단 표식마다 [문단 모양](왼쪽 여백·내어쓰기)을 주고 표식을 지운다.
    문단 모양을 다 주지 못한 표식은 예전처럼 빈칸으로 바꿔 첫 줄 들여쓰기만이라도 살린다."""
    from collections import Counter
    import doc_template as dtpl
    counts = Counter(m.group(0) for m in dtpl.PARA_MARK_RE.finditer(body_html))
    if not counts:
        return
    marks = [[mk, int(m.group(1)), int(m.group(2))]
             for mk in counts for m in [dtpl.PARA_MARK_RE.fullmatch(mk)]]
    try:
        res = json.loads(driver.execute_script(_JS_PARA_MARKS, marks) or "{}")
    except Exception as ex:
        res = {"per": {}, "errs": [str(ex)]}
    per = res.get("per", {})
    short = 0
    for mk, left, _ind in marks:
        ok = per.get(mk, 0) >= counts[mk] and not res.get("errs")
        # 못 준 표식은 빈칸으로(왼쪽 여백 6.5pt ≈ 빈칸 1칸)
        fallback = "" if ok else " " * round(left / 650)
        short += 0 if ok else counts[mk]
        driver.execute_script(_JS_REPLACE_MARK, mk, fallback)
    if short:
        log(f"⚠️ 문단 {short}곳의 내어쓰기를 넣지 못해 빈칸으로 들여 썼습니다. {res.get('errs', '')}")
        return
    log(f"✅ 문단 여백(내어쓰기) {sum(counts.values())}곳")


# ---------------- 4. 문서링크 ----------------
# 본문의 표식 글자를 찾아 선택한 뒤 [문서링크]로 관련 문서를 추가하면 그 자리에 링크가 들어간다
# ("본문의 현재 선택된 위치에 관련근거 링크가 추가 됩니다"). 남은 표식은 지우고,
# 링크를 못 넣으면 표식을 원래 글자(fallback)로 바꾼다.

_JS_FIND_MARK = r"""
var h = window.HwpCtrl, mark = arguments[0];
try {
  h.MovePos(2);                                   // 문서 처음으로
  var act = h.CreateAction('RepeatFind'), set = act.CreateSet(); act.GetDefault(set);
  set.SetItem('FindString', mark); set.SetItem('IgnoreMessage', 1); set.SetItem('Direction', 0);
  var ok = String(act.Execute(set));
  return [ok, JSON.stringify(h.GetSelectedPos ? h.GetSelectedPos() : null)];
} catch (e) { return ['ERR ' + e, '']; }
"""

_JS_REPLACE_MARK = r"""
var h = window.HwpCtrl, mark = arguments[0], text = arguments[1];
try {
  var act = h.CreateAction('AllReplace'), set = act.CreateSet(); act.GetDefault(set);
  set.SetItem('FindString', mark); set.SetItem('ReplaceString', text);
  set.SetItem('IgnoreMessage', 1); set.SetItem('Direction', 2);
  return String(act.Execute(set));
} catch (e) { return 'ERR ' + e; }
"""

_JS_BODY_HAS = r"""
try { return String(window.HwpCtrl.GetFieldText('/pubdoc/body/content') || '').indexOf(arguments[0]) >= 0; }
catch (e) { return null; }
"""

# 제목 칸에 wants가 모두 있고 excludes가 없는 줄 중 prefers(정규식)가 가장 많이 맞는 줄. 같으면 위쪽(최신).
_JS_PICK_ROW = r"""
var wants = arguments[0], excludes = arguments[1], prefers = arguments[2], minScore = arguments[3];
var o = window.DocumentList;
if (!o) return [-2, ''];
var best = -1, bestScore = -1, bestTitle = '';
for (var i = 0; i < o.GetListCount(); i++) {
  for (var c = 0; c < 16; c++) {
    var t; try { t = String(o.GetItemText(i, c)); } catch (e) { break; }
    var ok = true, k;
    for (k = 0; k < wants.length && ok; k++) { if (t.indexOf(wants[k]) < 0) ok = false; }
    for (k = 0; k < excludes.length && ok; k++) { if (t.indexOf(excludes[k]) >= 0) ok = false; }
    if (!ok) continue;
    var score = 0;
    for (k = 0; k < prefers.length; k++) { if (new RegExp(prefers[k]).test(t)) score++; }
    if (score >= minScore && score > bestScore) { best = i; bestScore = score; bestTitle = t; }
    break;
  }
}
return [best, bestTitle];
"""


# 문서번호(등록번호)가 꼭 맞는 줄: 칸 글자가 번호와 같거나, 번호만 적었으면 '…-번호'로 끝나는 줄
_JS_PICK_NO = r"""
var no = arguments[0], o = window.DocumentList;
if (!o) return [-2, ''];
for (var i = 0; i < o.GetListCount(); i++) {
  var hit = false, title = '';
  for (var c = 0; c < 16; c++) {
    var t; try { t = String(o.GetItemText(i, c)).trim(); } catch (e) { break; }
    if (t === no || (no.indexOf('-') < 0 && t.slice(-(no.length + 1)) === '-' + no)) hit = true;
    if (t.length > title.length && t.indexOf('-') < 0 && !/^[0-9]+$/.test(t)) title = t;
  }
  if (hit) return [i, title];
}
return [-1, ''];
"""

# 생산연도 고르기: 지금 해에서 못 찾으면 지난해들에서도 찾는다
_JS_YEARS = r"""
var o = window.CreateYearCombo, r = [];
if (!o) return r;
for (var i = 0; i < o.GetItemCount(); i++) { try { r.push(String(o.GetItemText ? o.GetItemText(i) : o.GetID(i))); } catch (e) { r.push(''); } }
return r;
"""


def _search_rows(driver, link: DocLink, log) -> tuple[int, str]:
    """문서링크 창에서 link를 찾아 (줄 번호, 제목). 못 찾으면 (-1, '')."""
    # 홈넷 등록번호 검색은 번호(숫자)만 받는다('가나관리소-1234'로 찾으면 안 나옴) → 숫자로 찾고 전체 번호로 고른다
    key = re.sub(r"^.*-", "", link.doc_no) if link.doc_no else link.search

    def run_search():
        driver.execute_script("document.getElementById('searchType').value = arguments[1];"
                              "document.getElementById('editSearchCondition').value = arguments[0]; search(1, 1);",
                              key, "docnum" if link.doc_no else "title")
        time.sleep(2)                    # 검색 전 목록이 아니라 새 목록에서 고르도록
        idx, picked, end = -1, "", time.time() + 15
        while time.time() < end and idx < 0:
            time.sleep(0.6)
            msg = _accept_alert(driver)  # '검색 결과가 없습니다' 등
            if msg:
                log(f"  문서링크 메시지: {msg}")
            try:
                if link.doc_no:
                    r = driver.execute_script(_JS_PICK_NO, link.doc_no)
                else:
                    r = driver.execute_script(_JS_PICK_ROW, list(link.title_has), list(link.exclude),
                                              list(link.prefer), link.min_prefer)
            except Exception:            # 목록을 다시 그리는 중
                r = None
            idx, picked = (r[0], r[1]) if isinstance(r, list) and len(r) == 2 else (-1, "")
            if idx == -1 and link.doc_no and time.time() > end - 9:
                break                    # 목록은 떴는데 맞는 번호가 없다
        return idx, picked

    try:
        years = [str(y) for y in driver.execute_script(_JS_YEARS)]
    except Exception:
        years = []
    if link.doc_no and link.year:        # 연도를 적었으면(…-12(2025. 1. 2.)) 그 해 대장에서만 찾는다
        if link.year not in years:
            log(f"  {link.doc_no}: 문서링크 창에 {link.year}년 대장이 없습니다")
            return -1, ""
        driver.execute_script("CreateYearCombo.SetCurSel(arguments[0]);", years.index(link.year))
        return run_search()
    idx, picked = run_search()
    if idx >= 0 or not link.doc_no:
        return idx, picked
    for y in range(1, min(len(years), 4)):   # 문서번호는 지난해 문서일 수도 있다: 생산연도를 바꿔 가며 찾는다
        try:
            driver.execute_script("CreateYearCombo.SetCurSel(arguments[0]);", y)
        except Exception:
            break
        log(f"  {link.doc_no}: 올해 대장에 없어 {years[y]}년 대장에서 찾습니다")
        idx, picked = run_search()
        if idx >= 0:
            return idx, picked
    return -1, ""


def _hwp_mark_exists(driver, mark: str) -> bool | None:
    return driver.execute_script(_JS_BODY_HAS, mark)


def insert_doc_link(driver, draft: str, link: DocLink, log) -> None:
    """본문 표식 자리에 [문서링크]로 관련 문서를 넣는다."""
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By

    wanted = f"문서번호 {link.doc_no}" if link.doc_no else " + ".join(link.title_has)

    def restore(reason: str):
        driver.switch_to.window(draft)
        _enter_hwp_frame(driver)
        driver.execute_script(_JS_REPLACE_MARK, link.mark, link.fallback)
        driver.switch_to.default_content()
        raise DraftError(reason)

    driver.switch_to.window(draft)
    _enter_hwp_frame(driver)
    found, sel = driver.execute_script(_JS_FIND_MARK, link.mark)
    if found != "true":
        driver.switch_to.default_content()
        log(f"  (본문에 문서링크 자리가 없어 건너뜁니다: {found})")
        return
    driver.switch_to.default_content()

    before = set(driver.window_handles)
    _click(driver, "#nbutton_BtnRelateAttachLink-button")
    win, end = None, time.time() + 20
    while time.time() < end and not win:
        time.sleep(0.4)
        _accept_alert(driver)            # "본문의 현재 선택된 위치에 … 추가 됩니다"
        new = set(driver.window_handles) - before
        win = new.pop() if new else None
    if not win:
        restore("[문서링크] 창이 열리지 않았습니다.")
    driver.switch_to.window(win)
    _wait(driver, lambda d: d.execute_script(
        "return !!(window.DocumentList && document.getElementById('editSearchCondition') && window.search)"),
        20, "[문서링크] 창이 준비되지 않았습니다.")
    idx, picked = _search_rows(driver, link, log)
    if idx < 0:
        driver.close()
        restore(f"[문서링크]에서 '{wanted}' 문서를 찾지 못했습니다.")
    log(f"  문서링크 고른 문서: {picked}")

    rows = driver.find_elements(By.CSS_SELECTOR, "tbody.yui-dt-data tr")
    if idx < len(rows):   # 제목 칸을 실제로 눌러 줄을 선택한다
        cells = rows[idx].find_elements(By.CSS_SELECTOR, "td")
        target = next((c for c in cells if picked and picked.strip() in (c.text or "")),
                      next((c for c in cells if all(w in (c.text or "") for w in link.title_has)),
                           cells[0] if cells else rows[idx]))
        if link.doc_no:                  # 문서번호 칸을 누른다(제목이 같은 문서가 여럿이어도 정확히)
            target = next((c for c in cells if (c.text or "").strip() == link.doc_no
                           or (c.text or "").strip().endswith("-" + link.doc_no)), target)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", target)
        ActionChains(driver).move_to_element(target).click(target).perform()
    else:
        driver.execute_script("DocumentList.SetSelectedIndex(arguments[0]); DocumentList_ItemClicked();", idx)
    # 줄을 누르면 문서 정보(AttachList)를 따로 불러온다 — 다 불러온 뒤 [추가]해야 들어간다.
    # 클릭이 안 먹으면 목록 함수로 다시 고르고, 정보가 끝내 비어 있어도 고른 줄이 맞으면 [추가]를 눌러 본다
    def selection(wait: float) -> tuple[bool, bool]:
        selected = loaded = False
        end = time.time() + wait
        while time.time() < end:
            msg = _accept_alert(driver)
            if msg:
                log(f"  문서링크 메시지: {msg}")
            try:
                selected, loaded = driver.execute_script(
                    "return [DocumentList.GetSelectedIndex() === arguments[0], AttachList.GetListCount() > 0];", idx)
            except Exception:
                pass
            if selected and loaded:
                break
            time.sleep(0.5)
        return selected, loaded

    selected, loaded = selection(8)
    if not loaded:
        driver.execute_script("DocumentList.SetSelectedIndex(arguments[0]); DocumentList_ItemClicked();", idx)
        selected, loaded = selection(10)
    if not selected:
        _save_probe(driver, "doclink_probe.html")
        driver.close()
        restore("[문서링크]에서 고른 문서를 선택하지 못했습니다.")
    if not loaded:
        log("  (고른 문서의 정보 목록이 비어 있지만 [추가]를 눌러 봅니다)")
    time.sleep(1)
    for attempt in range(2):             # [추가] 후 창이 닫혀야 본문에 들어간 것. 안 닫히면 한 번 더
        if win not in driver.window_handles:
            break
        driver.switch_to.window(win)
        _click(driver, "#nbutton_btnRelateOk-button")
        end = time.time() + (15 if attempt == 0 else 20)
        while time.time() < end and win in driver.window_handles:
            msg = _accept_alert(driver)
            if msg:
                log(f"  문서링크 메시지: {msg}")
            time.sleep(0.4)
    if win in driver.window_handles:
        driver.switch_to.window(win)
        _save_probe(driver, "doclink_probe.html")
        try:
            import paths
            driver.save_screenshot(os.path.join(paths.sub_dir("logs"), "doclink_probe.png"))
        except Exception:
            pass
        driver.close()
        restore("[문서링크]에서 [추가]가 되지 않았습니다(보안 문서는 직접 넣어 주세요).")

    # [추가] 후 창이 닫혔으면 선택해 둔 표식 자리에 링크가 들어간 것. 표식이 남아 있으면 지운다
    driver.switch_to.window(draft)
    _enter_hwp_frame(driver)
    time.sleep(1)
    if _hwp_mark_exists(driver, link.mark):
        driver.execute_script(_JS_REPLACE_MARK, link.mark, "")
    driver.switch_to.default_content()
    log(f"✅ 문서링크: {wanted}")


# ---------------- 전체 ----------------

LINK_MARK = "⟦문서링크⟧"


@dataclass
class DocLink:
    """본문의 표식(mark) 자리에 [문서링크]로 넣을 관련 문서."""
    search: str                 # 문서링크 창 문서제목 검색어(예: '34차')
    title_has: tuple            # 고를 문서 제목에 모두 들어 있어야 할 글자(예: ('입주자격심사 결과', '34차'))
    fallback: str               # 링크를 못 넣으면 표식 대신 넣을 글자(미리보기 글자)
    mark: str = LINK_MARK       # 본문 표식. 한 안에 링크가 여럿이면 서로 달라야 한다
    exclude: tuple = ()         # 제목에 이 글자가 있으면 고르지 않는다
    prefer: tuple = ()          # 제목에 맞을수록 먼저 고르는 정규식(예: 차수, 월)
    min_prefer: int = 0         # prefer 중 최소 몇 개가 맞아야 고르는지
    doc_no: str = ""            # 문서번호(등록번호, 예: '가나관리소-1234' 또는 '1234'). 있으면 번호로 찾는다
    year: str = ""              # 문서번호의 생산연도(예: '2025'). 비우면 올해부터 3년 전까지 찾는다


@dataclass
class DraftPart:
    """한 안(1안, 2안 …)에 넣을 내용."""
    info: DocInfo
    receiver: str               # '' 또는 '내부결재'면 수신자 없음
    body_html: str
    upload_path: str = ""       # 수신자 엑셀(수기입력 [업로드])
    doc_links: list = field(default_factory=list)   # 본문에 넣을 관련 문서 링크(본문의 각 표식 자리)


TAB_LI = "#tabHead li"


def add_subcase(driver, draft: str, log) -> int:
    """[안추가]로 새 안을 만든다. 새 안의 번호(1부터)를 돌려준다."""
    from selenium.webdriver.common.by import By
    driver.switch_to.window(draft)
    driver.switch_to.default_content()
    n0 = len(driver.find_elements(By.CSS_SELECTOR, TAB_LI))
    _click(driver, "#nbutton_BtnAddSubcase-button")
    end = time.time() + 30
    while time.time() < end:
        msg = _accept_alert(driver)
        if msg:
            log(f"  안추가 메시지: {msg}")
        try:
            driver.switch_to.window(draft)
            driver.switch_to.default_content()
            n = len(driver.find_elements(By.CSS_SELECTOR, TAB_LI))
        except Exception:
            n = n0
        if n > n0:
            log(f"✅ 안추가: {n}안")
            return n
        time.sleep(0.5)
    raise DraftError("[안추가]를 눌렀지만 새 안이 생기지 않았습니다.")


def create_draft(driver, info: DocInfo, receiver: str, body_html: str, log=print,
                 notify=None, upload_path: str = "") -> list[str]:
    """안이 하나인 표준기안문. create_drafts 참고."""
    return create_drafts(driver, [DraftPart(info, receiver, body_html, upload_path)], log, notify)


def create_drafts(driver, parts: list[DraftPart], log=print, notify=None) -> list[str]:
    """표준기안문에 안마다 제목·수신자·본문을 채운다. 2안부터는 [안추가]로 만든다. 상신은 하지 않는다.

    자동으로 못 한 부분은 사용자에게 맡기고(notify) 결재정보 [확인]을 기다린다.
    돌려주는 값은 사용자가 마저 할 일 목록.
    """
    todo: list[str] = []
    draft = open_form(driver, log)
    for i, part in enumerate(parts):
        name = f"{i + 1}안 " if len(parts) > 1 else ""
        if i:
            add_subcase(driver, draft, log)
        if len(parts) > 1:
            log(f"── {i + 1}안: {part.info.title}")
        docinfo = find_or_open_docinfo(driver, draft, log)
        _apply_docinfo(driver, docinfo, part, log, notify, subcase=i)
        time.sleep(2)   # 본문 문서가 서식에 반영될 시간
        if not insert_body(driver, draft, part.body_html, log, subcase=i):
            todo.append(f"{name}본문: [브라우저로 미리보기]의 본문(표 포함)을 복사해 붙여 넣기")
        else:
            from selenium.common.exceptions import WebDriverException
            for link in part.doc_links:
                try:
                    insert_doc_link(driver, draft, link, log)
                except (DraftError, WebDriverException) as ex:
                    if draft not in driver.window_handles:
                        raise DraftError("기안 창이 닫혔습니다. 홈넷 화면에서 이어서 작성해 주세요.") from None
                    msg = str(ex) if isinstance(ex, DraftError) else str(ex).splitlines()[0][:80]
                    log(f"⚠️ 문서링크 자동 추가 실패: {msg}")
                    driver.switch_to.window(draft)
                    how = (f"등록번호 '{link.doc_no}' 검색" if link.doc_no else
                           f"'{link.search}' 검색 → '{' + '.join(link.title_has)}'")
                    todo.append(f"{name}문서링크: 본문의 '{link.fallback}'을 선택하고 [문서링크]에서 "
                                f"{how} 문서 [추가]")
    todo.append("붙임 파일이 있으면 [첨부]로 올리기")
    todo.append("내용을 확인한 뒤 [결재올림](상신)은 직접 누르기")
    return todo


def _apply_docinfo(driver, docinfo: str, part: DraftPart, log, notify, subcase: int = 0) -> None:
    """결재정보 창: 제목·공개여부 → 수신자 → 편철 → [확인]. 못 한 것은 사람에게 맡기고 기다린다."""
    info, receiver, upload_path = part.info, part.receiver, part.upload_path
    fill_docinfo(driver, docinfo, info, log, subcase)

    from selenium.common.exceptions import WebDriverException
    steps = []
    if upload_path or (receiver and receiver != "내부결재"):
        try:
            set_receiver(driver, docinfo, receiver, log, upload_path, subcase)
        except (DraftError, WebDriverException) as ex:   # 창이 닫힌 경우 등도 사람에게 맡긴다
            msg = str(ex) if isinstance(ex, DraftError) else f"{type(ex).__name__}: {str(ex).splitlines()[0][:80]}"
            log(f"⚠️ 수신자 자동 입력 실패: {msg}")
            if docinfo not in driver.window_handles:
                raise DraftError("결재정보 창이 닫혔습니다. 홈넷 화면에서 이어서 작성해 주세요.") from None
            _close_sancline(driver, docinfo)
            steps.append(f"결재선 [설정] → 수신자 탭{f' → {subcase + 1}안' if subcase else ''} → 수기입력 → [업로드]: {upload_path}"
                         if upload_path else
                         f"결재선 [설정] → 수신자 탭 → 수기입력: {hand_receiver_text(receiver)}")
    if info.binder:
        try:
            set_binder(driver, docinfo, info.binder, log)
        except DraftError as ex:
            log(f"⚠️ 편철 자동 선택 실패: {ex}")
            steps.append(f"편철 [설정] → '{info.binder}' 선택")

    if steps or not submit_docinfo(driver, docinfo, log):
        if not steps:
            steps.append("결재정보 창의 안내 메시지 확인(필수 항목 등)")
        msg = ("브라우저의 결재정보 창에서 아래를 직접 한 뒤 [확인]을 눌러 주세요.\n\n"
               + "\n".join(f"• {s}" for s in steps)
               + "\n\n[확인]을 누르면 본문 넣기를 이어서 자동으로 합니다.")
        for s in steps:
            log(f"  ▶ {s}")
        if notify:
            notify(msg)
        wait_window_closed(driver, docinfo, 15 * 60, log)
        log("✅ 결재정보 확인됨")
