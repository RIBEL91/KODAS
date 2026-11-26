"""바로가기 [자격검증 기록]: 주민등록 검증결과를 엑셀처럼 표로 보고 칸을 바로 고친다.
기록은 KODAS 안(사용자 폴더의 자격검증기록.json)에 따로 저장한다 — 관계철 엑셀과 연결하지 않는다.
처음 한 번만 바탕화면 관계철 엑셀이 있으면 그 내용을 가져와 시작한다(엑셀은 읽기만).

탭: 갱신계약 · 주택정기 · 명의변경 · 예비자정기
- 칸을 두 번 누르거나, 칸을 고르고 글자를 치거나 Enter·F2 → 그 자리에서 고치기
- 갱신계약·주택정기의 월(입주자격검색)은 목록에서 고른다(26-1월 …)
- Enter: 저장하고 아래 칸 / Tab: 저장하고 오른쪽 칸 / Esc: 취소 / Delete: 칸 비우기
- [행 추가]: 시트의 마지막 기록 아래에 새 줄
- 총계는 세대주+배우자+세대원으로 자동 계산(직접 고치지 않음)
- [행 삭제]: 고른 줄을 지운다
- 갱신완료가 계약완료 등(주택정기는 확정)이면 맨 위 묶음 안에 접혀 숨는다
"""
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import ui_kit
import verify_log as vl

F = ui_kit.FONT
WIDTHS = {"text": 100, "date": 104, "num": 58, "total": 58, "status": 130, "check": 74, "memo": 320}
LABEL = "입주자격검색"
DONE = "done"           # 완료 묶음 줄의 iid
# 날짜 칸 달력(공문 작성 화면과 같은 모양)
CAL = dict(locale="ko_KR", firstweekday="sunday", showweeknumbers=False,
           background=ui_kit.PRIMARY, foreground="#ffffff", bordercolor=ui_kit.BORDER,
           headersbackground=ui_kit.PRIMARY_SOFT, headersforeground=ui_kit.PRIMARY_D,
           normalbackground="#ffffff", normalforeground=ui_kit.TEXT,
           weekendbackground="#ffffff", weekendforeground=ui_kit.DANGER,
           othermonthbackground="#f6f8fc", othermonthforeground=ui_kit.MUTED,
           othermonthwebackground="#f6f8fc", othermonthweforeground="#e9a8a8",
           selectbackground=ui_kit.PRIMARY, selectforeground="#ffffff")


