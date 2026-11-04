"""브라우저 드라이버 정리, VPN 클라이언트 강제 종료, hosts 파일 백업/초기화.

GUI와 Selenium 어느 쪽에도 의존하지 않는다. 로그는 호출부가 넘겨준
콜백으로 남기므로 이 모듈은 화면 구성을 알 필요가 없다.
"""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import socket
import subprocess
import time
import winreg
from ctypes import wintypes
from typing import Callable, NamedTuple

import psutil

EDGE_DRIVER_PROCESS = "msedgedriver.exe"
EDGE_BROWSER_PROCESS = "msedge.exe"
VPN_CLIENT_PROCESS = "SecuwaySSL.exe"

# VPN 터널은 TAP 어댑터로 잡힌다. 설명 예: "TAP-Windows Adapter V9 - SecuwaySSLU"
VPN_ADAPTER_KEYWORD = "SecuwaySSL"

HOSTS_FILE = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"), "System32", "drivers", "etc", "hosts"
)

# 종료 요청 후 프로세스가 실제로 내려가기를 기다리는 시간(초).
_KILL_TIMEOUT = 3

# 웹 로그인이 끝나도 VPN 클라이언트가 뜨기까지는 시간이 걸린다.
VPN_CLIENT_WAIT_TIMEOUT = 30
VPN_CLIENT_POLL_INTERVAL = 1.0

# 클라이언트가 떠도 IP 부여까지는 또 시간이 걸린다.
VPN_IP_WAIT_TIMEOUT = 30
VPN_IP_POLL_INTERVAL = 1.0

# 실제 통신 확인. 경로가 자리잡는 데 시간이 걸리므로 잠시 재시도한다.
VPN_PROBE_TIMEOUT = 15.0
VPN_PROBE_ATTEMPT_TIMEOUT = 4.0
VPN_PROBE_POLL_INTERVAL = 1.0

_NETWORK_CLASS_GUID = "{4D36E972-E325-11CE-BFC1-08002BE10318}"

Log = Callable[[str], None]


def is_elevated() -> bool:
    """관리자 권한으로 실행 중인지 확인한다.

    hosts 파일 수정과 VPN 클라이언트의 netsh 주소 설정에 관리자 권한이 필요하다.
    권한이 없으면 터널이 붙어도 IP가 부여되지 않고 클라이언트가 죽는다.
    """
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _iter_by_name(name: str):
    """이름이 일치하는 프로세스를 훑는다. 조회 중 사라지는 프로세스는 건너뛴다."""
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info.get("name") == name:
                yield proc
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue


def _kill(proc: psutil.Process) -> None:
    proc.kill()
    try:
        proc.wait(timeout=_KILL_TIMEOUT)
    except psutil.TimeoutExpired:
        pass


def terminate_orphan_drivers(log: Log) -> int:
    """이전 실행이 남긴 msedgedriver.exe만 정리한다.

    부모 프로세스가 살아 있는 드라이버는 다른 프로그램이 지금 사용 중이라는
    뜻이므로 건드리지 않는다. psutil의 parent()는 PID 재사용까지 걸러 주기
    때문에, None이 나오면 부모가 이미 죽은 찌꺼기로 볼 수 있다.
    """
    log("[시스템] 시작 전 이전 자동화 찌꺼기 프로세스 정리를 시도합니다...")

    killed = 0
    skipped = 0
    for proc in _iter_by_name(EDGE_DRIVER_PROCESS):
        try:
            if proc.parent() is not None:
                skipped += 1
                continue
            _kill(proc)
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    if killed:
        log(f"[시스템] {killed}개의 좀비 드라이버 프로세스를 성공적으로 종료했습니다.")
    else:
        log("[시스템] 정리할 찌꺼기 프로세스가 없습니다. (쾌적한 상태)")
    if skipped:
        log(f"[시스템] 사용 중인 드라이버 {skipped}개는 그대로 두었습니다.")

    return killed


def count_processes(name: str) -> int:
    return sum(1 for _ in _iter_by_name(name))


def count_vpn_clients() -> int:
    """지금 실행 중인 VPN 클라이언트 개수. VPN 한 곳당 하나씩 뜬다."""
    return count_processes(VPN_CLIENT_PROCESS)


