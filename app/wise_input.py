"""마우스·키보드 입력과 창 찾기(Windows API). 편리한 임대업무 앱의 winput.py에서 가져왔다(WISE 자동작성용)."""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32

# 화면 좌표를 실제 픽셀로 쓰는 설정(DPI 인식)은 gui.main에서 한다.

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x2, 0x4
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, MOUSEEVENTF_WHEEL = 0x2, 0x4, 0x0800
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _mouse(flags, data=0):
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, 0)
    return i


def _kbd(vk=0, scan=0, flags=0):
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


VK = {"enter": 0x0D, "esc": 0x1B, "tab": 0x09, "ctrl": 0x11, "a": 0x41, "down": 0x28, "up": 0x26,
      "delete": 0x2E, "backspace": 0x08, "home": 0x24}


def click(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.1)
    _send(_mouse(MOUSEEVENTF_LEFTDOWN), _mouse(MOUSEEVENTF_LEFTUP))
    time.sleep(0.1)


def double_click(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.1)
    _send(_mouse(MOUSEEVENTF_LEFTDOWN), _mouse(MOUSEEVENTF_LEFTUP))
    time.sleep(0.05)
    _send(_mouse(MOUSEEVENTF_LEFTDOWN), _mouse(MOUSEEVENTF_LEFTUP))
    time.sleep(0.1)


def wheel(x: int, y: int, notches: int) -> None:
    """(x, y)에서 마우스 휠. notches가 음수면 아래로."""
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    _send(_mouse(MOUSEEVENTF_WHEEL, 120 * notches))
    time.sleep(0.1)


def maximize(hwnd: int) -> None:
    user32.ShowWindow(hwnd, 3)            # SW_MAXIMIZE
    time.sleep(0.5)


def key(combo: str) -> None:
    names = combo.lower().split("+")
    for n in names:
        _send(_kbd(vk=VK[n]))
    for n in reversed(names):
        _send(_kbd(vk=VK[n], flags=KEYEVENTF_KEYUP))
    time.sleep(0.05)


def type_text(s: str) -> None:
    for ch in s:
        code = ord(ch)
        _send(_kbd(scan=code, flags=KEYEVENTF_UNICODE),
              _kbd(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        time.sleep(0.005)


def esc_pressed() -> bool:
    """ESC를 누르고 있거나 마지막 확인 뒤 눌렀으면 True."""
    return bool(user32.GetAsyncKeyState(0x1B) & 0x8001)


# ---------- 창 ----------
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_window(title: str, class_name: str = "") -> int:
    """제목이 title인(정확히) 보이는 최상위 창의 핸들. 없으면 0."""
    found = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value == title:
            if class_name:
                cbuf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cbuf, 256)
                if cbuf.value != class_name:
                    return True
            found.append(hwnd)
            return False
        return True
    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else 0


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def is_maximized(hwnd: int) -> bool:
    return bool(user32.IsZoomed(hwnd))


def activate(hwnd: int) -> None:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)        # SW_RESTORE
    user32.keybd_event(0x12, 0, 0, 0)     # Alt를 눌렀다 떼면 SetForegroundWindow가 막히지 않는다
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
