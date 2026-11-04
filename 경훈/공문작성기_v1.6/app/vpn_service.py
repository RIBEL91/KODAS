"""Selenium(Edge)으로 VPN 로그인 절차를 자동화한다.

사내 환경에 묶인 값(주소, XPath, 프로그램 경로)은 모두 이 파일 상단에 모아
두었다. VPN 사이트 화면이 바뀌어 로그인이 깨지면 여기부터 확인한다.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from selenium.common.exceptions import (TimeoutException, UnexpectedAlertPresentException,
                                        WebDriverException)
from selenium.webdriver.common.by import By
# selenium 4.28+는 `webdriver.Edge`를 지연 임포트로 노출한다. 그 경로로 쓰면
# PyInstaller의 정적 분석이 실제 모듈을 찾지 못해 번들에서 빠지고, exe에서만
# "No module named 'selenium.webdriver.edge.webdriver'"로 죽는다.
# 클래스를 직접 임포트해 두면 빌드 옵션 없이도 항상 포함된다.
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.webdriver import WebDriver as EdgeWebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from system_tasks import (EDGE_BROWSER_PROCESS, count_processes, find_profile_owner_pids,
                          read_edge_policies, release_profile)

# --- 사내 환경 상수 ---

LH_VPN_URL = "https://58.233.27.146"
KOHOM_VPN_URL = "https://inet.kohom.or.kr"
HOMNET_URL = "https://homnet.kohom.or.kr"

XPLATFORM_EXE = r"C:\Program Files (x86)\TOBESOFT\XPLATFORM\9.2.2\XPlatform.exe"
XPLATFORM_ARGS = ("-K", "LHwww_ETC", "-X", "https://testrms.lh.or.kr:8987/webdocs/lhwww.xadl")

# 터널이 실제로 통하는지 확인할 업무 서버. 사내 전용 주소여야 한다.
# VPN 클라이언트가 쓴 hosts 항목으로 이름이 풀리고 그 주소는 터널 경로를
# 타므로, 연결에 성공하면 hosts와 경로가 모두 정상이라는 뜻이다.
# VPN 포털 주소(inet.kohom.or.kr 등)는 VPN 없이도 열리므로 쓰면 안 된다.
LH_PROBE = ("testrms.lh.or.kr", 8987)
KOHOM_PROBE = ("homnet.kohom.or.kr", 443)

# 로그인 폼은 이름이 "main"인 프레임 안에 있고, 요소는 절대 XPath로 찾는다.
FRAME_NAME = "main"
XPATH_ID = ('/html/body/form[1]/table/tbody/tr/td/table/tbody/tr[1]/td[2]/table/tbody/'
            'tr[4]/td/table/tbody/tr[1]/td/p/input')
XPATH_LOGIN_BUTTON = ('/html/body/form[1]/table/tbody/tr/td/table/tbody/tr[1]/td[2]/table/tbody/'
                      'tr[4]/td/table/tbody/tr[7]/td/table/tbody/tr[1]/td/a')
# 폼이 그려졌는지 판단하는 기준 요소. 두 VPN 모두 이 요소를 기다린다.
XPATH_FORM_READY = '//*[@id="pw1"]/td/p/input'
XPATH_FAVORITES = ('/html/body/table/tbody/tr/td/table/tbody/tr[1]/td/table/tbody/tr[2]/td/'
                   'table/tbody/tr/td[2]')

# 실제 비밀번호 입력창은 VPN마다 다르다.
XPATH_PASSWORD_LH = '//*[@id="vkeyboard"]'
XPATH_PASSWORD_KOHOM = '//*[@id="pw1"]/td/p/input'

PROFILE_DIR_NAME = "VPN_Automation_Profile"
# 원래 프로필을 확보하지 못했을 때 차례로 시도할 대체 프로필 접미사.
FALLBACK_PROFILE_SUFFIXES = ("_alt", "_alt2", "_alt3")

WAIT_TIMEOUT = 20
# 가상 키보드가 입력을 받아들일 시간을 준다.
INPUT_DELAY = 0.5
# 진짜 headless는 보안 프로그램에 막히므로 창을 화면 밖으로 보내 숨긴다.
OFFSCREEN_POSITION = -32000

Log = Callable[[str], None]


@dataclass(frozen=True)
class VpnTarget:
    """VPN 한 곳의 접속 정보. 두 VPN의 차이는 이 값들뿐이다.

    ip_prefix는 연결 후 VPN 어댑터에 부여되어야 하는 IP 대역,
    probe_host/probe_port는 터널이 실제로 통하는지 확인할 업무 서버다.
    """

    name: str
    url: str
    password_xpath: str
    ip_prefix: str
    probe_host: str
    probe_port: int
    refresh_before_login: bool = False


LH_VPN = VpnTarget("LH VPN", LH_VPN_URL, XPATH_PASSWORD_LH, ip_prefix="10.",
                   probe_host=LH_PROBE[0], probe_port=LH_PROBE[1], refresh_before_login=True)
KOHOM_VPN = VpnTarget("공단 VPN", KOHOM_VPN_URL, XPATH_PASSWORD_KOHOM, ip_prefix="172.",
                      probe_host=KOHOM_PROBE[0], probe_port=KOHOM_PROBE[1])


def launch_wise(log: Log) -> bool:
    """WISE(XPlatform) 업무 프로그램을 실행한다. 브라우저와 무관하게 동작한다."""
    log("[진행] WISE(XPlatform) 프로그램을 실행합니다.")
    try:
        subprocess.Popen([XPLATFORM_EXE, *XPLATFORM_ARGS])
    except OSError as exc:
        log(f"[에러] WISE 프로그램 실행 실패: {exc}")
        return False

    log("[성공] WISE 프로그램 실행 명령이 전송되었습니다.")
    return True


class LoginService:
    """Edge 브라우저 하나를 열고 VPN 로그인을 수행한다."""

    def __init__(self, log: Log = print) -> None:
        self._log = log
        self.driver = None
        self._headless = False
        # 마지막 로그인 실패 사유. 사용자에게 그대로 보여줄 수 있는 문장이다.
        self.last_error: str | None = None

    # --- 브라우저 수명 관리 ---

    def open_browser(self, headless: bool = False) -> bool:
        """Edge 세션을 연다. 브라우저는 한 번만 띄운다.

        실패했다고 다시 띄우지 않는다. 재시도는 창만 여러 개 남기고 원인을
        가릴 뿐이었다. 대신 실패 시 원인 진단에 필요한 정보를 로그에 남긴다.
        """
        self._log("[시스템] Edge 브라우저를 준비합니다...")
        self._headless = headless

        profile = self._resolve_profile()
        started, reason = self._start_session(profile)
        if started:
            return True

        self._log(f"[에러] 브라우저 실행 실패: {reason}")
        self._diagnose_failure(profile)
        return False

    def _resolve_profile(self) -> str | None:
        """사용할 프로필 경로를 정한다. 확보 못 하면 대체 경로를 쓴다."""
        base = self._profile_dir()
        if not base:
            self._log("[경고] LOCALAPPDATA 환경변수를 찾을 수 없어 기본 프로필을 사용합니다.")
            return None

        if release_profile(self._log, base):
            return base

        self._log("[경고] 자동화 프로필을 확보하지 못해 대체 프로필을 사용합니다.")
        self._log("[경고]   보안 프로그램의 '항상 허용' 팝업이 다시 뜰 수 있습니다.")
        for suffix in FALLBACK_PROFILE_SUFFIXES:
            fallback = f"{base}{suffix}"
            if release_profile(self._log, fallback):
                return fallback
        return f"{base}{FALLBACK_PROFILE_SUFFIXES[0]}"

    def _diagnose_failure(self, user_data_dir: str | None) -> None:
        """실패 원인을 좁히기 위한 정보를 남긴다.

        브라우저가 정상 실행됐는데 chromedriver만 붙지 못하면, 원인은 프로필이
        아니라 원격 디버깅 차단일 가능성이 크다. chromedriver는 프로필 폴더의
        DevToolsActivePort를 읽지 못하면 원인을 프로필 충돌로 추측해 엉뚱한
        메시지를 내보내므로, 실제 상태를 직접 확인해 기록한다.
        """
        if user_data_dir:
            owners = find_profile_owner_pids(user_data_dir)
            self._log(f"[진단] 사용한 프로필: {user_data_dir}")
            self._log(f"[진단] 프로필 점유 프로세스: {owners or '없음'}")
            port_file = os.path.join(user_data_dir, "DevToolsActivePort")
            self._log(f"[진단] DevToolsActivePort 파일: {'있음' if os.path.exists(port_file) else '없음'}")

        policies = read_edge_policies()
        if policies:
            for name, value in policies.items():
                self._log(f"[진단] Edge 정책 {name} = {value}")
            self._log("[진단] 원격 디버깅이 정책으로 막혀 있으면 자동화가 동작하지 않습니다.")
        else:
            self._log("[진단] 브라우저 자동화를 막는 Edge 정책은 설정되어 있지 않습니다.")

        self._log(f"[진단] 실행 중인 Edge 프로세스: {count_processes(EDGE_BROWSER_PROCESS)}개")

    def _start_session(self, user_data_dir: str | None) -> tuple[bool, str]:
        """세션 생성을 한 번 시도한다. 실패 사유는 첫 줄만 돌려준다."""
        service = EdgeService()
        service.creation_flags = subprocess.CREATE_NO_WINDOW
        try:
            self.driver = EdgeWebDriver(service=service, options=self._build_options(user_data_dir))
        except WebDriverException as exc:
            self.driver = None
            return False, str(exc).splitlines()[0]

        self._log("[시스템] 브라우저 실행 완료.")
        return True, ""

    def close_browser(self) -> None:
        if not self.driver:
            return
        self._log("[시스템] 브라우저를 닫습니다.")
        try:
            self.driver.quit()
        except WebDriverException as exc:
            self._log(f"[경고] 브라우저 종료 중 오류: {exc}")
        finally:
            self.driver = None

    def _build_options(self, user_data_dir: str | None) -> Options:
        headless = self._headless
        options = Options()
        options.add_experimental_option("detach", True)
        # VPN 장비가 자체 서명 인증서를 쓰고, 보안 프로그램이 자동화 표식을 검사한다.
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        if headless:
            self._log("[시스템] 백그라운드(화면 숨김) 모드로 우회 실행합니다.")
            options.add_argument(f"--window-position={OFFSCREEN_POSITION},{OFFSCREEN_POSITION}")

        if user_data_dir:
            options.add_argument(f"--user-data-dir={user_data_dir}")

        return options

    @staticmethod
    def _profile_dir() -> str | None:
        """평소 쓰는 Edge 프로필과 섞이지 않도록 자동화 전용 프로필을 쓴다."""
        local_app_data = os.getenv("LOCALAPPDATA")
        if not local_app_data:
            return None
        return os.path.join(local_app_data, "Microsoft", "Edge", PROFILE_DIR_NAME)

    # --- 로그인 ---

    def login(self, target: VpnTarget, user_id: str, password: str) -> bool:
        """로그인 절차를 수행한다. 실패 사유는 last_error에 담는다."""
        self.last_error = None
        try:
            return self._login(target, user_id, password)
        except UnexpectedAlertPresentException as exc:
            # ID/비밀번호가 틀리면 사이트가 경고창을 띄운다. 이건 프로그램 오류가
            # 아니라 사용자가 조치할 수 있는 상황이므로 스택 트레이스 대신
            # 경고창 문구를 그대로 전달한다.
            message = (getattr(exc, "alert_text", None) or self._take_alert_text() or "").strip()
            self.last_error = message or "사이트에서 경고창이 표시되었습니다."
            self._log(f"[에러] [{target.name}] 로그인 실패: {self.last_error}")
            return False

    def _take_alert_text(self) -> str:
        """열려 있는 경고창의 문구를 읽고 닫는다. 없으면 빈 문자열."""
        if not self.driver:
            return ""
        try:
            alert = self.driver.switch_to.alert
            text = alert.text or ""
            alert.accept()
            return text
        except Exception:
            return ""

    def _login(self, target: VpnTarget, user_id: str, password: str) -> bool:
        if not self.driver:
            self._log(f"[{target.name}] 브라우저 인스턴스가 없어 연결을 중단합니다.")
            self.last_error = "브라우저가 실행되지 않았습니다."
            return False

        self._log(f"\n[{target.name}] 연결을 시작합니다. 주소: {target.url}")
        self.driver.get(target.url)

        if not self._headless:
            self.driver.maximize_window()

        if target.refresh_before_login:
            self.driver.refresh()

        if not self._switch_to_login_frame(target):
            self.last_error = "VPN 사이트에 접속하지 못했습니다. 네트워크를 확인해 주세요."
            return False

        self._log(f"[{target.name}] 로그인 입력창 로딩 대기 중...")
        if not self._wait_for(XPATH_FORM_READY,
                              f"[{target.name}] 로그인 페이지 로딩 시간 초과. 네트워크를 확인하세요."):
            self.last_error = "로그인 페이지가 열리지 않았습니다. 네트워크를 확인해 주세요."
            return False

        self._log(f"[{target.name}] 아이디 및 패스워드를 입력합니다.")
        self.driver.find_element(By.XPATH, XPATH_ID).send_keys(user_id)
        time.sleep(INPUT_DELAY)
        self.driver.find_element(By.XPATH, target.password_xpath).send_keys(password)
        time.sleep(INPUT_DELAY)

        self._log(f"[{target.name}] 로그인 버튼 클릭.")
        self.driver.find_element(By.XPATH, XPATH_LOGIN_BUTTON).click()

        self._log(f"[{target.name}] VPN 접속 처리 대기 중...")
        if not self._wait_for(XPATH_FAVORITES,
                              f"[{target.name}] 즐겨찾기 페이지 로딩 시간 초과. "
                              f"페이지 구조가 변경되었을 수 있습니다."):
            self.last_error = "로그인 후 화면이 넘어가지 않았습니다. 계정 정보를 확인해 주세요."
            return False

        self._log(f"[{target.name}] 연결 프로세스가 완료되었습니다.")
        return True

    def _switch_to_login_frame(self, target: VpnTarget) -> bool:
        try:
            WebDriverWait(self.driver, WAIT_TIMEOUT).until(
                EC.frame_to_be_available_and_switch_to_it(FRAME_NAME)
            )
            return True
        except TimeoutException:
            self._log(f"[경고] [{target.name}] 로그인 프레임을 찾지 못했습니다. "
                      f"VPN 사이트에 접속되지 않았을 수 있습니다.")
            return False

    def _wait_for(self, xpath: str, timeout_message: str) -> bool:
        try:
            WebDriverWait(self.driver, WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            return True
        except TimeoutException:
            self._log(f"[경고] {timeout_message}")
            return False

    # --- 로그인 이후 후속 작업 ---

    def open_homnet(self) -> None:
        if not self.driver:
            self._log("[에러] 브라우저가 열려있지 않아 홈넷을 켤 수 없습니다.")
            return

        self._log(f"[진행] 홈넷 페이지({HOMNET_URL})를 엽니다.")
        try:
            self.driver.execute_script(f"window.open('{HOMNET_URL}');")
        except WebDriverException as exc:
            self._log(f"[에러] 홈넷 페이지 열기 실패: {exc}")
