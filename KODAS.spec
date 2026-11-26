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

# 시작 화면 아래 진행 칸 15개가 왼쪽부터 파랑→초록으로 차례로 차오르고, 다 차면 다시 비운다(WISE 처리중 화면처럼).
# 시작 화면은 exe가 풀리는 동안에도 따로 돌아가는 Tcl/Tk 스크립트라, 그 끝에 애니메이션을 붙인다.
# 칸 자리는 tools/make_splash.py의 BLOCKS(x 56부터 29px 간격, y 118, 25×10)와 같다.
SPLASH_DOTS_TCL = r'''
set _kodas_cols {#0a5cb8 #1162b0 #1868a9 #1f6ea1 #257499 #2c7a91 #33808a #3a8682 #418c7a #489273 #4f986b #559e63 #5ca45b #63aa54 #6ab04c}
set _kodas_blocks {}
for {set i 0} {$i < 15} {incr i} {
set x [expr {56 + $i * 29}]
lappend _kodas_blocks [.root.canvas create rectangle [expr {$x + 1}] 119 [expr {$x + 24}] 127 -fill [lindex $_kodas_cols $i] -outline [lindex $_kodas_cols $i] -state hidden]
}
set _kodas_i 0
proc _kodas_tick {} {
global _kodas_blocks _kodas_i
set n 0
foreach b $_kodas_blocks {
.root.canvas itemconfigure $b -state [expr {$n < $_kodas_i ? "normal" : "hidden"}]
incr n
}
set _kodas_i [expr {($_kodas_i + 1) % 17}]
after 140 _kodas_tick
}
_kodas_tick
'''


# 시작 화면 바깥 그림자: Windows 시작 화면은 반투명 그림을 못 쓰므로, 검은 둥근 사각형 창(각 6% 투명도)을
# 조금씩 크게 7겹 겹쳐 가장자리로 갈수록 옅어지는 부드러운 그림자를 만든다(아래로 6px 내림).
# 그림(assets/splash.png, tools/make_splash.py)의 모서리 반지름 12와 맞춘다. 시작 화면이 닫히면 함께 닫힌다.
SPLASH_SHADOW_TCL = r'''
proc _kodas_rr {c x0 y0 x1 y1 r} {
set p [list $x0 [expr {$y0+$r}] $x0 $y0 [expr {$x0+$r}] $y0 [expr {$x1-$r}] $y0 $x1 $y0 $x1 [expr {$y0+$r}] $x1 [expr {$y1-$r}] $x1 $y1 [expr {$x1-$r}] $y1 [expr {$x0+$r}] $y1 $x0 $y1 $x0 [expr {$y1-$r}]]
$c create polygon $p -smooth 1 -fill black -outline black
}
proc _kodas_shadow {} {
update idletasks
set x [winfo rootx .]
set y [winfo rooty .]
set w [winfo width .]
set h [winfo height .]
for {set i 7} {$i >= 1} {incr i -1} {
set s [expr {$i * 2}]
set t .kodas_sh$i
catch {
toplevel $t -background magenta
wm overrideredirect $t 1
canvas $t.c -width [expr {$w + 2*$s}] -height [expr {$h + 2*$s}] -highlightthickness 0 -background magenta
pack $t.c
_kodas_rr $t.c 0 0 [expr {$w + 2*$s - 1}] [expr {$h + 2*$s - 1}] [expr {12 + $s}]
wm geometry $t +[expr {$x - $s}]+[expr {$y - $s + 6}]
wm attributes $t -transparentcolor magenta -alpha 0.06 -topmost 1
}
}
update idletasks
for {set i 1} {$i <= 7} {incr i} {catch {lower .kodas_sh$i .}}
wm attributes . -topmost 0
wm attributes . -topmost 1
raise .
}
after 30 _kodas_shadow
'''


class DotsSplash(Splash):
    def generate_script(self):
        script = (super().generate_script() + "\n" + SPLASH_DOTS_TCL.strip() + "\n"
                  + SPLASH_SHADOW_TCL.strip() + "\n")
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
