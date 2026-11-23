"""단지기본정보 [면적 자동으로 작성하기] 창(평형·세대수 칸 옆 단추).

① 직접 작성하는 항목(단지명·담당자·지역본부·계정) → [다음]
② 'WISE에 접속해 주세요' → 접속 후 [확인]
   → WISE 임대조건관리(건설)에서 평형(전용면적)·세대수만 읽어 단지기본정보에 채운다(wise_rent).
③ 채운 내용 보여 주기
"""
import tkinter as tk
from tkinter import messagebox, ttk

import complex_info
import ui_kit
import wise_rent

FONT = (ui_kit.FONT, 10)
FONT_B = (ui_kit.FONT, 10, "bold")
TITLE = (ui_kit.FONT, 14, "bold")


class OneTouchDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("면적 자동으로 작성하기")
        self.transient(app.root)
        self.resizable(False, False)
        self.configure(padx=22, pady=18)
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)
        self.result = None
        self._page1()
        self.update_idletasks()
        x = app.root.winfo_rootx() + max(0, (app.root.winfo_width() - self.winfo_reqwidth()) // 2)
        y = app.root.winfo_rooty() + 60
        self.geometry(f"+{x}+{y}")
        self.grab_set()

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _head(self, step, title, sub):
        ttk.Label(self.body, text=f"{step}  {title}", font=TITLE).pack(anchor="w")
        ttk.Label(self.body, text=sub, foreground="#666", wraplength=560, justify="left").pack(anchor="w",
                                                                                            pady=(2, 12))

    def _buttons(self, *specs):
        bar = ttk.Frame(self.body)
        bar.pack(fill="x", pady=(16, 0))
        for text, cmd, primary in reversed(specs):
            if primary:
                self.app._orange_button(bar, text, cmd).pack(side="right", padx=(8, 0))
            else:
                ttk.Button(bar, text=text, command=cmd).pack(side="right", padx=(8, 0))
        return bar

    # ---------------- ① 직접 작성하는 항목 ----------------
    def _page1(self):
        self._clear()
        a = self.app
        self._head("①", "직접 작성하는 항목",
                   "WISE에 없는 값은 여기서 넣어 주세요. 평형(전용면적)과 세대수는 "
                   "다음 단계에서 WISE 임대조건을 읽어 자동으로 채웁니다.")
        info = ttk.LabelFrame(self.body, text="우리 단지")
        info.pack(fill="x", pady=4)
        self.v = {}

        def row(parent, r, label, value, secret=False, hint=""):
            ttk.Label(parent, text=label).grid(row=r, column=0, sticky="e", padx=8, pady=3)
            e = ttk.Entry(parent, width=30, show="●" if secret else "")
            e.insert(0, value)
            e.grid(row=r, column=1, sticky="w", padx=4, pady=3)
            if hint:
                ttk.Label(parent, text=hint, foreground="#777").grid(row=r, column=2, sticky="w", padx=4)
            return e

        self.v["단지명"] = row(info, 0, "단지명 *", a.info_entries["단지명"].get(), hint="WISE 단지 검색에 씁니다")
        ttk.Label(info, text="WISE 지역본부").grid(row=1, column=0, sticky="e", padx=8, pady=3)
        self.region = ttk.Combobox(info, values=(wise_rent.KEEP_REGION,) + wise_rent.REGIONS,
                                   state="readonly", width=28)
        self.region.set(a.cfg.get("wise_region") or wise_rent.KEEP_REGION)
        self.region.grid(row=1, column=1, sticky="w", padx=4, pady=3)
        self.v["담당자"] = row(info, 2, "담당자 이름", a.info_entries["담당자"].get())
        self.v["전화번호"] = row(info, 3, "담당자 전화번호", a.info_entries["전화번호"].get())

        acc = ttk.LabelFrame(self.body, text="계정 (홈넷 로그인에 씁니다)")
        acc.pack(fill="x", pady=(10, 4))
        self.v["homnet_id"] = row(acc, 0, "홈넷 아이디(사번)", a.homnet_id.get())
        self.v["homnet_pw"] = row(acc, 1, "홈넷 비밀번호", a.homnet_pw.get(), secret=True)
        self.v["vpn_id"] = row(acc, 2, "VPN 아이디", a.vpn_id.get(), hint="사무실(사내망)에서는 비워도 됩니다")
        self.v["vpn_pw"] = row(acc, 3, "VPN 비밀번호", a.vpn_pw.get(), secret=True)
        self.remember = tk.BooleanVar(value=a.remember.get())
        ttk.Checkbutton(acc, text="이 PC에 계정 기억하기 (암호화 저장)",
                        variable=self.remember).grid(row=4, column=1, sticky="w", padx=4, pady=(3, 6))
        self.msg = ttk.Label(self.body, foreground="#c62828")
        self.msg.pack(anchor="w", pady=(6, 0))
        self._buttons(("취소", self.destroy, False), ("다음  ▶", self._next1, True))
        self.v["단지명"].focus_set()

    def _next1(self):
        if not self.v["단지명"].get().strip():
            self.msg.config(text="⚠ 단지명을 넣어 주세요. WISE에서 이 이름으로 단지를 찾습니다.")
            return
        self.saved = {k: e.get() if k.endswith("_pw") else e.get().strip() for k, e in self.v.items()}
        self.saved["region"] = self.region.get()
        self.saved["remember"] = self.remember.get()
        self._apply_manual()
        self._page2()

    def _apply_manual(self):
        """①에서 넣은 값을 단지기본정보 화면 칸에 옮긴다."""
        a, s = self.app, self.saved
        for key in ("단지명", "담당자", "전화번호"):
            e = a.info_entries[key]
            e.delete(0, "end")
            e.insert(0, s[key])
        for key in ("homnet_id", "homnet_pw", "vpn_id", "vpn_pw"):
            e = getattr(a, key)
            e.delete(0, "end")
            e.insert(0, s[key])
        a.remember.set(s["remember"])
        a.cfg["wise_region"] = "" if s["region"] == wise_rent.KEEP_REGION else s["region"]
        a._show_derived()

    # ---------------- ② WISE 접속 ----------------
    def _page2(self, error: str = ""):
        self._clear()
        self._head("②", "WISE에 접속해 주세요",
                   "WISE를 켜고 로그인한 뒤 [확인]을 눌러 주세요.")
        box = ttk.Frame(self.body)
        box.pack(fill="x")
        steps = ("확인을 누르면 KODAS가 WISE에서 다음을 차례로 누릅니다.",
                 "   건설임대 > 공급 > 공급임대조건 산정 > 임대조건관리(건설)",
                 f"   지역본부({self.saved['region']}) · 단지({self.saved['단지명']}) 고르기 → [검색]",
                 "   나온 임대조건에서 평형(전용면적)과 세대수를 읽어 단지기본정보에 채웁니다.",
                 "",
                 "• 읽기만 하고 WISE에 저장하거나 고치지 않습니다.",
                 "• WISE 창은 자동으로 최대화합니다. 끝날 때까지 마우스·키보드를 건드리지 마세요.",
                 "• 멈추려면 ESC를 누르세요.")
        for t in steps:
            ttk.Label(box, text=t, font=FONT_B if t.startswith("   ") else FONT).pack(anchor="w")
        self.msg = ttk.Label(self.body, foreground="#c62828", wraplength=560, justify="left", text=error)
        self.msg.pack(anchor="w", pady=(10, 0))
        self._buttons(("◀  이전", self._page1, False), ("확인", self._start, True))

    def _start(self):
        import wise_input
        if not wise_input.find_window(wise_rent.WISE_TITLE, wise_rent.WISE_CLASS):
            self.msg.config(text="⚠ WISE 창을 찾지 못했습니다. WISE에 접속(로그인)한 뒤 [확인]을 눌러 주세요.")
            return
        a = self.app
        if a.busy:
            self.msg.config(text="⚠ 다른 작업이 진행 중입니다. 끝난 뒤 다시 눌러 주세요.")
            return
        region, name = self.saved["region"], self.saved["단지명"]
        self.grab_release()
        self.withdraw()
        a.log(f"⚡ 면적 자동 작성: WISE에서 '{name}' 임대조건을 읽습니다(멈추려면 ESC).")
        a.run_bg(lambda: wise_rent.Wise(a.log).run(region, name), self._done, self._fail)

    def _back_to_front(self):
        a = self.app
        try:
            a.root.deiconify()
            a.root.lift()
            a.root.focus_force()
        except tk.TclError:
            pass
        self.deiconify()
        self.lift()
        self.grab_set()

    def _fail(self, ex):
        if not self.winfo_exists():
            return
        self._back_to_front()
        self._page2(f"⚠ {ex}")

    def _done(self, res: wise_rent.Result):
        if not self.winfo_exists():
            return
        self._fill(res)
        self._back_to_front()
        self._page3(res)

    # ---------------- 채우기 ----------------
    def _fill(self, res: wise_rent.Result):
        a = self.app
        types = res.types[:complex_info.TYPE_LIMIT]
        while a.type_n < len(types) and a._add_type_row():     # 평형이 많으면 칸을 늘린다
            pass
        for i in range(1, a.type_n + 1):
            area, units = (types[i - 1][0], str(types[i - 1][1])) if i <= len(types) else ("", "")   # 전용면적
            for key, val in ((f"평형{i}", area), (f"평형{i}세대수", units)):
                e = a.complex_entries[key]
                e.delete(0, "end")
                e.insert(0, val)
        a._save_settings()
        a._refresh()
        a.log(f"✅ 면적 자동 작성: 평형 {len(types)}개, 총 {sum(t[1] for t in types):,}세대를 채우고 저장했습니다.")

    # ---------------- ③ 결과 ----------------
    def _page3(self, res: wise_rent.Result):
        self._clear()
        self._head("③", "면적을 채웠습니다",
                   f"WISE 임대조건(임대시작일 {res.start} 기준)의 평형·세대수를 단지기본정보에 채우고 저장했습니다. "
                   "화면에서 한 번 확인해 주세요.")
        top = ttk.Frame(self.body)
        top.pack(fill="x")
        for label, val in (("단지", res.complex_name), ("지역본부", res.region or "-")):
            r = ttk.Frame(top)
            r.pack(anchor="w")
            ttk.Label(r, text=f"{label}", width=10, foreground="#666").pack(side="left")
            ttk.Label(r, text=val, font=FONT_B).pack(side="left")
        tv = ttk.Treeview(self.body, columns=("no", "area", "units"), show="headings",
                          height=min(max(len(res.types), 1), 8))
        for c, t, w in (("no", "", 70), ("area", "평형(전용면적 ㎡)", 150), ("units", "세대수", 100)):
            tv.heading(c, text=t)
            tv.column(c, width=w, anchor="e" if c != "no" else "center")
        for i, (area, units, *_) in enumerate(res.types, 1):
            tv.insert("", "end", values=(f"평형{i}" if i <= complex_info.TYPE_LIMIT else "넘침", area, units))
        tv.pack(anchor="w", pady=(10, 4))
        total = sum(t[1] for t in res.types)
        ttk.Label(self.body, text=f"합계 {total:,}세대 (총세대수 칸이 비어 있으면 이 합계가 들어갑니다)",
                  foreground="#555").pack(anchor="w")
        if len(res.types) > complex_info.TYPE_LIMIT:
            ttk.Label(self.body, foreground="#c62828",
                      text=f"⚠ 평형이 {len(res.types)}개라 앞의 {complex_info.TYPE_LIMIT}개만 칸에 넣었습니다.").pack(
                anchor="w", pady=(4, 0))
        self._buttons(("닫기", self.destroy, True))


def open_dialog(app):
    if not getattr(app, "complex_entries", None):
        messagebox.showinfo("면적 자동으로 작성하기", "단지기본정보 화면을 먼저 열어 주세요.", parent=app.root)
        return
    OneTouchDialog(app)
