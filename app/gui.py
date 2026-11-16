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
import proofread
import roster
import settings_store
import ui_kit

VERSION = "1.4.0"
FONT = (ui_kit.FONT, 10)
FONT_B = (ui_kit.FONT, 10, "bold")
ACCENT = ui_kit.PRIMARY_D   # 새 디자인: 파랑 계열(진한 쪽)
# 달력(DateEntry) 색: 앱의 파랑 계열. 주말은 붉은 글씨, 다른 달 날짜는 옅게
CAL_STYLE = dict(
    locale="ko_KR", firstweekday="sunday", showweeknumbers=False, font=FONT,
    background=ui_kit.PRIMARY, foreground="#ffffff", bordercolor=ui_kit.BORDER,
    headersbackground=ui_kit.PRIMARY_SOFT, headersforeground=ui_kit.PRIMARY_D,
    normalbackground="#ffffff", normalforeground=ui_kit.TEXT,
    weekendbackground="#ffffff", weekendforeground=ui_kit.DANGER,
    othermonthbackground="#f6f8fc", othermonthforeground=ui_kit.MUTED,
    othermonthwebackground="#f6f8fc", othermonthweforeground="#e9a8a8",
    selectbackground=ui_kit.PRIMARY, selectforeground="#ffffff",
    disableddaybackground="#f6f8fc", disableddayforeground=ui_kit.MUTED,
)
ORANGE = ui_kit.PRIMARY     # 단추·제목 색(예전 이름 그대로)
BROWN, SUB = ui_kit.TEXT, ui_kit.SUB   # 본문 글자, 설명 글자
LINE = ui_kit.LINE          # 옅은 구분선
SELECT_BG = ui_kit.PRIMARY_SOFT       # 목록에서 고른 줄
LINK_KEYS = ("문서링크", "심사결과링크", "소명안내링크")   # 자동 작성 때 홈넷 [문서링크]로 채우는 칸
# 문서번호(등록번호): '가나관리소-1234', '1234', 날짜를 붙이면 그 해 대장에서 '가나관리소-12(2025. 1. 2.)'
DOC_NO_RE = re.compile(r"^((?:[^\s,()-]+-)?\d{1,7})\s*(?:\(\s*((?:19|20)\d{2})[^()]*\))?$")
LINK_FIELD = "관련문서"     # 서식의 {관련문서} 자리(없으면 1안 본문 맨 위 '관련:' 줄)에 [문서링크]로 넣는 관련 문서
TEXT_OPTS = dict(bg="white", relief="flat", borderwidth=0, highlightthickness=1,
                 highlightbackground="#e0e0e0", highlightcolor=ACCENT, padx=6, pady=4)
INFO_FIELDS = [("단지명", "단지명", "예: 광주우산3 (관리소명·약칭은 자동)"),
               ("담당자", "담당자 이름", "예: 홍길동"),
               ("전화번호", "담당자 전화번호", "예: 031-000-0000"),
               ("임대유형", "공급유형", "16·24번 계약특수조건과 {단지:공급유형}에 씁니다")]   # 저장 키는 예전 그대로
RENT_TYPES = dtpl.RENT_TYPES


def recolor_sv_ttk(root: tk.Tk, sv_dir: str, color: str) -> None:
    """sv_ttk 밝은 테마의 파란 강조(단추·체크칸·입력칸 밑줄) 그림을 디자인 색으로 바꿔 다시 입힌다.
    sv_ttk는 그림 한 장(spritesheet)을 잘라 쓰므로, 파란 점만 색상을 돌려 새 그림에서 다시 자른다."""
    import colorsys
    from PIL import Image
    sheet = Image.open(os.path.join(sv_dir, "theme", "spritesheet_light.png")).convert("RGBA")
    th, ts, tv = colorsys.rgb_to_hsv(*(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)))
    px = sheet.load()
    for y in range(sheet.height):
        for x in range(sheet.width):
            r, g, b, a = px[x, y]
            if not a:
                continue
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if s > 0.25 and 0.52 < h < 0.70:            # 파란 강조색(#005fb8 둘레)
                nr, ng, nb = colorsys.hsv_to_rgb(th, min(1, s * ts), min(1, v * tv / 0.72))
                px[x, y] = (round(nr * 255), round(ng * 255), round(nb * 255), a)
    path = os.path.join(paths.user_dir(), "theme_sprites.png")
    sheet.save(path)
    root.tk.call("image", "create", "photo", "kodas_sheet", "-file", path)
    info = root.tk.splitlist(root.tk.eval("set ::spriteinfo"))
    imgs = dict(zip(*[iter(root.tk.splitlist(root.tk.eval("array get ttk::theme::sv_light::I")))] * 2))
    for i in range(0, len(info), 5):
        name, x, y, w, h = info[i], *map(int, info[i + 1:i + 5])
        if name in imgs:
            root.tk.call(imgs[name], "copy", "kodas_sheet", "-from", x, y, x + w, y + h)


def apply_theme(root: tk.Tk) -> ttk.Style:
    """윈도11 느낌의 Sun Valley 밝은 테마. 없으면 기본 테마로 그냥 진행."""
    try:
        import sv_ttk
        sv_ttk.set_theme("light", root)
        from tkinter import font as tkfont
        for name in tkfont.names(root):
            if name.startswith(("SunValley", "Tk")):
                tkfont.nametofont(name, root).configure(family=ui_kit.FONT)
        if ui_kit.DESIGN != ui_kit.DEFAULT_DESIGN:
            recolor_sv_ttk(root, os.path.dirname(sv_ttk.__file__), ui_kit.PRIMARY)
    except Exception:
        pass
    style = ttk.Style(root)
    bg = style.lookup("TFrame", "background") or "#fafafa"
    root.configure(bg=bg)
    root.option_add("*Toplevel.background", bg)
    return style


def default_date(label: str, today: dt.date) -> dt.date:
    return today + dt.timedelta(days=14) if "기한" in label else today


def saved_month(months, file_name: str) -> dt.date | None:
    """서식별로 저장해 둔 달('YYYY-MM')을 그 달 1일로. 없거나 깨졌으면 None."""
    try:
        year, month = months[file_name].split("-")
        return dt.date(int(year), int(month), 1)
    except (KeyError, TypeError, AttributeError, ValueError):
        return None


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


KEY_DATES = ("갱신월", "제출기한")      # 꼭 넣어야 하는 날짜(빨간 *)
ROUND_DATES = ("검색결과통보일",)        # 차수로 홈넷에서 찾아 채우는 날짜
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


class ChoiceBox(ttk.Frame):
    """{선택:형별=36|46|51} 칸: 체크칸을 늘어놓고 고른 것을 '36, 51'처럼 돌려준다(입력칸처럼 get()을 쓴다)."""

    def __init__(self, parent, options: list[str], suffix: str = "", command=None):
        super().__init__(parent)
        self.vars = []
        for opt in options:
            v = tk.BooleanVar(value=False)
            ttk.Checkbutton(self, text=f"{opt}{suffix}", variable=v,
                            command=command).pack(side="left", padx=(0, 10))
            self.vars.append((opt, v))

    def get(self) -> str:
        return dtpl.CHOICE_SEP.join(o for o, v in self.vars if v.get())

    def set(self, value: str) -> None:
        picked = {x.strip() for x in str(value or "").split(",")}
        for o, v in self.vars:
            v.set(o in picked)


MAX_COLLECT = 5000      # 대장 문서 받기: 한 번에 살펴볼 최대 문서 수


