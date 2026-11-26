"""[한글파일 작성] 창: 1~4권 중 고른 권의 품질평가 보고서(한글)를 만든다(hwp_report).

- 초안(품질평가 초안 작성에서 저장한 평가표 엑셀: 점수·평가 근거), 평가년도, 센터 이름, 관리소장 성명을 넣고 권을 고른다.
- 폴더링: 초안이 있는 폴더의 '품질평가 작성\\폴더링'(만든 한글파일도 '품질평가 작성'에 둔다). [고른 권 폴더링 만들기]는 번호·항목 폴더를 만들고, 초안의 평가 근거에 적힌
  문서를 홈넷 기록물등록대장에서 받아 항목 폴더에 넣는다(evidence_fetch). 거기 있는 파일이 증빙 쪽에 들어간다.
- 첨부파일 비밀번호 1~3: 잠긴 PDF·엑셀·한글 첨부를 열 때 차례로 넣어 본다(이 PC에서만 암호화해 저장).
"""
import datetime as dt
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import hwp_report as hr
import paths
import quality_eval as qe
import ui_kit

TITLE = "한글파일 작성"
FOLDER_TITLE = "폴더링"
ALL_NOS = "전체 번호"


class ReportDialog(tk.Toplevel):
    def __init__(self, master, cfg: dict, k: float = 1.0, log=None, homnet_run=None, path: str = "",
                 mode: str = "report", on_next=None):
        """mode 'folder' = [폴더링] 창(번호별 폴더링 만들기), 'report' = [한글파일 작성] 창.
        on_next(path): 폴더링 창의 [다음: 한글파일 작성] — 이 창을 닫고 한글파일 작성 창을 연다."""
        super().__init__(master)
        self.cfg, self.k, self.log = cfg, k, log or (lambda _m: None)
        self.homnet_run = homnet_run
        self.folder_mode = mode == "folder"
        self.on_next = on_next
        self.heading = FOLDER_TITLE if self.folder_mode else TITLE
        self.title(f"품질평가서 작성 — {self.heading}")
        self.minsize(int(620 * k), int(560 * k))
        self.items: list[qe.Item] = []
        self.path = ""
        self.running = False
        self.stop_ev = threading.Event()
        self.vols = {v: tk.BooleanVar(value=False) for v in qe.VOLUMES}
        c = cfg.get("quality_custom_folder", "") if mode != "folder" else ""
        self.custom_root = c if c and os.path.isdir(c) else ""     # [내가 만든 폴더링 적용하기]로 고른 폴더
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        p = path or cfg.get("quality_xlsx", "")      # [한글파일 만들기]로 오면 그 초안
        if p and os.path.isfile(p):
            self.after(50, lambda: self._load(p))

    # ---------------- 화면 ----------------
    def _build(self):
        F = ui_kit.FONT
        f = ttk.Frame(self, padding=(20, 16, 20, 14))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=self.heading, font=(F, 14, "bold")).pack(anchor="w")
        intro = ("권과 번호를 골라 [폴더링 만들기]를 누르면 대장에서 증빙을 받아 항목 폴더에 그림으로 넣습니다. "
                 "한 번호씩 만들고 검토한 뒤 다음 번호로 넘어가세요."
                 if self.folder_mode else
                 "권을 골라 [한글파일 작성]을 누르면 양식에 점수와 폴더링 사진을 넣은 보고서를 만듭니다.")
        ttk.Label(f, text=intro, foreground=ui_kit.SUB, wraplength=int(580 * self.k),
                  justify="left").pack(anchor="w", pady=(2, 12))

        box = self.tut_info = ttk.LabelFrame(f, text=" 기본 정보 ", padding=(12, 8))
        box.pack(fill="x")
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="초안 넣기", font=(F, 10, "bold")).grid(row=0, column=0, sticky="w", pady=3)
        self.path_lbl = ttk.Label(box, text="(품질평가 초안 작성에서 저장한 평가표를 넣어 주세요)", foreground=ui_kit.SUB,
                                  wraplength=int(380 * self.k))
        self.path_lbl.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Button(box, text="넣기…", command=self._choose).grid(row=0, column=2)
        ttk.Label(box, text="평가년도").grid(row=1, column=0, sticky="w", pady=3)
        self.year = tk.StringVar(value=str(dt.date.today().year))
        ttk.Spinbox(box, from_=2020, to=2100, width=8, textvariable=self.year).grid(row=1, column=1, sticky="w", padx=8)
        ttk.Label(box, text="센터(단지) 이름").grid(row=2, column=0, sticky="w", pady=3)
        self.center = ttk.Entry(box, width=24)
        self.center.grid(row=2, column=1, sticky="w", padx=8)
        self.center.insert(0, self.cfg.get("단지명", "") or "")
        ttk.Label(box, text="예: 광주양림2 (표지에 '○○ 주거행복지원센터'로 들어갑니다)", foreground=ui_kit.SUB).grid(
            row=2, column=1, sticky="e", padx=8)
        ttk.Label(box, text="관리소장 성명").grid(row=3, column=0, sticky="w", pady=3)
        self.chief = ttk.Entry(box, width=24)
        self.chief.grid(row=3, column=1, sticky="w", padx=8)
        self.chief.insert(0, self.cfg.get("quality_chief", "") or "")
        ttk.Label(box, text="서약서에 들어갑니다", foreground=ui_kit.SUB).grid(row=3, column=1, sticky="e", padx=8)
        ttk.Label(box, text="첨부파일 비밀번호").grid(row=4, column=0, sticky="w", pady=3)
        pw_row = ttk.Frame(box)
        pw_row.grid(row=4, column=1, columnspan=2, sticky="w", padx=8)
        saved = self._load_pws()
        self.pw_entries = []
        for i in range(3):
            ttk.Label(pw_row, text=f"{i + 1}").pack(side="left", padx=(0 if i == 0 else 8, 2))
            e = ttk.Entry(pw_row, width=12, show="●")
            e.pack(side="left")
            if i < len(saved) and saved[i]:
                e.insert(0, saved[i])
            self.pw_entries.append(e)
        self.wise_code = ttk.Entry(box, width=12)
        self.wise_code.insert(0, self.cfg.get("wise_complex", "") or "")
        if self.folder_mode:
            ttk.Label(box, text="WISE 단지코드").grid(row=6, column=0, sticky="w", pady=3)
            self.wise_code.grid(row=6, column=1, sticky="w", padx=8)
            ttk.Label(box, text="예: C00060 — WISE 해약처리현황 조회에 넣습니다(WISE를 켜 두면 캡처)",
                      foreground=ui_kit.SUB).grid(row=6, column=1, sticky="e", padx=8)
        # 단지별 법정영세민 기본단가 탭(4권 1-4)은 영구임대 단지만 나온다 — 단지가 여러 개면 쉼표로 여러 개
        self.basic_codes = ttk.Entry(box, width=30)
        self.basic_codes.insert(0, self.cfg.get("wise_basic_complexes", "") or "")
        if self.folder_mode:
            ttk.Label(box, text="영세민 기본단가 단지").grid(row=7, column=0, sticky="w", pady=3)
            self.basic_codes.grid(row=7, column=1, sticky="w", padx=8)
            ttk.Label(box, text="단지코드, 여러 개는 쉼표로(예: C00058, C00059)\n"
                                "— 단지별 법정영세민 기본단가 탭을 단지마다 한 장씩. 비우면 위 단지코드",
                      foreground=ui_kit.SUB, justify="left").grid(row=8, column=1, sticky="w", padx=8)
        ttk.Label(box, text="잠긴 첨부(PDF·엑셀·한글)를 열 때 1→2→3 차례로 넣어 봅니다. 없으면 비워 두세요.",
                  foreground=ui_kit.SUB).grid(row=5, column=1, columnspan=2, sticky="w", padx=8)

        vb = self.tut_vols = ttk.LabelFrame(f, text=" 작성할 권 ", padding=(12, 8))
        vb.pack(fill="x", pady=(12, 0))
        self.vol_info = {}
        for r, (v, name) in enumerate(qe.VOLUMES.items()):
            ttk.Checkbutton(vb, text=name, variable=self.vols[v],
                            command=lambda: self._update_steps(True)).grid(row=r, column=0, sticky="w", pady=2)
            lbl = ttk.Label(vb, foreground=ui_kit.SUB)
            lbl.grid(row=r, column=1, sticky="w", padx=12)
            self.vol_info[v] = lbl
        row = ttk.Frame(vb)
        row.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.step = tk.StringVar(value=ALL_NOS)        # 한 번호씩 만들고 검토한 뒤 다음 번호로
        self.step_cb = ttk.Combobox(row, textvariable=self.step, state="readonly", width=12, values=[ALL_NOS])
        self.tut_row = row
        if self.folder_mode:
            ttk.Label(row, text="번호").pack(side="left")
            self.step_cb.pack(side="left", padx=(4, 8))
            ttk.Button(row, text="폴더링 만들기 (대장에서 파일 받기)", style="Accent.TButton",
                       command=self._make_folders).pack(side="left")
        ttk.Button(row, text="폴더링 열기", command=self._open_root).pack(side="left", padx=6)
        ttk.Button(row, text="새로 보기", command=self._refresh).pack(side="left")
        self.root_lbl = ttk.Label(vb, foreground=ui_kit.SUB, wraplength=int(540 * self.k), justify="left")
        self.root_lbl.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        if not self.folder_mode:                       # 직접 만들어 둔 폴더링으로 사진 넣기
            mine = self.tut_mine = ttk.Frame(vb)
            mine.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
            ttk.Button(mine, text="📂 내가 만든 폴더링 적용하기…", command=self._pick_custom).pack(side="left")
            self.custom_off = ttk.Button(mine, text="해제 (KODAS 폴더링 쓰기)", command=self._clear_custom)
            self.custom_off.pack(side="left", padx=6)
            self.custom_lbl = ttk.Label(vb, foreground=ui_kit.SUB, wraplength=int(540 * self.k), justify="left")
            self.custom_lbl.grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))
            self._show_custom()

        self.status = tk.Text(f, height=7, wrap="word", relief="flat", borderwidth=0, highlightthickness=1,
                              highlightbackground="#e0e0e0", font=(F, 9))
        self.status.pack(fill="both", expand=True, pady=(12, 8))
        self.status.configure(state="disabled")
        bot = self.tut_bot = ttk.Frame(f)
        bot.pack(fill="x")
        self.pb = ttk.Progressbar(bot, mode="indeterminate", length=int(160 * self.k))
        ttk.Button(bot, text="닫기", command=self._close).pack(side="right")
        if self.folder_mode:
            self.go_btn = ttk.Button(bot, text="다음: 한글파일 작성 →", command=self._to_report)
        else:
            self.go_btn = ttk.Button(bot, text="한글파일 작성", style="Accent.TButton", command=self._go)
        if not self.folder_mode or self.on_next:
            self.go_btn.pack(side="right", padx=6)
        self.stop_btn = ttk.Button(bot, text="멈추기", command=self._stop)

    def _stop(self):
        """[멈추기]: 신호를 켜면 지금 하던 동작(WISE 기다림·파일 하나)까지만 하고 멈춘다."""
        if not self.running or self.stop_ev.is_set():
            return
        self.stop_ev.set()
        self.stop_btn.state(["disabled"])
        self.say("⏸ 멈추는 중입니다… (하던 동작 하나만 마치고 멈춥니다)")

    def say(self, msg: str):
        self.log(msg)
        self.status.configure(state="normal")
        self.status.insert("end", msg + "\n")
        self.status.see("end")
        self.status.configure(state="disabled")

    # ---------------- 평가표·폴더링 ----------------
    def _choose(self):
        from quality_view import SheetPicker
        home = os.path.expanduser("~")
        folders = [os.path.dirname(self.path)] if self.path else []
        folders += [os.path.join(home, n) for n in ("Desktop", "Documents", "Downloads")]
        if paths.frozen():
            folders.append(paths.program_dir())
        dlg = SheetPicker(self, "품질평가 초안 작성에서 저장한 초안 평가표", list(dict.fromkeys(folders)), self.k)
        self.wait_window(dlg)
        if dlg.result:
            self._load(dlg.result)

    def _load(self, path: str):
        try:
            items = qe.load(path)
        except Exception as ex:
            messagebox.showerror(TITLE, f"초안을 읽지 못했습니다.\n{ex}", parent=self)
            return
        self.path, self.items = path, items
        self.cfg["quality_xlsx"] = path
        self.path_lbl.config(text=os.path.basename(path), foreground=ui_kit.TEXT)
        y = qe.sheet_year(path)
        if y:
            self.year.set(str(y))
        if not self.center.get().strip():
            name = qe.complex_name(path)
            if name:
                self.center.insert(0, name)
        self._update_steps(True)
        self._refresh()

    def _to_report(self):
        """[다음: 한글파일 작성]: 이 창을 닫고 한글파일 작성 창에 같은 초안을 넣어 연다."""
        if self.running:
            messagebox.showinfo(FOLDER_TITLE, "폴더링을 만드는 중입니다. 끝난 뒤 눌러 주세요.", parent=self)
            return
        path = self.path
        self.passwords()
        self.cfg["quality_chief"] = self.chief.get().strip()
        self.destroy()
        if self.on_next:
            self.on_next(path)

    def _startfile_dir(self, d: str):
        if d and os.path.isdir(d):
            ui_kit.open_path(d, self)

    def _evid_root(self) -> str:
        return qe.evidence_root(self.path) if self.path else ""

    # ---------------- 내가 만든 폴더링 ----------------
    def _pick_custom(self):
        """직접 만들어 둔 폴더링 폴더를 고른다. 폴더 이름이 번호(1-1 …)로 시작하면 번호 폴더, 그 안의
        '1. …' '2. …' 폴더가 항목 폴더. 거기 있는 파일이 한글파일 증빙 쪽에 사진으로 들어간다."""
        from tkinter import filedialog
        start = self.custom_root or (os.path.dirname(self.path) if self.path else os.path.expanduser("~\\Desktop"))
        d = filedialog.askdirectory(parent=self, title="내가 만든 폴더링 폴더 고르기 (번호 폴더들이 들어 있는 폴더)",
                                    initialdir=start, mustexist=True)
        if not d:
            return
        d = os.path.normpath(d)
        if not self.items:
            messagebox.showinfo(TITLE, "먼저 [초안 넣기]로 초안 평가표를 넣어 주세요.\n"
                                "초안의 번호(1-1 …)와 폴더 이름을 맞춰 사진을 넣습니다.", parent=self)
            return
        found = qe.scan_custom(d, self.items)
        if not found:
            messagebox.showwarning(TITLE, "이 폴더에서 번호 폴더를 찾지 못했습니다.\n\n"
                                   "폴더 이름이 번호로 시작해야 합니다. 예)\n"
                                   "  4권 임대운영 \\ 1-1 \\ 1. 임대차계약 \\ (파일들)\n"
                                   "  1-2 입주자 관리 \\ (파일들)\n"
                                   "같은 번호가 여러 권에 있으면 위 폴더 이름에 '1권'·'4권'처럼 권을 넣어 주세요.",
                                   parent=self)
            self._refresh()
            return
        self.custom_root = d
        self.cfg["quality_custom_folder"] = d
        self._refresh()
        vols = sorted({k[0] for k in found})
        for v in vols:                                  # 찾은 권은 체크
            self.vols[v].set(True)
        self._refresh()
        files = sum(len(i.evidence) for i in self.items)
        self.say(f"📂 내가 만든 폴더링 적용: {d}\n   항목 폴더 {len(found)}개 · 파일 {files}개 "
                 f"({', '.join(qe.VOLUMES[v] for v in vols)})")
        miss = [i.label for i in self.items if qe.volume_of(i.part) in vols
                and (qe.volume_of(i.part), i.no, i.seq) not in found]
        if miss:
            self.say(f"   ⚠ 폴더를 못 찾은 항목 {len(miss)}개(증빙 없이 점수만): " + ", ".join(miss[:8])
                     + (" …" if len(miss) > 8 else ""))

    def _clear_custom(self):
        self.custom_root = ""
        self.cfg["quality_custom_folder"] = ""
        self.say("내가 만든 폴더링을 해제했습니다. KODAS 폴더링(품질평가 작성\\폴더링)을 씁니다.")
        self._refresh()

    def _show_custom(self):
        if not hasattr(self, "custom_lbl"):
            return
        if self.custom_root:
            self.custom_lbl.config(text=f"✔ 내가 만든 폴더링을 씁니다: {self.custom_root}", foreground=ui_kit.TEXT)
            self.custom_off.state(["!disabled"])
        else:
            self.custom_lbl.config(text="직접 폴더링해 둔 폴더가 있으면 골라 주세요. 폴더 이름의 번호(1-1, 2-3 …)로 "
                                        "항목을 찾아 그 안의 파일을 사진으로 넣습니다.", foreground=ui_kit.SUB)
            self.custom_off.state(["disabled"])

    def _refresh(self):
        self._show_custom()
        if self.custom_root:
            found = qe.scan_custom(self.custom_root, self.items)
            self.root_lbl.config(text=f"사진을 가져올 곳: 내가 만든 폴더링 (항목 폴더 {len(found)}개 찾음)")
            for v, lbl in self.vol_info.items():
                its = [i for i in self.items if qe.volume_of(i.part) == v]
                got = sum((v, i.no, i.seq) in found for i in its)
                lbl.config(text=f"항목 {len(its)}개 · 점수 {sum(i.score is not None for i in its)}개 · "
                                f"폴더 찾음 {got}개 · 증빙 파일 {sum(len(i.evidence) for i in its)}개" if its else "")
            return
        root = self._evid_root()
        self.root_lbl.config(text=f"폴더링: {root}  (4권: {qe.volume_dir(root, 4)})" if root
                             else "초안을 넣으면 그 폴더에 '품질평가 작성'을 만들어 폴더링(4권은 '폴더링 4권')과 한글파일을 넣습니다.")
        for v, lbl in self.vol_info.items():
            its = [i for i in self.items if qe.volume_of(i.part) == v]
            if not its:
                lbl.config(text="")
                continue
            if root and os.path.isdir(qe.volume_dir(root, v)):
                qe.scan_evidence(root, its)
            files = sum(len(i.evidence) for i in its)
            scored = sum(i.score is not None for i in its)
            lbl.config(text=f"항목 {len(its)}개 · 점수 {scored}개 · 증빙 파일 {files}개")

    def _chosen(self) -> list[int]:
        return [v for v, var in self.vols.items() if var.get()]

    def _step_values(self) -> list[str]:
        """번호 고르기 목록: 전체 + 체크한 권(없으면 모든 권)의 '4권 1-1' …(평가표 차례)."""
        vols = self._chosen() or list(qe.VOLUMES)
        out = []
        for v in vols:
            for i in self.items:
                if qe.volume_of(i.part) == v and f"{v}권 {i.no}" not in out:
                    out.append(f"{v}권 {i.no}")
        return [ALL_NOS] + out

    def _update_steps(self, first: bool = False):
        vals = self._step_values()
        self.step_cb.config(values=vals)
        if first or self.step.get() not in vals:
            self.step.set(vals[1] if len(vals) > 1 else ALL_NOS)     # 처음엔 첫 번호(1-1)부터

    def _next_step(self) -> str:
        vals = self._step_values()
        cur = self.step.get()
        if cur in vals and vals.index(cur) + 1 < len(vals):
            return vals[vals.index(cur) + 1]
        return ""

    # ---------------- 비밀번호 ----------------
    def _load_pws(self) -> list:
        out = []
        try:
            from app_config import decrypt
            for v in self.cfg.get("file_pws") or []:
                try:
                    out.append(decrypt(v) if v else "")
                except Exception:
                    out.append("")
        except Exception:
            pass
        return out

    def passwords(self) -> list:
        pws = [e.get() for e in self.pw_entries]
        try:
            from app_config import encrypt
            self.cfg["file_pws"] = [encrypt(p) if p else "" for p in pws]
        except Exception:
            pass
        return [p for p in pws if p]

    # ---------------- 폴더링 ----------------
    def _make_folders(self):
        if self.running:
            return
        if not self.path:
            messagebox.showinfo(TITLE, "먼저 [초안 넣기]로 초안 평가표를 넣어 주세요. 초안이 있는 폴더의 '품질평가 작성'에 폴더링을 만듭니다.",
                                parent=self)
            return
        vols = self._chosen()
        if not vols:
            messagebox.showinfo(TITLE, "폴더링을 만들 권을 체크해 주세요.", parent=self)
            return
        if not messagebox.askokcancel(
                TITLE, "와이즈(WISE)를 켜 주세요.\n\n"
                       "해약처리현황 같은 WISE 화면을 캡처해 폴더링에 넣습니다.\n"
                       "WISE를 켠 뒤 [확인]을 누르면 폴더링을 만듭니다.", parent=self):
            return
        pws = self.passwords()
        wcode = self.wise_code.get().strip().upper()
        self.cfg["wise_complex"] = wcode
        import re
        basic = [c for c in re.split(r"[\s,;·/]+", self.basic_codes.get().strip().upper()) if c]
        basic = list(dict.fromkeys(basic))
        self.cfg["wise_basic_complexes"] = ", ".join(basic)
        root = self._evid_root()
        items = [i for i in self.items if qe.volume_of(i.part) in vols]
        names = ", ".join(qe.VOLUMES[v] for v in vols)
        step = self.step.get()
        if step != ALL_NOS:                         # 한 번호만: '4권 1-1'
            sv, sno = step.split(" ", 1)
            items = [i for i in items if qe.volume_of(i.part) == int(sv.rstrip("권")) and i.no == sno]
            if not items:
                messagebox.showinfo(TITLE, f"{step}은(는) 체크한 권에 없습니다. 권 체크를 확인해 주세요.", parent=self)
                return
            names = f"{step} ({items[0].label.split(' ', 1)[-1]} 등 {len(items)}항목)"
        made = qe.make_folders(root, items)
        self.say(f"📁 {names} 폴더링: 새 폴더 {made}개 ({root})")
        import evidence_fetch as ef
        try:
            year = int(self.year.get())
        except ValueError:
            year = dt.date.today().year
        refs, _years = ef.plan(items, year)
        n_refs = sum(len(v) for v in refs.values())
        self._refresh()
        need_moumi = any((i.no, i.seq) in ef.MOUMI_SOURCES or "ledger" in ef.DOC_RULES.get((i.no, i.seq), {})
                         for i in items)          # 자료집계 취합자료 엑셀·대장에서 제목으로 고르는 문서
        use_homnet = bool((n_refs or need_moumi) and self.homnet_run)
        if use_homnet:
            ask = (f"{names} 폴더링을 만들었습니다(새 폴더 {made}개).\n\n"
                   f"초안의 평가 근거에 적힌 문서 {n_refs}건을 홈넷 기록물등록대장에서 받아\n"
                   "보고서 4권처럼 쪽마다 그림 파일로 항목 폴더에 넣을까요?\n"
                   "(이름·동호수·연락처는 000으로 가림, 열리지 않는 파일은 건너뛰고 이유를 폴더에 적음)\n\n"
                   "WISE가 켜져 있으면 해약처리현황 같은 화면도 열린 탭에서 캡처해 넣습니다.\n"
                   "홈넷에 로그인하며, 문서가 많으면 시간이 걸립니다. 이미 받은 문서는 건너뜁니다.")
        else:
            ask = (f"{names} 폴더링을 만들었습니다(새 폴더 {made}개).\n\n"
                   "초안의 평가 근거에 문서번호가 없어 대장에서 받을 문서는 없습니다.\n"
                   "폴더에 있는 받은 파일을 그림으로 바꾸고, WISE가 켜져 있으면 화면을 캡처해 넣을까요?")
        if not messagebox.askyesno(TITLE, ask, parent=self):
            return
        self._start_busy()
        pw = self.cfg.get("homnet_pw", "")
        office = self.center.get().strip() or self.cfg.get("단지명", "")
        from quality_view import _cache_dir
        cache = _cache_dir()

        def post(fn):
            try:
                self.after(0, fn)
            except (tk.TclError, RuntimeError):
                pass

        def say(m):
            post(lambda m=m: self.say(m))

        def job(driver, _log):
            import page_images
            with page_images.AutoAllow(say):
                return ef.fetch(driver, items, root, year, cache, pw, office, log=say, stop=self.stop_ev,
                                passwords=pws, complex_code=wcode, basic_codes=basic)

        def ok(res):
            stopped = self.stop_ev.is_set()
            self._end_busy()
            self._refresh()
            if stopped:                              # 멈췄으면 요약·다음 번호 넘기기 없이 끝
                self.say("⏹ 멈췄습니다. 받은 파일은 그대로 두었고, 다시 [폴더링 만들기]를 누르면 남은 것만 이어서 만듭니다.")
                return
            lines = [f"받은 문서 {res['docs']}건 · 첨부 {res['attach']}개 · 이미 있어 건너뜀 {res['skipped']}건"]
            if res.get("lists"):
                lines.append(f"매월 문서는 대장 검색 목록 그림 {res['lists']}장으로 넣음")
            if res.get("wise") or res.get("wise_fail"):
                lines.append(f"WISE 화면 캡처 {res.get('wise', 0)}개" +
                             (f" (못 한 것 {res['wise_fail']}개)" if res.get("wise_fail") else ""))
            if res.get("converted_fail"):
                lines.append(f"열리지 않아 건너뛴 파일 {res['converted_fail']}개")
            if res["not_found"]:
                lines.append(f"대장에서 못 찾은 근거 {len(res['not_found'])}건: " + ", ".join(res["not_found"][:8]))
            if res["failed"]:
                lines.append(f"받지 못한 문서 {len(res['failed'])}건(아래 기록 참고)")
                for x in res["failed"]:
                    self.say(f"   ✗ {x}")
            self.say("✅ " + " / ".join(lines))
            nxt = ""
            if step != ALL_NOS:                     # 한 번호씩: 검토한 뒤 다음 번호를 누르게 미리 골라 둔다
                nxt = self._next_step()
                if nxt:
                    self.step.set(nxt)
                self.say(f"   {step} 끝 — 폴더를 검토한 뒤 " +
                         (f"[폴더링 만들기]를 누르면 다음 번호({nxt})를 만듭니다." if nxt else "모든 번호를 마쳤습니다."))
            if messagebox.askyesno(TITLE, "\n".join(lines) + "\n\n폴더링을 열어 검토할까요?\n"
                                   f"(저장하지 못한 파일과 이유는 항목 폴더의 '{ef.REASON_NAME}'에 적었습니다)"
                                   + (f"\n\n다음 번호({nxt})를 골라 두었습니다." if nxt else ""),
                                   parent=self):
                if step != ALL_NOS:
                    self._startfile_dir(os.path.dirname(qe.item_dir(root, items[0], create=True)))
                else:
                    self._open_root(vols[0] if len(vols) == 1 else None)

        def err(ex):
            self._end_busy()
            self._refresh()
            self.say(f"❌ 대장에서 받지 못했습니다: {ex}")
            messagebox.showerror(TITLE, f"대장에서 받지 못했습니다.\n{ex}", parent=self)

        if not use_homnet:                  # 대장에서 받을 것이 없으면 홈넷 없이 그림 바꾸기·WISE 캡처만
            import threading

            def local():
                try:
                    r = job(None, say)
                except Exception as ex:
                    post(lambda ex=ex: err(ex))
                else:
                    post(lambda: ok(r))
            self.say("▶ 폴더링의 파일을 그림으로 바꾸고 WISE 화면을 캡처합니다…")
            threading.Thread(target=local, daemon=True).start()
            return
        self.say("▶ 홈넷에 로그인해 대장에서 평가 근거 문서를 받습니다…")
        self.homnet_run(job, ok, err)

    def _start_busy(self):
        self.running = True
        self.stop_ev.clear()
        self.stop_btn.state(["!disabled"])
        self.go_btn.state(["disabled"])
        self.stop_btn.pack(side="right")
        self.pb.pack(side="left")
        self.pb.start(15)
        self.config(cursor="watch")

    def _end_busy(self):
        self.running = False
        try:
            self.pb.stop()
            self.pb.pack_forget()
            self.stop_btn.pack_forget()
            self.go_btn.state(["!disabled"])
            self.config(cursor="")
        except tk.TclError:
            pass

    def _open_root(self, vol=None):
        if self.custom_root and os.path.isdir(self.custom_root):
            ui_kit.open_path(self.custom_root, self)
            return
        root = self._evid_root()
        if not root:
            messagebox.showinfo(TITLE, "먼저 [초안 넣기]로 초안을 넣어 주세요.", parent=self)
            return
        vols = [vol] if vol else self._chosen()
        d = qe.volume_dir(root, vols[0]) if len(vols) == 1 else root
        os.makedirs(d, exist_ok=True)
        ui_kit.open_path(d, self)

    # ---------------- 작성 ----------------
    def _go(self):
        if self.running:
            return
        vols = self._chosen()
        if not vols:
            messagebox.showinfo(TITLE, "작성할 권을 체크해 주세요.", parent=self)
            return
        try:
            year = int(self.year.get())
        except ValueError:
            messagebox.showwarning(TITLE, "평가년도를 숫자로 넣어 주세요.", parent=self)
            return
        center, chief = self.center.get().strip(), self.chief.get().strip()
        if not self.path and not messagebox.askyesno(
                TITLE, "초안을 넣지 않았습니다.\n점수와 증빙 없이 표지·서약서만 바꿔 만들까요?", parent=self):
            return
        self.cfg["quality_chief"] = chief
        if center:
            self.cfg["단지명"] = center
        out_dir = hr.default_out_dir(self.path)
        pws = self.passwords()
        self._start_busy()
        items, path = list(self.items), self.path
        custom = self.custom_root if self.custom_root and os.path.isdir(self.custom_root) else ""
        if custom:
            self.say(f"📂 내가 만든 폴더링의 사진을 넣습니다: {custom}")

        def post(fn):
            try:
                self.after(0, fn)
            except (tk.TclError, RuntimeError):
                pass

        def work():
            done, errs = [], []
            for v in vols:
                if self.stop_ev.is_set():
                    break
                post(lambda v=v: self.say(f"▶ {qe.VOLUMES[v]} 작성 중… (한글이 뒤에서 일합니다. 1~3분)"))
                try:
                    out, res = hr.build(v, items, path, out_dir, year, center, chief,
                                        log=lambda m: post(lambda m=m: self.say("   " + m)), stop=self.stop_ev,
                                        passwords=pws, custom_root=custom)
                    done.append((v, out, res))
                except Exception as ex:
                    errs.append((v, ex))
            post(lambda: self._finish(done, errs))

        threading.Thread(target=work, daemon=True).start()

    def _finish(self, done, errs):
        self._end_busy()
        lines = []
        for v, out, res in done:
            msg = f"✅ {qe.VOLUMES[v]}: 점수 {res['scores']}칸 · 증빙 {res['files']}쪽(사진칸 {res['photos']}개)"
            if res["pages_added"]:
                msg += f" (증빙 쪽 {res['pages_added']}쪽 늘림)"
            self.say(msg + f"\n   → {out}")
            if res["locked"]:
                self.say(f"   ⚠ 비밀번호로 열지 못한 파일: {', '.join(res['locked'])}")
            if res["no_page"]:
                self.say(f"   ⚠ 양식에 증빙 쪽이 없어 사진을 넣지 못한 번호: {', '.join(res['no_page'])}")
            lines.append(msg)
        for v, ex in errs:
            self.say(f"❌ {qe.VOLUMES[v]}: {ex}")
            lines.append(f"❌ {qe.VOLUMES[v]}: {ex}")
        if not done:
            if errs:
                messagebox.showerror(TITLE, "\n".join(lines), parent=self)
            return
        self.say("※ 단지개요(위치·면적·준공일 등)는 양식 예시 그대로입니다. 한글에서 고쳐 주세요.")
        if messagebox.askyesno(TITLE, "\n".join(lines) + "\n\n만든 한글파일을 열까요?\n"
                               "(단지개요는 양식 예시 그대로라 한글에서 고쳐 주세요)", parent=self):
            for _v, out, _r in done:
                if os.path.exists(out):
                    ui_kit.open_path(out, self)

    def _close(self):
        if self.running:
            if not messagebox.askyesno(TITLE, "작성 중입니다. 멈추고 닫을까요?", parent=self):
                return
            self.stop_ev.set()
        self.destroy()
