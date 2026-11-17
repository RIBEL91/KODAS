"""원터치 자동작성: WISE 임대조건관리(건설) 화면에서 우리 단지 평형·세대수를 읽어 온다.

순서: 건설임대 > 공급 > 공급임대조건 산정 > 임대조건관리(건설) → 지역본부·단지 고르기 → [검색]
      → '임대조건' 표의 형별·세대수·임대시작일·임대보증금·임대료를 읽는다.

WISE(XPlatform)는 화면 안의 단추·칸을 Windows가 알려 주지 않는다. 그래서 '편리한 임대업무' 앱처럼
WISE 창(최대화 1920×1032) 왼쪽 위를 기준으로 한 위치를 누르고, 글자는 Windows OCR로 읽는다.
표의 숫자는 OCR이 9를 3으로 잘못 읽어 글자 모양 맞추기(wise_glyph)로 읽는다.
ESC를 누르면 멈춘다.
"""
import datetime as dt
import difflib
import re
import time
from dataclasses import dataclass

import wise_glyph
import wise_glyphs
import wise_input as win
import wise_ocr as ocr

WISE_TITLE, WISE_CLASS = "LH-WISE", "CyWindowClass"
SCREEN = "임대조건관리"

REGIONS = ("서울지역본부", "경기남부지역본부", "경기북부지역본부", "인천지역본부", "강원지역본부",
           "충북지역본부", "대전충남지역본부", "전북지역본부", "광주전남지역본부", "대구경북지역본부",
           "부산울산지역본부", "경남지역본부", "제주지역본부")
KEEP_REGION = "WISE에 나온 그대로"

# ---- WISE 창 왼쪽 위 기준 위치(픽셀, 최대화 1920×1032에서 잰 값) ----
MENU_BUILD = (320, 69)                  # 위 메뉴 [건설임대]
MENU_SUPPLY = (401, 105)                # 아래 메뉴 [공급]
TREE_BOX = (40, 180, 240, 720)          # 왼쪽 메뉴 나무
TITLE_BOX = (255, 158, 760, 186)        # 화면 제목(임대조건관리(건설))
TABS_BOX = (255, 128, 1610, 156)        # 열린 화면 탭들
REGION_BOX = (366, 213, 506, 234)       # 지역본부 값
REGION_ARROW = (517, 223)
REGION_LIST_BOX = (366, 232, 600, 640)  # 지역본부 펼친 목록
TYPE_BOX = (366, 244, 506, 265)         # 임대조건유형 값
COMPLEX_CODE_BOX = (660, 213, 746, 234)
COMPLEX_NAME = (830, 223)               # 단지 이름 칸
COMPLEX_NAME_BOX = (750, 213, 916, 234)
COMPLEX_FIND = (931, 223)               # 단지 돋보기
SEARCH = (1840, 224)                    # [검색]
COUNT_BOX = (255, 332, 420, 353)        # '임대조건 [12건]'
GRID_TOP, ROW_H, ROWS = 423, 27, 10     # 임대조건 표: 첫 줄 가운데, 줄 높이, 보이는 줄 수
GRID_WHEEL = (1000, 550)
COLS = {"no": (258, 294), "type": (300, 392), "units": (396, 464), "excl": (468, 534), "start": (968, 1072),
        "dep": (1388, 1496), "rent": (1500, 1588)}
POPUP_SKIP_BOX = (255, 200, 1900, 270)  # 단지 고르는 창을 찾을 때 빼는 곳(원래 검색 칸)


class Stop(Exception):
    """사용자가 멈췄거나 더 진행할 수 없음(메시지를 그대로 보여 준다)."""


@dataclass
class Row:
    no: int
    area: str        # 형별(계약면적 ㎡) 예: 100.1438
    units: int
    excl: str        # 전용면적(㎡) 예: 59.7600 — 단지기본정보의 평형 칸에는 이 값을 넣는다
    start: str       # 임대시작일 첫날 2026-08-01
    deposit: str     # 임대보증금 48,525,000
    rent: str        # 임대료 264,020


