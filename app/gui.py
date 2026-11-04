"""공문 작성기 — 서식을 고르고 이름·날짜만 넣으면 홈넷 표준기안문으로 작성한다.

① 계정·기본정보: VPN·홈넷 계정, 관리소 정보, 결재정보 기본값 (처음 한 번)
② 공문 작성: 서식 선택 → 받는 분 이름·날짜 입력 → [홈넷에 자동 작성]
상신(결재올림)은 사람이 직접 누른다.
"""
import csv
import datetime as dt
import os
import queue
import re
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, scrolledtext, ttk

import complex_info
import doc_template as dtpl
import homnet
import homnet_draft
import paths
import roster
import settings_store
import ui_kit

VERSION = "1.3.0"
FONT = ("맑은 고딕", 10)
FONT_B = ("맑은 고딕", 10, "bold")
ACCENT = ui_kit.PRIMARY_D   # 새 디자인: 파랑 계열(진한 쪽)
ORANGE = ui_kit.PRIMARY     # 단추·제목 색(예전 이름 그대로)
BROWN, SUB = ui_kit.TEXT, ui_kit.SUB   # 본문 글자, 설명 글자
LINE = ui_kit.LINE          # 옅은 구분선
SELECT_BG = ui_kit.PRIMARY_SOFT       # 목록에서 고른 줄
LINK_KEYS = ("문서링크", "심사결과링크", "소명안내링크")   # 자동 작성 때 홈넷 [문서링크]로 채우는 칸
TEXT_OPTS = dict(bg="white", relief="flat", borderwidth=0, highlightthickness=1,
                 highlightbackground="#e0e0e0", highlightcolor=ACCENT, padx=6, pady=4)
INFO_FIELDS = [("관리소", "관리소명", "예: 가나관리소 (문서번호 앞에 붙는 이름)"),
               ("단지명", "단지명", "예: 가나1단지"),
               ("담당자", "담당자 이름", "예: 홍길동"),
               ("전화번호", "담당자 전화번호", "예: 031-000-0000")]


def apply_theme(root: tk.Tk) -> ttk.Style:
    """윈도11 느낌의 Sun Valley 밝은 테마. 없으면 기본 테마로 그냥 진행."""
    try:
        import sv_ttk
        sv_ttk.set_theme("light", root)
        from tkinter import font as tkfont
        for name in tkfont.names(root):
            if name.startswith("SunValley"):
                tkfont.nametofont(name, root).configure(family="맑은 고딕")
    except Exception:
        pass
    style = ttk.Style(root)
    bg = style.lookup("TFrame", "background") or "#fafafa"
    root.configure(bg=bg)
    root.option_add("*Toplevel.background", bg)
    return style


def default_date(label: str, today: dt.date) -> dt.date:
    return today + dt.timedelta(days=14) if "기한" in label else today


def month_end(d: dt.date) -> dt.date:
    nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return nxt - dt.timedelta(days=1)


def auto_date_rule(label: str, fields: dict):
    """입력칸 없이 자동으로 정하는 날짜면 계산 함수(dates, today) → date, 아니면 None.
    - 만료일·계약체결기한: 같은 공문에 갱신월이 있으면 그 달의 말일
    - 대상세대 갱신월: 같은 공문에 검색월이 있으면 그 13개월 전 달(입주자 정기검색)
    - 재임대월: 같은 공문에 갱신월이 있으면 그 2개월 전 달(임대조건 신고: 재임대 9월·갱신 11월)
    - 안내문시행일: 작성일(오늘)"""
    if label in ("만료일", "계약체결기한") and "갱신월" in fields:
        return lambda dates, today: month_end(dates["갱신월"]) if dates.get("갱신월") else None
    if label == "재임대월" and "갱신월" in fields:
        return lambda dates, today: months_before(dates["갱신월"], 2) if dates.get("갱신월") else None
    if label == "대상세대 갱신월" and "검색월" in fields:
        return lambda dates, today: months_before(dates["검색월"], 13) if dates.get("검색월") else None
    if label == "안내문시행일":
        return lambda dates, today: today
    return None


AUTO_DATE_NOTES = {"안내문시행일": "작성일", "대상세대 갱신월": "검색월 13개월 전",
                   "재임대월": "갱신월 2개월 전"}   # 나머지는 갱신월 말일
DATE_MONTH_AUTO = ("대상세대 갱신월", "재임대월")     # 달만 보이는 자동 날짜


def saved_geometry(geo: str, sw: int, sh: int) -> str:
    """지난번 창 크기·위치('가로x세로+x+y'). 지금 화면 안에 들어오지 않으면 ''(기본 크기로)."""
    m = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", geo or "")
    if not m:
        return ""
    w, h, x, y = map(int, m.groups())
    if w < 400 or h < 300 or w > sw or h > sh or x < -20 or y < -20 or x + w > sw + 20 or y + h > sh + 20:
        return ""
    return geo


