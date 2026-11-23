"""새 디자인 화면들(샘플 그림 기준: 왼쪽 메뉴 + 옅은 파랑 바탕 + 흰 카드).

- Sidebar: 왼쪽 메뉴(홈 · 공문 작성 · 서식 고르기 · 작성 이력 · 환경 설정)와 아래 관리소·담당자 카드.
- Home(=Landing): 인사말, 파란 배너([새 공문 작성하기]), 분야 카드 4개, 통계 3개,
  오른쪽 바로가기·최근 작성 문서. 검색칸에 적으면 모든 분야의 서식을 찾아 아래로 펼쳐 보여 준다.
- Picker: 그 분야의 서식을 '매월 작성' / '기타 공문'(매주 서식이 있으면 '매주 작성'도) 카드로 보여 준다.
  묶음(갱신계약·예비입주자 …)별로 접혀 있고 누르면 펼친다. 서식을 누르면 on_pick(번호).
- InfoScreen: 서식을 고른 뒤 관리소 정보·홈넷 계정을 확인·입력한다.
- HistoryScreen: 작성 이력(logs\\작성이력_*.csv) 목록.
창 크기에 맞춰 다시 그린다.
"""
import datetime as dt
import tkinter as tk
from tkinter import ttk

import ui_kit
from doc_template import RENT_TYPES, normalize_rent_type
from ui_kit import (BORDER, CARD, FONT, HOVER_SOFT, LINE, MUTED, PAGE, PRIMARY, PRIMARY_D, PRIMARY_SOFT,
                    SIDEBAR, SUB, TEXT, TINTS, HitCanvas, Painter, ellipsize, fs, is_done, keep_colors,
                    round_rect)

AREAS = [("임대", "입주자격심사 · 갱신계약 · 계약해지 · 가정어린이집"),
         ("시설", "당직 · 승강기 · 안전점검 · 환경정비 (월별)"),
         ("주거복지", "마이홈 · 간담회 · 클린데이 · 돌봄 (월별)"),
         ("주택관리", "관리비 · 회계 · 교육 · 보고 (월별 · 주별)")]
AREA_LOOK = {"임대": ("key", "blue", "입주자격 · 갱신계약 · 해지"),
             "시설": ("wrench", "violet", "당직 · 승강기 · 안전점검"),
             "주거복지": ("heart", "teal", "마이홈 · 간담회 · 돌봄"),
             "주택관리": ("calc", "pink", "관리비 · 회계 · 교육")}

# 예전 이름(다른 모듈·시험이 쓰는 이름)
BG = PAGE
ORANGE = PRIMARY
TEXT_HOVER = PRIMARY
SUB_TEXT = SUB


def _fs(pt: float, k: float, least: float = 0) -> int:
    return fs(pt, k, least)


def match(t, q: str) -> bool:
    """검색어(띄어쓰기 무시)가 서식 이름·제목·구분·묶음에 들어 있는지."""
    if not q:
        return True
    q = q.replace(" ", "")
    return any(q in s.replace(" ", "") for s in (t.label, t.title, t.group, t.bundle))


def _search_box(parent, query: tk.StringVar, hint: str = "", bg: str = CARD, border: str = BORDER,
                focus: str = PRIMARY):
    """검색칸(흰 바탕 + 옅은 테두리, 누르면 파란 테두리). (바깥 틀, 입력칸)
    둥근 바탕을 따로 그리는 곳에서는 border·focus를 바탕색과 같게 준다."""
    box = tk.Frame(parent, bg=border)
    inner = tk.Frame(box, bg=bg)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    tk.Label(inner, text="", bg=bg, fg=SUB, font=("Segoe MDL2 Assets", 11)).pack(side="left", padx=(12, 4))
    entry = tk.Entry(inner, textvariable=query, relief="flat", bd=0,
                     highlightthickness=0, insertbackground=TEXT, font=(FONT, 11))
    keep_colors(entry, bg=bg, fg=TEXT)
    entry.pack(side="left", fill="both", expand=True, padx=(4, 12), pady=6)
    if hint:
        tip = tk.Label(inner, text=hint, bg=bg, fg=MUTED, font=(FONT, 10))

        def show_tip(*_):
            if query.get() or parent.focus_get() is entry:
                tip.place_forget()
            else:
                tip.place(in_=entry, x=2, rely=0.5, anchor="w")
        query.trace_add("write", show_tip)
        entry.bind("<FocusIn>", show_tip, add="+")
        entry.bind("<FocusOut>", show_tip, add="+")
        tip.bind("<Button-1>", lambda _e: entry.focus_set())
        show_tip()
    entry.bind("<Escape>", lambda _e: query.set(""))
    entry.bind("<FocusIn>", lambda _e: box.config(bg=focus), add="+")
    entry.bind("<FocusOut>", lambda _e: box.config(bg=border), add="+")
    return box, entry


def _draw_title(cv: tk.Canvas, x, y, k, big: str, rest: str, sub: str):
    """화면 제목(굵게)과 아래 설명. y는 제목 아랫줄."""
    cv.create_text(x, y, anchor="sw", text=big + rest, font=(FONT, _fs(21, k, 15), "bold"), fill=TEXT)
    cv.create_text(x + 1 * k, y + 8 * k, anchor="nw", text=sub, font=(FONT, _fs(10.5, k, 9)), fill=SUB)


def _back_link(cv: tk.Canvas, x, y, text, command, k):
    t = cv.create_text(x, y, anchor="ne", text=text, font=(FONT, _fs(10.5, k, 9)), fill=SUB)
    cv.tag_bind(t, "<Enter>", lambda _e: (cv.itemconfigure(t, fill=PRIMARY), cv.config(cursor="hand2")))
    cv.tag_bind(t, "<Leave>", lambda _e: (cv.itemconfigure(t, fill=SUB), cv.config(cursor="")))
    cv.tag_bind(t, "<Button-1>", lambda _e: command())
    return t


def _fmt_time(s: str) -> str:
    """'2026-01-23 14:20:05' → '2026.01.23 14:20'."""
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").strftime("%Y.%m.%d %H:%M")
    except (ValueError, TypeError):
        return s or ""


