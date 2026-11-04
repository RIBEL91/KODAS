"""테스트 → exe 빌드 → 배포 폴더(dist\\공문작성기) 만들기.

    .venv\\Scripts\\python.exe build.py

배치파일 대신 파이썬으로 빌드한다(한글 경로·파일명을 cmd가 잘못 읽는 문제 회피).
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "공문작성기"
OUT = os.path.join(ROOT, "dist", NAME)


def main():
    os.chdir(ROOT)
    if subprocess.call([sys.executable, "-m", "pytest", "tests", "-q"]) != 0:
        sys.exit("테스트 실패 — 빌드를 멈춥니다.")
    import PyInstaller.__main__

    def p(*parts):   # spec 파일이 build\에 생기므로 경로는 모두 절대 경로로 준다
        return os.path.join(ROOT, *parts)
    PyInstaller.__main__.run([
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", NAME, "--icon", p("assets", "app.ico"),
        "--paths", p("app"),
        # webdriver.Chrome/Edge 지연 임포트를 PyInstaller가 놓치지 않도록
        "--collect-submodules", "selenium",
        "--collect-data", "sv_ttk",
        "--collect-data", "babel", "--hidden-import", "babel.numbers",   # 달력(tkcalendar) 한국어
        "--add-data", f"{p('assets')}{os.pathsep}assets",
        "--add-data", f"{p('서식')}{os.pathsep}서식",
        "--distpath", OUT, "--workpath", p("build"), "--specpath", p("build"),
        p("app", "gui.py"),
    ])
    shutil.copytree(os.path.join(ROOT, "서식"), os.path.join(OUT, "서식"), dirs_exist_ok=True)
    shutil.copy(os.path.join(ROOT, "사용안내.txt"), OUT)
    print(f"\n완료: {os.path.join(OUT, NAME + '.exe')}")


if __name__ == "__main__":
    main()
