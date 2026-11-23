"""체크 목록 일정판(ScheduleBoard)과 [임대업무 일정표] 창.

- 위쪽 ◀ ▶로 보는 달을 바꾼다. 매월 항목은 그 달 체크, 분기별·정해진 달 항목은 그 해 체크를 보여 준다.
- 이름의 {월+3} 같은 달 글자는 보는 달에 따라 바뀐다(11월에 '소명안내(2월)' → 12월엔 '(3월)').
- 묶음: 이번 달(일반·매월) / 분기별 / 정해진 달.
- 줄 오른쪽 ▲▼로 순번(같은 묶음 안 차례)을 바꾸고, ✕로 지운다. 이름을 두 번 누르면 이름을 고친다.
- 체크·추가·삭제·순번은 곧바로 저장된다(work_schedule).
- ScheduleBoard는 [임대업무 일정표](창)와 [나의 공문 작성](본문 화면) 둘 다 쓴다.
  나의 공문은 줄마다 서식('tpl')이 있어 [✎ 작성]으로 그 서식을 바로 연다.
"""
from __future__ import annotations

import datetime as dt
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import ui_kit
import work_schedule as ws

F = ui_kit.FONT
TITLE = "임대업무 일정표"
UPLOAD_BUNDLE = "PDF로 넣은 서식"      # pdf_import.BUNDLE (나의 공문 업로드로 만든 서식)
UPLOAD_LABEL = "PDF 업로드"