class VerifyDialog(tk.Toplevel):
    def __init__(self, master, cfg: dict, k: float = 1.0):
        super().__init__(master)
        self.cfg, self.k = cfg, k
        self.title("자격검증 기록 — 주민등록 검증결과")
        self.geometry(f"{int(1240 * k)}x{int(720 * k)}")
        self.configure(background=ui_kit.PAGE)
        self.rows: dict[str, list] = {s.key: [] for s in vl.SHEETS}      # 탭별 기록(줄 차례)
        self.tabs: dict[str, dict] = {}                                   # 탭별 화면
        self.editor = None               # (view, rec, field, widget, 처음 글자)
        self.queue: list = []            # 저장할 것 [{"sheet": key, "rec": 기록, "status": 상태 바뀜}]
        self.busy = False

        top = ttk.Frame(self, padding=(14, 12, 14, 4))
        top.pack(fill="x")
        ttk.Label(top, text="자격검증 기록", font=(F, 15, "bold")).pack(side="left")
        ttk.Label(top, text="칸을 두 번 누르거나 골라서 바로 적으면 곧바로 저장됩니다",
                  foreground=ui_kit.SUB).pack(side="left", padx=12)
        self.xl_up = ttk.Button(top, text="⬆ 엑셀 올려 적용", command=self._import_xlsx)
        self.xl_up.pack(side="right")
        self.xl_down = ttk.Button(top, text="⬇ 엑셀로 받기", command=self._export_xlsx)
        self.xl_down.pack(side="right", padx=(0, 6))
        self.add_btns = []               # 탭마다 [＋ 행 추가](튜토리얼이 가리킨다)
        # 소명안내를 체크하면 소명완료일 = 오늘 + 소명기간(일)
        ttk.Label(top, text="일", foreground=ui_kit.SUB).pack(side="right", padx=(2, 16))
        self.call_days = tk.StringVar(value=str(self._call_days()))
        sp = ttk.Spinbox(top, from_=1, to=90, width=4, textvariable=self.call_days, font=(F, 10),
                         command=self._keep_call_days)
        sp.pack(side="right")
        sp.bind("<FocusOut>", lambda _e: self._keep_call_days())
        sp.bind("<Return>", lambda _e: self._keep_call_days())
        ttk.Label(top, text="소명기간", foreground=ui_kit.SUB).pack(side="right", padx=(0, 4))

        style = ttk.Style(self)
        style.configure("Grid.Treeview", rowheight=int(26 * self.k), font=(F, 10))
        style.configure("Grid.Treeview.Heading", font=(F, 10, "bold"))
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        for v in vl.VIEWS:
            self._build_tab(v)
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._close_editor(True))
        self.status = ttk.Label(self, foreground=ui_kit.SUB, padding=(14, 0, 14, 10))
        self.status.pack(fill="x")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(50, self.reload)

    # ---------------- 화면 ----------------
    def _build_tab(self, v: vl.View):
        s = v.sheet
        tab = ttk.Frame(self.nb, padding=(8, 8))
        self.nb.add(tab, text=f"  {v.key}  ")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 6))
        add = ttk.Button(bar, text="＋ 행 추가", style="Accent.TButton", command=lambda v=v: self._add_row(v))
        add.pack(side="left")
        self.add_btns.append(add)
        ttk.Button(bar, text="행 삭제", command=lambda v=v: self._delete_row(v)).pack(side="left", padx=(6, 0))
        cell = ttk.Label(bar, foreground=ui_kit.PRIMARY_D, font=(F, 10, "bold"))
        cell.pack(side="left", padx=12)
        ttk.Label(bar, foreground=ui_kit.SUB,
                  text="두 번 누르기·글자 치기·Enter로 고치기  |  Enter 아래로 · Tab 오른쪽으로 · Esc 취소  |  "
                       "총계는 자동").pack(side="right")
        box = ttk.Frame(tab)
        box.pack(fill="both", expand=True)
        cols = [f.key for f in s.fields]
        tree = ttk.Treeview(box, columns=cols, show="headings", selectmode="browse", style="Grid.Treeview")
        for f in s.fields:
            head = ("월" if v.months else "구분") if f.key == LABEL else f.key
            tree.heading(f.key, text=head.replace("(문서통보일)", ""))
            tree.column(f.key, width=int(WIDTHS[f.kind] * self.k), anchor="w" if f.kind == "memo" else "center",
                        stretch=f.kind == "memo")
        tree.tag_configure("even", background=ui_kit.HOVER_SOFT)     # 짝수 줄은 옅은 디자인 색(줄 구분, 사용자 2026-11-23)
        tree.tag_configure("saving", foreground="#b45309")
        tree.tag_configure("group", background="#e9edf5", foreground=ui_kit.SUB, font=(F, 10, "bold"))
        tree.tag_configure("doneRow", foreground="#7a8496", background="#f8f9fb")
        tree.tag_configure("doneEven", background="#eceff4")
        sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        # 고른 줄의 자격검증 기록사항: 표 아래 넓은 칸에 적는다(다른 줄을 고르거나 칸을 벗어나면 저장)
        mf = ttk.LabelFrame(tab, text=f" {vl.MEMO} ", padding=(10, 6))
        mf.pack(fill="x", pady=(8, 0))
        mtop = ttk.Frame(mf)
        mtop.pack(fill="x")
        mlbl = ttk.Label(mtop, foreground=ui_kit.SUB, text="표에서 줄을 고르면 그 줄의 기록사항을 여기에 적습니다")
        mlbl.pack(side="left")
        ttk.Button(mtop, text="기록 저장", command=lambda v=v: self._memo_save(v)).pack(side="right")
        ttk.Label(mtop, foreground=ui_kit.MUTED, text="Ctrl+Enter 저장 · 다른 줄을 고르면 자동 저장").pack(
            side="right", padx=8)
        memo = tk.Text(mf, height=4, wrap="word", font=(F, 10), relief="solid", bd=1, state="disabled",
                       background=ui_kit.PAGE)
        memo.pack(fill="x", pady=(4, 0))
        memo.bind("<Control-Return>", lambda _e, v=v: (self._memo_save(v), "break")[1])
        memo.bind("<FocusOut>", lambda _e, v=v: self._memo_save(v))
        self.tabs[v.key] = {"tree": tree, "cell": cell, "col": 0, "open": False,
                            "memo": memo, "memo_lbl": mlbl, "memo_rec": None}
        tree.bind("<Button-1>", lambda e, v=v: self._click(v, e))
        tree.bind("<Double-1>", lambda e, v=v: self._double(v, e))
        tree.bind("<Return>", lambda _e, v=v: self._edit(v))
        tree.bind("<F2>", lambda _e, v=v: self._edit(v))
        tree.bind("<Left>", lambda _e, v=v: self._move_col(v, -1))
        tree.bind("<Right>", lambda _e, v=v: self._move_col(v, 1))
        tree.bind("<Tab>", lambda _e, v=v: self._move_col(v, 1))
        tree.bind("<Delete>", lambda _e, v=v: self._clear_cell(v))
        tree.bind("<Key>", lambda e, v=v: self._type_start(v, e))
        tree.bind("<<TreeviewSelect>>", lambda _e, v=v: self._show_cell(v))
        tree.bind("<MouseWheel>", lambda _e: self._close_editor(True), add="+")

    def _call_days(self) -> int:
        try:
            n = int(str(self.cfg.get("call_days", vl.DEFAULT_CALL_DAYS)).strip())
        except (TypeError, ValueError):
            n = vl.DEFAULT_CALL_DAYS
        return n if 0 < n <= 365 else vl.DEFAULT_CALL_DAYS

    def _keep_call_days(self):
        """소명기간 칸 값을 설정에 둔다(창을 닫으면 저장)."""
        try:
            n = int(self.call_days.get().strip())
        except ValueError:
            n = 0
        if not 0 < n <= 365:
            self.call_days.set(str(self._call_days()))
            return
        self.cfg["call_days"] = n

    def _toggle_call(self, v: vl.View, rec: dict):
        """소명안내 체크 켜기·끄기. 켜면 소명완료일 = 오늘 + 소명기간, 끄면 둘 다 비운다."""
        self._keep_call_days()
        on = not str(rec.get(vl.CALL, "") or "").strip()
        vl.set_call(rec, on, days=self._call_days())
        self._save(v.sheet, rec)
        name = str(rec.get(LABEL, "")).replace(chr(10), " ")
        self._set_status(f"{name}: 소명안내 체크 → 소명완료일 {vl.show(rec[vl.CALL_DUE])} (오늘 + {self._call_days()}일)"
                         if on else f"{name}: 소명안내 체크를 풀고 소명완료일을 비웠습니다.")

    def _set_status(self, text: str, error: bool = False):
        self.status.config(text=text, foreground=ui_kit.DANGER if error else ui_kit.SUB)

    def _rec(self, s: vl.Sheet, row: int) -> dict | None:
        return next((r for r in self.rows[s.key] if r["_row"] == row), None)

    def _sel(self, v: vl.View) -> dict | None:
        """고른 줄의 기록(완료 묶음 줄을 골랐으면 None)."""
        sel = self.tabs[v.key]["tree"].selection()
        if not sel or sel[0] == DONE:
            return None
        return self._rec(v.sheet, int(sel[0]))

    @staticmethod
    def _cell_text(rec: dict, f: vl.Field) -> str:
        return vl.show(rec.get(f.key, "")).replace("\n", " ⏎ ")

    def _saving(self, rec: dict) -> bool:
        return any(q["rec"] is rec for q in self.queue)

    def _fill_tree(self, v: vl.View, keep: dict | None = None):
        """표를 다시 그린다. 갱신완료(계약완료 등) 줄은 맨 위 묶음 안에(처음엔 접힘)."""
        t = self.tabs[v.key]
        tree = t["tree"]
        tree.delete(*tree.get_children())
        rows = self.rows[v.sheet.key]
        done = [r for r in rows if vl.is_done(v.sheet, r)]
        rest = [r for r in rows if not vl.is_done(v.sheet, r)]
        if done:
            n = len(v.sheet.fields)
            label = f"{'▼' if t['open'] else '▶'} {vl.status_key(v.sheet)} {len(done)}건"
            tree.insert("", "end", iid=DONE, open=t["open"], tags=("group",),
                        values=[label, "(누르면 " + ("접기" if t["open"] else "펼치기") + ")"] + [""] * (n - 2))
            for i, r in enumerate(done):
                tree.insert(DONE, "end", iid=str(r["_row"]), values=[self._cell_text(r, f) for f in v.sheet.fields],
                            tags=("doneRow",) + (("doneEven",) if i % 2 else ()) + (("saving",) if self._saving(r) else ()))
        for i, r in enumerate(rest):
            tree.insert("", "end", iid=str(r["_row"]), values=[self._cell_text(r, f) for f in v.sheet.fields],
                        tags=(("even",) if i % 2 else ()) + (("saving",) if self._saving(r) else ()))
        if keep is not None and tree.exists(str(keep["_row"])):
            iid = str(keep["_row"])
            if tree.parent(iid) == DONE and not t["open"]:
                iid = DONE
            tree.selection_set(iid)
            tree.focus(iid)
            tree.see(iid)
        else:
            kids = tree.get_children()
            if kids:
                tree.see(kids[-1])

    def _refresh_rec(self, s: vl.Sheet, rec: dict):
        """그 기록의 줄만 다시 그린다(완료 묶음을 오가야 하면 표 전체를 다시 그린다)."""
        for v in vl.VIEWS:
            if v.sheet is not s:
                continue
            tree, iid = self.tabs[v.key]["tree"], str(rec["_row"])
            in_done = tree.exists(iid) and tree.parent(iid) == DONE
            if not tree.exists(iid) or in_done != vl.is_done(s, rec):
                self._fill_tree(v, keep=rec)
                continue
            tags = [x for x in tree.item(iid, "tags") if x != "saving"] + (["saving"] if self._saving(rec) else [])
            tree.item(iid, values=[self._cell_text(rec, f) for f in s.fields], tags=tags)

    def _toggle_done(self, v: vl.View):
        t = self.tabs[v.key]
        t["open"] = not t["open"]
        self._fill_tree(v)
        if t["tree"].exists(DONE):
            t["tree"].selection_set(DONE)
            t["tree"].see(DONE)

    # ---------------- 칸 고르기 ----------------
    def _click(self, v: vl.View, e):
        self._close_editor(True)
        tree, t = self.tabs[v.key]["tree"], self.tabs[v.key]
        if tree.identify_row(e.y) == DONE:          # 완료 묶음 줄: 눌러서 펼치기·접기
            self.after(1, lambda: self._toggle_done(v))
            return "break"
        col = tree.identify_column(e.x)
        if col:
            t["col"] = max(0, int(col[1:]) - 1)
        row = tree.identify_row(e.y)
        f = v.sheet.fields[t["col"]] if col else None
        if f is not None and f.kind == "check" and row and row != DONE and tree.identify_region(e.x, e.y) == "cell":
            rec = self._rec(v.sheet, int(row))
            if rec is not None:          # 소명안내 칸은 한 번 눌러 체크
                tree.selection_set(row)
                tree.focus(row)
                self.after(1, lambda: (self._toggle_call(v, rec), self._show_cell(v)))
                return "break"
        self.after(1, lambda: self._show_cell(v))

    def _double(self, v: vl.View, e):
        """두 번 누르기: 고치기. 소명안내 칸은 한 번 누를 때 이미 체크했으니 넘어간다."""
        tree = self.tabs[v.key]["tree"]
        col = tree.identify_column(e.x)
        if col and v.sheet.fields[max(0, int(col[1:]) - 1)].kind == "check":
            return "break"
        self._click(v, e)
        self._edit(v)
        return "break"

    def _memo_load(self, v: vl.View, rec: dict | None):
        """표 아래 기록사항 칸에 rec의 기록사항을 띄운다(앞에 띄운 줄에서 고친 것은 먼저 저장)."""
        t = self.tabs[v.key]
        if t["memo_rec"] is rec:
            return
        self._memo_save(v)
        memo = t["memo"]
        t["memo_rec"] = rec
        memo.config(state="normal")
        memo.delete("1.0", "end")
        if rec is None:
            memo.config(state="disabled", background=ui_kit.PAGE)
            t["memo_lbl"].config(text="표에서 줄을 고르면 그 줄의 기록사항을 여기에 적습니다")
            return
        memo.insert("1.0", vl.show(rec.get(vl.MEMO, "")))
        memo.config(background="#ffffff")
        name = str(rec.get(LABEL, "")).replace("\n", " ")
        t["memo_lbl"].config(text=name)

    def _memo_load_empty(self, v: vl.View):
        t = self.tabs[v.key]
        t["memo"].config(state="normal")
        t["memo"].delete("1.0", "end")
        t["memo"].config(state="disabled", background=ui_kit.PAGE)
        t["memo_lbl"].config(text="표에서 줄을 고르면 그 줄의 기록사항을 여기에 적습니다")

    def _memo_save(self, v: vl.View):
        t = self.tabs[v.key]
        rec = t["memo_rec"]
        if rec is None:
            return
        text = t["memo"].get("1.0", "end-1c").strip()
        if text != str(rec.get(vl.MEMO, "") or "").strip():
            rec[vl.MEMO] = text
            self._save(v.sheet, rec)

    def _show_cell(self, v: vl.View):
        t = self.tabs[v.key]
        rec = self._sel(v)
        self._memo_load(v, rec)
        if rec is None:
            t["cell"].config(text="")
            return
        f = v.sheet.fields[t["col"]]
        name = str(rec.get(LABEL, "")).replace("\n", " ")
        t["cell"].config(text=f"▶ {name} · {f.key}")

    def _move_col(self, v: vl.View, d: int):
        t = self.tabs[v.key]
        t["col"] = (t["col"] + d) % len(v.sheet.fields)
        self._show_cell(v)
        return "break"

    # ---------------- 칸 고치기 ----------------
    def _type_start(self, v: vl.View, e):
        """칸을 고른 채 글자를 치면 엑셀처럼 그 글자로 고치기 시작."""
        if e.char and e.char.isprintable() and not (e.state & 0x4):     # Ctrl 조합은 빼고
            self._edit(v, first=e.char)
            return "break"

    def _edit(self, v: vl.View, first: str | None = None):
        s, t = v.sheet, self.tabs[v.key]
        tree = t["tree"]
        sel = tree.selection()
        if sel and sel[0] == DONE:
            self._toggle_done(v)
            return "break"
        rec = self._sel(v)
        if rec is None:
            return "break"
        f = s.fields[t["col"]]
        if f.kind == "total":
            self._set_status("총계는 세대주+배우자+세대원으로 자동 계산됩니다.")
            return "break"
        if f.kind == "check":           # 소명안내: 누르면 체크 켜기·끄기(소명완료일 자동)
            if first is None or first == " ":
                self._toggle_call(v, rec)
            return "break"
        if f.kind == "memo":            # 기록사항은 표 아래 넓은 칸에 적는다
            self._memo_load(v, rec)
            memo = t["memo"]
            if first is not None:
                memo.insert("end", first)
            memo.focus_set()
            memo.mark_set("insert", "end-1c")
            return "break"
        iid = str(rec["_row"])
        tree.see(iid)
        tree.update_idletasks()
        box = tree.bbox(iid, f.key)
        if not box:
            return "break"
        x, y, w, h = box
        shown = vl.show(rec.get(f.key, ""))
        month = f.key == LABEL and v.months
        if f.kind == "memo":
            ed = tk.Text(tree, wrap="word", font=(F, 10), relief="solid", bd=1, height=4)
            ed.insert("1.0", shown if first is None else first)
            ed.place(x=x, y=y, width=max(w, int(320 * self.k)), height=int(96 * self.k))
            ed.bind("<Return>", lambda _e: (self._commit(v, rec, f, ed, 1), "break")[1])
            ed.bind("<Shift-Return>", lambda _e: None)          # 줄바꿈은 Shift+Enter
            ed.mark_set("insert", "end-1c")
            start = shown
        else:
            start = shown.replace("\n", " / ")                  # 한 줄 칸: 줄바꿈은 ' / '로 보여 준다
            if month:          # 월은 목록에서 고른다
                ed = ttk.Combobox(tree, values=vl.month_choices(current=shown), font=(F, 10), state="readonly")
                ed.set(shown or vl.next_label(self.rows[s.key]))
                ed.bind("<<ComboboxSelected>>", lambda _e: self._commit(v, rec, f, ed, 0, move=False))
                self.after(30, lambda: (ed.winfo_exists() and ed.event_generate("<Down>")))   # 목록을 바로 펼친다
            elif f.kind == "date":       # 날짜는 달력에서 고른다(글씨 고정 — 타자로 움직이지 않게)
                ed = ui_kit.fixed_date_entry(tree, "y. m. d.", CAL, font=(F, 10))
                cur = rec.get(f.key)
                if isinstance(cur, vl.dt.date):
                    ed.set_date(cur)
                ed.delete(0, "end")
                ed.insert(0, start)
                ed.bind("<<DateEntrySelected>>", lambda _e: self._commit(v, rec, f, ed, 0, move=False))
                self.after(40, lambda: (ed.winfo_exists() and ed.drop_down()))   # 달력을 바로 연다
            elif f.kind == "status" or f.key == LABEL:
                ed = ttk.Combobox(tree, values=s.status_values if f.kind == "status" else (s.label_choices or vl.OTHER_NAMES),
                                  font=(F, 10))
                ed.insert(0, start if first is None else first)
                ed.bind("<<ComboboxSelected>>", lambda _e: self._commit(v, rec, f, ed, 0, move=False))
            else:
                ed = ttk.Entry(tree, font=(F, 10))
                ed.insert(0, start if first is None else first)
            ed.place(x=x, y=y, width=max(w, int(110 * self.k)), height=h)
            ed.bind("<Return>", lambda _e: (self._commit(v, rec, f, ed, 1), "break")[1])
            if not month and f.kind != "date":
                ed.icursor("end")
                if first is None:
                    ed.select_range(0, "end")
        ed.bind("<Tab>", lambda _e: (self._commit(v, rec, f, ed, 0, right=True), "break")[1])
        ed.bind("<Escape>", lambda _e: (self._close_editor(False), tree.focus_set(), "break")[2])
        ed.bind("<FocusOut>", lambda _e: self.after(10, lambda: self._focus_out(ed)))
        ed.focus_set()
        self.editor = (v, rec, f, ed, start)
        return "break"

    def _focus_out(self, ed):
        if self.editor and self.editor[3] is ed:
            try:
                focus = self.focus_get()
            except (KeyError, tk.TclError):      # 콤보 펼침 목록에 포커스가 있을 때
                return
            if focus is not None and str(focus).startswith(str(ed)):
                return
            self._close_editor(True)

    def _close_editor(self, commit: bool):
        if not self.editor:
            return
        v, rec, f, ed, _ = self.editor
        if commit:
            self._commit(v, rec, f, ed, 0, move=False)
        else:
            self.editor = None
            ed.destroy()

    def _commit(self, v: vl.View, rec: dict, f: vl.Field, ed, down: int, right: bool = False, move: bool = True):
        if not self.editor or self.editor[3] is not ed:
            return
        start = self.editor[4]
        raw = (ed.get("1.0", "end-1c") if isinstance(ed, tk.Text) else ed.get()).strip()
        self.editor = None
        ed.destroy()
        s = v.sheet
        tree, t = self.tabs[v.key]["tree"], self.tabs[v.key]
        if raw != start.strip():          # 바뀐 것만 저장
            if f.kind == "date":
                val = vl.parse_date(raw)
            elif f.kind == "num":
                val = vl.parse_num(raw)
            elif f.key == "차수" and raw.isdigit():
                val = int(raw)
            else:
                val = raw
            was_done = vl.is_done(s, rec)
            rec[f.key] = val
            if f.key in vl.COUNT_KEYS:
                rec["총계"] = vl.total_of(rec)
            if f.kind == "date" and isinstance(val, str) and val:
                self._set_status(f"⚠ '{val}'은 날짜로 읽지 못해 글자 그대로 넣습니다(예: 2026. 11. 18.).",
                                 error=True)
            self._save(s, rec, status=f.kind == "status")
            if vl.is_done(s, rec) and not was_done:
                self._set_status(f"'{str(rec.get(LABEL, '')).replace(chr(10), ' ')}' 줄은 {rec.get(f.key)}라 맨 위 "
                                 "묶음으로 숨겼습니다.")
        tree.focus_set()
        if not move:
            self._show_cell(v)
            return
        if right:
            t["col"] = (t["col"] + 1) % len(s.fields)
        elif down:
            iid = str(rec["_row"])
            nxt = tree.next(iid) if tree.exists(iid) else ""
            if nxt:
                tree.selection_set(nxt)
                tree.focus(nxt)
                tree.see(nxt)
        self._show_cell(v)

    def _clear_cell(self, v: vl.View):
        """Delete: 고른 칸을 비운다(월·구분 칸은 비우지 않는다)."""
        t = self.tabs[v.key]
        rec = self._sel(v)
        f = v.sheet.fields[t["col"]]
        if rec is None or f.kind == "total" or f.key == LABEL:
            return "break"
        if f.kind == "check" and rec.get(f.key, "") != "":
            self._toggle_call(v, rec)
            return "break"
        if rec.get(f.key, "") != "":
            rec[f.key] = ""
            if f.key in vl.COUNT_KEYS:
                rec["총계"] = vl.total_of(rec)
            self._save(v.sheet, rec, status=f.kind == "status")
        return "break"

    # ---------------- 행 추가 ----------------
    def _add_row(self, v: vl.View):
        self._close_editor(True)
        s = v.sheet
        rows = self.rows[s.key]
        row = max([r["_row"] for r in rows], default=vl.FIRST_ROW - 1) + 1     # 시트의 마지막 기록 아래
        rec = {f.key: "" for f in s.fields}
        rec[LABEL] = (vl.next_label(rows) if v.months else (s.label_choices or vl.OTHER_NAMES)[0]) or ""
        rec["_row"] = row
        rows.append(rec)
        self._save(s, rec)
        self._fill_tree(v, keep=rec)
        t = self.tabs[v.key]
        t["col"] = 1 if v.months else 0        # 월은 미리 채웠으니 요청일부터
        t["tree"].focus_set()
        self._show_cell(v)
        self.after(30, lambda: self._edit(v))

    # ---------------- 저장(차례대로) ----------------
    def _save(self, s: vl.Sheet, rec: dict, status: bool = False):
        # 지금 저장 중인 줄을 또 고쳤으면 끝난 뒤 한 번 더 저장한다(저장 중인 값은 고치기 전 값)
        start = 1 if self.busy and self.queue else 0
        item = next((q for q in self.queue[start:] if q["rec"] is rec), None)
        if item:
            item["status"] = item["status"] or status
        else:
            self.queue.append({"sheet": s.key, "rec": rec, "status": status})
        self._refresh_rec(s, rec)
        self._pump()

    def _pump(self):
        if self.busy or not self.queue:
            return
        item = self.queue[0]
        s = next(x for x in vl.SHEETS if x.key == item["sheet"])
        rec = item["rec"]
        values = {k: v for k, v in rec.items() if k != "_row"}
        name = str(values.get(LABEL, "")).replace("\n", " ")
        row = rec["_row"]
        self._set_status(f"저장하는 중… ({s.key} {name})")

        def done(w: vl.Written):
            if self.queue and self.queue[0] is item:
                self.queue.pop(0)
            if w.moved_to != w.moved_from:          # 끝난 줄을 위로 옮겼다 → 줄 번호를 맞춘다
                vl.remap_rows(self.rows[s.key], w.moved_from, w.moved_to)
                for v in vl.VIEWS:
                    if v.sheet is s:
                        self._fill_tree(v, keep=rec)
            else:
                self._refresh_rec(s, rec)
            if self.queue:
                self._pump()
            else:
                self._set_status(f"✅ 저장했습니다 — {s.key} {name}")

        def fail():
            self.queue.clear()
            self.reload()

        self._run(lambda: vl.store_write(s, values, row, status_changed=item["status"]), done, fail)

    def _run(self, job, done, fail=None):
        """저장·읽기는 따로 돌리고(처음 엑셀 가져오기는 몇 초 걸린다), 끝나면 done(결과)."""
        self.busy = True
        box = {}

        def work():
            try:
                box["ok"] = job()
            except Exception as ex:      # ExcelError 등
                box["err"] = ex

        th = threading.Thread(target=work, daemon=True)
        th.start()

        def poll():
            if th.is_alive():
                self.after(120, poll)
                return
            self.busy = False
            if not self.winfo_exists():
                return
            if "err" in box:
                self._set_status(f"⚠ {box['err']}", error=True)
                messagebox.showwarning("자격검증 기록", str(box["err"]), parent=self)
                if fail:
                    fail()
            else:
                done(box["ok"])
        poll()

    # ---------------- 읽기 ----------------
    def reload(self):
        self._close_editor(True)
        if self.busy or self.queue:
            self._set_status("저장이 끝난 뒤 다시 읽어 주세요.")
            return
        first = not vl.store_exists()
        excel = vl.default_book() if first else ""
        self._set_status("처음이라 바탕화면 관계철 엑셀의 기록을 가져오는 중…(엑셀은 읽기만 합니다)"
                         if excel else "기록을 읽는 중…")

        def job():
            n = vl.store_import_excel(excel) if excel else None
            return vl.store_book(), n

        def done(res):
            book, n = res
            for s in vl.SHEETS:
                self.rows[s.key] = book.rows[s.key]
            for v in vl.VIEWS:
                self.tabs[v.key]["memo_rec"] = None
                self._memo_load_empty(v)
                self._fill_tree(v)
            self._set_status(f"관계철 엑셀에서 기록 {n}줄을 가져왔습니다. 이제부터는 엑셀과 따로 저장됩니다."
                             if n is not None else "")

        def fail():
            for v in vl.VIEWS:
                self._fill_tree(v)
        self._run(job, done, fail)

    def _delete_row(self, v: vl.View):
        self._close_editor(True)
        rec = self._sel(v)
        if rec is None:
            messagebox.showinfo("행 삭제", "지울 줄을 표에서 먼저 골라 주세요.", parent=self)
            return
        if self.busy or self.queue:
            self._set_status("저장이 끝난 뒤 다시 눌러 주세요.")
            return
        name = str(rec.get(LABEL, "")).replace("\n", " ")
        if not messagebox.askyesno("행 삭제", f"'{name}' 줄을 지울까요?", parent=self):
            return
        self.tabs[v.key]["memo_rec"] = None
        vl.store_delete(v.sheet, rec["_row"])
        self.rows[v.sheet.key] = vl.store_load()[v.sheet.key]
        self._memo_load_empty(v)
        self._fill_tree(v)
        self._set_status(f"'{name}' 줄을 지웠습니다.")

    # ---------------- 엑셀로 받기 · 올려 적용 ----------------
    def _wait_saved(self) -> bool:
        self._close_editor(True)
        for v in vl.VIEWS:
            self._memo_save(v)
        if self.busy or self.queue:
            self._set_status("저장이 끝난 뒤 다시 눌러 주세요.")
            return False
        return True

    def _export_xlsx(self):
        if not self._wait_saved():
            return
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            parent=self, title="자격검증 기록을 엑셀로 받기", defaultextension=".xlsx",
            initialdir=os.path.join(os.path.expanduser("~"), "Desktop"),
            initialfile=f"자격검증기록_{vl.dt.date.today():%Y%m%d}.xlsx", filetypes=[("엑셀 파일", "*.xlsx")])
        if not path:
            return
        self._set_status("엑셀로 쓰는 중…")

        def done(n):
            self._set_status(f"✅ 기록 {n}줄을 엑셀로 받았습니다 — {path}")
            if messagebox.askyesno("엑셀로 받기", f"기록 {n}줄을 저장했습니다.\n{path}\n\n지금 열어 볼까요?", parent=self):
                os.startfile(path)
        self._run(lambda: vl.store_export_xlsx(path), done)

    def _import_xlsx(self):
        if not self._wait_saved():
            return
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            parent=self, title="적용할 자격검증 기록 엑셀 고르기",
            initialdir=os.path.join(os.path.expanduser("~"), "Desktop"), filetypes=[("엑셀 파일", "*.xlsx")])
        if not path:
            return
        try:
            got = vl.read_xlsx(path)
        except vl.ExcelError as ex:
            messagebox.showwarning("엑셀 올려 적용", str(ex), parent=self)
            return
        lines = "\n".join(f"· {k}: 지금 {len(self.rows[k])}줄 → {len(rows)}줄" for k, rows in got.items())
        if not messagebox.askyesno(
                "엑셀 올려 적용",
                f"올린 파일 내용으로 기록을 바꿉니다.\n\n{lines}\n\n"
                "파일에 없는 시트는 그대로 둡니다. 지금 기록은 백업 폴더에 남겨 둡니다.\n적용할까요?", parent=self):
            return
        self._set_status("엑셀 내용을 적용하는 중…")

        def done(counts):
            book = vl.store_book()
            for s in vl.SHEETS:
                self.rows[s.key] = book.rows[s.key]
            for v in vl.VIEWS:
                self.tabs[v.key]["memo_rec"] = None
                self._memo_load_empty(v)
                self._fill_tree(v)
            self._set_status("✅ 엑셀 내용을 적용했습니다 — "
                             + " · ".join(f"{k} {n}줄" for k, n in counts.items()))
        self._run(lambda: vl.store_import_xlsx(path), done)

    def _close(self):
        self._close_editor(True)
        for v in vl.VIEWS:
            self._memo_save(v)
        if self.busy or self.queue:
            if not messagebox.askyesno("자격검증 기록", "아직 저장하는 중입니다. 그래도 닫을까요?", parent=self):
                return
        self.destroy()
