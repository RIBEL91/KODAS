"""홈넷 대장(기록물등록대장)의 문서를 '다음'으로 넘기며 본문을 저장하고 서식으로 등록하는 수집 도구.

1) 대장 문서 창이 열려 있지 않으면 전자결재 → 대장관리 → 기록물등록대장을 열고
   (검색어가 있으면 제목으로 검색한 뒤) 맨 위 문서를 자동으로 연다.
2) 그 문서부터 N개를 {제목}.txt · .html · .meta.json(편철) 으로 저장한다.
   암호(보안) 문서는 홈넷 비밀번호를 넣어 열어 본다. 그래도 안 열리면 건너뛴다.
3) 저장한 문서를 서식 파일로 바꿔 서식 폴더의 '수집한 서식' 폴더에 넣는다(import_to_templates).
   이름·동호·날짜·금액·전화번호는 빈칸·자리표시로 바뀐다.
이 PC 안에만 저장한다(어디로도 보내지 않는다). 비밀번호는 기록에 남기지 않는다.
"""
import hashlib
import os
import re
import time

import binder_rules
import privacy

VIEWER_URL_PARTS = ("ledger_dochandler", "dochandler", "view_handdocument")
# 본문 없이 편철·등록구분·첨부만 보여 주는 '조회' 화면(접수 등록 문서). 이 화면은 저장하지 않는다.
VIEW_ONLY_URL = "view_handdocument"
_VIEW_ONLY_MARKS = ("생산처리과기관코드", "등록구분")

_JS_HAS_HWP = "return !!(window.HwpCtrl && typeof HwpCtrl.GetTextFile === 'function');"

# 웹한글 본문을 HTML·TEXT로 읽는다(콜백형·바로 돌려주는 형 모두 처리)
_JS_READ_HWP = r"""
var done = arguments[arguments.length - 1], h = window.HwpCtrl, out = {}, finished = false;
function finish() { if (!finished) { finished = true; done(JSON.stringify(out)); } }
var fmts = ['HTML', 'TEXT'], i = 0;
function next() {
  if (i >= fmts.length) { finish(); return; }
  var f = fmts[i++], got = false;
  function take(v) { if (got) return; got = true; out[f] = String(v == null ? '' : v); next(); }
  try {
    var r = h.GetTextFile(f, '', function (res) { take(res); });
    if (typeof r === 'string' && r) { take(r); }
  } catch (e) { out[f + 'Err'] = String(e); take(''); }
}
setTimeout(finish, 6000);   // 웹한글이 아직 준비 중이면 오래 기다리지 않고 다음 시도에서 다시 읽는다
next();
"""

_JS_PAGE_TEXT = "return (document.body && (document.body.innerText || '')) || '';"

_XPATH_NEXT = ("//*[(self::button or self::a or self::span or self::td or self::div or self::input or self::img)"
               " and (normalize-space(.)='다음' or @value='다음' or @alt='다음' or @title='다음')]")


class CollectError(Exception):
    pass


# ---------------- 순수 함수(시험 가능) ----------------

def fingerprint(text: str) -> str:
    return hashlib.md5(re.sub(r"\s+", "", text or "")[:4000].encode("utf-8")).hexdigest()


_DATE_BITS = [
    r"\d{1,4}\s*동\s*\d{1,4}\s*호",                                          # 104동 1306호
    r"\d{2,4}\s*[.년/\-]\s*\d{1,2}\s*[.월/\-]?\s*(?:\d{1,2}\s*[.일]?)?\s*(?:월분|분)?",   # 2025.12. · 2025년 11월분
    r"\d{2,4}\s*년(?:도)?",                                                  # 2025년
    r"\d{1,2}\s*월\s*분?",                                                    # 12월분
    r"[OＯ○]{2,}\s*(?:동\s*[OＯ○]{2,}\s*호)?",                                # 가린 자리(OOO동 OOO호)
]
_DATE_BITS_RE = re.compile("|".join(_DATE_BITS))


def similar_key(title: str) -> str:
    """비슷한 제목인지 견줄 열쇠: 날짜·연도·월·동호수와 괄호·빈칸을 뺀 글자.
    '사회복무요원 급여 지급(2025.12월분)'과 '(2025.11월분)' → 같은 열쇠. '납부최고 1차'·'2차'는 다르다."""
    t = _DATE_BITS_RE.sub("", title or "")
    return re.sub(r"[\s()\[\]{}<>.,·~\-_/:]+", "", t)


SECURE_MASKS = {"이름": "OOO", "동호수": "OOO동 OOO호", "연락처": "OOO-OOOO-OOOO", "주민번호": "OOOOOO-OOOOOOO"}


def _mask_secure_doc(doc: dict, extra=(), keep_phones=()) -> dict:
    """보안 문서(비밀번호로 연 문서)의 본문 글자·HTML에서 인적사항을 OOO으로 바꾼다.
    '…(104동 1306호)'처럼 제목에 든 동호수도 바뀌므로 파일 이름에도 남지 않는다."""
    import html as _h
    import privacy
    plain = (doc.get("text") or "") + "\n" + re.sub(r"<[^>]+>", " ", _h.unescape(doc.get("html") or ""))
    found = [(s, SECURE_MASKS.get(kind, repl), kind)
             for s, repl, kind in privacy.find_private(plain, extra, keep_phones)]
    out = dict(doc)
    out["text"] = privacy.mask_text(doc.get("text") or "", found=found)[0]
    if doc.get("html"):
        out["html"] = privacy.mask_html(doc["html"], found=found)[0]
    out["secure_found"] = found
    return out


def extract_meta(text: str) -> dict:
    """본문 글자에서 수신자·제목을 뽑는다. '수신자 내부결재'(한 줄)와 '수신자' 다음 줄에 값이 오는 모양 모두."""
    import doc_template
    lines = (text or "").replace("\r", "").split("\n")
    title, receiver, _ = doc_template.split_header(lines)
    internal = "내부결재" in receiver or (not receiver and "내부결재" in (text or "")[:600])
    return {"receiver": receiver, "title": title, "internal": internal}


def index_line(n: int, meta: dict, size: int, name: str = "") -> str:
    return (f"{n:03d} | {'내부결재' if meta['internal'] else '수신자있음'} | "
            f"수신자: {meta['receiver'] or '-'} | 제목: {meta['title'] or '-'} | {size}자"
            + (f" | 파일: {name}" if name else ""))


def safe_name(title: str, n: int, used: set) -> str:
    """제목을 파일 이름으로. 윈도에서 못 쓰는 글자는 빼고, 같은 이름이면 (2)·(3)을 붙인다."""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", title or "")
    s = re.sub(r"\s+", " ", s).strip(" .")
    s = s[:80].rstrip(" .")
    if not s:
        s = f"{n:03d}"
    base, k = s, 2
    while s.lower() in used:
        s = f"{base} ({k})"
        k += 1
    used.add(s.lower())
    return s


def is_view_only(text: str, url: str = "") -> bool:
    """대장의 '조회' 화면(본문 없이 편철·생산처리과기관코드·등록구분 … 표만 있는 화면)인지."""
    if VIEW_ONLY_URL in (url or ""):
        return True
    t = re.sub(r"\s+", "", text or "")
    return all(m in t for m in _VIEW_ONLY_MARKS)


def view_title(text: str) -> str:
    """'조회' 화면 글자에서 제목 칸 값을 읽는다('제목<탭>…' 또는 '제목' 다음 줄)."""
    lines = [l.strip() for l in (text or "").replace("\r", "").split("\n")]
    for i, l in enumerate(lines):
        m = re.match(r"^제\s*목\s*[\t:：]?\s*(.*)$", l)
        if m:
            val = m.group(1).strip() or next((x for x in lines[i + 1:i + 3] if x), "")
            return val.split("\t")[0].strip()
    return ""


def other_receiver(meta: dict) -> bool:
    """수신자가 따로 있는 문서(내부결재가 아님)인지. 모르면 False."""
    return bool(meta["receiver"]) and "내부결재" not in meta["receiver"]


# ---------------- 브라우저 쪽 ----------------

def find_viewer(driver) -> str:
    for h in driver.window_handles:
        try:
            driver.switch_to.window(h)
            url = driver.current_url or ""
        except Exception:
            continue
        if any(p in url for p in VIEWER_URL_PARTS):
            return h
    raise CollectError("열려 있는 대장 문서 창을 찾지 못했습니다. 전자결재 > 대장관리 > 기록물등록대장에서 "
                       "문서를 하나 열어 둔 뒤 다시 눌러 주세요.")


def _contexts(driver):
    """본문을 찾을 화면 후보: 맨 위 화면과 그 안의 iframe(2단계까지)."""
    from selenium.webdriver.common.by import By
    driver.switch_to.default_content()
    yield "top"
    top = driver.find_elements(By.TAG_NAME, "iframe")
    for i in range(len(top)):
        driver.switch_to.default_content()
        try:
            driver.switch_to.frame(driver.find_elements(By.TAG_NAME, "iframe")[i])
        except Exception:
            continue
        yield f"frame{i}"
        for j in range(len(driver.find_elements(By.TAG_NAME, "iframe"))):
            try:
                driver.switch_to.frame(driver.find_elements(By.TAG_NAME, "iframe")[j])
            except Exception:
                continue
            yield f"frame{i}.{j}"
            driver.switch_to.parent_frame()