def wait_for_vpn_clients(log: Log, expected: int,
                         timeout: float = VPN_CLIENT_WAIT_TIMEOUT,
                         poll_interval: float = VPN_CLIENT_POLL_INTERVAL) -> int:
    """VPN 클라이언트가 expected개 이상 뜰 때까지 기다리고 실제 개수를 돌려준다.

    웹 로그인 성공과 터널 연결은 다른 단계다. 로그인 페이지가 넘어가도
    클라이언트가 뜨지 않으면 실제로는 연결되지 않은 것이므로, 프로세스가
    올라오는 것까지 확인해야 한다.
    """
    count = count_vpn_clients()
    if count >= expected or timeout <= 0:
        return count

    log(f"[확인] {VPN_CLIENT_PROCESS} {expected}개 기동을 기다립니다... "
        f"(현재 {count}개, 최대 {timeout:.0f}초)")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        count = count_vpn_clients()
        if count >= expected:
            break
    return count


def _connection_name(instance_guid: str) -> str | None:
    """어댑터 GUID로 네트워크 연결 이름(예: "로컬 영역 연결* 11")을 찾는다."""
    path = (rf"SYSTEM\CurrentControlSet\Control\Network\{_NETWORK_CLASS_GUID}"
            rf"\{instance_guid}\Connection")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return winreg.QueryValueEx(key, "Name")[0]
    except OSError:
        return None


