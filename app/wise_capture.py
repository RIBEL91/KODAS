"""WISE(LH-WISE) 화면 캡처: 폴더링 때 WISE가 켜져 있으면 보고서 4권 작성방법대로 화면을 열어 조회하고 캡처한다.

- 화면 열기: 왼쪽 [메뉴 검색] 칸에 화면 이름을 넣고 ↓·Enter(첫 번째 추천 = 건설임대).
- 조회 조건: 화면마다 정해 둔 대로(기준일 '명도일', 최근 3년 등) 넣고 [검색] → '처리중입니다' 창이 닫힐 때까지 기다림.
- 마지막 순번이 보이게 표 오른쪽 스크롤 막대를 끝까지 내린다(줄은 누르지 않는다 — 고치는 화면이 있음).
- 개인정보: 계약자(명)·주민(등록)번호 칸을 표 선 위치로 찾아 하얗게 지운 뒤 저장한다. 칸을 못 찾으면 저장하지 않는다.
조회만 하고 저장·수정 버튼은 누르지 않는다.

WISE(XPlatform)는 화면 안의 글자를 Windows가 알려 주지 않으므로 Windows 한국어 OCR로 글자 위치를 찾는다.
위치는 WISE 창을 최대화(1920×1032)한 화면 기준이다(2026-11-20 광주양림2 WISE에서 잼).
"""
from __future__ import annotations

import asyncio
import ctypes
import datetime as dt
import difflib
import time
from ctypes import wintypes
from dataclasses import dataclass, field

WISE_TITLE, WISE_CLASS = "LH-WISE", "CyWindowClass"
MENU_SEARCH = (125, 165)                 # [메뉴 검색] 입력칸
HEAD_BOX = (272, 158, 900, 186)          # 연 화면 제목(초록 네모 옆)
QUERY_BOX = (255, 200, 1800, 300)        # 조회 조건 칸
SEARCH_BTN = (1845, 225)                 # [검색]
BUSY_BOX = (600, 440, 1300, 600)         # '처리중입니다' 창
SCROLL_X = 1887                          # 표 세로 스크롤 막대
SHOT_BOX = (244, 158, 1906, 1000)        # 캡처할 화면 영역(메뉴·아래 상태줄 빼고)
HEAD_LINE = (154, 181, 214)              # 표 머리글 세로선 색
DATA_LINE = (206, 212, 221)              # 표 본문 세로선 색

user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class WiseError(Exception):
    pass


STOPPED_MSG = "멈춤"
STOP = None              # 폴더링 [멈추기] 신호(threading.Event) — evidence_fetch가 넣어 둔다


def _sleep(sec: float) -> None:
    """[멈추기]를 누르면 기다리는 도중에도 곧바로 WiseError(멈춤)로 빠져나온다."""
    end = time.time() + sec
    while True:
        if STOP is not None and STOP.is_set():
            raise WiseError(STOPPED_MSG)
        left = end - time.time()
        if left <= 0:
            return
        time.sleep(min(left, 0.1))


@dataclass
class Screen:
    """WISE 화면 하나를 조회·캡처하는 방법."""
    menu: str                                    # 메뉴 검색어(화면 이름)
    date_label: str                              # 기간 칸 앞 글자(OCR로 찾음)
    date_dx: tuple[int, int]                     # 그 글자 가운데에서 시작·끝 날짜칸까지 x 거리
    period: str = "3y"                           # '3y' = 평가년도 전 3년, 'year' = 평가년도 1~12월
    combo: tuple[int, str] | None = None         # (글자에서 콤보까지 x 거리, 고를 값) — 기준일 '명도일'
    complex_dx: int = 0                          # 단지 글자에서 단지코드 칸까지(비어 있으면 코드를 넣는다)
    private: list[str] = field(default_factory=list)   # 지울 칸 머리글


SCREENS = {
    "해약처리현황": Screen("해약처리현황", "기준일", (178, 277), "3y", (85, "명도일"), 90, ["계약자", "주민번호"]),
    "해약처리현황(평가년도)": Screen("해약처리현황", "기준일", (178, 277), "year", (85, "명도일"), 90,
                              ["계약자", "주민번호"]),
    "계약자입주일관리": Screen("계약자입주일관리", "최초계약일자", (90, 190), "3y", None, 0, ["계약자명", "주민등록번호"]),
}


# ---------------- 창·입력 ----------------
def find_window() -> int:
    found = []

    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value == WISE_TITLE:
            cbuf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cbuf, 256)
            if cbuf.value == WISE_CLASS:
                found.append(hwnd)
                return False
        return True
    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else 0


def _rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def _activate(hwnd: int) -> None:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)            # SW_RESTORE
    if not user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, 3)            # SW_MAXIMIZE — 위치를 최대화 화면 기준으로 잰다
    user32.keybd_event(0x12, 0, 0, 0)         # Alt를 눌렀다 떼면 SetForegroundWindow가 막히지 않는다
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    _sleep(0.8)


ULONG_PTR = ctypes.c_size_t