def months_before(d: dt.date, n: int) -> dt.date:
    """n개월 전 달의 1일."""
    k = d.year * 12 + d.month - 1 - n
    return dt.date(k // 12, k % 12 + 1, 1)


def is_month_field(label: str, style: str) -> bool:
    """'갱신월'처럼 달만 고르는 칸(형식 월·월만·년월), 관리업무 서식의 달 형식('26년 11월 등)."""
    return (label.endswith("월") and style in ("월", "월만", "년월")) or style in dtpl.MONTH_STYLES


class MonthEntry(ttk.Frame):
    """연·월만 고르는 칸. get_date()는 그 달 1일."""

    def __init__(self, parent, command=None):
        super().__init__(parent)
        today = dt.date.today()
        self.year = tk.StringVar(value=str(today.year))
        self.month = tk.StringVar(value=str(today.month))
        ys = ttk.Spinbox(self, from_=today.year - 5, to=today.year + 5, width=6,
                         textvariable=self.year, command=command, state="readonly")
        ys.pack(side="left")
        ttk.Label(self, text="년").pack(side="left", padx=(2, 6))
        ms = ttk.Combobox(self, values=[str(m) for m in range(1, 13)], width=4,
                          textvariable=self.month, state="readonly")
        ms.pack(side="left")
        ttk.Label(self, text="월").pack(side="left", padx=2)
        if command:
            ms.bind("<<ComboboxSelected>>", lambda _e: command())

    def get_date(self) -> dt.date:
        return dt.date(int(self.year.get()), int(self.month.get()), 1)

    def set_date(self, d: dt.date) -> None:
        self.year.set(str(d.year))
        self.month.set(str(d.month))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.driver = None
        self.cfg = settings_store.load()
        dtpl.set_complex(complex_info.resolve(self.cfg.get("complex_info", {})))   # 서식의 {단지:…} 칸
        self.templates: list[dtpl.Template] = []
        self.current: dtpl.Template | None = None
        self.date_widgets: dict[str, object] = {}
        self.edit_mode = False
        self.roster: list[roster.Person] = []
        self.roster_path = ""
        self.roster_tree = None
        self.upload_path = ""      # 홈넷 수신자 [업로드]에 올릴 엑셀 (저장하지 않음 — 잘못 보내지 않도록)
        self.upload_count: int | None = None   # 그 엑셀의 수신자 수 → 서식의 {세대수}
        self.first_docs: dict[str, dtpl.Template] = {}   # 서식\1안 폴더의 내부결재 서식 (이름 → 서식)
        self.with_first: dict[str, bool] = {}            # 서식별 '1안 함께 작성' 선택 (이번 실행 동안)
        self.option_docs: dict[str, dtpl.Template] = {}  # 서식\선택안 폴더 (이름 → 서식)
        self.option_pick: dict[str, list] = {}           # 서식별로 체크한 선택안 (이번 실행 동안)
        self.option_uploads: dict[str, str] = {}         # 선택안별 수신자 엑셀 (저장하지 않음)
        self.option_counts: dict[str, int | None] = {}
        self.option_vars: dict[str, tk.BooleanVar] = {}
        self.none_checked: dict[str, bool] = {}          # 서식별 '없음표시'(예: 소명대상 없음) 체크 (이번 실행 동안)
        self.area = "임대"                              # 시작 화면에서 고른 분야

        root.title(f"공문 작성기 — 홈넷 표준기안문 자동 작성 v{VERSION}")
        try:
            root.iconbitmap(default=os.path.join(paths.bundle_dir(), "assets", "app.ico"))
        except tk.TclError:
            pass
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.k = k = max(1.0, root.winfo_fpixels("1i") / 96)
        # 창 모드: 화면을 꽉 채우지 않고 화면의 80% 안쪽 크기로 가운데에 띄운다(크기 조절·최대화 가능)
        w, h = min(int(1400 * k), int(sw * 0.85)), min(int(860 * k), int(sh * 0.85))   # 왼쪽 메뉴만큼 넓게
        root.minsize(min(int(1080 * k), w), min(int(620 * k), h))
        root.geometry(saved_geometry(self.cfg.get("window", ""), sw, sh)
                      or f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        root.state("normal")
        root.bind("<F11>", lambda _e: self._toggle_maximize())
        style = apply_theme(root)
        for name in ("TLabel", "TButton", "TRadiobutton", "TCheckbutton", "TEntry", "TCombobox"):
            style.configure(name, font=FONT)
        root.option_add("*TEntry.font", FONT)
        root.option_add("*TCombobox.font", FONT)
        style.configure("TLabelframe.Label", font=FONT_B, foreground=BROWN)
        style.configure("TNotebook.Tab", font=FONT_B, padding=(16, 6))
        # 탭 머리는 감춘다: 기본정보 화면 → 공문 작성 화면만 보이고, 계정·결재정보는 [파일] 메뉴에서 연다
        style.layout("Plain.TNotebook.Tab", [])
        style.configure("Treeview", font=FONT, rowheight=int(26 * k), foreground=BROWN)
        style.map("Treeview", background=[("selected", SELECT_BG)], foreground=[("selected", BROWN)])
        style.configure("Accent.TButton", font=FONT_B, padding=(14, 6))
        style.configure("Big.Accent.TButton", font=("맑은 고딕", 11, "bold"), padding=(18, 8))
        style.configure("Warn.TLabel", foreground="#b45309")

        self._build_menu()
        # 새 디자인: 왼쪽 메뉴 + 오른쪽 본문(처음 화면·서식 고르기·기본정보·작성 이력은 본문을 덮는다)
        import landing
        self.sidebar = landing.Sidebar(root, {"home": self._go_home, "write": self._show_write,
                                              "picker": self._show_picker, "history": self._show_history,
                                              "settings": self._show_settings},
                                       self.k, VERSION, profile=self._profile, on_profile=self._show_settings)
        self.sidebar.pack(side="left", fill="y")
        self.main = tk.Frame(root, bg=style.lookup("TFrame", "background") or "#fafafa")
        self.main.pack(side="left", fill="both", expand=True)
        self._build_header()
        self._build_log()
        style.configure("Plain.TNotebook", borderwidth=0)
        self.nb = ttk.Notebook(self.main, style="Plain.TNotebook")
        self.nb.pack(fill="both", expand=True, padx=12, pady=(10, 4))
        self._build_tab_account()
        self._build_tab_write()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(100, self._drain)
        last_roster = self.cfg.get("roster_path", "")
        if last_roster and os.path.isfile(last_roster):   # 지난번 명단을 다시 불러 둔다
            self._load_roster(last_roster, quiet=True)
        self._load_templates()
        # 처음 쓰는 사람은 계정·기본정보부터, 이미 입력했으면 바로 공문 작성으로
        if self.cfg.get("담당자") and self.cfg.get("단지명"):
            self.nb.select(1)
        # 시작 화면(대시보드)을 맨 위에 덮는다
        logo = os.path.join(paths.bundle_dir(), "assets", "logo.png")
        shortcuts = (("단지기본정보", "building", "blue", self._show_complex),
                     ("서식 폴더 열기", "folder", "amber", lambda: os.startfile(paths.template_dir())),
                     ("명단 불러오기", "people", "green", self._pick_roster),
                     ("사용 방법", "help", "violet", self._show_help))
        self.landing = landing.Landing(self.main, self._enter_area, logo, VERSION, self._area_counts(),
                                       on_pick=self._pick_from_home,
                                       items=lambda: list(enumerate(self.templates)),
                                       on_new=self._show_picker, shortcuts=shortcuts,
                                       history=self._history_rows, on_history=self._show_history,
                                       user=lambda: self._profile()[2],
                                       on_more=lambda q: self._show_picker(query=q))
        # 새 공문 작성(서식 고르기) 화면: 분야 탭 + 모든 분야에서 비슷한 공문 찾기
        self.picker = landing.Picker(self.main, self._pick_template, self._go_home, logo,
                                     all_items=lambda: list(enumerate(self.templates)), on_area=self._set_area)
        self.info_screen = landing.InfoScreen(self.main, self._info_done, self._show_picker, logo)   # 기본정보 화면
        self.history_screen = landing.HistoryScreen(self.main, self._go_home,
                                                    lambda: os.startfile(paths.sub_dir("logs")))
        self._go_home()

    # ================= 시작 화면 · 분야 =================
    def _area_counts(self) -> dict:
        counts: dict[str, int] = {}
        for t in self.templates:
            counts[t.area] = counts.get(t.area, 0) + 1
        return counts

    OVERLAYS = ("landing", "picker", "info_screen", "history_screen")

    def _hide_overlays(self, keep=None):
        for n in self.OVERLAYS:
            w = getattr(self, n, None)
            if w is not None and w is not keep:
                w.place_forget()

    def _cover(self, w):
        """본문(self.main)을 화면 w로 덮는다."""
        self._hide_overlays(keep=w)
        w.place(x=0, y=0, relwidth=1, relheight=1)
        tk.Misc.lift(w)      # Canvas.lift는 그림 요소용이라 창 자체를 올린다

    def _profile(self) -> tuple:
        """(관리소, 단지명, 담당자) — 왼쪽 메뉴 아래 카드와 인사말에 쓴다."""
        v = self._info_values() if hasattr(self, "info_entries") else {}
        return (v.get("관리소", "") or self.cfg.get("관리소", ""), v.get("단지명", "") or self.cfg.get("단지명", ""),
                v.get("담당자", "") or self.cfg.get("담당자", ""))

    def _history_rows(self) -> list:
        return ui_kit.read_history(paths.sub_dir("logs"))

    def _nav(self, key: str):
        if getattr(self, "sidebar", None) is not None:
            self.sidebar.set_active(key)
        if key == "write":
            self.header_title.config(text=f"공문 작성  ·  {self.area}")

    def _go_home(self):
        if self.edit_mode:
            self._toggle_edit()
        self.landing.set_counts(self._area_counts())
        self._cover(self.landing)
        self._nav("home")
        self.landing.focus_search()     # 처음 화면에서 바로 공문을 찾을 수 있게

    def _overlay_shown(self) -> bool:
        """처음 화면·서식 고르기·기본정보·작성 이력 화면이 공문 작성 화면을 덮고 있는지."""
        return any(w is not None and w.winfo_ismapped()
                   for w in (getattr(self, n, None) for n in self.OVERLAYS))

    def _show_write(self):
        """왼쪽 메뉴 [공문 작성]: 고른 서식이 있으면 작성 화면으로, 없으면 서식 고르기로."""
        if self.current is None:
            self._show_picker()
            return
        self._hide_overlays()
        self.nb.select(1)
        self._nav("write")
        self._refresh()

    def _show_history(self):
        self._cover(self.history_screen)
        self.history_screen.show(self._history_rows())
        self._nav("history")

    def _show_picker(self, query: str = ""):
        """새 공문 작성(서식 고르기) 화면을 덮는다: 분야 탭 + 지금 분야의 서식, query가 있으면 비슷한 공문."""
        if self.edit_mode:
            self._toggle_edit()
        items = [(i, t) for i, t in enumerate(self.templates) if t.area == self.area]
        cur = self.templates.index(self.current) if self.current in self.templates else None
        self.landing.query.set("")
        self._cover(self.picker)
        self._nav("picker")
        self.picker.show(self.area, items, cur, query=query)
        self.picker.search_entry.focus_set()
        if query:
            self.picker.search_entry.icursor("end")

    def _pick_template(self, i: int):
        """서식 고르기 화면에서 고른 서식을 열고, 기본정보 화면을 거쳐 ② 공문 작성 화면으로 간다."""
        self._hide_overlays()
        self._nav("write")
        self.search.set("")
        iid = str(i)
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)
        info = {**self._info_values(), "homnet_id": self.homnet_id.get().strip(), "homnet_pw": self.homnet_pw.get()}
        self._cover(self.info_screen)
        self.info_screen.show(self.templates[i].label if 0 <= i < len(self.templates) else "", info)

    def _info_done(self, values: dict):
        """기본정보 화면의 [시작하기]: ① 탭 입력칸에 옮기고 저장한 뒤 공문 작성 화면으로."""
        for key, e in list(self.info_entries.items()) + [("homnet_id", self.homnet_id), ("homnet_pw", self.homnet_pw)]:
            e.delete(0, "end")
            e.insert(0, values.get(key, ""))
        self._save_settings()
        self.info_screen.place_forget()
        self.nb.select(1)
        self._nav("write")
        self._refresh()

    def _pick_from_home(self, i: int):
        """처음 화면 검색 결과에서 고른 서식: 그 분야로 옮겨 바로 연다(분야·서식 고르기 화면을 건너뜀)."""
        if not 0 <= i < len(self.templates):
            return
        self.landing.query.set("")
        self.landing.place_forget()
        self._set_area(self.templates[i].area)
        self._pick_template(i)

    def _enter_area(self, area: str):
        n = self._area_counts().get(area, 0)
        if not n:
            messagebox.showinfo(area, f"'{area}' 서식은 아직 없습니다.\n\n"
                                      f"서식 txt 머리말에 '분야: {area}'를 적어 서식 폴더에 넣으면 "
                                      "여기에 나타납니다.", parent=self.root)
            return
        self._set_area(area)
        self._show_picker()

    def _set_area(self, area: str):
        self.area = area
        self.header_title.config(text=f"공문 작성  ·  {area}")
        self._fill_tree()
        if self.current is None or self.current.area != area:
            pick = next((i for i, t in enumerate(self.templates) if t.area == area), None)
            if pick is not None and self.tree.exists(str(pick)):
                self.tree.selection_set(str(pick))
                self.tree.see(str(pick))
        self.tree.yview_moveto(0)
        if self.tree.selection():
            self.tree.see(self.tree.selection()[0])

    # ================= 공통 =================
    def _build_menu(self):
        bar = tk.Menu(self.root)
        f = tk.Menu(bar, tearoff=0)
        f.add_command(label="처음 화면으로", command=lambda: self._go_home())
        f.add_command(label="창 최대화 / 원래 크기 (F11)", command=self._toggle_maximize)
        f.add_command(label="계정·결재정보 설정 (VPN·공개여부·편철)", command=self._show_settings)
        f.add_command(label="단지기본정보 (관리소명·평형·업체 — 월별·주별 서식)", command=self._show_complex)
        f.add_separator()
        f.add_command(label="서식 폴더 열기", command=lambda: os.startfile(paths.template_dir()))
        f.add_command(label="서식 다시 읽기", command=self._load_templates)
        f.add_command(label="수신인 명단(엑셀) 불러오기", command=self._pick_roster)
        f.add_separator()
        f.add_command(label="작업 기록 폴더 열기", command=lambda: os.startfile(paths.sub_dir("logs")))
        f.add_command(label="저장된 계정 지우기 (담당자가 바뀔 때)", command=self._clear_accounts)
        bar.add_cascade(label="파일", menu=f)
        hlp = tk.Menu(bar, tearoff=0)
        hlp.add_command(label="사용 방법", command=self._show_help)
        hlp.add_command(label="서식 만드는 법", command=self._show_template_help)
        bar.add_cascade(label="도움말", menu=hlp)
        self.root.config(menu=bar)

    def _build_header(self):
        """본문 위 머리: 화면 제목(굵게)과 설명, 오른쪽에 글자 단추."""
        bg = self.main.cget("bg")
        head = tk.Frame(self.main, bg=bg)
        head.pack(fill="x", padx=(16, 8), pady=(12, 0))
        right = tk.Frame(head, bg=bg)
        right.pack(side="right", padx=16)
        for text, cmd in (("←  뒤로가기", self._go_back), ("☰  서식 고르기", self._show_picker),
                          ("⌂  처음 화면", self._go_home)):
            self._text_button(right, text, cmd, bg=bg).pack(side="left", padx=(12, 0))
        mid = tk.Frame(head, bg=bg)
        mid.pack(side="left", padx=6, pady=6)
        self.header_title = tk.Label(mid, text="공문 작성", font=("맑은 고딕", 16, "bold"), bg=bg, fg=BROWN)
        self.header_title.pack(anchor="w")
        tk.Label(mid, text="이름·날짜를 넣고 확인한 뒤 [홈넷에 자동 작성]을 누르세요",
                 font=("맑은 고딕", 9), bg=bg, fg=SUB).pack(anchor="w")

    @staticmethod
    def _text_button(parent, text, command, bg="white"):
        """링크처럼 생긴 글자 단추(마우스를 올리면 파랑)."""
        b = tk.Label(parent, text=text, font=FONT, bg=bg, fg=BROWN, cursor="hand2", padx=4, pady=4)
        b.bind("<Button-1>", lambda _e: command())
        b.bind("<Enter>", lambda _e: b.config(fg=ACCENT))
        b.bind("<Leave>", lambda _e: b.config(fg=BROWN))
        return b

    @staticmethod
    def _orange_button(parent, text, command, big=False):
        """기본정보 화면의 [시작하기]와 같은 파란 단추(예전 이름 그대로)."""
        b = tk.Label(parent, text=text, bg=ORANGE, fg="white", cursor="hand2",
                     font=("맑은 고딕", 11 if big else 10, "bold"), padx=24 if big else 16, pady=9 if big else 5)
        b.bind("<Button-1>", lambda _e: command())
        b.bind("<Enter>", lambda _e: b.config(bg=ACCENT))
        b.bind("<Leave>", lambda _e: b.config(bg=ORANGE))
        return b

    def _show_settings(self):
        """계정·결재정보 설정(감춰 둔 ① 탭). [뒤로가기]나 [저장하고 다음]으로 공문 작성에 돌아온다."""
        self._hide_overlays()
        self.nb.select(0)
        self.header_title.config(text="환경 설정")
        self._nav("settings")

    def _go_back(self):
        """한 단계 뒤로: 설정 화면이면 공문 작성으로, 공문 작성이면 기본정보 화면으로."""
        if self.nb.index("current") == 0:
            if self.current is None:
                self._go_home()
                return
            self.nb.select(1)
            self.header_title.config(text=f"공문 작성  ·  {self.area}")
            self._nav("write")
        elif self.current is not None and self.current in self.templates:
            self._pick_template(self.templates.index(self.current))
        else:
            self._show_picker()

    def _build_log(self):
        f = ttk.LabelFrame(self.main, text="진행 상황")
        f.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
        self.log_box = scrolledtext.ScrolledText(f, height=5, wrap="word", font=("맑은 고딕", 9),
                                                 state="disabled", **TEXT_OPTS)
        self.log_box.pack(fill="both", expand=True, padx=4, pady=4)
        self.progress = ttk.Progressbar(f, mode="indeterminate")

    def log(self, msg: str):
        """어느 스레드에서든 호출 가능. 문제 진단을 위해 파일에도 남긴다."""
        self.q.put(("log", msg))
        self._log_file(msg)

    @staticmethod
    def _log_file(msg: str):
        try:
            path = os.path.join(paths.sub_dir("logs"), f"app_{dt.date.today():%Y%m%d}.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{dt.datetime.now():%H:%M:%S}] {msg}\n")
        except OSError:
            pass

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log_box.config(state="normal")
                    self.log_box.insert("end", f"[{dt.datetime.now():%H:%M:%S}] {payload}\n")
                    self.log_box.see("end")
                    self.log_box.config(state="disabled")
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def run_bg(self, work, on_ok=None, on_err=None):
        """work()를 작업 스레드에서 실행하고 결과를 메인 스레드 콜백으로 넘긴다."""
        if self.busy:
            messagebox.showinfo("진행 중", "다른 작업이 진행 중입니다. 잠시 기다려 주세요.")
            return
        self.busy = True
        self.root.config(cursor="watch")
        self.progress.pack(fill="x", padx=4, pady=(0, 4), before=self.log_box)
        self.progress.start(15)

        def runner():
            try:
                result = work()
            except Exception as ex:
                import traceback
                self.log(f"❌ {str(ex) or type(ex).__name__}")
                self._log_file(traceback.format_exc())
                self.q.put(("call", lambda ex=ex: self._done(on_err, ex)))
            else:
                self.q.put(("call", lambda r=result: self._done(on_ok, r)))

        threading.Thread(target=runner, daemon=True).start()

    def _done(self, cb, value):
        self.busy = False
        self.root.config(cursor="")
        self.progress.stop()
        self.progress.pack_forget()
        if cb:
            cb(value)

    def _row(self, parent, r, label, default="", secret=False, width=34, hint=""):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="e", padx=8, pady=3)
        e = ttk.Entry(parent, width=width, show="●" if secret else "")
        e.grid(row=r, column=1, sticky="w", padx=4, pady=3)
        if default:
            e.insert(0, default)
        if hint:
            ttk.Label(parent, text=hint, foreground="#777").grid(row=r, column=2, sticky="w", padx=4)
        return e

    # ================= ① 계정·기본정보 =================
    def _build_tab_account(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  ① 계정·기본정보  ")
        c = self.cfg

        acc = ttk.LabelFrame(tab, text="계정 (홈넷 로그인에 씁니다)")
        acc.pack(fill="x", padx=10, pady=(8, 4))
        self.homnet_id = self._row(acc, 0, "홈넷 아이디(사번)", c.get("homnet_id", ""))
        self.homnet_pw = self._row(acc, 1, "홈넷 비밀번호", c.get("homnet_pw", ""), secret=True)
        self.vpn_id = self._row(acc, 2, "VPN 아이디", c.get("vpn_id", ""),
                                hint="사무실(사내망)에서는 비워도 됩니다")
        self.vpn_pw = self._row(acc, 3, "VPN 비밀번호", c.get("vpn_pw", ""), secret=True)
        self.remember = tk.BooleanVar(value=bool(c.get("remember", True)))
        ttk.Checkbutton(acc, text="이 PC에 계정 기억하기 (암호화 저장)",
                        variable=self.remember).grid(row=4, column=1, sticky="w", padx=4, pady=3)
        st = ttk.Frame(acc)
        st.grid(row=5, column=1, columnspan=2, sticky="w", padx=4, pady=(2, 6))
        self.net_status = tk.StringVar(value="● 사내망 연결: 확인 전")
        self.net_label = ttk.Label(st, textvariable=self.net_status, font=FONT_B, foreground="#888")
        self.net_label.pack(side="left")
        ttk.Button(st, text="연결 상태 확인", command=self._check_tunnel).pack(side="left", padx=10)

        info = ttk.LabelFrame(tab, text="우리 관리소 정보 (처음 한 번만 입력 — 공문의 빈칸에 자동으로 들어갑니다)")
        info.pack(fill="x", padx=10, pady=4)
        self.info_entries = {}
        for i, (key, label, hint) in enumerate(INFO_FIELDS):
            self.info_entries[key] = self._row(info, i, label, c.get(key, ""), hint=hint)
            self.info_entries[key].bind("<KeyRelease>", lambda _e: self._refresh())

        doc = ttk.LabelFrame(tab, text="결재정보 기본값")
        doc.pack(fill="x", padx=10, pady=4)
        ttk.Label(doc, text="공개여부").grid(row=0, column=0, sticky="e", padx=8, pady=3)
        self.public_type = ttk.Combobox(doc, values=homnet_draft.PUBLIC_TYPES, state="readonly", width=10)
        self.public_type.set(c.get("public_type", "비공개"))
        self.public_type.grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(doc, text="비공개 호").grid(row=0, column=2, sticky="e", padx=8)
        self.closed = ttk.Entry(doc, width=8)
        self.closed.insert(0, c.get("closed_grades", "6"))
        self.closed.grid(row=0, column=3, sticky="w", padx=4)
        ttk.Label(doc, text="예: 6  (여러 개는 6,5)", foreground="#777").grid(row=0, column=4, sticky="w")
        ttk.Label(doc, text="열람등급").grid(row=1, column=0, sticky="e", padx=8, pady=3)
        self.security = ttk.Combobox(doc, values=list(homnet_draft.SECURITY_GRADES), state="readonly", width=28)
        self.security.set(c.get("security", "1등급[결재선+문서담당자열람]"))
        self.security.grid(row=1, column=1, columnspan=3, sticky="w", padx=4)
        ttk.Label(doc, text="편철(기록물철명)").grid(row=2, column=0, sticky="e", padx=8, pady=3)
        self.binder = ttk.Entry(doc, width=34)
        self.binder.insert(0, c.get("binder", ""))
        self.binder.grid(row=2, column=1, columnspan=3, sticky="w", padx=4)
        ttk.Label(doc, text="비우면 홈넷 기본값 그대로", foreground="#777").grid(row=2, column=4, sticky="w")

        nav = ttk.Frame(tab)
        nav.pack(side="bottom", fill="x", padx=10, pady=8)
        self._orange_button(nav, "저장하고 다음  ▶", self._next_from_account).pack(side="right")

    def _next_from_account(self):
        self._save_settings()
        self.log("✅ 계정·기본정보를 저장했습니다.")
        self.nb.select(1)
        self._nav("write")

    def _check_tunnel(self):
        import session

        def ok(res):
            alive, reason = res
            if alive:
                self.net_status.set("● 사내망 연결됨")
                self.net_label.config(foreground="#1a7f37")
            else:
                self.net_status.set(f"● 사내망 미연결 ({reason}) — VPN 계정을 넣으면 자동 접속합니다")
                self.net_label.config(foreground="#c62828")
        self.run_bg(session.tunnel_alive, ok)

    def _info_values(self) -> dict:
        return {k: e.get().strip() for k, e in self.info_entries.items()}

    def _save_settings(self):
        values = {"vpn_id": self.vpn_id.get(), "vpn_pw": self.vpn_pw.get(),
                  "homnet_id": self.homnet_id.get(), "homnet_pw": self.homnet_pw.get(),
                  "public_type": self.public_type.get(), "closed_grades": self.closed.get().strip(),
                  "security": self.security.get(), "binder": self.binder.get().strip(),
                  "last_template": self.current.file_name if self.current else "",
                  "roster_path": self.roster_path,
                  "complex_info": self.cfg.get("complex_info", {}),
                  "window": self.cfg.get("window", ""),
                  **self._info_values()}
        try:
            settings_store.save(values, self.remember.get())
        except Exception as ex:
            self.log(f"⚠️ 설정 저장 실패: {ex}")
        if getattr(self, "sidebar", None) is not None:
            self.sidebar.refresh()

    # ================= ② 공문 작성 =================
    def _build_tab_write(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  ② 공문 작성  ")

        bottom = ttk.Frame(tab)
        bottom.pack(side="bottom", fill="x", padx=10, pady=8)
        self.auto_btn = self._orange_button(bottom, "홈넷에 자동 작성  ▶", self._create_draft, big=True)
        self.auto_btn.pack(side="right")
        ttk.Button(bottom, text="브라우저로 미리보기", command=self._open_preview).pack(side="right", padx=8)
        ttk.Label(bottom, foreground="#555", text="표준기안문에 제목·수신자·본문을 넣고 멈춥니다. "
                                                  "[결재올림]은 확인 후 직접 눌러 주세요.").pack(side="left")
        ttk.Separator(tab).pack(side="bottom", fill="x")

        pane = ttk.PanedWindow(tab, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=6, pady=6)

        # 왼쪽: 서식 목록
        left = ttk.LabelFrame(pane, text="1. 서식 고르기")
        pane.add(left, weight=2)
        sf = ttk.Frame(left)
        sf.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Label(sf, text="🔍").pack(side="left")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self._fill_tree())
        ttk.Entry(sf, textvariable=self.search).pack(side="left", fill="x", expand=True, padx=4)
        tf = ttk.Frame(left)
        tf.pack(fill="both", expand=True, padx=6, pady=6)
        self.tree = ttk.Treeview(tf, show="tree", selectmode="browse")
        self.tree.column("#0", width=int(380 * self.k))   # 서식 이름이 잘리지 않을 만큼
        ysb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # 오른쪽: 입력 + 미리보기
        right = ttk.Frame(pane)
        pane.add(right, weight=5)
        # 입력칸이 길어져도(2안·3안 …) 아래 '3. 확인하기'가 밀려나지 않게, 높이를 제한하고 스크롤한다
        box = ttk.LabelFrame(right, text="2. 이름·날짜 넣기")
        box.pack(fill="x", padx=4, pady=(0, 6))
        bg = ttk.Style(self.root).lookup("TFrame", "background") or "#fafafa"
        self.inputs_canvas = cv = tk.Canvas(box, highlightthickness=0, bd=0, bg=bg, height=10)
        sb = ttk.Scrollbar(box, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="x", expand=True)
        self.inputs_sb = sb
        self.inputs = ttk.Frame(cv)
        win = cv.create_window(0, 0, window=self.inputs, anchor="nw")

        def fit(_e=None):
            need = self.inputs.winfo_reqheight()
            limit = max(int(180 * self.k), int(right.winfo_height() * 0.55))
            cv.configure(height=min(need, limit), scrollregion=(0, 0, 0, need))
            cv.itemconfigure(win, width=cv.winfo_width())
            if need > limit:
                sb.pack(side="right", fill="y")
            else:
                sb.pack_forget()
                cv.yview_moveto(0)
        self.inputs.bind("<Configure>", fit)
        cv.bind("<Configure>", lambda _e: cv.itemconfigure(win, width=cv.winfo_width()))
        right.bind("<Configure>", fit, add="+")

        def wheel(e):
            if sb.winfo_ismapped():
                cv.yview_scroll(int(-e.delta / 120), "units")
        cv.bind("<Enter>", lambda _e: cv.bind_all("<MouseWheel>", wheel))
        cv.bind("<Leave>", lambda _e: cv.unbind_all("<MouseWheel>"))

        pv = ttk.LabelFrame(right, text="3. 확인하기")
        pv.pack(fill="both", expand=True, padx=4)
        top = ttk.Frame(pv)
        top.pack(fill="x", padx=6, pady=(6, 2))
        self.title_var = tk.StringVar()
        self.recv_var = tk.StringVar()
        ttk.Label(top, text="제목:", font=FONT_B).grid(row=0, column=0, sticky="nw")
        ttk.Label(top, textvariable=self.title_var, wraplength=int(620 * self.k)).grid(
            row=0, column=1, sticky="w", padx=4)
        ttk.Label(top, text="수신자:", font=FONT_B).grid(row=1, column=0, sticky="nw")
        ttk.Label(top, textvariable=self.recv_var).grid(row=1, column=1, sticky="w", padx=4)
        bar = ttk.Frame(pv)
        bar.pack(fill="x", padx=6, pady=2)
        self.mode_btn = ttk.Button(bar, text="✏ 본문 직접 고치기", command=self._toggle_edit)
        self.mode_btn.pack(side="left")
        self.save_btn = ttk.Button(bar, text="고친 내용을 서식에 저장", command=self._save_template)
        self.mode_hint = ttk.Label(bar, foreground="#555", text="")
        self.mode_hint.pack(side="left", padx=8)
        self.preview = scrolledtext.ScrolledText(pv, wrap="word", font=("맑은 고딕", 10), **TEXT_OPTS)
        self.preview.pack(fill="both", expand=True, padx=6, pady=4)
        self.preview.tag_configure("blank", foreground="#c62828", background="#fde8e8")
        self.preview.tag_configure("field", foreground=ACCENT, font=("맑은 고딕", 10, "bold"))
        self.preview.tag_configure("table", background="#f1f5fb", foreground="#333")
        self.preview.tag_raise("blank")
        self.warn_var = tk.StringVar()
        ttk.Label(pv, textvariable=self.warn_var, style="Warn.TLabel", wraplength=int(700 * self.k),
                  justify="left").pack(fill="x", padx=6, pady=(0, 6))

    def _load_templates(self):
        folder = paths.template_dir()
        self.templates, errors = dtpl.load_all(folder)
        first_dir = os.path.join(folder, dtpl.FIRST_DIR)
        firsts, first_errors = dtpl.load_all(first_dir) if os.path.isdir(first_dir) else ([], [])
        self.first_docs = {x.file_name: x for x in firsts}
        opt_dir = os.path.join(folder, dtpl.OPTION_DIR)
        opts, opt_errors = dtpl.load_all(opt_dir) if os.path.isdir(opt_dir) else ([], [])
        self.option_docs = {x.file_name: x for x in opts}
        for e in errors + first_errors + opt_errors:
            self.log(f"⚠️ 서식을 읽지 못했습니다 — {e}")
        self.log(f"서식 {len(self.templates)}개를 불러왔습니다. ({folder})")
        self._fill_tree()
        last = self.cfg.get("last_template", "")
        mine = [t for t in self.templates if t.area == self.area]
        pick = next((t for t in mine if t.file_name == last), None)
        if pick is None and mine:
            pick = mine[0]
        if pick:
            iid = self.templates.index(pick)
            if self.tree.exists(str(iid)):
                self.tree.selection_set(str(iid))
                self.tree.yview_moveto(0)       # 묶음 제목이 보이도록 맨 위부터
                self.tree.see(str(iid))
        if getattr(self, "landing", None) is not None:
            self.landing.set_counts(self._area_counts())

    def _fill_tree(self):
        q = self.search.get().strip()
        self.tree.delete(*self.tree.get_children())
        # 매월 작성 / 수시 작성 → 구분 폴더 → 서식
        sections = {c: self.tree.insert("", "end", text=label, open=True)
                    for c, label in (("매월", "📅 매월 작성하는 공문"), ("매주", "🗓 매주 작성하는 공문"),
                                     ("수시", "🗂 기타 공문"))}
        groups: dict[tuple[str, str], str] = {}
        for i, t in enumerate(self.templates):
            if t.area != self.area:
                continue
            if q and q not in t.label and q not in t.group and q not in t.title:
                continue
            key = (t.cycle, t.bundle or t.group)     # 묶음(갱신계약·예비입주자 …)이 있으면 묶음으로
            if key not in groups:
                groups[key] = self.tree.insert(sections[t.cycle], "end", text=f"📁 {key[1]}", open=True)
            self.tree.insert(groups[key], "end", iid=str(i), text=t.label)
        for sec in sections.values():           # 비어 있는 묶음은 감춘다(검색 결과 등)
            if not self.tree.get_children(sec):
                self.tree.delete(sec)

    def _on_select(self, _=None):
        sel = self.tree.selection()
        if not sel or not sel[0].isdigit():
            return
        t = self.templates[int(sel[0])]
        if t is self.current:
            return
        if self.edit_mode:
            self._toggle_edit()
        self.current = t
        self._build_inputs()
        self._refresh()

    # ---------- 1안(내부결재) + 2안 ----------
    def _first_doc(self, t: dtpl.Template) -> dtpl.Template | None:
        """서식 머리말 '1안: …'이 가리키는 내부결재 서식(서식\\1안 폴더)."""
        return self.first_docs.get(t.first.strip()) if t.first.strip() else None

    def _docs(self) -> list[dtpl.Template]:
        """이번에 작성할 안 목록.
        - '1안:'이 있으면 [1안 내부결재, 고른 서식]
        - '선택안:'이 있으면 [고른 서식(1안), 체크한 선택안들(2안, 3안 …)]"""
        t = self.current
        first = self._first_doc(t) if self.with_first.get(t.file_name, True) else None
        return ([first] if first is not None else []) + [t] + self._picked_options(t)

    # ---------- 선택안(2안·3안 …) ----------
    def _picked_options(self, t: dtpl.Template) -> list[dtpl.Template]:
        if self._none(t):                       # 소명대상 없음이면 안내문(선택안)을 쓰지 않는다
            return []
        names = self.option_pick.get(t.file_name)
        if names is None:                       # 처음에는 첫 번째 선택안만 체크
            names = t.options[:1]
        return [self.option_docs[n] for n in t.options if n in names and n in self.option_docs]

    def _none(self, t: dtpl.Template) -> bool:
        return bool(t.none_label) and self.none_checked.get(t.file_name, False)

    def _on_none_toggle(self):
        t = self.current
        self.none_checked[t.file_name] = self.none_var.get()
        self._build_inputs(keep=True)
        self._refresh()

    def _on_option_toggle(self):
        t = self.current
        self.option_pick[t.file_name] = [n for n, v in self.option_vars.items() if v.get()]
        self._build_inputs(keep=True)
        self._refresh()

    def _upload_for(self, d: dtpl.Template) -> str:
        """그 안의 수신자 엑셀. 선택안은 안마다 따로, 나머지는 공통 하나."""
        if d.file_name in self.option_docs and d is self.option_docs[d.file_name]:
            return self.option_uploads.get(d.file_name, "")
        return self.upload_path

    def _build_option_rows(self, parent, row: int, t: dtpl.Template) -> int:
        """체크박스(2안·3안 …)와 안마다 수신자 엑셀 고르기."""
        ttk.Label(parent, text="함께 작성할 소명 안내문 — 체크한 순서대로 2안, 3안 …이 되고, "
                               "안마다 고른 엑셀 명단이 그 안의 수신자가 됩니다",
                  font=FONT_B, wraplength=int(600 * self.k), justify="left").grid(
            row=row, column=0, columnspan=6, sticky="w", padx=8, pady=(6, 2))
        row += 1
        picked = [d.file_name for d in self._picked_options(t)]
        none = self._none(t)
        self.option_vars = {}
        for i, name in enumerate(t.options):
            doc = self.option_docs.get(name)
            v = tk.BooleanVar(value=name in picked)
            self.option_vars[name] = v
            # 첫 줄: 안 번호 + 체크박스(안내문 이름)
            box = ttk.Frame(parent)
            box.grid(row=row, column=0, columnspan=6, sticky="w", padx=12, pady=(3, 0))
            no = f"{picked.index(name) + 2}안" if name in picked else "　　"
            ttk.Label(box, text=no, width=4, foreground=ACCENT, font=FONT_B).pack(side="left")
            cb = ttk.Checkbutton(box, variable=v, command=self._on_option_toggle,
                                 text=doc.label.split(". ", 1)[-1] if doc else f"(서식 없음: {name})")
            cb.pack(side="left")
            if doc is None or none:
                cb.state(["disabled"])
            row += 1
            if name not in picked:
                continue
            # 둘째 줄: 이 안의 수신자 엑셀 (줄을 나눠 창이 좁아도 버튼이 잘리지 않게)
            sub = ttk.Frame(parent)
            sub.grid(row=row, column=0, columnspan=6, sticky="w", padx=(60, 8), pady=(0, 4))
            ttk.Label(sub, text="수신자 엑셀").pack(side="left")
            ttk.Button(sub, text="📎 고르기", command=lambda n=name: self._pick_option_upload(n)).pack(
                side="left", padx=6)
            path = self.option_uploads.get(name, "")
            if path:
                n = self.option_counts.get(name)
                ttk.Label(sub, text=f"✅ {os.path.basename(path)}" + (f" ({n}세대)" if n is not None else ""),
                          foreground="#1a7f37").pack(side="left")
                ttk.Button(sub, text="빼기", command=lambda n=name: self._set_option_upload(n, "")).pack(
                    side="left", padx=4)
            else:
                ttk.Label(sub, text="⚠ 아직 안 골랐습니다", foreground="#b45309").pack(side="left")
            row += 1
        return row

    def _pick_option_upload(self, name: str):
        path = filedialog.askopenfilename(
            title="이 안의 수신자 엑셀 고르기", parent=self.root,
            initialdir=os.path.dirname(self.option_uploads.get(name) or self.upload_path or self.roster_path)
            or os.path.expanduser("~\\Desktop"),
            filetypes=[("엑셀", "*.xlsx *.xls *.csv"), ("모든 파일", "*.*")])
        if path:
            self._set_option_upload(name, path)

    def _set_option_upload(self, name: str, path: str):
        if path:
            self.option_uploads[name] = path
            try:
                self.option_counts[name] = roster.count_upload(path)
            except Exception as ex:
                self.option_counts[name] = None
                self.log(f"⚠️ 수신자 엑셀의 인원을 세지 못했습니다 — {ex}")
            self.log(f"수신자 엑셀({name}): {path}")
        else:
            self.option_uploads.pop(name, None)
            self.option_counts.pop(name, None)
        self._build_inputs(keep=True)
        self._refresh()

    def _on_first_toggle(self):
        self.with_first[self.current.file_name] = self.first_var.get()
        self._build_inputs(keep=True)
        self._refresh()

    def _build_inputs(self, keep: bool = False):
        old_values, old_dates = self._values() if keep else ({}, {})
        for w in self.inputs.winfo_children():
            w.destroy()
        t = self.current
        f = self.inputs
        r = 0
        self.name_entry = self.addr_entry = None
        self.auto_label = None

        # 맨 위 따로 한 줄: 소명대상 없음 — 체크하면 안내문(선택안)을 모두 빼고 1안 제목 끝에 표시한다
        if t.none_label:
            none = self._none(t)
            bar = tk.Frame(f, bg=SELECT_BG if none else "#fbf6f2", highlightthickness=1,
                           highlightbackground=ORANGE if none else LINE)
            bar.grid(row=r, column=0, columnspan=6, sticky="we", padx=8, pady=(6, 6))
            self.none_var = tk.BooleanVar(value=none)
            tk.Checkbutton(bar, variable=self.none_var, command=self._on_none_toggle, text=t.none_label,
                           bg=bar["bg"], activebackground=bar["bg"], fg=BROWN, selectcolor="white",
                           font=FONT_B, bd=0, highlightthickness=0, cursor="hand2").pack(side="left", padx=10, pady=6)
            tk.Label(bar, bg=bar["bg"], fg=BROWN if none else SUB, font=("맑은 고딕", 9),
                     text=f"안내문 없이 1안만 작성하고, 제목 끝에 '{t.none_label}'을 붙입니다" if none else
                     f"이번 달 소명할 세대가 없으면 체크하세요 (1안 제목 끝에 '{t.none_label}')").pack(
                side="left", padx=(4, 10))
            r += 1

        # '1안:'이 있는 서식은 내부결재 1안 + 이 서식 2안으로 한 번에 작성한다. 예: 갱신계약 안내
        first = self._first_doc(t)
        if t.first.strip():
            self.first_var = tk.BooleanVar(value=self.with_first.get(t.file_name, True) and first is not None)
            cb = ttk.Checkbutton(f, variable=self.first_var, command=self._on_first_toggle,
                                 text=f"1안 내부결재 함께 작성 — {t.first if first else '(1안 서식 없음: ' + t.first + ')'}")
            cb.grid(row=r, column=0, columnspan=5, sticky="w", padx=8, pady=4)
            if first is None:
                cb.state(["disabled"])
            r += 1

        if t.memo:
            ttk.Label(f, text=f"📝 {t.memo}", foreground="#7a5b00", wraplength=int(640 * self.k),
                      justify="left").grid(row=r, column=0, columnspan=6, sticky="w", padx=8, pady=(4, 2))
            r += 1

        if t.options:      # 2안·3안 …으로 붙일 선택안 고르기
            r = self._build_option_rows(f, r, t)

        docs = self._docs()
        uses = lambda key: any(d.uses(key) for d in docs)   # noqa: E731
        sender = next((d for d in docs if not d.internal), t)
        if uses("이름"):
            label = sender.name_hint or ("받는 분 이름" if not sender.internal else "이름")
            ttk.Label(f, text=label, font=FONT_B).grid(row=r, column=0, sticky="e", padx=8, pady=4)
            self.name_entry = ttk.Entry(f, width=30)
            self.name_entry.grid(row=r, column=1, sticky="w", padx=4)
            self.name_entry.insert(0, old_values.get("이름", ""))
            self.name_entry.bind("<KeyRelease>", lambda _e: self._refresh())
            if not self._overlay_shown():     # 처음 화면 검색칸 등에서 커서를 빼앗지 않게
                self.name_entry.focus_set()
            ttk.Label(f, text="여러 명이면 쉼표로 (예: 홍길동, 김철수)" if "상속인" in sender.receiver else "",
                      foreground="#777").grid(row=r, column=2, columnspan=3, sticky="w")
            r += 1
        if uses("주소"):
            ttk.Label(f, text="동·호 (주소)").grid(row=r, column=0, sticky="e", padx=8, pady=4)
            self.addr_entry = ttk.Entry(f, width=30)
            self.addr_entry.grid(row=r, column=1, sticky="w", padx=4)
            self.addr_entry.insert(0, old_values.get("주소", ""))
            self.addr_entry.bind("<KeyRelease>", lambda _e: self._refresh())
            ttk.Label(f, text="예: 101동 1001호  (비워도 됩니다)", foreground="#777").grid(
                row=r, column=2, columnspan=3, sticky="w")
            r += 1

        from tkcalendar import DateEntry
        today = dt.date.today()
        self.date_widgets = {}
        fields: list[tuple[str, str]] = []      # 1안·2안의 날짜 칸. 같은 이름은 한 번만
        for d in docs:
            fields += [fs for fs in d.date_fields() if fs[0] not in dict(fields)]
        # 자동으로 정하는 날짜는 입력칸을 만들지 않는다(만료일=갱신월 말일, 안내문시행일=작성일)
        self.auto_dates = [lb for lb, _ in fields if auto_date_rule(lb, dict(fields))]
        fields = [fs for fs in fields if fs[0] not in self.auto_dates]
        for i, (label, style) in enumerate(fields):
            rr, cc = r + i // 2, (i % 2) * 3
            ttk.Label(f, text=label).grid(row=rr, column=cc, sticky="e", padx=8, pady=4)
            if is_month_field(label, style):
                de = MonthEntry(f, command=self._refresh)
            else:
                de = DateEntry(f, width=12, locale="ko_KR", date_pattern="yyyy-mm-dd",
                               firstweekday="sunday", showweeknumbers=False,
                               selectbackground=ACCENT, font=FONT)
                de.bind("<<DateEntrySelected>>", lambda _e: self._refresh())
                de.bind("<KeyRelease>", lambda _e: self._refresh())
            de.set_date(old_dates.get(label) or default_date(label, today))
            de.grid(row=rr, column=cc + 1, sticky="w", padx=4)
            hint = "작성일부터 2주" if "기한" in label else ""
            ttk.Label(f, text=hint, foreground="#999").grid(row=rr, column=cc + 2, sticky="w")
            self.date_widgets[label] = de
        self.roster_tree = None
        r += (len(fields) + 1) // 2
        # {입력:항목} 수기 입력 칸(두 칸씩 한 줄)
        self.text_widgets = {}
        inputs = list(dict.fromkeys(x for d in docs for x in d.input_fields()))
        kinds = {k: v for d in reversed(docs) for k, v in d.input_kinds().items()}
        defaults = {k: v for d in reversed(docs) for k, v in d.input_defaults().items()}
        uses_link = "차수" in inputs and any(d.uses(k) for d in docs for k in LINK_KEYS)
        if uses_link and "자격검색요청일" not in inputs:
            tip = ("차수를 넣으면 자동 작성 때 [문서링크]에서 같은 차수의 '입주자격심사 결과'와 "
                   "같은 차수·월의 '소명 안내' 문서를 찾아 관련 문서번호 자리에 넣습니다")
        elif any(x.endswith("일") for x in inputs):
            tip = ("차수를 넣으면 자동 작성 때 [문서링크]로 그 차수의 '주택소유 전산검색 결과 통보'를 넣습니다. "
                   "[홈넷에서 찾기]는 자격검색요청일을 채워 줍니다. 날짜는 2026. 10. 25.처럼 적어 주세요"
                   if uses_link else "아래 날짜는 직접 적어 주세요 (예: 2026. 10. 25.)")
        else:
            tip = ""
        if tip:
            # 긴 안내문이 칸 너비를 밀어 입력칸을 화면 밖으로 내보내지 않게 줄바꿈한다
            ttk.Label(f, text=tip, foreground="#777", wraplength=int(560 * self.k), justify="left").grid(
                row=r, column=0, columnspan=6, sticky="w", padx=8, pady=(2, 0))
            r += 1
        # 수기 입력 칸은 한 줄에 하나씩(이름 칸 아래 같은 열) — 버튼·안내가 옆 칸을 밀지 않게
        for label in inputs:
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="e", padx=8, pady=4)
            box = ttk.Frame(f)
            box.grid(row=r, column=1, columnspan=5, sticky="w", padx=4)
            e = ttk.Entry(box, width=18)
            e.insert(0, old_values.get("입력:" + label, defaults.get(label, "")))
            e.pack(side="left")
            e.bind("<KeyRelease>", lambda _e: self._refresh())
            self.text_widgets[label] = e
            if label == "차수" and ("자격검색요청일" in inputs or "검색결과통보일" in self.date_widgets):
                # 차수를 넣으면 기록물등록대장에서 결과 통보 문서를 찾아 요청일·통보일을 채운다
                ttk.Button(box, text="🔎 홈넷에서 찾기", command=self._lookup_round).pack(side="left", padx=6)
                e.bind("<Return>", lambda _e: self._lookup_round())
                e.bind("<FocusOut>", lambda _e: self._lookup_round(auto=True))
                self._looked_round = self._round()
            elif kinds.get(label) == "금액":
                ttk.Label(box, text="숫자만 (예: 113560 → 금113,560원(금일십일만…))",
                          foreground="#999").pack(side="left", padx=8)
            elif kinds.get(label) == "숫자":
                ttk.Label(box, text="숫자", foreground="#999").pack(side="left", padx=8)
            elif label.endswith("일"):
                ttk.Label(box, text="예: 2026. 10. 8.", foreground="#999").pack(side="left", padx=8)
            r += 1
        if self.auto_dates:
            self.auto_label = ttk.Label(f, foreground="#1a5fb4")
            self.auto_label.grid(row=r, column=0, columnspan=6, sticky="w", padx=8, pady=(0, 4))
            r += 1
        if not sender.internal and not t.options:   # 선택안이 있으면 안마다 위에서 고른다
            self._build_upload_row(f, r)
            r += 1
        if uses("이름"):
            self._build_roster(f, r)
        if not uses("이름") and not uses("주소") and not fields and not inputs and not t.internal:
            ttk.Label(f, text="이 서식은 넣을 이름·날짜가 없습니다. 아래 본문을 확인하고 필요하면 직접 고쳐 주세요.",
                      foreground="#555").grid(row=0, column=0, padx=8, pady=8)

    def _round(self) -> str:
        e = self.text_widgets.get("차수") if hasattr(self, "text_widgets") else None
        n = e.get().strip().rstrip("차").strip() if e is not None else ""
        return n if n.isdigit() else ""

    def _link_specs(self, dates: dict) -> dict:
        """서식의 링크 칸 → [문서링크]로 넣을 관련 문서(DocLink).
        fallback(미리보기 글자) 자리에 자동 작성 때 홈넷 [문서링크]로 그 문서가 들어간다."""
        import ledger
        n = self._round()
        if not n:
            return {}
        DocLink = homnet_draft.DocLink
        round_re = rf"(^|[^0-9]){n}\s*차"
        specs = {
            "문서링크": DocLink(f"{n}차", (f"{ledger.NOTICE_TITLE}({n}차",), f"[문서링크: {n}차 결과 통보]"),
            "심사결과링크": DocLink(f"{n}차", ("입주자격심사 결과",), f"[문서링크: {n}차 입주자격심사 결과]",
                                prefer=(round_re,), min_prefer=1),
        }
        # 소명 안내문은 제목 형식이 여러 가지라 '소명'으로 찾고 같은 차수·같은 월이 맞는 문서를 고른다
        month = dates.get("갱신월")
        prefer = (round_re,) + ((rf"(^|[^0-9]){month.month}\s*월",) if month else ())
        label = f"{n}차" + (f"·{month.month}월" if month else "")
        specs["소명안내링크"] = DocLink("소명", ("소명",), f"[문서링크: {label} 소명 안내]",
                                    exclude=("소명 결과", "소명결과"), prefer=prefer, min_prefer=1)
        return specs

    def _doc_links(self, d: dtpl.Template, dates: dict) -> list:
        """서식 본문에 있는 링크 칸마다 [문서링크]로 넣을 관련 문서 정보(본문 순서)."""
        import dataclasses
        specs = {k: v for k, v in self._link_specs(dates).items() if d.uses(k)}
        order = sorted(specs, key=lambda k: d.body.find("{" + k + "}"))
        return [dataclasses.replace(specs[k], mark=homnet_draft.LINK_MARK.replace("⟧", f"{i}⟧"))
                for i, k in enumerate(order, 1)]

    # ---------- 차수 → 기록물등록대장 조회 ----------
    def _lookup_round(self, auto: bool = False):
        """'주택소유 전산검색 결과 통보(N차 …)'를 기록물등록대장에서 찾아 통보일·요청일을 채운다.
        auto: 차수 칸을 벗어날 때. 차수가 바뀌었을 때만 조용히 찾는다."""
        box = self.text_widgets.get("차수")
        raw = box.get().strip().rstrip("차").strip() if box else ""
        if auto and (not raw.isdigit() or raw == getattr(self, "_looked_round", "")):
            return
        if not raw.isdigit():
            messagebox.showwarning("차수", "차수를 숫자로 넣어 주세요. 예: 34")
            return
        hid, hpw = self.homnet_id.get().strip(), self.homnet_pw.get()
        if auto and not (hid and hpw):
            return
        self._looked_round = raw
        if not (hid and hpw):
            messagebox.showwarning("계정 필요", "① 계정·기본정보에서 홈넷 아이디와 비밀번호를 넣어 주세요.")
            self.nb.select(0)
            return
        vpn_id, vpn_pw = self.vpn_id.get().strip(), self.vpn_pw.get()

        def work():
            import ledger
            import session
            session.ensure_tunnel(self.log, vpn_id, vpn_pw)
            if not homnet.driver_alive(self.driver):
                self.driver = None
                self.driver = session.open_homnet(hid, hpw, self.log)
            return ledger.find_notice(self.driver, int(raw), self.log)

        def ok(n):
            fill = {}
            if n.request_date:
                fill["자격검색요청일"] = n.request_date
            if n.enforce_date:
                fill["검색결과통보일"] = n.enforce_date     # 결과 통보 시행일
            self.log(f"  {n.title} — {n.doc_number}({dtpl.fmt_date(n.enforce_date, '일')})")
            for label, value in fill.items():
                e = self.text_widgets.get(label)
                if e is not None:
                    e.delete(0, "end")
                    e.insert(0, dtpl.fmt_date(value, "일"))
                elif label in self.date_widgets:
                    self.date_widgets[label].set_date(value)
                else:
                    continue
                self.log(f"  {label}: {dtpl.fmt_date(value, '일')}")
            self._refresh()

        def err(ex):
            messagebox.showerror("찾지 못함", f"{ex}\n\n문서번호와 날짜를 직접 넣어 주세요.")

        self.run_bg(work, ok, err)

    # ---------- 홈넷 수신자 업로드 엑셀 ----------
    def _build_upload_row(self, parent, row: int):
        """여러 명에게 보낼 때: 홈넷 수기입력 [업로드]에 올릴 엑셀을 고른다."""
        ttk.Label(parent, text="수신자 엑셀 업로드").grid(row=row, column=0, sticky="e", padx=8, pady=4)
        box = ttk.Frame(parent)
        box.grid(row=row, column=1, columnspan=5, sticky="w", padx=4)
        ttk.Button(box, text="📎 업로드할 엑셀 고르기", command=self._pick_upload).pack(side="left")
        self.upload_label = ttk.Label(box)
        self.upload_label.pack(side="left", padx=8)
        self.upload_clear = ttk.Button(box, text="빼기", command=lambda: self._set_upload(""))
        self._set_upload(self.upload_path, refresh=False)

    def _pick_upload(self):
        path = filedialog.askopenfilename(
            title="홈넷 수신자 업로드용 엑셀 고르기", parent=self.root,
            initialdir=os.path.dirname(self.upload_path or self.roster_path) or os.path.expanduser("~\\Desktop"),
            filetypes=[("엑셀", "*.xlsx *.xls *.csv"), ("모든 파일", "*.*")])
        if path:
            self._set_upload(path)
            self.log(f"수신자 업로드 엑셀: {path}")

    def _set_upload(self, path: str, refresh: bool = True):
        if path != self.upload_path or (path and self.upload_count is None):
            self.upload_count = None
            if path:
                try:
                    self.upload_count = roster.count_upload(path)
                except Exception as ex:
                    self.log(f"⚠️ 수신자 엑셀의 인원을 세지 못했습니다 — {ex}")
        self.upload_path = path
        label = getattr(self, "upload_label", None)
        if label is None or not label.winfo_exists():     # 이 서식엔 공통 업로드 줄이 없다(선택안 서식 등)
            if refresh:
                self._refresh()
            return
        if path:
            n = f" ({self.upload_count}세대)" if self.upload_count is not None else ""
            self.upload_label.config(text=f"✅ {os.path.basename(path)}{n} — 자동 작성 때 홈넷 수기입력 [업로드]로 올립니다",
                                     foreground="#1a7f37")
            self.upload_clear.pack(side="left")
        else:
            self.upload_label.config(text="여러 명에게 보낼 때 (홈넷 [샘플 다운로드] 양식으로 작성한 엑셀)",
                                     foreground="#777")
            self.upload_clear.pack_forget()
        if refresh:
            self._refresh()

    # ---------- 수신인 명단(엑셀) ----------
    def _build_roster(self, parent, row: int):
        """엑셀 명단에서 한 명을 고르면 이름·동호 칸을 채운다."""
        box = ttk.Frame(parent)
        box.grid(row=row, column=0, columnspan=6, sticky="we", padx=8, pady=(6, 4))
        bar = ttk.Frame(box)
        bar.pack(fill="x")
        ttk.Button(bar, text="📂 엑셀 명단 불러오기", command=self._pick_roster).pack(side="left")
        self.roster_info = ttk.Label(bar, foreground="#555")
        self.roster_info.pack(side="left", padx=8)
        self.roster_search = tk.StringVar()
        ttk.Entry(bar, textvariable=self.roster_search, width=16).pack(side="right")
        ttk.Label(bar, text="🔍").pack(side="right")
        self.roster_search.trace_add("write", lambda *_: self._fill_roster())

        tf = ttk.Frame(box)
        tf.pack(fill="x", pady=(4, 0))
        self.roster_tree = ttk.Treeview(tf, columns=("addr", "name"), show="headings",
                                        selectmode="browse", height=5)
        self.roster_tree.heading("addr", text="동·호")
        self.roster_tree.heading("name", text="이름")
        self.roster_tree.column("addr", width=int(160 * self.k), anchor="center")
        self.roster_tree.column("name", width=int(160 * self.k), anchor="center")
        ysb = ttk.Scrollbar(tf, orient="vertical", command=self.roster_tree.yview)
        self.roster_tree.configure(yscrollcommand=ysb.set)
        self.roster_tree.pack(side="left", fill="x", expand=True)
        ysb.pack(side="right", fill="y")
        self.roster_tree.bind("<<TreeviewSelect>>", self._on_pick_person)
        self._fill_roster()

    def _fill_roster(self):
        tree = self.roster_tree
        if tree is None:
            return
        tree.delete(*tree.get_children())
        q = self.roster_search.get().strip()
        for i, p in enumerate(self.roster):
            if q and q not in p.name and q not in p.address:
                continue
            tree.insert("", "end", iid=str(i), values=(p.address, p.name))
        if self.roster:
            self.roster_info.config(text=f"{os.path.basename(self.roster_path)} · {len(self.roster)}명 "
                                         "— 목록에서 받는 분을 누르세요")
        else:
            self.roster_info.config(text="첫 줄에 '이름', '동', '호'가 적힌 엑셀(.xlsx)을 불러오면 "
                                         "목록에서 골라 넣을 수 있습니다")

    def _pick_roster(self):
        path = filedialog.askopenfilename(
            title="수신인 명단 엑셀 고르기", parent=self.root,
            initialdir=os.path.dirname(self.roster_path) or os.path.expanduser("~\\Desktop"),
            filetypes=[("엑셀·CSV", "*.xlsx *.xlsm *.csv"), ("모든 파일", "*.*")])
        if path:
            self._load_roster(path)

    def _load_roster(self, path: str, quiet: bool = False):
        try:
            people = roster.load(path)
        except Exception as ex:
            self.log(f"⚠️ 명단을 읽지 못했습니다 — {ex}")
            if not quiet:
                messagebox.showwarning("명단 불러오기", str(ex))
            return
        self.roster, self.roster_path = people, path
        self.log(f"✅ 수신인 명단 {len(people)}명을 불러왔습니다. ({os.path.basename(path)})")
        if self.roster_tree is not None:
            self.roster_search.set("")
            self._fill_roster()

    def _on_pick_person(self, _=None):
        sel = self.roster_tree.selection()
        if not sel:
            return
        p = self.roster[int(sel[0])]
        for entry, value in ((self.name_entry, p.name), (self.addr_entry, p.address)):
            if entry is not None:
                entry.delete(0, "end")
                entry.insert(0, value)
        self._refresh()

    def _values(self) -> tuple[dict, dict]:
        values = self._info_values()
        if self.name_entry is not None:
            values["이름"] = self.name_entry.get().strip()
        if self.addr_entry is not None:
            values["주소"] = self.addr_entry.get().strip()
        if self.upload_path and self.upload_count is not None:
            values["세대수"] = str(self.upload_count)
        for label, e in getattr(self, "text_widgets", {}).items():
            values["입력:" + label] = e.get().strip()
        dates = {}
        for label, de in self.date_widgets.items():
            try:
                dates[label] = de.get_date()
            except Exception:
                pass
        for label in getattr(self, "auto_dates", []):
            v = auto_date_rule(label, dates)(dates, dt.date.today())
            if v:
                dates[label] = v
        for key, link in self._link_specs(dates).items():
            values[key] = link.fallback
        return values, dates

    def _filled(self, doc: dtpl.Template | None = None) -> tuple[str, str, str]:
        """(제목, 수신자, 본문 텍스트). doc을 주지 않으면 1안(고른 서식)."""
        t = doc or self.current
        values, dates = self._values()
        title = dtpl.fill(t.title, values, dates, t.extras)
        if t is self.current and self._none(t):
            title = dtpl.add_title_note(title, t.none_label)
        if t.internal:
            receiver = dtpl.INTERNAL
        elif self._upload_for(t):
            receiver = f"엑셀 업로드({os.path.basename(self._upload_for(t))})"
        elif t.file_name in self.option_docs:      # 선택안은 그 안의 엑셀 명단이 수신자
            receiver = "⚠ 이 안의 수신자 엑셀을 골라 주세요"
        else:
            receiver = dtpl.fill_receiver(t.receiver, values)
        return title, receiver, dtpl.fill(t.body, values, dates, t.extras)

    def _all_filled(self) -> list[tuple[str, str, str]]:
        """작성할 안마다 (제목, 수신자, 본문)."""
        return [self._filled(d) for d in self._docs()]

    def _refresh(self):
        if self.current is None or self.edit_mode:
            return
        filled = self._all_filled()
        title, receiver, body = filled[0]
        if getattr(self, "auto_dates", None) and getattr(self, "auto_label", None) is not None:
            _, dates = self._values()
            self.auto_label.config(text="자동: " + ",  ".join(
                f"{lb} {dtpl.fmt_date(dates[lb], '년월' if lb in DATE_MONTH_AUTO else '일')}"
                f" ({AUTO_DATE_NOTES.get(lb, '갱신월 말일')})"
                for lb in self.auto_dates if lb in dates))
        more = len(filled) - 1
        self.title_var.set(title + (f"   (+ {'2안' if more == 1 else f'2안～{more + 1}안'})" if more else ""))
        self.recv_var.set(receiver)
        self.preview.config(state="normal")
        self.preview.delete("1.0", "end")
        shown = dtpl.to_preview_text(body)
        for no, (t2, r2, b2) in enumerate(filled[1:], 2):
            shown += (f"\n\n━━━━━━━━━━ {no}안 ━━━━━━━━━━\n제목: {t2}\n수신자: {r2}\n\n"
                      + dtpl.to_preview_text(b2))
        self.preview.insert("1.0", shown)
        for i, line in enumerate(shown.split("\n"), 1):   # 표 줄은 옅은 바탕으로 구분
            if line.startswith("    ▏"):
                self.preview.tag_add("table", f"{i}.0", f"{i}.end")
        everything = "\n".join("\n".join(x) for x in filled)
        self._highlight(dtpl.leftovers(everything))
        self.preview.config(state="disabled")
        left = dtpl.leftovers(everything)
        self.warn_var.set(("⚠ 아직 채우지 않은 칸이 있습니다(빨간 표시): " + ", ".join(left[:8])
                           + (" …" if len(left) > 8 else "")
                           + "\n   필요하면 [✏ 본문 직접 고치기]로 고치거나, 홈넷에서 작성 후 고쳐 주세요.")
                          if left else "✅ 빈칸이 모두 채워졌습니다.")
        self.mode_hint.config(text="")

    def _highlight(self, words: list[str]):
        for w in words:
            start = "1.0"
            while True:
                pos = self.preview.search(w, start, stopindex="end")
                if not pos:
                    break
                end = f"{pos}+{len(w)}c"
                self.preview.tag_add("blank", pos, end)
                start = end

    def _toggle_edit(self):
        if self.current is None:
            return
        t = self.current
        if not self.edit_mode:
            self.edit_mode = True
            self.preview.config(state="normal")
            self.preview.delete("1.0", "end")
            self.preview.insert("1.0", t.body)
            start = "1.0"
            while True:     # {이름}·{날짜:…} 빈칸은 파란색으로 보여 준다
                pos = self.preview.search(r"\{[^{}]+\}", start, stopindex="end", regexp=True,
                                          count=(cnt := tk.IntVar()))
                if not pos:
                    break
                end = f"{pos}+{cnt.get()}c"
                self.preview.tag_add("field", pos, end)
                start = end
            self.mode_btn.config(text="✔ 고치기 끝 (미리보기로)")
            self.save_btn.pack(side="left", padx=6, after=self.mode_btn)
            self.mode_hint.config(text="파란 글씨 { } 는 위에 넣은 이름·날짜로 바뀌는 자리입니다. "
                                       "표는 | 로 칸을 나눕니다.")
        else:
            t.body = self.preview.get("1.0", "end").rstrip("\n")
            self.edit_mode = False
            self.mode_btn.config(text="✏ 본문 직접 고치기")
            self.save_btn.pack_forget()
            self._refresh()
            self.mode_hint.config(text="고친 내용은 이번 작성에 쓰입니다. 계속 쓰려면 [고친 내용을 서식에 저장].")

    def _save_template(self):
        t = self.current
        if t is None:
            return
        if self.edit_mode:
            t.body = self.preview.get("1.0", "end").rstrip("\n")
        if not messagebox.askyesno("서식 저장", f"「{t.label}」 서식 파일을 고친 내용으로 바꿉니다.\n"
                                              "다음부터 이 내용으로 시작합니다. 저장할까요?"):
            return
        try:
            dtpl.save(t)
        except OSError as ex:
            messagebox.showerror("저장 실패", str(ex))
            return
        self.log(f"✅ 서식 저장: {t.path}")

    def _current_body(self) -> str:
        if self.edit_mode:
            self._toggle_edit()
        return self._filled()[2]

    def _open_preview(self):
        if self.current is None:
            return
        self._current_body()
        for i, (title, receiver, body) in enumerate(self._all_filled()):
            path = os.path.join(paths.sub_dir("output"), "미리보기.html" if i == 0 else f"미리보기_{i + 1}안.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(dtpl.preview_html(title, receiver, dtpl.to_html(body)))
            webbrowser.open("file:///" + path.replace("\\", "/"))

    def _doc_info(self, title: str) -> homnet_draft.DocInfo:
        try:
            grades = sorted({int(x) for x in self.closed.get().replace(" ", "").split(",") if x})
        except ValueError:
            raise ValueError("① 계정·기본정보의 '비공개 호'는 숫자로 적어 주세요. 예: 6") from None
        if any(g < 1 or g > 8 for g in grades):
            raise ValueError("비공개 호는 1~8 사이 숫자입니다.")
        if self.public_type.get() == "비공개" and not grades:
            raise ValueError("비공개로 할 때는 비공개 호를 적어 주세요. 예: 6")
        return homnet_draft.DocInfo(
            title=title, public_type=self.public_type.get(), closed_grades=grades,
            security=homnet_draft.SECURITY_GRADES.get(self.security.get(), "1"),
            binder=self.binder.get().strip())

    def _create_draft(self):
        if self.current is None:
            messagebox.showinfo("서식 선택", "왼쪽에서 서식을 먼저 골라 주세요.")
            return
        self._current_body()
        docs = self._docs()
        filled = self._all_filled()
        # 수신자는 내부결재가 아닌 안에만, 안마다 그 안의 엑셀로 넣는다
        uploads = ["" if d.internal else self._upload_for(d) for d in docs]
        no_excel = [f"{i}안" for i, (d, u) in enumerate(zip(docs, uploads), 1)
                    if not d.internal and not u and d.file_name in self.option_docs]
        if no_excel:   # 선택안(소명 안내문)은 그 안의 엑셀 명단이 수신자다
            messagebox.showwarning("수신자 엑셀", f"{', '.join(no_excel)}의 수신자 엑셀을 골라 주세요.\n"
                                                "(안마다 [📎 고르기]로 그 안에 보낼 명단 엑셀을 고릅니다)")
            return
        missing = [u for u in uploads if u and not os.path.isfile(u)]
        if missing:
            messagebox.showwarning("엑셀 없음", "수신자 업로드 엑셀을 찾을 수 없습니다.\n" + "\n".join(missing))
            return
        needs_name = (any(not d.internal and d.uses("이름") and not u for d, u in zip(docs, uploads))
                      or all(d.internal for d in docs))
        if (needs_name and self.name_entry is not None
                and not self.name_entry.get().strip()):
            messagebox.showwarning("이름 필요", "받는 분 이름을 넣어 주세요.")
            self.name_entry.focus_set()
            return
        hid, hpw = self.homnet_id.get().strip(), self.homnet_pw.get()
        if not (hid and hpw):
            messagebox.showwarning("계정 필요", "① 계정·기본정보에서 홈넷 아이디와 비밀번호를 넣어 주세요.")
            self.nb.select(0)
            return
        try:
            parts = []
            dates = self._values()[1]
            for d, (t, r, b), up in zip(docs, filled, uploads):
                links = self._doc_links(d, dates)
                for link in links:      # 관련 문서번호 자리는 홈넷 [문서링크]로 넣는다
                    b = b.replace(link.fallback, link.mark, 1)
                parts.append(homnet_draft.DraftPart(self._doc_info(t), r, dtpl.to_html(b), up, doc_links=links))
        except ValueError as ex:
            messagebox.showwarning("확인", str(ex))
            return
        left = dtpl.leftovers("\n".join("\n".join(x) for x in filled))
        many = len(filled) > 1
        msg = "홈넷 표준기안문을 아래 내용으로 작성합니다.\n\n" + "".join(
            (f"[{i}안] " if many else "") + f"제목: {t}\n" + ("      " if many else "") + f"수신자: {r}\n\n"
            for i, (t, r, _) in enumerate(filled, 1))
        title, receiver = filled[0][0], " / ".join(r for _, r, _ in filled)
        if left:
            msg += f"⚠ 아직 채우지 않은 칸이 있습니다: {', '.join(left[:6])}\n  (작성 후 홈넷에서 고쳐도 됩니다)\n\n"
        msg += "결재올림(상신)은 하지 않습니다. 계속할까요?"
        if not messagebox.askyesno("홈넷에 작성", msg):
            return
        self._save_settings()
        vpn_id, vpn_pw = self.vpn_id.get().strip(), self.vpn_pw.get()

        def work():
            import session
            session.ensure_tunnel(self.log, vpn_id, vpn_pw)
            if not homnet.driver_alive(self.driver):
                self.driver = None
                self.driver = session.open_homnet(hid, hpw, self.log)

            def notify(m):
                self.q.put(("call", lambda: messagebox.showinfo("직접 해 주실 일", m)))
            return homnet_draft.create_drafts(self.driver, parts, log=self.log, notify=notify)

        values_now = self._values()[0]

        def ok(todo):
            self._write_history(title, receiver, "작성완료(상신 전)")
            self._carry_over(docs, values_now)
            steps = "\n".join(f"{i}. {s}" for i, s in enumerate(todo, 1))
            self.log("✅ 표준기안문 작성을 마쳤습니다. 브라우저에서 확인하세요.")
            messagebox.showinfo("작성 완료", f"브라우저에서 다음을 마저 해 주세요.\n\n{steps}")

        def err(ex):
            self._write_history(title, receiver, f"실패: {ex}")
            messagebox.showerror("작성 실패", f"{ex}\n\n[브라우저로 미리보기]에서 본문을 복사해 "
                                             "직접 붙여 넣을 수도 있습니다.")

        self.run_bg(work, ok, err)

    def _carry_over(self, docs: list, values: dict) -> list[str]:
        """서식 머리말 '이월: 받을칸 <- 줄칸'대로 이번 값을 다음 작성 때 처음 값으로 서식에 저장한다.
        (예: 이번 달 누적액 → 다음 달 '전월누적'). 바뀐 칸을 돌려준다."""
        done = []
        for t in docs:
            if not t.carry:
                continue
            calc = dtpl.computed(t, values)
            disk = dtpl.load(t.path)          # 직접 고친(저장 안 한) 본문은 서식에 넣지 않는다
            mine = []
            for dst, src in t.carry:
                v = calc.get(src) or values.get("입력:" + src, "")
                if not v or "오류" in v:
                    continue
                num = dtpl.fmt_number(dtpl.to_number(v)).replace(",", "")
                if dtpl.set_default(disk, dst, num):
                    mine.append(f"{dst}={dtpl.fmt_number(dtpl.to_number(num))}")
            if mine:
                dtpl.save(disk)
                t.title, t.body, t.extras = disk.title, disk.body, disk.extras
                done += mine
        if done:
            self.log("📌 다음 작성 때 쓸 값을 서식에 저장했습니다: " + ", ".join(done))
            if self.current in docs:
                self._build_inputs()
                self._refresh()
        return done

    # ================= 단지기본정보 =================
    def _show_complex(self):
        """관리소명·평형·업체처럼 여러 서식에 되풀이해 들어가는 값({단지:…} 칸)을 넣는 창."""
        win = tk.Toplevel(self.root)
        win.title("단지기본정보")
        win.transient(self.root)
        win.grab_set()
        saved = {**complex_info.defaults(), **self.cfg.get("complex_info", {})}
        entries: dict[str, ttk.Entry] = {}
        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, foreground="#555", wraplength=int(620 * self.k), justify="left",
                  text="월별·주별 서식의 {단지:관리소명} 같은 칸에 자동으로 들어갑니다. "
                       "한 번 넣어 두면 공문마다 입력하지 않아도 됩니다.").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        def rows(parent, items):
            for i, (key, label, _, hint) in enumerate(items):
                ttk.Label(parent, text=label).grid(row=i, column=0, sticky="e", padx=6, pady=2)
                e = ttk.Entry(parent, width=36)
                e.insert(0, saved.get(key, ""))
                e.grid(row=i, column=1, sticky="w", padx=4)
                ttk.Label(parent, text=hint, foreground="#999").grid(row=i, column=2, sticky="w")
                entries[key] = e

        basic = ttk.LabelFrame(body, text="기본")
        basic.grid(row=1, column=0, columnspan=4, sticky="we", pady=4)
        rows(basic, complex_info.BASIC)
        types = ttk.LabelFrame(body, text="평형(계약면적 ㎡)과 세대수")
        types.grid(row=2, column=0, columnspan=4, sticky="we", pady=4)
        for i in range(1, complex_info.MAX_TYPES + 1):
            r, c = (i - 1) // 3, ((i - 1) % 3) * 3
            ttk.Label(types, text=f"평형{i}").grid(row=r, column=c, padx=(8, 2), pady=2)
            box = ttk.Frame(types)
            box.grid(row=r, column=c + 1, padx=2, pady=2)
            for key, unit in ((f"평형{i}", "㎡"), (f"평형{i}세대수", "세대")):
                e = ttk.Entry(box, width=8)
                e.insert(0, saved.get(key, ""))
                e.pack(side="left")
                ttk.Label(box, text=unit, foreground="#999").pack(side="left", padx=(1, 6))
                entries[key] = e
        acc = ttk.LabelFrame(body, text="계좌·업체")
        acc.grid(row=3, column=0, columnspan=4, sticky="we", pady=4)
        rows(acc, complex_info.ACCOUNT)
        ttk.Label(body, text="직접 추가하는 항목 (한 줄에 '이름=값', 서식에서는 {단지:이름})").grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        extra = tk.Text(body, height=3, width=60, font=FONT, **TEXT_OPTS)
        extra.insert("1.0", saved.get("추가항목", ""))
        extra.grid(row=5, column=0, columnspan=4, sticky="we")

        def save():
            info = {k: e.get().strip() for k, e in entries.items()}
            info["추가항목"] = extra.get("1.0", "end-1c")
            self.cfg["complex_info"] = info
            dtpl.set_complex(complex_info.resolve(info))
            self._save_settings()
            self.log("✅ 단지기본정보를 저장했습니다. 월별·주별 서식에 자동으로 들어갑니다.")
            win.destroy()
            self._refresh()

        def reset():
            if messagebox.askyesno("처음 값으로", "단지기본정보를 처음 값(광주우산3)으로 되돌릴까요?", parent=win):
                d = complex_info.defaults()
                for k, e in entries.items():
                    e.delete(0, "end")
                    e.insert(0, d.get(k, ""))
                extra.delete("1.0", "end")

        btns = ttk.Frame(body)
        btns.grid(row=6, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="처음 값으로", command=reset).pack(side="left", padx=4)
        ttk.Button(btns, text="닫기", command=win.destroy).pack(side="left", padx=4)
        ttk.Button(btns, text="저장", style="Accent.TButton", command=save).pack(side="left", padx=4)

    def _write_history(self, title, receiver, status):
        path = os.path.join(paths.sub_dir("logs"), f"작성이력_{dt.date.today():%Y%m}.csv")
        new = not os.path.exists(path)
        try:
            with open(path, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["시각", "서식", "제목", "수신자", "상태"])
                w.writerow([f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
                            self.current.label if self.current else "", title, receiver, status])
        except OSError as ex:
            self.log(f"⚠️ 작성 이력 저장 실패: {ex}")

    # ================= 기타 =================
    def _clear_accounts(self):
        if not messagebox.askyesno("계정 지우기", "저장된 VPN·홈넷 계정을 지울까요?\n(관리소 정보는 남습니다)"):
            return
        settings_store.clear()
        for e in (self.vpn_id, self.vpn_pw, self.homnet_id, self.homnet_pw):
            e.delete(0, "end")
        self.remember.set(False)
        self.log("저장된 계정을 지웠습니다.")

    def _show_help(self):
        messagebox.showinfo("사용 방법", (
            "처음 한 번\n"
            "  ① 계정·기본정보에 홈넷 계정(밖에서는 VPN 계정도)과 관리소 정보를 넣고 [저장하고 다음].\n\n"
            "공문 쓸 때마다\n"
            "  1. 왼쪽에서 서식을 고릅니다(🔍로 검색 가능).\n"
            "  2. 받는 분 이름과 날짜를 넣습니다. 날짜 칸 ▼를 누르면 달력이 나옵니다.\n"
            "     [📂 엑셀 명단 불러오기]로 명단을 올리면 목록에서 눌러 이름·동호를 넣을 수 있습니다.\n"
            "     (엑셀 첫 줄에 '이름', '동', '호' — 성명·계약자명, 동호 한 칸도 됩니다)\n"
            "  3. 아래 미리보기를 확인합니다. 빨간 표시는 아직 채우지 않은 칸입니다.\n"
            "  4. [홈넷에 자동 작성]을 누르면 브라우저가 열리고\n"
            "     전자결재 → 문서작성 → 표준기안문에 제목·수신자·본문을 넣습니다.\n"
            "  5. 브라우저에서 내용을 확인하고 [결재올림]은 직접 누릅니다.\n\n"
            "※ 브라우저 창은 작성이 끝날 때까지 닫지 마세요."))

    def _show_template_help(self):
        messagebox.showinfo("서식 만드는 법", (
            "서식은 [파일 → 서식 폴더 열기]의 txt 파일입니다. 메모장으로 고치거나 복사해 새로 만들 수 있습니다.\n\n"
            "맨 위 머리말\n"
            "  제목: 공문 제목\n  수신자: {주소} {이름} 귀하   (내부결재면 '내부결재')\n"
            "  구분: 목록에서 묶을 이름\n  ---   ← 이 줄 아래가 본문\n\n"
            "빈칸\n"
            "  {이름} {주소} — 공문마다 입력\n"
            "  {단지명} {담당자} {전화번호} {관리소} — 기본정보에서 자동\n"
            "  {날짜:제출기한} → 2026년 11월 6일(금)\n"
            "  {날짜:만료일|일} → 2026년 11월 6일   |월 → 2026년 11월   |점 → 2026.11.06.\n"
            "  {입력:차수} — 직접 적는 칸   {숫자:수량=10} — 숫자(처음 값 10)   {금액:청구액} — 금○원(금…원)\n"
            "  {계산:금액=수량*단가} — 다른 칸으로 계산   {단지:관리소명} — 파일 → 단지기본정보의 값\n"
            "  머리말 '분야: 시설' → 시작 화면 분야,  '주기: 매월'·'주기: 매주' → 매월·매주 작성 묶음\n\n"
            "표\n"
            "  | 구분 | 내용 |   ← 첫 줄은 머리글\n"
            "  칸 안 줄바꿈 <br>, 위 칸과 합치기 ^, 왼쪽 칸과 합치기 <"))

    def _toggle_maximize(self):
        self.root.state("normal" if self.root.state() == "zoomed" else "zoomed")

    def _on_close(self):
        if self.root.state() == "normal":       # 다음에 같은 크기·위치의 창으로 연다
            self.cfg["window"] = self.root.geometry()
        self._save_settings()
        self.root.destroy()


