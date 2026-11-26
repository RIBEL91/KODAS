"""내 데이터 내려받기·등록하기(환경 설정).

KODAS 데이터 폴더(설정·단지기본정보·서식·자격검증 기록·나의공문·업무일정·품질평가 대장 등)를
zip 파일 하나로 묶어 내려받고, 그 파일을 다른 PC(또는 새 KODAS)에서 등록하면 같은 설정으로 쓴다.

- 로그·출력물·브라우저 기록처럼 다시 생기는 것은 넣지 않는다.
- 등록하기 전에 지금 데이터를 '백업\\데이터등록전_날짜.zip'으로 남긴다.
- 계정 비밀번호는 PC마다 다른 키로 암호화돼 있어 다른 PC에서는 다시 넣어야 한다.
"""
import datetime as dt
import json
import os
import shutil
import zipfile

import paths

MARK = "KODAS_내데이터.json"          # zip 안 표지 파일(KODAS가 만든 파일인지 확인)
SKIP_DIRS = {"logs", "output", "browser", "__pycache__", "백업"}
SKIP_EXT = (".lock", ".tmp", ".old")
REPLACE_DIRS = ("서식",)               # 등록할 때 통째로 바꾸는 폴더(지운 서식이 남지 않게)


class DataError(Exception):
    pass


def _folders() -> list[str]:
    """내려받을 폴더: 기록 폴더(설정 등), 소스 실행이면 서식·기록이 있는 저장소 폴더 쪽도."""
    out = [paths.user_dir()]
    d = paths.data_dir()
    if os.path.abspath(d) != os.path.abspath(out[0]):
        out.append(d)
    return out


def _files(root: str):
    """root 아래 내려받을 파일 (전체 경로, zip 안 이름)."""
    for cur, dirs, files in os.walk(root):
        rel = os.path.relpath(cur, root)
        if rel == ".":
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            if os.path.abspath(root) != os.path.abspath(paths.user_dir()):
                dirs[:] = [x for x in dirs if x in REPLACE_DIRS]     # 저장소 폴더는 서식만
                files = []
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for f in files:
            if f.lower().endswith(SKIP_EXT) or f == MARK:
                continue
            full = os.path.join(cur, f)
            yield full, os.path.normpath(os.path.join(rel, f)).replace(os.sep, "/")


def default_name(today: dt.date | None = None) -> str:
    return f"KODAS 내데이터_{(today or dt.date.today()):%Y%m%d}.zip"


def export_zip(dst: str) -> int:
    """내 데이터를 dst(zip)로 묶는다. 넣은 파일 수."""
    n, seen = 0, set()
    tmp = dst + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for root in _folders():
            for full, arc in _files(root):
                if arc in seen:
                    continue
                seen.add(arc)
                z.write(full, arc)
                n += 1
        z.writestr(MARK, json.dumps({"made": dt.datetime.now().isoformat(timespec="seconds"),
                                     "files": n}, ensure_ascii=False, indent=1))
    os.replace(tmp, dst)
    return n


def check_zip(src: str) -> dict:
    """등록할 zip을 확인한다. 표지 내용(+names)을 돌려준다. KODAS 데이터가 아니면 DataError."""
    try:
        z = zipfile.ZipFile(src)
    except (OSError, zipfile.BadZipFile) as e:
        raise DataError(f"zip 파일을 열지 못했습니다: {e}")
    with z:
        names = z.namelist()
        if MARK not in names:
            raise DataError("KODAS [내 데이터 내려받기]로 만든 파일이 아닙니다.")
        for nm in names:
            p = nm.replace("\\", "/")
            if p.startswith("/") or ".." in p.split("/") or ":" in p:
                raise DataError(f"파일 안에 잘못된 경로가 있습니다: {nm}")
        try:
            info = json.loads(z.read(MARK).decode("utf-8"))
        except ValueError:
            info = {}
    info["names"] = [x for x in names if x != MARK and not x.endswith("/")]
    return info


def backup_current() -> str:
    """지금 데이터를 백업 폴더에 zip으로 남긴다. 만든 파일 경로."""
    folder = os.path.join(paths.user_dir(), "백업")
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, f"데이터등록전_{dt.datetime.now():%Y%m%d_%H%M%S}.zip")
    export_zip(dst)
    return dst