def read_doc(driver, log=None) -> dict:
    """열려 있는 문서의 본문을 읽는다. {'html','text','source'}"""
    import json
    driver.set_script_timeout(10)
    page_text = ""
    for name in _contexts(driver):
        try:
            if driver.execute_script(_JS_HAS_HWP):
                data = json.loads(driver.execute_async_script(_JS_READ_HWP) or "{}")
                driver.switch_to.default_content()
                text, html = data.get("TEXT", ""), data.get("HTML", "")
                if text.strip() or html.strip():
                    return {"html": html, "text": text, "source": f"웹한글({name})"}
                if log:
                    log(f"  웹한글({name})에서 글자를 못 읽음: {data}")
            txt = driver.execute_script(_JS_PAGE_TEXT) or ""
            if len(txt) > len(page_text):
                page_text = txt
        except Exception as ex:
            if log:
                log(f"  {name} 읽기 실패: {type(ex).__name__}")
    driver.switch_to.default_content()
    if page_text.strip():
        return {"html": "", "text": page_text, "source": "화면 글자(웹한글 못 찾음)"}
    raise CollectError("문서 본문을 읽지 못했습니다(웹한글을 찾지 못함).")


_XPATH_INFO = ("//*[(self::button or self::a or self::span or self::td or self::div or self::input or self::img)"
               " and (normalize-space(.)='문서정보' or @value='문서정보' or @alt='문서정보' or @title='문서정보')]")

# 암호 입력칸(보이는 것)이나 '암호를 입력' 안내가 있는지
_JS_PASSWORD = r"""
function vis(e){var r=e.getBoundingClientRect(),s=getComputedStyle(e);
  return r.width>0&&r.height>0&&s.visibility!='hidden'&&s.display!='none';}
var pw=[].slice.call(document.querySelectorAll('input[type=password]')).some(vis);
var t=((document.body&&document.body.innerText)||'');
var hit=t.length<400&&/(암호|비밀번호|패스워드)/.test(t);
return pw||hit;
"""

# 암호 입력칸이 있는 창(레이어) 안의 [취소]·[닫기]만 누른다(도구줄의 [닫기]는 건드리지 않는다)
_JS_DISMISS_PW = r"""
function vis(e){var r=e.getBoundingClientRect(),s=getComputedStyle(e);
  return r.width>0&&r.height>0&&s.visibility!='hidden'&&s.display!='none';}
var inp=[].slice.call(document.querySelectorAll('input[type=password]')).filter(vis)[0];
if(!inp) return false;
var root=inp;
for(var up=0;up<8&&root.parentElement;up++){
  root=root.parentElement;
  var els=[].slice.call(root.querySelectorAll('button,input[type=button],input[type=submit],a,span,img'));
  for(var i=0;i<els.length;i++){
    var e=els[i],tx=((e.innerText||e.value||e.alt||e.title||'')+'').trim();
    if(vis(e)&&(tx=='취소'||tx=='닫기'||tx=='Cancel'||tx=='Close')){e.click();return true;}
  }
}
return false;
"""

_JS_FORM_TEXT = r"""
var out=[],t=((document.body&&document.body.innerText)||'');out.push(t);
[].slice.call(document.querySelectorAll('input,select,textarea')).forEach(function(e){
  var v=e.tagName=='SELECT'?((e.options[e.selectedIndex]||{}).text):e.value;
  if(v&&e.type!='hidden'&&e.type!='password')out.push('['+(e.id||e.name||e.tagName)+'] '+v);
});
return out.join('\n');
"""

_ENC_WORDS = re.compile(r"암호|비밀번호|패스워드")


def password_prompt(driver) -> bool:
    """암호 입력 화면(창)이 떠 있는지."""
    try:
        for _ in _contexts(driver):
            try:
                if driver.execute_script(_JS_PASSWORD):
                    driver.switch_to.default_content()
                    return True
            except Exception:
                continue
    except Exception:
        pass
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return False


def drain_alerts(driver, log=None, password: str = "") -> str:
    """경고창·확인창을 닫는다. 돌려주는 값: '' 보통 · 'unlocked' 암호 칸에 비밀번호를 넣음 · 'encrypted' 못 엶.

    암호를 묻는 창(prompt)이면 password를 넣고 [확인]. 비밀번호가 없거나 이미 한 번 넣었는데
    또 물으면(틀림) [취소]로 닫고 'encrypted'.
    """
    state = ""
    for _ in range(3):
        try:
            a = driver.switch_to.alert
            text = (a.text or "").strip()
        except Exception:
            break
        try:
            if _ENC_WORDS.search(text) and password and state == "":
                try:
                    a.send_keys(password)        # 입력칸이 있는 창(prompt)이면 비밀번호를 넣는다
                except Exception:
                    pass                         # 안내만 하는 창이면 [확인] 뒤 화면의 암호 칸에 넣는다
                a.accept()
                state = "unlocked"
            elif _ENC_WORDS.search(text):
                a.dismiss()
                state = "encrypted"
            else:
                a.accept()
        except Exception:
            break
        if log:
            log(f"  팝업 처리: {text[:80] or '(내용 없음)'}")
    return state


# 보이는 암호 입력칸 옆(같은 창·레이어)의 [확인]·[열기]를 누른다
_JS_SUBMIT_PW = r"""
function vis(e){var r=e.getBoundingClientRect(),s=getComputedStyle(e);
  return r.width>0&&r.height>0&&s.visibility!='hidden'&&s.display!='none';}
var inp=arguments[0], root=inp;
for(var up=0;up<8&&root.parentElement;up++){
  root=root.parentElement;
  var els=[].slice.call(root.querySelectorAll('button,input[type=button],input[type=submit],a,span,img'));
  for(var i=0;i<els.length;i++){
    var e=els[i],tx=((e.innerText||e.value||e.alt||e.title||'')+'').replace(/\s+/g,'');
    if(vis(e)&&(tx=='확인'||tx=='열기'||tx=='OK'||tx=='열람')){e.click();return true;}
  }
}
return false;
"""