def selftest() -> int:
    """서식 전체를 채워 HTML로 만들어 본다(브라우저·사내망 없이 점검)."""
    folder = paths.template_dir()
    items, errors = dtpl.load_all(folder)
    out = paths.sub_dir("output", "selftest")
    today = dt.date.today()
    dtpl.set_complex(complex_info.resolve(settings_store.load().get("complex_info", {})))
    values = {"이름": "홍길동", "주소": "101동 1001호", "관리소": "가나관리소",
              "단지명": "가나1단지", "담당자": "김담당", "전화번호": "031-000-0000"}
    for t in items:
        dates = {k: default_date(k, today) for k, _ in t.date_fields()}
        title = dtpl.fill(t.title, values, dates, t.extras)
        receiver = dtpl.INTERNAL if t.internal else dtpl.fill_receiver(t.receiver, values)
        body = dtpl.fill(t.body, values, dates, t.extras)
        with open(os.path.join(out, t.file_name + ".html"), "w", encoding="utf-8") as f:
            f.write(dtpl.preview_html(title, receiver, dtpl.to_html(body)))
    lines = [f"서식 {len(items)}개 변환, 오류 {len(errors)}개 → {out}"] + [f"  {e}" for e in errors]
    ok = not errors
    # 브라우저 자동화 점검: 홈넷 로그인 화면이 열리는지(로그인은 하지 않음)
    try:
        import session
        alive, reason = session.tunnel_alive()
        lines.append(f"사내망 연결: {'됨' if alive else '안 됨 ' + reason}")
        d = homnet.build_driver(headless=True, detach=False)
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait
            d.set_page_load_timeout(20)
            d.get(homnet.LOGIN_URL)
            WebDriverWait(d, 15).until(EC.presence_of_element_located((By.XPATH, homnet.XPATH_ID_INPUT)))
            lines.append(f"브라우저({homnet.browser_name()}) 홈넷 로그인 화면: 정상")
        finally:
            d.quit()
    except Exception as ex:
        ok = False
        lines.append(f"브라우저 점검 실패: {type(ex).__name__} {str(ex).splitlines()[0] if str(ex) else ''}")
    report = "\n".join(lines)
    with open(os.path.join(paths.sub_dir("logs"), "selftest.txt"), "w", encoding="utf-8") as f:
        f.write(report + "\n")
    try:
        print(report)
    except Exception:      # 창 모드 exe는 콘솔이 없다
        pass
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    try:   # 고해상도 화면에서 글자가 흐리지 않게
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
