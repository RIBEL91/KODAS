"""프로그램 폴더·사용자 데이터 폴더 경로.

exe(PyInstaller onefile)와 소스 실행 양쪽에서 같은 규칙을 쓴다.
- 사용자 설정은 %APPDATA%\\공문작성기 (exe를 어디에 두든 유지)
- 서식·작업 기록·미리보기는 프로그램 폴더 아래
"""
import os
import shutil
import sys

APP_NAME = "공문작성기"


def program_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundle_dir() -> str:
    """번들 리소스(assets, 서식) 위치. onefile exe는 임시 폴더(_MEIPASS)에 풀린다."""
    return getattr(sys, "_MEIPASS", None) or program_dir()


def user_dir() -> str:
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def sub_dir(*parts: str) -> str:
    path = os.path.join(program_dir(), *parts)
    os.makedirs(path, exist_ok=True)
    return path


def template_dir() -> str:
    """서식 폴더. exe 옆에 없으면 번들에 든 기본 서식을 꺼내 둔다(사용자가 고칠 수 있도록)."""
    folder = os.path.join(program_dir(), "서식")
    if not os.path.isdir(folder) or not os.listdir(folder):
        src = os.path.join(bundle_dir(), "서식")
        if os.path.isdir(src) and os.path.abspath(src) != os.path.abspath(folder):
            shutil.copytree(src, folder, dirs_exist_ok=True)
    os.makedirs(folder, exist_ok=True)
    return folder