@dataclass
class Result:
    region: str
    complex_name: str
    rent_type: str
    start: str
    types: list      # [(전용면적 '59.76', 세대수 82, 보증금, 임대료, 계약면적 '100.14')] 전용면적 순
    total_rows: int


def similar(a: str, b: str) -> float:
    a, b = ocr.compact(a), ocr.compact(b)
    if not a or not b:
        return 0.0
    if a == b or b in a or a in b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def clean(text: str) -> str:
    """입력칸 테두리를 글자로 잘못 읽은 앞뒤 'I', '|' 같은 것을 뗀다."""
    words = text.split()
    while words and len(words[0]) == 1 and not re.match(r"[가-힣0-9]", words[0]):
        words.pop(0)
    while words and len(words[-1]) == 1 and not re.match(r"[가-힣0-9]", words[-1]):
        words.pop()
    return " ".join(words)


# ---------------- 읽은 표 → 평형 ----------------
def latest_rows(rows: list[Row], today: dt.date | None = None) -> list[Row]:
    """임대시작일(첫날)이 오늘 이전 중 가장 늦은 줄들(없으면 가장 늦은 줄들)."""
    today = today or dt.date.today()
    starts = sorted({r.start for r in rows if re.fullmatch(r"\d{4}-\d{2}-\d{2}", r.start)})
    if not starts:
        return list(rows)
    past = [s for s in starts if s <= today.isoformat()]
    pick = past[-1] if past else starts[-1]
    return [r for r in rows if r.start == pick]


def to_types(rows: list[Row]) -> list[tuple]:
    """같은 형별은 한 줄로(세대수는 큰 값). 평형은 전용면적(소수 둘째 자리) — 단지기본정보에 넣어 온 값이
    전용면적이다(예: 광주양림2 59.76㎡ = 계약면적 100.14㎡). 전용면적 작은 순."""
    seen: dict[str, Row] = {}
    for r in rows:
        k = r.area
        if k not in seen or r.units > seen[k].units:
            seen[k] = r
    out = [(f"{float(r.excl):.2f}", r.units, r.deposit, r.rent, f"{float(r.area):.2f}") for r in seen.values()]
    return sorted(out, key=lambda t: (float(t[0]), float(t[4])))