class ScheduleBoard(tk.Frame):
    """체크 목록 일정판.

    path: 저장 파일(None이면 임대업무 일정표 파일). defaults: 파일이 없을 때 처음 목록.
    word: '업무'·'공문' 같은 낱말(묶음 제목·안내에 쓴다).
    on_add(board) → 넣을 항목 목록(없으면 기본 [업무 추가] 창). on_open(task): [✎ 작성]을 누르면 부른다.
    """

    def __init__(self, master, k: float = 1.0, title: str = TITLE, path: str | None = None, defaults=None,
                 word: str = "업무", add_text: str = "➕ 업무 추가", on_add=None, on_open=None, intro: str = ""):
        super().__init__(master, background=ui_kit.PAGE)
        self.k, self.title_text, self.path, self.word = k, title, path, word
        self.on_add, self.on_open = on_add, on_open
        self.sections = ((f"이번 달 {word}", ("일반", "매월")), (f"분기별 {word}", ("분기별",)),
                         (f"정해진 달 {word}", ("정해진 달",)))
        today = dt.date.today()
        self.year, self.month = today.year, today.month
        self._defaults = defaults
        self.tasks = ws.load(path, defaults)
        self.hide_done = tk.BooleanVar(value=False)

        top = ttk.Frame(self, padding=(16, 12, 16, 4))
        top.pack(fill="x")
        ttk.Label(top, text=title, font=(F, 15, "bold")).pack(side="left")
        ttk.Button(top, text=add_text, style="Accent.TButton", command=self._add).pack(side="right")
        if intro:
            ttk.Label(self, text=intro, foreground=ui_kit.SUB, padding=(16, 0, 16, 4),
                      wraplength=int(900 * k), justify="left").pack(fill="x")

        nav = ttk.Frame(self, padding=(16, 2, 16, 6))
        nav.pack(fill="x")
        ttk.Button(nav, text="◀", width=3, command=lambda: self._move(-1)).pack(side="left")
        self.month_lbl = ttk.Label(nav, font=(F, 12, "bold"), width=12, anchor="center")
        self.month_lbl.pack(side="left", padx=6)
        ttk.Button(nav, text="▶", width=3, command=lambda: self._move(1)).pack(side="left")
        ttk.Button(nav, text="이번 달", command=self._this_month).pack(side="left", padx=8)
        ttk.Checkbutton(nav, text=f"끝낸 {word} 숨기기", variable=self.hide_done, command=self._draw).pack(side="left")
        self.sum_lbl = ttk.Label(nav, foreground=ui_kit.SUB)
        self.sum_lbl.pack(side="right")

        tips = "체크하면 바로 저장됩니다 · 이름을 두 번 누르면 이름 고치기 · ▲▼ 순번 바꾸기 · ✕ 지우기"
        if on_open:
            tips = "✎ 작성: 그 공문 쓰기 · " + tips
        ttk.Label(self, text=tips, foreground=ui_kit.SUB, padding=(16, 0, 16, 6)).pack(fill="x")

        holder = ttk.Frame(self, padding=(16, 0, 4, 12))
        holder.pack(fill="both", expand=True)
        self.cv = tk.Canvas(holder, highlightthickness=0, background=ui_kit.CARD)
        sb = ttk.Scrollbar(holder, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=sb.set)
        self.cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.body = tk.Frame(self.cv, background=ui_kit.CARD)
        self.win = self.cv.create_window(0, 0, anchor="nw", window=self.body)
        self.body.bind("<Configure>", lambda _e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self.win, width=e.width))
        # 휠: 목록 위에 마우스가 있을 때만 이 목록을 굴린다(본문 화면으로 쓸 때 다른 화면 휠과 겹치지 않게)
        self.cv.bind("<Enter>", lambda _e: self.cv.bind_all("<MouseWheel>", self._wheel))
        self.cv.bind("<Leave>", lambda _e: self.cv.unbind_all("<MouseWheel>"))
        self._draw()

    def _wheel(self, e):
        try:
            self.cv.yview_scroll(-1 if e.delta > 0 else 1, "units")
        except tk.TclError:
            pass

    def reload(self):
        """저장 파일을 다시 읽어 그린다(다른 화면에서 고쳤을 수 있을 때)."""
        self.tasks = ws.load(self.path, self._defaults)
        self._draw()

    # ---------------- 보기 ----------------
    def _move(self, step: int):
        self.year, self.month = ws.shift(self.year, self.month, step)
        self._draw()

    def _this_month(self):
        today = dt.date.today()
        self.year, self.month = today.year, today.month
        self._draw()

    def _shown(self, t) -> bool:
        if t["kind"] == "정해진 달" and not t.get("months"):
            return True
        if not self.hide_done.get():
            return True
        key = ws.current_slot(t, self.year, self.month)
        if key is None:                      # 정해진 달 항목인데 이번 달이 아님 → 숨김 보기에서는 뺀다
            return False
        return not ws.is_done(t, key)

    def _draw(self):
        self.month_lbl.config(text=f"{self.year}년 {self.month}월")
        for w in self.body.winfo_children():
            w.destroy()
        todo = done = 0
        for t in self.tasks:
            key = ws.current_slot(t, self.year, self.month)
            if key is not None:
                if ws.is_done(t, key):
                    done += 1
                else:
                    todo += 1
        self.sum_lbl.config(text=f"이번 달 할 일 {todo} · 끝냄 {done}")
        for n, (name, kinds) in enumerate(self.sections):
            items = [t for t in self.tasks if t["kind"] in kinds]
            head = tk.Frame(self.body, background=ui_kit.PRIMARY_SOFT)
            head.pack(fill="x", pady=(10, 2))
            label = f"■ {name} ({self.month}월)" if n == 0 else f"■ {name}"
            tk.Label(head, text=label, background=ui_kit.PRIMARY_SOFT, foreground=ui_kit.TEXT,
                     font=(F, 11, "bold"), padx=8, pady=4).pack(side="left")
            if n == 1:
                q = (self.month - 1) // 3 + 1
                tk.Label(head, text=f"{self.year}년 · 지금은 {q}분기", background=ui_kit.PRIMARY_SOFT,
                         foreground=ui_kit.SUB, font=(F, 9)).pack(side="left")
            elif n == 2:
                tk.Label(head, text=f"{self.year}년", background=ui_kit.PRIMARY_SOFT,
                         foreground=ui_kit.SUB, font=(F, 9)).pack(side="left")
            shown = [t for t in items if self._shown(t)]
            if not shown:
                tk.Label(self.body, text=f"({self.word} 없음)" if not items else "(모두 끝냈습니다)",
                         background=ui_kit.CARD, foreground=ui_kit.MUTED, font=(F, 10), padx=12,
                         pady=4).pack(anchor="w")
            for t in shown:
                self._row(t, items.index(t) + 1, kinds)
        self.cv.yview_moveto(0)

    def _link(self, parent, text, cmd, bg, fg=None, hover=None, font=None):
        fg = fg or ui_kit.MUTED
        b = tk.Label(parent, text=text, background=bg, foreground=fg, font=font or (F, 9), cursor="hand2", padx=3)
        b.pack(side="right")
        b.bind("<Button-1>", lambda _e: cmd())
        b.bind("<Enter>", lambda _e: b.config(foreground=hover or ui_kit.PRIMARY))
        b.bind("<Leave>", lambda _e: b.config(foreground=fg))
        return b

    def _row(self, t, no: int = 0, kinds=()):
        bg = ui_kit.CARD
        row = tk.Frame(self.body, background=bg)
        row.pack(fill="x", padx=4, pady=1)
        slots = ws.slots(t, self.year, self.month)
        cur = ws.current_slot(t, self.year, self.month)
        self._link(row, "✕", lambda: self._delete(t), bg, hover=ui_kit.DANGER, font=(F, 10))
        for sym, step in (("▼", 1), ("▲", -1)):             # 순번 바꾸기(같은 묶음 안에서 한 칸씩)
            self._link(row, sym, lambda s=step: self._move_task(t, s, kinds), bg)
        if self.on_open and t.get("tpl"):
            self._link(row, "✎ 작성", lambda: self.on_open(t), bg, fg=ui_kit.PRIMARY, hover=ui_kit.PRIMARY_D,
                       font=(F, 10, "bold"))
        if no:
            tk.Label(row, text=f"{no}.", background=bg, foreground=ui_kit.SUB, font=(F, 10), width=3,
                     anchor="e").pack(side="left")
        if t["kind"] in ("일반", "매월"):
            key = slots[0][0]
            var = tk.BooleanVar(value=ws.is_done(t, key))
            text = ws.render(t["title"], self.year, self.month) + ("  · 한 번" if t["kind"] == "일반" else "")
            cb = tk.Checkbutton(row, text=text, variable=var, background=bg, activebackground=bg, anchor="w",
                                font=(F, 11, "overstrike") if var.get() else (F, 11),
                                foreground=ui_kit.MUTED if var.get() else ui_kit.TEXT,
                                command=lambda: self._toggle(t, key, var.get()))
            cb.pack(side="left", fill="x", expand=True, anchor="w")
            cb.bind("<Double-Button-1>", lambda _e: self._rename(t))
            return
        lbl = tk.Label(row, text=ws.render(t["title"], self.year, self.month), background=bg,
                       foreground=ui_kit.TEXT, font=(F, 11, "bold"), anchor="w", padx=6)
        lbl.pack(fill="x", anchor="w")
        lbl.bind("<Double-Button-1>", lambda _e: self._rename(t))
        boxes = tk.Frame(self.body, background=bg)
        boxes.pack(fill="x", padx=(28, 4), pady=(0, 4))
        if not slots:
            tk.Label(boxes, text="(달을 고르지 않았습니다 — 지우고 다시 넣어 주세요)", background=bg,
                     foreground=ui_kit.MUTED, font=(F, 9)).pack(side="left")
        for key, label in slots:
            var = tk.BooleanVar(value=ws.is_done(t, key))
            now = key == cur
            cb = tk.Checkbutton(boxes, text=label, variable=var, background=bg, activebackground=bg,
                                font=(F, 10, "bold") if now else (F, 10),
                                foreground=ui_kit.PRIMARY if now else ui_kit.TEXT,
                                command=lambda k=key, v=var: self._toggle(t, k, v.get()))
            cb.pack(side="left", padx=(0, 8))

    # ---------------- 고치기 ----------------
    def _save(self):
        try:
            ws.save(self.tasks, self.path)
        except OSError as e:
            messagebox.showerror(self.title_text, f"저장하지 못했습니다.\n{e}", parent=self)

    def _toggle(self, t, key, on):
        ws.set_done(t, key, on)
        self._save()
        self.after_idle(self._redraw_keep)

    def _redraw_keep(self):
        y = self.cv.yview()[0]
        self._draw()
        self.update_idletasks()
        self.cv.yview_moveto(y)

    def _move_task(self, t, step, kinds):
        if ws.move(self.tasks, t, step, kinds):
            self._save()
            self._redraw_keep()

    def _delete(self, t):
        if not messagebox.askyesno(self.title_text,
                                   f"'{ws.render(t['title'], self.year, self.month)}'을(를) 목록에서 지울까요?",
                                   parent=self):
            return
        self.tasks = [x for x in self.tasks if x is not t]
        self._save()
        self._redraw_keep()

    def _rename(self, t):
        name = simpledialog.askstring(self.title_text, "이름\n" + ws.TOKEN_HELP.replace(", {년", ",\n{년"),
                                      initialvalue=t["title"], parent=self)
        if name and name.strip():
            t["title"] = name.strip()
            self._save()
            self._redraw_keep()

    def add_tasks(self, new: list):
        if not new:
            return
        self.tasks.extend(new)
        self._save()
        self._draw()
        self.update_idletasks()
        self.cv.yview_moveto(0 if all(t["kind"] in ("일반", "매월") for t in new) else 1.0)

    def _add(self):
        if self.on_add:
            self.add_tasks(self.on_add(self) or [])
            return
        dlg = AddTaskDialog(self, self.k)
        self.wait_window(dlg)
        if dlg.result:
            self.add_tasks([dlg.result])