def adapter_descriptions() -> dict[str, str]:
    """네트워크 연결 이름 → 어댑터 설명 매핑.

    psutil은 연결 이름만 주고 어댑터 설명은 주지 않는다. VPN 어댑터를
    설명으로 골라내야 사내 LAN의 10.x 주소를 VPN 주소로 오인하지 않는다.
    ipconfig 출력을 파싱하지 않으므로 표시 언어의 영향을 받지 않는다.
    """
    descriptions: dict[str, str] = {}
    path = rf"SYSTEM\CurrentControlSet\Control\Class\{_NETWORK_CLASS_GUID}"
    try:
        class_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
    except OSError:
        return descriptions

    with class_key:
        index = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(class_key, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(class_key, subkey_name) as adapter_key:
                    description = winreg.QueryValueEx(adapter_key, "DriverDesc")[0]
                    instance_guid = winreg.QueryValueEx(adapter_key, "NetCfgInstanceId")[0]
            except OSError:
                continue

            name = _connection_name(instance_guid)
            if name:
                descriptions[name] = description
    return descriptions


def find_vpn_adapters(keyword: str = VPN_ADAPTER_KEYWORD,
                      only_up: bool = True) -> list[tuple[str, str, list[str]]]:
    """VPN TAP 어댑터 목록을 (연결 이름, 설명, IPv4 목록)으로 돌려준다.

    **연결이 끊긴 어댑터는 기본적으로 제외한다.** psutil은 내려간 어댑터에도
    마지막에 설정됐던 주소를 그대로 돌려주기 때문에, 상태를 보지 않으면 죽은
    터널을 연결된 것으로 오인한다(실제로 그렇게 판정한 적이 있다).
    ipconfig 에서는 "미디어 연결 끊김"으로 나오고 IPv4 항목 자체가 없다.

    진단 로그처럼 끊긴 어댑터까지 보여야 할 때만 only_up=False 로 부른다.
    """
    descriptions = adapter_descriptions()
    stats = psutil.net_if_stats()
    adapters = []
    for name, addresses in psutil.net_if_addrs().items():
        description = descriptions.get(name, "")
        if keyword.lower() not in description.lower():
            continue
        status = stats.get(name)
        if only_up and (status is None or not status.isup):
            continue
        ipv4 = [addr.address for addr in addresses if addr.family == socket.AF_INET]
        adapters.append((name, description, ipv4))
    return adapters


def describe_vpn_adapters(keyword: str = VPN_ADAPTER_KEYWORD) -> list[str]:
    """진단용 어댑터 요약. 끊긴 어댑터도 상태와 함께 보여준다."""
    stats = psutil.net_if_stats()
    lines = []
    for name, description, ipv4 in find_vpn_adapters(keyword, only_up=False):
        status = stats.get(name)
        state = "연결됨" if status is not None and status.isup else "연결 끊김"
        addresses = ", ".join(ipv4) if ipv4 else "IPv4 없음"
        lines.append(f"{description} ({name}): {state}, {addresses}")
    return lines


def find_vpn_ip(prefix: str, keyword: str = VPN_ADAPTER_KEYWORD) -> str | None:
    """VPN 어댑터 중 prefix로 시작하는 IPv4를 가진 첫 주소를 돌려준다."""
    for _, _, ipv4_addresses in find_vpn_adapters(keyword):
        for address in ipv4_addresses:
            if address.startswith(prefix):
                return address
    return None


def wait_for_vpn_ip(log: Log, vpn_name: str, prefix: str,
                    timeout: float = VPN_IP_WAIT_TIMEOUT,
                    poll_interval: float = VPN_IP_POLL_INTERVAL) -> str | None:
    """VPN 어댑터에 prefix 대역 IP가 부여될 때까지 기다린다.

    클라이언트 프로세스가 떠 있어도 IP를 못 받으면 실제 통신은 되지 않는다.
    그래서 프로세스 확인과 별개로 주소까지 봐야 한다.
    """
    address = find_vpn_ip(prefix)
    if address or timeout <= 0:
        return address

    log(f"[확인] [{vpn_name}] VPN 어댑터에 {prefix}x 대역 IP가 부여되기를 "
        f"기다립니다... (최대 {timeout:.0f}초)")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        address = find_vpn_ip(prefix)
        if address:
            return address
    return None


def check_tcp_reachable(host: str, port: int,
                        timeout: float = VPN_PROBE_ATTEMPT_TIMEOUT) -> tuple[bool, str]:
    """업무 서버에 TCP 연결을 시도한다. 실패하면 사유 문자열을 함께 돌려준다.

    ICMP(ping) 대신 TCP를 쓰는 이유는 두 가지다. 방화벽이 ICMP를 막는 경우가
    흔하고, 실제로 필요한 것은 업무 서버까지의 통신이지 응답 여부가 아니다.
    대상 이름은 VPN 클라이언트가 쓴 hosts 항목으로 풀리고 그 주소는 터널
    경로를 타므로, 이 확인이 성공하면 hosts와 경로가 모두 살아 있다는 뜻이다.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except socket.gaierror as exc:
        return False, f"이름을 해석하지 못했습니다 (hosts 항목 없음): {exc}"
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def resolve_host(host: str) -> str | None:
    """이름을 주소로 바꾼다. 풀리지 않으면 None.

    연결 유지 신호는 이름이 아니라 이 주소로 보낸다. VPN 클라이언트가 쓴
    hosts 항목이 사라지면 이름 해석부터 실패해 신호가 터널로 나가지 못하고,
    그러면 유지하려던 세션이 오히려 유휴로 끊긴다.
    """
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None


def wait_for_reachable(log: Log, vpn_name: str, host: str, port: int,
                       timeout: float = VPN_PROBE_TIMEOUT,
                       attempt_timeout: float = VPN_PROBE_ATTEMPT_TIMEOUT,
                       poll_interval: float = VPN_PROBE_POLL_INTERVAL) -> tuple[bool, str]:
    """업무 서버에 연결될 때까지 재시도한다. timeout이 0이면 한 번만 시도한다."""
    deadline = time.monotonic() + timeout
    announced = False
    while True:
        reachable, reason = check_tcp_reachable(host, port, attempt_timeout)
        if reachable:
            return True, ""
        if time.monotonic() >= deadline:
            return False, reason
        if not announced:
            log(f"[확인] [{vpn_name}] 업무 서버({host}:{port}) 응답을 기다립니다... "
                f"(최대 {timeout:.0f}초)")
            announced = True
        time.sleep(poll_interval)


def wait_for_vpn_disconnect(timeout: float = 10.0, poll_interval: float = 0.5) -> bool:
    """VPN 클라이언트가 모두 내려갈 때까지 기다린다. 내려갔으면 True.

    IP 대역이 사라지는지로 판정하면 안 된다. 클라이언트를 종료해도 어댑터에는
    직전 주소가 한동안 남아 있어서, 실제로는 끊겼는데 "끊기지 않았다"는 잘못된
    경고가 나온다. 터널이 살아 있는지는 프로세스로 판단하는 편이 정확하다.
    """
    deadline = time.monotonic() + timeout
    while True:
        if count_vpn_clients() == 0:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_interval)


# Chromium은 프로필 선점 여부를 "메시지 창"으로 판정한다. 창 클래스는
# Chrome_MessageWindow, 창 제목이 곧 user-data-dir 경로다(Edge도 동일).
# 파일 잠금이 풀려도 이 창이 남아 있으면 새 인스턴스는 기존 인스턴스로
# 명령줄을 넘기고 종료하며, chromedriver는 그것을
# "user data directory is already in use"로 보고한다.
_MESSAGE_WINDOW_CLASS = "Chrome_MessageWindow"
_HWND_MESSAGE = wintypes.HWND(-3)

# 프로세스를 죽인 뒤 창과 잠금이 실제로 풀리기까지 걸리는 시간.
PROFILE_RELEASE_DELAY = 1.0


def _find_message_windows() -> list[tuple[int, str]]:
    """메시지 전용 창 중 Chromium 계열의 것을 (pid, 제목)으로 모은다."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowExW.restype = wintypes.HWND
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                                     wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    windows: list[tuple[int, str]] = []
    handle = None
    while True:
        handle = user32.FindWindowExW(_HWND_MESSAGE, handle, _MESSAGE_WINDOW_CLASS, None)
        if not handle:
            break
        buffer = ctypes.create_unicode_buffer(1024)
        user32.GetWindowTextW(handle, buffer, 1024)
        if not buffer.value:
            continue
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if pid.value:
            windows.append((pid.value, buffer.value))
    return windows


def find_profile_owner_pids(user_data_dir: str) -> list[int]:
    """해당 프로필을 선점하고 있는 브라우저 프로세스 목록.

    Chromium 자신이 쓰는 판정 방법이라 명령줄을 읽지 못하는 보호된
    프로세스에도 통한다.
    """
    target = os.path.normcase(os.path.normpath(user_data_dir))
    try:
        windows = _find_message_windows()
    except OSError:
        return []
    return [pid for pid, title in windows
            if os.path.normcase(os.path.normpath(title)) == target]


# Chromium 계열이 프로필을 선점할 때 쓰는 잠금 파일.
# Windows는 lockfile, POSIX는 SingletonLock을 쓴다. 이름을 잘못 보면
# 잔재를 못 지우고, 사용 중인지도 판정하지 못한다.
PROFILE_LOCK_FILES = ("lockfile", "SingletonLock")


def free_profile_lock(user_data_dir: str) -> bool:
    """프로필을 새 세션이 쓸 수 있는 상태인지 확인하고, 잔재 잠금은 지운다.

    이름 바꾸기가 되면 아무도 그 파일을 잡고 있지 않다는 뜻이므로 잔재로 보고
    지운다(브라우저가 다시 만든다). WinError 32로 실패하면 사용 중이다.

    프로세스 명령줄로 판정하지 않는 이유가 있다. Edge의 보호된 프로세스는
    cmdline과 open_files 모두 AccessDenied가 나고, psutil은 이때 None을
    돌려주기 때문에 '해당 없음'과 구분되지 않는다. 파일 잠금은 권한과
    무관하게 확실하다.
    """
    if not os.path.isdir(user_data_dir):
        return True

    for name in PROFILE_LOCK_FILES:
        path = os.path.join(user_data_dir, name)
        if not os.path.exists(path):
            continue
        stale = f"{path}.stale"
        try:
            os.replace(path, stale)
        except OSError:
            return False
        try:
            os.remove(stale)
        except OSError:
            pass
    return True


def terminate_profile_browsers(log: Log, user_data_dir: str) -> int:
    """지정한 Edge 프로필을 사용 중인 브라우저를 종료한다.

    자동화 전용 프로필만 대상으로 하므로 평소 쓰는 Edge 창은 건드리지 않는다.
    이 프로필을 쓰는 Edge가 살아 있으면 새 세션 생성이
    "user data directory is already in use"로 실패한다.
    """
    needle = user_data_dir.lower()
    killed = 0
    for proc in psutil.process_iter(["name", "cmdline"]):
        if proc.info.get("name") != EDGE_BROWSER_PROCESS:
            continue
        try:
            if not any(needle in arg.lower() for arg in (proc.info.get("cmdline") or [])):
                continue
            _kill(proc)
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if killed:
        log(f"[시스템] 자동화 프로필을 사용하던 Edge 프로세스 {killed}개를 정리했습니다.")
    return killed


def _kill_tree(pid: int) -> None:
    try:
        proc = psutil.Process(pid)
        children = proc.children(recursive=True)
    except psutil.Error:
        return
    for target in (*children, proc):
        try:
            _kill(target)
        except psutil.Error:
            pass


class _ShellExecuteInfoW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


# 사용자가 UAC 창에서 '아니오'를 눌렀을 때의 오류 코드.
ELEVATION_CANCELLED = 1223
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SW_HIDE = 0
_WAIT_TIMEOUT = 0x00000102


def run_elevated(executable: str, parameters: str, timeout: float = 180.0) -> int | None:
    """관리자 권한으로 실행하고 끝날 때까지 기다린 뒤 종료 코드를 돌려준다.

    프로그램 전체를 관리자 권한으로 올리면 Edge 자동화가 깨지므로, 권한이
    필요한 작업만 이렇게 잠깐 올려서 처리한다.

    사용자가 UAC 창을 취소하면 ELEVATION_CANCELLED, 실행 자체가 안 되면 None.
    """
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfoW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    info = _ShellExecuteInfoW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = parameters
    info.nShow = _SW_HIDE

    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        return ELEVATION_CANCELLED if error == ELEVATION_CANCELLED else None

    try:
        if kernel32.WaitForSingleObject(info.hProcess, int(timeout * 1000)) == _WAIT_TIMEOUT:
            return None
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)


