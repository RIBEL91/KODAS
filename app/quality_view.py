"""품질평가서 작성 창.

- 왼쪽: 올해 평가표(초안)의 항목 목록 — 번호·평가항목·배점·점수·증빙·평가 근거
- 오른쪽 위: 고른 항목의 번호·평가항목(평가기준·준비서류·평가 근거·평가점수 칸은 숨김)
- 오른쪽 아래: [전년도 품질평가 초안] 엑셀과 [품질평가 초안 작성] 엑셀을 넣는 칸.
  [대장관리 참고해 초안 작성]을 누르면 전년도 근거의 문서들과 같은 종류의 올해 문서를
  홈넷 기록물등록대장에서 찾아 초안 엑셀의 평가 근거(I열)에 적는다(quality_draft).
평가표는 지사에서 내려오는 양식 그대로 쓰고, 점수(G열)·근거(I열)만 저장한다.
"""
import datetime as dt
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import paths
import quality_draft as qd
import quality_eval as qe
import ui_kit

ALL = "전체 항목"
MINE = "★ 내가 고른 항목"
MAX_EXTRA = 5          # 근거 보태기 파일 최대 개수
EXTRA_YEARS = 5        # 근거 보태기는 최근 5개년도 평가표만
REPORT4 = "임대운영 · 본지사 협조도 (4권)"


def item_key(it) -> str:
    """항목을 해가 바뀌어도 같게 가리키는 열쇠: 부문|번호|같은 번호 안 순서."""
    return f"{it.part}|{it.no}|{it.seq}"