class ScheduleDialog(tk.Toplevel):
    """[임대업무 기록하기 → 임대업무 일정표] 창."""

    def __init__(self, master, k: float = 1.0):
        super().__init__(master)
        self.title(TITLE)
        self.geometry(f"{int(720 * k)}x{int(760 * k)}")
        self.configure(background=ui_kit.PAGE)
        self.board = ScheduleBoard(self, k)
        self.board.pack(fill="both", expand=True)


class KindPicker(ttk.Frame):
    """구분(일반·매월·분기별·정해진 달) + 정해진 달이면 달 고르기."""

    HINTS = {"일반": "한 번", "매월": "달마다", "분기별": "1~4분기", "정해진 달": "고른 달마다"}

    def __init__(self, master, kind: str = "매월"):
        super().__init__(master)
        self.kind = tk.StringVar(value=kind)
        kinds = ttk.Frame(self)
        kinds.pack(anchor="w")
        for kd in ws.KINDS:
            ttk.Radiobutton(kinds, text=f"{kd} ({self.HINTS[kd]})", value=kd, variable=self.kind,
                            command=self._changed).pack(side="left", padx=(0, 10))
        self.months_box = ttk.Frame(self)
        self.month_vars = {}
        for m in range(1, 13):
            v = tk.BooleanVar(value=False)
            self.month_vars[m] = v
            ttk.Checkbutton(self.months_box, text=f"{m}월", variable=v).grid(row=(m - 1) // 6, column=(m - 1) % 6,
                                                                           sticky="w", padx=(0, 8))

    def _changed(self):
        if self.kind.get() == "정해진 달":
            self.months_box.pack(anchor="w", pady=(6, 0))
        else:
            self.months_box.pack_forget()

    def months(self) -> list[int]:
        return [m for m, v in self.month_vars.items() if v.get()]

    def check(self, parent) -> bool:
        if self.kind.get() == "정해진 달" and not self.months():
            messagebox.showinfo("구분", "할 달을 하나 이상 골라 주세요.", parent=parent)
            return False
        return True