# ======================================================================
#  왼쪽 메뉴
# ======================================================================
class Sidebar(HitCanvas):
    NAV = (("home", "홈", "home"), ("write", "공문 작성", "edit"), ("picker", "서식 고르기", "layers"),
           ("history", "작성 이력", "history"), None, ("settings", "환경 설정", "settings"),
           ("mydocs", "나의 공문 작성", "star"))
    # 단지기본정보는 처음 화면 바로가기·[파일] 메뉴·아래 관리소 카드에서 연다

    def __init__(self, parent, commands: dict, k: float, version: str = "", profile=None, on_profile=None):
        self.k = k
        self.W = int(236 * k)
        super().__init__(parent, bg=SIDEBAR, width=self.W)
        self.commands = commands
        self.version = version
        self.profile = profile or (lambda: ("", "", ""))
        self.on_profile = on_profile
        self.active = "home"
        self._img = None
        self._job = None
        self.bind("<Configure>", lambda _e: self._schedule())

    def _schedule(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(30, self.draw)

    def set_active(self, key: str):
        if key != self.active:
            self.active = key
            self.draw()

    def refresh(self):
        self.draw()

    def draw(self):
        self._job = None
        w, h = self.W, max(self.winfo_height(), 400)
        k = min(self.k, h / 640 * self.k) if h < 640 * self.k else self.k
        self.delete("all")
        self.clear_hits()
        P = Painter(w, h, SIDEBAR)
        P.line([(w - 0.5, 0), (w - 0.5, h)], BORDER, 1)

        # 로고(파란 문서) + 이름 KODAS
        lx, ly, ls = 22 * k, 30 * k, 46 * k
        dw, dh, fold = 30 * k, 38 * k, 10 * k           # 문서 너비·높이·접힌 귀퉁이
        dx0, dy0 = lx + (ls - dw) / 2, ly + (ls - dh) / 2
        dx1, dy1 = dx0 + dw, dy0 + dh
        P.shadow(dx0, dy0, dx1, dy1, 5 * k, alpha=36, dy=3, color=PRIMARY_D)
        P.polygon([(dx0, dy0), (dx1 - fold, dy0), (dx1, dy0 + fold), (dx1, dy1), (dx0, dy1)], PRIMARY)
        P.polygon([(dx1 - fold, dy0), (dx1, dy0 + fold), (dx1 - fold, dy0 + fold)], PRIMARY_SOFT)
        for i in range(3):                               # 글줄 세 개
            yy = dy0 + 17 * k + i * 6.5 * k
            P.line([(dx0 + 7 * k, yy), (dx1 - (7 if i < 2 else 12) * k, yy)], "#ffffff", max(1, round(2.2 * k)))
        self.create_text(lx + ls + 12 * k, ly + ls / 2 - 9 * k, anchor="w", text="KODAS",
                         font=(FONT, fs(17, k), "bold"), fill=TEXT)
        self.create_text(lx + ls + 13 * k, ly + ls / 2 + 13 * k, anchor="w", text="공문 자동작성 시스템",
                         font=(FONT, fs(8.5, k, 8)), fill=SUB)
        # 로고 밑: KODAS 뜻(머리글자 K·O·D·A·S는 진한 색) — KOhom Document Automation System
        import tkinter.font as tkfont
        px = -max(11, round(12.5 * k))
        f_thin = tkfont.Font(family=FONT, size=px)
        f_bold = tkfont.Font(family=FONT, size=px, weight="bold")
        parts = (("KO", True), ("hom ", False), ("D", True), ("ocument ", False),
                 ("A", True), ("utomation ", False), ("S", True), ("ystem", False))
        total = sum((f_bold if s else f_thin).measure(p) for p, s in parts)
        mx, my = max(10 * k, (w - total) / 2), ly + ls + 16 * k
        for part, strong in parts:
            f = f_bold if strong else f_thin
            self.create_text(mx, my, anchor="w", text=part, font=f, fill=PRIMARY if strong else SUB)
            mx += f.measure(part)
        # 로고(KODAS)를 누르면 홈으로
        self.add_hit((14 * k, ly - 6 * k, w - 14 * k, my + 8 * k), self.commands.get("home"))

        # 메뉴
        y = 122 * k
        ih = 48 * k
        for item in self.NAV:
            if item is None:
                y += 10 * k
                P.line([(26 * k, y), (w - 26 * k, y)], LINE, 1)
                y += 18 * k
                continue
            key, label, icon = item
            on = key == self.active
            x0, x1 = 14 * k, w - 14 * k
            if on:
                P.rrect(x0, y, x1, y + ih, 12 * k, PRIMARY_SOFT)
            P.icon(icon, x0 + 30 * k, y + ih / 2, 19 * k, PRIMARY if on else "#4b5567")
            t = self.create_text(x0 + 58 * k, y + ih / 2, anchor="w", text=label,
                                 font=(FONT, fs(11.5, k, 9), "bold" if on else "normal"),
                                 fill=PRIMARY_D if on else TEXT)
            cmd = self.commands.get(key)
            self.add_hit((x0, y, x1, y + ih), cmd,
                         (lambda t=t, on=on: lambda v: self.itemconfigure(
                             t, fill=PRIMARY_D if (v or on) else TEXT))())
            y += ih + 8 * k

        # 아래: 관리소 · 담당자 카드
        org, place, name = self.profile()
        cy1 = h - 18 * k
        cy0 = cy1 - 128 * k
        if cy0 > y + 10 * k:
            x0, x1 = 14 * k, w - 14 * k
            P.rrect(x0, cy0, x1, cy1, 14 * k, HOVER_SOFT)
            mid = cy0 + 70 * k
            P.icon("building", x0 + 26 * k, cy0 + 35 * k, 19 * k, "#4b5567")
            self.create_text(x0 + 50 * k, cy0 + 26 * k, anchor="w", text=ellipsize(org or "주택관리공단", 11),
                             font=(FONT, fs(10.5, k, 9), "bold"), fill=TEXT)
            self.create_text(x0 + 50 * k, cy0 + 47 * k, anchor="w", text=ellipsize(place or "단지명을 넣어 주세요", 13),
                             font=(FONT, fs(9, k, 8)), fill=SUB)
            P.line([(x0 + 14 * k, mid), (x1 - 14 * k, mid)], BORDER, 1)
            P.icon("person", x0 + 26 * k, mid + 29 * k, 18 * k, "#4b5567")
            who = self.create_text(x0 + 50 * k, mid + 29 * k, anchor="w",
                                   text=f"{ellipsize(name, 8)} 님" if name else "담당자 정보 넣기",
                                   font=(FONT, fs(10.5, k, 9)), fill=TEXT)
            P.icon("chevron", x1 - 22 * k, mid + 29 * k, 11 * k, SUB)
            self.add_hit((x0, cy0, x1, cy1), self.on_profile,
                         lambda v: self.itemconfigure(who, fill=PRIMARY_D if v else TEXT))

        self._img = P.finish()
        self.create_image(0, 0, anchor="nw", image=self._img, tags="bg")
        self.tag_lower("bg")


# ======================================================================
#  처음 화면(대시보드)
# ======================================================================
class Home(HitCanvas):
    MAX_RESULTS = 8       # 검색 결과는 이만큼만 보여 준다(더 있으면 '외 n건')

    def __init__(self, parent, on_select, logo_path: str = "", version: str = "", counts: dict | None = None,
                 on_pick=None, items=None, on_new=None, shortcuts=(), history=None, on_history=None, user=None,
                 on_more=None):
        super().__init__(parent, bg=PAGE)
        self.on_more = on_more                  # '비슷한 공문 모두 보기' → on_more(검색어)
        self.on_select = on_select
        self.on_pick = on_pick                  # 검색 결과를 누르면 on_pick(번호)
        self.items = items or (lambda: [])      # () → [(번호, 서식) …] 모든 분야
        self.on_new = on_new
        self.shortcuts = list(shortcuts)        # [(이름, 아이콘, 색, 명령) …]
        self.history = history or (lambda: [])
        self.on_history = on_history
        self.user = user or (lambda: "")
        self.version = version
        self.counts = counts or {}
        self.query = tk.StringVar()
        self.search, self.search_entry = _search_box(self, self.query, "찾을 공문 이름 (예: 승강기, 갱신)",
                                                     border=CARD, focus=CARD)
        self.query.trace_add("write", lambda *_: self._show_results())
        self.search_entry.bind("<Return>", lambda _e: self._open_first())
        self.search_entry.bind("<Down>", lambda _e: self._open_first())
        self.drop = tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        self._drop_at = (0, 0, 300)
        self._img = None
        self._job = None
        self.bind("<Configure>", lambda _e: self._schedule())

    # ---- 바깥에서 부르는 것 ----
    def set_counts(self, counts: dict):
        self.counts = counts
        self.draw()

    def refresh(self):
        self.draw()

    def focus_search(self):
        """검색칸을 비우고 커서를 넣는다. 뒤에서 공문 작성 화면이 준비되며 커서를 가져가므로 한숨 쉬고 넣는다."""
        self.query.set("")

        def put():
            if self.winfo_ismapped() and self.focus_get() is not self.search_entry:
                self.search_entry.focus_force()
        self.after_idle(put)
        for ms in (300, 800, 1500):
            self.after(ms, put)

    def results(self) -> list:
        """검색어와 비슷한 공문(모든 분야) [(번호, 서식) …] 비슷한 순서."""
        import similar
        q = self.query.get().strip()
        return [(r[0], r[1]) for r in similar.search(self.items(), q)] if q else []

    def _open_first(self):
        found = self.results()
        if found and self.on_pick:
            self.on_pick(found[0][0])

    def _schedule(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(40, self.draw)

    # ---- 검색 결과(검색칸 아래로 펼침) ----
    def _show_results(self):
        for c in self.drop.winfo_children():
            c.destroy()
        q = self.query.get().strip()
        if not q:
            self.drop.place_forget()
            return
        found = self.results()
        x1, y, w = self._drop_at
        head = tk.Label(self.drop, text=f"검색 결과 {len(found)}건  ·  누르거나 Enter로 첫 공문 열기  ·  Esc 지우기",
                        bg=CARD, fg=SUB, font=(FONT, 9), anchor="w", padx=14, pady=8)
        head.pack(fill="x")
        tk.Frame(self.drop, bg=LINE, height=1).pack(fill="x")
        if not found:
            tk.Label(self.drop, text="찾는 서식이 없습니다. 다른 말로 찾아 보세요.", bg=CARD, fg=MUTED,
                     font=(FONT, 10), anchor="w", padx=14, pady=14).pack(fill="x")
        for n, t in found[:self.MAX_RESULTS]:
            self._result_row(n, t)
        if found and self.on_more:
            tk.Frame(self.drop, bg=LINE, height=1).pack(fill="x")
            more = tk.Label(self.drop, text=f"비슷한 공문 모두 보기 ({len(found)}건)  ›", bg=CARD, fg=PRIMARY_D,
                            font=(FONT, 9, "bold"), anchor="w", padx=14, pady=9, cursor="hand2")
            more.pack(fill="x")
            more.bind("<Enter>", lambda _e: more.config(bg=HOVER_SOFT))
            more.bind("<Leave>", lambda _e: more.config(bg=CARD))
            more.bind("<Button-1>", lambda _e: self.on_more(q))
        self.drop.place(x=x1, y=y, anchor="ne", width=w)
        tk.Misc.lift(self.drop)

    def _result_row(self, n, t):
        row = tk.Frame(self.drop, bg=CARD, cursor="hand2")
        row.pack(fill="x")
        area = tk.Label(row, text=t.area, bg=PRIMARY_SOFT, fg=PRIMARY_D, font=(FONT, 8, "bold"), padx=7, pady=1)
        area.pack(side="left", padx=(14, 10), pady=10)
        body = tk.Frame(row, bg=CARD)
        body.pack(side="left", fill="x", expand=True, pady=6)
        title = tk.Label(body, text=t.label, bg=CARD, fg=TEXT, font=(FONT, 10), anchor="w")
        title.pack(fill="x")
        cyc = {"매월": "매월", "매주": "매주"}.get(t.cycle, "수시")
        sub = tk.Label(body, text=f"{cyc} · {t.bundle or t.group}", bg=CARD, fg=SUB, font=(FONT, 8), anchor="w")
        sub.pack(fill="x")
        parts = (row, body, title, sub)

        def hover(on):
            for p in parts:
                p.config(bg=HOVER_SOFT if on else CARD)
            title.config(fg=PRIMARY_D if on else TEXT)
        for p in parts + (area,):
            p.bind("<Enter>", lambda _e: hover(True))
            p.bind("<Leave>", lambda _e: hover(False))
            p.bind("<Button-1>", lambda _e, n=n: self.on_pick and self.on_pick(n))

    # ---- 그리기 ----
    def draw(self):
        self._job = None
        w, h = max(self.winfo_width(), 760), max(self.winfo_height(), 500)
        k = max(0.7, min(w / 1120, h / 720))
        self.delete("all")
        self.clear_hits()
        P = Painter(w, h, PAGE)
        m, gap = 28 * k, 18 * k
        rw = min(max(w * 0.28, 250 * k), 340 * k)
        rx0 = w - m - rw
        x0, x1 = m, rx0 - gap

        # ---- 인사말 + 검색칸 ----
        name = self.user()
        greet = self.create_text(x0 + 4 * k, 30 * k, anchor="nw", text=f"안녕하세요, {name} 님!" if name else "안녕하세요!",
                                 font=(FONT, fs(21, k, 15), "bold"), fill=TEXT)
        gb = self.bbox(greet)
        P.emoji("\U0001F44B", gb[2] + 10 * k, (gb[1] + gb[3]) / 2, 26 * k)
        self.create_text(x0 + 5 * k, gb[3] + 6 * k, anchor="nw",
                         text="KODAS가 서식에 이름·날짜만 넣으면 홈넷 공문을 자동으로 작성해요.",
                         font=(FONT, fs(11, k, 9)), fill=SUB)
        sw = min(300 * k, (x1 - x0) * 0.42)
        sy, sh = 34 * k, 42 * k
        P.shadow(x1 - sw, sy, x1, sy + sh, sh / 2, alpha=18, dy=3)
        P.rrect(x1 - sw, sy, x1, sy + sh, sh / 2, CARD, outline=BORDER)
        inset = sh * 0.3
        self.create_window(x1 - inset, sy + 3 * k, anchor="ne", window=self.search, width=sw - inset * 2,
                           height=sh - 6 * k)
        self._drop_at = (x1, sy + sh + 6 * k, max(sw, min(460 * k, x1 - x0)))

        # ---- 높이 나누기 ----
        top = 112 * k
        avail = h - m - top - 2 * gap
        hero_h = max(170 * k, avail * 0.43)
        card_h = max(124 * k, avail * 0.31)
        stat_h = avail - hero_h - card_h
        if stat_h < 86 * k:
            hero_h -= 86 * k - stat_h
            stat_h = 86 * k

        # ---- 파란 배너 ----
        hy0, hy1 = top, top + hero_h
        P.shadow(x0 + 10 * k, hy0 + 10 * k, x1 - 10 * k, hy1, 22 * k, alpha=55, dy=10, color=PRIMARY_D)
        mask = P.gradient_rrect(x0, hy0, x1, hy1, 22 * k, *HERO_COLORS)
        photo = bool(ui_kit.HERO_PHOTO) and P.photo_in(x0, hy0, mask, ui_kit.HERO_PHOTO, HERO_COLORS[1])
        hw = x1 - x0

        def deco(d, ss):
            d.ellipse([hw * 0.30 * ss, hero_h * 0.55 * ss, hw * 1.25 * ss, hero_h * 1.9 * ss],
                      fill=(255, 255, 255, 26))
            d.ellipse([hw * 0.55 * ss, hero_h * 0.72 * ss, hw * 1.4 * ss, hero_h * 2.2 * ss],
                      fill=(255, 255, 255, 22))
            d.ellipse([-hw * 0.2 * ss, -hero_h * 0.9 * ss, hw * 0.45 * ss, hero_h * 0.35 * ss],
                      fill=(255, 255, 255, 14))
        if not photo:                     # 사진 배너에는 장식 원·종이 그림을 얹지 않는다(사진이 보이게)
            P.overlay_in(x0, hy0, mask, deco)
        art = hw >= 560 * k and not photo
        tx = x0 + 40 * k
        text_w = hw - 80 * k
        if art:
            ph = min(hero_h * 0.74, 250 * k, hw * 0.34)
            pw = ph * 0.78
            cx = x1 - hw * 0.19
            cy = hy0 + hero_h * 0.52
            P.paper(cx + pw * 0.14, cy + ph * 0.04, pw, ph, -10, title="")
            P.paper(cx, cy, pw, ph, 6, title="공문")
            P.sparkle(cx - pw * 0.66, cy - ph * 0.40, 11 * k)
            P.sparkle(cx + pw * 0.72, cy + ph * 0.22, 8 * k)
            P.sparkle(cx + pw * 0.08, cy + ph * 0.32, 9 * k, alpha=230)
            text_w = cx - pw * 0.72 - tx
        P.sparkle(tx + 8 * k, hy0 + 38 * k, 10 * k)
        P.sparkle(tx + 20 * k, hy0 + 28 * k, 5 * k)
        self.create_text(tx + 30 * k, hy0 + 38 * k, anchor="w", text="공문 자동 작성",
                         font=(FONT, fs(11.5, k, 9), "bold"), fill="#ffffff")
        ly = hy0 + 60 * k
        lines = ("서식을 고르고 이름·날짜만 넣으면", "홈넷 공문 초안을 자동으로 만들어 드려요.")
        from tkinter import font as tkfont
        pt = 17.0
        while pt > 11 and tkfont.Font(self, family=FONT, size=fs(pt, k), weight="bold").measure(lines[1]) > text_w:
            pt -= 0.5                     # 배너 폭에 두 줄로 들어가도록 글자를 줄인다
        for line in lines:
            big = self.create_text(tx, ly, anchor="nw", text=line, width=text_w,
                                   font=(FONT, fs(pt, k), "bold"), fill="#ffffff")
            ly = self.bbox(big)[3] + 4 * k
        bb = self.bbox(big)
        bw, bh = 218 * k, 48 * k
        by = max(bb[3] + 18 * k, hy1 - 30 * k - bh)
        if by + bh > hy1 - 12 * k:
            by = hy1 - 12 * k - bh
        P.shadow(tx, by, tx + bw, by + bh, bh / 2, alpha=50, dy=6, color=PRIMARY_D)
        P.rrect(tx, by, tx + bw, by + bh, bh / 2, "#ffffff")
        P.icon("add", tx + 30 * k, by + bh / 2, 16 * k, PRIMARY)
        P.icon("chevron", tx + bw - 26 * k, by + bh / 2, 11 * k, TEXT)
        bt = self.create_text(tx + 52 * k, by + bh / 2, anchor="w", text="새 공문 작성하기",
                              font=(FONT, fs(12, k, 10), "bold"), fill=TEXT)
        self.add_hit((tx, by, tx + bw, by + bh), self.on_new,
                     lambda v: self.itemconfigure(bt, fill=PRIMARY_D if v else TEXT))

        # ---- 분야 카드 4개 ----
        cy0 = hy1 + gap
        cg = 14 * k
        cw = (x1 - x0 - 3 * cg) / 4
        for i, (area, _desc) in enumerate(AREAS):
            icon, tint, short = AREA_LOOK[area]
            cx0 = x0 + i * (cw + cg)
            P.card(cx0, cy0, cx0 + cw, cy0 + card_h, 16 * k)
            ccx = cx0 + cw / 2
            P.tint_icon(icon, ccx, cy0 + card_h * 0.32, 25 * k, tint, size=22 * k)
            n = self.counts.get(area, 0)
            title = self.create_text(ccx, cy0 + card_h * 0.62, anchor="center", text=area,
                                     font=(FONT, fs(13, k, 10), "bold"), fill=TEXT)
            self.create_text(ccx, cy0 + card_h * 0.81, anchor="center",
                             text=f"{short}" if n else "준비 중", width=cw - 16 * k, justify="center",
                             font=(FONT, fs(9, k, 8)), fill=SUB if n else MUTED)
            if n:
                chip = f"{n}종"
                cw_chip = (len(chip) * 8 + 14) * k
                P.rrect(cx0 + cw - 12 * k - cw_chip, cy0 + 12 * k, cx0 + cw - 12 * k, cy0 + 32 * k, 10 * k,
                        TINTS[tint][0])
                self.create_text(cx0 + cw - 12 * k - cw_chip / 2, cy0 + 22 * k, text=chip, anchor="center",
                                 font=(FONT, fs(8, k, 7), "bold"), fill=TINTS[tint][1])
            self.add_hit((cx0, cy0, cx0 + cw, cy0 + card_h), lambda a=area: self.on_select(a),
                         (lambda t=title: lambda v: self.itemconfigure(t, fill=PRIMARY_D if v else TEXT))())

        # ---- 통계 3개 ----
        rows = self.history()
        done = [r for r in rows if is_done(r)]
        month = f"{dt.date.today():%Y-%m}"
        stats = (("작성한 문서", len(done), "건", "page", "blue"),
                 ("등록된 서식", len(self.items()), "개", "layers", "violet"),
                 ("이번 달 작성", sum(1 for r in done if r.get("시각", "").startswith(month)), "건", "history", "teal"))
        sy0 = cy0 + card_h + gap
        sy1 = sy0 + stat_h
        sg = 14 * k
        sw3 = (x1 - x0 - 2 * sg) / 3
        for i, (label, value, unit, icon, tint) in enumerate(stats):
            sx0 = x0 + i * (sw3 + sg)
            P.card(sx0, sy0, sx0 + sw3, sy1, 16 * k)
            mid = (sy0 + sy1) / 2
            P.tint_icon(icon, sx0 + 44 * k, mid, 27 * k, tint, square=True, size=22 * k)
            P.wave(sx0 + sw3 * 0.6, sy1 - 14 * k, sx0 + sw3 - 16 * k, min(stat_h * 0.42, 46 * k),
                   TINTS[tint][1], alpha=34)
            self.create_text(sx0 + 86 * k, mid - 15 * k, anchor="w", text=label,
                             font=(FONT, fs(10, k, 8.5)), fill=SUB)
            v = self.create_text(sx0 + 86 * k, mid + 14 * k, anchor="w", text=f"{value:,}",
                                 font=(FONT, fs(20, k, 13), "bold"), fill=TEXT)
            vb = self.bbox(v)
            self.create_text(vb[2] + 3 * k, mid + 18 * k, anchor="w", text=unit,
                             font=(FONT, fs(11, k, 9)), fill=TEXT)
            hover = (lambda t=v: lambda on: self.itemconfigure(t, fill=PRIMARY_D if on else TEXT))()
            if i == 1 and self.on_new:          # 등록된 서식 → 서식 고르기 화면
                self.add_hit((sx0, sy0, sx0 + sw3, sy1), self.on_new, hover)
            elif i != 1 and self.on_history:
                self.add_hit((sx0, sy0, sx0 + sw3, sy1), self.on_history, hover)

        # ---- 오른쪽: 바로가기 ----
        px0, px1 = rx0, w - m
        py0 = 30 * k
        pad = 20 * k
        tg = 12 * k
        tw = (rw - pad * 2 - tg) / 2
        n = min(len(self.shortcuts), 6)
        rows_n = max(1, (n + 1) // 2)              # 두 칸씩, 홀수면 마지막 칸은 한 줄 전체
        th = max(70 * k if rows_n > 2 else 86 * k,
                 min(108 * k, (h * 0.42 - 76 * k - (rows_n - 2) * tg) / max(2, rows_n)))
        p1y1 = py0 + 62 * k + th * rows_n + tg * (rows_n - 1) + pad
        P.card(px0, py0, px1, p1y1, 18 * k)
        self.create_text(px0 + pad + 2 * k, py0 + 32 * k, anchor="w", text="바로가기",
                         font=(FONT, fs(14, k, 10), "bold"), fill=TEXT)
        for j, (label, icon, tint, cmd) in enumerate(self.shortcuts[:n]):
            tx0 = px0 + pad + (j % 2) * (tw + tg)
            ty0 = py0 + 62 * k + (j // 2) * (th + tg)
            ww = tw * 2 + tg if (j == n - 1 and n % 2) else tw      # 홀수 개면 마지막은 넓게
            P.rrect(tx0, ty0, tx0 + ww, ty0 + th, 14 * k, CARD, outline=BORDER)
            P.shadow(tx0 + 4 * k, ty0 + 4 * k, tx0 + ww - 4 * k, ty0 + th, 14 * k, alpha=14, dy=3)
            if ww > tw:                              # 넓은 칸: 아이콘 왼쪽, 글자 오른쪽
                lw = self.create_text(0, 0, text=label, font=(FONT, fs(10, k, 8.5)))
                bw = self.bbox(lw)[2] - self.bbox(lw)[0]
                self.delete(lw)
                ix = tx0 + ww / 2 - (bw + 44 * k) / 2 + 21 * k
                P.tint_icon(icon, ix, ty0 + th / 2, 21 * k, tint, square=True, size=20 * k)
                lt = self.create_text(ix + 32 * k, ty0 + th / 2, anchor="w", text=label,
                                      font=(FONT, fs(10, k, 8.5)), fill=TEXT)
            else:
                P.tint_icon(icon, tx0 + tw / 2, ty0 + th * 0.38, 21 * k, tint, square=True, size=20 * k)
                lt = self.create_text(tx0 + tw / 2, ty0 + th * 0.76, anchor="center", text=label,
                                      font=(FONT, fs(10, k, 8.5)), fill=TEXT,
                                      width=tw - 16 * k, justify="center")   # 긴 이름은 두 줄로
            self.add_hit((tx0, ty0, tx0 + ww, ty0 + th), cmd,
                         (lambda t=lt: lambda v: self.itemconfigure(t, fill=PRIMARY_D if v else TEXT))())

        # ---- 오른쪽: 최근 작성 문서 ----
        p2y0 = p1y1 + gap
        p2y1 = h - m
        P.card(px0, p2y0, px1, p2y1, 18 * k)
        self.create_text(px0 + pad + 2 * k, p2y0 + 32 * k, anchor="w", text="최근 작성 문서",
                         font=(FONT, fs(14, k, 10), "bold"), fill=TEXT)
        if self.on_history:
            more = self.create_text(px1 - pad - 14 * k, p2y0 + 32 * k, anchor="e", text="전체보기",
                                    font=(FONT, fs(9.5, k, 8)), fill=SUB)
            P.icon("chevron", px1 - pad - 4 * k, p2y0 + 32 * k, 9 * k, SUB)
            mb = self.bbox(more)
            self.add_hit((mb[0] - 4 * k, mb[1] - 6 * k, px1 - pad + 4 * k, mb[3] + 6 * k), self.on_history,
                         lambda v: self.itemconfigure(more, fill=PRIMARY_D if v else SUB))
        ry = p2y0 + 58 * k
        rh, rg = 70 * k, 8 * k
        fit = max(0, int((p2y1 - pad + rg - ry) // (rh + rg)))
        if not rows:
            self.create_text((px0 + px1) / 2, (ry + p2y1) / 2, anchor="center", justify="center",
                             text="아직 작성한 문서가 없습니다.\n공문을 작성하면 여기에 보입니다.",
                             font=(FONT, fs(10, k, 8.5)), fill=MUTED)
        chars = max(8, int((rw - 120 * k) / (11 * k)))
        for r in rows[:fit]:
            rx = px0 + pad - 6 * k
            P.rrect(rx, ry, px1 - pad + 6 * k, ry + rh, 12 * k, SIDEBAR, outline=BORDER)
            ok = is_done(r)
            P.tint_icon("page", rx + 30 * k, ry + rh / 2, 18 * k, "blue" if ok else "red", square=True,
                        size=16 * k)
            title = (r.get("제목") or r.get("서식") or "").strip() or "(제목 없음)"
            self.create_text(rx + 58 * k, ry + rh / 2 - 11 * k, anchor="w", text=ellipsize(title, chars),
                             font=(FONT, fs(10.5, k, 8.5), "bold"), fill=TEXT)
            self.create_text(rx + 58 * k, ry + rh / 2 + 12 * k, anchor="w",
                             text=_fmt_time(r.get("시각", "")) + ("" if ok else "  ·  실패"),
                             font=(FONT, fs(9, k, 8)), fill=SUB if ok else "#d14343")
            P.icon("more", px1 - pad - 14 * k, ry + rh / 2, 14 * k, SUB)
            if self.on_history:
                self.add_hit((rx, ry, px1 - pad + 6 * k, ry + rh), self.on_history)
            ry += rh + rg

        self._img = P.finish()
        self.create_image(0, 0, anchor="nw", image=self._img, tags="bg")
        self.tag_lower("bg")
        if self.query.get().strip():
            self._show_results()


HERO_COLORS = ui_kit.HERO      # 디자인에 따라 바뀐다
Landing = Home      # 예전 이름


# ======================================================================
#  서식 고르기
# ======================================================================
class Picker(tk.Frame):
    """서식 고르기 화면. 위에 제목·검색칸, 아래에 '매월 작성' / '기타 공문'(매주) 카드.
    show(분야, [(번호, 서식) …], 고른 번호)로 채운다. 서식을 누르면 on_pick(번호), '처음 화면'은 on_home()."""

    SECTIONS = (("매월", "매월 작성하는 공문", "MONTHLY"), ("수시", "기타 공문", "OTHERS"),
                ("매주", "매주 작성하는 공문", "WEEKLY"))     # 매주는 그런 서식이 있는 분야에만 보인다
    BUNDLES = ("갱신계약", "주택소유 정기", "임대조건 신고", "예비입주자 순위안내",     # 매월 작성 펼침 묶음 순서
               "예비입주자", "권리의무승계", "가정어린이집", "기타")                  # 기타 공문 펼침 묶음 순서
    LOOK = {"매월": ("history", "blue"), "수시": ("layers", "violet"), "매주": ("list", "teal")}

    MAX_FOUND = 60        # 비슷한 공문은 이만큼까지 보여 준다

    def __init__(self, parent, on_pick, on_home, logo_path: str = "", all_items=None, on_area=None):
        super().__init__(parent, bg=PAGE)
        self.on_pick, self.on_home = on_pick, on_home
        self.all_items = all_items or (lambda: list(self.items))   # () → [(번호, 서식) …] 모든 분야
        self.on_area = on_area              # 분야 탭을 누르면 on_area(분야) (앱의 지금 분야를 맞춘다)
        self.area, self.items, self.current = "", [], None
        self.opened: set = set()          # 펼친 묶음
        self.cv = tk.Canvas(self, highlightthickness=0, bd=0, bg=PAGE)
        self.ysb = ttk.Scrollbar(self, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=self.ysb.set)
        self.cv.pack(side="left", fill="both", expand=True)
        self._icons: list = []
        self.bind("<Configure>", lambda _e: self.draw())
        self.cv.bind("<Enter>", lambda _e: self.cv.bind_all("<MouseWheel>", self._wheel))
        self.cv.bind("<Leave>", lambda _e: self.cv.unbind_all("<MouseWheel>"))
        self.query = tk.StringVar()
        self.search, self.search_entry = _search_box(self.cv, self.query,
                                                     "모든 분야에서 비슷한 공문 찾기 (예: 승강기 점검)")
        self.query.trace_add("write", lambda *_: (self.cv.yview_moveto(0), self.draw()))
        self.search_entry.bind("<Return>", lambda _e: self._open_first())

    def show(self, area: str, items: list, current: int | None = None, query: str = ""):
        self.area, self.items, self.current = area, items, current
        self.query.set(query)
        cur = next((t for n, t in items if n == current), None)
        if cur is not None:
            self.opened.add(self._bundle(cur))       # 고른 서식이 있는 묶음은 펼쳐 둔다
        self.cv.yview_moveto(0)
        self.draw()

    @staticmethod
    def _bundle(t) -> str:
        return t.bundle or t.group

    def _bundle_rank(self, t) -> tuple:
        b = self._bundle(t)
        rank = (self.BUNDLES.index(b), "") if b in self.BUNDLES else (len(self.BUNDLES), b)
        return rank + (t.sort_key,)

    def _toggle(self, bundle: str):
        self.opened ^= {bundle}
        self.draw()

    def _wheel(self, e):
        top, bottom = self.cv.yview()
        if top > 0 or bottom < 1:
            self.cv.yview_scroll(int(-e.delta / 120), "units")

    @staticmethod
    def _match(t, q: str) -> bool:
        return match(t, q)

    def found(self) -> list:
        """검색어와 비슷한 공문(모든 분야) [(번호, 서식, 점수, 맞은 곳, 미리보기) …]."""
        import similar
        q = self.query.get().strip()
        return similar.search(self.all_items(), q, self.MAX_FOUND) if q else []

    def _open_first(self):
        f = self.found()
        if f:
            self.on_pick(f[0][0])

    def _choose(self, area: str):
        """분야 탭: 그 분야 서식으로 바꾼다(검색어는 지운다)."""
        self.area = area
        self.items = [(n, t) for n, t in self.all_items() if t.area == area]
        if self.current is not None and all(n != self.current for n, _ in self.items):
            self.current = None
        if self.on_area:
            self.on_area(area)
        self.query.set("")          # → 다시 그림
        self.cv.yview_moveto(0)
        self.draw()

    def _chip(self, cv, x, y, text, on, k, command) -> float:
        """분야 탭 알약 단추. 끝난 x를 돌려준다."""
        from tkinter import font as tkfont
        f = (FONT, _fs(10.5, k, 9), "bold" if on else "normal")
        tw = tkfont.Font(self, family=f[0], size=f[1], weight=f[2]).measure(text)
        w, h = tw + 34 * k, 36 * k
        tag = f"chip_{abs(hash(text))}"
        base = PRIMARY if on else CARD
        pill = round_rect(cv, x, y - h / 2, x + w, y + h / 2, h / 2, fill=base,
                          outline=PRIMARY if on else BORDER, tags=tag)
        cv.create_text(x + w / 2, y, text=text, font=f, fill="#ffffff" if on else TEXT, tags=tag)

        def hover(v):
            if not on:
                cv.itemconfigure(pill, fill=HOVER_SOFT if v else CARD)
            cv.config(cursor="hand2" if v else "")
        cv.tag_bind(tag, "<Enter>", lambda _e: hover(True))
        cv.tag_bind(tag, "<Leave>", lambda _e: hover(False))
        cv.tag_bind(tag, "<Button-1>", lambda _e: command())
        return x + w

    def _icon_img(self, name, tint, k):
        """제목 옆 둥근 네모 아이콘 그림."""
        r = 20 * k
        P = Painter(int(r * 2 + 2), int(r * 2 + 2), PAGE)
        P.tint_icon(name, r + 1, r + 1, r, tint, square=True, size=18 * k)
        img = P.finish()
        self._icons.append(img)
        return img

    # ---------------- 그리기 ----------------
    def draw(self):
        w, h = max(self.winfo_width(), 600), max(self.winfo_height(), 420)
        k = max(0.75, min(w / 1120, h / 720))
        cv = self.cv
        cv.delete("all")
        self._icons = []
        cw = w
        mx = 36 * k
        _back_link(cv, cw - mx, 30 * k, "←  처음 화면", self.on_home, k)
        name = self.area or "공문"
        q = self.query.get().strip()
        found = self.found() if q else []
        shown = list(self.items)
        if q:
            sub = f"‘{q}’와 비슷한 공문 {len(found)}건  ·  모든 분야에서 찾았습니다  ·  Esc로 지우기"
        else:
            sub = f"분야를 고르고 작성할 서식을 누르세요  ·  {name} 서식 {len(self.items)}종"
        cv.create_image(mx, 62 * k, anchor="w", image=self._icon_img("edit", "blue", k))
        _draw_title(cv, mx + 54 * k, 74 * k, k, "새 공문 작성", "", sub)

        # 분야 탭(왼쪽) + 비슷한 공문 검색칸(오른쪽, 좁으면 아랫줄)
        counts: dict = {}
        for _, t in self.all_items():
            counts[t.area] = counts.get(t.area, 0) + 1
        ry = 134 * k
        x = mx
        for area, _ in AREAS:
            x = self._chip(cv, x, ry, f"{area}  {counts.get(area, 0)}", area == self.area and not q, k,
                           lambda a=area: self._choose(a)) + 10 * k
        sw = min(400 * k, cw * 0.42)
        sh = max(30, 42 * k)
        if x + 20 * k > cw - mx - sw:
            ry += 52 * k
            cv.create_window(mx, ry - sh / 2, anchor="nw", window=self.search, width=cw - mx * 2, height=sh)
        else:
            cv.create_window(cw - mx, ry - sh / 2, anchor="ne", window=self.search, width=sw, height=sh)

        top = ry + 44 * k
        if q:
            bottom = self._results(cv, mx, top, cw - mx * 2, found, k)
            total = max(h, bottom + 36 * k)
            cv.config(scrollregion=(0, 0, cw, total))
            if total > h + 1:
                self.ysb.pack(side="right", fill="y", before=self.cv)
            else:
                self.ysb.pack_forget()
            return
        two = cw >= 760 * k
        cgap = 24 * k
        col_w = (cw - mx * 2 - cgap) / 2 if two else cw - mx * 2
        bottom = top
        col_end = [top, top]
        sections = [s for s in self.SECTIONS if s[0] != "매주" or any(t.cycle == "매주" for _, t in self.items)]
        for i, (cycle, label, eng) in enumerate(sections):
            mine_all = [it for it in self.items if it[1].cycle == cycle]
            fold = any(t.bundle for _, t in mine_all)
            if fold:
                mine_all.sort(key=lambda it: self._bundle_rank(it[1]))
            nos = {n: j for j, (n, _) in enumerate(mine_all, 1)}
            mine = [(n, t) for n, t in shown if t.cycle == cycle]
            col = i % 2 if two else 0
            x = mx + col * (col_w + cgap)
            if two:
                y0 = col_end[col] + (cgap if i >= 2 else 0)
            else:
                y0 = top if i == 0 else bottom + cgap
            end = self._section(cv, x, y0, col_w, cycle, label, eng, mine, k, fold=fold, nos=nos)
            col_end[col] = end
            bottom = max(bottom, end)
        total = max(h, bottom + 36 * k)
        cv.config(scrollregion=(0, 0, cw, total))
        if total > h + 1:
            self.ysb.pack(side="right", fill="y", before=self.cv)
        else:
            self.ysb.pack_forget()

    def _section(self, cv, x, y, col_w, cycle, label, eng, items, k, fold=False, nos=None, searching=False) -> float:
        """흰 카드 안에 묶음 머리(아이콘 + 이름 + 수)와 서식 줄을 그린다. 끝난 y를 돌려준다."""
        y_top = y
        pad = 20 * k
        x_in = x + pad
        w_in = col_w - pad * 2
        icon, tint = self.LOOK.get(cycle, ("layers", "blue"))
        cv.create_image(x_in, y + pad + 18 * k, anchor="w", image=self._icon_img(icon, tint, k * 0.85))
        cv.create_text(x_in + 44 * k, y + pad + 10 * k, anchor="w", text=label,
                       font=(FONT, _fs(14, k, 10), "bold"), fill=TEXT)
        cv.create_text(x_in + 45 * k, y + pad + 31 * k, anchor="w", text=f"{eng}  ·  {len(items)}종",
                       font=(FONT, _fs(8.5, k, 7.5), "bold"), fill=TINTS[tint][1])
        y += pad + 62 * k
        if not items:
            cv.create_text(x_in, y, anchor="nw", text="찾는 서식이 없습니다" if searching else "없음",
                           font=(FONT, _fs(10, k, 9)), fill=MUTED)
            y += 30 * k
        elif fold:
            items = sorted(items, key=lambda it: self._bundle_rank(it[1]))
            bundles = list(dict.fromkeys(self._bundle(t) for _, t in items))
            for b in bundles:
                mine = [(n, t) for n, t in items if self._bundle(t) == b]
                opened = searching or b in self.opened or len(bundles) == 1   # 묶음이 하나뿐이면 펼쳐 둔다
                y = self._fold_head(cv, x_in, y, w_in, b, len(mine), opened, k)
                if opened:
                    y += 4 * k
                    for n, t in mine:
                        y = self._row(cv, x_in + 14 * k, y, w_in - 14 * k, n, t, k, no=f"{nos[n]:02d}")
                    y += 6 * k
        else:
            for n, t in items:
                y = self._row(cv, x_in, y, w_in, n, t, k, no=f"{nos[n]:02d}" if nos else None)
        y += pad - 6 * k
        card = round_rect(cv, x, y_top, x + col_w, y, 16 * k, fill=CARD, outline=BORDER)
        cv.tag_lower(card)
        return y

    WHERE = {"제목": ("제목 일치", "blue"), "분류": ("분류 일치", "violet"),
             "내용": ("내용 일치", "teal"), "비슷": ("이름 비슷", "amber")}

    def _results(self, cv, x, y, width, found, k) -> float:
        """비슷한 공문 카드: 분야 표시 · 서식 이름 · 맞은 곳 · 본문 미리보기. 끝난 y를 돌려준다."""
        y_top = y
        pad = 22 * k
        xi, wi = x + pad, width - pad * 2
        cv.create_image(xi, y + pad + 18 * k, anchor="w", image=self._icon_img("search", "blue", k * 0.85))
        cv.create_text(xi + 44 * k, y + pad + 10 * k, anchor="w", text="비슷한 공문",
                       font=(FONT, _fs(14, k, 10), "bold"), fill=TEXT)
        cv.create_text(xi + 45 * k, y + pad + 31 * k, anchor="w",
                       text="이름·제목이 맞는 서식이 먼저, 분류·내용이 비슷한 서식이 뒤에 나옵니다  ·  Enter로 첫 공문 열기",
                       font=(FONT, _fs(8.5, k, 7.5)), fill=SUB)
        y += pad + 62 * k
        if not found:
            cv.create_text(xi, y, anchor="nw", font=(FONT, _fs(10.5, k, 9)), fill=MUTED,
                           text="비슷한 공문이 없습니다. 낱말을 줄이거나 다른 말로 찾아 보세요 (예: 갱신, 관리비, 교육).")
            y += 34 * k
        for n, t, _s, where, snip in found:
            y = self._found_row(cv, xi, y, wi, n, t, where, snip, k)
        if len(found) >= self.MAX_FOUND:
            cv.create_text(xi, y + 6 * k, anchor="nw", font=(FONT, _fs(9, k, 8)), fill=MUTED,
                           text=f"비슷한 순서로 {self.MAX_FOUND}건까지만 보입니다 — 검색어를 더 넣어 주세요")
            y += 30 * k
        y += pad - 6 * k
        card = round_rect(cv, x, y_top, x + width, y, 16 * k, fill=CARD, outline=BORDER)
        cv.tag_lower(card)
        return y

    def _found_row(self, cv, x, y, w, n, t, where, snip, k) -> float:
        tag = f"found_{n}"
        y += 8 * k
        _icon, tint, _ = AREA_LOOK.get(t.area, ("layers", "blue", ""))
        soft, strong = TINTS[tint]
        bw = 74 * k
        badge = round_rect(cv, x + 4 * k, y, x + 4 * k + bw, y + 24 * k, 12 * k, fill=soft, outline="", tags=tag)
        cv.create_text(x + 4 * k + bw / 2, y + 12 * k, text=t.area, font=(FONT, _fs(8.5, k, 7.5), "bold"),
                       fill=strong, tags=tag)
        tx = x + bw + 20 * k
        wl, wt = self.WHERE.get(where, ("", "blue"))
        title = cv.create_text(tx, y + 12 * k, anchor="w", text=t.label, width=w - (tx - x) - 110 * k,
                               font=(FONT, _fs(11, k, 9.5), "bold"), fill=TEXT, tags=tag)
        if wl:
            cw_ = 82 * k
            round_rect(cv, x + w - 8 * k - cw_, y + 1 * k, x + w - 8 * k, y + 23 * k, 11 * k,
                       fill=TINTS[wt][0], outline="", tags=tag)
            cv.create_text(x + w - 8 * k - cw_ / 2, y + 12 * k, text=wl, font=(FONT, _fs(8, k, 7)),
                           fill=TINTS[wt][1], tags=tag)
        yy = cv.bbox(title)[3] + 4 * k
        cyc = {"매월": "매월 작성", "매주": "매주 작성"}.get(t.cycle, "기타 공문")
        cv.create_text(tx, yy, anchor="nw", text=f"{cyc}  ·  {t.bundle or t.group}", tags=tag,
                       font=(FONT, _fs(9, k, 8)), fill=SUB)
        yy += 22 * k
        if snip:
            s = cv.create_text(tx, yy, anchor="nw", text=f"“{ellipsize(snip, 90)}”", width=w - (tx - x) - 20 * k,
                               font=(FONT, _fs(9, k, 8)), fill=MUTED, tags=tag)
            yy = cv.bbox(s)[3] + 2 * k
        y2 = yy + 10 * k
        hit = round_rect(cv, x - 8 * k, y - 8 * k, x + w + 8 * k, y2 - 2 * k, 10 * k, fill=CARD, outline="",
                         tags=tag)
        cv.tag_lower(hit, badge)
        cv.create_line(x, y2 + 1, x + w, y2 + 1, fill=LINE)

        def hover(on: bool):
            cv.itemconfigure(hit, fill=HOVER_SOFT if on else CARD)
            cv.itemconfigure(title, fill=PRIMARY_D if on else TEXT)
            cv.config(cursor="hand2" if on else "")
        cv.tag_bind(tag, "<Enter>", lambda _e: hover(True))
        cv.tag_bind(tag, "<Leave>", lambda _e: hover(False))
        cv.tag_bind(tag, "<Button-1>", lambda _e: self.on_pick(n))
        return y2 + 4 * k

    def _row(self, cv, x, y, col_w, n, t, k, no=None) -> float:
        tag = f"tpl_{n}"
        file_no, _, name = t.label.partition(". ")
        no = no or file_no
        picked = n == self.current
        color = PRIMARY_D if picked else TEXT
        y += 6 * k
        num = cv.create_text(x + 6 * k, y, anchor="nw", text=no if name else "",
                             font=(FONT, _fs(10.5, k, 9), "bold"), fill=PRIMARY if picked else MUTED, tags=tag)
        title = cv.create_text(x + 38 * k, y, anchor="nw", text=name or t.label, width=col_w - 46 * k,
                               font=(FONT, _fs(11, k, 9.5), "bold" if picked else "normal"), fill=color, tags=tag)
        y2 = cv.bbox(title)[3] + 9 * k
        hit = round_rect(cv, x - 2 * k, y - 7 * k, x + col_w, y2 - 3 * k, 8 * k,
                         fill=PRIMARY_SOFT if picked else CARD, outline="", tags=tag)
        cv.tag_lower(hit, num)          # 줄 바탕은 글자 아래로

        def hover(on: bool):
            if not picked:
                cv.itemconfigure(hit, fill=HOVER_SOFT if on else CARD)
            cv.itemconfigure(title, fill=PRIMARY_D if on or picked else TEXT)
            cv.config(cursor="hand2" if on else "")
        cv.tag_bind(tag, "<Enter>", lambda _e: hover(True))
        cv.tag_bind(tag, "<Leave>", lambda _e: hover(False))
        cv.tag_bind(tag, "<Button-1>", lambda _e: self.on_pick(n))
        return y2

    def _fold_head(self, cv, x, y, col_w, name, count, opened, k) -> float:
        """펼침 묶음 머리: ▸/▾ + 이름 + 서식 수. 누르면 펼치거나 접는다."""
        tag = f"fold_{abs(hash(name))}"      # 태그에 띄어쓰기가 있으면 Tk가 둘로 쪼개 클릭이 안 먹는다
        hh = 40 * k
        hit = round_rect(cv, x - 4 * k, y, x + col_w, y + hh, 10 * k, fill=HOVER_SOFT if opened else SIDEBAR,
                         outline="", tags=tag)
        cv.create_text(x + 10 * k, y + hh / 2, anchor="w", text="▾" if opened else "▸",
                       font=(FONT, _fs(11, k, 9)), fill=PRIMARY, tags=tag)
        title = cv.create_text(x + 30 * k, y + hh / 2, anchor="w", text=name,
                               font=(FONT, _fs(11.5, k, 9.5), "bold"),
                               fill=PRIMARY_D if opened else TEXT, tags=tag)
        cv.create_text(x + col_w - 12 * k, y + hh / 2, anchor="e", text=f"서식 {count}",
                       font=(FONT, _fs(9, k, 8)), fill=SUB, tags=tag)

        def hover(on: bool):
            cv.itemconfigure(title, fill=PRIMARY_D if on or opened else TEXT)
            cv.itemconfigure(hit, fill=HOVER_SOFT if on else (HOVER_SOFT if opened else SIDEBAR))
            cv.config(cursor="hand2" if on else "")
        cv.tag_bind(tag, "<Enter>", lambda _e: hover(True))
        cv.tag_bind(tag, "<Leave>", lambda _e: hover(False))
        cv.tag_bind(tag, "<Button-1>", lambda _e: self._toggle(name))
        return y + hh + 6 * k


# ======================================================================
#  기본정보
# ======================================================================
class InfoScreen(tk.Frame):
    """기본정보 화면. 서식을 고른 뒤 공문 작성 전에 관리소 정보·홈넷 계정을 확인·입력한다.
    show(서식 이름, 값)으로 채우고, [시작하기]는 on_done(값), '서식 다시 고르기'는 on_back()."""

    INFO = (("단지명", "단지명", "예: 광주우산3 (관리소명·약칭은 자동)"),
            ("담당자", "담당자 이름", "예: 홍길동"),
            ("전화번호", "담당자 전화번호", "예: 031-000-0000"),
            ("임대유형", "공급유형", "계약특수조건 조항을 유형에 맞춰 넣습니다"))
    ACCOUNT = (("homnet_id", "홈넷 아이디(사번)", "자동 작성 때 홈넷 로그인에 씁니다"),
               ("homnet_pw", "홈넷 비밀번호", "이 PC에만 암호화해 저장합니다"))
    REQUIRED = ("단지명", "담당자")

    def __init__(self, parent, on_done, on_back, logo_path: str = ""):
        super().__init__(parent, bg=PAGE)
        self.on_done, self.on_back = on_done, on_back
        self.label = ""
        self._icons: list = []
        self.cv = tk.Canvas(self, highlightthickness=0, bd=0, bg=PAGE)
        self.cv.pack(side="left", fill="both", expand=True)
        self.entries: dict[str, tk.Entry] = {}
        for key, _, _ in self.INFO + self.ACCOUNT:
            if key == "임대유형":     # 고르는 칸
                cb = ttk.Combobox(self.cv, values=RENT_TYPES, state="readonly", font=(FONT, 11))
                cb.bind("<<ComboboxSelected>>", lambda _e: self.msg.set(""))
                self.entries[key] = cb
                continue
            e = tk.Entry(self.cv, relief="flat", bd=0, insertbackground=TEXT, highlightthickness=1,
                         font=(FONT, 11), show="●" if key == "homnet_pw" else "")
            keep_colors(e, bg=SIDEBAR, fg=TEXT, highlightbackground=BORDER, highlightcolor=PRIMARY)
            e.bind("<Return>", lambda _e: self._done())
            e.bind("<KeyRelease>", lambda _e: self.msg.set(""))
            self.entries[key] = e
        self.start = tk.Label(self.cv, text="시작하기  ▶", bg=PRIMARY, fg="white", font=(FONT, 12, "bold"),
                              padx=30, pady=10, cursor="hand2")
        self.start.bind("<Button-1>", lambda _e: self._done())
        self.start.bind("<Enter>", lambda _e: self.start.config(bg=PRIMARY_D))
        self.start.bind("<Leave>", lambda _e: self.start.config(bg=PRIMARY))
        self.msg = tk.StringVar()
        self.msg_label = tk.Label(self.cv, textvariable=self.msg, bg=PAGE, fg="#c0392b", font=(FONT, 9))
        self.bind("<Configure>", lambda _e: self.draw())

    def show(self, label: str, values: dict):
        self.label = label
        for key, e in self.entries.items():
            if isinstance(e, ttk.Combobox):
                e.set(normalize_rent_type(values.get(key)))
                continue
            e.delete(0, "end")
            e.insert(0, values.get(key, "") or "")
        self.msg.set("")
        self.draw()
        first = next((k for k in self.REQUIRED if not self.entries[k].get().strip()), None)
        (self.entries[first] if first else self.start).focus_set()

    def values(self) -> dict:
        return {k: e.get().strip() if k != "homnet_pw" else e.get() for k, e in self.entries.items()}

    def _done(self):
        v = self.values()
        missing = [lb for k, lb, _ in self.INFO if k in self.REQUIRED and not v[k]]
        if missing:
            self.msg.set(f"⚠ {', '.join(missing)} 칸을 채워 주세요.")
            return
        self.on_done(v)

    def _icon_img(self, name, tint, k):
        r = 20 * k
        P = Painter(int(r * 2 + 2), int(r * 2 + 2), CARD)
        P.tint_icon(name, r + 1, r + 1, r, tint, square=True, size=18 * k)
        img = P.finish()
        self._icons.append(img)
        return img

    # ---------------- 그리기 ----------------
    def draw(self):
        w, h = max(self.winfo_width(), 600), max(self.winfo_height(), 420)
        k = max(0.75, min(w / 1120, h / 720))
        cv = self.cv
        cv.delete("all")
        self._icons = []
        cw = w
        mx = 36 * k
        _back_link(cv, cw - mx, 30 * k, "←  서식 다시 고르기", self.on_back, k)
        sub = "공문의 빈칸에 들어갈 기본정보를 확인해 주세요" + (f"  ·  {self.label}" if self.label else "")
        _draw_title(cv, mx, 74 * k, k, "기", "본정보", sub)

        top = 140 * k
        two = cw >= 760 * k
        cgap = 24 * k
        col_w = (cw - mx * 2 - cgap) / 2 if two else cw - mx * 2
        pad = 24 * k
        ent_w = min(col_w - pad * 2, 380 * k)
        bottom = top
        sections = (("우리 관리소 정보", "공문 빈칸에 자동으로 들어갑니다", self.INFO, "building", "blue"),
                    ("홈넷 계정", "VPN 계정은 단지기본정보에서 넣습니다", self.ACCOUNT, "person", "violet"))
        for i, (title, note, fields, icon, tint) in enumerate(sections):
            x = mx + (i * (col_w + cgap) if two else 0)
            y = top if two or i == 0 else bottom + cgap
            y_top = y
            xi = x + pad
            cv.create_image(xi, y + pad + 18 * k, anchor="w", image=self._icon_img(icon, tint, k * 0.85))
            cv.create_text(xi + 44 * k, y + pad + 9 * k, anchor="w", text=title,
                           font=(FONT, _fs(14, k, 10), "bold"), fill=TEXT)
            cv.create_text(xi + 45 * k, y + pad + 30 * k, anchor="w", text=note,
                           font=(FONT, _fs(9, k, 8)), fill=SUB)
            y += pad + 66 * k
            for key, label, hint in fields:
                star = " *" if key in self.REQUIRED else ""
                cv.create_text(xi, y, anchor="nw", text=label + star, font=(FONT, _fs(10, k, 9), "bold"),
                               fill=TEXT)
                cv.create_text(xi + ent_w, y + 1 * k, anchor="ne", text=hint, font=(FONT, _fs(8, k, 8)),
                               fill=MUTED)
                cv.create_window(xi, y + 22 * k, anchor="nw", window=self.entries[key],
                                 width=ent_w, height=max(28, round(36 * k)))
                y += 72 * k
            y += pad - 14 * k
            card = round_rect(cv, x, y_top, x + col_w, y, 16 * k, fill=CARD, outline=BORDER)
            cv.tag_lower(card)
            bottom = max(bottom, y)

        by = max(bottom + 20 * k, h - 76 * k)
        cv.create_window(cw - mx, by, anchor="ne", window=self.start)
        cv.create_window(mx, by + 12 * k, anchor="nw", window=self.msg_label)
        cv.config(scrollregion=(0, 0, cw, max(h, by + 60 * k)))


# ======================================================================
#  작성 이력
# ======================================================================
class HistoryScreen(tk.Frame):
    """작성 이력 목록. show([행 …])로 채운다. on_folder()는 기록 폴더 열기, on_home()은 처음 화면."""

    COLS = (("시각", "작성 시각", 150), ("서식", "서식", 260), ("제목", "제목", 360),
            ("수신자", "수신자", 160), ("상태", "상태", 150))

    def __init__(self, parent, on_home, on_folder=None):
        super().__init__(parent, bg=PAGE)
        self.on_home, self.on_folder = on_home, on_folder
        self.head = tk.Canvas(self, highlightthickness=0, bd=0, bg=PAGE, height=120)
        self.head.pack(fill="x")
        body = tk.Frame(self, bg=BORDER)
        body.pack(fill="both", expand=True, padx=36, pady=(0, 28))
        inner = tk.Frame(body, bg=CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        bar = tk.Frame(inner, bg=CARD)
        bar.pack(fill="x", padx=18, pady=(14, 8))
        self.count = tk.Label(bar, text="", bg=CARD, fg=SUB, font=(FONT, 10))
        self.count.pack(side="left")
        if on_folder:
            b = tk.Label(bar, text="기록 폴더 열기", bg=PRIMARY_SOFT, fg=PRIMARY_D, font=(FONT, 10, "bold"),
                         padx=14, pady=5, cursor="hand2")
            b.pack(side="right")
            b.bind("<Button-1>", lambda _e: on_folder())
            b.bind("<Enter>", lambda _e: b.config(bg=PRIMARY_SOFT))
            b.bind("<Leave>", lambda _e: b.config(bg=PRIMARY_SOFT))
        tf = tk.Frame(inner, bg=CARD)
        tf.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        dpi = max(1.0, self.winfo_fpixels("1i") / 96)       # 화면 배율(150% 등)만큼 칸을 넓힌다
        st = ttk.Style(self)
        st.configure("History.Treeview", rowheight=int(32 * dpi), font=(FONT, 10), foreground=TEXT,
                     background=CARD, fieldbackground=CARD)
        st.configure("History.Treeview.Heading", font=(FONT, 10, "bold"), foreground=SUB)
        st.map("History.Treeview", background=[("selected", PRIMARY_SOFT)], foreground=[("selected", TEXT)])
        self.tree = ttk.Treeview(tf, columns=[c for c, _, _ in self.COLS], show="headings",
                                 style="History.Treeview")
        for c, label, width in self.COLS:
            self.tree.heading(c, text=label, anchor="w")
            self.tree.column(c, width=int(width * dpi), minwidth=int(width * dpi * 0.7), anchor="w",
                             stretch=c in ("제목", "서식"))
        ysb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.tag_configure("fail", foreground="#d14343")
        self.tree.tag_configure("empty", foreground=MUTED)
        self.head.bind("<Configure>", lambda _e: self._draw_head())
        self.rows: list = []

    def _draw_head(self):
        cv = self.head
        cv.delete("all")
        w = max(cv.winfo_width(), 600)
        k = max(0.75, min(w / 1120, 1.4))
        _back_link(cv, w - 36, 30 * k, "←  처음 화면", self.on_home, k)
        _draw_title(cv, 36, 74 * k, k, "작", "성 이력",
                    "홈넷에 자동 작성한 공문 기록 중 최근 한 달치입니다 (logs\\작성이력_년월.csv)")
        cv.config(height=int(112 * k))

    def show(self, rows: list):
        self.rows = rows
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            vals = [(_fmt_time(r.get(c, "")) if c == "시각" else (r.get(c) or "")) for c, _, _ in self.COLS]
            self.tree.insert("", "end", values=vals, tags=() if is_done(r) else ("fail",))
        done = sum(1 for r in rows if is_done(r))
        self.count.config(text=f"전체 {len(rows)}건  ·  완료 {done}건  ·  실패 {len(rows) - done}건")
        if not rows:
            self.tree.insert("", "end", values=("", "", "아직 작성한 문서가 없습니다 — [홈넷에 자동 작성]을 하면 "
                                                        "여기에 기록됩니다.", "", ""), tags=("empty",))
        self._draw_head()