class _KI(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _MI(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("mi", _MI), ("ki", _KI)]


class _IN(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(*ins):
    arr = (_IN * len(ins))(*ins)
    user32.SendInput(len(ins), arr, ctypes.sizeof(_IN))


def _kbd(vk=0, scan=0, flags=0):
    i = _IN(type=1)
    i.u.ki = _KI(vk, scan, flags, 0, 0)
    return i


def _mouse(flags):
    i = _IN(type=0)
    i.u.mi = _MI(0, 0, 0, flags, 0, 0)
    return i


VK = {"enter": 0x0D, "tab": 0x09, "ctrl": 0x11, "a": 0x41, "down": 0x28}


def _key(combo: str) -> None:
    names = combo.split("+")
    for n in names:
        _send(_kbd(vk=VK[n]))
    for n in reversed(names):
        _send(_kbd(vk=VK[n], flags=2))
    _sleep(0.08)


def _type(s: str) -> None:
    for ch in s:
        _send(_kbd(scan=ord(ch), flags=4), _kbd(scan=ord(ch), flags=4 | 2))
        _sleep(0.01)


def _click(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    _sleep(0.1)
    _send(_mouse(0x2), _mouse(0x4))
    _sleep(0.15)


# ---------------- OCR ----------------
async def _recognize(img):
    from PIL import Image
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()
    writer = DataWriter()
    writer.write_bytes(Image.merge("RGBA", (b, g, r, a)).tobytes())
    bmp = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8,
                                                rgba.width, rgba.height, BitmapAlphaMode.PREMULTIPLIED)
    engine = OcrEngine.try_create_from_language(Language("ko"))
    if engine is None:
        raise WiseError("한국어 OCR을 쓸 수 없습니다(Windows 설정 → 언어에서 한국어 설치).")
    return await engine.recognize_async(bmp)


def read_words(img, scale: float = 2.0) -> list[tuple[str, int, int]]:
    """그림 속 낱말과 가운데 위치(그림 좌표) 목록."""
    from PIL import Image
    if scale != 1:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    res = asyncio.run(_recognize(img))
    out = []
    for ln in res.lines:
        for w in ln.words:
            r = w.bounding_rect
            out.append((w.text, int((r.x + r.width / 2) / scale), int((r.y + r.height / 2) / scale)))
    return out


def _norm(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum())


def _score(word: str, name: str) -> float:
    w, n = _norm(word), _norm(name)
    if not w or not n:
        return 0.0
    if n in w:
        return 1.0
    return max(difflib.SequenceMatcher(None, w[i:i + len(n)], n).ratio() for i in range(max(1, len(w) - len(n) + 1)))


def _merged(words):
    """OCR이 '주민 변 호'처럼 쪼갠 낱말도 맞춰 보게, 같은 줄의 이웃 낱말 2~3개를 붙인 후보도 만든다."""
    out = list(words)
    for i in range(len(words)):
        text, x0, y0 = words[i]
        xs = [x0]
        for j in range(i + 1, min(i + 3, len(words))):
            t, x, y = words[j]
            if abs(y - y0) > 4 or x <= xs[-1] or x - xs[-1] > 70:
                break
            text += t
            xs.append(x)
            out.append((text, (xs[0] + xs[-1]) // 2, y0))
    return out


def find_word(words, name: str, least: float = 0.75):
    best, pos = 0.0, None
    for text, x, y in _merged(words):
        s = _score(text, name)
        if s > best:
            best, pos = s, (x, y)
    return pos if best >= least else None


def _grab(box):
    from PIL import ImageGrab
    return ImageGrab.grab(bbox=box, all_screens=True)


# ---------------- 개인정보 칸 지우기 ----------------
def _near(p, c, tol=14) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(p[:3], c))


def mask_columns(img, headers: list[str]) -> int:
    """표 머리글이 headers인 칸의 본문을 하얗게 지운다(img를 고침). 지운 칸 수."""
    from PIL import ImageDraw
    rgb = img.convert("RGB")
    words = read_words(rgb, 2)
    seq = find_word(words, "순번", 0.9)                # 표 머리글 줄 아래만(조회 칸의 '계약자' 글자는 빼고)
    if seq is None:
        return 0
    words = [w for w in words if w[2] >= seq[1] - 45]
    draw = ImageDraw.Draw(img)
    done = 0
    for h in headers:
        pos = find_word(words, h, 0.7)
        if pos is None:
            continue
        x, y = pos
        left = next((i for i in range(x, max(0, x - 260), -1) if _near(rgb.getpixel((i, y)), HEAD_LINE)), None)
        right = next((i for i in range(x, min(rgb.width, x + 260)) if _near(rgb.getpixel((i, y)), HEAD_LINE)), None)
        if left is None or right is None:
            continue
        span = grid_span(rgb, left, y)
        if span is None:
            continue
        draw.rectangle([left + 1, span[0], right - 1, span[2] - 1], fill="white")     # 합계 줄까지
        done += 1
    return done


def grid_span(rgb, x: int, y0: int) -> tuple[int, int, int] | None:
    """표 세로선(x)을 따라: (본문 시작 y, 본문 끝 y(합계 줄 위), 표 끝 y(흰 바탕 시작)).
    고른 줄의 테두리(주황)·합계 줄 선 색이 섞여도 흰 바탕이 나올 때까지를 표로 본다."""
    yy = y0
    while yy < rgb.height and _near(rgb.getpixel((x, yy)), HEAD_LINE, 10):
        yy += 1
    top = yy
    data_end = None
    while yy < rgb.height and min(rgb.getpixel((x, yy))[:3]) < 250:
        if data_end is None and _near(rgb.getpixel((x, yy)), (185, 192, 202), 4):
            data_end = yy
        yy += 1
    if yy >= rgb.height or yy - top < 20:
        return None
    return top, data_end or yy, yy


_RRN = __import__("re").compile(r"\d{6}\s*-\s*[1-4]")


def has_private(img) -> bool:
    """그림에 주민등록번호 모양(######-#)이 남아 있으면 True(저장하지 않는다)."""
    words = read_words(img.convert("RGB"), 1.5)
    return any(_RRN.search(t) for t, _x, _y in _merged(words))


# ---------------- 조회·캡처 ----------------
def _period(kind: str, year: int) -> tuple[str, str]:
    if kind == "year":
        return f"{year}0101", f"{year}1231"
    return f"{year - 2}0101", f"{year}1231"              # 최근 3년 = 평가년도 포함(2026 평가 → 2024.1.1~2026.12.31, 사용자 2026-11-21)


def _wait_busy(box, limit: float = 120) -> None:
    end = time.time() + limit
    _sleep(2)
    while time.time() < end:
        if not any(_score(t, "처리중") >= 0.8 for t, _x, _y in read_words(_grab(box(BUSY_BOX)), 1.5)):
            _sleep(1)
            return
        _sleep(3)
    raise WiseError("WISE 조회가 오래 걸려 끝나지 않음")


def _total(words) -> int:
    """'해약내역 [173건]'의 건수."""
    import re
    for t, _x, _y in _merged(words):
        m = re.search(r"\[(\d+)\s*건", t)
        if m:
            return int(m.group(1))
    return 0


def _last_no(img, head) -> int:
    """순번 칸(머리글 head 아래)만 크게 읽어 보이는 가장 큰 번호."""
    hx, hy = head
    x0 = max(0, hx - 40)
    col = img.crop((x0, hy + 15, hx + 360, img.height))       # 순번 옆 칸까지 넣어야 OCR이 줄로 읽는다
    nums = [int(t) for t, x, _y in read_words(col, 2.5) if t.isdigit() and abs(x + x0 - hx) <= 25]
    return max(nums, default=0)


def _open_menu(box, at, menu: str) -> bool:
    """[메뉴 검색]에 화면 이름을 넣고 ↓·Enter — 제목이 바뀔 때까지(3번까지 다시)."""
    for _try in range(3):
        at(*MENU_SEARCH)
        _sleep(0.4)
        _key("ctrl+a")
        _type(menu)
        _sleep(1.8)                      # 추천 목록이 뜰 때까지
        _key("down")
        _sleep(0.4)
        _key("enter")
        end = time.time() + 8
        while time.time() < end:
            _sleep(1)
            head = " ".join(t for t, _x, _y in read_words(_grab(box(HEAD_BOX))))
            if _score(head, menu) >= 0.75:
                return True
    return False


def capture(key: str, out_path: str, year: int, complex_code: str = "", log=None) -> str:
    """SCREENS[key] 화면을 열어 조회하고 마지막 순번이 보이게 내린 뒤 개인정보를 지워 out_path(PNG)로 저장.
    성공하면 '', 못 하면 이유."""
    sc = SCREENS[key]
    say = log or (lambda _m: None)
    hwnd = find_window()
    if not hwnd:
        return "WISE가 켜져 있지 않아 캡처하지 못함(WISE에 로그인해 둔 뒤 다시 폴더링)"
    prev = user32.GetForegroundWindow()
    was_min = bool(user32.IsIconic(hwnd))
    try:
        _activate(hwnd)
        ox, oy = _rect(hwnd)[:2]
        box = lambda b: (ox + b[0], oy + b[1], ox + b[2], oy + b[3])
        at = lambda x, y: _click(ox + x, oy + y)
        # 1) 메뉴 검색으로 화면 열기
        if not _open_menu(box, at, sc.menu):
            return f"WISE 메뉴 검색으로 '{sc.menu}' 화면을 열지 못함"
        _sleep(1)
        say(f"     WISE '{sc.menu}' 화면을 열었습니다.")
        # 2) 조건
        q = read_words(_grab(box(QUERY_BOX)))
        lab = find_word(q, sc.date_label)
        if lab is None:
            return f"WISE '{sc.menu}' 화면에서 '{sc.date_label}' 칸을 찾지 못함"
        lx, ly = QUERY_BOX[0] + lab[0], QUERY_BOX[1] + lab[1]
        if sc.combo:
            dx, want = sc.combo
            at(lx + dx, ly)
            _sleep(0.8)
            opts = read_words(_grab(box((lx + dx - 60, ly + 8, lx + dx + 80, ly + 120))))
            p = find_word(opts, want, 0.6) or find_word(opts, want[1:], 0.9)     # OCR이 '명'을 '경'으로 읽기도 함
            if p is None:
                return f"WISE '{sc.menu}' 화면에서 '{want}'을(를) 고르지 못함"
            at(lx + dx - 60 + p[0], ly + 8 + p[1])
            _sleep(0.6)
        start, end = _period(sc.period, year)
        for dx, val in zip(sc.date_dx, (start, end)):
            at(lx + dx, ly)
            _key("ctrl+a")
            _type(val)
            _key("tab")
            _sleep(0.3)
        if sc.complex_dx:
            c = find_word(q, "단지", 0.9)
            if c is not None:
                cx, cy = QUERY_BOX[0] + c[0], QUERY_BOX[1] + c[1]
                name = read_words(_grab(box((cx + 130, cy - 12, cx + 330, cy + 12))), 2)
                if not name:                          # 단지가 비어 있으면 코드를 넣는다
                    if not complex_code:
                        return f"WISE '{sc.menu}' 화면의 단지가 비어 있고 단지코드를 몰라 조회하지 못함"
                    at(cx + sc.complex_dx, cy)
                    _key("ctrl+a")
                    _type(complex_code)
                    _key("enter")
                    _sleep(1.5)
        say(f"     WISE 조회({start[:4]}.{start[4:6]}~{end[:4]}.{end[4:6]})…")
        at(*SEARCH_BTN)
        _wait_busy(box)
        # 3) 마지막 순번까지 내리기
        shot = _grab(box(SHOT_BOX)).convert("RGB")
        hp = find_word(read_words(shot, 2), "순번", 0.9)
        if hp is None:
            return f"WISE '{sc.menu}' 조회 결과 표를 찾지 못함"
        line_x = next((i for i in range(hp[0], min(shot.width, hp[0] + 120)) if _near(shot.getpixel((i, hp[1])), HEAD_LINE)),
                      None)
        span = grid_span(shot, line_x, hp[1]) if line_x is not None else None
        if span is None:
            return f"WISE '{sc.menu}' 조회 결과가 없음"
        total = _total(read_words(shot, 2))
        from PIL import ImageChops
        grid = (0, span[0], shot.width, span[1])
        prev_img, at_end = shot, False
        for _round in range(12):                    # 스크롤 막대 아래쪽을 눌러 내린다 — 더 눌러도 표가 그대로면 끝
            for _ in range(15):
                at(SCROLL_X, SHOT_BOX[1] + span[1] - 20)
            _sleep(0.8)
            img = _grab(box(SHOT_BOX)).convert("RGB")
            if ImageChops.difference(img.crop(grid), prev_img.crop(grid)).getbbox() is None:
                at_end = True
                break
            prev_img = img
        if not at_end:
            return f"WISE '{sc.menu}' 표를 마지막 순번까지 내리지 못함"
        last = _last_no(img, hp)
        # 4) 캡처 → 개인정보 지우기 → 확인 → 저장
        if sc.private and mask_columns(img, sc.private) < len(sc.private):
            return f"WISE '{sc.menu}' 화면의 개인정보 칸({', '.join(sc.private)})을 찾지 못해 캡처를 저장하지 않음"
        if has_private(img):
            return f"WISE '{sc.menu}' 캡처에 주민등록번호가 남아 있어 저장하지 않음"
        img.save(out_path)
        say(f"     WISE 캡처 완료(마지막 순번까지" + (f", {total}건" if total else "") + ", 계약자·주민번호 지움)")
        return ""
    except WiseError as ex:
        return str(ex)
    except Exception as ex:
        return f"WISE 화면을 캡처하지 못함 ({type(ex).__name__}: {ex})"[:200]
    finally:
        if was_min:
            user32.ShowWindow(hwnd, 6)        # SW_MINIMIZE — 원래대로
        if prev:
            try:
                user32.SetForegroundWindow(prev)
            except Exception:
                pass


# ---------------- 분양권퇴거유예세대관리: 동·호·퇴거여부 확대 ----------------
BUNYANG_MENU = "분양권퇴거유예세대관리"
HSCROLL_Y = 795                          # SHOT_BOX 안에서 표 가로 스크롤 막대 높이
# 지울 칸(관계 칸은 증빙양식 '세대주 관계'라 남긴다)
BUNYANG_PRIVATE = ("계약자성명", "연락처", "우편번호", "주소", "성명", "주민등록번호", "물건소재지주소", "물건소재")


def _columns(rgb, y: int) -> list[int]:
    """표 머리글 줄 y에서 세로선 x 목록."""
    out = []
    for x in range(rgb.width):
        if _near(rgb.getpixel((x, y)), HEAD_LINE, 12) and (not out or x - out[-1] > 3):
            out.append(x)
    return out


def _header_cells(rgb, words, y: int, tol: int = 16) -> list[tuple[int, int, str]]:
    """머리글 줄 y의 칸들 [(왼쪽, 오른쪽, 글자)]. 글자는 그 칸 안 낱말을 이어 붙임."""
    lines = _columns(rgb, y)
    cells = []
    for a, b in zip(lines, lines[1:]):
        if b - a < 12:
            continue
        txt = "".join(t for t, x, yy in sorted(words, key=lambda w: (w[2], w[1])) if a < x < b and abs(yy - y) <= tol)
        cells.append((a, b, _norm(txt)))
    return cells


def _cell(cells, name: str):
    n = _norm(name)
    for c in cells:
        if c[2] == n:
            return c
    best = max(cells, key=lambda c: difflib.SequenceMatcher(None, c[2], n).ratio(), default=None)
    if best is not None and difflib.SequenceMatcher(None, best[2], n).ratio() >= 0.8:
        return best
    return None


def _head_top(rgb, x: int, y: int) -> int:
    """머리글 칸(x, 글자 줄 y)의 위 끝 — 배경색이 바뀌는 곳."""
    bg = rgb.getpixel((x, y))
    yy = y
    while yy > 0 and _near(rgb.getpixel((x, yy - 1)), bg, 10):
        yy -= 1
    return yy


def _zoom(img, box, k: float = 1.7, border: int = 4):
    from PIL import Image, ImageOps
    piece = img.crop(box)
    piece = piece.resize((int(piece.width * k), int(piece.height * k)), Image.LANCZOS)
    return ImageOps.expand(piece, border=border, fill="black")


def capture_bunyang(out_path: str, complex_code: str = "", log=None) -> str:
    """WISE 분양권퇴거유예세대관리(건설)를 조회해 표 왼쪽 화면(개인정보 칸 흰칸)에 동·호와
    (오른쪽으로 넘겨야 보이는) 퇴거여부 칸을 크게 겹쳐 out_path로 저장. 성공하면 '', 못 하면 이유."""
    from PIL import Image, ImageChops, ImageDraw
    say = log or (lambda _m: None)
    hwnd = find_window()
    if not hwnd:
        return "WISE가 켜져 있지 않아 캡처하지 못함(WISE에 로그인해 둔 뒤 다시 폴더링)"
    prev = user32.GetForegroundWindow()
    was_min = bool(user32.IsIconic(hwnd))
    try:
        _activate(hwnd)
        ox, oy = _rect(hwnd)[:2]
        box = lambda b: (ox + b[0], oy + b[1], ox + b[2], oy + b[3])
        at = lambda x, y: _click(ox + x, oy + y)
        if not _open_menu(box, at, BUNYANG_MENU):
            return f"WISE 메뉴 검색으로 '{BUNYANG_MENU}' 화면을 열지 못함"
        _sleep(1)
        say(f"     WISE '{BUNYANG_MENU}' 화면을 열었습니다.")
        q = read_words(_grab(box(QUERY_BOX)))
        c = find_word(q, "단지", 0.9)
        if c is not None:
            cx, cy = QUERY_BOX[0] + c[0], QUERY_BOX[1] + c[1]
            if not read_words(_grab(box((cx + 130, cy - 12, cx + 280, cy + 12))), 2):
                if not complex_code:
                    return f"WISE '{BUNYANG_MENU}' 화면의 단지가 비어 있고 단지코드를 몰라 조회하지 못함"
                at(cx + 80, cy)
                _key("ctrl+a")
                _type(complex_code)
                _key("enter")
                _sleep(1.5)
        at(*SEARCH_BTN)                       # 기간은 화면 기본값(오늘 앞뒤) 그대로
        _wait_busy(box)
        hs = lambda x: at(SHOT_BOX[0] + x, SHOT_BOX[1] + HSCROLL_Y)
        for _ in range(8):
            hs(12)                            # 왼쪽 끝으로
        _sleep(0.8)
        a = _grab(box(SHOT_BOX)).convert("RGB")
        wa = read_words(a, 2)
        hp = find_word(wa, "계약차수", 0.8)
        if hp is None:
            return f"WISE '{BUNYANG_MENU}' 조회 결과 표를 찾지 못함"
        cells = _header_cells(a, wa, hp[1])
        span = grid_span(a, cells[0][0], hp[1]) if cells else None
        if span is None:
            return f"WISE '{BUNYANG_MENU}' 조회 결과가 없음(분양권 보유 세대 없음)"
        top, end = span[0], span[2]
        ki = next((i for i, c in enumerate(cells) if c[0] < hp[0] < c[1]), None)
        ri = next((i for i, c in enumerate(cells) if ki is not None and i > ki and _score(c[2], "관계") >= 0.9), None)
        if ki is None or ri is None or ri - ki != 8:
            return f"WISE '{BUNYANG_MENU}' 표 칸 차례(계약차수·동·호…관계)가 달라 캡처를 저장하지 않음"
        dong, ho = cells[ki + 1], cells[ki + 2]
        private = set(range(ki + 4, ri)) | set(range(ri + 1, len(cells)))      # 계약자성명~주소, 성명~끝
        total = _total(wa)
        prev_img, b = a, a
        for _ in range(10):                   # 오른쪽으로 넘겨 퇴거여부 칸 — 더 안 바뀌면 끝
            for _k in range(4):
                hs(1500)
            _sleep(0.6)
            b = _grab(box(SHOT_BOX)).convert("RGB")
            if ImageChops.difference(b.crop((0, top, b.width, end)), prev_img.crop((0, top, b.width, end))).getbbox() is None:
                break
            prev_img = b
        wb = read_words(b, 2)
        hy = find_word(wb, "해약신청상태", 0.8)               # 퇴거여부는 그 바로 오른쪽 칸(OCR이 '퇴거며부'로 읽음)
        cells_b = _header_cells(b, wb, hy[1], 30) if hy else []
        si = next((i for i, c in enumerate(cells_b) if c[0] < hy[0] < c[1]), None) if hy else None
        out = cells_b[si + 1] if si is not None and si + 1 < len(cells_b) else None
        if out is not None and _score(out[2], "퇴거여부") < 0.7:
            out = None
        for _ in range(8):
            hs(12)                            # 원래대로 왼쪽
        if out is None:
            return f"WISE '{BUNYANG_MENU}' 표에서 퇴거여부 칸을 찾지 못함"
        # 개인정보 칸 지우기(왼쪽 화면) — 오른쪽 끝에 잘린 칸도 지운다
        img = a.copy()
        g = ImageDraw.Draw(img)
        hidden = 0
        for k in sorted(private):
            x0, x1, _t = cells[k]
            g.rectangle([x0 + 1, top, x1 - 1, end - 1], fill="white")
            hidden += 1
        last = cells[-1][1]
        if last < img.width - 30:
            g.rectangle([last + 1, top, img.width - 1, end - 1], fill="white")
        if hidden < 4:
            return f"WISE '{BUNYANG_MENU}' 화면의 개인정보 칸을 찾지 못해 캡처를 저장하지 않음"
        # 확대 칸: 동·호(두 칸 함께), 퇴거여부
        dh_top = _head_top(a, dong[0] + 3, hp[1])
        z1 = _zoom(a, (dong[0], dh_top, ho[1] + 1, end))
        ot = _head_top(b, out[0] + 3, hy[1])
        z2 = _zoom(b, (out[0], ot, out[1] + 1, end))
        y0 = dh_top + 4
        x1 = max(0, (dong[0] + ho[1]) // 2 - z1.width // 2)
        addr = cells[ri - 1]
        x2 = ((addr[0] + addr[1]) // 2 - z2.width // 2) if addr else x1 + z1.width + 120
        x2 = min(max(x1 + z1.width + 20, x2), img.width - z2.width)
        sheet = Image.new("RGB", (img.width, max(img.height, y0 + max(z1.height, z2.height) + 10)), "white")
        sheet.paste(img, (0, 0))
        sheet.paste(z1, (x1, y0))
        sheet.paste(z2, (x2, y0))
        if has_private(sheet):
            return f"WISE '{BUNYANG_MENU}' 캡처에 주민등록번호가 남아 있어 저장하지 않음"
        sheet.save(out_path)
        say("     WISE 캡처 완료(" + (f"{total}건, " if total else "") + "동·호·퇴거여부 확대, 개인정보 칸 지움)")
        return ""
    except WiseError as ex:
        return str(ex)
    except Exception as ex:
        return f"WISE 화면을 캡처하지 못함 ({type(ex).__name__}: {ex})"[:200]
    finally:
        if was_min:
            user32.ShowWindow(hwnd, 6)
        if prev:
            try:
                user32.SetForegroundWindow(prev)
            except Exception:
                pass


# ---------------- 자격검색요청관리(건설): 주택소유정기검색 분기별 ----------------
JG_MENU = "자격검색요청관리"
JG_KIND = "주택소유정기검색"
# SHOT_BOX 안 좌표(최대화 화면, 2026-11-21 광주양림2에서 잼)
JG_COMBO = (255, 65)                     # 요청대상검색구분 콤보
JG_COMBO_TEXT = (140, 55, 370, 77)
JG_CODE = (555, 66)                      # 단지/지자체 코드 칸
JG_NAME = (603, 55, 770, 78)             # 단지 이름 칸
JG_DATES = ((558, 96), (655, 96))        # 요청일 시작·끝
JG_UPPER_END = 380                       # 위쪽 '요청대상' 표 끝(아래 '요청상세내역'에 입주자 이름·주민번호가 있어 자름)
ALERT_BOX = (400, 260, 1100, 560)        # SHOT_BOX 안 '알림'·'에러' 창 자리


def _dismiss_alert(ox: int, oy: int) -> str:
    """WISE 알림·에러 창이 떠 있으면 [확인]을 누르고 그 글을 돌려준다(없으면 '')."""
    sx, sy = SHOT_BOX[0], SHOT_BOX[1]
    b = ALERT_BOX
    words = read_words(_grab((ox + sx + b[0], oy + sy + b[1], ox + sx + b[2], oy + sy + b[3])).convert("RGB"), 2)
    text = " ".join(t for t, _x, _y in words)
    if not any(k in text for k in ("오류", "존재하지", "문의", "없습니다", "확인하")):
        return ""
    ok = next(((x, y) for t, x, y in words if _norm(t) == "확인"), None)
    if ok is None:
        return ""
    _click(ox + sx + b[0] + ok[0], oy + sy + b[1] + ok[1])
    _sleep(1)
    return text


QUARTERS = {1: ("0101", "0331"), 2: ("0401", "0630"), 3: ("0701", "0930"), 4: ("1001", "1231")}


def capture_jagyeok(quarter: int, out_path: str, year: int, complex_code: str = "", log=None) -> str:
    """자격검색요청관리(건설)에서 요청대상검색구분 '주택소유정기검색', 요청일 = 평가년도 quarter분기로 조회해
    위쪽 '요청대상' 표만 찍고 요청일·희망완료일 칸을 크게 겹쳐 저장. 성공하면 '', 못 하면 이유."""
    from PIL import Image
    say = log or (lambda _m: None)
    hwnd = find_window()
    if not hwnd:
        return "WISE가 켜져 있지 않아 캡처하지 못함(WISE에 로그인해 둔 뒤 다시 폴더링)"
    prev = user32.GetForegroundWindow()
    was_min = bool(user32.IsIconic(hwnd))
    try:
        _activate(hwnd)
        ox, oy = _rect(hwnd)[:2]
        box = lambda b: (ox + b[0], oy + b[1], ox + b[2], oy + b[3])
        sx, sy = SHOT_BOX[0], SHOT_BOX[1]
        sbox = lambda b: box((sx + b[0], sy + b[1], sx + b[2], sy + b[3]))
        at = lambda x, y: _click(ox + sx + x, oy + sy + y)
        head = " ".join(t for t, _x, _y in read_words(_grab(box(HEAD_BOX))))
        if _score(head, JG_MENU) < 0.75:
            if not _open_menu(box, lambda x, y: _click(ox + x, oy + y), JG_MENU):
                return f"WISE 메뉴 검색으로 '{JG_MENU}' 화면을 열지 못함"
            _sleep(1.5)
            say(f"     WISE '{JG_MENU}' 화면을 열었습니다.")
        combo = lambda: " ".join(t for t, _x, _y in read_words(_grab(sbox(JG_COMBO_TEXT)).convert("RGB"), 3))
        is_kind = lambda t: "소유정기" in _norm(t) or _score(t, JG_KIND) >= 0.75
        if not is_kind(combo()):
            at(*JG_COMBO)
            _sleep(1)
            for _ in range(40):                      # 목록을 연 채로 ↓ — 칸 글자가 주택소유정기검색이 되면 Enter
                _key("down")
                _sleep(0.3)
                if is_kind(combo()):
                    break
            _key("enter")
            _sleep(1)
            if not is_kind(combo()):
                return f"WISE '{JG_MENU}'에서 요청대상검색구분 '{JG_KIND}'을(를) 고르지 못함"
        name = read_words(_grab(sbox(JG_NAME)).convert("RGB"), 2)
        if not name:                                 # 구분을 바꾸면 단지가 지워진다 — 코드를 넣고 Tab(단지 찾기)
            if not complex_code:
                return f"WISE '{JG_MENU}' 화면의 단지가 비어 있고 단지코드를 몰라 조회하지 못함"
            at(*JG_CODE)
            _key("ctrl+a")
            _sleep(0.2)
            _type(complex_code)
            _sleep(0.4)
            _key("tab")
            _sleep(2.5)
            if not read_words(_grab(sbox(JG_NAME)).convert("RGB"), 2):
                return f"WISE '{JG_MENU}' 화면에서 단지 {complex_code}를 찾지 못함"
        _dismiss_alert(ox, oy)
        a, b = QUARTERS[quarter]
        months = range(int(a[:2]), int(b[:2]) + 1)
        import re as _re
        shot = words = None
        for _try in range(3):                       # WISE가 '시스템 오류' 창을 띄우면 닫고 다시 조회
            for (x, y), val in zip(JG_DATES, (f"{year}{a}", f"{year}{b}")):
                at(x, y)
                _key("ctrl+a")
                _type(val)
                _key("tab")
                _sleep(0.3)
                _dismiss_alert(ox, oy)
            say(f"     WISE 조회({year}.{a[:2]}~{year}.{b[:2]}, {JG_KIND})…")
            _click(ox + SEARCH_BTN[0], oy + SEARCH_BTN[1])
            _wait_busy(box)
            _sleep(1.5)
            if _dismiss_alert(ox, oy):
                _sleep(1)
                continue
            shot = _grab(box(SHOT_BOX)).convert("RGB").crop((0, 0, SHOT_BOX[2] - SHOT_BOX[0], JG_UPPER_END))
            words = read_words(shot, 2)
            got = [m for t, _x, y in words if y > 200 and _x < 165          # 요청일 칸(희망완료일은 다음 달)
                   for m in [_re.match(rf"{year}-(\d\d)-\d\d", t.replace(" ", ""))] if m]
            if not got:
                break                               # 결과 없음 — 아래에서 이유로
            if all(int(m.group(1)) in months for m in got):
                break
            shot = None                             # 다른 분기 결과가 남아 있음 — 다시
        if shot is None:
            return f"WISE '{JG_MENU}' {quarter}분기 조회가 되지 않음(오류 창 또는 이전 결과가 남음)"
        hp = next(((x, y) for t, x, y in _merged(words) if y > 150 and _score(t, "요청일") >= 0.9 and len(_norm(t)) <= 4), None)
        if hp is None:
            return f"WISE '{JG_MENU}' 조회 결과 표를 찾지 못함"
        cells = _header_cells(shot, words, hp[1], 20)
        ri = next((i for i, c in enumerate(cells) if c[0] < hp[0] < c[1]), None)
        if ri is None or ri + 1 >= len(cells):
            return f"WISE '{JG_MENU}' 표에서 요청일·희망완료일 칸을 찾지 못함"
        req, hope = cells[ri], cells[ri + 1]
        span = grid_span(shot, req[0], hp[1])
        if span is None:
            return f"WISE '{JG_MENU}' {quarter}분기({a[:2]}~{b[:2]}월) 조회 결과가 없음"
        top = _head_top(shot, req[0] + 3, hp[1])
        z = _zoom(shot, (req[0], top, hope[1] + 1, span[2]))
        img = shot.crop((0, 0, shot.width, span[2] + 8))
        x0, y0 = max(0, req[0] - 6), top + 4
        sheet = Image.new("RGB", (img.width, max(img.height, y0 + z.height + 10)), "white")
        sheet.paste(img, (0, 0))
        sheet.paste(z, (x0, y0))
        if has_private(sheet):
            return f"WISE '{JG_MENU}' 캡처에 주민등록번호가 남아 있어 저장하지 않음"
        sheet.save(out_path)
        say(f"     WISE 캡처 완료({quarter}분기, 요청일·희망완료일 확대)")
        return ""
    except WiseError as ex:
        return str(ex)
    except Exception as ex:
        return f"WISE 화면을 캡처하지 못함 ({type(ex).__name__}: {ex})"[:200]
    finally:
        if was_min:
            user32.ShowWindow(hwnd, 6)
        if prev:
            try:
                user32.SetForegroundWindow(prev)
            except Exception:
                pass


# ---------------- 임대조건기초자료관리(건설): 단지별임대조건인상률 / 단지별법정영세민기본단가 탭 ----------------
IM_MENU = "임대조건기초자료관리"
IM_TABS = {"인상률": ("임대조건인상", (806, 64)), "기본단가": ("법정영세민기본단가", (478, 64))}   # SHOT_BOX 안
IM_CODE, IM_NAME = (113, 120), (161, 110, 345, 131)
IM_SEARCH = (1600, 120)
ROW_H = 27                               # WISE 표 한 줄 높이


def _im_prepare(tab: str, complex_code: str, say):
    """화면·탭을 열고 단지를 넣어 조회. (ox, oy, 이유)."""
    hwnd = find_window()
    if not hwnd:
        return None, None, "WISE가 켜져 있지 않아 캡처하지 못함(WISE에 로그인해 둔 뒤 다시 폴더링)"
    _activate(hwnd)
    ox, oy = _rect(hwnd)[:2]
    box = lambda b: (ox + b[0], oy + b[1], ox + b[2], oy + b[3])
    sx, sy = SHOT_BOX[0], SHOT_BOX[1]
    at = lambda x, y: _click(ox + sx + x, oy + sy + y)
    head = " ".join(t for t, _x, _y in read_words(_grab(box(HEAD_BOX))))
    if _score(head, IM_MENU) < 0.75:
        if not _open_menu(box, lambda x, y: _click(ox + x, oy + y), IM_MENU):
            return ox, oy, f"WISE 메뉴 검색으로 '{IM_MENU}' 화면을 열지 못함"
        _sleep(1.5)
        say(f"     WISE '{IM_MENU}' 화면을 열었습니다.")
    _dismiss_alert(ox, oy)
    label, pos = IM_TABS[tab]
    tabs = read_words(_grab(box((sx, sy + 40, sx + 1450, sy + 85))).convert("RGB"), 2)
    p = find_word(tabs, label, 0.7)
    at(p[0] if p else pos[0], pos[1])
    _sleep(2.5)
    _dismiss_alert(ox, oy)
    sbox = lambda b: box((sx + b[0], sy + b[1], sx + b[2], sy + b[3]))
    name_of = lambda: read_words(_grab(sbox(IM_NAME)).convert("RGB"), 2)
    if complex_code:
        # 단지코드는 늘 새로 넣는다(앞서 다른 단지를 조회해 둔 채일 수 있음 — 기본단가는 단지가 여러 개)
        at(*IM_CODE)
        _key("ctrl+a")
        _sleep(0.2)
        _type(complex_code)
        _sleep(0.4)
        _key("tab")
        _sleep(2.5)
        msg = _dismiss_alert(ox, oy)
        if msg or not name_of():
            # Tab으로 단지 이름이 안 뜨면 [검색]을 눌러 조회한 뒤 다시 본다(사용자: "검색 누르고 해도 돼")
            at(*IM_SEARCH)
            _wait_busy(box)
            _sleep(1)
            msg = _dismiss_alert(ox, oy)
            if msg or not name_of():
                why = "단지가 조회되지 않음" + (" — 영구임대 단지만 있는 탭(기본단가 단지 칸에 영구임대 단지코드를 넣어 주세요)"
                                          if tab == "기본단가" else "")
                return ox, oy, f"WISE '{IM_MENU}' {label} 탭에서 {complex_code} {why}"
    elif not name_of():
        return ox, oy, f"WISE '{IM_MENU}' 화면의 단지가 비어 있고 단지코드를 몰라 조회하지 못함"
    at(*IM_SEARCH)
    _wait_busy(box)
    _sleep(1)
    msg = _dismiss_alert(ox, oy)
    if msg:
        return ox, oy, f"WISE '{IM_MENU}' {label} 탭 조회 안 됨({msg[:40]})"
    return ox, oy, ""


def capture_imdae(tab: str, out_path: str, complex_code: str = "", log=None) -> str:
    """임대조건기초자료관리 탭을 조회해 찍고, 인상률 탭은 인상률(%) 머리글+첫 줄을,
    기본단가 탭은 맨 아래(최근 적용년도) 4줄의 임대보증금·임대료·단가고시일자를 크게 겹친다."""
    from PIL import Image, ImageChops
    say = log or (lambda _m: None)
    prev = user32.GetForegroundWindow()
    try:
        ox, oy, why = _im_prepare(tab, complex_code, say)
        if why:
            return why
        box = lambda b: (ox + b[0], oy + b[1], ox + b[2], oy + b[3])
        shot = _grab(box(SHOT_BOX)).convert("RGB")
        words = read_words(shot, 2)
        hw = [w for w in words if w[2] > 180]
        # 머리글 OCR이 약하다('신분명'이 깨짐) — 인상률 탭은 '인상률(%)'(없으면 형별코드+2칸), 기본단가 탭은 '임대보증금'
        if tab == "인상률":
            anchor = next(((x, y) for t, x, y in hw if y > 225 and "%" in t and _score(t.split("(")[0], "인상률") >= 0.6), None)
            shift = 0
            if anchor is None:
                anchor, shift = find_word(hw, "형별코드", 0.75), 2
        else:
            anchor, shift = find_word(hw, "임대보증금", 0.75), 0
        if anchor is None:
            return f"WISE '{IM_MENU}' 조회 결과 표를 찾지 못함"
        cells = _header_cells(shot, words, anchor[1], 20)
        ai = next((i for i, c in enumerate(cells) if c[0] < anchor[0] < c[1]), None)
        if ai is None or ai + shift >= len(cells):
            return f"WISE '{IM_MENU}' 표 칸을 찾지 못함"
        ai += shift - 1                                             # cells[ai + 1] = 확대할 첫 칸
        span = grid_span(shot, cells[0][0], anchor[1])
        if span is None:
            return f"WISE '{IM_MENU}' 조회 결과가 없음"
        top = _head_top(shot, cells[ai + 1][0] + 3, anchor[1])
        if tab == "인상률":
            col = cells[ai + 1]                                     # 인상률(%)
            z = _zoom(shot, (col[0], top, col[1] + 1, span[0] + ROW_H), 2.2)
            x0, y0 = col[1] + 30, top + 10
            base = shot
        else:
            # 표를 맨 아래(최근 적용년도)까지 내린다 — 더 눌러도 그대로면 끝
            grid = (0, span[0], shot.width, span[1])
            last = shot
            for _round in range(12):
                for _ in range(15):
                    _click(ox + SCROLL_X, oy + SHOT_BOX[1] + span[1] - 20)
                _sleep(0.8)
                img = _grab(box(SHOT_BOX)).convert("RGB")
                if ImageChops.difference(img.crop(grid), last.crop(grid)).getbbox() is None:
                    break
                last = img
            base = last
            lo, hi = cells[ai + 1][0], cells[min(ai + 3, len(cells) - 1)][1]   # 임대보증금 ~ 단가고시일자
            end = grid_span(base, cells[0][0], anchor[1])
            bottom = end[2] if end else span[2]
            z = _zoom(base, (lo, max(span[0], bottom - ROW_H * 4), hi + 1, bottom), 1.6)
            x0, y0 = max(0, lo - 20), bottom - ROW_H * 4 + 10
        x0 = min(x0, base.width - z.width)
        sheet = Image.new("RGB", (base.width, max(base.height, y0 + z.height + 10)), "white")
        sheet.paste(base, (0, 0))
        sheet.paste(z, (x0, y0))
        if has_private(sheet):
            return f"WISE '{IM_MENU}' 캡처에 주민등록번호가 남아 있어 저장하지 않음"
        sheet.save(out_path)
        say(f"     WISE 캡처 완료({IM_TABS[tab][0]} 탭)")
        return ""
    except WiseError as ex:
        return str(ex)
    except Exception as ex:
        return f"WISE 화면을 캡처하지 못함 ({type(ex).__name__}: {ex})"[:200]
    finally:
        if prev:
            try:
                user32.SetForegroundWindow(prev)
            except Exception:
                pass