class CollectDialog(tk.Toplevel):
    """대장 문서 받기 설정: 검색어 · 개수 · 받을 것(서식·PDF·첨부) · 꼭 가릴 이름·동호수·연락처."""

    AREAS = ("자동(편철)", "임대", "시설", "주거복지", "주택관리")
    THIS_YEAR = "올해"

    @classmethod
    def parse_year(cls, text: str) -> int | None:
        """'2025년' → 2025, '올해' → None(홈넷 기본 = 올해, 미리 열어 둔 문서 창도 그대로 쓴다)."""
        m = re.fullmatch(r"\s*(\d{4})\s*년?\s*", text or "")
        return int(m.group(1)) if m else None

    def __init__(self, master, area: str = "자동(편철)"):
        super().__init__(master)
        self.title("홈넷 대장 문서 받기")
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, justify="left", text=(
            "홈넷 전자결재 → 대장관리 → 기록물등록대장의 문서를 자동으로 열어 [다음]으로 넘기며 받습니다.\n"
            "본문 없이 편철·등록구분만 보이는 '조회' 화면은 건너뛰고, 보안(암호) 문서는 홈넷 비밀번호로 열어 봅니다.\n"
            "대장 문서 창을 미리 열어 두었다면 그 문서부터 받습니다.")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="제목 검색어(선택)").grid(row=1, column=0, sticky="e", padx=6, pady=(10, 3))
        self.keyword = ttk.Entry(f, width=34)
        self.keyword.grid(row=1, column=1, sticky="w", pady=(10, 3))
        ttk.Label(f, text="살펴볼 문서 수").grid(row=2, column=0, sticky="e", padx=6, pady=3)
        cf = ttk.Frame(f)
        cf.grid(row=2, column=1, sticky="w")
        self.count = ttk.Spinbox(cf, from_=1, to=MAX_COLLECT, width=8)
        self.count.set("30")
        self.count.pack(side="left")
        ttk.Label(cf, text="연도").pack(side="left", padx=(16, 6))
        this_year = dt.date.today().year
        self.year = ttk.Combobox(cf, width=10, state="readonly",
                                 values=[self.THIS_YEAR] + [f"{y}년" for y in range(this_year - 1, 2005, -1)])
        self.year.set(self.THIS_YEAR)
        self.year.pack(side="left")
        ttk.Label(cf, text="(그 해 기록물등록대장에서 받습니다)", foreground="#777").pack(side="left", padx=6)
        ttk.Label(f, text="편철(선택)").grid(row=3, column=0, sticky="e", padx=6, pady=3)
        bf = ttk.Frame(f)
        bf.grid(row=3, column=1, sticky="w")
        self.binders = ttk.Entry(bf, width=34)
        self.binders.pack(side="left")
        ttk.Label(bf, text="예: 교육훈련, 시설관리  (비우면 모든 편철)", foreground="#777").pack(side="left", padx=6)
        self.dedupe = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="비슷한 제목은 하나만 (예: '…급여 지급(2025.12월분)'·'(11월분)'처럼 날짜·월만 다른 문서)",
                        variable=self.dedupe).grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.internal = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="내부결재 문서만 (켜면 수신자가 있는 문서·접수 문서도 건너뜀)",
                        variable=self.internal).grid(row=4, column=0, columnspan=2, sticky="w", pady=3)

        what = ttk.LabelFrame(f, text="받을 것", padding=(10, 4))
        what.grid(row=5, column=0, columnspan=2, sticky="we", pady=(8, 4))
        self.pdf = tk.BooleanVar(value=True)
        ttk.Checkbutton(what, text="문서를 PDF 파일로 받기 — 이름·동호수·연락처는 000으로 가림",
                        variable=self.pdf).grid(row=0, column=0, columnspan=3, sticky="w", pady=2)
        self.attach = tk.BooleanVar(value=True)
        ttk.Checkbutton(what, text="첨부파일도 받기 — PDF 첨부도 이름·동호수·연락처를 000으로 가림",
                        variable=self.attach).grid(row=1, column=0, columnspan=3, sticky="w", pady=2)
        self.register = tk.BooleanVar(value=True)
        ttk.Checkbutton(what, text="서식으로 넣기 — 이름·동호수·연락처는 공문 쓸 때 넣는 칸이 됨",
                        variable=self.register).grid(row=2, column=0, sticky="w", pady=2)
        ttk.Label(what, text="분야").grid(row=2, column=1, sticky="e", padx=(10, 4))
        self.area = ttk.Combobox(what, values=self.AREAS, width=9, state="readonly")
        self.area.configure(width=11)
        self.area.set("자동(편철)")      # 기본: 문서마다 편철로 분야를 정하고 편철 묶음에 넣는다
        self.area.grid(row=2, column=2, sticky="w")
        ttk.Label(what, foreground="#777", text=(
            "자동(편철): 문서정보의 편철(예: 교육훈련관계철)로 분야를 정해 '편철 · 교육훈련관계철' 묶음에 넣고,\n"
            "받은 폴더에 편철별 폴더·편철별_목록.csv를 만듭니다.")).grid(row=3, column=0, columnspan=3, sticky="w")

        hide = ttk.LabelFrame(f, text="꼭 가릴 글자 (선택 — 자동으로 못 찾는 것, 쉼표로 여러 개)", padding=(10, 4))
        hide.grid(row=6, column=0, columnspan=2, sticky="we", pady=4)
        self.hide = {}
        for i, (key, hint) in enumerate((("이름", "예: 홍길동, 김영희"), ("동호수", "예: 105동 814호"),
                                         ("연락처", "예: 010-1234-5678"))):
            ttk.Label(hide, text=key).grid(row=i, column=0, sticky="e", padx=(0, 6), pady=2)
            e = ttk.Entry(hide, width=30)
            e.grid(row=i, column=1, sticky="w", pady=2)
            ttk.Label(hide, text=hint, foreground="#777").grid(row=i, column=2, sticky="w", padx=6)
            self.hide[key] = e
        ttk.Label(f, foreground="#777", justify="left", text=(
            "관리소 대표번호(기본정보의 전화번호)는 가리지 않습니다. 스캔(그림)만 있는 PDF는 글자를 찾을 수 없어\n"
            "가리지 못하니 완료 창의 목록을 보고 직접 확인해 주세요.")).grid(row=7, column=0, columnspan=2, sticky="w")
        b = ttk.Frame(f)
        b.grid(row=10, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(b, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(b, text="받기 시작", style="Accent.TButton", command=self._ok).pack(side="right", padx=6)
        ttk.Button(b, text="📚 고른 연도 전체 받기", command=self._ok_all).pack(side="right", padx=6)
        self.keyword.focus_set()
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    @staticmethod
    def split_words(text: str) -> list:
        """'홍길동, 김영희 / 105동 814호' → ['홍길동', '김영희', '105동 814호']"""
        return [w.strip() for w in re.split(r"[,，/;\n]+", text or "") if w.strip()]

    def _ok_all(self):
        """고른 연도(올해면 올해) 대장의 문서를 처음부터 끝까지(최대 MAX_COLLECT개) 받는다."""
        year = self.parse_year(self.year.get()) or dt.date.today().year
        if not messagebox.askyesno(
                "연도 전체 받기",
                f"{year}년 기록물등록대장의 문서를 처음부터 끝까지 모두 받습니다(최대 {MAX_COLLECT:,}개).\n\n"
                "문서 하나에 5초쯤 걸려 1,000개면 1시간 30분쯤 걸립니다.\n"
                "도중에 [■ 그만 받기]를 누르면 그때까지 받은 문서만 정리합니다.\n\n"
                "제목 검색어·편철·체크한 조건은 그대로 적용됩니다. 시작할까요?", parent=self):
            return
        self._ok(count=MAX_COLLECT, year=year)

    def _ok(self, count: int | None = None, year: int | None = None):
        try:
            n = count or max(1, min(MAX_COLLECT, int(self.count.get())))
        except ValueError:
            messagebox.showwarning("문서 수", "살펴볼 문서 수를 숫자로 넣어 주세요.", parent=self)
            return
        if not (self.pdf.get() or self.attach.get() or self.register.get()):
            messagebox.showwarning("받을 것", "PDF·첨부파일·서식 중 하나는 골라 주세요.", parent=self)
            return
        extra = [w for e in self.hide.values() for w in self.split_words(e.get())]
        self.result = {"keyword": self.keyword.get().strip(), "count": n, "area": self.area.get(),
                       "only_internal": self.internal.get(), "register": self.register.get(),
                       "pdf": self.pdf.get(), "attachments": self.attach.get(), "extra": extra,
                       "binders": self.split_words(self.binders.get()),
                       "year": year or self.parse_year(self.year.get()), "dedupe": self.dedupe.get()}
        self.destroy()


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
        self.roster_path = self.cfg.get("roster_path", "")
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

        root.title(f"KODAS — 공문 자동작성 시스템 v{VERSION}")
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
        style.configure("Big.Accent.TButton", font=(ui_kit.FONT, 11, "bold"), padding=(18, 8))
        style.configure("Warn.TLabel", foreground="#b45309")

        self._build_menu()
        # 새 디자인: 왼쪽 메뉴 + 오른쪽 본문(처음 화면·서식 고르기·기본정보·작성 이력은 본문을 덮는다)
        import landing
        self.sidebar = landing.Sidebar(root, {"home": self._go_home, "write": self._show_write,
                                              "picker": self._show_picker, "history": self._show_history,
                                              "complex": self._show_complex, "settings": self._show_settings},
                                       self.k, VERSION, profile=self._profile, on_profile=self._show_complex)
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
        self._build_tab_design()        # 환경 설정: 디자인(색·글씨체) 고르기
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(100, self._drain)
        self._load_templates()
        # 처음 쓰는 사람은 계정·기본정보부터, 이미 입력했으면 바로 공문 작성으로
        if self.cfg.get("담당자") and self.cfg.get("단지명"):
            self.nb.select(1)
        # 시작 화면(대시보드)을 맨 위에 덮는다
        logo = os.path.join(paths.bundle_dir(), "assets", "logo.png")
        shortcuts = (("단지기본정보", "building", "blue", self._show_complex),
                     ("서식 폴더 열기", "folder", "amber", lambda: os.startfile(paths.template_dir())),
                     ("대장 문서 받기", "download", "green", self._collect_docs),
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
            self._set_write_title()

    def _set_write_title(self):
        """공문 작성 화면 맨 위 제목: 고른 서식 이름(예: 14. 갱신계약 입주자격심사 소명결과)."""
        self.header_title.config(text=self.current.label if self.current is not None
                                 else f"공문 작성  ·  {self.area}")

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
        """서식 고르기 화면에서 고른 서식을 열고 ② 공문 작성 화면으로 간다.
        기본정보 화면은 필수 칸(단지명·담당자)이 비어 있을 때(처음 쓸 때)만 거친다.
        이미 넣었으면 바로 작성 화면으로 — 고칠 때는 [파일] → 단지기본정보."""
        import landing
        self._hide_overlays()
        self._nav("write")
        self.search.set("")
        iid = str(i)
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)
        info = {**self._info_values(), "homnet_id": self.homnet_id.get().strip(), "homnet_pw": self.homnet_pw.get()}
        if all(str(info.get(k, "") or "").strip() for k in landing.InfoScreen.REQUIRED):
            self.nb.select(1)
            self._refresh()
            return
        self._cover(self.info_screen)
        self.info_screen.show(self.templates[i].label if 0 <= i < len(self.templates) else "", info)

    def _open_write(self):
        self.info_screen.place_forget()
        self.nb.select(1)
        self._nav("write")
        self._refresh()

    def _info_done(self, values: dict):
        """기본정보 화면의 [시작하기]: ① 탭 입력칸에 옮기고 저장한 뒤 공문 작성 화면으로."""
        for key, e in list(self.info_entries.items()) + [("homnet_id", self.homnet_id), ("homnet_pw", self.homnet_pw)]:
            if isinstance(e, ttk.Combobox):     # 임대유형
                e.set(values.get(key, ""))
                continue
            e.delete(0, "end")
            e.insert(0, values.get(key, ""))
        self._save_settings()
        if not self.remember.get():
            self.log("⚠️ '계정 기억하기'가 꺼져 있어 홈넷 계정은 저장하지 않았습니다(다음 실행 때 다시 묻습니다).")
        self._open_write()

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
        f.add_command(label="단지기본정보 (관리소·평형·업체·계정·결재정보)", command=self._show_complex)
        f.add_separator()
        f.add_command(label="서식 폴더 열기", command=lambda: os.startfile(paths.template_dir()))
        f.add_command(label="서식 다시 읽기", command=self._load_templates)
        f.add_command(label="홈넷 대장 문서 받기 (PDF·첨부·서식)…", command=self._collect_docs)
        f.add_command(label="받은 대장 문서 폴더 열기", command=lambda: os.startfile(paths.sub_dir("수집")))
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
                          ("⌂  처음 화면", self._go_home), ("ⓘ  도움말", self._show_page_help)):
            self._text_button(right, text, cmd, bg=bg).pack(side="left", padx=(12, 0))
        mid = tk.Frame(head, bg=bg)
        mid.pack(side="left", padx=6, pady=6)
        self.header_title = tk.Label(mid, text="공문 작성", font=(ui_kit.FONT, 16, "bold"), bg=bg, fg=BROWN)
        self.header_title.pack(anchor="w")

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
                     font=(ui_kit.FONT, 11 if big else 10, "bold"), padx=24 if big else 16, pady=9 if big else 5)
        b.bind("<Button-1>", lambda _e: command())
        b.bind("<Enter>", lambda _e: b.config(bg=ACCENT))
        b.bind("<Leave>", lambda _e: b.config(bg=ORANGE))
        return b

    def _show_complex(self):
        """단지기본정보(감춰 둔 ① 탭: 관리소·단지·평형·업체·계정·결재정보). [뒤로가기]나 [저장하고 다음]으로 돌아온다."""
        self._hide_overlays()
        self.nb.select(0)
        self.header_title.config(text="단지기본정보")
        self._nav("complex")

    def _show_settings(self):
        """환경 설정: 공문작성기 디자인(색 묶음 5가지 · 글씨체)을 고른다."""
        self._hide_overlays()
        self.nb.select(2)
        self.header_title.config(text="환경 설정")
        self._nav("settings")

    def _go_back(self):
        """한 단계 뒤로: 단지기본정보·환경 설정 화면이면 공문 작성으로, 공문 작성이면 서식 고르기 화면으로."""
        if self.nb.index("current") in (0, 2):
            if self.current is None:
                self._go_home()
                return
            self.nb.select(1)
            self._nav("write")
        else:
            self._show_picker()

    def _build_log(self):
        f = ttk.LabelFrame(self.main, text="진행 상황")
        f.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
        self.log_box = scrolledtext.ScrolledText(f, height=5, wrap="word", font=(ui_kit.FONT, 9),
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

    # ================= ① 단지기본정보 (예전 '환경 설정' + '단지기본정보' 창을 합친 화면) =================
    # 관리소명·단지명·단지약칭은 '단지명' 한 칸으로, 임대유형·공급유형은 '공급유형' 한 칸으로 받는다.
    # 단지 항목 중 화면에 따로 두지 않고 위 칸에서 만들어 넣는 것들:
    COMPLEX_SHARED = ("관리소명", "단지명", "단지약칭", "공급유형")

    def _scroll_area(self, parent):
        """세로로 긴 화면을 위한 스크롤 영역. 안쪽 Frame을 돌려준다."""
        bg = ttk.Style().lookup("TFrame", "background") or "#fafafa"
        cv = tk.Canvas(parent, highlightthickness=0, borderwidth=0, bg=bg)
        sb = ttk.Scrollbar(parent, orient="vertical", command=cv.yview)
        inner = ttk.Frame(cv)
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)

        def wheel(e):
            cv.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")
        cv.bind("<Enter>", lambda _e: cv.bind_all("<MouseWheel>", wheel))
        cv.bind("<Leave>", lambda _e: cv.unbind_all("<MouseWheel>"))
        return inner

    def _build_tab_account(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  ① 단지기본정보  ")
        c = self.cfg
        cx_saved = c.get("complex_info", {}) or {}
        cx = {**complex_info.defaults(), **cx_saved}

        nav = ttk.Frame(tab)
        nav.pack(side="bottom", fill="x", padx=10, pady=8)
        self._orange_button(nav, "저장하고 다음  ▶", self._next_from_account).pack(side="right")
        ttk.Button(nav, text="단지 항목 처음 값으로", command=self._reset_complex).pack(side="right", padx=8)
        ttk.Label(nav, foreground="#555", text="여기 값은 모든 공문의 빈칸({관리소}·{단지:관리소명} 등)에 "
                                               "자동으로 들어갑니다.").pack(side="left")
        ttk.Separator(tab).pack(side="bottom", fill="x")
        body = self._scroll_area(tab)

        info = ttk.LabelFrame(body, text="우리 관리소·단지 (처음 한 번만 입력 — 공문의 빈칸에 자동으로 들어갑니다)")
        info.pack(fill="x", padx=10, pady=(8, 4))
        self.info_entries = {}
        r = 0
        for key, label, hint in INFO_FIELDS:
            if key == "임대유형":     # 공급유형(고르는 칸) — 계약특수조건과 {단지:공급유형}에 같이 쓴다
                ttk.Label(info, text=label).grid(row=r, column=0, sticky="e", padx=8, pady=3)
                cb = ttk.Combobox(info, values=RENT_TYPES, state="readonly", width=10)
                old = dtpl.normalize_rent_type(c.get(key)) or dtpl.normalize_rent_type(cx_saved.get("공급유형"))
                cb.set(old if old in RENT_TYPES else "")
                cb.grid(row=r, column=1, sticky="w", padx=4)
                ttk.Label(info, text=hint, foreground="#777").grid(row=r, column=2, sticky="w")
                cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh())
                self.info_entries[key] = cb
                r += 1
                continue
            default = c.get(key, "") or (cx_saved.get("단지명", "") if key == "단지명" else "")
            self.info_entries[key] = self._row(info, r, label, default, hint=hint)
            self.info_entries[key].bind("<KeyRelease>", lambda _e: self._refresh())
            r += 1
            if key == "단지명":      # 단지명에서 자동으로 만든 관리소명·약칭을 바로 보여 준다
                self.derived_label = ttk.Label(info, foreground=ACCENT)
                self.derived_label.grid(row=r, column=1, columnspan=2, sticky="w", padx=4, pady=(0, 4))
                self.info_entries[key].bind("<KeyRelease>", lambda _e: self._show_derived(), add="+")
                r += 1
        self._show_derived()
        self.complex_entries: dict[str, ttk.Entry] = {}
        for key, label, _, hint in complex_info.BASIC:
            if key in self.COMPLEX_SHARED:
                continue
            self.complex_entries[key] = self._row(info, r, label, cx.get(key, ""), hint=hint)
            r += 1

        types = ttk.LabelFrame(body, text="평형(계약면적 ㎡)과 세대수")
        types.pack(fill="x", padx=10, pady=4)
        for i in range(1, complex_info.MAX_TYPES + 1):
            rr, cc = (i - 1) // 3, ((i - 1) % 3) * 3
            ttk.Label(types, text=f"평형{i}").grid(row=rr, column=cc, padx=(8, 2), pady=3)
            box = ttk.Frame(types)
            box.grid(row=rr, column=cc + 1, padx=2, pady=3)
            for key, unit in ((f"평형{i}", "㎡"), (f"평형{i}세대수", "세대")):
                e = ttk.Entry(box, width=8)
                e.insert(0, cx.get(key, ""))
                e.pack(side="left")
                ttk.Label(box, text=unit, foreground="#999").pack(side="left", padx=(1, 6))
                self.complex_entries[key] = e

        accf = ttk.LabelFrame(body, text="계좌·업체")
        accf.pack(fill="x", padx=10, pady=4)
        for i, (key, label, _, hint) in enumerate(complex_info.ACCOUNT):
            self.complex_entries[key] = self._row(accf, i, label, cx.get(key, ""), hint=hint)

        ex = ttk.LabelFrame(body, text="직접 추가하는 항목 (한 줄에 '이름=값', 서식에서는 {단지:이름})")
        ex.pack(fill="x", padx=10, pady=4)
        self.complex_extra = tk.Text(ex, height=3, width=60, font=FONT, **TEXT_OPTS)
        self.complex_extra.insert("1.0", cx.get("추가항목", ""))
        self.complex_extra.pack(fill="x", padx=8, pady=6)

        acc = ttk.LabelFrame(body, text="계정 (홈넷 로그인에 씁니다)")
        acc.pack(fill="x", padx=10, pady=4)
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

        doc = ttk.LabelFrame(body, text="결재정보 기본값")
        doc.pack(fill="x", padx=10, pady=(4, 10))
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

    def _show_derived(self):
        name = self.info_entries["단지명"].get().strip()
        self.derived_label.config(
            text=f"→ 관리소명: {complex_info.office_name(name)}   ·   단지 약칭: {complex_info.short_name(name)}"
            if name else "→ 관리소명·단지 약칭은 단지명으로 자동으로 만듭니다")

    def _complex_values(self) -> dict:
        """화면의 단지 항목 + 단지명·공급유형에서 만든 값 → settings.json의 complex_info."""
        out = {k: e.get().strip() for k, e in self.complex_entries.items()}
        out["추가항목"] = self.complex_extra.get("1.0", "end-1c")
        info = self._info_values()
        name = info.get("단지명", "")
        out["단지명"] = name
        out["관리소명"] = complex_info.office_name(name)
        out["단지약칭"] = complex_info.short_name(name)
        out["공급유형"] = info.get("임대유형", "") or (self.cfg.get("complex_info") or {}).get("공급유형", "")
        return out

    def _reset_complex(self):
        if not messagebox.askyesno("처음 값으로", "단지 항목(평형·계좌·업체 등)을 처음 값(광주우산3)으로 되돌릴까요?\n"
                                              "관리소명·단지명·담당자·계정은 그대로 둡니다.", parent=self.root):
            return
        d = complex_info.defaults()
        for k, e in self.complex_entries.items():
            e.delete(0, "end")
            e.insert(0, d.get(k, ""))
        self.complex_extra.delete("1.0", "end")

    def _next_from_account(self):
        self._save_settings()
        self.log("✅ 단지기본정보를 저장했습니다. 모든 서식에 자동으로 들어갑니다.")
        self._refresh()
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
        v = {k: e.get().strip() for k, e in self.info_entries.items()}
        v["관리소"] = complex_info.office_name(v.get("단지명", ""))     # {관리소}: 단지명으로 만든다
        return v

    def _save_settings(self):
        if getattr(self, "complex_entries", None):
            self.cfg["complex_info"] = self._complex_values()
            dtpl.set_complex(complex_info.resolve(self.cfg["complex_info"]))
        values = {"vpn_id": self.vpn_id.get(), "vpn_pw": self.vpn_pw.get(),
                  "homnet_id": self.homnet_id.get(), "homnet_pw": self.homnet_pw.get(),
                  "public_type": self.public_type.get(), "closed_grades": self.closed.get().strip(),
                  "security": self.security.get(), "binder": self.binder.get().strip(),
                  "last_template": self.current.file_name if self.current else "",
                  "roster_path": self.roster_path,
                  "complex_info": self.cfg.get("complex_info", {}),
                  "window": self.cfg.get("window", ""),
                  "renewal_months": self.cfg.get("renewal_months", {}),
                  "design": self.cfg.get("design", {}),
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
        ttk.Separator(tab).pack(side="bottom", fill="x")

        pane = ttk.PanedWindow(tab, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=6, pady=6)

        # 서식 목록: 화면에는 띄우지 않는다(서식은 왼쪽 메뉴 [서식 고르기]에서 고른다). 고른 서식 표시용으로만 둔다
        left = ttk.Frame(tab)
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
        # 입력칸이 길어져도(2안·3안 …) 아래 '2. 확인하기'가 밀려나지 않게, 높이를 제한하고 스크롤한다
        box = ttk.LabelFrame(right, text="1. 이름·날짜 넣기")
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
            # 본문을 펼쳐 고칠 때는 입력칸을 줄이고, 평소에는 입력칸을 넓게 쓴다
            limit = max(int(180 * self.k), int(right.winfo_height() * (0.55 if self.edit_mode else 0.8)))
            cv.configure(height=min(need, limit), scrollregion=(0, 0, 0, need))
            cv.itemconfigure(win, width=cv.winfo_width())
            if need > limit:
                sb.pack(side="right", fill="y")
            else:
                sb.pack_forget()
                cv.yview_moveto(0)
        self._fit_inputs = fit
        self.inputs.bind("<Configure>", fit)
        cv.bind("<Configure>", lambda _e: cv.itemconfigure(win, width=cv.winfo_width()))
        right.bind("<Configure>", fit, add="+")

        def wheel(e):
            if sb.winfo_ismapped():
                cv.yview_scroll(int(-e.delta / 120), "units")
        cv.bind("<Enter>", lambda _e: cv.bind_all("<MouseWheel>", wheel))
        cv.bind("<Leave>", lambda _e: cv.unbind_all("<MouseWheel>"))

        pv = ttk.LabelFrame(right, text="2. 확인하기")
        pv.pack(fill="x", padx=4)
        self.preview_box = pv
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
        self.proof_on = False         # [올바른 문서 만들기]를 누른 뒤에는 넣은 값까지 규칙대로 맞춰 고친다
        self.proof_btn = ttk.Button(bar, text="✔ 올바른 문서 만들기", command=self._proofread)
        self.proof_btn.pack(side="left", padx=(6, 0))
        self.save_btn = ttk.Button(bar, text="고친 내용을 서식에 저장", command=self._save_template)
        self.mode_hint = ttk.Label(bar, foreground="#555", text="")
        self.mode_hint.pack(side="left", padx=8)
        # 본문은 [✏ 본문 직접 고치기]를 눌렀을 때만 펼친다
        self.preview = scrolledtext.ScrolledText(pv, wrap="word", font=(ui_kit.FONT, 10), **TEXT_OPTS)
        self.preview.tag_configure("blank", foreground="#c62828", background="#fde8e8")
        self.preview.tag_configure("field", foreground=ACCENT, font=(ui_kit.FONT, 10, "bold"))
        self.preview.tag_configure("table", background="#f1f5fb", foreground="#333")
        self.preview.tag_raise("blank")
        self.warn_var = tk.StringVar()
        self.warn_label = ttk.Label(pv, textvariable=self.warn_var, style="Warn.TLabel",
                                    wraplength=int(700 * self.k), justify="left")
        self.warn_label.pack(fill="x", padx=6, pady=(0, 6))

    def _load_templates(self):
        folder = paths.template_dir()
        self.templates, errors = dtpl.load_all(folder)
        got_dir = os.path.join(folder, dtpl.COLLECTED_DIR)    # 홈넷 대장에서 모아 만든 서식도 목록에 넣는다
        got, got_errors = dtpl.load_all(got_dir) if os.path.isdir(got_dir) else ([], [])
        self.templates += got
        errors += got_errors
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
        self.proof_on = False
        self._set_write_title()
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
        if d.external_receiver:     # 다른 서식에서 고른 엑셀이 이 서식에 쓰이면 안 된다
            return ""
        if d.file_name in self.option_docs and d is self.option_docs[d.file_name]:
            return self.option_uploads.get(d.file_name, "")
        return self.upload_path

    def _build_option_rows(self, parent, row: int, t: dtpl.Template) -> int:
        """체크박스(2안·3안 …)와 안마다 수신자 엑셀 고르기."""
        self._help("함께 작성할 소명 안내문: 체크한 순서대로 2안, 3안 …이 되고, "
                   "안마다 [📎 고르기]로 고른 엑셀 명단이 그 안의 수신자가 됩니다.")
        ttk.Label(parent, text="함께 작성할 소명 안내문", font=FONT_B).grid(
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
        self.required = []      # (이름표, 입력칸) — 꼭 넣어야 하는 칸. 비어 있으면 이름표가 빨갛다
        self.help_lines = []    # 화면에 쓰지 않고 [ⓘ 도움말]에 모아 보여 줄 설명
        self._help("빨간 * 표시 칸은 꼭 넣어야 합니다.")

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
            self._help(f"[{t.none_label}]: 이번 달 소명할 세대가 없으면 체크하세요. "
                       f"안내문 없이 1안만 작성하고, 1안 제목 끝에 '{t.none_label}'을 붙입니다.")
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
            self._help(f"📝 {t.memo}")

        if t.options:      # 2안·3안 …으로 붙일 선택안 고르기
            r = self._build_option_rows(f, r, t)

        docs = self._docs()
        uses = lambda key: any(d.uses(key) for d in docs)   # noqa: E731
        sender = next((d for d in docs if not d.internal), t)
        # 받는 분에게 보내는 안이 모두 수신자 엑셀로 가면 이름·동호 칸은 필요 없다(엑셀의 수신자에게 간다)
        person = lambda d: d.uses("이름") or d.uses("주소")   # noqa: E731
        to_people = [d for d in docs if not d.internal and person(d)]
        by_excel = (bool(to_people) and all(self._upload_for(d) for d in to_people)
                    and not any(d.internal and person(d) for d in docs))
        if by_excel and (uses("이름") or uses("주소")):
            ttk.Label(f, text="📎 수신자 엑셀로 보내므로 받는 분 이름·동호는 넣지 않습니다",
                      foreground="#1a7f37").grid(row=r, column=0, columnspan=6, sticky="w", padx=8, pady=4)
            r += 1
        if uses("이름") and not by_excel:
            label = sender.name_hint or ("받는 분 이름" if not sender.internal else "이름")
            lb = ttk.Label(f, text="* " + label, font=FONT_B)
            lb.grid(row=r, column=0, sticky="e", padx=8, pady=4)
            side = ttk.Frame(f)
            side.grid(row=r, column=1, columnspan=5, sticky="w", padx=4)
            self.name_entry = ttk.Entry(side, width=30)
            self.required.append((lb, self.name_entry))
            self.name_entry.pack(side="left")
            self.name_entry.insert(0, old_values.get("이름", ""))
            self.name_entry.bind("<KeyRelease>", lambda _e: self._refresh())
            if not self._overlay_shown():     # 처음 화면 검색칸 등에서 커서를 빼앗지 않게
                self.name_entry.focus_set()
            if "상속인" in sender.receiver:
                self._help(f"{label}: 여러 명이면 쉼표로 나눠 적습니다 (예: 홍길동, 김철수).")
            if sender.external_receiver:
                self._help(f"{label}: 자동 작성 때 홈넷 수신자 탭의 외부유통문서에서 전남광주통합특별시를 펼쳐 "
                           "그 아래 이 기관을 추가합니다. 예) 전남광주통합특별시남구 또는 남구")
            r += 1
        if uses("주소") and not by_excel:
            ttk.Label(f, text="동·호 (주소)").grid(row=r, column=0, sticky="e", padx=8, pady=4)
            self.addr_entry = ttk.Entry(f, width=30)
            self.addr_entry.grid(row=r, column=1, sticky="w", padx=4)
            self.addr_entry.insert(0, old_values.get("주소", ""))
            self.addr_entry.bind("<KeyRelease>", lambda _e: self._refresh())
            self._help("동·호 (주소): 예) 101동 1001호. 비워도 됩니다.")
            r += 1

        from tkcalendar import DateEntry
        today = dt.date.today()
        self.date_widgets = {}
        fields: list[tuple[str, str]] = []      # 1안·2안의 날짜 칸. 같은 이름은 한 번만
        for d in docs:
            fields += [fs for fs in d.date_fields() if fs[0] not in dict(fields)]
        # 자동으로 정하는 날짜는 입력칸을 만들지 않는다(만료일=갱신월 말일, 안내문시행일=작성일)
        self.auto_dates = [lb for lb, _ in fields if auto_date_rule(lb, dict(fields))]
        # 차수가 있는 서식의 결과 통보일은 차수로 홈넷에서 찾아 채운다(입력칸 없음)
        has_round = any("차수" in d.input_fields() for d in docs)
        self.found_labels = [lb for lb, _ in fields if lb in ROUND_DATES and has_round]
        if not keep:
            self.found = ("", {})
        fields = [fs for fs in fields if fs[0] not in self.auto_dates + self.found_labels]
        for i, (label, style) in enumerate(fields):
            rr, cc = r + i // 2, (i % 2) * 3
            if label in KEY_DATES:
                ttk.Label(f, text="* " + label, font=FONT_B, foreground="#c62828").grid(
                    row=rr, column=cc, sticky="e", padx=8, pady=4)
            else:
                ttk.Label(f, text=label).grid(row=rr, column=cc, sticky="e", padx=8, pady=4)
            if is_month_field(label, style):
                de = MonthEntry(f, command=self._refresh)
            else:
                de = DateEntry(f, width=12, date_pattern="yyyy-mm-dd", **CAL_STYLE)
                de.bind("<<DateEntrySelected>>", lambda _e: self._refresh())
                de.bind("<KeyRelease>", lambda _e: self._refresh())
            last = saved_month(self.cfg.get("renewal_months"), t.file_name) if label == "갱신월" else None
            de.set_date(old_dates.get(label) or last or default_date(label, today))
            de.grid(row=rr, column=cc + 1, sticky="w", padx=4)
            if "기한" in label:
                self._help(f"{label}: 작성일부터 2주 뒤 날짜가 미리 들어갑니다. ▼를 눌러 달력에서 바꿀 수 있습니다.")
            self.date_widgets[label] = de
        r += (len(fields) + 1) // 2
        # {입력:항목} 수기 입력 칸(두 칸씩 한 줄)
        self.text_widgets = {}
        inputs = list(dict.fromkeys(x for d in docs for x in d.input_fields()))
        kinds = {k: v for d in reversed(docs) for k, v in d.input_kinds().items()}
        defaults = {k: v for d in reversed(docs) for k, v in d.input_defaults().items()}
        uses_link = "차수" in inputs and any(d.uses(k) for d in docs for k in LINK_KEYS)
        self.uses_review = any(d.uses("심사결과링크") for d in docs)    # 소명결과: 차수로 입주자격심사 결과도 찾는다
        if uses_link and "자격검색요청일" not in inputs:
            tip = ("차수를 넣으면 자동 작성 때 [문서링크]에서 같은 차수의 '입주자격심사 결과'와 "
                   "같은 차수·월의 '소명 안내' 문서를 찾아 관련 문서번호 자리에 넣습니다")
        elif any(x.endswith("일") for x in inputs):
            tip = ("차수를 넣으면 자동 작성 때 [문서링크]로 그 차수의 '주택소유 전산검색 결과 통보'를 넣고, "
                   "자격검색요청일도 그 문서에서 찾아 채웁니다. 날짜는 2026. 10. 25.처럼 적어 주세요"
                   if uses_link else "아래 날짜는 직접 적어 주세요 (예: 2026. 10. 25.)")
        else:
            tip = ""
        if tip:
            self._help(tip)
        # 수기 입력 칸은 한 줄에 하나씩(이름 칸 아래 같은 열) — 버튼·안내가 옆 칸을 밀지 않게
        options = {k: v for d in reversed(docs) for k, v in d.input_options().items()}
        for label in inputs:
            lb = ttk.Label(f, text="* " + label, font=FONT_B)
            lb.grid(row=r, column=0, sticky="e", padx=8, pady=4)
            box = ttk.Frame(f)
            box.grid(row=r, column=1, columnspan=5, sticky="w", padx=4)
            if kinds.get(label) == "선택":     # 체크해서 고르는 칸(예: 형별 36·46·51형)
                e = ChoiceBox(box, options.get(label, []), "형" if label == "형별" else "",
                              command=self._refresh)
                e.set(old_values.get("입력:" + label, ""))
                e.pack(side="left")
                self.required.append((lb, e))
                self.text_widgets[label] = e
                self._help(f"{label}: 해당하는 것을 모두 체크합니다. 제목과 표에 고른 것이 들어갑니다.")
                r += 1
                continue
            is_date = label.endswith("일") and kinds.get(label) not in ("금액", "숫자")
            if is_date:     # 날짜 칸: ▼를 누르면 달력. '2026. 10. 8.' 꼴로 들어가고 직접 적어도 된다
                e = DateEntry(box, width=14, date_pattern="y. m. d.", **CAL_STYLE)
                e.bind("<<DateEntrySelected>>", lambda _e: self._refresh())
                e.delete(0, "end")
            else:
                e = ttk.Entry(box, width=18)
            self.required.append((lb, e))
            e.insert(0, old_values.get("입력:" + label, defaults.get(label, ""))
                     or (dtpl.fmt_date(today, "일") if is_date else ""))
            e.pack(side="left")
            e.bind("<KeyRelease>", lambda _e: self._refresh())
            self.text_widgets[label] = e
            if label == "차수" and ("자격검색요청일" in inputs or "검색결과통보일" in self.date_widgets
                                  or self.found_labels):
                # 차수를 넣으면 기록물등록대장에서 결과 통보 문서를 찾아 요청일·통보일을 채운다
                self._help("차수: 숫자만 적고 Enter (예: 34) — 그 차수 공문을 홈넷에서 찾아 "
                           "관련 문서 링크와 날짜를 자동으로 넣습니다.")
                e.bind("<Return>", lambda _e: self._lookup_round())    # 칸을 벗어나는 것만으로는 찾지 않는다
            elif label == "차수":
                self._help("차수: 숫자만 적어 주세요 (예: 34).")
            elif kinds.get(label) == "금액":
                self._help(f"{label}: 숫자만 적습니다 (예: 113560 → 금113,560원(금일십일만…)).")
            elif kinds.get(label) == "숫자":
                self._help(f"{label}: 숫자만 적습니다.")
            if is_date:
                self._help(f"{label}: ▼를 눌러 달력에서 고르거나 직접 적습니다 (예: 2026. 10. 8.).")
            r += 1
        if self.auto_dates or self.found_labels:
            self.auto_label = ttk.Label(f, foreground="#1a5fb4")
            self.auto_label.grid(row=r, column=0, columnspan=6, sticky="w", padx=8, pady=(0, 4))
            r += 1
        # 관련 문서: 제목 일부를 적으면 자동 작성 때 홈넷 [문서링크]로 그 문서를 본문에 넣는다
        ttk.Label(f, text="🔗 관련 문서번호").grid(row=r, column=0, sticky="e", padx=8, pady=4)
        lbox = ttk.Frame(f)
        lbox.grid(row=r, column=1, columnspan=5, sticky="w", padx=4)
        self.link_entry = ttk.Entry(lbox, width=34)
        self.link_entry.insert(0, old_values.get(LINK_FIELD + "_검색어", ""))
        self.link_entry.pack(side="left")
        self.link_entry.bind("<KeyRelease>", lambda _e: self._refresh())
        ttk.Label(lbox, foreground="#777", text="예: 광주우산3관리소-1234 또는 1234 (여러 개는 쉼표) — "
                                                "자동 작성 때 그 번호의 문서를 [문서링크]로 넣습니다"
                  ).pack(side="left", padx=8)
        r += 1
        # 선택안이 있으면 안마다 위에서 고르고, 외부유통문서에서 찾는 서식은 엑셀을 쓰지 않는다
        if not sender.internal and not t.options and not sender.external_receiver:
            self._build_upload_row(f, r)
            r += 1
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
        links = [specs[k] for k in order]
        if "{" + LINK_FIELD + "}" in self._link_body(d):      # [🔗 관련 문서]에 적은 문서들
            links += [self._user_link(w) for w in self._link_words()]
        return [dataclasses.replace(x, mark=homnet_draft.LINK_MARK.replace("⟧", f"{i}⟧"))
                for i, x in enumerate(links, 1)]

    # ---------- 차수 → 기록물등록대장 조회 ----------
    def _lookup_round(self, then=None):
        """'주택소유 전산검색 결과 통보(N차 …)'를 기록물등록대장에서 찾아 통보일·요청일을 채운다."""
        box = self.text_widgets.get("차수")
        raw = box.get().strip().rstrip("차").strip() if box else ""
        if not raw.isdigit():
            messagebox.showwarning("차수", "차수를 숫자로 넣어 주세요. 예: 34")
            return
        hid, hpw = self.homnet_id.get().strip(), self.homnet_pw.get()
        if not (hid and hpw):
            messagebox.showwarning("계정 필요", "단지기본정보에서 홈넷 아이디와 비밀번호를 넣어 주세요.")
            self._show_complex()
            return
        vpn_id, vpn_pw = self.vpn_id.get().strip(), self.vpn_pw.get()
        uses_review = getattr(self, "uses_review", False)

        def work():
            import ledger
            import session
            session.ensure_tunnel(self.log, vpn_id, vpn_pw)
            if not homnet.driver_alive(self.driver):
                self.driver = None
                self.driver = session.open_homnet(hid, hpw, self.log)
            review = None
            if uses_review:
                try:
                    review = ledger.find_review(self.driver, int(raw), self.log)
                except ledger.LedgerError as ex:
                    self.log(f"⚠️ {ex}")
            return ledger.find_notice(self.driver, int(raw), self.log), review

        def ok(result):
            n, review = result
            if review and "갱신월" in self.date_widgets:
                self.date_widgets["갱신월"].set_date(review.renewal_month)
                self.log(f"  {review.title} — {review.doc_number}, 갱신월 {review.renewal_month:%Y-%m}")
            elif uses_review:
                messagebox.showwarning("입주자격심사 결과", f"{raw}차 입주자격심사 결과 문서를 찾지 못했습니다. 갱신월을 직접 확인해 주세요.")
            fill = {}
            if n.request_date:
                fill["자격검색요청일"] = n.request_date
            if n.enforce_date:
                fill["검색결과통보일"] = n.enforce_date     # 결과 통보 시행일
            self.log(f"  {n.title} — {n.doc_number}({dtpl.fmt_date(n.enforce_date, '일')})")
            # 입력칸 없이 찾아 넣는 날짜(결과 통보일): 어느 차수로 찾았는지와 함께 둔다
            self.found = (raw, {lb: v for lb, v in fill.items() if lb in self.found_labels})
            for label, value in fill.items():
                e = self.text_widgets.get(label)
                if label in self.found_labels:
                    pass
                elif e is not None:
                    e.delete(0, "end")
                    e.insert(0, dtpl.fmt_date(value, "일"))
                elif label in self.date_widgets:
                    self.date_widgets[label].set_date(value)
                else:
                    continue
                self.log(f"  {label}: {dtpl.fmt_date(value, '일')}")
            self._refresh()
            if then:      # [자동 작성]에서 왔으면 찾은 날짜로 이어서 작성한다
                then()

        def err(ex):
            messagebox.showerror("찾지 못함", f"{ex}\n\n차수를 확인하고 Enter로 다시 찾거나, "
                                            "날짜를 [✏ 본문 직접 고치기]에서 직접 넣어 주세요.")

        self.run_bg(work, ok, err)

    # ---------- 홈넷 수신자 업로드 엑셀 ----------
    def _build_upload_row(self, parent, row: int):
        """여러 명에게 보낼 때: 홈넷 수기입력 [업로드]에 올릴 엑셀을 고른다."""
        self._help("수신자 엑셀 업로드: 여러 명에게 보낼 때 홈넷 [샘플 다운로드] 양식으로 작성한 엑셀을 고릅니다. "
                   "자동 작성 때 홈넷 수기입력 [업로드]로 올립니다.")
        ttk.Label(parent, text="수신자 엑셀 업로드").grid(row=row, column=0, sticky="e", padx=8, pady=4)
        box = ttk.Frame(parent)
        box.grid(row=row, column=1, columnspan=5, sticky="w", padx=4)
        ttk.Button(box, text="📎 업로드할 엑셀 고르기", command=self._pick_upload).pack(side="left")
        self.upload_label = ttk.Label(box)
        self.upload_label.pack(side="left", padx=8)
        self.upload_clear = ttk.Button(box, text="빼기", command=lambda: self._change_upload(""))
        self._set_upload(self.upload_path, refresh=False)

    def _pick_upload(self):
        path = filedialog.askopenfilename(
            title="홈넷 수신자 업로드용 엑셀 고르기", parent=self.root,
            initialdir=os.path.dirname(self.upload_path or self.roster_path) or os.path.expanduser("~\\Desktop"),
            filetypes=[("엑셀", "*.xlsx *.xls *.csv"), ("모든 파일", "*.*")])
        if path:
            self._change_upload(path)
            self.log(f"수신자 업로드 엑셀: {path}")

    def _change_upload(self, path: str):
        """수신자 엑셀을 고르거나 뺀다. 받는 분 이름·동호 칸이 보일지 달라지므로 입력칸을 다시 그린다."""
        self._set_upload(path, refresh=False)
        self._build_inputs(keep=True)
        self._refresh()

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
            self.upload_label.config(text=f"✅ {os.path.basename(path)}{n}",
                                     foreground="#1a7f37")
            self.upload_clear.pack(side="left")
        else:
            self.upload_label.config(text="")
            self.upload_clear.pack_forget()
        if refresh:
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
        # 차수로 찾아 둔 결과 통보일: 지금 차수와 같을 때만 쓴다
        found_round, found = getattr(self, "found", ("", {}))
        if found_round and found_round == self._round():
            dates.update({k: v for k, v in found.items() if k in getattr(self, "found_labels", [])})
        for key, link in self._link_specs(dates).items():
            values[key] = link.fallback
        words = self._link_words()
        values[LINK_FIELD + "_검색어"] = ", ".join(words)
        values[LINK_FIELD] = ", ".join(self._user_link_text(w) for w in words)
        return values, dates

    def _link_words(self) -> list[str]:
        """[🔗 관련 문서] 칸의 검색어들(쉼표로 나눔)."""
        e = getattr(self, "link_entry", None)
        try:
            raw = e.get() if e is not None and e.winfo_exists() else ""
        except tk.TclError:
            raw = ""
        return [w.strip() for w in re.split(r"[,，]+", raw) if w.strip()]

    @staticmethod
    def _user_link_text(word: str) -> str:
        return f"[문서링크: {word}]"

    @classmethod
    def _user_link(cls, word: str) -> homnet_draft.DocLink:
        """[🔗 관련 문서번호]에 적은 말 → 문서링크. 문서번호(…-1234, 1234)면 등록번호로 정확히 찾고,
        번호가 아니면(예전처럼) 문서 제목 일부로 찾는다."""
        m = DOC_NO_RE.match(word)
        if m:
            return homnet_draft.DocLink(m.group(1), (m.group(1),), cls._user_link_text(word), doc_no=m.group(1),
                                        year=m.group(2) or "")
        return homnet_draft.DocLink(word, (word,), cls._user_link_text(word))

    def _link_target(self) -> dtpl.Template | None:
        """서식에 {관련문서} 자리가 없을 때 관련 문서 줄을 넣을 안(1안)."""
        docs = self._docs()
        return docs[0] if docs else None

    def _link_body(self, t: dtpl.Template) -> str:
        """관련 문서를 적었고 서식에 {관련문서} 자리가 없으면 1안 본문 맨 위에 '관련:' 줄을 넣는다."""
        if (self._link_words() and "{" + LINK_FIELD + "}" not in t.body
                and not any(d.uses(LINK_FIELD) for d in self._docs()) and t is self._link_target()):
            return "관련: {" + LINK_FIELD + "}\n" + t.body
        return t.body

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
        body = dtpl.fill(self._link_body(t), values, dates, t.extras)
        if getattr(self, "proof_on", False):     # [올바른 문서 만들기]: 넣은 날짜·금액 등도 규칙대로
            title, body = proofread.fix_title(title)[0], proofread.fix(body)[0]
        return title, receiver, body

    def _proofread(self):
        """[올바른 문서 만들기]: 공문서 작성 규칙(날짜·시간·금액 표기, 항목 기호, 붙임, 끝 표시, 행정용어)에
        맞지 않는 곳을 찾아 고친다. 서식 본문도 고치고, 이후 넣는 값도 자동으로 맞춘다."""
        if self.current is None:
            return
        if self.edit_mode:                   # 본문을 직접 고치는 중이면 그 글을 고친다
            text = self.preview.get("1.0", "end").rstrip("\n")
            new, changes = proofread.fix(text)
            if changes:
                self.preview.delete("1.0", "end")
                self.preview.insert("1.0", new)
                self._tag_fields()
        else:
            changes = []
            for t, _r, b in self._all_filled():      # 지금 보이는 글(값을 넣은 본문) 기준으로 알려 준다
                changes += proofread.fix_title(t)[1] + proofread.fix(b)[1]
            touched = False
            for d in self._docs():                    # 서식 본문도 고쳐 둔다([고친 내용을 서식에 저장]으로 남길 수 있게)
                nb, c1 = proofread.fix(d.body)
                nt, c2 = proofread.fix_title(d.title)
                if c1 or c2:
                    d.body, d.title, touched = nb, nt, True
            self.proof_on = True
            self._refresh()
            if touched:
                self.save_btn.pack(side="left", padx=6, after=self.proof_btn)
        if changes:
            self.log(f"✔ 올바른 문서 만들기: {len(changes)}곳을 고쳤습니다.")
            self.mode_hint.config(text=f"✔ 공문서 규칙대로 {len(changes)}곳을 고쳤습니다.")
            messagebox.showinfo("올바른 문서 만들기", f"틀린 곳 {len(changes)}곳을 고쳤습니다.\n\n"
                                + proofread.summary(changes)
                                + ("" if self.edit_mode else
                                   "\n\n이 문서는 이제 이름·날짜를 바꿔 넣어도 같은 규칙으로 맞춰 줍니다.\n"
                                   "홈넷에 작성할 때 낱말이 줄 끝에서 끊기면 자간을 조절해 한 줄에 맞춥니다.\n"
                                   "다음에도 이대로 쓰려면 [고친 내용을 서식에 저장]을 누르세요."))
        else:
            self.mode_hint.config(text="✔ 공문서 규칙에 맞습니다.")
            messagebox.showinfo("올바른 문서 만들기", "✅ 고칠 곳이 없습니다. 공문서 작성 규칙에 맞습니다.\n\n"
                                "(날짜·시간·금액 표기, 항목 기호 순서, 붙임, '끝.' 표시, 행정용어를 살폈습니다)\n\n"
                                "홈넷에 작성할 때 낱말이 줄 끝에서 끊기면 자간을 조절해 한 줄에 맞춥니다.")

    def _tag_fields(self):
        """본문 직접 고치기 화면에서 {이름}·{날짜:…} 빈칸을 파란색으로."""
        start = "1.0"
        while True:
            pos = self.preview.search(r"\{[^{}]+\}", start, stopindex="end", regexp=True,
                                      count=(cnt := tk.IntVar()))
            if not pos:
                break
            end = f"{pos}+{cnt.get()}c"
            self.preview.tag_add("field", pos, end)
            start = end

    def _all_filled(self) -> list[tuple[str, str, str]]:
        """작성할 안마다 (제목, 수신자, 본문)."""
        return [self._filled(d) for d in self._docs()]

    def _mark_required(self):
        """꼭 넣어야 하는 칸: 비어 있으면 이름표를 빨갛게, 채우면 원래 색으로."""
        for lb, e in getattr(self, "required", []):
            if not lb.winfo_exists():
                continue
            lb.config(foreground="#c62828" if not e.get().strip() else BROWN)

    def _refresh(self):
        if self.current is None:
            return
        self._mark_required()
        if self.edit_mode:
            return
        filled = self._all_filled()
        title, receiver, body = filled[0]
        if getattr(self, "auto_label", None) is not None:
            _, dates = self._values()
            n = self._round()
            parts = [f"{lb} {dtpl.fmt_date(dates[lb], '년월' if lb in DATE_MONTH_AUTO else '일')}"
                     f" ({AUTO_DATE_NOTES.get(lb, '갱신월 말일')})"
                     for lb in self.auto_dates if lb in dates]
            parts += [f"{lb} {dtpl.fmt_date(dates[lb], '일')} ({n}차 결과 통보 문서 날짜)" if lb in dates
                      else f"{lb}: 차수를 넣고 Enter를 누르면 홈넷에서 찾아 넣습니다"
                      for lb in self.found_labels]
            self.auto_label.config(text="자동: " + ",  ".join(parts))
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
            # 본문을 펼친다(평소에는 접어 두고 제목·수신자·빈칸 안내만 보인다)
            self.preview_box.pack_configure(fill="both", expand=True)
            self.preview.pack(fill="both", expand=True, padx=6, pady=4, before=self.warn_label)
            self._fit_inputs()
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
            self.mode_btn.config(text="✔ 고치기 끝 (본문 닫기)")
            self.save_btn.pack(side="left", padx=6, after=self.mode_btn)
            self.mode_hint.config(text="")
        else:
            t.body = self.preview.get("1.0", "end").rstrip("\n")
            self.edit_mode = False
            self.mode_btn.config(text="✏ 본문 직접 고치기")
            self.save_btn.pack_forget()
            self.preview.pack_forget()
            self.preview_box.pack_configure(fill="x", expand=False)
            self._fit_inputs()
            self._refresh()
            self.mode_hint.config(text="")

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
            raise ValueError("단지기본정보의 '비공개 호'는 숫자로 적어 주세요. 예: 6") from None
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
            messagebox.showinfo("서식 선택", "[서식 고르기]에서 서식을 먼저 골라 주세요.")
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
            messagebox.showwarning("계정 필요", "단지기본정보에서 홈넷 아이디와 비밀번호를 넣어 주세요.")
            self._show_complex()
            return
        # 차수로 찾는 결과 통보일을 아직 못 찾았으면 먼저 찾는다
        if self.found_labels and self.found[0] != self._round():
            if not self._round():
                messagebox.showwarning("차수 필요", "차수를 숫자로 넣어 주세요. 예: 34")
                self.text_widgets["차수"].focus_set()
                return
            self.log(f"{self._round()}차 날짜를 홈넷에서 찾은 뒤 이어서 작성합니다...")
            self._lookup_round(then=self._create_draft)
            return
        try:
            parts = []
            dates = self._values()[1]
            for d, (t, r, b), up in zip(docs, filled, uploads):
                links = self._doc_links(d, dates)
                for link in links:      # 관련 문서번호 자리는 홈넷 [문서링크]로 넣는다
                    b = b.replace(link.fallback, link.mark, 1)
                parts.append(homnet_draft.DraftPart(self._doc_info(t), r, dtpl.to_html(b, hwp=True), up,
                                                    doc_links=links, external_receiver=d.external_receiver,
                                                    fit_spacing=getattr(self, "proof_on", False)))
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
        file_name = self.current.file_name
        renewal = dates.get("갱신월") if "갱신월" in self.date_widgets else None

        def ok(todo):
            self._write_history(title, receiver, "작성완료(상신 전)")
            self._remember_renewal(file_name, renewal)
            self._carry_over(docs, values_now)
            steps = "\n".join(f"{i}. {s}" for i, s in enumerate(todo, 1))
            self.log("✅ 표준기안문 작성을 마쳤습니다. 브라우저에서 확인하세요.")
            messagebox.showinfo("작성 완료", f"브라우저에서 다음을 마저 해 주세요.\n\n{steps}")

        def err(ex):
            self._write_history(title, receiver, f"실패: {ex}")
            messagebox.showerror("작성 실패", f"{ex}\n\n[브라우저로 미리보기]에서 본문을 복사해 "
                                             "직접 붙여 넣을 수도 있습니다.")

        self.run_bg(work, ok, err)

    def _remember_renewal(self, file_name: str, month: dt.date | None) -> None:
        """작성을 마친 공문의 갱신월을 서식별로 저장한다. 다음에 그 서식을 열면 이 달이 들어간다."""
        if month is None:
            return
        self.cfg.setdefault("renewal_months", {})[file_name] = f"{month:%Y-%m}"
        self._save_settings()

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

    # ================= 대장 문서 모으기 =================
    def _collect_docs(self):
        """기록물등록대장 문서를 [다음]으로 넘기며 '수집' 폴더에 받는다.
        고른 것에 따라 PDF(000으로 가림)·첨부파일(PDF는 000으로 가림)·서식('수집한 서식')을 만든다."""
        hid, hpw = self.homnet_id.get().strip(), self.homnet_pw.get()
        if not (hid and hpw):
            messagebox.showwarning("계정 필요", "단지기본정보에서 홈넷 아이디와 비밀번호를 넣어 주세요.")
            self._show_complex()
            return
        import collector
        prev_dir, prev = collector.unfinished(paths.sub_dir("수집"))
        resume = False
        if prev_dir and prev.get("settings"):
            c = prev.get("counts") or {}
            ans = messagebox.askyesnocancel("이어 받기", (
                "지난번 대장 문서 받기가 끝까지 가지 못하고 멈췄습니다.\n\n"
                f"  받은 폴더: {os.path.basename(prev_dir)}\n"
                f"  {prev.get('done', 0)}/{prev.get('count', 0)}개째까지 봄 · 문서 {c.get('saved', 0)}개 저장\n"
                f"  마지막으로 본 문서: {prev.get('title') or '-'}\n\n"
                "[예] 멈춘 곳 다음 문서부터 이어 받기(같은 폴더·같은 설정)\n"
                "[아니요] 처음부터 새로 받기\n"
                "[취소] 그만두기"))
            if ans is None:
                return
            if ans:
                resume, opt = True, prev["settings"]
            else:
                collector.mark_finished(prev_dir)
        if not resume:
            dlg = CollectDialog(self.root)
            self.root.wait_window(dlg)
            opt = dlg.result
            if not opt:
                return
        vpn_id, vpn_pw = self.vpn_id.get().strip(), self.vpn_pw.get()
        dest = os.path.join(paths.template_dir(), dtpl.COLLECTED_DIR)
        info = self._info_values()
        dtpl.KNOWN_INFO = info                     # 관리소·단지명·담당자·전화번호 글자는 {…} 칸으로 바꾼다
        keep_phones = [info.get("전화번호", "")]   # 관리소 대표번호는 PDF에서 가리지 않는다
        stop = threading.Event()
        box = self._collect_progress(stop)

        def log(m):
            self.log(m)
            self.q.put(("call", lambda m=m: box["show"](m)))

        def work():
            import collector
            import session
            session.ensure_tunnel(self.log, vpn_id, vpn_pw)
            if not homnet.driver_alive(self.driver):
                self.driver = None
                self.driver = session.open_homnet(hid, hpw, self.log)
            out = prev_dir if resume else os.path.join(paths.sub_dir("수집"),
                                                       dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
            if stop.is_set():
                raise RuntimeError("시작하기 전에 중단했습니다.")
            res = collector.collect(self.driver, out, opt["count"], log,
                                    only_internal=opt["only_internal"], password=hpw,
                                    keyword=opt["keyword"], auto_open=True, pdf=opt["pdf"],
                                    attachments=opt["attachments"], extra=opt["extra"], keep_phones=keep_phones,
                                    stop=stop, resume=resume, settings=opt, binders=opt.get("binders", ()), year=opt.get("year"),
                                    dedupe=opt.get("dedupe", True))
            res["made"] = []
            if opt["register"] and res["names"]:
                st = collector.load_progress(out)               # 이어 받기: 앞서 서식으로 넣은 문서는 빼고
                done = set(st.get("registered") or [])
                todo = [x for x in res["names"] if x not in done]
                try:
                    res["made"] = collector.import_to_templates(out, todo, dest, log, opt["area"])
                finally:
                    st["registered"] = sorted(done | set(todo))
                    collector.save_progress(out, st)
            return res

        def ok(res):
            box["close"]()
            made = res.get("made") or []
            att = res.get("attach") or {}
            self.log(f"✅ 대장 문서 {res['saved']}개 받음 · PDF {res.get('pdfs', 0)}개 · 첨부 {att.get('files', 0)}개"
                     f" · 서식 {len(made)}개 ({res['dir']})")
            if made:
                self._load_templates()
                done = {os.path.normcase(os.path.abspath(p)) for p in made}
                mine = [t for t in self.templates if os.path.normcase(os.path.abspath(t.path)) in done]
                areas = [t.area for t in mine]
                self._set_area(max(set(areas), key=areas.count) if areas else opt["area"])
                self.picker.opened |= {"수집한 서식", "수집한 서식(수신자 있음)"} | {t.bundle for t in mine}
                self._show_picker()
            head = []
            if res.get("error"):
                head.append(f"⚠ 받는 중 오류가 나서 멈췄습니다: {res['error']}\n"
                            "   그때까지 받은 문서는 저장했습니다.")
            if res.get("error") or res.get("stopped"):
                head.append(f"   {res.get('done', 0)}/{res.get('count', 0)}개째까지 봤습니다. "
                            "다시 [대장 문서 받기]를 누르면 멈춘 곳 다음부터 이어 받습니다.\n")
            if res.get("resumed"):
                head.append("⏩ 지난번 멈춘 곳부터 이어 받았습니다(아래 수는 앞서 받은 것까지 합친 수).")
            lines = head + [("⏹ 중간에 그만 받았습니다. " if res.get("stopped") else "") + f"{res['saved']}개 문서를 받았습니다.",
                     f"  - 보안 문서를 비밀번호로 연 것: {res.get('unlocked', 0)}개",
                     f"  - 받지 않음: '조회' 화면 {res.get('views', 0)}개, 열지 못한 보안 문서 {res.get('encrypted', 0)}개"
                     + (f", 내부결재 아님 {res['skipped']}개" if res.get("skipped") else "")]
            if opt["pdf"]:
                lines.append(f"  - PDF {res.get('pdfs', 0)}개 (PDF 폴더 · 이름·동호수·연락처는 000)")
            if opt["attachments"]:
                lines.append(f"  - 첨부파일 {att.get('files', 0)}개 (첨부 폴더 · PDF {att.get('pdf', 0)}개에서 "
                             f"{att.get('masked', 0)}곳을 000으로 가림)")
                if att.get("scanned"):
                    lines.append("  ⚠ 스캔(그림)이라 가리지 못한 PDF: " + ", ".join(att["scanned"][:5])
                                 + (" …" if len(att["scanned"]) > 5 else ""))
                if att.get("locked"):
                    lines.append("  ⚠ 암호가 걸려 가리지 못한 PDF(그대로 둠): " + ", ".join(att["locked"][:5])
                                 + (" …" if len(att["locked"]) > 5 else ""))
                if att.get("other"):
                    lines.append("  ⚠ PDF가 아니라 가리지 않은 파일(한글·엑셀 등): " + ", ".join(att["other"][:5])
                                 + (" …" if len(att["other"]) > 5 else ""))
            if res.get("off_binder"):
                lines.append(f"  - 고른 편철이 아니라 건너뜀: {res['off_binder']}개")
            if res.get("similar"):
                lines.append(f"  - 비슷한 제목(날짜·월만 다름)이라 건너뜀: {res['similar']}개")
            if res.get("unlocked"):
                lines.append(f"  - 보안 문서 {res['unlocked']}개는 비밀번호로 열고 인적사항을 OOO으로 바꿔 저장")
            if res.get("by_binder"):
                lines.append("  - 편철별: " + ", ".join(f"{b} {len(v)}건" for b, v in sorted(res["by_binder"].items()))
                             + "\n    (받은 폴더의 '편철별' 폴더 · 편철별_목록.csv)")
            if made:
                where = (f"[{opt['area']}] 분야" if opt["area"] in CollectDialog.AREAS[1:]
                         else "편철에 맞는 분야(임대·시설·주거복지·주택관리)")
                lines.append(f"\n서식 {len(made)}개를 {where}의 '기타 공문 → 편철 · (편철 이름)' 묶음에 넣었습니다.\n"
                             "이름·동호수·연락처는 공문 쓸 때 넣는 칸이 되었고, 그 밖의 사람 이름은 000으로 바꿨습니다.\n"
                             "문장 속 개인정보가 남아 있을 수 있으니 쓰기 전에 한 번 훑어봐 주세요.")
            lines.append(f"\n받은 폴더: {res['dir']}")
            if messagebox.askyesno("받기 완료" if not (res.get("error") or res.get("stopped")) else "받기 멈춤",
                                   "\n".join(lines) + "\n\n받은 폴더를 열까요?"):
                os.startfile(res["dir"])

        def err(ex):
            box["close"]()
            messagebox.showerror("받기 실패", f"{ex}\n\n받다가 멈췄다면 받은 문서는 저장되어 있습니다. "
                                 "다시 [대장 문서 받기]를 누르면 멈춘 곳부터 이어 받을지 묻습니다.")

        if self.busy:
            box["close"]()
        self.run_bg(work, ok, err)

    def _collect_progress(self, stop: threading.Event) -> dict:
        """대장 문서 받는 동안 띄우는 작은 창: 지금 하는 일과 [■ 그만 받기] 단추.
        누르면 지금 문서까지만 받고 멈춘 뒤, 받은 문서는 PDF·서식으로 정리한다."""
        win = tk.Toplevel(self.root)
        win.title("대장 문서 받는 중")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        f = ttk.Frame(win, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="홈넷 대장 문서를 받고 있습니다…", font=FONT_B).pack(anchor="w")
        now = tk.StringVar(value="홈넷에 로그인하는 중")
        ttk.Label(f, textvariable=now, width=64, foreground="#555").pack(anchor="w", pady=(6, 10))
        bar = ttk.Progressbar(f, mode="indeterminate", length=420)
        bar.pack(fill="x")
        bar.start(15)

        def halt():
            if stop.is_set():
                return
            stop.set()
            btn.config(state="disabled", text="멈추는 중… (지금 문서까지 받고 정리합니다)")
            self.log("⏹ [그만 받기]를 눌렀습니다. 지금 문서까지 받고 멈춥니다.")

        btn = ttk.Button(f, text="■ 그만 받기", command=halt)
        btn.pack(anchor="e", pady=(10, 0))
        win.protocol("WM_DELETE_WINDOW", halt)

        def show(m: str):
            if win.winfo_exists():
                now.set(m.strip()[:70])

        def close():
            if win.winfo_exists():
                bar.stop()
                win.destroy()
        return {"show": show, "close": close, "win": win, "halt": halt}

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
            "  왼쪽 메뉴 [단지기본정보]에 관리소·단지 정보(평형·업체 포함)와 홈넷 계정(밖에서는 VPN 계정도)을\n"
            "  넣고 [저장하고 다음].\n\n"
            "공문 쓸 때마다\n"
            "  1. 왼쪽 메뉴 [서식 고르기]에서 서식을 고릅니다(🔍로 검색 가능).\n"
            "  2. 받는 분 이름과 날짜를 넣습니다. 빨간 * 표시는 꼭 넣어야 하는 칸입니다.\n"
            "     날짜 칸 ▼를 누르면 달력이 나옵니다.\n"
            "     여러 명에게 보낼 때는 [📎 업로드할 엑셀 고르기]로 수신자 엑셀을 고릅니다.\n"
            "  3. 아래 확인하기에서 제목·수신자를 봅니다. 본문은 [✏ 본문 직접 고치기]를 누르면 열립니다.\n"
            "     [✔ 올바른 문서 만들기]를 누르면 날짜·시간·금액 표기, 항목 번호, 붙임, '끝.' 표시, 행정용어를\n"
            "     공문서 규칙대로 고쳐 줍니다.\n"
            "     [🔗 관련 문서번호]에 문서번호(예: 가나관리소-1234, 지난해 문서는 가나관리소-12(2025. 1. 2.))를\n"
            "     적으면 그 문서를 [문서링크]로 본문에 넣습니다.\n"
            "  4. [홈넷에 자동 작성]을 누르면 브라우저가 열리고\n"
            "     전자결재 → 문서작성 → 표준기안문에 제목·수신자·본문을 넣습니다.\n"
            "  5. 브라우저에서 내용을 확인하고 [결재올림]은 직접 누릅니다.\n\n"
            "대장 문서 받기\n"
            "  처음 화면 [대장 문서 받기](또는 [파일 → 홈넷 대장 문서 받기])를 누르면 기록물등록대장의 문서를\n"
            "  자동으로 열어 받습니다. PDF·첨부파일은 이름·동호수·연락처를 000으로 가리고, 서식으로 넣으면\n"
            "  이름·동호수·연락처가 공문 쓸 때 넣는 칸이 됩니다. 보안 문서는 홈넷 비밀번호로 열어 봅니다.\n"
            "  받는 동안 뜨는 작은 창의 [■ 그만 받기]를 누르면 지금 문서까지만 받고 멈춥니다.\n\n"
            "※ 브라우저 창은 작성이 끝날 때까지 닫지 마세요."))

    def _help(self, text: str) -> None:
        if text not in self.help_lines:
            self.help_lines.append(text)

    def _show_page_help(self):
        """머리 [ⓘ 도움말]: 공문 작성 화면이면 이 공문의 설명을 한 번에, 아니면 사용 방법."""
        t = self.current
        if self._overlay_shown() or t is None:
            self._show_help()
            return
        old = getattr(self, "help_win", None)
        if old is not None and old.winfo_exists():
            old.destroy()
        win = self.help_win = tk.Toplevel(self.root)
        win.title("도움말")
        win.transient(self.root)
        win.configure(bg="white")
        tk.Label(win, text=f"ⓘ  {t.label}", font=(ui_kit.FONT, 12, "bold"), bg="white", fg=BROWN,
                 anchor="w", justify="left", wraplength=int(560 * self.k)).pack(fill="x", padx=18, pady=(14, 6))
        txt = tk.Text(win, wrap="word", font=FONT, bg="white", relief="flat", bd=0,
                      width=70, height=1, padx=4, spacing1=3, spacing3=3)
        txt.pack(fill="both", expand=True, padx=14)
        txt.tag_configure("h", font=FONT_B, foreground=ACCENT, spacing1=10)
        txt.tag_configure("li", lmargin1=8, lmargin2=22)
        txt.insert("end", "이 공문 넣는 법\n", "h")
        for line in self.help_lines:
            txt.insert("end", "•  " + line + "\n", "li")
        txt.insert("end", "확인하고 작성하기\n", "h")
        for line in ("[✏ 본문 직접 고치기]를 누르면 본문이 열립니다. 파란 글씨 { } 는 위에 넣은 이름·날짜로 "
                     "바뀌는 자리이고, 표는 | 로 칸을 나눕니다.",
                     "고친 내용은 이번 작성에만 쓰입니다. 계속 쓰려면 [고친 내용을 서식에 저장]을 누릅니다.",
                     "[홈넷에 자동 작성]은 표준기안문에 제목·수신자·본문을 넣고 멈춥니다. "
                     "[결재올림]은 확인 후 직접 눌러 주세요.",
                     "브라우저 창은 작성이 끝날 때까지 닫지 마세요."):
            txt.insert("end", "•  " + line + "\n", "li")
        txt.update_idletasks()
        rows = txt.count("1.0", "end", "displaylines")
        rows = rows[0] if isinstance(rows, tuple) else (rows or 20)
        txt.config(height=min(28, rows + 1), state="disabled")
        ttk.Button(win, text="닫기", command=win.destroy).pack(pady=(4, 12))
        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + self.root.winfo_width() - win.winfo_width() - 40
        win.geometry(f"+{max(0, x)}+{self.root.winfo_rooty() + 60}")
        win.focus_set()

    def _show_template_help(self):
        messagebox.showinfo("서식 만드는 법", (
            "서식은 [파일 → 서식 폴더 열기]의 txt 파일입니다. 메모장으로 고치거나 복사해 새로 만들 수 있습니다.\n\n"
            "맨 위 머리말\n"
            "  제목: 공문 제목\n  수신자: {주소} {이름} 귀하   (내부결재면 '내부결재')\n"
            "  구분: 목록에서 묶을 이름\n  ---   ← 이 줄 아래가 본문\n\n"
            "빈칸\n"
            "  {이름} {주소} — 공문마다 입력\n"
            "  {관련문서} — [🔗 관련 문서번호]에 적은 문서를 [문서링크]로 넣을 자리(없으면 1안 맨 위 '관련:' 줄)\n"
            "  {단지명} {담당자} {전화번호} {관리소} — 기본정보에서 자동\n"
            "  {날짜:제출기한} → 2026년 11월 6일(금)\n"
            "  {날짜:만료일|일} → 2026년 11월 6일   |월 → 2026년 11월   |점 → 2026.11.06.\n"
            "  {입력:차수} — 직접 적는 칸   {숫자:수량=10} — 숫자(처음 값 10)   {금액:청구액} — 금○원(금…원)\n"
            "  {계산:금액=수량*단가} — 다른 칸으로 계산   {단지:관리소명} — 단지기본정보의 값\n"
            "  {선택:형별=36|46|51|59} — 체크해서 고르는 칸(여러 개 → '36, 51')   "
            "표 줄의 {선택값:형별} — 고른 것마다 그 줄을 하나씩\n"
            "  머리말 '분야: 시설' → 시작 화면 분야,  '주기: 매월'·'주기: 매주' → 매월·매주 작성 묶음\n\n"
            "표\n"
            "  | 구분 | 내용 |   ← 첫 줄은 머리글\n"
            "  칸 안 줄바꿈 <br>, 위 칸과 합치기 ^, 왼쪽 칸과 합치기 <"))

    def _toggle_maximize(self):
        self.root.state("normal" if self.root.state() == "zoomed" else "zoomed")

    # ================= 환경 설정: 디자인 =================
    FONT_DEFAULT = "디자인 기본 글씨체"
    SAMPLE = "가나다라 공문 자동작성 2026. 11. 16."

    def _build_tab_design(self):
        """디자인 5가지 + 내 사진 디자인과 글씨체를 고르는 화면. 저장하면 다시 시작해 적용한다."""
        from tkinter import font as tkfont
        tab = ttk.Frame(self.nb, padding=(18, 12))
        self.nb.add(tab, text="  환경 설정  ")
        saved = self.cfg.get("design") or {}
        self.design_name = tk.StringVar(value=ui_kit.DESIGN)
        have = set(tkfont.families(self.root))
        fonts = [f for f in ui_kit.FONT_CHOICES if f in have] or ["맑은 고딕"]
        self.design_font = tk.StringVar(value=saved.get("font") if saved.get("font") in fonts else self.FONT_DEFAULT)
        # 내 사진 디자인: 고른 사진 파일과 거기서 뽑은 색 (저장한 적 있으면 그대로 보여 준다)
        photo = saved.get("photo", "") if saved.get("name") == ui_kit.PHOTO_DESIGN else ""
        self.photo_path = photo if photo and os.path.isfile(photo) else ""
        self.photo_colors = saved.get("colors") if self.photo_path else None
        self.photo_new = False
        self._photo_thumb = None

        ttk.Label(tab, text="디자인", font=(ui_kit.FONT, 13, "bold")).pack(anchor="w")
        ttk.Label(tab, foreground=SUB, text="마음에 드는 디자인을 누르고 [저장하고 다시 시작]을 누르면 "
                                             "프로그램이 다시 켜지면서 바뀝니다. 작성 중인 내용은 저장해 두세요.\n"
                                             "'내 사진'을 누르면 사진을 골라, 사진의 색으로 화면을 꾸미고 "
                                             "첫 화면 배너에 사진을 깝니다.").pack(anchor="w", pady=(2, 10))
        grid = ttk.Frame(tab)
        grid.pack(anchor="w")
        self.design_cards = {}
        for i, name in enumerate(list(ui_kit.DESIGNS) + [ui_kit.PHOTO_DESIGN]):
            card = tk.Canvas(grid, width=int(230 * self.k), height=int(150 * self.k), highlightthickness=0,
                             bg=ttk.Style().lookup("TFrame", "background") or "#fafafa", cursor="hand2")
            card.grid(row=i // 3, column=i % 3, padx=(0, 14), pady=(0, 14))
            card.bind("<Button-1>", lambda _e, n=name: self._pick_design(n))
            self.design_cards[name] = card
        ff = ttk.Frame(tab)
        ff.pack(anchor="w", pady=(4, 0))
        ttk.Label(ff, text="글씨체", font=FONT_B).pack(side="left")
        cb = ttk.Combobox(ff, state="readonly", width=20, textvariable=self.design_font,
                          values=[self.FONT_DEFAULT] + fonts)
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._draw_design_cards())
        self.photo_btn = ttk.Button(ff, text="사진 바꾸기", command=self._choose_photo)
        self.design_sample = tk.Label(tab, text=self.SAMPLE, anchor="w", bg="white", fg=BROWN, padx=12, pady=8)
        self.design_sample.pack(anchor="w", fill="x", pady=(10, 0))
        b = ttk.Frame(tab)
        b.pack(anchor="w", pady=(14, 0))
        ttk.Button(b, text="저장하고 다시 시작", style="Accent.TButton", command=self._save_design).pack(side="left")
        ttk.Button(b, text="처음 디자인으로", command=lambda: (self.design_font.set(self.FONT_DEFAULT),
                                                          self._pick_design(ui_kit.DEFAULT_DESIGN))
                   ).pack(side="left", padx=8)
        self._draw_design_cards()

    def _design_data(self, name: str) -> dict:
        """디자인 이름의 색 묶음. 내 사진은 사진에서 뽑은 색(사진이 없으면 기본 색)."""
        if name == ui_kit.PHOTO_DESIGN:
            return self.photo_colors or ui_kit.DESIGNS[ui_kit.DEFAULT_DESIGN]
        return ui_kit.DESIGNS[name]

    def _design_font(self, name: str) -> str:
        f = self.design_font.get()
        return self._design_data(name)["font"] if f == self.FONT_DEFAULT else f

    def _pick_design(self, name: str):
        if name == ui_kit.PHOTO_DESIGN and not self.photo_path:
            self._choose_photo()
            return
        self.design_name.set(name)
        self._draw_design_cards()

    def _choose_photo(self) -> bool:
        """사진 파일을 골라 색을 뽑는다. 고르면 True."""
        path = filedialog.askopenfilename(
            parent=self.root, title="디자인에 쓸 사진 고르기",
            filetypes=[("사진", "*.jpg *.jpeg *.png *.bmp *.gif *.webp"), ("모든 파일", "*.*")])
        if not path:
            return False
        try:
            colors = ui_kit.palette_from_photo(path)
        except Exception as e:
            messagebox.showerror("사진 고르기", f"사진을 읽지 못했습니다.\n{e}", parent=self.root)
            return False
        self.photo_path, self.photo_colors, self.photo_new = path, colors, True
        self.design_name.set(ui_kit.PHOTO_DESIGN)
        self._draw_design_cards()
        return True

    def _photo_preview(self, w: int, h: int):
        """미리보기 카드의 배너 자리에 넣을 작은 사진(첫 화면 배너처럼 왼쪽을 어둡게 덮는다)."""
        try:
            from PIL import Image, ImageOps, ImageTk
            src = ui_kit._photo(self.photo_path)
            pic = ImageOps.fit(src, (w, h), method=Image.LANCZOS).convert("RGBA")
            fade = Image.linear_gradient("L").rotate(90).resize((w, h)).point(lambda p: int(215 - p * 0.55))
            cover = Image.new("RGBA", (w, h), ui_kit.rgb(self.photo_colors["hero"][1]))
            cover.putalpha(fade)
            pic.alpha_composite(cover)
            return ImageTk.PhotoImage(pic, master=self.root)
        except Exception:
            return None

    def _draw_design_cards(self):
        """디자인마다 작은 미리보기: 바탕·왼쪽 메뉴·배너·단추·글자."""
        k = self.k
        for name, cv in self.design_cards.items():
            d = self._design_data(name)
            picked = name == self.design_name.get()
            font = self._design_font(name)
            cv.delete("all")
            W, H = int(cv["width"]), int(cv["height"])
            is_photo = name == ui_kit.PHOTO_DESIGN
            if is_photo and not self.photo_path:       # 아직 사진을 안 고름: 사진 고르기 칸
                cv.create_rectangle(3, 3, W - 3, H - 3, fill="#ffffff", outline="#9fb0cc", dash=(5, 3))
                cv.create_text(W / 2, H / 2 - 18 * k, text="", fill=ui_kit.PRIMARY, font=("Segoe MDL2 Assets", 18))
                cv.create_text(W / 2, H / 2 + 12 * k, text="내 사진으로 꾸미기", fill=ui_kit.TEXT,
                               font=(ui_kit.FONT, 11, "bold"))
                cv.create_text(W / 2, H / 2 + 32 * k, text="눌러서 사진 고르기", fill=SUB, font=(ui_kit.FONT, 8))
                continue
            ui_kit.round_rect(cv, 2, 2, W - 2, H - 2, 12 * k, fill=d["page"],
                       outline=d["primary"] if picked else d["border"], width=3 if picked else 1)
            cv.create_rectangle(10 * k, 10 * k, 52 * k, H - 38 * k, fill=d["sidebar"], outline=d["border"])
            for j in range(3):
                y = 22 * k + j * 18 * k
                cv.create_rectangle(16 * k, y, 46 * k, y + 8 * k, outline="",
                                    fill=d["soft"] if j == 0 else d["line"])
            h0, h1 = d["hero"]
            thumb = self._photo_preview(int(W - 70 * k), int(36 * k)) if is_photo else None
            if thumb:
                self._photo_thumb = thumb              # 붙잡아 두지 않으면 그림이 사라진다
                cv.create_image(60 * k, 10 * k, anchor="nw", image=thumb)
            else:
                cv.create_rectangle(60 * k, 10 * k, (60 + 80) * k, 46 * k, fill=h0, outline="")
                cv.create_rectangle((60 + 80) * k, 10 * k, W - 10 * k, 46 * k, fill=h1, outline="")
            cv.create_text(68 * k, 28 * k, anchor="w", text="공문 작성", fill="#ffffff",
                           font=(font, 10, "bold"))
            cv.create_rectangle(60 * k, 54 * k, W - 10 * k, H - 38 * k, fill="#ffffff", outline=d["border"])
            cv.create_text(68 * k, 66 * k, anchor="w", text="가나다 공문", fill=d["text"], font=(font, 9))
            cv.create_text(68 * k, 82 * k, anchor="w", text="설명 글자", fill=d["sub"], font=(font, 8))
            ui_kit.round_rect(cv, W - 64 * k, 72 * k, W - 16 * k, 94 * k, 8 * k, fill=d["primary"], outline="")
            cv.create_text(W - 40 * k, 83 * k, text="확인", fill="#ffffff", font=(font, 8, "bold"))
            cv.create_text(14 * k, H - 19 * k, anchor="w", text=("✔ " if picked else "") + name,
                           fill=d["primary_d"] if picked else d["text"], font=(font, 11, "bold"))
            cv.create_text(W - 12 * k, H - 19 * k, anchor="e", text=font, fill=d["sub"], font=(font, 8))
        n = self.design_name.get()
        self.design_sample.config(text=f"{self.SAMPLE}   ·   {n} / {self._design_font(n)}",
                                  font=(self._design_font(n), 12), fg=self._design_data(n)["text"])
        if self.photo_path and not self.photo_btn.winfo_ismapped():   # 사진을 고른 뒤에는 바꾸기 단추
            self.photo_btn.pack(side="left", padx=(16, 0))

    def _keep_photo(self) -> str:
        """고른 사진을 설정 폴더에 줄여 복사해 둔다(원본을 옮기거나 지워도 디자인이 유지되게)."""
        from PIL import Image
        dst = os.path.join(paths.user_dir(), "design_photo.jpg")
        with Image.open(self.photo_path) as im:
            im = im.convert("RGB")
            im.thumbnail((2400, 2400))
            im.save(dst, "JPEG", quality=90)
        return dst

    def _save_design(self):
        name, f = self.design_name.get(), self.design_font.get()
        design = {"name": name, "font": "" if f == self.FONT_DEFAULT else f}
        same = design == {"name": ui_kit.DESIGN, "font": (self.cfg.get("design") or {}).get("font", "")}
        if same and not (name == ui_kit.PHOTO_DESIGN and self.photo_new):
            messagebox.showinfo("환경 설정", "지금 쓰는 디자인과 같습니다.", parent=self.root)
            return
        if not messagebox.askyesno("디자인 바꾸기", f"'{name}' 디자인({self._design_font(name)})으로 바꾸고\n"
                                   "프로그램을 다시 시작할까요?", parent=self.root):
            return
        if name == ui_kit.PHOTO_DESIGN:
            try:
                photo = self._keep_photo() if self.photo_new else self.photo_path
            except Exception as e:
                messagebox.showerror("디자인 바꾸기", f"사진을 저장하지 못했습니다.\n{e}", parent=self.root)
                return
            design.update(photo=photo, colors=self.photo_colors)
        self.cfg["design"] = design
        self._on_close()                       # 설정을 저장하고 창을 닫는다(디자인도 함께 저장)
        try:
            settings_store.set_value("design", design)
        except Exception:
            pass
        import subprocess
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable], cwd=paths.program_dir())
        else:
            subprocess.Popen([sys.executable, os.path.abspath(__file__)], cwd=paths.program_dir())

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
