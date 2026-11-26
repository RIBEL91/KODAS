"""처음 시작할 때 보여 주는 튜토리얼(기능마다 화면을 직접 열고, 설명할 자리를 차례로 강조).

KODAS 창(또는 자격검증 기록 같은 보조 창) 위에 어두운 반투명 창을 덮고, 설명하는 자리만 구멍(투명)을
뚫어 밝게 보여 준다. 옆에 설명 카드(기능 이름 · 단계 n/N · 이전 · 다음 · 건너뛰기)를 띄운다.
Esc = 닫기, ←/→·Enter = 이전/다음.

단계 = dict(part=기능 이름, title=제목, text=설명, box=자리 찾기 함수 → 화면 좌표 (x0, y0, x1, y1) 또는 None,
           go=이 단계를 보여 주기 전에 부를 함수(화면 열기 등), over=덮을 창을 돌려주는 함수(없으면 KODAS 창),
           legend=[(글자, 색)] 색 안내 줄)

다 보거나 건너뛰면 KODAS 데이터에 '튜토리얼.json'을 남겨 다음부터는 저절로 뜨지 않는다.
[도움말 → 튜토리얼 다시 보기]로 언제든 다시 볼 수 있다.
"""
from __future__ import annotations

import json
import os
import tkinter as tk

import paths
import ui_kit

F = ui_kit.FONT
HOLE = "#ff00fe"           # 투명으로 바꿀 색(구멍)
DONE_NAME = "튜토리얼.json"


def done_path() -> str:
    return os.path.join(paths.data_dir(), DONE_NAME)


def seen() -> bool:
    return os.path.exists(done_path())


def mark_seen() -> None:
    try:
        os.makedirs(paths.data_dir(), exist_ok=True)
        with open(done_path(), "w", encoding="utf-8") as f:
            json.dump({"seen": True}, f)
    except OSError:
        pass


def reveal(widget):
    """스크롤 캔버스 안에 든 위젯이면, 그 위젯이 보이도록 캔버스를 굴린다(단지기본정보처럼 긴 화면)."""
    try:
        w = widget
        while w is not None and w.master is not None:
            if isinstance(w.master, tk.Canvas):
                cv, inner = w.master, w
                cv.update_idletasks()
                total = max(1, inner.winfo_height())
                y = widget.winfo_rooty() - inner.winfo_rooty()
                top = cv.canvasy(0)
                if not (top <= y and y + widget.winfo_height() <= top + cv.winfo_height()):
                    cv.yview_moveto(max(0.0, (y - 12) / total))
                    cv.update_idletasks()
            w = w.master
    except (tk.TclError, AttributeError):
        pass


def widget_box(*widgets):
    """위젯들을 모두 감싸는 화면 좌표(보이는 것만). 하나도 안 보이면 None. 먼저 첫 위젯이 보이게 굴린다."""
    if widgets and widgets[0] is not None:
        reveal(widgets[0])
    boxes = []
    for w in widgets:
        try:
            if w is not None and w.winfo_exists() and w.winfo_ismapped() and w.winfo_viewable():
                x, y = w.winfo_rootx(), w.winfo_rooty()
                boxes.append((x, y, x + w.winfo_width(), y + w.winfo_height()))
        except tk.TclError:
            pass
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def canvas_box(widget, key):
    """그림으로 그린 화면(홈·왼쪽 메뉴)의 rects[key] → 화면 좌표."""
    try:
        r = widget.rects.get(key)
        if not r or not widget.winfo_ismapped():
            return None
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        return x + r[0], y + r[1], x + r[2], y + r[3]
    except tk.TclError:
        return None