def _center(win, master):
    win.update_idletasks()
    x = master.winfo_rootx() + max(0, (master.winfo_width() - win.winfo_reqwidth()) // 2)
    y = master.winfo_rooty() + max(0, (master.winfo_height() - win.winfo_reqheight()) // 3)
    win.geometry(f"+{x}+{y}")


class AddTaskDialog(tk.Toplevel):
    """새 업무: 이름 + 구분(일반·매월·분기별·정해진 달) + 정해진 달이면 달 고르기."""

    def __init__(self, master, k: float = 1.0):
        super().__init__(master)
        self.result = None
        self.title("업무 추가")
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.configure(padx=20, pady=16)
        ttk.Label(self, text="업무 이름").grid(row=0, column=0, sticky="w", pady=4)
        self.name = ttk.Entry(self, width=40)
        self.name.grid(row=0, column=1, sticky="w", pady=4)
        ttk.Label(self, text="구분").grid(row=1, column=0, sticky="nw", pady=4)
        self.kp = KindPicker(self)
        self.kp.grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(self, text=ws.TOKEN_HELP.replace(", {년", ",\n{년"), foreground=ui_kit.SUB,
                  justify="left").grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        btns = ttk.Frame(self)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="추가", style="Accent.TButton", command=self._ok).pack(side="left", padx=6)
        ttk.Button(btns, text="취소", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        _center(self, master)
        self.name.focus_set()
        self.grab_set()

    def _ok(self):
        name = self.name.get().strip()
        if not name:
            messagebox.showinfo("업무 추가", "업무 이름을 넣어 주세요.", parent=self)
            return
        if not self.kp.check(self):
            return
        self.result = ws.new_task(name, self.kp.kind.get(), self.kp.months())
        self.destroy()


class TemplatePickDialog(tk.Toplevel):
    """[나의 공문 작성 → 공문 넣기]: 등록된 서식 중 내 업무 공문을 골라(여러 개) 구분과 함께 넣는다.

    items: [(서식 키, 분야, 묶음, 이름)]. have: 이미 넣은 서식 키(목록에 '넣음'으로 보인다).
    result: [(서식 키, 이름)], kind, months.
    """

    def __init__(self, master, items: list, have: set, k: float = 1.0):
        super().__init__(master)
        # 업로드한 PDF로 만든 서식(묶음 'PDF로 넣은 서식')을 맨 위에
        items = sorted(items, key=lambda x: x[2] != UPLOAD_BUNDLE)
        self.items, self.have, self.result = items, have, None
        self.kind, self.months = "매월", []
        self.title("나의 공문에 넣기")
        self.transient(master.winfo_toplevel())
        self.geometry(f"{int(760 * k)}x{int(620 * k)}")
        self.configure(padx=16, pady=12)
        ttk.Label(self, text="내 업무 공문 고르기", font=(F, 13, "bold")).pack(anchor="w")
        ttk.Label(self, text="여러 개를 고를 수 있습니다(Ctrl·Shift + 누르기). 📄 = 업로드한 PDF 공문(맨 위). "
                             "이미 넣은 공문은 '넣음'으로 보입니다.",
                  foreground=ui_kit.SUB).pack(anchor="w", pady=(2, 8))
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Label(bar, text="찾기").pack(side="left")
        self.q = tk.StringVar()
        ent = ttk.Entry(bar, textvariable=self.q, width=30)
        ent.pack(side="left", padx=6)
        self.q.trace_add("write", lambda *_: self._fill())
        self.area = tk.StringVar(value="전체")
        areas = ["전체"] + ([UPLOAD_LABEL] if any(b == UPLOAD_BUNDLE for _, _, b, _ in items) else [])             + list(dict.fromkeys(a for _, a, _, _ in items))
        cb = ttk.Combobox(bar, state="readonly", values=areas, textvariable=self.area, width=12)
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._fill())
        box = ttk.Frame(self)
        box.pack(fill="both", expand=True, pady=8)
        self.tv = ttk.Treeview(box, columns=("area", "bundle", "name", "have"), show="headings",
                               selectmode="extended")
        for c, t, w in (("area", "분야", 80), ("bundle", "묶음", 170), ("name", "공문", 380), ("have", "", 50)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=int(w * k), anchor="center" if c in ("area", "have") else "w",
                           stretch=c == "name")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tv.bind("<Double-Button-1>", lambda _e: self._ok())
        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Label(row, text="구분").pack(side="left", anchor="n", padx=(0, 8))
        self.kp = KindPicker(row, "매월")
        self.kp.pack(side="left")
        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="고른 공문 넣기", style="Accent.TButton", command=self._ok).pack(side="right", padx=6)
        self.bind("<Escape>", lambda _e: self.destroy())
        self._fill()
        _center(self, master)
        ent.focus_set()
        self.grab_set()

    def _fill(self):
        q = self.q.get().strip().replace(" ", "")
        area = self.area.get()
        self.tv.delete(*self.tv.get_children())
        for n, (key, a, bundle, name) in enumerate(self.items):
            if area == UPLOAD_LABEL:
                if bundle != UPLOAD_BUNDLE:
                    continue
            elif area != "전체" and a != area:
                continue
            if q and q not in (name + bundle).replace(" ", ""):
                continue
            shown = ("📄 " + name) if bundle == UPLOAD_BUNDLE else name
            self.tv.insert("", "end", iid=str(n), values=(a, bundle, shown, "넣음" if key in self.have else ""))

    def _ok(self):
        sel = [self.items[int(i)] for i in self.tv.selection()]
        if not sel:
            messagebox.showinfo("나의 공문", "넣을 공문을 골라 주세요.", parent=self)
            return
        if not self.kp.check(self):
            return
        self.result = [(key, name) for key, _a, _b, name in sel]
        self.kind, self.months = self.kp.kind.get(), self.kp.months()
        self.destroy()