class PickItemsDialog(tk.Toplevel):
    """[내 항목 고르기]: 부문 › 항목을 눌러 ☑/☐를 바꾼다. 부문 줄을 누르면 그 부문 전체를 바꾼다.
    [저장]하면 self.result = 고른 열쇠 집합, 취소하면 None."""

    def __init__(self, master, items, chosen: set, who: str, k: float = 1.0):
        super().__init__(master)
        self.title("내 항목 고르기")
        self.transient(master)
        self.geometry(f"{int(640 * k)}x{int(640 * k)}")
        self.items, self.chosen, self.result = items, set(chosen), None
        ttk.Label(self, text=f"담당자: {who}   —   보고 싶은 항목을 눌러 ☑ 표시하세요 (부문 줄을 누르면 부문 전체)",
                  padding=(12, 10, 12, 4), wraplength=int(600 * k)).pack(anchor="w")
        box = ttk.Frame(self, padding=(12, 0))
        box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(box, show="tree", selectmode="none")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.parts: dict[str, list] = {}
        for it in items:
            self.parts.setdefault(it.part, []).append(it)
        for part, its in self.parts.items():
            pid = "p:" + part
            self.tree.insert("", "end", iid=pid, open=True)
            for it in its:
                self.tree.insert(pid, "end", iid="i:" + item_key(it))
        self._draw()
        self.tree.bind("<Button-1>", self._click)
        bot = ttk.Frame(self, padding=(12, 10))
        bot.pack(fill="x")
        ttk.Button(bot, text="모두 고르기", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(bot, text="모두 빼기", command=lambda: self._set_all(False)).pack(side="left", padx=6)
        self.count = ttk.Label(bot)
        self.count.pack(side="left", padx=10)
        ttk.Button(bot, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(bot, text="저장", style="Accent.TButton", command=self._ok).pack(side="right", padx=6)
        self._draw()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    def _draw(self):
        for part, its in self.parts.items():
            n = sum(item_key(i) in self.chosen for i in its)
            mark = "☑" if n == len(its) else ("◩" if n else "☐")
            self.tree.item("p:" + part, text=f"{mark}  {part}  ({n}/{len(its)})")
            for it in its:
                on = item_key(it) in self.chosen
                self.tree.item("i:" + item_key(it), text=f"{'☑' if on else '☐'}  {it.label}")
        if hasattr(self, "count"):
            self.count.config(text=f"{len(self.chosen & {item_key(i) for i in self.items})}개 골랐습니다")

    def _click(self, e):
        iid = self.tree.identify_row(e.y)
        if not iid or self.tree.identify_element(e.x, e.y) == "Treeitem.indicator":
            return            # 접기/펼치기 화살표는 그대로
        if iid.startswith("p:"):
            keys = {item_key(i) for i in self.parts[iid[2:]]}
            if keys <= self.chosen:
                self.chosen -= keys
            else:
                self.chosen |= keys
        else:
            self.chosen ^= {iid[2:]}
        self._draw()
        return "break"

    def _set_all(self, on: bool):
        keys = {item_key(i) for i in self.items}
        self.chosen = (self.chosen | keys) if on else (self.chosen - keys)
        self._draw()

    def _ok(self):
        self.result = self.chosen & {item_key(i) for i in self.items}
        self.destroy()


def _fmt(v) -> str:
    if v is None:
        return ""
    return f"{v:g}"


def _blank(it) -> bool:
    """점수를 아직 넣지 않은 항목(가감점은 해당 없으면 비워 두는 게 보통이라 뺀다)."""
    return it.score is None and it.part != "가감점"


def _cache_dir() -> str:
    d = os.path.join(paths.user_dir(), "품질평가_대장")
    os.makedirs(d, exist_ok=True)
    return d


class SheetPicker(tk.Toplevel):
    """품질평가 평가표 엑셀만 보여 주는 고르기 창. 바탕화면·문서·다운로드(와 지금 넣은 파일의 폴더)를
    뒤져 '항목별평가표' 시트가 있는 엑셀만 늘어놓는다(파일 이름에 '품질평가'가 없어도 된다).
    [다른 위치에서 찾기…]로 고른 파일도 평가표가 아니면 넣지 않는다. 고른 경로는 result."""

    def __init__(self, master, title: str, folders: list[str], k: float = 1.0):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.geometry(f"{int(820 * k)}x{int(420 * k)}")
        self.result = ""
        self._found = False         # 찾기를 마쳤는지
        self._rows: list = []       # (경로, 평가년도, 고친 때) — 작업 스레드가 쌓는다
        self._shown = 0
        self._order: list = []      # 목록에 넣은 차례(고친 때 최근 순)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        self.msg = ttk.Label(f, text="품질평가 평가표 엑셀을 찾는 중입니다…", foreground=ui_kit.SUB)
        self.msg.pack(anchor="w")
        cols = ("year", "name", "folder", "time")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", selectmode="browse")
        for c, text, w in zip(cols, ("평가년도", "파일", "폴더", "고친 때"), (70, 330, 280, 120)):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=int(w * k), anchor="center" if c in ("year", "time") else "w")
        self.tree.pack(fill="both", expand=True, pady=(6, 8))
        self.tree.bind("<Double-1>", lambda _e: self._ok())
        self.tree.bind("<Return>", lambda _e: self._ok())
        b = ttk.Frame(f)
        b.pack(fill="x")
        ttk.Button(b, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(b, text="넣기", style="Accent.TButton", command=self._ok).pack(side="right", padx=8)
        ttk.Button(b, text="다른 위치에서 찾기…", command=self._browse).pack(side="left")
        self.bind("<Escape>", lambda _e: self.destroy())
        self._folders = folders
        threading.Thread(target=self._scan, daemon=True).start()
        self.after(100, self._poll)
        self.grab_set()

    def _scan(self):
        """작업 스레드: 찾는 대로 self._rows에 쌓는다(화면은 _poll이 가져간다)."""
        for p in qe.iter_sheets(self._folders):
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            self._rows.append((p, qe.quick_year(p), mt))
        self._found = True

    def _poll(self):
        if not self.winfo_exists():
            return
        home = os.path.expanduser("~")
        while self._shown < len(self._rows):
            p, y, mt = self._rows[self._shown]
            self._shown += 1
            folder = os.path.dirname(p)
            if folder.lower().startswith(home.lower()):
                folder = "~" + folder[len(home):]
            t = dt.datetime.fromtimestamp(mt).strftime("%y-%m-%d %H:%M")
            # 고친 때가 최근인 것이 위로
            pos = next((i for i, (_q, _y, m2) in enumerate(self._order) if m2 < mt), len(self._order))
            self._order.insert(pos, (p, y, mt))
            self.tree.insert("", pos, iid=p, values=(f"{y}년도" if y else "", os.path.basename(p), folder, t))
        if not self._found:
            self.msg.config(text=f"품질평가 평가표 엑셀을 찾는 중입니다… ({len(self._rows)}개 찾음)")
            self.after(150, self._poll)
            return
        if self._rows:
            if not self.tree.selection():
                first = self._order[0][0]
                self.tree.selection_set(first)
                self.tree.focus(first)
            self.msg.config(text=f"품질평가 평가표 엑셀 {len(self._rows)}개 (다른 엑셀은 보이지 않습니다). "
                                 "골라서 [넣기]를 누르세요.")
        else:
            self.msg.config(text="바탕화면·문서·다운로드에서 품질평가 평가표 엑셀을 찾지 못했습니다. "
                                 "[다른 위치에서 찾기…]로 골라 주세요.")

    def _ok(self):
        sel = self.tree.selection()
        if sel:
            self.result = sel[0]
            self.destroy()

    def _browse(self):
        p = filedialog.askopenfilename(parent=self, title=self.title(), filetypes=[("엑셀", "*.xlsx")],
                                       initialdir=self._folders[0] if self._folders else None)
        if not p:
            return
        if not qe.is_sheet(p):
            messagebox.showwarning("품질평가서 작성", f"품질평가 평가표 엑셀이 아닙니다('{qe.SHEET}' 시트가 없음).\n\n"
                                   f"{os.path.basename(p)}", parent=self)
            return
        self.result = p
        self.destroy()


class QualityDialog(tk.Toplevel):
    def __init__(self, master, cfg: dict, k: float = 1.0, log=None, homnet_run=None, on_report=None):
        """homnet_run(job, on_ok, on_err): 홈넷에 로그인한 뒤 job(driver, log)를 작업 스레드에서 돌린다.
        on_report(path): [한글파일 만들기] — 이 창을 닫고 한글파일 작성 창을 그 초안으로 연다."""
        super().__init__(master)
        self.cfg, self.k, self.log = cfg, k, log or (lambda _m: None)
        self.homnet_run = homnet_run
        self.on_report = on_report
        self.title("품질평가서 작성")
        self.geometry(f"{int(1200 * k)}x{int(780 * k)}")
        self.minsize(int(940 * k), int(620 * k))
        self.transient(master)
        self.path = ""                      # 품질평가 초안(올해) 엑셀
        self.prev_path = cfg.get("quality_prev_xlsx", "") if os.path.isfile(cfg.get("quality_prev_xlsx", "")) else ""
        extras = cfg.get("quality_extra_xlsx_list") or [cfg.get("quality_extra_xlsx", "")]   # 예전엔 한 개
        self.extra_paths = [p for p in dict.fromkeys(extras) if p and os.path.isfile(p)][:MAX_EXTRA]
        self.items: list[qe.Item] = []
        self.dirty = False
        self.running = False
        self.cur: qe.Item | None = None
        self.part = tk.StringVar(value=ALL)       # 처음엔 전체 항목, [내 항목 고르기]로 담당자별 항목만 볼 수 있다
        self.only_missing = tk.BooleanVar(value=False)
        self.only_blank = tk.BooleanVar(value=False)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(50, self._open_first)

    # ---------------- 화면 ----------------
    def _build(self):
        F = ui_kit.FONT
        top = ttk.Frame(self, padding=(14, 12, 14, 6))
        top.pack(fill="x")
        ttk.Label(top, text="품질평가서 작성", font=(F, 14, "bold")).pack(side="left")
        ttk.Button(top, text="엑셀로 열기", command=lambda: self._startfile(self.path)).pack(side="right")
        ttk.Button(top, text="증빙 폴더 열기", command=self._open_root).pack(side="right", padx=6)

        bar = ttk.Frame(self, padding=(14, 2, 14, 6))
        bar.pack(fill="x")
        ttk.Label(bar, text="보기").pack(side="left")
        self.part_cb = ttk.Combobox(bar, state="readonly", width=30, textvariable=self.part)
        self.part_cb.pack(side="left", padx=6)
        self.part_cb.bind("<<ComboboxSelected>>", lambda _e: self._part_changed())
        ttk.Button(bar, text="내 항목 고르기…", command=self._pick_mine).pack(side="left")
        ttk.Button(bar, text="점수 자동 매기기", command=self._auto_score).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(bar, text="증빙 없는 항목만", variable=self.only_missing,
                        command=self._fill).pack(side="left", padx=10)
        ttk.Checkbutton(bar, text="점수 안 넣은 항목만", variable=self.only_blank,
                        command=self._fill).pack(side="left")
        self.sum_lbl = ttk.Label(bar, font=(F, 10, "bold"))
        self.sum_lbl.pack(side="right")

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=14)
        # 틀 크기를 고정해 둔다: 평가 근거 열이 긴 글에 맞춰 넓어져도(_fit_basis) 목록이 창을 다 차지해
        # 오른쪽 [파일 넣기] 칸을 밀어내지 않게 — 긴 근거는 목록 안 가로 스크롤바로 본다.
        left = ttk.Frame(body, width=int(660 * self.k), height=int(400 * self.k))
        left.grid_propagate(False)
        cols =("no", "item", "max", "score", "ev", "basis")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        for c, t, w, a in (("no", "번호", 56, "center"), ("item", "평가항목", 290, "w"), ("max", "배점", 50, "center"),
                           ("score", "점수", 50, "center"), ("ev", "증빙", 76, "center"),
                           ("basis", "평가 근거", 240, "w")):
            self.tree.heading(c, text=t)
            # 늘어나는 열 없이 고정 너비 → 평가 근거가 길면 아래 가로 스크롤바로 오른쪽까지 본다
            self.tree.column(c, width=int(w * self.k), minwidth=int(40 * self.k), anchor=a, stretch=False)
        self.tree.tag_configure("part", background=ui_kit.PRIMARY_SOFT, font=(F, 10, "bold"))
        self.tree.tag_configure("missing", foreground="#c0392b")
        self.tree.tag_configure("drafted", background="#fff6d6")
        self.tree.tag_configure("lack", background="#ffe1e1")     # 작년과 비교해 없는 문서가 있는 항목(옅은 빨강)
        self.tree.tag_configure("auto", foreground="#1d4ed8")      # [점수 자동 매기기]로 넣은 점수(파란 글씨)
        self.tree.tag_configure("noscore", font=(F, 10, "bold"))    # 점수 안 넣은 항목(굵은 글씨 + 점수 칸 '미입력')
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb.set, xscrollcommand=xsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        # Shift+휠 = 가로로 움직이기
        self.tree.bind("<Shift-MouseWheel>",
                       lambda e: (self.tree.xview_scroll(-1 if e.delta > 0 else 1, "units"), "break")[1])
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._select())
        body.add(left, weight=3)

        holder = ttk.Frame(body, padding=(14, 0, 0, 0))
        body.add(holder, weight=2)
        right = self._scroll_area(holder)       # 창이 작아도 아래 칸까지 마우스 휠·스크롤바로 내려 본다
        self.title_lbl = ttk.Label(right, font=(F, 11, "bold"), wraplength=int(420 * self.k), justify="left")
        self.title_lbl.pack(anchor="w", fill="x")
        self.reason_lbl = ttk.Label(right, foreground="#b45309", wraplength=int(420 * self.k), justify="left")
        self.reason_lbl.pack(anchor="w", fill="x")
        # 평가기준·준비서류·평가 근거·평가점수 칸은 화면에 보이지 않는다(2026-11-18 요청).
        # 고른 항목 정보를 담는 데는 그대로 쓰도록 배치하지 않은 틀 안에 만들어 둔다.
        hidden = ttk.Frame(right)
        self.crit = self._ro_text(hidden, "평가기준", 4)
        self.docs = self._ro_text(hidden, "준비서류 (점수 인정 기준)", 3)
        self.basis_box = self._ro_text(hidden, "평가 근거", 3)     # 목록에서 잘리는 긴 근거를 한 줄씩 다 보여 준다
        self.basis_box.tag_configure("miss", foreground="#e00000")          # 작년에 있고 올해 없음(✗) — 엑셀 빨간 글씨
        self.basis_box.tag_configure("added", foreground="#c99700")         # 작년과 비교해 새로 들어감 — 엑셀 노란 글씨
        sf = ttk.Frame(hidden)
        sf.pack(anchor="w", fill="x", pady=(8, 0))
        ttk.Label(sf, text="평가점수", font=(F, 10, "bold")).pack(side="left")
        self.score = tk.StringVar()
        self.score_e = ttk.Spinbox(sf, from_=-10, to=10, increment=0.1, width=7, textvariable=self.score)
        self.score_e.pack(side="left", padx=8)
        self.max_lbl = ttk.Label(sf, foreground=ui_kit.SUB)
        self.max_lbl.pack(side="left")
        ttk.Button(sf, text="만점", width=5, command=self._full).pack(side="left", padx=8)
        self.score_e.bind("<KeyRelease>", lambda _e: self._apply())
        self.score_e.bind("<<Increment>>", lambda _e: self.after(1, self._apply))
        self.score_e.bind("<<Decrement>>", lambda _e: self.after(1, self._apply))

        # ---- 전년도 초안 / 올해 초안 ----
        self.prev_lbl = self._slot(right, "작년도 초안", "평가 근거 기입란이 적혀 있는 품질평가 초안 엑셀",
                                   self._choose_prev, lambda: self._startfile(self.prev_path), self._clear_prev)
        # 근거 보태기: 최근 5개년도 작성분 엑셀을 5개까지
        ebox = ttk.LabelFrame(right, text=f" 최근 5개년도 작성분 (선택 · 없어도 초안 작성 가능, 최대 {MAX_EXTRA}개) ", padding=(10, 6))
        ebox.pack(fill="x", pady=(12, 0))
        etop = ttk.Frame(ebox)
        etop.pack(fill="x")
        self.extra_hint = ttk.Label(etop, foreground=ui_kit.SUB, wraplength=int(260 * self.k), justify="left",
                                    text="최근 5년 안에 손으로 적어 둔 평가표(예: 작년·올해 상반기 작성본) — "
                                         "그 문서들도 함께 넣습니다. 없어도 됩니다")
        self.extra_hint.pack(side="left", fill="x", expand=True)
        self.extra_add = ttk.Button(etop, text="파일 넣기…", command=self._choose_extra)
        self.extra_add.pack(side="right")
        self.extra_rows = ttk.Frame(ebox)
        self.extra_rows.pack(fill="x")
        self.cur_lbl = self._slot(right, "품질평가 초안 작성", "근거를 기록할 평가표 엑셀(빈 양식이어도 됩니다)",
                                  self._choose, lambda: self._startfile(self.path), self._clear_cur)
        gf = ttk.Frame(right)
        gf.pack(fill="x", pady=(10, 0))
        this_year = dt.date.today().year
        saved_year = self.cfg.get("quality_ledger_year")
        self.ledger_year = tk.StringVar(value=str(saved_year if isinstance(saved_year, int) else this_year))
        ttk.Label(gf, text="대장 연도", font=(ui_kit.FONT, 10, "bold")).pack(side="left")
        self.year_cb = ttk.Combobox(gf, state="readonly", width=6, textvariable=self.ledger_year,
                                    values=[str(y) for y in range(this_year, this_year - 6, -1)])
        self.year_cb.pack(side="left", padx=(6, 2))
        self.year_cb.bind("<<ComboboxSelected>>", lambda _e: self._year_changed())
        ttk.Label(gf, text="년").pack(side="left", padx=(0, 10))
        self.go_btn = ttk.Button(gf, text="대장관리 참고해 초안 작성", style="Accent.TButton", command=self._draft)
        self.go_btn.pack(side="left")
        self.stop_btn = ttk.Button(gf, text="멈추기", command=self._stop)
        self.status = ttk.Label(right, foreground=ui_kit.SUB, wraplength=int(420 * self.k), justify="left",
                                text="참고 초안의 평가 근거에 적힌 문서들과 같은 종류의 문서를 홈넷 대장관리(기록물등록대장)의 "
                                     "고른 연도에서 찾아 초안 작성 파일에 기록합니다. (홈넷 로그인 필요, 대장을 처음 읽을 때 몇 분 걸립니다)")
        self.status.pack(anchor="w", fill="x", pady=(6, 0))
        self._show_slots()

        bot = ttk.Frame(self, padding=(14, 10))
        bot.pack(fill="x")
        ttk.Button(bot, text="닫기", command=self._close).pack(side="right")
        ttk.Button(bot, text="완성본 엑셀로 저장…", style="Accent.TButton", command=self._save_as).pack(side="right", padx=8)
        ttk.Button(bot, text="평가표에 저장", command=self._save).pack(side="right")
        if self.on_report:
            ttk.Button(bot, text="다음: 폴더링 →", command=self._to_report).pack(side="right")
        else:                                       # KODAS: 폴더링 창이 없으니 증빙 폴더는 이 창에서
            ttk.Button(bot, text="증빙 폴더 만들기", command=self._make_folders).pack(side="right")
            ttk.Button(bot, text="증빙 다시 확인", command=self._rescan).pack(side="right", padx=8)
        # 안내 글은 버튼 뒤에 놓는다: 창이 좁으면 버튼이 아니라 이 글이 줄바꿈된다
        ttk.Label(bot, foreground=ui_kit.SUB, wraplength=int(420 * self.k), justify="left",
                  text="점수를 고치거나 초안을 만든 뒤 [평가표에 저장]을 누르면 엑셀에 들어갑니다. 저장 전 원본은 자동 백업."
                  ).pack(side="left", fill="x", expand=True)
        self.bind("<Activate>", lambda e: self._rescan() if e.widget is self else None)   # 탐색기에서 넣고 돌아오면

    def _scroll_area(self, parent):
        """세로 스크롤 영역(안쪽 Frame을 돌려준다). 내용이 창보다 길 때만 스크롤바가 보이고 휠이 움직인다."""
        bg = ttk.Style().lookup("TFrame", "background") or "#fafafa"
        cv = tk.Canvas(parent, highlightthickness=0, borderwidth=0, bg=bg)
        sb = ttk.Scrollbar(parent, orient="vertical", command=cv.yview)
        inner = ttk.Frame(cv)
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)

        def overflow() -> bool:
            return inner.winfo_reqheight() > cv.winfo_height() + 1

        def relayout(_e=None):
            cv.configure(scrollregion=(0, 0, inner.winfo_reqwidth(), inner.winfo_reqheight()))
            if overflow():
                if not sb.winfo_ismapped():
                    sb.pack(side="right", fill="y", before=cv)
            else:
                sb.pack_forget()
                cv.yview_moveto(0)
        inner.bind("<Configure>", relayout)

        def resized(e):
            cv.itemconfigure(win, width=e.width)
            for lbl in (getattr(self, n, None) for n in ("title_lbl", "reason_lbl", "status")):
                if lbl is not None:                     # 글이 오른쪽에서 잘리지 않게 칸 너비에 맞춰 줄바꿈
                    lbl.configure(wraplength=max(120, e.width - 12))
            relayout()
        cv.bind("<Configure>", resized)

        def wheel(e):
            if overflow():
                cv.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")
        self._panel_wheel = wheel
        # 오른쪽 칸 어디에 마우스가 있든(글 칸 위 포함) 휠로 내린다. 왼쪽 목록은 목록 자체 스크롤.
        parent.bind("<Enter>", lambda _e: self.bind_all("<MouseWheel>", wheel))
        def leave(_e):
            x, y = parent.winfo_pointerxy()
            w = parent.winfo_containing(x, y)
            while w is not None and w is not parent:      # 안쪽 칸으로 옮겨 간 것이면 그대로 둔다
                w = w.master
            if w is None:
                self.unbind_all("<MouseWheel>")
        parent.bind("<Leave>", leave)
        self.bind("<Destroy>", lambda e: self.unbind_all("<MouseWheel>") if e.widget is self else None, add="+")
        return inner

    def _slot(self, parent, title, hint, on_pick, on_open, on_clear):
        box = ttk.LabelFrame(parent, text=f" {title} ", padding=(10, 6))
        box.pack(fill="x", pady=(12, 0))
        # 버튼을 먼저 놓는다: 칸이 좁아도 [파일 넣기…]가 찌그러지지 않고 설명 글이 줄어든다
        ttk.Button(box, text="삭제", width=5, command=on_clear).pack(side="right")
        ttk.Button(box, text="열기", width=5, command=on_open).pack(side="right", padx=(6, 0))
        ttk.Button(box, text="파일 넣기…", command=on_pick).pack(side="right", padx=6)
        lbl = ttk.Label(box, text=hint, foreground=ui_kit.SUB, wraplength=int(170 * self.k), justify="left")
        lbl.pack(side="left", fill="x", expand=True)
        lbl.hint = hint
        return lbl

    def _clear_prev(self):
        """[작년도 초안] 칸에서 파일을 뺀다(파일 자체는 지우지 않음)."""
        if not self.prev_path or self.running:
            return
        if not messagebox.askyesno("품질평가서 작성", f"작년도 초안 칸에서 이 파일을 뺄까요?\n\n{os.path.basename(self.prev_path)}"
                                   "\n\n(엑셀 파일 자체는 지우지 않습니다)", parent=self):
            return
        self.prev_path = ""
        self.cfg["quality_prev_xlsx"] = ""
        self._show_slots()
        self.status.config(text="작년도 초안 파일을 뺐습니다. [파일 넣기…]로 다시 넣어 주세요.")

    def _choose_extra(self):
        """[최근 5개년도 작성분] 칸에 파일을 하나 더 넣는다(최대 MAX_EXTRA개, 최근 5년 안의 평가표만)."""
        if self.running:
            return
        if len(self.extra_paths) >= MAX_EXTRA:
            messagebox.showinfo("품질평가서 작성", f"근거 보태기 파일은 {MAX_EXTRA}개까지 넣을 수 있습니다.\n"
                                "다른 파일을 넣으려면 먼저 [빼기]로 하나를 빼 주세요.", parent=self)
            return
        last = self.extra_paths[-1] if self.extra_paths else self.path
        p = self._ask_xlsx("최근 5개년도에 손으로 적어 둔 품질평가 평가표 엑셀(평가 근거가 들어 있는 것)",
                           os.path.dirname(last) if last else "")
        if not p:
            return
        if any(os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(x)) for x in self.extra_paths):
            messagebox.showinfo("품질평가서 작성", "이미 넣은 파일입니다.", parent=self)
            return
        y = qe.sheet_year(p)
        oldest = dt.date.today().year - (EXTRA_YEARS - 1)
        if y and y < oldest:
            messagebox.showwarning("품질평가서 작성", f"{y}년도 평가표입니다. 최근 5개년도({oldest}~{dt.date.today().year}년) "
                                   "작성분만 넣을 수 있습니다.", parent=self)
            return
        try:
            items = qe.load(p)
        except Exception as e:
            messagebox.showerror("품질평가서 작성", f"평가표를 읽지 못했습니다.\n{e}", parent=self)
            return
        n = sum(1 for i in items if i.basis.strip())
        if not n:
            messagebox.showwarning("품질평가서 작성", "이 파일에는 평가 근거가 하나도 없습니다.", parent=self)
            return
        self.extra_paths.append(p)
        self._save_extras()
        self._show_slots()
        self.status.config(text=f"{(str(y) + '년도 ') if y else ''}작성분: 평가 근거가 있는 항목 {n}개를 읽었습니다. "
                                f"초안 작성 때 함께 넣습니다. (근거 보태기 {len(self.extra_paths)}/{MAX_EXTRA})")

    def _clear_extra(self, p):
        """근거 보태기 칸에서 파일 하나를 뺀다(파일 자체는 지우지 않음)."""
        if self.running or p not in self.extra_paths:
            return
        if not messagebox.askyesno("품질평가서 작성", f"근거 보태기에서 이 파일을 뺄까요?\n\n{os.path.basename(p)}"
                                   "\n\n(엑셀 파일 자체는 지우지 않습니다)", parent=self):
            return
        self.extra_paths.remove(p)
        self._save_extras()
        self._show_slots()
        self.status.config(text="근거 보태기 파일을 뺐습니다.")

    def _save_extras(self):
        self.cfg["quality_extra_xlsx_list"] = list(self.extra_paths)
        self.cfg.pop("quality_extra_xlsx", None)          # 예전 한 개짜리 설정

    def _clear_cur(self):
        """[품질평가 초안 작성] 칸에서 파일을 뺀다(목록도 비움, 파일 자체는 지우지 않음)."""
        if not self.path or self.running:
            return
        if not messagebox.askyesno("품질평가서 작성", f"초안 작성 칸에서 이 파일을 뺄까요?\n\n{os.path.basename(self.path)}"
                                   "\n\n(엑셀 파일 자체는 지우지 않습니다)", parent=self):
            return
        if not self._confirm_discard():
            return
        self.path, self.items, self.dirty, self.cur = "", [], False, None
        self.cfg["quality_xlsx"] = ""
        self.tree.delete(*self.tree.get_children())
        self.title_lbl.config(text="")
        self._set_ro(self.crit, "")
        self._set_ro(self.docs, "")
        self._set_ro(self.basis_box, "")
        self.score.set("")
        self.max_lbl.config(text="")
        self._show_slots()
        self._summary()
        self.status.config(text="초안 작성 파일을 뺐습니다. [파일 넣기…]로 다시 넣어 주세요.")

    def _show_slots(self):
        for lbl, p in ((self.prev_lbl, self.prev_path), (self.cur_lbl, self.path)):
            if p:
                y = qe.sheet_year(p)
                lbl.config(text=(f"[{y}년도] " if y else "") + os.path.basename(p), foreground=ui_kit.TEXT)
            else:
                lbl.config(text=lbl.hint, foreground=ui_kit.SUB)
        # 근거 보태기: 넣은 파일마다 한 줄([연도] 파일 이름 · 열기 · 빼기), 최근 연도가 위로
        for w in self.extra_rows.winfo_children():
            w.destroy()
        for p in self._extras_sorted():
            row = ttk.Frame(self.extra_rows)
            row.pack(fill="x", pady=(4, 0))
            y = qe.sheet_year(p)
            ttk.Label(row, text=(f"[{y}년도] " if y else "") + os.path.basename(p), wraplength=int(260 * self.k),
                      justify="left").pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="빼기", width=5, command=lambda q=p: self._clear_extra(q)).pack(side="right")
            ttk.Button(row, text="열기", width=5, command=lambda q=p: self._startfile(q)).pack(side="right", padx=(6, 0))
        self.extra_hint.config(text=(f"{len(self.extra_paths)}/{MAX_EXTRA}개 넣었습니다. 초안 작성 때 이 문서들도 함께 넣습니다."
                                     if self.extra_paths else
                                     "최근 5년 안에 손으로 적어 둔 평가표(예: 작년·올해 상반기 작성본) — "
                                     "그 문서들도 함께 넣습니다. 없어도 됩니다"))
        self.extra_add.state(["disabled"] if len(self.extra_paths) >= MAX_EXTRA else ["!disabled"])

    def _extras_sorted(self) -> list:
        """근거 보태기 파일들: 최근 연도부터(연도를 모르면 맨 뒤)."""
        return sorted(self.extra_paths, key=lambda p: -(qe.sheet_year(p) or 0))

    def _ro_text(self, parent, title, h):
        ttk.Label(parent, text=title, font=(ui_kit.FONT, 10, "bold")).pack(anchor="w", pady=(8, 2))
        t = tk.Text(parent, height=h, wrap="word", font=(ui_kit.FONT, 9), relief="flat",
                    background=ui_kit.PAGE, foreground=ui_kit.TEXT, padx=6, pady=4)
        t.pack(fill="x")
        t.configure(state="disabled")
        t.min_rows = h
        # 글 칸 위에서 휠을 굴려도 오른쪽 칸 전체가 내려가게(글 칸은 내용만큼 늘어나 따로 스크롤할 일이 없다)
        t.bind("<MouseWheel>", lambda e: (self._panel_wheel(e), "break")[1])
        t.bind("<Configure>", lambda _e, tt=t: self._fit_text(tt))
        return t

    def _set_ro(self, t, text):
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", text)
        t.configure(state="disabled")
        self._fit_text(t)

    @staticmethod
    def _fit_text(t):
        """글 칸 높이를 내용 줄 수에 맞춘다(최소는 처음 높이)."""
        try:
            rows = t.count("1.0", "end", "displaylines")
        except tk.TclError:
            return
        rows = rows[0] if isinstance(rows, tuple) else (rows or 1)
        want = max(getattr(t, "min_rows", 1), rows)
        if int(t.cget("height")) != want:
            t.configure(height=want)

    # ---------------- 파일 ----------------
    def _open_first(self):
        last = self.cfg.get("quality_xlsx", "")
        if last and os.path.isfile(last):
            self._first_load = isinstance(self.cfg.get("quality_ledger_year"), int)   # 전에 고른 연도는 그대로
            self._load(last)
            self._first_load = False
            return
        home = os.path.expanduser("~")
        found = qe.find_sheets([os.path.join(home, "Desktop"), os.path.join(home, "Documents"),
                                os.path.join(home, "Downloads")], dt.date.today().year)
        if found and messagebox.askyesno(
                "품질평가서 작성", f"이 평가표에 올해 초안을 작성할까요?\n\n{found[0]}\n\n(아니요를 누르면 직접 고릅니다)",
                parent=self):
            self._load(found[0])
        else:
            self._choose()

    def _ask_xlsx(self, title, init):
        """[파일 넣기…]: 품질평가 평가표 엑셀만 늘어놓은 목록에서 고른다(SheetPicker)."""
        home = os.path.expanduser("~")
        folders = [init] + [os.path.dirname(p) for p in (self.path, self.prev_path, *self.extra_paths) if p]
        folders += [os.path.join(home, n) for n in ("Desktop", "Documents", "Downloads")]
        if paths.frozen():
            folders.append(paths.program_dir())        # 프로그램 폴더(영철ai/품질평가서 작성기)에 저장한 초안·완성본
        dlg = SheetPicker(self, title, list(dict.fromkeys(f for f in folders if f)), self.k)
        self.wait_window(dlg)
        return dlg.result or ""

    def _choose(self):
        if not self._confirm_discard():
            return
        p = self._ask_xlsx("품질평가 초안을 작성할 올해 평가표 엑셀", os.path.dirname(self.path) if self.path else "")
        if p:
            self._load(p)

    def _choose_prev(self):
        init = os.path.dirname(self.prev_path or self.path) if (self.prev_path or self.path) else ""
        p = self._ask_xlsx("전년도 품질평가 초안 엑셀(평가 근거가 들어 있는 것)", init)
        if not p:
            return
        try:
            items = qe.load(p)
        except Exception as e:
            messagebox.showerror("품질평가서 작성", f"전년도 평가표를 읽지 못했습니다.\n{e}", parent=self)
            return
        n = sum(1 for i in items if i.basis.strip())
        if not n:
            messagebox.showwarning("품질평가서 작성", "이 파일에는 평가 근거가 하나도 없습니다.\n"
                                   "근거를 적어 둔 전년도 평가표를 넣어 주세요.", parent=self)
            return
        self.prev_path = p
        self.cfg["quality_prev_xlsx"] = p
        self._show_slots()
        self.status.config(text=f"전년도 초안: 평가 근거가 있는 항목 {n}개를 읽었습니다.")

    def _load(self, path):
        if not path:
            return
        try:
            items = qe.load(path)
        except Exception as e:
            messagebox.showerror("품질평가서 작성", f"평가표를 읽지 못했습니다.\n{e}", parent=self)
            return
        self.path, self.items, self.dirty, self.cur = path, items, False, None
        self.cfg["quality_xlsx"] = path
        qe.scan_evidence(qe.evidence_root(path), items)
        parts = [ALL, MINE, REPORT4] + list(dict.fromkeys(i.part for i in items))
        self.part_cb.config(values=parts)
        if self.part.get() not in parts:
            self.part.set(ALL)
        y = qe.sheet_year(path)                 # 새로 넣은 초안 작성 파일의 평가년도를 대장 연도로(올해 이하일 때)
        if not getattr(self, "_first_load", False) and y and y <= dt.date.today().year and str(y) in self.year_cb.cget("values"):
            self.ledger_year.set(str(y))
            self.cfg["quality_ledger_year"] = y
        self._show_slots()
        self._fill()

    def _year_changed(self):
        self.cfg["quality_ledger_year"] = int(self.ledger_year.get())
        self.status.config(text=f"대장 연도를 {self.ledger_year.get()}년으로 골랐습니다. "
                                "[대장관리 참고해 초안 작성]을 누르면 그해 대장관리에서 찾아 넣습니다.")

    # ---------------- 목록 ----------------
    # ---------------- 담당자별 내 항목 ----------------
    def _who(self) -> str:
        return (self.cfg.get("담당자") or "").strip() or "기본"

    def _mine(self) -> set:
        """지금 담당자가 고른 항목 열쇠(설정 quality_my_items[담당자])."""
        return set((self.cfg.get("quality_my_items") or {}).get(self._who(), []))

    def _pick_mine(self):
        if not self.items:
            messagebox.showinfo("품질평가서 작성", "먼저 [품질평가 초안 작성]에 평가표 엑셀을 넣어 주세요.", parent=self)
            return
        dlg = PickItemsDialog(self, self.items, self._mine(), self._who(), self.k)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        mine = dict(self.cfg.get("quality_my_items") or {})
        mine[self._who()] = sorted(dlg.result)
        self.cfg["quality_my_items"] = mine
        self.part.set(MINE if dlg.result else ALL)
        self._fill()

    def _part_changed(self):
        if self.part.get() == MINE and not (self._mine() & {item_key(i) for i in self.items}):
            self.part.set(ALL)
            self._fill()
            self._pick_mine()            # 아직 고른 항목이 없으면 바로 고르게
            return
        self._fill()

    def _in_part(self, it) -> bool:
        p = self.part.get()
        if p == MINE:
            return item_key(it) in self._mine()
        if p == REPORT4:
            return it.part in qe.REPORT4_PARTS
        return p == ALL or it.part == p

    def _visible(self):
        for it in self.items:
            if not self._in_part(it):
                continue
            if self.only_missing.get() and (it.evidence or it.notes):
                continue
            if self.only_blank.get() and not _blank(it):
                continue
            yield it

    def _tags(self, it):
        tags = [] if (it.evidence or it.notes) else ["missing"]
        if it.auto_why and it.score is not None:
            tags = ["auto"]
        if it.flag:
            tags.append("lack")
        elif getattr(it, "drafted", False):
            tags.append("drafted")
        if _blank(it):
            tags.append("noscore")
        return tuple(tags)

    def _fill(self):
        keep = self.cur.row if self.cur else None
        self.tree.delete(*self.tree.get_children())
        part = None
        for it in self._visible():
            if it.part != part:
                part = it.part
                self.tree.insert("", "end", iid=f"p{it.row}", values=("", f"■ {part}", "", "", "", ""),
                                 tags=("part",))
            self.tree.insert("", "end", iid=str(it.row), values=self._row(it), tags=self._tags(it))
        if keep and self.tree.exists(str(keep)):
            self.tree.selection_set(str(keep))
            self.tree.see(str(keep))
        self._fit_basis()
        self._summary()

    def _fit_basis(self):
        """평가 근거 열 너비를 가장 긴 근거 글에 맞춘다(가로 스크롤바로 끝까지 볼 수 있게)."""
        import tkinter.font as tkfont
        try:
            f = tkfont.Font(font=ttk.Style().lookup("Treeview", "font") or "TkDefaultFont")
        except tk.TclError:
            f = tkfont.nametofont("TkDefaultFont")
        longest = max((f.measure(self.tree.set(i, "basis")) for i in self.tree.get_children()), default=0)
        self.tree.column("basis", width=min(max(int(240 * self.k), longest + 24), 4000))

    def _row(self, it):
        ev = f"{len(it.evidence)}개" if it.evidence else (it.notes[0][:8] if it.notes else "없음")
        return (it.no, it.text, _fmt(it.max_score), "미입력" if _blank(it) else _fmt(it.score), ev, it.basis.replace("\n", " / "))

    def _rescan(self):
        if not self.path:
            return
        qe.scan_evidence(qe.evidence_root(self.path), self.items)
        for it in self.items:
            if self.tree.exists(str(it.row)):
                self.tree.item(str(it.row), values=self._row(it), tags=self._tags(it))
        self._summary()

    def _summary(self):
        vis = [i for i in self.items if self._in_part(i)]
        got = sum(i.score or 0 for i in vis)
        full = sum(i.max_score or 0 for i in vis if i.part != "가감점")
        miss = sum(1 for i in vis if not (i.evidence or i.notes))
        blank = sum(1 for i in vis if _blank(i))
        self.sum_lbl.config(text=f"점수 {got:g} / {full:g}점   ·   점수 안 넣은 항목 {blank}   ·   증빙 없는 항목 {miss}"
                                 + ("   · 저장 안 함" if self.dirty else ""))

    def _select(self):
        sel = self.tree.selection()
        if not sel or sel[0].startswith("p"):
            return
        it = next((i for i in self.items if str(i.row) == sel[0]), None)
        if not it:
            return
        self.cur = it
        self.title_lbl.config(text=f"{it.no}  {it.text}" + (f"   ({it.indicator})" if it.indicator else ""))
        self._set_ro(self.crit, it.criteria or "-")
        self._set_ro(self.docs, it.docs or "-")
        self._set_ro(self.basis_box, (it.basis or "").strip() or "(아직 없음)")
        t, added = self.basis_box, set(it.added or [])
        for n, line in enumerate(t.get("1.0", "end-1c").split("\n"), start=1):
            tag = "miss" if line.startswith(qe.MISS_MARK) else "added" if line.strip() in added else None
            if tag:
                t.tag_add(tag, f"{n}.0", f"{n}.end")
        self.score.set(_fmt(it.score))
        self.max_lbl.config(text=f"/ 배점 {_fmt(it.max_score)}" if it.max_score is not None else "(가감점)")
        why = [f"자동 점수: {it.auto_why}"] if it.auto_why else []
        why += [f"점수 불인정 사유: {it.reason}"] if it.reason else []
        self.reason_lbl.config(text="\n".join(why))

    def _apply(self):
        it = self.cur
        if not it:
            return
        txt = self.score.get().strip()
        try:
            score = float(txt) if txt else None
        except ValueError:
            return
        if score != it.score:
            it.score = score
            it.auto_why = ""                 # 손으로 고친 점수는 자동 점수 표시를 지운다
            self.dirty = True
            if self.tree.exists(str(it.row)):
                self.tree.item(str(it.row), values=self._row(it), tags=self._tags(it))
            self.reason_lbl.config(text=f"점수 불인정 사유: {it.reason}" if it.reason else "")
            self._summary()

    def _auto_score(self):
        """[점수 자동 매기기]: 보이는 범위(보기)의 항목에 올해 근거·작년 점수로 점수를 넣는다."""
        if not self.items:
            messagebox.showinfo("품질평가서 작성", "먼저 [품질평가 초안 작성]에 평가표 엑셀을 넣어 주세요.", parent=self)
            return
        prev = []
        if self.prev_path and os.path.isfile(self.prev_path):
            try:
                prev = qe.load(self.prev_path)
            except Exception as e:
                messagebox.showwarning("품질평가서 작성", f"참고 초안(작년)을 읽지 못해 작년 점수 없이 매깁니다.\n{e}",
                                       parent=self)
        scope = [i for i in self.items if self._in_part(i)]
        have = [i for i in scope if i.score is not None]
        redo = True
        if have:
            ans = messagebox.askyesnocancel(
                "점수 자동 매기기", f"이미 점수가 들어 있는 항목이 {len(have)}개 있습니다.\n\n"
                "예: 그 항목도 다시 매기기\n아니요: 빈 항목만 매기기", parent=self)
            if ans is None:
                return
            redo = ans
        done, skip = 0, []
        for it, score, why in qe.auto_scores(scope, prev):
            if it.score is not None and not redo:
                continue
            if score is None:
                skip.append(f"{it.label[:30]} — {why}")
                continue
            if score != it.score or not it.auto_why:
                it.score, it.auto_why = score, why
                done += 1
        if done:
            self.dirty = True
        self._fill()
        self._select()
        check = sum(1 for i in scope if i.auto_why and i.flag)
        msg = (f"✅ 점수 자동 매기기: {done}개 항목에 점수를 넣었습니다(파란 글씨). "
               + ("작년 점수를 기준으로 했습니다. " if prev else "참고 초안(작년)이 없어 근거가 있으면 만점으로 넣었습니다. ")
               + "확인 후 [평가표에 저장]을 누르세요.")
        self.status.config(text=msg)
        self.log(msg)
        messagebox.showinfo("점수 자동 매기기", f"{done}개 항목에 점수를 넣었습니다. (목록의 파란 글씨)\n"
                            + (f"작년보다 없는 문서가 있는 항목(옅은 빨간 줄) {check}개는 꼭 확인하세요.\n" if check else "")
                            + (f"\n매기지 않은 항목 {len(skip)}개 (직접 넣어 주세요):\n" + "\n".join(skip[:12])
                               + ("\n…" if len(skip) > 12 else "") if skip else "")
                            + "\n\n항목을 누르면 오른쪽에 점수를 매긴 까닭이 보입니다.", parent=self)

    def _full(self):
        if self.cur and self.cur.max_score is not None:
            self.score.set(_fmt(self.cur.max_score))
            self._apply()

    # ---------------- 초안 작성(대장관리) ----------------
    def _draft(self):
        if self.running:
            return
        if not self.prev_path:
            messagebox.showinfo("품질평가서 작성", "먼저 [작년도 초안]에 평가 근거가 적힌 초안 엑셀을 넣어 주세요.",
                                parent=self)
            return
        if not self.path:
            messagebox.showinfo("품질평가서 작성", "먼저 [품질평가 초안 작성]에 기록할 평가표 엑셀을 넣어 주세요.",
                                parent=self)
            return
        try:
            prev_items = qe.load(self.prev_path)
        except Exception as e:
            messagebox.showerror("품질평가서 작성", f"전년도 평가표를 읽지 못했습니다.\n{e}", parent=self)
            return
        cur_year = int(self.ledger_year.get())              # 고른 연도의 대장관리에서 찾는다
        prev_year = qe.sheet_year(self.prev_path) or cur_year
        scope = self.part.get()
        mine = self._mine()
        only = (lambda it: it.part in qe.REPORT4_PARTS) if scope == REPORT4 else \
            (lambda it: item_key(it) in mine) if scope == MINE else \
            (None if scope == ALL else (lambda it, s=scope: it.part == s))
        old_years, new_years = qd.needed_years([p for p in prev_items if only is None or only(p)],
                                               prev_year, cur_year)
        extras = []
        for path in self._extras_sorted():              # 최근 5개년도 작성분(최근 연도부터)
            if not os.path.isfile(path):
                continue
            try:
                ex_items = qe.load(path)
            except Exception as e:
                messagebox.showerror("품질평가서 작성", f"근거 보태기 평가표를 읽지 못했습니다.\n"
                                     f"{os.path.basename(path)}\n{e}", parent=self)
                return
            y = qe.sheet_year(path)
            ex_year = y or cur_year
            label = f"{y}년도" if y else (os.path.splitext(os.path.basename(path))[0].strip() or "올해")
            extras.append((ex_items, ex_year, label))
            o2, n2 = qd.needed_years([p for p in ex_items if only is None or only(p)], ex_year, cur_year)
            old_years, new_years = old_years | o2, new_years | n2
        self._extras = extras
        if not old_years:
            messagebox.showinfo("품질평가서 작성", "참고 초안 근거에 '번호(날짜)' 모양의 문서번호가 없어 대장을 볼 필요가 없습니다.\n"
                                "문서번호 없는 근거만 그대로 옮깁니다.", parent=self)
            self._apply_draft(prev_items, prev_year, cur_year, {}, only, [])
            return
        years = sorted(old_years | new_years)
        cached = qd.cached_ledgers(years, _cache_dir())
        if cached is not None:                 # 오늘 읽어 둔 대장 목록이 있으면 홈넷에 들어가지 않는다
            self.log(f"대장 목록: 오늘 읽어 둔 {', '.join(map(str, years))}년 목록을 씁니다.")
            self._apply_draft(prev_items, prev_year, cur_year, cached, only, [])
            return
        if not self.homnet_run:
            return
        if not messagebox.askyesno(
                "대장관리 참고해 초안 작성",
                f"참고 초안 근거의 문서 제목을 {', '.join(map(str, sorted(old_years)))}년 대장에서 확인하고,\n"
                f"같은 종류의 문서를 {cur_year}년 대장관리에서 찾아\n"
                f"'{scope}' 항목의 평가 근거를 초안 작성 파일에 기록합니다.\n\n"
                "홈넷에 로그인해 기록물등록대장을 읽기만 합니다. 진행할까요?",
                parent=self):
            return
        self.stop_ev = threading.Event()
        self._busy(True, "홈넷 기록물등록대장을 읽는 중입니다...")

        def say(m):                       # 작업 스레드 → 화면은 _poll이 읽어 간다(Tk는 한 스레드에서만)
            self.log(m)
            self._last_msg = m

        def job(driver, _log):
            return qd.load_ledgers(driver, years, _cache_dir(), say, self.stop_ev, self.cfg.get("단지명", ""))

        def ok(res):
            if not self.winfo_exists():
                return
            self._busy(False)
            ledgers, missing_years = res
            self._apply_draft(prev_items, prev_year, cur_year, ledgers, only, missing_years)

        def err(ex):
            if self.winfo_exists():
                self._busy(False, f"❌ 초안을 만들지 못했습니다: {ex}")

        self.homnet_run(job, ok, err)

    def _apply_draft(self, prev_items, prev_year, cur_year, ledgers, only, missing_years):
        results = qd.make_draft(prev_items, self.items, prev_year, cur_year, ledgers, only,
                                extras=getattr(self, "_extras", []))
        for it, _res in results:
            it.drafted = True
        if results:
            self.dirty = True
        self._fill()
        found = sum(r.found for _i, r in results)
        miss = [m for _i, r in results for m in r.missing]
        lacks = [it for it, r in results if r.lacking]
        msg = (f"✅ 초안 작성: 항목 {len(results)}개의 평가 근거를 채웠습니다 ({cur_year}년 문서 {found}건). "
               "엷은 노란 줄이 바뀐 항목입니다. 확인 후 [평가표에 저장]을 누르세요.")
        if lacks:
            msg += (f"\n⚠️ 작년과 비교해 없는 문서가 있는 항목 {len(lacks)}개 — 평가 근거 맨 아래에 "
                    "'✗ 작년에 있고 올해 없음' 줄(엑셀에서 빨간 글씨)로 적었습니다.")
        elif miss:
            msg += f"\n⚠️ 확인 필요 {len(miss)}건 — 근거 칸에 '확인 필요'로 표시했습니다."
        if missing_years:
            msg += f"\n⚠️ {', '.join(map(str, missing_years))}년 대장이 홈넷에 없어 그 해 문서는 찾지 못했습니다."
        if not results:
            msg = ("초안 작성: 이미 같은 평가 근거가 들어 있어 바꾼 항목이 없습니다. "
                   "(참고 초안과 초안 작성 파일이 같거나, 이미 초안을 만든 파일입니다)")
        self.status.config(text=msg)
        self.log(msg.splitlines()[0])
        # 홈넷 브라우저가 앞을 가리므로 이 창을 다시 앞으로 올리고 결과를 알린다
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.focus_force()
            self.after(300, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass
        if results:
            if messagebox.askyesno("초안 작성 완료", f"항목 {len(results)}개의 평가 근거를 채웠습니다 ({cur_year}년 문서 {found}건)."
                                   + (f"\n확인 필요 {len(miss)}건이 있습니다." if miss else "")
                                   + "\n\n바뀐 항목은 목록에 엷은 노란 줄로 보입니다."
                                   + "\n엑셀 평가 근거 칸: 작년에 없던 문서는 노란 글씨, 작년에 있고 올해 없는 문서는 빨간 글씨(✗)."
                                   + "\n\n지금 완성본 엑셀로 저장할까요?",
                                   parent=self):
                self._save_as()
        else:
            messagebox.showinfo("초안 작성", "이미 같은 평가 근거가 들어 있어 바꾼 항목이 없습니다.\n"
                                "[완성본 엑셀로 저장…]으로 지금 내용을 엑셀로 받을 수 있습니다.", parent=self)

    def _busy(self, on, text=""):
        self.running = on
        self.go_btn.state(["disabled"] if on else ["!disabled"])
        if on:
            self.stop_btn.pack(side="left", padx=8)
            self._last_msg = ""
            self._poll()
        else:
            self.stop_btn.pack_forget()
        if text:
            self.status.config(text=text)

    def _poll(self):
        if not self.running or not self.winfo_exists():
            return
        if getattr(self, "_last_msg", ""):
            self.status.config(text=self._last_msg)
        self.after(400, self._poll)

    def _stop(self):
        if getattr(self, "stop_ev", None):
            self.stop_ev.set()
            self.status.config(text="멈추는 중입니다... (지금 읽는 쪽까지 마칩니다)")

    # ---------------- 저장·폴더 ----------------
    def _save(self, quiet: bool = False) -> bool:
        if not self.path:
            return False
        self._apply()
        name = qe.complex_name(self.path) or ""
        label = "" if name else (self.cfg.get("단지명") or "")
        try:
            bak = qe.save(self.path, self.items, label, os.path.join(paths.user_dir(), "품질평가_백업"))
        except PermissionError:
            messagebox.showwarning("품질평가서 작성", "엑셀에서 평가표가 열려 있어 저장하지 못했습니다.\n"
                                   "엑셀을 닫고 다시 [평가표에 저장]을 눌러 주세요.", parent=self)
            return False
        except Exception as e:
            messagebox.showerror("품질평가서 작성", f"저장하지 못했습니다.\n{e}", parent=self)
            return False
        self.dirty = False
        self._summary()
        self.log(f"✅ 품질평가 평가표를 저장했습니다. ({os.path.basename(self.path)})")
        if not quiet:
            messagebox.showinfo("품질평가서 작성", "평가표에 저장했습니다.\n\n"
                            f"저장 전 원본 백업: {bak}", parent=self)
        return True

    def _save_as(self):
        """완성본을 새 엑셀 파일로 저장한다(기본: 초안 옆 '품질평가 작성' 폴더). 초안 작성 파일은 그대로 둔다."""
        if not self.path:
            messagebox.showinfo("품질평가서 작성", "먼저 [품질평가 초안 작성]에 평가표 엑셀을 넣어 주세요.", parent=self)
            return
        self._apply()
        name = qe.complex_name(self.path) or self.cfg.get("단지명") or ""
        year = qe.sheet_year(self.path) or dt.date.today().year
        only = None
        if self.part.get() == MINE:                 # [내 항목 고르기]로 고른 항목만 보는 중이면 엑셀도 그 항목만
            only = [i for i in self.items if self._in_part(i)]
        tail = f"_완성본({self._who()} 내 항목)" if only else "_완성본"
        default = f"({name}) {year}년도 품질평가 평가표{tail}.xlsx" if name else f"{year}년도 품질평가 평가표{tail}.xlsx"
        down = qe.work_dir(self.path)          # 폴더링·한글파일과 같은 '품질평가 작성' 폴더
        os.makedirs(down, exist_ok=True)
        dst = filedialog.asksaveasfilename(parent=self, title="완성본 엑셀로 저장", initialdir=down,
                                           initialfile=default, defaultextension=".xlsx",
                                           filetypes=[("엑셀", "*.xlsx")])
        if not dst:
            return
        try:
            qe.save_as(self.path, dst, self.items, "" if qe.complex_name(self.path) else name, only)
        except PermissionError:
            messagebox.showwarning("품질평가서 작성", "같은 이름의 파일이 엑셀에서 열려 있어 저장하지 못했습니다.\n"
                                   "엑셀을 닫거나 다른 이름으로 저장해 주세요.", parent=self)
            return
        except Exception as e:
            messagebox.showerror("품질평가서 작성", f"저장하지 못했습니다.\n{e}", parent=self)
            return
        self.log(f"✅ 품질평가 완성본을 저장했습니다: {dst}")
        what = f"내 항목 {len(only)}개만 보이게(다른 항목 줄은 숨김) " if only else ""
        if messagebox.askyesno("품질평가서 작성", f"완성본을 {what}저장했습니다.\n\n{dst}\n\n지금 엑셀로 열어 볼까요?",
                               parent=self):
            self._startfile(dst)

    def _to_report(self):
        """[한글파일 만들기]: 고친 것이 있으면 평가표에 저장한 뒤, 이 창을 닫고 한글파일 작성 창에 이 초안을 넣는다."""
        if not self.path:
            messagebox.showinfo("품질평가서 작성", "먼저 [품질평가 초안 작성]에 평가표 엑셀을 넣어 주세요.", parent=self)
            return
        if self.running:
            messagebox.showinfo("품질평가서 작성", "대장을 읽는 중입니다. 끝난 뒤 눌러 주세요.", parent=self)
            return
        if self.dirty and not self._save(quiet=True):
            return
        path = self.path
        self.cfg["quality_xlsx"] = path
        self.destroy()
        self.on_report(path)

    def _make_folders(self):
        if not self.path:
            return
        root = qe.evidence_root(self.path)
        n = qe.make_folders(root, [i for i in self.items if self._in_part(i)])
        self._rescan()
        messagebox.showinfo("품질평가서 작성", f"증빙 폴더를 {n}개 새로 만들었습니다." if n else
                            "증빙 폴더가 이미 모두 있습니다.", parent=self)

    def _open_root(self):
        if self.path:
            root = qe.evidence_root(self.path)
            os.makedirs(root, exist_ok=True)
            self._startfile(root)
        else:
            self._startfile("")

    def _startfile(self, p):
        """[열기] 버튼들: 파일이 없으면 그냥 넘어가지 않고 알려 주고, 열다가 막히면 다른 길로 연다."""
        if not p:
            messagebox.showinfo("품질평가서 작성", "아직 넣은 파일이 없습니다.\n먼저 [파일 넣기…]로 엑셀을 넣어 주세요.",
                                parent=self)
            return
        if not os.path.exists(p):
            messagebox.showwarning("품질평가서 작성", f"파일을 찾을 수 없습니다(옮겼거나 지웠을 수 있음).\n\n{p}",
                                   parent=self)
            return
        ui_kit.open_path(p, self)

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        ans = messagebox.askyesnocancel("품질평가서 작성", "저장하지 않은 점수·근거가 있습니다. 평가표에 저장할까요?",
                                        parent=self)
        if ans is None:
            return False
        return self._save() if ans else True

    def _close(self):
        if self.running and not messagebox.askyesno("품질평가서 작성", "대장을 읽는 중입니다. 멈추고 닫을까요?", parent=self):
            return
        self._stop()
        if self._confirm_discard():
            self.destroy()
