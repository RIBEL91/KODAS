"""사내망 접속 세션: VPN 터널 선확인 → (필요시) VPN 접속 → 홈넷 로그인.

LeavePromotion session.py의 흐름을 그대로 쓴다. 브라우저는 웹기안기 작성 후
사람이 상신할 수 있도록 열어 둔다(detach).
"""
import time

import homnet

TUNNEL_WAIT_SEC = 40   # VPN 로그인 후 사내망이 통할 때까지 기다리는 최대 시간


class SessionError(Exception):
    """사용자에게 그대로 보여줄 수 있는 접속 오류."""


def tunnel_alive() -> tuple[bool, str]:
    import system_tasks
    from vpn_service import KOHOM_VPN
    return system_tasks.check_tcp_reachable(KOHOM_VPN.probe_host, KOHOM_VPN.probe_port)


def ensure_tunnel(log, vpn_id: str = "", vpn_pw: str = "") -> None:
    """터널이 이미 살아있으면 접속하지 않는다. 아니면 입력한 계정으로 VPN에 접속한다."""
    reachable, reason = tunnel_alive()
    if reachable:
        log("✅ 사내망(VPN)이 이미 연결되어 있습니다.")
        return
    if not (vpn_id and vpn_pw):
        raise SessionError("사내망(VPN)에 연결되어 있지 않습니다. VPN에 접속하고 홈넷에 로그인한 뒤 다시 작성해 주세요.")

    from vpn_service import KOHOM_VPN, LoginService
    log(f"VPN 접속을 시도합니다... ({reason})")
    vpn = LoginService(log=log)
    # VPN 로그인은 Edge 창에서 한다. 창은 닫지 않는다(detach) — 닫으면 VPN이 끊길 수 있다.
    if not vpn.open_browser():
        raise SessionError("VPN 로그인용 Edge 브라우저를 열지 못했습니다. "
                           "열려 있는 Edge 창을 모두 닫고 다시 시도해 주세요.")
    if not vpn.login(KOHOM_VPN, vpn_id, vpn_pw):
        raise SessionError(f"VPN 접속에 실패했습니다. {vpn.last_error or ''}".strip())
    deadline = time.time() + TUNNEL_WAIT_SEC
    while True:
        reachable, reason = tunnel_alive()
        if reachable or time.time() >= deadline:
            break
        time.sleep(2)
    if not reachable:
        raise SessionError(f"VPN 접속 후에도 사내망에 연결되지 않습니다: {reason}")
    log("✅ VPN 접속 완료")


def _quit(driver) -> None:
    try:
        driver.quit()
    except Exception:
        pass


def open_homnet(homnet_id: str, homnet_pw: str, log):
    """브라우저를 열어 홈넷에 로그인한 드라이버를 돌려준다."""
    if not (homnet_id and homnet_pw):
        raise SessionError("홈넷 아이디와 비밀번호를 입력하세요.")
    log(f"{homnet.browser_name()} 브라우저를 엽니다... (처음 한 번은 준비에 30초쯤 걸릴 수 있습니다)")
    try:
        driver = homnet.build_driver()
    except ModuleNotFoundError as ex:
        raise SessionError(f"프로그램 구성 요소가 빠져 있습니다: {ex.name}") from ex
    except Exception as ex:
        raise SessionError("브라우저를 열지 못했습니다. 인터넷 연결을 확인해 주세요. "
                           f"({type(ex).__name__}: {str(ex).splitlines()[0] if str(ex) else ''})") from ex
    log("홈넷 로그인...")
    try:
        homnet.homnet_login(driver, homnet_id, homnet_pw, log=log)
    except homnet.LoginError as ex:
        _quit(driver)
        raise SessionError(str(ex)) from None
    except Exception as ex:
        _quit(driver)
        raise SessionError(f"홈넷 로그인 중 오류: {type(ex).__name__} {ex}".strip()) from None
    time.sleep(1)
    log("✅ 홈넷 로그인 완료")
    return driver
