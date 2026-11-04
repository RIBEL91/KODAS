"""홈넷 브라우저 열기 · 로그인 (LeavePromotion leave_scraper.py에서 옮김).

크롬이 설치돼 있으면 크롬, 없으면 윈도에 기본으로 있는 엣지를 쓴다.
웹기안기 작성 후 사람이 확인하고 상신하도록 창은 열어 둔다(detach).
"""
import os
import time

LOGIN_URL = "https://homnet.kohom.or.kr"

# 홈넷 로그인 폼
XPATH_ID_INPUT = '/html/body/div[1]/div/div/form/div/div[1]/input'
XPATH_PW_INPUT = '/html/body/div[1]/div/div/form/div/div[2]/input'
XPATH_LOGIN_BTN = '/html/body/div[1]/div/div/form/div/div[5]/button'

# 로그인 후 상황별 안내창
SEL_DUP_CONTINUE = "#nextGoBt"     # '다른 ip로 접속되어 있습니다' → 계속
SEL_PW_EXPIRED_OK = "#okBt"        # '비밀번호를 수정한지 90일이 넘어' 변경 창


class LoginError(Exception):
    """사용자에게 그대로 보여줄 수 있는 로그인 실패 사유."""


def _chrome_paths() -> list[str]:
    roots = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    return [os.path.join(r, "Google", "Chrome", "Application", "chrome.exe") for r in roots if r]


def chrome_installed() -> bool:
    return any(os.path.isfile(p) for p in _chrome_paths())


def browser_name() -> str:
    return "크롬" if chrome_installed() else "엣지"


def _common(options, headless: bool, detach: bool):
    if headless:
        options.add_argument("--headless=new")
    if detach:
        options.add_experimental_option("detach", True)
    options.add_argument("--window-size=1400,1000")
    options.add_argument("--disable-gpu")
    # 'Chrome이 자동화된 테스트 소프트웨어에 의해 제어되고 있습니다' 안내줄 숨김
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    # 로그인 뒤 '비밀번호를 저장하시겠습니까?' 말풍선을 띄우지 않는다
    options.add_experimental_option("prefs", {"credentials_enable_service": False,
                                              "profile.password_manager_enabled": False})
    return options


def build_driver(headless: bool = False, detach: bool = True):
    """홈넷 자동화용 드라이버. 드라이버 파일은 Selenium이 처음 한 번 내려받는다."""
    import subprocess
    if chrome_installed():
        # 지연 임포트 경로(webdriver.Chrome)는 PyInstaller가 놓치므로 클래스를 직접 임포트한다.
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.webdriver import WebDriver
    else:
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.edge.service import Service
        from selenium.webdriver.edge.webdriver import WebDriver
    service = Service()
    service.creation_flags = subprocess.CREATE_NO_WINDOW
    return WebDriver(service=service, options=_common(Options(), headless, detach))


def driver_alive(driver) -> bool:
    if driver is None:
        return False
    try:
        return bool(driver.window_handles)
    except Exception:
        return False


def _visible(driver, css: str):
    from selenium.webdriver.common.by import By
    for el in driver.find_elements(By.CSS_SELECTOR, css):
        try:
            if el.is_displayed():
                return el
        except Exception:
            pass
    return None


def homnet_login(driver, user_id: str, password: str, timeout: int = 25, log=None) -> None:
    """홈넷 포털에 로그인한다. 이 세션이 그룹웨어(gw) 진입에도 쓰인다(SSO).

    - 다른 IP 중복접속 안내 → [계속]
    - 비밀번호 90일 경과 → 자동 처리하지 않고 LoginError
    - 경고창(예: 비밀번호 오류) → 문구를 담아 LoginError
    로그인 화면(/login)을 벗어나면 성공으로 본다.
    """
    from selenium.common.exceptions import (NoAlertPresentException,
                                            UnexpectedAlertPresentException)
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    def _log(m):
        if log:
            log(m)

    driver.get(LOGIN_URL)
    wait = WebDriverWait(driver, 15)
    id_box = wait.until(EC.presence_of_element_located((By.XPATH, XPATH_ID_INPUT)))
    id_box.clear()
    id_box.send_keys(user_id)
    pw_box = driver.find_element(By.XPATH, XPATH_PW_INPUT)
    pw_box.clear()
    pw_box.send_keys(password)
    driver.find_element(By.XPATH, XPATH_LOGIN_BTN).click()

    clicked_continue = False
    end = time.time() + timeout
    while time.time() < end:
        try:
            alert = driver.switch_to.alert
            text = (alert.text or "").strip()
            alert.accept()
            raise LoginError(f"홈넷 로그인 실패: {text or '경고창'}")
        except NoAlertPresentException:
            pass
        try:
            url = driver.current_url or ""
        except UnexpectedAlertPresentException:
            continue            # 경고창이 막 떴다 → 다음 바퀴에서 문구를 읽는다
        if "/login" not in url:
            return
        if _visible(driver, SEL_PW_EXPIRED_OK):
            raise LoginError("홈넷 비밀번호를 변경한 지 90일이 지났습니다. "
                             "홈넷에서 직접 비밀번호를 변경한 뒤 다시 시도하세요.")
        btn = _visible(driver, SEL_DUP_CONTINUE)
        if btn and not clicked_continue:
            _log("ℹ️ 다른 곳에서 홈넷에 접속 중이라는 안내 → [계속]을 누릅니다.")
            driver.execute_script("arguments[0].click();", btn)
            clicked_continue = True
        time.sleep(0.5)
    raise LoginError("홈넷 로그인 화면에서 넘어가지 않습니다. 아이디/비밀번호를 확인하거나 "
                     "브라우저 창의 안내 메시지를 확인하세요.")
