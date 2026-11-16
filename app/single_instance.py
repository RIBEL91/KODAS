"""KODAS는 하나만 열리게 한다.

윈도 이름 있는 뮤텍스(Local\\KODAS_공문작성기)를 잡는다. 이미 누가 잡고 있으면(=KODAS가 열려 있으면)
열려 있는 KODAS 창을 앞으로 올리고 새로 연 것은 끝낸다.
디자인을 바꾸고 '다시 시작'할 때는 이전 창이 닫히는 동안 잠깐 기다린다(wait).
"""
import ctypes
import os
import time
from ctypes import wintypes

MUTEX_NAME = "Local\\KODAS_공문작성기"
TITLE_PREFIX = "KODAS — 공문 자동작성 시스템"
ERROR_ALREADY_EXISTS = 183
_handle = None          # 프로그램이 끝날 때까지 쥐고 있는다(놓으면 다른 KODAS가 열린다)


def acquire(wait: float = 0) -> bool:
    """뮤텍스를 잡으면 True(이 KODAS가 유일). wait초 동안은 이전 KODAS가 닫히기를 기다린다."""
    global _handle
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    end = time.time() + wait
    while True:
        h = k32.CreateMutexW(None, False, MUTEX_NAME)
        if not h:
            return True                     # 뮤텍스를 못 만들면 막지 않는다(프로그램은 열리게)
        if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
            _handle = h
            return True
        k32.CloseHandle(h)
        if time.time() >= end:
            return False
        time.sleep(0.3)


def find_window() -> int:
    """열려 있는 다른 KODAS 본 창의 핸들(없으면 0)."""
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    found = []
    me = os.getpid()
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lp):
        if not u32.IsWindowVisible(hwnd):
            return True
        n = u32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        if buf.value.startswith(TITLE_PREFIX):
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != me:
                found.append(hwnd)
                return False
        return True

    u32.EnumWindows(proto(cb), 0)
    return found[0] if found else 0


def show_existing() -> bool:
    """열려 있는 KODAS 창을 앞으로(최소화돼 있으면 되살려서). 찾으면 True."""
    hwnd = find_window()
    if not hwnd:
        return False
    u32 = ctypes.WinDLL("user32")
    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, 9)             # SW_RESTORE
    else:
        u32.ShowWindow(hwnd, 5)             # SW_SHOW
    u32.SetForegroundWindow(hwnd)
    return True