def unlock_field(driver, password: str, log=None) -> bool:
    """화면(또는 iframe)에 뜬 암호 입력칸에 홈넷 비밀번호를 넣고 [확인]한다. 칸이 없으면 False."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    if not password:
        return False
    try:
        for _ in _contexts(driver):
            boxes = [e for e in driver.find_elements(By.CSS_SELECTOR, "input[type=password]")
                     if e.is_displayed()]
            if not boxes:
                continue
            box = boxes[0]
            box.clear()
            box.send_keys(password)
            if not driver.execute_script(_JS_SUBMIT_PW, box):
                box.send_keys(Keys.ENTER)
            driver.switch_to.default_content()
            if log:
                log("  보안 문서라 홈넷 비밀번호를 넣어 엽니다.")
            return True
    except Exception:
        pass
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return False


# 보안문서: 문서를 열면 문서 창 대신 '처리암호' 창(npasswddlg.jsp)이 따로 뜬다.
# 입력칸 #Passwd에 홈넷 비밀번호를 넣고 [확인](#nbutton_BtnSubmit-button)을 누르면 문서 창이 열린다.
PW_WINDOW_URL = "npasswddlg"
UNLOCKED_VIEWERS: set = set()      # 비밀번호로 연 문서 창(첫 문서) — 저장할 때 보안 문서로 다룬다


def _pw_window(driver) -> str | None:
    cur = None
    try:
        cur = driver.current_window_handle
    except Exception:
        pass
    found = None
    for h in driver.window_handles:
        try:
            driver.switch_to.window(h)
            if PW_WINDOW_URL in (driver.current_url or ""):
                found = h
                break
        except Exception:
            continue
    if cur and not found:
        try:
            driver.switch_to.window(cur)
        except Exception:
            pass
    return found


def unlock_pw_window(driver, password: str, log=None, wait: float = 0) -> str:
    """'처리암호' 창이 떠 있으면 홈넷 비밀번호를 넣어 연다.
    돌려주는 값: '' 창 없음 · 'unlocked' 열림 · 'failed' 비밀번호가 없거나 틀려서 못 엶(창은 닫는다)."""
    from selenium.webdriver.common.by import By
    end = time.time() + wait
    while True:
        win = _pw_window(driver)
        if win or time.time() >= end:
            break
        time.sleep(0.5)
    if not win:
        return ""

    def cancel():
        try:
            driver.switch_to.window(win)
            driver.execute_script("var b=document.getElementById('nbutton_BtnCancel-button');"
                                  "if(b){b.click();}else if(window.closeThisWindow){closeThisWindow();}"
                                  "else{window.close();}")
        except Exception:
            pass
        time.sleep(0.5)
        if win in driver.window_handles:
            try:
                driver.switch_to.window(win)
                driver.close()
            except Exception:
                pass
        driver.switch_to.window(driver.window_handles[0])

    if not password:
        if log:
            log("  보안 문서인데 홈넷 비밀번호가 없어 열지 못합니다(① 계정에 비밀번호를 넣어 주세요).")
        cancel()
        return "failed"
    driver.switch_to.window(win)
    box = driver.find_element(By.ID, "Passwd")
    box.clear()
    box.send_keys(password)
    driver.execute_script("var b=document.getElementById('nbutton_BtnSubmit-button');"
                          "if(b){b.click();}else if(window.OkBtn_Click){OkBtn_Click();}")
    stop = time.time() + 8
    while time.time() < stop:
        try:
            a = driver.switch_to.alert             # '처리암호가 틀립니다' 등
            msg = (a.text or "").strip()
            a.accept()
            if log:
                log(f"  보안 문서 비밀번호가 맞지 않습니다: {msg[:60]}")
            cancel()
            return "failed"
        except Exception:
            pass
        if win not in driver.window_handles:
            if log:
                log("  보안 문서라 홈넷 비밀번호를 넣어 열었습니다.")
            return "unlocked"
        time.sleep(0.4)
    if log:
        log("  보안 문서 비밀번호 창이 닫히지 않아 건너뜁니다.")
    cancel()
    return "failed"


def dismiss_password(driver) -> None:
    """암호 입력 창을 닫는다([취소]/[닫기], 없으면 Esc)."""
    try:
        for _ in _contexts(driver):
            try:
                if driver.execute_script(_JS_DISMISS_PW):
                    driver.switch_to.default_content()
                    return
            except Exception:
                continue
        driver.switch_to.default_content()
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.keys import Keys
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    except Exception:
        pass


def clean_binder(raw: str) -> str:
    """대장의 편철 '임대보증금관계철(1)' → 기록물철 이름 '임대보증금관계철' (뒤의 (숫자)는 권호)."""
    return binder_rules.clean(raw)


def parse_doc_info(raw: str) -> dict:
    """[문서정보](결재정보) 창의 글자에서 편철·구분을 읽는다."""
    binder = ""
    for line in raw.split("\n"):
        m = re.match(r"^\[([^\]]*)\]\s*(.+)$", line.strip())
        if m and re.search(r"abinet|inder|편철", m.group(1)) and m.group(2).strip():
            binder = m.group(2).strip()
            break
    if not binder:
        lines = [l.strip() for l in raw.split("\n")]
        for i, l in enumerate(lines):
            m = re.match(r"^편\s*철\s*[:：\t ]*\s*(.*)$", l)
            if not m:
                continue
            val = m.group(1).strip()
            if not val or val in ("설정", "선택"):
                val = next((x for x in lines[i + 1:i + 4] if x and x not in ("설정", "선택")), "")
            val = re.sub(r"\s*(설정|선택)$", "", val).strip()
            if val and not re.match(r"^(문서|공개|보존|비공개|결재)", val):
                binder = val
                break
    kind = re.search(r"구\s*분\s*[:：\t ]*\s*(생산|접수)", raw)
    doc_no = re.search(r"문\s*서\s*번\s*호\s*[:：\t ]*\s*([^\s\t|]+-\d+)", raw)
    day = re.search(r"기\s*안\s*일\s*자\s*[:：\t ]*\s*(\d{4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}\.?)", raw)
    return {"binder_raw": binder, "binder": clean_binder(binder), "kind": kind.group(1) if kind else "",
            "doc_no": doc_no.group(1) if doc_no else "",
            "date": re.sub(r"\s+", "", day.group(1)) if day else ""}


def read_doc_info(driver, viewer: str, log=None) -> dict:
    """[문서정보]를 열어 편철·구분을 읽는다. 읽지 못해도 빈 값으로 돌려준다(수집은 계속한다)."""
    info = {"raw": "", "binder_raw": "", "binder": "", "kind": "", "doc_no": "", "date": ""}
    win = None
    try:
        driver.switch_to.window(viewer)
        before = set(driver.window_handles)
        clicked = False
        from selenium.webdriver.common.by import By
        for _ in _contexts(driver):
            els = [e for e in driver.find_elements(By.XPATH, _XPATH_INFO) if e.is_displayed()]
            if els:
                driver.execute_script("arguments[0].click();", els[-1])
                clicked = True
                break
        driver.switch_to.default_content()
        if not clicked:
            return info
        end = time.time() + 8
        while time.time() < end and win is None:
            new = set(driver.window_handles) - before
            if new:
                win = new.pop()
            else:
                time.sleep(0.4)
        if win:
            driver.switch_to.window(win)
        time.sleep(1.5)
        parts = []
        for _ in _contexts(driver):
            try:
                parts.append(driver.execute_script(_JS_FORM_TEXT) or "")
            except Exception:
                continue
        driver.switch_to.default_content()
        info["raw"] = "\n".join(parts)
        info.update(parse_doc_info(info["raw"]))
    except Exception as ex:
        if log:
            log(f"  (문서정보를 읽지 못했습니다: {type(ex).__name__})")
    finally:
        try:
            if win and win in driver.window_handles and win != viewer:
                driver.switch_to.window(win)
                driver.close()
            elif win is None:
                dismiss_password(driver)            # 창이 아니라 레이어로 떴으면 Esc로 닫는다
            driver.switch_to.window(viewer)
        except Exception:
            pass
    return info


def click_next(driver) -> bool:
    """[다음] 버튼을 누른다. 못 찾으면 False."""
    from selenium.webdriver.common.by import By
    for _ in _contexts(driver):
        els = [e for e in driver.find_elements(By.XPATH, _XPATH_NEXT) if e.is_displayed()]
        if els:
            driver.execute_script("arguments[0].click();", els[-1])
            driver.switch_to.default_content()
            return True
    driver.switch_to.default_content()
    return False


def _new_view_window(driver, known) -> str | None:
    """[다음]으로 새로 뜬 '조회' 창(view_handdocument)이 있으면 그 핸들. 지금 창으로 돌아온다."""
    cur = driver.current_window_handle
    found = None
    for h in driver.window_handles:
        if h in known or h == cur:
            continue
        try:
            driver.switch_to.window(h)
            if VIEW_ONLY_URL in (driver.current_url or ""):
                found = h
                break
        except Exception:
            continue
    driver.switch_to.window(cur)
    return found


def _view_doc(driver, handle: str) -> dict:
    """'조회' 화면 글자를 읽어 건너뛸 때 쓸 정보로."""
    try:
        driver.switch_to.window(handle)
        text = driver.execute_script(_JS_PAGE_TEXT) or ""
    except Exception:
        text = ""
    return {"handle": handle, "text": text, "title": view_title(text)}


def wait_new_doc(driver, last_fp: str, log=None, tries: int = 6, password: str = "", known=frozenset()):
    """다음 문서가 뜰 때까지 기다린다.
    ('doc', 문서) · ('view', 조회 화면 정보) · ('encrypted', None) · ('same', None)

    - 'view': 본문 없는 '조회' 화면(지금 창이 바뀌었거나 새 창으로 뜸). 저장하지 않고 건너뛴다.
    - 암호(보안) 문서는 password(홈넷 비밀번호)를 한 번 넣어 열어 본다. 열리면 doc['unlocked'] = True.
    known: [다음]을 누르기 전에 있던 창들(새로 뜬 '조회' 창을 알아보려고).
    """
    unreadable = 0
    tried_pw = False
    attempt = 0
    while attempt < tries:
        attempt += 1
        pw = unlock_pw_window(driver, "" if tried_pw else password, log)   # 따로 뜬 '처리암호' 창
        if pw == "failed":
            return "encrypted", None
        if pw == "unlocked":
            tried_pw = True
            time.sleep(2)
            viewer = _viewer_handle(driver, known) or _viewer_handle(driver)   # 열린 문서 창으로
            if viewer:
                driver.switch_to.window(viewer)
            attempt = max(0, attempt - 1)
            continue
        st = drain_alerts(driver, log, "" if tried_pw else password)
        if known:
            popup = _new_view_window(driver, known)
            if popup:
                return "view", _view_doc(driver, popup)
        try:
            url = driver.current_url or ""
        except Exception:
            url = ""
        if VIEW_ONLY_URL in url:
            v = _view_doc(driver, driver.current_window_handle)
            if fingerprint(v["text"]) != last_fp:
                return "view", v
            time.sleep(2)
            continue
        if st == "unlocked":
            tried_pw = True
            if log:
                log("  보안 문서라 홈넷 비밀번호를 넣어 엽니다.")
            unlock_field(driver, password, None)     # 안내창 뒤에 암호 칸이 뜨는 경우
            time.sleep(2)
            continue
        if st == "encrypted":
            return "encrypted", None
        try:
            doc = read_doc(driver, log if attempt == tries else None)
        except CollectError:
            doc = None
        except Exception:
            drain_alerts(driver, log)
            doc = None
        if doc and fingerprint(doc["text"]) != last_fp and not _looks_like_pw_screen(doc["text"]):
            if not doc["html"] and is_view_only(doc["text"]):      # 주소는 달라도 '조회' 표만 읽힌 경우
                return "view", {"handle": driver.current_window_handle, "text": doc["text"],
                                "title": view_title(doc["text"])}
            doc["viewer"] = driver.current_window_handle     # 보안 문서는 문서 창이 새로 뜰 수 있다
            doc["unlocked"] = tried_pw or doc["viewer"] in UNLOCKED_VIEWERS
            UNLOCKED_VIEWERS.discard(doc["viewer"])
            return "doc", doc
        if not doc:
            unreadable += 1
        if password_prompt(driver):
            if password and not tried_pw and unlock_field(driver, password, log):
                tried_pw = True
                attempt = max(0, attempt - 1)        # 비밀번호를 넣은 뒤 다시 충분히 기다린다
                time.sleep(2)
                continue
            return "encrypted", None
        time.sleep(2)
    if unreadable >= tries - 1:
        return "encrypted", None            # 계속 읽히지 않으면 열 수 없는(암호) 문서로 보고 넘어간다
    return "same", None


def _looks_like_pw_screen(text: str) -> bool:
    """본문 대신 '암호를 입력하세요' 화면 글자만 읽힌 경우."""
    t = (text or "").strip()
    return len(t) < 400 and bool(_ENC_WORDS.search(t)) and not re.search(r"제\s*목|수\s*신", t)


_JS_OPEN_ROW = r"""
var i = arguments[0], o = window.DocumentList;
if (!o || o.GetListCount() <= i) return 'empty';
try { o.SetSelectedIndex(i); } catch (e) {}
var names = ['DoOpen', 'DoView', 'OpenDocument', 'ViewDocument', 'DocumentList_ItemDblClicked',
             'DocumentList_ItemDoubleClicked', 'DocumentList_DblClick'];