# ---------------- WISE 조작 ----------------
class Wise:
    def __init__(self, log):
        self.log = log
        self.hwnd = 0
        self.ox = self.oy = 0

    def _abs(self, p):
        return self.ox + p[0], self.oy + p[1]

    def _box(self, b):
        return self.ox + b[0], self.oy + b[1], self.ox + b[2], self.oy + b[3]

    def _check(self):
        if win.esc_pressed():
            raise Stop("ESC를 눌러 멈췄습니다.")

    def _sleep(self, sec):
        end = time.time() + sec
        while time.time() < end:
            self._check()
            time.sleep(0.1)

    def _click(self, p, double=False):
        self._check()
        (win.double_click if double else win.click)(*self._abs(p))

    def _lines(self, box, scale=2.0):
        return ocr.read(self._box(box), scale)

    def _text(self, box, scale=2.0) -> str:
        return clean(" ".join(ln.text for ln in self._lines(box, scale)))

    def _find(self, box, word, min_ratio=0.75):
        """box 안에서 word와 가장 비슷한 줄(화면 좌표). 없으면 None."""
        best, score = None, 0.0
        for ln in self._lines(box):
            s = similar(ln.text, word)
            if s > score:
                best, score = ln, s
        return best if score >= min_ratio else None

    def _click_line(self, ln, double=False):
        self._check()
        (win.double_click if double else win.click)(ln.x, ln.y)

    # ---- 1. 창 ----
    def attach(self):
        self.hwnd = win.find_window(WISE_TITLE, WISE_CLASS)
        if not self.hwnd:
            raise Stop("WISE 창을 찾지 못했습니다. WISE에 접속(로그인)한 뒤 다시 눌러 주세요.")
        win.activate(self.hwnd)
        if not win.is_maximized(self.hwnd):
            win.maximize(self.hwnd)
            win.activate(self.hwnd)
        left, top, right, bottom = win.window_rect(self.hwnd)
        self.ox, self.oy = left, top
        if right - left < 1800 or bottom - top < 1000:
            raise Stop(f"WISE 창 크기가 {right - left}×{bottom - top}입니다. 1920×1080 화면에서 "
                       "WISE를 최대화한 상태여야 자리를 찾을 수 있습니다.")
        win.esc_pressed()            # 전에 눌린 ESC 기록 지우기

    # ---- 2. 메뉴 ----
    def _on_screen(self) -> bool:
        return similar(self._text(TITLE_BOX), "임대조건관리(건설)") >= 0.75

    def open_screen(self):
        if self._on_screen():
            self.log("WISE: 임대조건관리(건설) 화면이 이미 열려 있습니다.")
            return
        tab = self._find(TABS_BOX, "임대조건관리(건설)", 0.8)
        if tab:
            self._click_line(tab)
            self._sleep(1.5)
            if self._on_screen():
                return
        self.log("WISE: 건설임대 > 공급 > 공급임대조건 산정 > 임대조건관리(건설)을 엽니다.")
        self._click(MENU_BUILD)
        self._sleep(1.5)
        self._click(MENU_SUPPLY)
        self._sleep(1.5)
        item = self._find(TREE_BOX, "임대조건관리(건설)", 0.8)
        if item is None:
            group = self._find(TREE_BOX, "공급임대조건 산정", 0.7)
            if group is None:
                raise Stop("왼쪽 메뉴에서 '공급임대조건 산정'을 찾지 못했습니다. WISE에서 "
                           "건설임대 > 공급 메뉴가 보이는지 확인해 주세요.")
            self._click_line(group)
            self._sleep(1.2)
            item = self._find(TREE_BOX, "임대조건관리(건설)", 0.8)
        if item is None:
            raise Stop("왼쪽 메뉴에서 '임대조건관리(건설)'을 찾지 못했습니다.")
        self._click_line(item)
        for _ in range(20):
            self._sleep(0.5)
            if self._on_screen():
                self._sleep(1.0)
                return
        raise Stop("임대조건관리(건설) 화면이 열리지 않았습니다.")

    # ---- 3. 지역본부·단지 ----
    def set_region(self, region: str) -> str:
        now = self._text(REGION_BOX)
        if not region or region == KEEP_REGION or similar(now, region) >= 0.8:
            return now
        self.log(f"WISE: 지역본부를 {region}(으)로 바꿉니다.")
        self._click(REGION_ARROW)
        self._sleep(1.0)
        item = self._find(REGION_LIST_BOX, region, 0.7)
        if item is None:
            win.key("esc")
            raise Stop(f"지역본부 목록에서 '{region}'을 찾지 못했습니다. WISE에서 직접 고른 뒤, "
                       f"지역본부를 '{KEEP_REGION}'으로 두고 다시 해 주세요.")
        self._click_line(item)
        self._sleep(1.0)
        return self._text(REGION_BOX)

    def set_complex(self, name: str):
        if similar(self._text(COMPLEX_NAME_BOX), name) >= 0.9 and self._text(COMPLEX_CODE_BOX).strip():
            return
        self.log(f"WISE: 단지 '{name}'을 찾습니다.")
        self._click(COMPLEX_NAME)
        win.key("ctrl+a")
        win.key("delete")
        win.type_text(name)
        self._sleep(0.3)
        win.key("enter")
        self._sleep(1.5)
        if self._complex_ok(name):
            return
        self._click(COMPLEX_FIND)
        self._sleep(2.0)
        if self._complex_ok(name):
            return
        # 단지 고르는 창: 화면 전체에서 단지명이 적힌 줄(원래 검색 칸 말고)을 두 번 누른다
        for _ in range(3):
            cand = None
            for ln in self._lines((0, 120, 1920, 1000)):
                if similar(ln.text, name) < 0.85:
                    continue
                sx, sy = ln.x - self.ox, ln.y - self.oy
                b = POPUP_SKIP_BOX
                if b[0] <= sx <= b[2] and b[1] <= sy <= b[3]:
                    continue
                cand = ln
                break
            if cand is not None:
                self._click_line(cand, double=True)
                self._sleep(1.5)
                if self._complex_ok(name):
                    return
                win.key("enter")
                self._sleep(1.5)
                if self._complex_ok(name):
                    return
            self._sleep(1.0)
        raise Stop(f"WISE에서 단지 '{name}'을 고르지 못했습니다. WISE에서 단지를 직접 고르고 "
                   "[검색]까지 누른 뒤 원터치 자동작성을 다시 눌러 주세요(그 화면을 그대로 읽습니다).")

    def _complex_ok(self, name: str) -> bool:
        return (similar(self._text(COMPLEX_NAME_BOX), name) >= 0.8
                and bool(re.search(r"\w{3,}", self._text(COMPLEX_CODE_BOX))))

    def search(self):
        self.log("WISE: [검색]을 누릅니다.")
        self._click(SEARCH)
        self._sleep(2.5)

    # ---- 4. 표 읽기 ----
    def _cell(self, img, i, col):
        a, b = COLS[col]
        cy = GRID_TOP + i * ROW_H
        return wise_glyph.read(img.crop((a, cy - 11, b, cy + 11)), wise_glyphs.GLYPHS)

    def _visible_rows(self) -> list[Row]:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=self._box((0, 0, 1920, 1032)), all_screens=True)
        out = []
        for i in range(ROWS):
            v = {c: self._cell(img, i, c) for c in COLS}
            if not v["no"]:
                break
            if None in v.values() or not v["no"].isdigit():
                raise Stop(f"임대조건 표 {i + 1}번째 줄 숫자를 읽지 못했습니다. WISE 표가 다른 창에 "
                           "가려지지 않았는지, 칸 너비를 바꾸지 않았는지 확인해 주세요.")
            try:
                out.append(Row(int(v["no"]), v["type"], int(v["units"].replace(",", "") or 0), v["excl"],
                               v["start"], v["dep"], v["rent"]))
            except ValueError:
                raise Stop(f"임대조건 표 {i + 1}번째 줄 값이 이상합니다: {v}")
        return out

    def read_rows(self) -> list[Row]:
        rows: dict[int, Row] = {}
        last_top = None
        for _ in range(30):
            vis = self._visible_rows()
            if not vis:
                break
            for r in vis:
                rows[r.no] = r
            if vis[0].no == last_top or len(vis) < ROWS:
                break
            last_top = vis[0].no
            win.wheel(*self._abs(GRID_WHEEL), -3)       # 아래로 내려 나머지 줄
            self._sleep(0.8)
        return [rows[k] for k in sorted(rows)]

    def run(self, region: str, complex_name: str) -> Result:
        self.attach()
        self.open_screen()
        region_now = self.set_region(region)
        self.set_complex(complex_name)
        self.search()
        rows = self.read_rows()
        if not rows:
            raise Stop("임대조건 표가 비어 있습니다. 지역본부·단지·임대조건유형을 확인해 주세요.")
        pick = latest_rows(rows)
        rent_type = self._text(TYPE_BOX).replace(" ", "")
        self.log(f"WISE: 임대조건 {len(rows)}줄을 읽었습니다(임대시작일 {pick[0].start} 기준 {len(pick)}줄).")
        return Result(region_now.replace(" ", ""), complex_name, rent_type, pick[0].start, to_types(pick),
                      len(rows))