# --- TAP 어댑터 (VPN 터널) ---
#
# 터널 하나당 TAP 어댑터 하나가 필요하다. LH와 공단을 동시에 쓰므로 2개가
# 있어야 하는데, SecuwaySSL 설치 프로그램은 1개만 만든다. 어댑터를 추가하는
# 도구(tapinstall.exe)와 드라이버(OemVista.inf)는 VPN 클라이언트와 함께
# 설치되므로 따로 배포할 필요가 없다.
TAP_COMPONENT_ID = "swutap0901"
TAP_REQUIRED_COUNT = 2
_TAP_TOOLKIT_ROOTS = (
    r"C:\Program Files (x86)\SecuwaySSLU",
    r"C:\Program Files\SecuwaySSLU",
)
_TAP_COUNT_PATTERN = re.compile(r"(\d+)\s+matching device")


def find_tap_toolkit(extra_roots: tuple[str, ...] = ()) -> tuple[str, str] | None:
    """(tapinstall.exe, OemVista.inf) 경로. 찾지 못하면 None."""
    for root in (*extra_roots, *_TAP_TOOLKIT_ROOTS):
        tool = os.path.join(root, "bin", "tapinstall.exe")
        inf = os.path.join(root, "driver", "OemVista.inf")
        if os.path.isfile(tool) and os.path.isfile(inf):
            return tool, inf
    return None


