"""프로그램 폴더·사용자 데이터 폴더 경로.

exe(PyInstaller onefile, 영철ai/KODAS/KODAS.exe)는 자기 옆 'KODAS 데이터' 폴더에 모든 기록을 둔다
(2026-11-20: 인사이동 때 KODAS 폴더만 압축해 가져가면 서식·설정·일정·기록이 그대로 따라가게).
- 설정·서식·작업 기록·미리보기·받은 대장 문서·일정표·나의 공문: KODAS.exe 옆 'KODAS 데이터'
  (그 폴더에 쓸 수 없으면 예전처럼 %APPDATA%/공문작성기)
- 예전 버전이 %APPDATA%/공문작성기에 둔 기록은 처음 한 번 'KODAS 데이터'로 복사한다(원본은 그대로 둔다)
- 홈넷·VPN 계정은 PC마다 다른 키로 암호화돼 있어 다른 PC에서는 다시 넣어야 한다(settings_store)
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


PORTABLE_NAME = "KODAS 데이터"
SKIP_COPY = ("browser",)          # PC마다 다른 브라우저 임시 자료는 옮기지 않는다
_USER_DIR = None


def legacy_dir() -> str:
    """예전 버전의 기록 폴더(%APPDATA%/공문작성기)."""
    return os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), APP_NAME)


def _writable(folder: str) -> bool:
    try:
        os.makedirs(folder, exist_ok=True)
        test = os.path.join(folder, ".쓰기확인")
        with open(test, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test)
        return True
    except OSError:
        return False


def migrate(old: str, new: str) -> bool:
    """예전 기록 폴더(old)를 새 폴더(new)로 한 번 복사한다. new에 이미 설정이 있으면 하지 않는다."""
    if not os.path.isdir(old) or os.path.exists(os.path.join(new, "settings.json")):
        return False
    os.makedirs(new, exist_ok=True)
    for name in os.listdir(old):
        if name in SKIP_COPY:
            continue
        s, d = os.path.join(old, name), os.path.join(new, name)
        try:
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
            elif not os.path.exists(d):
                shutil.copy2(s, d)
        except OSError:
            pass
    sp = os.path.join(new, "settings.json")           # 설정 속 예전 폴더 경로(디자인 사진 등)를 새 폴더로
    try:
        with open(sp, encoding="utf-8") as f:
            text = f.read()
        for a, b in ((old, new), (old.replace(os.sep, "/"), new.replace(os.sep, "/"))):
            text = text.replace(json.dumps(a, ensure_ascii=False)[1:-1], json.dumps(b, ensure_ascii=False)[1:-1])
        with open(sp, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass
    return True


def user_dir() -> str:
    """기록 폴더. exe는 KODAS.exe 옆 'KODAS 데이터'(쓸 수 없으면 %APPDATA%/공문작성기), 소스 실행은 %APPDATA%."""
    global _USER_DIR
    if _USER_DIR and os.path.isdir(_USER_DIR):
        return _USER_DIR
    path = legacy_dir()
    if frozen():
        portable = os.path.join(program_dir(), PORTABLE_NAME)
        if _writable(portable):
            migrate(legacy_dir(), portable)
            path = portable
    os.makedirs(path, exist_ok=True)
    _USER_DIR = path
    return path


def data_file(path: str) -> str:
    """설정에 적힌 기록 폴더 안 파일 경로를 지금 기록 폴더 기준으로(폴더째 옮긴 뒤에도 찾게)."""
    if not path or os.path.isfile(path):
        return path
    alt = os.path.join(user_dir(), os.path.basename(path))
    return alt if os.path.isfile(alt) else path


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
