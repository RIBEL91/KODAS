"""테스트 → 파일 하나짜리 exe 빌드 → 영철ai\\KODAS.exe (메인 실행 파일).

    .venv\\Scripts\\python.exe build.py

- 메인 실행 파일: 바탕화면\\영철ai\\KODAS.exe. 이 파일 하나만 옮겨도 실행된다
  (서식·아이콘은 exe 안에, 설정·서식·기록은 %APPDATA%\\공문작성기에 둔다 → paths.py).
- GitHub 업로드용 사본: 저장소의 dist\\KODAS.exe (메인과 같은 파일).
배치파일 대신 파이썬으로 빌드한다(한글 경로·파일명을 cmd가 잘못 읽는 문제 회피).
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "KODAS"
MAIN_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "영철ai")     # 메인 실행 파일이 놓이는 곳
UPLOAD_DIR = os.path.join(ROOT, "dist")                                  # 저장소에 올릴 사본


def _put(src: str, folder: str) -> str:
    """exe를 folder에 놓는다. 이전 exe가 실행 중이면 이름을 .old로 비켜 두고 바꾼다."""
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, NAME + ".exe")
    import glob
    for old in glob.glob(glob.escape(dst) + ".old*"):
        try:
            os.remove(old)                     # 지난번에 비켜 둔 파일(이제 안 쓰이면 지워진다)
        except OSError:
            pass
    if os.path.exists(dst):
        try:
            os.remove(dst)
        except OSError:                        # 실행 중이라 못 지움 → 비어 있는 .old 이름으로 비켜 둔다
            n = 1
            while os.path.exists(dst + (".old" if n == 1 else f".old{n}")):
                n += 1
            os.replace(dst, dst + (".old" if n == 1 else f".old{n}"))
    shutil.copy2(src, dst)
    return dst


def main():
    os.chdir(ROOT)
    if subprocess.call([sys.executable, "-m", "pytest", "tests", "-q"]) != 0:
        sys.exit("테스트 실패 — 빌드를 멈춥니다.")
    import PyInstaller.__main__

    def p(*parts):   # spec 파일이 build\에 생기므로 경로는 모두 절대 경로로 준다
        return os.path.join(ROOT, *parts)
    out = p("build", "exe")
    PyInstaller.__main__.run([
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", NAME, "--icon", p("assets", "app.ico"),
        "--splash", p("assets", "splash.png"),     # 풀리는 몇 초 동안 '여는 중' 화면 (gui.bring_to_front에서 닫음)
        "--paths", p("app"),
        # webdriver.Chrome/Edge 지연 임포트를 PyInstaller가 놓치지 않도록
        "--collect-submodules", "selenium",
        "--collect-data", "sv_ttk",
        "--collect-all", "winrt",                  # 원터치 자동작성: Windows OCR로 WISE 화면 글자 읽기
        "--collect-data", "babel", "--hidden-import", "babel.numbers",   # 달력(tkcalendar) 한국어
        "--add-data", f"{p('assets')}{os.pathsep}assets",
        "--add-data", f"{p('서식')}{os.pathsep}서식",
        "--distpath", out, "--workpath", p("build"), "--specpath", p("build"),
        p("app", "gui.py"),
    ])
    built = os.path.join(out, NAME + ".exe")
    print(f"\n메인 실행 파일: {_put(built, MAIN_DIR)}")
    print(f"업로드용 사본: {_put(built, UPLOAD_DIR)}")


if __name__ == "__main__":
    main()