def _run_tapinstall(tool: str, args: list[str], cwd: str | None = None) -> tuple[int, str]:
    result = subprocess.run(
        [tool, *args],
        capture_output=True,
        cwd=cwd,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    output = (result.stdout + result.stderr).decode("utf-8", "replace")
    return result.returncode, output


def count_tap_adapters(toolkit: tuple[str, str] | None = None) -> int | None:
    """설치된 TAP 어댑터 개수. 도구를 못 찾거나 조회에 실패하면 None."""
    toolkit = toolkit or find_tap_toolkit()
    if not toolkit:
        return None
    code, output = _run_tapinstall(toolkit[0], ["hwids", TAP_COMPONENT_ID])
    if code != 0 and "matching device" not in output:
        return None
    match = _TAP_COUNT_PATTERN.search(output)
    return int(match.group(1)) if match else 0


def ensure_tap_adapters(log: Log, required: int = TAP_REQUIRED_COUNT,
                        extra_roots: tuple[str, ...] = ()) -> bool:
    """TAP 어댑터가 required개가 되도록 부족한 만큼 추가한다. 관리자 권한 필요."""
    toolkit = find_tap_toolkit(extra_roots)
    if not toolkit:
        log("[에러] TAP 어댑터 설치 도구를 찾지 못했습니다.")
        log("[에러]   공단 VPN 또는 LH VPN 홈페이지에서 VPN 클라이언트를 먼저 설치해 주세요.")
        return False

    tool, inf = toolkit
    current = count_tap_adapters(toolkit)
    if current is None:
        log("[에러] 현재 TAP 어댑터 개수를 확인하지 못했습니다.")
        return False

    log(f"[시스템] 현재 TAP 어댑터: {current}개 (필요 {required}개)")
    if current >= required:
        log("[시스템] 추가 설치가 필요하지 않습니다.")
        return True

    driver_dir = os.path.dirname(inf)
    for _ in range(required - current):
        code, output = _run_tapinstall(tool, ["install", inf, TAP_COMPONENT_ID], cwd=driver_dir)
        if code != 0:
            log(f"[에러] TAP 어댑터 추가 실패 (종료 코드 {code})")
            for line in output.splitlines():
                if line.strip():
                    log(f"[에러]   {line.strip()}")
            break
        log("[시스템] TAP 어댑터를 하나 추가했습니다.")

    final = count_tap_adapters(toolkit)
    log(f"[시스템] 설치 후 TAP 어댑터: {final}개")
    return final is not None and final >= required


def read_edge_policies() -> dict[str, int]:
    """브라우저 자동화를 막을 수 있는 Edge 정책 값을 읽는다.

    회사 정책으로 원격 디버깅이나 개발자 도구가 막혀 있으면 브라우저는
    정상 실행되는데 chromedriver만 붙지 못한다. 이때 chromedriver는 원인을
    프로필 충돌로 추측해 "user data directory is already in use"를 내보내서,
    로그만 보면 엉뚱한 곳을 파게 된다.
    """
    names = ("RemoteDebuggingAllowed", "DeveloperToolsAvailability")
    policies: dict[str, int] = {}
    for root, label in ((winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU")):
        try:
            with winreg.OpenKey(root, r"SOFTWARE\Policies\Microsoft\Edge") as key:
                for name in names:
                    try:
                        policies[f"{label}\\{name}"] = winreg.QueryValueEx(key, name)[0]
                    except OSError:
                        continue
        except OSError:
            continue
    return policies


def is_profile_available(user_data_dir: str) -> bool:
    """새 브라우저 세션이 이 프로필을 쓸 수 있는 상태인지 확인한다."""
    if find_profile_owner_pids(user_data_dir):
        return False
    return free_profile_lock(user_data_dir)


def release_profile(log: Log, user_data_dir: str) -> bool:
    """프로필을 새 세션이 쓸 수 있게 정리한다. 성공하면 True.

    선점 중인 브라우저를 프로세스 트리째 종료한 뒤, 명령줄로 잡히는 나머지
    프로세스도 정리한다. 자동화 전용 프로필만 대상이므로 평소 쓰는 Edge 창은
    건드리지 않는다.
    """
    if is_profile_available(user_data_dir):
        return True

    owners = find_profile_owner_pids(user_data_dir)
    if owners:
        listed = ", ".join(str(pid) for pid in owners)
        log(f"[시스템] 프로필을 선점 중인 브라우저(PID {listed})를 정리합니다.")
        for pid in owners:
            _kill_tree(pid)

    terminate_profile_browsers(log, user_data_dir)
    time.sleep(PROFILE_RELEASE_DELAY)
    return is_profile_available(user_data_dir)


def terminate_vpn_client(log: Log) -> tuple[int, int]:
    """꼬여 있는 VPN 클라이언트를 자식 프로세스까지 함께 종료한다.

    (종료한 개수, 발견한 개수)를 돌려준다. 종료에 실패한 경우와 애초에 없는
    경우를 구분해야 권한 문제를 알아챌 수 있다.
    """
    found = killed = 0
    for proc in _iter_by_name(VPN_CLIENT_PROCESS):
        found += 1
        try:
            for child in proc.children(recursive=True):
                try:
                    _kill(child)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            _kill(proc)
            killed += 1
        except psutil.AccessDenied:
            log(f"[경고] {VPN_CLIENT_PROCESS}(PID {proc.pid}) 종료 권한이 없습니다.")
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            pass

    if not found:
        log(f"[시스템] 실행 중인 {VPN_CLIENT_PROCESS} 프로세스가 없습니다.")
    elif killed:
        log(f"[시스템] {VPN_CLIENT_PROCESS} 프로세스 {killed}개를 종료했습니다.")
    return killed, found


class VpnKillResult(NamedTuple):
    """VPN 정리 결과. 두 작업의 성패를 따로 본다.

    접속 순서를 맞추는 데 필요한 것은 클라이언트 종료뿐이므로, hosts 초기화가
    막혀도 로그인 절차는 이어갈 수 있어야 한다.
    """

    clients_cleared: bool
    hosts_reset: bool

    @property
    def ok(self) -> bool:
        return self.clients_cleared and self.hosts_reset

    def to_exit_code(self) -> int:
        return (0 if self.clients_cleared else 1) | (0 if self.hosts_reset else 2)

    @classmethod
    def from_exit_code(cls, code: int) -> "VpnKillResult":
        return cls(clients_cleared=not code & 1, hosts_reset=not code & 2)


def perform_vpn_kill(log: Log, backup_dir: str) -> VpnKillResult:
    """VPN 클라이언트를 종료하고 hosts 파일을 초기화한다. 둘 다 관리자 권한이 필요하다."""
    log(f"[시스템] VPN 정리 작업 시작 (관리자 권한: {'예' if is_elevated() else '아니오'})")

    killed, found = terminate_vpn_client(log)
    clients_cleared = not found or bool(killed)
    if not clients_cleared:
        log("[에러] VPN 클라이언트를 종료하지 못했습니다. 관리자 권한이 필요합니다.")

    return VpnKillResult(clients_cleared, _reset_hosts(log, backup_dir))


def _reset_hosts(log: Log, backup_dir: str) -> bool:
    try:
        backup_path = backup_hosts_file(backup_dir)
    except OSError as exc:
        log(f"[에러] hosts 파일 백업 실패로 초기화를 중단했습니다: {exc}")
        return False
    log(f"[시스템] 초기화 전 hosts 파일을 백업했습니다: {backup_path}")

    try:
        reset_hosts_file()
    except PermissionError:
        if is_elevated():
            log("[에러] hosts 파일을 초기화하지 못했습니다. 다른 프로그램이 파일을 사용 중이거나,")
            log("[에러]   보안 프로그램이 hosts 파일 변경을 차단하고 있을 수 있습니다.")
        else:
            log("[에러] 권한이 부족해 hosts 파일을 초기화하지 못했습니다.")
        return False
    except OSError as exc:
        log(f"[에러] hosts 파일 초기화 중 에러 발생: {exc}")
        return False

    log("[시스템] hosts 파일 내용이 성공적으로 초기화되었습니다.")
    return True


def backup_hosts_file(destination_dir: str) -> str:
    """hosts 파일을 바이트 단위로 복사해 두고 백업 경로를 돌려준다.

    텍스트로 읽어 다시 쓰면 인코딩이 맞지 않는 줄이 조용히 손실된다.
    복원해서 그대로 쓸 수 있어야 하므로 반드시 바이너리 복사를 쓴다.
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(destination_dir, f"hosts_backup_{timestamp}.txt")
    shutil.copy2(HOSTS_FILE, backup_path)
    return backup_path


# VPN 클라이언트를 막 종료한 직후에는 hosts 핸들이 잠깐 남아 있을 수 있다.
HOSTS_WRITE_ATTEMPTS = 4
HOSTS_WRITE_RETRY_DELAY = 0.7


def reset_hosts_file() -> None:
    """hosts 파일 내용을 비운다.

    Windows는 권한 부족과 '다른 프로세스가 사용 중'을 둘 다 PermissionError로
    올린다. 후자는 잠깐 기다리면 풀리는 경우가 많아 몇 번 재시도한다.
    """
    last_error: PermissionError | None = None
    for attempt in range(HOSTS_WRITE_ATTEMPTS):
        try:
            with open(HOSTS_FILE, "w", encoding="utf-8") as f:
                f.write("")
            return
        except PermissionError as exc:
            last_error = exc
            if attempt + 1 < HOSTS_WRITE_ATTEMPTS:
                time.sleep(HOSTS_WRITE_RETRY_DELAY)
    raise last_error  # type: ignore[misc]
