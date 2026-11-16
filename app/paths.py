"""프로그램 폴더·사용자 데이터 폴더 경로.

exe(PyInstaller onefile, 영철ai\\KODAS.exe)는 파일 하나만 옮겨도 그대로 쓰이도록
자기 옆에 아무것도 두지 않는다.
- 설정·서식·작업 기록·미리보기·받은 대장 문서: %APPDATA%\\공문작성기 (exe를 어디에 두든 유지)
- 기본 서식은 exe 안에 들어 있고, 실행할 때 사용자 서식 폴더로 맞춰 꺼낸다(sync_templates)
소스로 실행할 때는 저장소 폴더(서식, logs, output, 수집)를 그대로 쓴다.
"""
import hashlib
import json
import os
import shutil
import sys

APP_NAME = "공문작성기"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def program_dir() -> str:
    if frozen():
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


def data_dir() -> str:
    """서식·기록 등 작업 데이터를 두는 곳. exe는 사용자 폴더, 소스 실행은 저장소 폴더."""
    return user_dir() if frozen() else program_dir()


def sub_dir(*parts: str) -> str:
    path = os.path.join(data_dir(), *parts)
    os.makedirs(path, exist_ok=True)
    return path


def template_dir() -> str:
    """서식 폴더. exe로 실행하면 번들 기본 서식을 사용자 서식 폴더에 맞춰 둔다."""
    folder = os.path.join(data_dir(), "서식")
    src = os.path.join(bundle_dir(), "서식")
    if os.path.isdir(src) and os.path.abspath(src) != os.path.abspath(folder):
        try:
            sync_templates(src, folder)
        except OSError:
            pass
    os.makedirs(folder, exist_ok=True)
    return folder


MANIFEST = ".기본서식.json"


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def sync_templates(src: str, dst: str) -> None:
    """번들 기본 서식(src)을 사용자 서식 폴더(dst)에 맞춘다.

    - 처음 보는 기본 서식은 복사한다(새 버전에 추가된 서식이 생긴다).
    - 사용자가 고치지 않은 서식은 새 버전 내용으로 바꾼다.
    - 사용자가 고친 서식, 직접 만든 서식은 건드리지 않는다. 사용자가 지운 기본 서식은 되살리지 않는다.
    어떤 기본 서식을 어떤 내용으로 꺼냈는지는 dst의 MANIFEST에 적어 둔다.
    """
    os.makedirs(dst, exist_ok=True)
    mpath = os.path.join(dst, MANIFEST)
    try:
        with open(mpath, encoding="utf-8") as f:
            seen = json.load(f)
    except (OSError, ValueError):
        seen = {}
    if not isinstance(seen, dict):
        seen = {}
    changed = False
    for base, _dirs, files in os.walk(src):
        for name in files:
            s = os.path.join(base, name)
            rel = os.path.relpath(s, src).replace("\\", "/")
            d = os.path.join(dst, rel)
            new = _sha(s)
            old = seen.get(rel)
            if old == new:
                continue
            if os.path.exists(d):
                cur = _sha(d)
                if cur != new and cur != old:      # 사용자가 고친 서식(또는 같은 이름의 직접 만든 서식)
                    if old is None:
                        seen[rel] = new             # 다음부터는 고친 서식으로 본다
                        changed = True
                    continue
            elif old is not None:                   # 사용자가 지운 기본 서식
                seen[rel] = new
                changed = True
                continue
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            seen[rel] = new
            changed = True
    if changed:
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(seen, f, ensure_ascii=False, indent=0)
