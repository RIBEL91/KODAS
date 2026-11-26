"""자료집계(moumi.kohom.or.kr/totsys)의 [문서수신 → 제출완료함]에서 우리가 낸 취합자료 첨부를 받는다(읽기만).

- 들어가기: 홈넷 본 화면의 [자료취합] = sloLogin('data') → 새 창(자료집계, 프레임 topx·left·main).
  주소로 바로 열면 '작업시간이 종료' 알림이 뜨므로 꼭 홈넷에서 연다.
- 제출완료함: main 프레임 …/repoper/mydocbox/endbox/report_list.jsp?reportType=END,
  검색 findForm(findOption='totDoc.name' 자료명, findWord) → 줄 a[href*=fn_goToView] → 보기 화면.
- 첨부: 보기 화면의 a[onclick*=doDownloadFileTargetFrm('/servlet/…HttpViewer?saveAs=…')] — 브라우저 쿠키로 직접 받는다.
2026-11-20 광주양림2 계정으로 구조를 확인했다.
"""
from __future__ import annotations

import os
import re
import time
import urllib.parse
import urllib.request

BASE = "https://moumi.kohom.or.kr"
END_BOX = BASE + "/totsys/repoper/mydocbox/endbox/report_list.jsp?reportType=END"


class MoumiError(Exception):
    pass


def open_moumi(driver) -> tuple[str, str]:
    """홈넷 본 창에서 자료집계 창을 연다. (홈넷 창, 자료집계 창)."""
    import homnet
    main = homnet.main_window(driver)
    driver.switch_to.window(main)
    driver.switch_to.default_content()
    before = set(driver.window_handles)
    driver.execute_script("sloLogin('data');")
    end = time.time() + 25
    while time.time() < end:
        time.sleep(1)
        new = [h for h in driver.window_handles if h not in before]
        if new:
            driver.switch_to.window(new[0])
            time.sleep(3)
            return main, new[0]
    raise MoumiError("자료집계 창이 열리지 않았습니다(홈넷 [자료취합]).")


def _main_frame(driver):
    driver.switch_to.default_content()
    driver.switch_to.frame("main")


def find_submitted(driver, word: str, year: int) -> list[tuple[str, str]]:
    """제출완료함을 자료명으로 검색한다. [(제목, fn_goToView(...) 스크립트)] — year가 든 제목이 앞."""
    _main_frame(driver)
    driver.execute_script("location.href = arguments[0];", END_BOX)
    time.sleep(3)
    driver.execute_script("var f=document.findForm; f.findOption.value='totDoc.name'; f.findWord.value=arguments[0];"
                          "f.strPage.value=1; f.submit();", word)
    time.sleep(3)
    rows = driver.execute_script("return Array.from(document.querySelectorAll('a[href*=fn_goToView]'))"
                                 ".map(a=>[(a.title||a.innerText).trim(), a.getAttribute('href')])") or []
    ys = (f"{year}년", f"({str(year)[2:]}.", f"{str(year)[2:]}년")
    rows.sort(key=lambda r: 0 if any(y in r[0] for y in ys) else 1)
    return [(t, h.replace("javascript:", "")) for t, h in rows]


def _cookie_header(driver) -> str:
    return "; ".join(f"{c['name']}={c['value']}" for c in driver.get_cookies())


def download_attachments(driver, view_js: str, dest: str, log=print) -> tuple[str, list[str]]:
    """제출완료함 한 건을 열어 첨부를 dest에 받는다. (보기 화면 제목, [받은 파일])."""
    _main_frame(driver)
    driver.execute_script(view_js)
    time.sleep(3)
    title = driver.execute_script("var e=document.querySelector('.title,h3,h2'); return e? e.innerText.trim() : document.title;") or ""
    links = driver.execute_script(
        "return Array.from(document.querySelectorAll('a[onclick*=doDownloadFileTargetFrm]'))"
        ".map(a=>[a.innerText.trim(), a.getAttribute('onclick')])") or []
    cookie = _cookie_header(driver)
    os.makedirs(dest, exist_ok=True)
    out = []
    for name, onclick in links:
        m = re.search(r"doDownloadFileTargetFrm\('([^']+)'", onclick or "")
        if not m:
            continue
        url = urllib.parse.urljoin(BASE, m.group(1))
        fname = re.sub(r'[\\/:*?"<>|]+', "_", name or "첨부")
        path = os.path.join(dest, fname)
        req = urllib.request.Request(url, headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0",
                                                   "Referer": BASE + "/totsys/repoper/mydocbox/endbox/report_view.jsp"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
                f.write(r.read())
        except Exception as ex:
            log(f"     ✗ 자료집계 첨부를 받지 못함: {name} ({type(ex).__name__})")
            continue
        if os.path.getsize(path) < 200:
            os.remove(path)
            continue
        out.append(path)
    return title, out


def close(driver, moumi_handle: str, main_handle: str) -> None:
    try:
        driver.switch_to.window(moumi_handle)
        driver.close()
    except Exception:
        pass
    try:
        driver.switch_to.window(main_handle)
        driver.switch_to.default_content()
    except Exception:
        pass