for (var k = 0; k < names.length; k++) {
  if (typeof window[names[k]] === 'function') { try { window[names[k]](); return names[k]; } catch (e) {} }
}
return 'none';
"""


def _viewer_handle(driver, ignore=frozenset()) -> str | None:
    for h in driver.window_handles:
        if h in ignore:
            continue
        try:
            driver.switch_to.window(h)
            if any(p in (driver.current_url or "") for p in VIEWER_URL_PARTS):
                return h
        except Exception:
            continue
    return None


def row_after(rows: list[dict], title: str) -> int | None:
    """대장 목록 줄들([{'text': [...]}])에서 제목이 title인 줄의 다음 줄 번호. 못 찾으면 None."""
    key = re.sub(r"\s+", "", title or "")
    if not key:
        return None
    for i, row in enumerate(rows):
        if any(key == re.sub(r"\s+", "", t or "") for t in row.get("text", [])):
            return i + 1 if i + 1 < len(rows) else None
    return None


CURRENT_PAGE = 1     # 마지막으로 연 대장 목록 쪽(다음 줄을 찾을 때 이 쪽부터 본다)


def _shown(key) -> str:
    return key if isinstance(key, str) else (key[-1] if key else "")


def row_index(rows: list[dict], key) -> int | None:
    """대장 목록 줄들에서 칸 글자가 key(제목 또는 문서번호, 여럿이면 그중 하나)와 같은 줄 번호.
    문서번호를 먼저 견준다(같은 제목이 여러 줄이어도 헷갈리지 않게)."""
    keys = [re.sub(r"\s+", "", k or "") for k in ((key,) if isinstance(key, str) else key)]
    for k in [k for k in keys if k]:
        for i, row in enumerate(rows):
            if any(k == re.sub(r"\s+", "", t or "") for t in row.get("text", [])):
                return i
    return None


_DOC_NO_RE = re.compile(r"(?:시행|접수)\s*([^\s()]+-\d+)")


def doc_numbers(text: str) -> tuple:
    """본문 아래 '시행 ○○관리소-123 (날짜) 접수 ○○-45'에서 문서번호들(대장의 등록번호와 견줄 것)."""
    return tuple(dict.fromkeys(m.group(1) for m in _DOC_NO_RE.finditer(text or "")))


def open_first_doc(driver, keyword: str, log, after_title: str = "", year: int | None = None,
                   password: str = "", start_row: int = 0, page: int = 1) -> str:
    """기록물등록대장을 열어(검색어가 있으면 제목 검색) 맨 위 문서를 연다. 문서 창 핸들을 돌려준다.
    after_title을 주면 그 제목 줄의 다음 줄 문서를 연다('조회' 화면에 [다음]이 없을 때 이어 가기).
    year를 주면 그 해 대장(생산연도)에서 연다. 비우면 홈넷 기본(올해).
    보안 문서면 password(홈넷 비밀번호)로 '처리암호' 창을 연다. 못 열면 그다음 줄 문서를 연다."""
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By

    import json

    import ledger
    log("전자결재 → 대장관리 → 기록물등록대장을 엽니다..." if not after_title
        else f"  대장 목록에서 '{_shown(after_title)}' 다음 문서를 엽니다...")
    ledger.open_register(driver)
    if year:
        if not after_title:
            log(f"  연도: {year}년 대장")
        try:
            ledger.select_year(driver, year)
        except ledger.LedgerError as ex:
            driver.switch_to.default_content()
            raise CollectError(str(ex)) from None
    if keyword.strip():
        log(f"  제목 검색: {keyword.strip()}")
        ledger.search_register(driver, keyword.strip())
    end = time.time() + 20
    while time.time() < end:
        time.sleep(1)
        try:
            n = driver.execute_script("return window.DocumentList ? DocumentList.GetListCount() : -1;")
        except Exception:
            n = -1
        if n and n > 0:
            break
    else:
        driver.switch_to.default_content()
        raise CollectError("기록물등록대장" + (f"({year}년)" if year else "") + " 목록에 문서가 없습니다."
                           + (" 검색어를 확인해 주세요." if keyword else ""))
    time.sleep(1)
    global CURRENT_PAGE
    pages = ledger.total_pages(driver)
    page = max(1, min(page, pages))
    rows = ledger.go_page(driver, page, keyword.strip()) if page > 1 else ledger.list_rows(driver)
    row = start_row
    if after_title:
        # 대장 목록은 한 쪽에 50줄이다. 문서 창의 [다음]은 쪽을 넘지 못하므로 목록에서 다음 줄(다음 쪽)을 찾는다.
        row = None
        for pg in range(page, min(pages, page + 3) + 1):
            if pg != page:
                rows = ledger.go_page(driver, pg, keyword.strip())
            idx = row_index(rows, after_title)
            if idx is None:
                continue
            page = pg
            if idx + 1 < len(rows):
                row = idx + 1
            elif pg < pages:                       # 그 쪽 마지막 줄 → 다음 쪽 첫 줄
                page = pg + 1
                rows = ledger.go_page(driver, page, keyword.strip())
                row = 0
            break
        if row is None:
            driver.switch_to.default_content()
            raise CollectError(f"대장 목록에서 '{_shown(after_title)}' 다음 문서를 찾지 못했습니다(마지막 문서일 수 있음).")
    elif rows and row >= len(rows) and page < pages:   # 앞 쪽 끝을 넘은 줄 → 다음 쪽
        row -= len(rows)
        page += 1
        rows = ledger.go_page(driver, page, keyword.strip())
    CURRENT_PAGE = page
    if page > 1 and not after_title and start_row == 0:
        log(f"  대장 {page}쪽")
    before = frozenset(driver.window_handles)
    how = driver.execute_script(_JS_OPEN_ROW, row)

    unlocked_here = False

    def wait_viewer(sec):
        nonlocal unlocked_here
        stop = time.time() + sec
        while time.time() < stop:
            drain_alerts(driver)
            pw = unlock_pw_window(driver, password, log)      # 보안 문서: '처리암호' 창
            if pw == "failed":
                return "LOCKED"
            if pw == "unlocked":
                unlocked_here = True
                stop = max(stop, time.time() + 10)            # 비밀번호를 넣은 뒤 문서 창을 충분히 기다린다
            h = _viewer_handle(driver, before)
            if h:
                return h
            time.sleep(0.5)
        return None

    def next_row():
        if row >= 30:
            raise CollectError("보안 문서를 열지 못해 대장의 문서를 열 수 없습니다.")
        log("  보안 문서를 열지 못해 그다음 문서를 엽니다.")
        return open_first_doc(driver, keyword, log, year=year, password=password, start_row=row + 1, page=page)

    handle = wait_viewer(8) if how not in ("none", "empty") else None
    if handle == "LOCKED":
        return next_row()
    if handle is None:                     # 함수로 안 열리면 첫 줄을 실제로 더블클릭한다
        import homnet
        driver.switch_to.window(homnet.main_window(driver))
        driver.switch_to.default_content()
        driver.switch_to.frame("linkageIframe")
        driver.switch_to.frame("contentview")
        rows = driver.find_elements(By.CSS_SELECTOR, "tbody.yui-dt-data tr")
        if len(rows) > row:
            cells = rows[row].find_elements(By.CSS_SELECTOR, "td")
            target = cells[min(4, len(cells) - 1)] if cells else rows[row]
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", target)
            ActionChains(driver).move_to_element(target).double_click(target).perform()
            handle = wait_viewer(15)
            if handle == "LOCKED":
                return next_row()
    if handle is None:
        raise CollectError("대장의 문서를 자동으로 열지 못했습니다. 기록물등록대장에서 첫 문서를 "
                           "더블클릭해 연 뒤 다시 실행해 주세요.")
    if unlocked_here:
        UNLOCKED_VIEWERS.add(handle)
    log("✅ 대장 문서 창을 열었습니다.")
    return handle



# ---------------- 첨부파일 받기 · 본문 PDF ----------------
# 첨부 목록의 파일 이름(…pdf, …hwp 등)을 눌러 받는다. 홈넷 화면 모양이 바뀌어도 되도록 글자로 찾는다.
ATTACH_EXT = ("pdf", "hwp", "hwpx", "hwt", "doc", "docx", "xls", "xlsx", "xlsm", "csv", "ppt", "pptx",
              "jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "zip", "txt")
_ATTACH_NAME_RE = re.compile(r"[^\\/:*?\"<>|\r\n\t]{1,150}\.(?:" + "|".join(ATTACH_EXT) + r")(?![A-Za-z0-9])",
                             re.IGNORECASE)

# 눌러서 받을 수 있는 첨부 이름 칸: 파일 이름 글자가 있는 a·span·td·div·li 중 가장 안쪽(자식에 같은 글자가 없는 것)
_JS_ATTACH_LINKS = r"""
var re = new RegExp(arguments[0], 'i'), out = [];
var els = document.querySelectorAll('a, span, td, div, li, label, button');
for (var i = 0; i < els.length; i++) {
  var e = els[i], t = (e.innerText || e.textContent || '').trim();
  if (!t || t.length > 200 || !re.test(t)) continue;
  var inner = false;
  for (var k = 0; k < e.children.length; k++) {
    if (re.test((e.children[k].innerText || e.children[k].textContent || '').trim())) { inner = true; break; }
  }
  if (inner) continue;
  var r = e.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) continue;
  e.setAttribute('data-kodas-attach', String(out.length));
  out.push(t);
}
return out;
"""

_XPATH_DOWN_ALL = ("//*[(self::button or self::a or self::span or self::input or self::img or self::div)"
                   " and (contains(normalize-space(.),'전체 다운') or contains(normalize-space(.),'일괄 다운')"
                   " or contains(normalize-space(.),'전체저장') or contains(@value,'전체 다운')"
                   " or contains(@alt,'전체 다운') or contains(@title,'전체 다운') or contains(@title,'전체저장')"
                   " or contains(@id,'all_download'))]")


def attach_names(text: str) -> list[str]:
    """글자에서 첨부 파일 이름을 뽑는다(같은 이름은 한 번만)."""
    seen, out = set(), []
    for m in _ATTACH_NAME_RE.finditer(text or ""):
        name = re.sub(r"^\s*(?:\d+\.\s*|[-·•]\s*|첨부\s*[:：]?\s*)+", "", m.group(0)).strip()
        name = re.sub(r"\s*\(\s*[\d.,]+\s*(?:[KMG]?B|바이트)\s*\)\s*$", "", name, flags=re.IGNORECASE)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def _set_download_dir(driver, folder: str) -> None:
    os.makedirs(folder, exist_ok=True)
    try:
        driver.execute_cdp_cmd("Browser.setDownloadBehavior",
                               {"behavior": "allow", "downloadPath": folder, "eventsEnabled": False})
    except Exception:
        driver.execute_cdp_cmd("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": folder})


def _wait_downloads(folder: str, before: set, timeout: float = 30) -> list[str]:
    """folder에 새로 생긴 파일이 다 받아질 때까지 기다린다(.crdownload·.tmp가 없어질 때까지)."""
    end, last, stable = time.time() + timeout, None, 0
    while time.time() < end:
        time.sleep(0.5)
        now = set(os.listdir(folder)) - before
        busy = [n for n in now if n.endswith((".crdownload", ".tmp", ".partial"))]
        done = sorted(n for n in now if n not in busy)
        if done and not busy:
            if done == last:
                stable += 1
                if stable >= 2:
                    return [os.path.join(folder, n) for n in done]
            else:
                last, stable = done, 0
    now = set(os.listdir(folder)) - before
    return [os.path.join(folder, n) for n in sorted(now) if not n.endswith((".crdownload", ".tmp", ".partial"))]


def download_attachments(driver, viewer: str, folder: str, log=None) -> list[str]:
    """열려 있는 대장 문서의 첨부파일을 folder로 받는다. 받은 파일 경로 목록.

    첨부 이름을 하나씩 누르고, 없으면 [전체 다운로드]를 눌러 본다. 새로 뜬 창·알림은 닫는다.
    아무것도 받지 못하면 화면 구조를 logs\\attach_probe.html로 남긴다(다음 수정 때 참고).
    """
    from selenium.webdriver.common.by import By
    _set_download_dir(driver, folder)
    got: list[str] = []
    names_seen: list[str] = []
    driver.switch_to.window(viewer)
    keep = set(driver.window_handles)
    found, files = _homnet_filelist(driver, viewer, folder, keep, log)
    if found:                                     # 홈넷 첨부 목록(오른쪽 '첨부파일' 칸)이 있으면 그것으로 끝
        return files
    pattern = _ATTACH_NAME_RE.pattern
    for ctx in _contexts(driver):
        try:
            names = driver.execute_script(_JS_ATTACH_LINKS, pattern) or []
        except Exception:
            continue
        for i, name in enumerate(names):
            if name in names_seen:
                continue
            names_seen.append(name)
            before = set(os.listdir(folder))
            try:
                el = driver.find_element(By.CSS_SELECTOR, f'[data-kodas-attach="{i}"]')
                driver.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", el)
            except Exception as ex:
                if log:
                    log(f"    첨부 '{name}'을(를) 누르지 못함: {type(ex).__name__}")
                continue
            drain_alerts(driver)
            files = _wait_downloads(folder, before, timeout=25)
            _close_new_windows(driver, keep, viewer, ctx)
            got += [f for f in files if f not in got]
            if log:
                log(f"    첨부 받음: {', '.join(os.path.basename(f) for f in files)}" if files
                    else f"    첨부 '{name}'을(를) 눌렀지만 받은 파일이 없습니다")
    driver.switch_to.default_content()
    if not got:                                   # 이름을 못 찾았으면 [전체 다운로드] 단추를 눌러 본다
        for _ in _contexts(driver):
            els = [e for e in driver.find_elements(By.XPATH, _XPATH_DOWN_ALL) if e.is_displayed()]
            if els:
                before = set(os.listdir(folder))
                driver.execute_script("arguments[0].click();", els[0])
                drain_alerts(driver)
                got = _wait_downloads(folder, before, timeout=40)
                break
        driver.switch_to.default_content()
        _close_new_windows(driver, keep, viewer, None)
    if not got and names_seen and log:
        log("    첨부 이름은 보이지만 받지 못했습니다(화면 구조를 logs\\attach_probe.html로 남김)")
    if not got and names_seen:
        _save_viewer_probe(driver, viewer)
    return got


# 홈넷 대장 문서 창 오른쪽 '첨부파일' 칸: FileList 위젯(AttachList). 줄마다 div#AttachList_list_N이고
# 이름(title)에는 확장자가 없다(아이콘 그림 file_pdf.png로 종류를 안다). 줄을 두 번 누르면 받는다.
_JS_FILELIST = r"""
var out = [], els = document.querySelectorAll('div[id^="AttachList_list_"]');
for (var i = 0; i < els.length; i++) {
  var e = els[i];
  out.push([e.id, e.getAttribute('title') || (e.innerText || '').trim()]);
}
return out;
"""

_JS_DBLCLICK = r"""
var e = document.getElementById(arguments[0]);
if (!e) return false;
e.scrollIntoView({block: 'center'});
['mousedown', 'mouseup', 'click', 'mousedown', 'mouseup', 'click', 'dblclick'].forEach(function (t) {
  e.dispatchEvent(new MouseEvent(t, {bubbles: true, cancelable: true, view: window, detail: t === 'dblclick' ? 2 : 1}));
});
return true;
"""


def _homnet_filelist(driver, viewer: str, folder: str, keep: set, log=None) -> tuple[bool, list[str]]:
    """홈넷 첨부 목록에서 줄마다 두 번 눌러 받는다. (첨부 목록이 있었는지, 받은 파일)"""
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    got: list[str] = []
    for ctx in _contexts(driver):
        try:
            items = driver.execute_script(_JS_FILELIST) or []
        except Exception:
            continue
        if not items:
            continue
        for item_id, name in items:
            before = set(os.listdir(folder))
            try:
                el = driver.find_element(By.ID, item_id)
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                ActionChains(driver).double_click(el).perform()
            except Exception:
                driver.execute_script(_JS_DBLCLICK, item_id)     # 화면 밖이면 스크립트로 두 번 누른다
            drain_alerts(driver)
            files = _wait_downloads(folder, before, timeout=40)
            if not files:                                         # 한 번 더(느린 서버)
                driver.execute_script(_JS_DBLCLICK, item_id)
                drain_alerts(driver)
                files = _wait_downloads(folder, before, timeout=40)
            _close_new_windows(driver, keep, viewer, ctx)
            got += [f for f in files if f not in got]
            if log:
                log(f"    첨부 받음: {', '.join(os.path.basename(f) for f in files)}" if files
                    else f"    첨부 '{name}'을(를) 받지 못했습니다")
        driver.switch_to.default_content()
        return True, got
    driver.switch_to.default_content()
    return False, got


def _close_new_windows(driver, keep: set, viewer: str, ctx) -> None:
    """첨부를 누를 때 새로 뜬 창(내려받기 창 등)을 닫고 문서 창으로 돌아온다."""
    for h in list(driver.window_handles):
        if h in keep:
            continue
        try:
            driver.switch_to.window(h)
            driver.close()
        except Exception:
            pass
    driver.switch_to.window(viewer)
    if ctx and ctx != "top":                      # 첨부 목록이 있던 iframe으로 다시 들어간다
        for name in _contexts(driver):
            if name == ctx:
                return


def _save_viewer_probe(driver, viewer: str) -> None:
    try:
        import paths
        driver.switch_to.window(viewer)
        parts = []
        for name in _contexts(driver):
            parts.append(f"<!-- {name} -->\n" + (driver.page_source or "")[:400000])
        driver.switch_to.default_content()
        with open(os.path.join(paths.sub_dir("logs"), "attach_probe.html"), "w", encoding="utf-8") as f:
            f.write("\n".join(parts))
    except Exception:
        pass


def unzip_here(path: str) -> list[str]:
    """받은 zip(전체 다운로드)을 같은 폴더에 풀고 풀린 파일 목록을 돌려준다. zip은 지운다."""
    import zipfile
    folder = os.path.dirname(path)
    out = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            raw = info.filename
            if not info.flag_bits & 0x800:        # 한글 이름이 cp437로 적힌 zip(윈도에서 만든 zip)
                try:
                    raw = raw.encode("cp437").decode("cp949")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            name = os.path.basename(raw.replace("\\", "/"))
            if not name:
                continue
            dst = os.path.join(folder, name)
            with z.open(info) as src, open(dst, "wb") as f:
                f.write(src.read())
            out.append(dst)
    os.remove(path)
    return out


def mask_attachments(files: list[str], dest: str, log=None, extra=(), keep_phones=(), known=()) -> dict:
    """받은 첨부를 dest로 옮긴다. PDF는 이름·동호수·연락처를 000으로 가린 것만 남긴다(원본은 지운다).

    PDF가 아닌 파일(hwp·엑셀·그림 등)은 가리지 못하므로 그대로 옮기고 목록에 표시한다.
    """
    import shutil
    import privacy
    os.makedirs(dest, exist_ok=True)
    res = {"pdf": 0, "masked": 0, "other": [], "scanned": [], "locked": []}
    queue = list(files)
    while queue:
        f = queue.pop(0)
        if f.lower().endswith(".zip"):
            try:
                queue += unzip_here(f)
            except Exception as ex:
                if log:
                    log(f"    zip을 풀지 못함: {os.path.basename(f)} ({ex})")
            continue
        base = os.path.basename(f)
        dst = _free_name(dest, base)
        if f.lower().endswith(".pdf"):
            try:
                r = privacy.mask_pdf(f, dst, extra, keep_phones, known)
                os.remove(f)
                res["pdf"] += 1
                res["masked"] += r["masked"]
                if r["scanned"] and r["scanned"] == r["pages"]:     # 모든 쪽이 그림(스캔): 이름에 표시
                    marked = _free_name(dest, _tag(base, "스캔본·가리지 못함"))
                    os.replace(dst, marked)
                    dst = marked
                if r["scanned"]:
                    res["scanned"].append(os.path.basename(dst))
                if log:
                    log(f"    PDF 가림: {os.path.basename(dst)} — {privacy.summary(r['kinds'])}"
                        + (f" (글자 없는 스캔 쪽 {r['scanned']}쪽은 가리지 못함)" if r["scanned"] else ""))
            except privacy.PdfLocked:
                # 암호가 걸린 PDF는 열 수 없어 가리지 못한다. 암호 없이는 아무도 못 보니 그대로 두고 이름에 표시한다
                dst = _free_name(dest, _tag(base, "암호·가리지 못함"))
                shutil.move(f, dst)
                res["locked"].append(os.path.basename(dst))
                if log:
                    log(f"    암호가 걸린 PDF라 가리지 못하고 그대로 둡니다: {os.path.basename(dst)}")
            except Exception as ex:
                if log:
                    log(f"    PDF를 가리지 못해 받지 않았습니다: {base} ({type(ex).__name__})")
                os.remove(f)
        else:
            shutil.move(f, dst)
            res["other"].append(os.path.basename(dst))
    return res


def _tag(name: str, note: str) -> str:
    stem, ext = os.path.splitext(name)
    return f"{stem} ({note}){ext}"


def _free_name(folder: str, name: str) -> str:
    """folder 안에서 겹치지 않는 파일 경로('이름 (2).pdf'처럼)."""
    path, k = os.path.join(folder, name), 2
    while os.path.exists(path):
        stem, ext = os.path.splitext(name)
        path = os.path.join(folder, f"{stem} ({k}){ext}")
        k += 1
    return path


def masked_pdf_html(html: str, text: str, title: str, extra=(), keep_phones=()) -> tuple[str, list]:
    """본문 HTML(없으면 글자)의 개인정보를 000으로 가려 PDF로 찍을 HTML로. (HTML, 가린 목록)"""
    import html as _h
    import privacy
    found = privacy.find_private((text or "") + "\n" + re.sub(r"<[^>]+>", " ", _h.unescape(html or "")),
                                 extra, keep_phones)
    if html and html.strip():
        body, _ = privacy.mask_html(html, found=found)
    else:
        masked, _ = privacy.mask_text(text or "", found=found)
        body = ("<html><head><meta charset='utf-8'><title>" + _h.escape(title or "") + "</title></head>"
                "<body style=\"font-family:'굴림',Gulim,sans-serif;font-size:12pt;\">"
                "<pre style=\"white-space:pre-wrap;font-family:inherit;\">" + _h.escape(masked) + "</pre></body></html>")
    if "<meta charset" not in body.lower():
        body = "<meta charset='utf-8'>" + body
    return body, found


def html_to_pdf(driver, html: str, path: str) -> None:
    """브라우저(크롬·엣지)로 HTML을 A4 PDF로 찍는다. 새 탭에서 찍고 닫는다."""
    import base64
    home = driver.current_window_handle
    driver.switch_to.new_window("tab")
    try:
        driver.get("about:blank")
        driver.execute_script("document.open(); document.write(arguments[0]); document.close();", html)
        time.sleep(0.8)
        res = driver.execute_cdp_cmd("Page.printToPDF", {
            "printBackground": True, "paperWidth": 8.27, "paperHeight": 11.69,
            "marginTop": 0.6, "marginBottom": 0.6, "marginLeft": 0.6, "marginRight": 0.6})
        with open(path, "wb") as f:
            f.write(base64.b64decode(res["data"]))
    finally:
        driver.close()
        driver.switch_to.window(home)


def make_pdfs(driver, out_dir: str, names: list, log=print, extra=(), keep_phones=()) -> int:
    """저장한 문서마다 이름·동호수·연락처를 000으로 가린 PDF를 out_dir\\PDF에 만든다. 만든 수."""
    import privacy
    pdf_dir = os.path.join(out_dir, "PDF")
    os.makedirs(pdf_dir, exist_ok=True)
    made = 0
    for name in names:
        def read(ext):
            p = os.path.join(out_dir, name + ext)
            if not os.path.isfile(p):
                return ""
            with open(p, encoding="utf-8-sig") as f:
                return f.read()
        try:
            html, found = masked_pdf_html(read(".html"), read(".txt"), name, extra, keep_phones)
            pdf = os.path.join(pdf_dir, name + ".pdf")
            html_to_pdf(driver, html, pdf)
            # 찍힌 PDF에 남은 개인정보가 있으면 한 번 더 가린다(HTML 태그가 이름을 둘로 나눈 경우 등)
            left = [x for x in found if x[0] in privacy.pdf_text(pdf)]
            if left:
                tmp = pdf + ".tmp"
                os.replace(pdf, tmp)
                privacy.mask_pdf(tmp, pdf, extra, keep_phones, found)
                os.remove(tmp)
            made += 1
            kinds = {}
            for _s, _r, kind in found:
                kinds[kind] = kinds.get(kind, 0) + 1
            log(f"  PDF: {name}.pdf — {privacy.summary(kinds)}")
        except Exception as ex:
            log(f"  PDF를 만들지 못함: {name} ({type(ex).__name__}: {ex})")
    return made


def import_to_templates(out_dir: str, names: list, dest: str, log=print, area: str = "주택관리") -> list:
    """수집한 문서({이름}.txt + .html + .meta.json)를 서식 파일로 바꿔 dest 폴더에 넣는다.

    area: 서식이 놓일 분야. '자동(편철)'이면 문서마다 편철(없으면 제목)로 분야를 정한다.
    서식 고르기에서는 편철 이름 묶음으로 보인다. 이미 같은 이름의 서식이 있으면 '(2)'처럼 붙여 덮어쓰지 않는다.
    만든 파일 경로 목록을 돌려준다.
    """
    import doc_template
    os.makedirs(dest, exist_ok=True)
    made = []
    for name in names:
        src = os.path.join(out_dir, name + ".txt")
        doc_area = area
        if area == binder_rules.AUTO:
            m = read_meta(out_dir, name)
            doc_area = binder_rules.area_for(m.get("편철", ""), m.get("제목", "") or name)
        try:
            with open(src, encoding="utf-8-sig") as f:
                text = doc_template.from_collected(f.read(), src, doc_area)
            doc_template.parse(text, src)                     # 서식으로 읽히는지 확인
        except (OSError, ValueError, UnicodeDecodeError) as ex:
            log(f"  서식으로 바꾸지 못함: {name} ({ex})")
            continue
        # 파일 이름도 개인정보를 가린 제목으로('…(105동 814호)' → '…(○)')
        title = doc_template.parse(text, src).title
        base = safe_name(re.sub(r"\{[^{}]*\}", "○", title), 0, set()) or name
        k = 2
        path = os.path.join(dest, base + ".txt")
        while os.path.exists(path):
            path = os.path.join(dest, f"{base} ({k}).txt")
            k += 1
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        made.append(path)
        log(f"  서식: {os.path.basename(path)} → [{doc_area}] {doc_template.parse(text, path).bundle}")
    return made


def _take_attachments(driver, handle, out_dir, name, doc, att, log, extra, keep_phones) -> None:
    """지금 문서의 첨부를 받아 첨부\\{name}에 넣는다(PDF는 000으로 가림). 실패해도 모으기는 계속한다."""
    import privacy
    tmp = os.path.join(out_dir, "_받는중")
    try:
        files = download_attachments(driver, handle, tmp, log)
        if files:
            known = privacy.find_private(doc.get("text", ""), extra, keep_phones)
            r = mask_attachments(files, os.path.join(out_dir, "첨부", name), log, extra, keep_phones, known)
            att["files"] += len(files)
            att["pdf"] += r["pdf"]
            att["masked"] += r["masked"]
            att["other"] += [os.path.join(name, x) for x in r["other"]]
            att["scanned"] += [os.path.join(name, x) for x in r["scanned"]]
            att["locked"] += [os.path.join(name, x) for x in r["locked"]]
    except Exception as ex:
        log(f"    첨부를 받지 못했습니다: {type(ex).__name__}: {ex}")
    finally:
        try:
            driver.switch_to.window(handle)
            driver.switch_to.default_content()
        except Exception:
            pass
        try:
            if os.path.isdir(tmp) and not os.listdir(tmp):
                os.rmdir(tmp)
        except OSError:
            pass


def _close_window(driver, h: str) -> None:
    """작업용 창 하나를 닫는다(홈넷 본 창은 닫지 않는다)."""
    import homnet
    try:
        if h in driver.window_handles and h != homnet.main_window(driver):
            driver.switch_to.window(h)
            driver.close()
    except Exception:
        pass


# ---------------- 이어 받기 ----------------
# 받은 폴더마다 진행 상태를 남겨 두고, 오류·[그만 받기]·프로그램 종료로 멈췄으면 다음에 그 다음 문서부터 이어 받는다.
PROGRESS_FILE = "_이어받기.json"


def load_progress(out_dir: str) -> dict:
    import json
    try:
        with open(os.path.join(out_dir, PROGRESS_FILE), encoding="utf-8-sig") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def save_progress(out_dir: str, state: dict) -> None:
    """진행 상태를 저장한다. 쓰는 도중 꺼져도 앞 상태가 남도록 임시 파일에 쓰고 바꿔 끼운다."""
    import json
    path = os.path.join(out_dir, PROGRESS_FILE)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError:
        pass


def unfinished(root: str) -> tuple:
    """root('수집' 폴더)에서 가장 최근에 받은 폴더가 끝까지 받지 못했으면 (폴더, 진행 상태). 아니면 (None, {})."""
    try:
        subs = sorted((d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))), reverse=True)
    except OSError:
        return None, {}
    for d in subs:
        st = load_progress(os.path.join(root, d))
        if not st:
            continue
        return (os.path.join(root, d), st) if not st.get("finished") else (None, {})
    return None, {}


def mark_finished(out_dir: str) -> None:
    """이어 받지 않기로 한 폴더: 다음부터 묻지 않는다."""
    st = load_progress(out_dir)
    if st:
        st["finished"] = True
        save_progress(out_dir, st)


def collect(driver, out_dir: str, count: int, log=print, only_internal: bool = False,
            password: str = "", keyword: str = "", auto_open: bool = True, pdf: bool = False,
            attachments: bool = False, extra=(), keep_phones=(), stop=None, binders=(),
            year: int | None = None, dedupe: bool = True, resume: bool = False,
            settings: dict | None = None) -> dict:
    """대장 문서부터 count개를 살펴보고 저장한다. 파일 이름은 문서 제목과 같다.

    - 대장 문서 창이 없고 auto_open이면 기록물등록대장을 열어 맨 위 문서부터 시작한다(keyword로 검색 가능).
    - 본문 없는 '조회' 화면(접수 등록 문서)은 저장하지 않고 건너뛴다. 그 화면에 [다음]이 없으면
      대장 목록으로 돌아가 그 문서 다음 줄부터 이어 간다.
    - 암호(보안) 문서는 password(홈넷 비밀번호)로 열어 본다. 안 열리면 건너뛴다.
    - only_internal이면 수신자가 따로 있는 문서·구분이 '접수'인 문서도 건너뛴다(기본은 모두 저장).
    - 저장: {제목}.txt · {제목}.html · {제목}.meta.json(편철 등) · {제목}.info.txt(결재정보 원문, 확인용)
    - pdf: 문서마다 이름·동호수·연락처를 000으로 가린 PDF를 PDF 폴더에 만든다.
    - attachments: 첨부파일을 첨부\\{제목} 폴더로 받는다. PDF 첨부는 000으로 가린 것만 남긴다.
    - extra: 꼭 가릴 글자(이름·동호수·연락처), keep_phones: 가리지 않을 전화번호(관리소 대표번호)
    - stop: threading.Event. 켜지면 지금 문서까지만 받고 멈춘다(받은 문서의 PDF·목록은 만든다)
    - 받는 도중 오류가 나도 그때까지 받은 문서의 목록·PDF는 만든다(돌려준 값의 'error'에 오류 내용).
    - 문서 하나를 볼 때마다 out_dir\\_이어받기.json에 어디까지 봤는지 적는다. resume이면 그 파일을 읽어
      마지막으로 본 문서의 다음 문서부터 이어 받는다(앞서 받은 문서·셈은 그대로 이어진다).
    - settings: 받기 설정(대화상자에서 고른 것). 이어 받을 때 그대로 쓰도록 진행 상태에 같이 적는다.
    - binders: 받을 편철 낱말(예: ['교육훈련', '시설관리']). 비우면 모든 편철. 다른 편철 문서는 건너뛴다.
    - year: 그 해(생산연도) 대장에서 받는다. 비우면 올해. 연도를 고르면 미리 열어 둔 문서 창은 쓰지 않는다.
    - dedupe: 날짜·월·동호수만 다른 비슷한 제목(예: '…급여 지급(2025.12월분)'·'(2025.11월분)')은
      처음 것 하나만 받는다.
    - 보안 문서(비밀번호로 연 문서)는 저장하기 전에 이름·동호수·연락처·주민번호를 OOO으로 바꾼다.
    - 끝나면 편철별 목록(편철별_목록.csv)과 편철별 폴더(편철별\\{편철}\\, 가린 PDF·첨부)를 만든다.
    """
    import json
    os.makedirs(out_dir, exist_ok=True)
    off_binder = 0
    state = load_progress(out_dir) if resume else {}
    saved_key = state.get("key")
    saved_key = tuple(saved_key) if isinstance(saved_key, list) else (saved_key or state.get("title") or "")
    resume_key = saved_key if resume else ""
    if resume_key:
        log(f"⏩ 지난번 멈춘 곳 다음부터 이어 받습니다({state.get('done', 0)}/{count}개째까지 봄, "
            f"마지막 문서: {state.get('title') or _shown(resume_key)}).")
        handle = open_first_doc(driver, keyword, log, after_title=resume_key, year=year, password=password,
                                page=int(state.get("page") or 1))
    else:
        try:
            if year and auto_open:                # 연도를 골랐으면 그 해 대장 맨 위부터
                raise CollectError("")
            handle = find_viewer(driver)          # 미리 열어 둔 대장 문서 창이 있으면 그 문서부터
        except CollectError:
            if not auto_open:
                raise
            handle = open_first_doc(driver, keyword, log, year=year, password=password)
    index, last, saved, internal, skipped, encrypted, used = [], "", 0, 0, 0, 0, set()
    similar, seen_keys = 0, {}
    names, unlocked, views = [], 0, 0
    att = {"files": 0, "pdf": 0, "masked": 0, "other": [], "scanned": [], "locked": []}
    consecutive_enc = 0
    known = frozenset(driver.window_handles)
    cur_title, last_view = "", ""
    stopped = False
    start = 0
    if state.get("done"):                     # 이어 받기: 앞서 받은 문서와 셈을 이어 간다
        c = state.get("counts") or {}
        start = min(int(state["done"]), count)
        names, index = list(state.get("names") or []), list(state.get("index") or [])
        used = {x.lower() for x in names}
        saved, internal, skipped = c.get("saved", 0), c.get("internal", 0), c.get("skipped", 0)
        encrypted, unlocked, views = c.get("encrypted", 0), c.get("unlocked", 0), c.get("views", 0)
        att.update(c.get("attach") or {})
        similar, off_binder = c.get("similar", 0), c.get("off_binder", 0)
        seen_keys = dict(c.get("seen_keys") or {})
    state.update(settings=settings if settings is not None else state.get("settings", {}),
                 count=count, finished=False)
    error = ""

    def checkpoint(n: int) -> None:
        """문서 n개째까지 봤다고 적는다(이어 받을 때 cur_title 다음 문서부터)."""
        state.update(done=n, title=cur_title, key=list(cur_key) if isinstance(cur_key, tuple) else cur_key,
                     page=CURRENT_PAGE, names=names, index=index,
                     counts={"saved": saved, "internal": internal, "skipped": skipped, "encrypted": encrypted,
                             "unlocked": unlocked, "views": views, "attach": att, "similar": similar,
                             "off_binder": off_binder, "seen_keys": seen_keys})
        save_progress(out_dir, state)

    def halted() -> bool:
        nonlocal stopped
        if stop is not None and stop.is_set() and not stopped:
            stopped = True
            log("⏹ 중단: 여기까지 받은 문서만 정리합니다.")
        return stopped

    def reopen_after(title) -> str | None:
        """[다음]으로 못 넘어갈 때: 지금 창을 닫고 대장 목록에서 title 다음 줄 문서를 연다."""
        if not (auto_open and title):
            return None
        _close_window(driver, handle)
        try:
            return open_first_doc(driver, keyword, log, after_title=title, year=year, password=password,
                                  page=CURRENT_PAGE)
        except CollectError as ex:
            log(f"  {ex}")
            return None

    try:
        cur_key, same_in_row, n = resume_key, 0, start
        while n < count:
            n += 1
            if halted():
                break
            try:
                driver.switch_to.window(handle)
            except Exception:
                raise CollectError("문서 창이 닫혀 있어 여기서 멈춥니다.")
            status, doc = wait_new_doc(driver, last, log, password=password, known=known)
            if status == "same":
                # 대장 목록 한 쪽(50줄)의 마지막 문서에서는 [다음]이 넘어가지 않는다 → 목록의 다음 쪽에서 이어 간다
                handle = reopen_after(cur_key or cur_title)
                if handle is None:
                    log("마지막 문서이거나 다음 문서로 넘어가지 않아 여기서 멈춥니다.")
                    break
                last, known = "", frozenset(driver.window_handles)
                same_in_row += 1
                if same_in_row >= 3:
                    log("다음 문서로 계속 넘어가지 않아 여기서 멈춥니다.")
                    break
                n -= 1                               # 문서를 본 것이 아니므로 셈하지 않는다
                continue
            same_in_row = 0
            if status == "view":
                views += 1
                title = doc["title"] or "(제목 못 읽음)"
                log(f"  {n}/{count} 저장하지 않음('조회' 화면·본문 없음): {title}")
                repeat = bool(doc["title"]) and doc["title"] == last_view
                last_view, cur_title = doc["title"], doc["title"]
                cur_key = doc_numbers(doc.get("text", "")) + (doc["title"],)
                checkpoint(n)
                if doc["handle"] != handle:                     # 새 창으로 뜬 '조회' 화면은 닫고 문서 창으로
                    _close_window(driver, doc["handle"])
                    driver.switch_to.window(handle)
                else:
                    last = fingerprint(doc["text"])
                if n == count:
                    break
                known = frozenset(driver.window_handles)
                if repeat or doc["handle"] == handle and not click_next(driver):
                    handle = reopen_after(cur_key or cur_title)
                    if handle is None:
                        log("'조회' 화면 다음 문서로 넘어가지 못해 여기서 멈춥니다.")
                        break
                    last, known = "", frozenset(driver.window_handles)
                elif doc["handle"] != handle and not click_next(driver):
                    log("[다음] 버튼을 찾지 못해 여기서 멈춥니다.")
                    break
                time.sleep(1.5)
                continue
            last_view = ""
            if status == "encrypted":
                encrypted += 1
                consecutive_enc += 1
                log(f"  {n}/{count} 암호가 걸린 문서라 건너뜁니다.")
                dismiss_password(driver)
                if consecutive_enc >= 15:
                    log("암호 문서가 계속 이어져 여기서 멈춥니다.")
                    break
            else:
                consecutive_enc = 0
                if doc.get("viewer") and doc["viewer"] != handle:   # 보안 문서를 비밀번호로 열면 문서 창이 바뀐다
                    if handle in driver.window_handles:
                        _close_window(driver, handle)
                    handle = doc["viewer"]
                    driver.switch_to.window(handle)
                last = fingerprint(doc["text"])
                raw_title = extract_meta(doc["text"])["title"]
                cur_key = doc_numbers(doc["text"]) + (raw_title,)   # 목록에서 이 문서 줄을 찾을 열쇠(가리기 전)
                if doc.get("unlocked"):            # 보안 문서: 받은 글자부터 인적사항을 OOO으로 바꿔 둔다
                    doc = _mask_secure_doc(doc, extra, keep_phones)
                meta = extract_meta(doc["text"])
                cur_title = meta["title"]
                key = similar_key(meta["title"])
                if dedupe and key and key in seen_keys:
                    similar += 1
                    log(f"  {n}/{count} 건너뜀(비슷한 제목을 이미 받음 — '{seen_keys[key]}'): {meta['title']}")
                elif only_internal and other_receiver(meta):
                    skipped += 1
                    log(f"  {n}/{count} 건너뜀(수신자 있음·접수): {meta['title'] or '(제목 못 읽음)'}")
                else:
                    info = read_doc_info(driver, handle, log)
                    if only_internal and info["kind"] == "접수":
                        skipped += 1
                        log(f"  {n}/{count} 건너뜀(접수): {meta['title'] or '(제목 못 읽음)'}")
                    elif not binder_rules.matches(info["binder"], binders):
                        off_binder += 1
                        log(f"  {n}/{count} 건너뜀(편철 '{info['binder'] or '못 읽음'}'은 고른 편철 아님): "
                            f"{meta['title'] or '(제목 못 읽음)'}")
                    else:
                        name = safe_name(meta["title"], n, used)
                        with open(os.path.join(out_dir, name + ".txt"), "w", encoding="utf-8") as f:
                            f.write(doc["text"])
                        if doc["html"]:
                            with open(os.path.join(out_dir, name + ".html"), "w", encoding="utf-8") as f:
                                f.write(doc["html"])
                        if info["raw"]:
                            raw = info["raw"]
                            if doc.get("unlocked"):
                                raw = privacy.mask_text(raw, found=doc.get("secure_found", []))[0]
                            with open(os.path.join(out_dir, name + ".info.txt"), "w", encoding="utf-8") as f:
                                f.write(raw)
                        with open(os.path.join(out_dir, name + ".meta.json"), "w", encoding="utf-8") as f:
                            json.dump({"제목": meta["title"], "수신자": meta["receiver"], "구분": info["kind"],
                                       "편철": info["binder"], "편철원문": info["binder_raw"],
                                       "문서번호": info.get("doc_no", ""), "기안일자": info.get("date", ""),
                                       "분야": binder_rules.area_for(info["binder"], meta["title"]),
                                       "보안문서": bool(doc.get("unlocked"))},
                                      f, ensure_ascii=False, indent=1)
                        if key:
                            seen_keys[key] = meta["title"]
                        index.append(index_line(saved + 1, meta, len(doc["text"]), name)
                                     + f" | 편철: {info['binder'] or '-'}")
                        saved += 1
                        names.append(name)
                        internal += 1 if meta["internal"] else 0
                        unlocked += 1 if doc.get("unlocked") else 0
                        log(f"  {n}/{count} 저장: {name} [편철: {info['binder'] or '못 읽음'}]"
                            + (" (보안 문서·비밀번호로 엶)" if doc.get("unlocked") else ""))
                        if attachments:                     # 지금 문서의 첨부까지는 받는다
                            _take_attachments(driver, handle, out_dir, name, doc, att, log, extra, keep_phones)
            if status != "encrypted":
                checkpoint(n)
            if n == count or halted():
                break
            known = frozenset(driver.window_handles)
            if not click_next(driver):
                handle = reopen_after(cur_key or cur_title)     # [다음]이 없으면 대장 목록에서 다음 줄로
                if handle is None:
                    log("[다음] 버튼을 찾지 못해 여기서 멈춥니다.")
                    break
                last, known = "", frozenset(driver.window_handles)
            time.sleep(1.5)
    except Exception as ex:                       # 오류가 나도 받은 문서까지는 정리한다
        error = f"{type(ex).__name__}: {ex}" if not isinstance(ex, CollectError) else str(ex)
        log(f"⚠ 받는 중 오류가 나서 멈춥니다: {error}")
        log("  여기까지 받은 문서는 저장했습니다. 다시 [대장 문서 받기]를 누르면 멈춘 곳부터 이어 받습니다.")
    with open(os.path.join(out_dir, "index.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(index) + "\n")
    pdfs = 0
    if pdf and names:
        todo = [x for x in names if not os.path.isfile(os.path.join(out_dir, "PDF", x + ".pdf"))]
        if todo:
            log(f"문서 {len(todo)}개를 PDF로 만듭니다(이름·동호수·연락처는 000으로 가림)...")
            try:
                driver.switch_to.window(handle if handle in driver.window_handles else driver.window_handles[0])
            except Exception:
                pass
            try:
                make_pdfs(driver, out_dir, todo, log, extra, keep_phones)
            except Exception as ex:
                log(f"⚠ PDF를 만드는 중 오류: {type(ex).__name__}: {ex} (다음에 이어 받을 때 다시 만듭니다)")
                error = error or f"PDF 만들기 오류: {ex}"
        pdfs = sum(os.path.isfile(os.path.join(out_dir, "PDF", x + ".pdf")) for x in names)
    try:
        by_binder = organize_by_binder(out_dir, names, log)
    except Exception as ex:
        log(f"⚠ 편철별 정리 중 오류: {type(ex).__name__}: {ex}")
        by_binder = {}
    state["finished"] = not (stopped or error)
    save_progress(out_dir, state)
    return {"pdfs": pdfs, "attach": att, "saved": saved, "internal": internal, "skipped": skipped, "encrypted": encrypted,
            "unlocked": unlocked, "views": views, "names": names, "dir": out_dir, "stopped": stopped,
            "error": error, "resumed": bool(resume_key), "done": state.get("done", 0), "count": count,
            "off_binder": off_binder, "by_binder": by_binder, "similar": similar}


NO_BINDER = "편철 못 읽음"


def read_meta(out_dir: str, name: str) -> dict:
    import json
    try:
        with open(os.path.join(out_dir, name + ".meta.json"), encoding="utf-8-sig") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def organize_by_binder(out_dir: str, names: list, log=print) -> dict:
    """받은 문서를 편철별로 정리한다. {편철: [이름 …]}

    - 편철별_목록.csv : 번호·편철·분야·구분·문서번호·기안일자·제목·파일 (엑셀로 열림)
    - 편철별\\{편철}\\ : 그 편철 문서의 가린 PDF와 첨부 폴더를 복사(가리지 않은 txt·html은 넣지 않음)
    """
    import csv
    import shutil
    groups: dict[str, list] = {}
    rows = []
    for name in names:
        m = read_meta(out_dir, name)
        binder = (m.get("편철") or "").strip() or NO_BINDER
        groups.setdefault(binder, []).append(name)
        rows.append((binder, m, name))
    if not rows:
        return groups
    rows.sort(key=lambda r: (r[0] == NO_BINDER, r[0]))           # 편철 이름 차례, 못 읽은 것은 맨 뒤
    with open(os.path.join(out_dir, "편철별_목록.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["번호", "편철", "편철원문", "분야", "구분", "문서번호", "기안일자", "제목", "파일"])
        for i, (binder, m, name) in enumerate(rows, 1):
            w.writerow([i, binder, m.get("편철원문", ""), m.get("분야", ""), m.get("구분", ""),
                        m.get("문서번호", ""), m.get("기안일자", ""), m.get("제목", ""), name])
    root = os.path.join(out_dir, "편철별")
    for binder, mine in groups.items():
        folder = os.path.join(root, safe_name(binder, 0, set()))
        for name in mine:
            pdf = os.path.join(out_dir, "PDF", name + ".pdf")
            att = os.path.join(out_dir, "첨부", name)
            try:
                if os.path.isfile(pdf):
                    os.makedirs(folder, exist_ok=True)
                    shutil.copy2(pdf, os.path.join(folder, name + ".pdf"))
                if os.path.isdir(att):
                    shutil.copytree(att, os.path.join(folder, "첨부", name), dirs_exist_ok=True)
            except OSError as ex:
                log(f"  편철별 폴더에 넣지 못함: {name} ({ex})")
    log("편철별 정리: " + ", ".join(f"{b} {len(v)}건" for b, v in sorted(groups.items())))
    return groups

