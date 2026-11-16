"""품질평가서 작성 창.

- 왼쪽: 올해 평가표(초안)의 항목 목록 — 번호·평가항목·배점·점수·증빙·평가 근거
- 오른쪽 위: 고른 항목의 평가기준·준비서류·평가점수
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
REPORT4 = "임대운영 · 본지사 협조도 (4권)"


def _fmt(v) -> str:
    if v is None:
        return ""
    return f"{v:g}"


def _cache_dir() -> str:
    d = os.path.join(paths.user_dir(), "품질평가_대장")
    os.makedirs(d, exist_ok=True)
    return d


class QualityDialog(tk.Toplevel):
    def __init__(self, master, cfg: dict, k: float = 1.0, log=None, homnet_run=None):
        """homnet_run(job, on_ok, on_err): 홈넷에 로그인한 뒤 job(driver, log)를 작업 스레드에서 돌린다."""
        super().__init__(master)
        self.cfg, self.k, self.log = cfg, k, log or (lambda _m: None)
        self.homnet_run = homnet_run
        self.title("품질평가서 작성")
        self.geometry(f"{int(1200 * k)}x{int(780 * k)}")
        self.minsize(int(940 * k), int(620 * k))
        self.transient(master)
        self.path = ""                      # 품질평가 초안(올해) 엑셀
        self.prev_path = cfg.get("quality_prev_xlsx", "") if os.path.isfile(cfg.get("quality_prev_xlsx", "")) else ""
        self.items: list[qe.Item] = []
        self.dirty = False
        self.running = False
        self.cur: qe.Item | None = None
        self.part = tk.StringVar(value=REPORT4)
        self.only_missing = tk.BooleanVar(value=False)
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
        self.part_cb.bind("<<ComboboxSelected>>", lambda _e: self._fill())
        ttk.Checkbutton(bar, text="증빙 없는 항목만", variable=self.only_missing,
                        command=self._fill).pack(side="left", padx=10)
        self.sum_lbl = ttk.Label(bar, font=(F, 10, "bold"))
        self.sum_lbl.pack(side="right")

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=14)
        left = ttk.Frame(body)
        cols = ("no", "item", "max", "score", "ev", "basis")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        for c, t, w, a in (("no", "번호", 56, "center"), ("item", "평가항목", 290, "w"), ("max", "배점", 50, "center"),
                           ("score", "점수", 50, "center"), ("ev", "증빙", 76, "center"),
                           ("basis", "평가 근거", 240, "w")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=int(w * self.k), anchor=a, stretch=c in ("item", "basis"))
        self.tree.tag_configure("part", background=ui_kit.PRIMARY_SOFT, font=(F, 10, "bold"))
        self.tree.tag_configure("missing", foreground="#c0392b")
        self.tree.tag_configure("drafted", background="#fff6d6")
        self.tree.tag_configure("lack", background="#fff200")     # 작년과 비교해 없는 문서가 있는 항목
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._select())
        body.add(left, weight=3)

        right = ttk.Frame(body, padding=(14, 0, 0, 0))
        body.add(right, weight=2)
        self.title_lbl = ttk.Label(right, font=(F, 11, "bold"), wraplength=int(420 * self.k), justify="left")
        self.title_lbl.pack(anchor="w", fill="x")
        self.reason_lbl = ttk.Label(right, foreground="#b45309", wraplength=int(420 * self.k), justify="left")
        self.reason_lbl.pack(anchor="w", fill="x")
        self.crit = self._ro_text(right, "평가기준", 4)
        self.docs = self._ro_text(right, "준비서류 (점수 인정 기준)", 3)
        sf = ttk.Frame(right)
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
        self.prev_lbl = self._slot(right, "품질평가 초안 (근거 참고)", "평가 근거 기입란이 적혀 있는 품질평가 초안 엑셀",
                                   self._choose_prev, lambda: self._startfile(self.prev_path), self._clear_prev)
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
        ttk.Label(bot, foreground=ui_kit.SUB,
                  text="점수를 고치거나 초안을 만든 뒤 [평가표에 저장]을 누르면 엑셀에 들어갑니다. 저장 전 원본은 자동 백업."
                  ).pack(side="left")
        ttk.Button(bot, text="닫기", command=self._close).pack(side="right")
        ttk.Button(bot, text="완성본 엑셀로 저장…", style="Accent.TButton", command=self._save_as).pack(side="right", padx=8)
        ttk.Button(bot, text="평가표에 저장", command=self._save).pack(side="right")
        ttk.Button(bot, text="증빙 폴더 만들기", command=self._make_folders).pack(side="right")
        ttk.Button(bot, text="증빙 다시 확인", command=self._rescan).pack(side="right", padx=8)
        self.bind("<Activate>", lambda e: self._rescan() if e.widget is self else None)   # 탐색기에서 넣고 돌아오면

    def _slot(self, parent, title, hint, on_pick, on_open, on_clear):
        box = ttk.LabelFrame(parent, text=f" {title} ", padding=(10, 6))
        box.pack(fill="x", pady=(12, 0))
        lbl = ttk.Label(box, text=hint, foreground=ui_kit.SUB, wraplength=int(260 * self.k), justify="left")
        lbl.pack(side="left", fill="x", expand=True)
        ttk.Button(box, text="삭제", width=5, command=on_clear).pack(side="right")
        ttk.Button(box, text="열기", width=5, command=on_open).pack(side="right", padx=(6, 0))
        ttk.Button(box, text="파일 넣기…", command=on_pick).pack(side="right", padx=6)
        lbl.hint = hint
        return lbl

    def _clear_prev(self):
        """[품질평가 초안 (근거 참고)] 칸에서 파일을 뺀다(파일 자체는 지우지 않음)."""
        if not self.prev_path or self.running:
            return
        if not messagebox.askyesno("품질평가서 작성", f"근거 참고 칸에서 이 파일을 뺄까요?\n\n{os.path.basename(self.prev_path)}"
                                   "\n\n(엑셀 파일 자체는 지우지 않습니다)", parent=self):
            return
        self.prev_path = ""
        self.cfg["quality_prev_xlsx"] = ""
        self._show_slots()
        self.status.config(text="근거 참고 파일을 뺐습니다. [파일 넣기…]로 다시 넣어 주세요.")

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

    def _ro_text(self, parent, title, h):
        ttk.Label(parent, text=title, font=(ui_kit.FONT, 10, "bold")).pack(anchor="w", pady=(8, 2))
        t = tk.Text(parent, height=h, wrap="word", font=(ui_kit.FONT, 9), relief="flat",
                    background=ui_kit.PAGE, foreground=ui_kit.TEXT, padx=6, pady=4)
        t.pack(fill="x")
        t.configure(state="disabled")
        return t

    @staticmethod
    def _set_ro(t, text):
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", text)
        t.configure(state="disabled")

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
        return filedialog.askopenfilename(parent=self, title=title, initialdir=init or
                                          os.path.join(os.path.expanduser("~"), "Desktop"),
                                          filetypes=[("엑셀", "*.xlsx"), ("모든 파일", "*.*")])

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
        parts = [REPORT4, ALL] + list(dict.fromkeys(i.part for i in items))
        self.part_cb.config(values=parts)
        if self.part.get() not in parts:
            self.part.set(REPORT4)
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
    def _in_part(self, it) -> bool:
        p = self.part.get()
        if p == REPORT4:
            return it.part in qe.REPORT4_PARTS
        return p == ALL or it.part == p

    def _visible(self):
        for it in self.items:
            if self._in_part(it) and not (self.only_missing.get() and (it.evidence or it.notes)):
                yield it

    def _tags(self, it):
        tags = [] if (it.evidence or it.notes) else ["missing"]
        if it.flag:
            tags.append("lack")
        elif getattr(it, "drafted", False):
            tags.append("drafted")
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
        self._summary()

    def _row(self, it):
        ev = f"{len(it.evidence)}개" if it.evidence else (it.notes[0][:8] if it.notes else "없음")
        return (it.no, it.text, _fmt(it.max_score), _fmt(it.score), ev, it.basis.replace("\n", " / "))

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
        blank = sum(1 for i in vis if i.score is None and i.part != "가감점")
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
        self.score.set(_fmt(it.score))
        self.max_lbl.config(text=f"/ 배점 {_fmt(it.max_score)}" if it.max_score is not None else "(가감점)")
        self.reason_lbl.config(text=f"점수 불인정 사유: {it.reason}" if it.reason else "")

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
            self.dirty = True
            if self.tree.exists(str(it.row)):
                self.tree.item(str(it.row), values=self._row(it))
            self._summary()

    def _full(self):
        if self.cur and self.cur.max_score is not None:
            self.score.set(_fmt(self.cur.max_score))
            self._apply()

    # ---------------- 초안 작성(대장관리) ----------------
    def _draft(self):
        if self.running:
            return
        if not self.prev_path:
            messagebox.showinfo("품질평가서 작성", "먼저 [품질평가 초안 (근거 참고)]에 평가 근거가 적힌 초안 엑셀을 넣어 주세요.",
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
        only = (lambda it: it.part in qe.REPORT4_PARTS) if scope == REPORT4 else \
            (None if scope == ALL else (lambda it, s=scope: it.part == s))
        old_years, new_years = qd.needed_years([p for p in prev_items if only is None or only(p)],
                                               prev_year, cur_year)
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
        results = qd.make_draft(prev_items, self.items, prev_year, cur_year, ledgers, only)
        for it, _res in results:
            it.drafted = True
        if results:
            self.dirty = True
        self._fill()
        found = sum(r.found for _i, r in results)
        miss = [m for _i, r in results for m in r.missing]
        lacks = [it for it, r in results if r.lacking]
        msg = (f"✅ 초안 작성: 항목 {len(results)}개의 평가 근거를 채웠습니다 ({cur_year}년 문서 {found}건). "
               "노란 줄이 바뀐 항목입니다. 확인 후 [평가표에 저장]을 누르세요.")
        if lacks:
            msg += (f"\n⚠️ 작년과 비교해 없는 문서가 있는 항목 {len(lacks)}개 — 노란색으로 표시하고 "
                    "점수 불인정 사유 칸에 없는 항목을 적었습니다.")
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
                                   + "\n\n바뀐 항목은 목록에 노란 줄로 보입니다.\n지금 완성본 엑셀로 저장할까요?",
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
    def _save(self) -> bool:
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
        messagebox.showinfo("품질평가서 작성", "평가표에 저장했습니다.\n\n"
                            f"저장 전 원본 백업: {bak}", parent=self)
        return True

    def _save_as(self):
        """완성본을 새 엑셀 파일로 내려받는다(기본: 다운로드 폴더). 초안 작성 파일은 그대로 둔다."""
        if not self.path:
            messagebox.showinfo("품질평가서 작성", "먼저 [품질평가 초안 작성]에 평가표 엑셀을 넣어 주세요.", parent=self)
            return
        self._apply()
        name = qe.complex_name(self.path) or self.cfg.get("단지명") or ""
        year = qe.sheet_year(self.path) or dt.date.today().year
        default = f"({name}) {year}년도 품질평가 평가표_완성본.xlsx" if name else f"{year}년도 품질평가 평가표_완성본.xlsx"
        down = os.path.join(os.path.expanduser("~"), "Downloads")
        dst = filedialog.asksaveasfilename(parent=self, title="완성본 엑셀로 저장", initialdir=down,
                                           initialfile=default, defaultextension=".xlsx",
                                           filetypes=[("엑셀", "*.xlsx")])
        if not dst:
            return
        try:
            qe.save_as(self.path, dst, self.items, "" if qe.complex_name(self.path) else name)
        except PermissionError:
            messagebox.showwarning("품질평가서 작성", "같은 이름의 파일이 엑셀에서 열려 있어 저장하지 못했습니다.\n"
                                   "엑셀을 닫거나 다른 이름으로 저장해 주세요.", parent=self)
            return
        except Exception as e:
            messagebox.showerror("품질평가서 작성", f"저장하지 못했습니다.\n{e}", parent=self)
            return
        self.log(f"✅ 품질평가 완성본을 저장했습니다: {dst}")
        if messagebox.askyesno("품질평가서 작성", f"완성본을 저장했습니다.\n\n{dst}\n\n지금 엑셀로 열어 볼까요?", parent=self):
            self._startfile(dst)

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

    def _startfile(self, p):
        if p and os.path.exists(p):
            os.startfile(p)

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
