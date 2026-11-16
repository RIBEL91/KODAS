"""KODAS 하나만 열기: 이미 뮤텍스를 쥔 KODAS가 있으면 두 번째는 못 잡는다."""
import ctypes
import os
import subprocess
import sys

APP = os.path.join(os.path.dirname(__file__), "..", "app")
sys.path.insert(0, APP)

import single_instance as si  # noqa: E402

CHILD = ("import sys; sys.path.insert(0, sys.argv[1]); import single_instance as si; "
         "si.MUTEX_NAME = sys.argv[2]; print(si.acquire(wait=float(sys.argv[3])))")


def _child(name, wait=0):
    out = subprocess.run([sys.executable, "-c", CHILD, APP, name, str(wait)], capture_output=True, text=True,
                         timeout=30)
    return out.stdout.strip()


def test_second_instance_blocked(monkeypatch):
    name = f"Local\\KODAS_test_{os.getpid()}"
    monkeypatch.setattr(si, "MUTEX_NAME", name)
    monkeypatch.setattr(si, "_handle", None)
    assert si.acquire() is True
    try:
        assert _child(name) == "False"              # 이미 열려 있음
    finally:
        ctypes.windll.kernel32.CloseHandle(si._handle)
    assert _child(name) == "True"                   # 닫힌 뒤에는 열림


def test_find_window_ignores_others():
    assert isinstance(si.find_window(), int)