class Tutorial:
    PAD = 7

    def __init__(self, root: tk.Tk, steps: list, on_close=None):
        self.root, self.steps, self.on_close = root, steps, on_close
        self.i = 0
        self.alive = True
        self._job = None
        self.shade = tk.Toplevel(root)
        self.shade.withdraw()
        self.shade.overrideredirect(True)
        self.shade.configure(background="#0b1020")
        self.cv = tk.Canvas(self.shade, background="#0b1020", highlightthickness=0, cursor="arrow")
        self.cv.pack(fill="both", expand=True)
        try:
            self.shade.attributes("-alpha", 0.66)
            self.shade.attributes("-transparentcolor", HOLE)
            self.shade.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.card = tk.Toplevel(root)
        self.card.withdraw()
        self.card.overrideredirect(True)
        self.card.configure(background=ui_kit.PRIMARY)
        try:
            self.card.attributes("-topmost", True)
        except tk.TclError:
            pass
        self._build_card()
        for w in (self.shade, self.card):
            w.bind("<Escape>", lambda _e: self.close())
            w.bind("<Right>", lambda _e: self.next())
            w.bind("<Return>", lambda _e: self.next())
            w.bind("<Left>", lambda _e: self.prev())
        root.bind("<Configure>", lambda _e: self.alive and self._later(), add="+")   # 창을 옮기면 따라간다
        self.root.after(250, self.show)

    # ---------------- 카드 ----------------
    def _build_card(self):
        body = tk.Frame(self.card, background=ui_kit.CARD)
        body.pack(fill="both", expand=True, padx=2, pady=2)
        top = tk.Frame(body, background=ui_kit.CARD)
        top.pack(fill="x", padx=22, pady=(16, 0))
        self.part_lbl = tk.Label(top, background=ui_kit.PRIMARY, foreground="#ffffff", font=(F, 9, "bold"),
                                 padx=8, pady=1)
        self.part_lbl.pack(side="left")
        self.step_lbl = tk.Label(top, background=ui_kit.CARD, foreground=ui_kit.SUB, font=(F, 9), padx=8)
        self.step_lbl.pack(side="left")
        skip = tk.Label(top, text="건너뛰기 ✕", background=ui_kit.CARD, foreground=ui_kit.SUB, font=(F, 9),
                        cursor="hand2")
        skip.pack(side="right")
        skip.bind("<Button-1>", lambda _e: self.close())
        self.title_lbl = tk.Label(body, background=ui_kit.CARD, foreground=ui_kit.TEXT, font=(F, 14, "bold"),
                                  anchor="w", justify="left")
        self.title_lbl.pack(fill="x", padx=22, pady=(10, 4))
        self.text_lbl = tk.Label(body, background=ui_kit.CARD, foreground=ui_kit.SUB, font=(F, 10),
                                 anchor="w", justify="left", wraplength=340)
        self.text_lbl.pack(fill="x", padx=22)
        self.body = body
        self.legend = None                 # 색 안내 줄(단계마다 새로 만든다 — 빈 Frame은 줄어들지 않으므로)
        bottom = tk.Frame(body, background=ui_kit.CARD)
        self.bottom = bottom
        bottom.pack(fill="x", padx=22, pady=(14, 16))
        self.bar = tk.Canvas(bottom, width=110, height=6, background=ui_kit.CARD, highlightthickness=0)
        self.bar.pack(side="left")
        self.next_btn = self._button(bottom, "다음  ›", self.next, primary=True)
        self.next_btn.pack(side="right")
        self.prev_btn = self._button(bottom, "‹  이전", self.prev)
        self.prev_btn.pack(side="right", padx=(0, 8))

    def _button(self, parent, text, cmd, primary=False):
        bg, fg = (ui_kit.PRIMARY, "#ffffff") if primary else (ui_kit.HOVER_SOFT, ui_kit.TEXT)
        hover = ui_kit.PRIMARY_D if primary else ui_kit.PRIMARY_SOFT
        b = tk.Label(parent, text=text, background=bg, foreground=fg, font=(F, 10, "bold"), padx=16, pady=6,
                     cursor="hand2")
        b.bind("<Button-1>", lambda _e: cmd())
        b.bind("<Enter>", lambda _e: b.config(background=hover))
        b.bind("<Leave>", lambda _e: b.config(background=bg))
        return b

    # ---------------- 보여 주기 ----------------
    def _later(self):
        if self._job:
            self.root.after_cancel(self._job)
        self._job = self.root.after(150, self._place)

    def show(self):
        if not self.alive:
            return
        st = self.steps[self.i]
        if st.get("go"):
            try:
                st["go"]()
            except Exception:
                pass
        parts = list(dict.fromkeys(s["part"] for s in self.steps))
        same = [s for s in self.steps if s["part"] == st["part"]]
        self.part_lbl.config(text=f"{parts.index(st['part']) + 1}. {st['part']}")
        self.step_lbl.config(text=f"{same.index(st) + 1} / {len(same)}")
        self.title_lbl.config(text=st["title"])
        self.text_lbl.config(text=st["text"])
        if self.legend is not None:
            self.legend.destroy()
            self.legend = None
        if st.get("legend"):
            self.legend = tk.Frame(self.body, background=ui_kit.CARD)
            self.legend.pack(fill="x", padx=22, before=self.bottom)
        for text, color in st.get("legend") or ():
            row = tk.Frame(self.legend, background=ui_kit.CARD)
            row.pack(fill="x", pady=(6, 0))
            tk.Label(row, text="●", background=ui_kit.CARD, foreground=color, font=(F, 11)).pack(side="left")
            tk.Label(row, text=text, background=ui_kit.CARD, foreground=color, font=(F, 10, "bold"),
                     padx=6).pack(side="left")
        last = self.i == len(self.steps) - 1
        self.prev_btn.config(foreground=ui_kit.TEXT if self.i else ui_kit.MUTED)
        self.next_btn.config(text="시작하기  ✓" if last else "다음  ›")
        self.bar.delete("all")
        self.bar.create_rectangle(0, 0, 110, 6, fill=ui_kit.BORDER, outline="")
        self.bar.create_rectangle(0, 0, 110 * (self.i + 1) / len(self.steps), 6, fill=ui_kit.PRIMARY, outline="")
        self.root.update_idletasks()
        self.root.after(220, self._place)          # 연 화면이 다 그려진 뒤 자리를 잰다

    def _place(self):
        self._job = None
        if not self.alive:
            return
        st = self.steps[self.i]
        win = self.root
        try:
            if st.get("over"):
                win = st["over"]() or self.root
            if self.root.state() == "iconic":
                return
            win.update_idletasks()
            rx, ry = win.winfo_rootx(), win.winfo_rooty()
            rw, rh = win.winfo_width(), win.winfo_height()
        except tk.TclError:
            return
        self.shade.geometry(f"{rw}x{rh}+{rx}+{ry}")
        self.cv.delete("all")
        try:
            box = st["box"]() if st.get("box") else None
        except Exception:
            box = None
        if box:
            p = self.PAD
            x0, y0, x1, y1 = box[0] - rx - p, box[1] - ry - p, box[2] - rx + p, box[3] - ry + p
            ui_kit.round_rect(self.cv, x0 - 4, y0 - 4, x1 + 4, y1 + 4, 16, fill="#ffb21f", outline="")
            ui_kit.round_rect(self.cv, x0, y0, x1, y1, 12, fill=HOLE, outline="")
        self.shade.deiconify()
        self.shade.lift()
        # 카드: 구멍 오른쪽 → 왼쪽 → 아래 → 위, 덮은 창 안에 들어오게
        self.card.update_idletasks()
        cw, ch = max(390, self.card.winfo_reqwidth()), self.card.winfo_reqheight()
        gap = 20
        if box:
            bx0, by0, bx1, by1 = box[0] - self.PAD, box[1] - self.PAD, box[2] + self.PAD, box[3] + self.PAD
            if bx1 + gap + cw <= rx + rw - 10:
                x, y = bx1 + gap, by0
            elif bx0 - gap - cw >= rx + 10:
                x, y = bx0 - gap - cw, by0
            elif by1 + gap + ch <= ry + rh - 10:
                x, y = bx0, by1 + gap
            else:
                x, y = bx0, by0 - gap - ch
        else:
            x, y = rx + (rw - cw) // 2, ry + (rh - ch) // 2
        x = int(min(max(x, rx + 10), rx + rw - cw - 10))
        y = int(min(max(y, ry + 10), ry + rh - ch - 10))
        self.card.geometry(f"{cw}x{ch}+{x}+{y}")
        self.card.deiconify()
        self.card.lift()
        self.card.focus_force()

    def next(self):
        if self.i >= len(self.steps) - 1:
            self.close()
            return
        self.i += 1
        self.show()

    def prev(self):
        if self.i > 0:
            self.i -= 1
            self.show()

    def close(self):
        mark_seen()
        self.alive = False                 # (unbind는 다른 <Configure> 묶음까지 지우므로 쓰지 않는다)
        if self._job:
            self.root.after_cancel(self._job)
            self._job = None
        for w in (self.shade, self.card):
            try:
                w.destroy()
            except tk.TclError:
                pass
        if self.on_close:
            self.on_close()