def import_zip(src: str) -> tuple[int, str]:
    """zip의 데이터를 기록 폴더에 넣는다(서식 폴더는 통째로 바꾼다). (넣은 파일 수, 백업 파일)."""
    info = check_zip(src)
    backup = backup_current()
    user, data = paths.user_dir(), paths.data_dir()
    tops = {n.split("/")[0] for n in info["names"]}
    for d in REPLACE_DIRS:
        if d in tops:
            target = os.path.join(data, d)
            if os.path.isdir(target):
                shutil.rmtree(target)
    n = 0
    with zipfile.ZipFile(src) as z:
        for nm in info["names"]:
            base = data if nm.split("/")[0] in REPLACE_DIRS else user
            out = os.path.join(base, *nm.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with z.open(nm) as fsrc, open(out, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst)
            n += 1
    return n, backup


def wipe(folder: str | None = None) -> list[str]:
    """[데이터 초기화]: 기록 폴더(KODAS 데이터) 안을 모두 지운다 — 단지기본정보·설정·계정·서식·기록·일정·백업까지.
    폴더 자체는 남긴다. 지우지 못한 것(열려 있는 파일 등)의 이름 목록을 돌려준다.
    서식은 다음 실행 때 exe 안 기본 서식으로 다시 채워진다."""
    folder = folder or paths.user_dir()
    left = []
    for name in os.listdir(folder):
        p = os.path.join(folder, name)
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
        except OSError:
            left.append(name)
    try:                                     # 초기화 표시: 다시 켤 때 예전 기록을 끌어오지 않게
        with open(os.path.join(folder, paths.RESET_MARK), "w", encoding="utf-8") as f:
            f.write("KODAS [데이터 초기화]로 비운 폴더입니다. 바탕화면 관계철 엑셀 등에서 기록을 다시 가져오지 않습니다.\n")
    except OSError:
        pass
    return left


# ---------------- 자동 백업(한 달마다) ----------------
# 데이터 초기화·실수로 지움에 대비해, KODAS를 켤 때 마지막 자동 백업이 한 달(AUTO_DAYS일)이 지났으면
# 내 데이터를 zip으로 남긴다. 자리는 KODAS 데이터 '밖'(KODAS.exe 옆 'KODAS 자동백업')이라 초기화해도 남는다.
# 되살리기: [환경 설정 → 내 데이터 등록하기]에서 그 zip을 고른다. 최근 AUTO_KEEP개만 남긴다.
AUTO_DIR_NAME = "KODAS 자동백업"
AUTO_PREFIX = "KODAS 자동백업_"
AUTO_DAYS = 30
AUTO_KEEP = 12


def auto_dir() -> str:
    """자동 백업 폴더: KODAS.exe 옆(쓸 수 없으면 문서 폴더)."""
    for base in (paths.program_dir(), os.path.join(os.path.expanduser("~"), "Documents")):
        d = os.path.join(base, AUTO_DIR_NAME)
        try:
            os.makedirs(d, exist_ok=True)
            test = os.path.join(d, ".쓰기확인")
            with open(test, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(test)
            return d
        except OSError:
            continue
    raise OSError("자동 백업 폴더를 만들 수 없습니다.")


def auto_list(folder: str) -> list[str]:
    """자동 백업 zip들(오래된 것부터)."""
    try:
        names = [n for n in os.listdir(folder) if n.startswith(AUTO_PREFIX) and n.lower().endswith(".zip")]
    except OSError:
        return []
    return [os.path.join(folder, n) for n in sorted(names)]


def auto_backup(folder: str | None = None, now: dt.datetime | None = None,
                days: int = AUTO_DAYS, keep: int = AUTO_KEEP) -> str | None:
    """마지막 자동 백업이 days일 지났으면(또는 없으면) 새로 만든다. 만든 파일 경로, 안 만들었으면 None.
    설정 파일이 없으면(처음 상태·초기화 직후) 만들지 않는다 — 빈 데이터로 좋은 백업을 밀어내지 않게."""
    now = now or dt.datetime.now()
    if not os.path.exists(os.path.join(paths.user_dir(), "settings.json")):
        return None
    folder = folder or auto_dir()
    old = auto_list(folder)
    if old:
        last = dt.datetime.fromtimestamp(os.path.getmtime(old[-1]))
        if now - last < dt.timedelta(days=days):
            return None
    dst = os.path.join(folder, f"{AUTO_PREFIX}{now:%Y%m%d_%H%M}.zip")
    export_zip(dst)
    for p in auto_list(folder)[:-keep]:          # 오래된 것 정리
        try:
            os.remove(p)
        except OSError:
            pass
    return dst
