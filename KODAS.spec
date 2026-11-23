# -*- mode: python ; coding: utf-8 -*-
# KODAS 파일 하나짜리 exe 빌드 설정 (build.py가 부른다: .venv\Scripts\python.exe build.py)
# 기능은 그대로 두고 쓰지 않는 것만 빼서 용량을 줄인다:
#  - 다른 운영체제용 selenium-manager(맥·리눅스) — 윈도우용만 둔다
#  - 달력(babel) 언어 자료 — 한국어·영어·기본(root)만 둔다
#  - 쓰지 않는 모듈: numpy(openpyxl이 있으면 쓰는 선택 모듈), pytest·pygments(selenium의 trio 테스트 도구가 끌고 옴),
#    yaml, fontTools(PDF 글꼴 줄이기 기능 — KODAS는 안 씀), AVIF·Qt 그림 모듈
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

ROOT = SPECPATH
P = lambda *x: os.path.join(ROOT, *x)

datas = [(P('assets'), 'assets'), (P('서식'), '서식')]
binaries = []
hiddenimports = ['babel.numbers']
datas += collect_data_files('sv_ttk')
datas += collect_data_files('babel')
hiddenimports += collect_submodules('selenium')         # webdriver.Chrome/Edge 지연 임포트
tmp = collect_all('winrt')                                # 원터치 자동작성: Windows OCR
datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

EXCLUDES = ['numpy', 'pytest', '_pytest', 'pygments', 'yaml', 'fontTools',
            'PIL.AvifImagePlugin', 'PIL._avif', 'PIL.ImageQt', 'tkinter.test']

a = Analysis(
    [P('app', 'gui.py')],
    pathex=[P('app')],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[P('tools', 'rth_keep_exe_open.py')],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

BABEL_KEEP = ('root.dat', 'ko.dat', 'ko_KR.dat', 'en.dat', 'en_US.dat')


def keep(entry) -> bool:
    dest = entry[0].replace('\\', '/')
    if dest.startswith('selenium/webdriver/common/') and '/selenium-manager' in dest \
            and not dest.startswith('selenium/webdriver/common/windows/'):
        return False
    if dest.startswith('babel/locale-data/') and dest.rsplit('/', 1)[-1] not in BABEL_KEEP:
        return False
    return True


a.binaries = [e for e in a.binaries if keep(e)]
a.datas = [e for e in a.datas if keep(e)]

pyz = PYZ(a.pure)

# 시작 화면 아래 점 세 개(●○○)가 차례로 주황색이 되며 움직인다 — 멈춘 게 아니라 여는 중임을 보여 준다.
# 시작 화면은 exe가 풀리는 동안에도 따로 돌아가는 Tcl/Tk 스크립트라, 그 끝에 애니메이션을 붙인다.
# 점 자리는 assets/splash.png의 점(가운데 x 156·170·184, y 170, 지름 9)과 같다.
SPLASH_DOTS_TCL = r'''
set _kodas_dots {}
foreach _cx {156 170 184} {
lappend _kodas_dots [.root.canvas create oval [expr {$_cx - 4.5}] 165.5 [expr {$_cx + 4.5}] 174.5 -fill white -outline white]
}
set _kodas_i 0
proc _kodas_tick {} {
global _kodas_dots _kodas_i
set n 0
foreach d $_kodas_dots {
set c [expr {$n == $_kodas_i ? "#FFB21F" : "white"}]
.root.canvas itemconfigure $d -fill $c -outline $c
incr n
}
set _kodas_i [expr {($_kodas_i + 1) % 3}]
after 350 _kodas_tick
}
_kodas_tick
'''


class DotsSplash(Splash):
    def generate_script(self):
        script = super().generate_script() + "\n" + SPLASH_DOTS_TCL.strip() + "\n"
        with open(self.script_name, "w", encoding="utf-8") as f:
            f.write(script)
        return script


splash = DotsSplash(                # 풀리는 몇 초 동안 '여는 중' 화면 (gui.bring_to_front에서 닫음)
    P('assets', 'splash.png'),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [],
    name='KODAS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # UPX 압축은 백신 오탐·느린 시작 때문에 쓰지 않는다
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[P('assets', 'app.ico')],
)
