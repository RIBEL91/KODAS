"""새 디자인 공통 부품: 색·글꼴, PIL로 그리는 둥근 카드·그림자·그라데이션·아이콘, 클릭 영역 캔버스.

화면 바탕(카드·그림자·그림)은 PIL로 한 장의 그림으로 그려 캔버스에 깔고,
글자는 캔버스 글자로 위에 올린다(글자가 또렷하게 보이도록).
"""
import csv
import glob
import os
import tkinter as tk
from functools import lru_cache

FONT = "맑은 고딕"

# ---------------- 색 ----------------
PAGE = "#f4f7fd"          # 화면 바탕(아주 옅은 파랑)
SIDEBAR = "#fafbff"
CARD = "#ffffff"
BORDER = "#e5eaf4"
LINE = "#e8ecf4"
PRIMARY = "#3d6df2"
PRIMARY_D = "#2b57d4"
PRIMARY_SOFT = "#dfe8fd"
HOVER_SOFT = "#eef2fc"
TEXT = "#1c2433"
SUB = "#687489"
MUTED = "#a3adbd"
DANGER = "#d14343"
HERO = ("#5c93fb", "#6a5df0")        # 큰 배너 그라데이션(파랑 → 보라)
TINTS = {                             # (옅은 바탕, 진한 색)
    "blue": ("#e7eefe", "#3d6df2"),
    "violet": ("#efeafe", "#7c5cf0"),
    "teal": ("#e0f5f1", "#139f8a"),
    "pink": ("#f5e8fd", "#a04ee8"),
    "amber": ("#fff2da", "#e89a00"),
    "green": ("#e3f5e8", "#1f9d55"),
    "red": ("#fde8e8", "#e04848"),
}

# ---------------- 디자인(환경 설정에서 고름) ----------------
# 프로그램이 시작할 때 저장된 디자인을 이 모듈의 색·글꼴에 입힌다(다른 화면은 여기 값을 가져다 쓴다).
# 바꾼 디자인은 다시 시작하면 적용된다.
DESIGNS = {
    "기본 파랑": dict(font="맑은 고딕", page="#f4f7fd", sidebar="#fafbff", border="#e5eaf4", line="#e8ecf4",
                  primary="#3d6df2", primary_d="#2b57d4", soft="#dfe8fd", hover="#eef2fc",
                  text="#1c2433", sub="#687489", hero=("#5c93fb", "#6a5df0")),
    "초록 숲": dict(font="나눔고딕", page="#f2f8f4", sidebar="#f9fcfa", border="#dcebe1", line="#e1ede5",
                 primary="#1e9466", primary_d="#14724e", soft="#d5f0e3", hover="#e9f6ef",
                 text="#1a2a21", sub="#5d7267", hero=("#3cc48f", "#178a87")),
    "따뜻한 주황": dict(font="한컴 고딕", page="#fbf6f1", sidebar="#fffbf7", border="#efe1d3", line="#f1e5d9",
                   primary="#dd6b1c", primary_d="#b25414", soft="#fbe3cf", hover="#fcefe4",
                   text="#2d2219", sub="#7a6a5c", hero=("#f7a04f", "#e0573a")),
    "보라 라벤더": dict(font="함초롬돋움", page="#f6f4fd", sidebar="#fbfaff", border="#e6e0f6", line="#e9e5f6",
                   primary="#7552dd", primary_d="#5b3cc0", soft="#e7defb", hover="#f1ebfc",
                   text="#221d33", sub="#6e6789", hero=("#9b7bf5", "#cf5fb6")),
    "차분한 회색": dict(font="굴림", page="#f2f3f5", sidebar="#fafafa", border="#dfe2e6", line="#e4e6e9",
                   primary="#4b5563", primary_d="#323a46", soft="#e1e4e8", hover="#eceef1",
                   text="#1f2328", sub="#6b7280", hero=("#6b7a8f", "#3a4352")),
}
DEFAULT_DESIGN = "기본 파랑"
PHOTO_DESIGN = "내 사진"          # 사진을 고르면 그 사진에서 색을 뽑고, 첫 화면 배너에 사진을 깐다
FONT_CHOICES = ("맑은 고딕", "나눔고딕", "한컴 고딕", "함초롬돋움", "한컴산뜻돋움", "굴림", "돋움", "바탕")
DESIGN = DEFAULT_DESIGN
HERO_PHOTO = ""                   # 배너에 깔 사진 파일(내 사진 디자인일 때만)


def _hsv_hex(h: float, s: float, v: float) -> str:
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def palette_from_photo(path: str) -> dict:
    """사진에서 대표 색을 뽑아 디자인 색 묶음(DESIGNS 한 칸과 같은 모양)을 만든다.

    사진을 작게 줄여 8색으로 묶고, 많이 쓰였으면서 선명한 색을 강조색으로 고른다.
    글자가 잘 읽히도록 밝기·채도는 알맞은 범위로 맞춘다. 흑백에 가까운 사진이면 회색 계열.
    """
    import colorsys
    from PIL import Image
    with Image.open(path) as im:
        small = im.convert("RGB").resize((96, 96))
    q = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:24]
    counts = sorted(q.getcolors(), reverse=True)           # [(개수, 번호)]
    total = sum(c for c, _ in counts) or 1
    cands = []
    for cnt, idx in counts:
        r, g, b = pal[idx * 3: idx * 3 + 3]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        cands.append((cnt / total, h, s, v))
    score = lambda c: c[0] ** 0.6 * (c[2] + 0.15)          # noqa: E731  많이 쓰이고 선명할수록
    vivid = [c for c in cands if c[2] > 0.22 and c[3] > 0.18]
    if vivid:
        main = max(vivid, key=score)
        others = [c for c in vivid if c is not main and abs(((c[1] - main[1]) + 0.5) % 1 - 0.5) > 0.04]
        second = max(others, key=score) if others else None
        h, s = main[1], max(0.55, min(0.85, main[2]))
        h2 = second[1] if second else h + 0.08
        s2 = max(0.40, min(0.85, second[2])) if second else s
        gray = False
    else:                                                  # 흑백·무채색 사진
        h, s, h2, s2, gray = 0.6, 0.12, 0.6, 0.15, True
    return dict(
        font="맑은 고딕",
        page=_hsv_hex(h, 0.02 if gray else 0.04, 0.975),
        sidebar=_hsv_hex(h, 0.02, 0.99),
        border=_hsv_hex(h, 0.05 if gray else 0.10, 0.91),
        line=_hsv_hex(h, 0.04 if gray else 0.08, 0.93),
        primary=_hsv_hex(h, s, 0.42 if gray else 0.62),
        primary_d=_hsv_hex(h, min(1, s + 0.05), 0.30 if gray else 0.48),
        soft=_hsv_hex(h, 0.15, 0.97),
        hover=_hsv_hex(h, 0.07, 0.98),
        text=_hsv_hex(h, 0.1 if gray else 0.25, 0.18),
        sub=_hsv_hex(h, 0.08 if gray else 0.15, 0.48),
        hero=(_hsv_hex(h, s * 0.9, 0.55 if gray else 0.80), _hsv_hex(h2, s2, 0.35 if gray else 0.62)),
    )


def apply_design(name: str = DEFAULT_DESIGN, font: str = "", colors: dict | None = None,
                 photo: str = "") -> None:
    """디자인(색 묶음)과 글씨체를 이 모듈의 값에 입힌다. font를 비우면 그 디자인의 글씨체.

    '내 사진' 디자인은 사진에서 뽑아 저장해 둔 colors와 배너에 깔 사진 파일 photo를 쓴다.
    """
    global DESIGN, FONT, PAGE, SIDEBAR, BORDER, LINE, PRIMARY, PRIMARY_D, PRIMARY_SOFT, HOVER_SOFT
    global TEXT, SUB, HERO, HERO_PHOTO
    HERO_PHOTO = ""
    d = None
    if name == PHOTO_DESIGN and isinstance(colors, dict) and all(k in colors for k in DESIGNS[DEFAULT_DESIGN]):
        d = colors
        HERO_PHOTO = photo if photo and os.path.isfile(photo) else ""
    if d is None:
        d = DESIGNS.get(name) or DESIGNS[DEFAULT_DESIGN]
        name = name if name in DESIGNS else DEFAULT_DESIGN
    DESIGN = name
    FONT = font or d["font"]
    PAGE, SIDEBAR, BORDER, LINE = d["page"], d["sidebar"], d["border"], d["line"]
    PRIMARY, PRIMARY_D, PRIMARY_SOFT, HOVER_SOFT = d["primary"], d["primary_d"], d["soft"], d["hover"]
    TEXT, SUB, HERO = d["text"], d["sub"], tuple(d["hero"])
    TINTS["blue"] = (PRIMARY_SOFT, PRIMARY)      # 강조 아이콘도 디자인 색으로


@lru_cache(maxsize=2)
def _photo(path: str):
    """배너 사진을 한 번만 읽어 둔다(창 크기가 바뀔 때마다 다시 읽지 않게)."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((2400, 2400))
            return im
    except Exception:
        return None


def saved_design() -> dict:
    """설정 파일에 저장된 디자인 {'name': …, 'font': …}. 없으면 빈 dict."""
    try:
        import settings_store
        d = settings_store.load_raw().get("design") or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


_saved = saved_design()
apply_design(_saved.get("name", DEFAULT_DESIGN), _saved.get("font", ""), _saved.get("colors"),
             _saved.get("photo", ""))

# ---------------- 아이콘(윈도 기본 글꼴 Segoe MDL2 Assets) ----------------
ICON = {
    "home": "\ue80f", "edit": "\ue70f", "layers": "\ue81e", "history": "\ue81c", "settings": "\ue713",
    "page": "\ue7c3", "key": "\ue8d7", "wrench": "\ue90f", "heart": "\ueb51", "calc": "\ue8ef",
    "building": "\ue731", "person": "\ue77b", "people": "\ue716", "help": "\ue897", "search": "\ue721",
    "add": "\ue710", "chevron": "\ue76c", "more": "\ue712", "star": "\ue735", "folder": "\uf12b",
    "report": "\ue9f9", "list": "\ue8bc", "info": "\ue946", "back": "\ue72b",
    "download": "\ue896",
}

FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def fs(pt: float, k: float, least: float = 0) -> int:
    """배율 k에 맞춘 글자 크기(픽셀, 음수). 점으로 주면 윈도 배율이 한 번 더 곱해져 겹친다."""
    return -max(round(least * 96 / 72), round(pt * k * 96 / 72))


def rgb(c: str, a: int = 255) -> tuple:
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) + (a,)


def mix(c1: str, c2: str, t: float) -> str:
    a, b = rgb(c1), rgb(c2)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a[:3], b[:3]))


@lru_cache(maxsize=64)
def _font(name: str, size: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, name), max(1, size))
    except OSError:
        return None


class Painter:
    """w×h 그림을 ss배 크기로 그린 뒤 줄여서(부드러운 가장자리) 돌려준다.
    그림자는 따로 흐리게 그려 모양 아래에 깐다."""

    def __init__(self, w: int, h: int, bg: str, ss: int = 2):
        from PIL import Image, ImageDraw
        self.Image = Image
        self.w, self.h, self.ss = max(1, int(w)), max(1, int(h)), ss
        self.bg = bg
        self.im = Image.new("RGBA", (self.w * ss, self.h * ss), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)
        self.sh_scale = 0.5                       # 그림자는 반 크기로 그려 흐린다(빠르게)
        self.sh = Image.new("RGBA", (max(1, int(self.w * self.sh_scale)), max(1, int(self.h * self.sh_scale))),
                            (0, 0, 0, 0))
        self.shd = ImageDraw.Draw(self.sh)

    def S(self, v: float) -> int:
        return round(v * self.ss)

    def _box(self, x0, y0, x1, y1):
        return [self.S(x0), self.S(y0), self.S(x1), self.S(y1)]

    # ---- 모양 ----
    def shadow(self, x0, y0, x1, y1, r, alpha=26, dy=6, color="#30509a"):
        s = self.sh_scale
        self.shd.rounded_rectangle([x0 * s, (y0 + dy) * s, x1 * s, (y1 + dy) * s], radius=r * s,
                                   fill=rgb(color, alpha))

    def card(self, x0, y0, x1, y1, r, fill=CARD, outline=BORDER, shadow=True):
        if shadow:
            self.shadow(x0 + 2, y0 + 2, x1 - 2, y1, r)
        self.rrect(x0, y0, x1, y1, r, fill, outline)

    def rrect(self, x0, y0, x1, y1, r, fill, outline=None, width=1, alpha=255):
        self.d.rounded_rectangle(self._box(x0, y0, x1, y1), radius=self.S(r), fill=rgb(fill, alpha),
                                 outline=rgb(outline) if outline else None,
                                 width=self.S(width) if outline else 0)

    def gradient_rrect(self, x0, y0, x1, y1, r, c1, c2):
        """왼쪽 위 c1 → 오른쪽 아래 c2 대각선 그라데이션의 둥근 사각형."""
        Image = self.Image
        from PIL import ImageChops
        bw, bh = max(1, self.S(x1 - x0)), max(1, self.S(y1 - y0))
        gy = Image.linear_gradient("L").resize((bw, bh))                 # 위 0 → 아래 255
        gx = Image.linear_gradient("L").rotate(90).resize((bw, bh))      # 반시계 90° → 왼 0 → 오른 255
        small = ImageChops.add(gx, gy, scale=2.0)                         # (가로 + 세로) / 2 = 대각선
        grad = Image.composite(Image.new("RGBA", (bw, bh), rgb(c2)), Image.new("RGBA", (bw, bh), rgb(c1)), small)
        mask = Image.new("L", (bw, bh), 0)
        from PIL import ImageDraw
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, bw - 1, bh - 1], radius=self.S(r), fill=255)
        self.im.paste(grad, (self.S(x0), self.S(y0)), mask)
        return mask

    def overlay_in(self, x0, y0, mask, draw_fn):
        """mask(둥근 배너 모양) 안쪽에만 보이게 장식을 그린다. draw_fn(ImageDraw, ss)."""
        from PIL import ImageDraw
        layer = self.Image.new("RGBA", mask.size, (0, 0, 0, 0))
        draw_fn(ImageDraw.Draw(layer), self.ss)
        clip = self.Image.new("RGBA", mask.size, (0, 0, 0, 0))
        clip.paste(layer, (0, 0), mask)
        self.im.alpha_composite(clip, (self.S(x0), self.S(y0)))

    def photo_in(self, x0, y0, mask, path, tint):
        """mask(둥근 배너) 안에 사진을 꽉 채워 깔고, 흰 글자가 읽히게 왼쪽을 tint 색으로 어둡게 덮는다."""
        from PIL import ImageOps
        src = _photo(path)
        if src is None:
            return False
        pic = ImageOps.fit(src, mask.size, method=self.Image.LANCZOS).convert("RGBA")
        bw, bh = mask.size
        fade = self.Image.linear_gradient("L").rotate(90).resize((bw, bh))      # 왼 0 → 오른 255
        fade = fade.point(lambda p: int(215 - p * 0.55))                          # 왼쪽 진하게, 오른쪽 옅게
        cover = self.Image.new("RGBA", (bw, bh), rgb(tint))
        cover.putalpha(fade)
        pic.alpha_composite(cover)
        self.im.paste(pic, (self.S(x0), self.S(y0)), mask)
        return True

    def circle(self, cx, cy, rad, fill, alpha=255):
        self.d.ellipse(self._box(cx - rad, cy - rad, cx + rad, cy + rad), fill=rgb(fill, alpha))

    def line(self, pts, fill, width=1, alpha=255):
        self.d.line([(self.S(x), self.S(y)) for x, y in pts], fill=rgb(fill, alpha), width=self.S(width),
                    joint="curve")

    def polygon(self, pts, fill, alpha=255):
        self.d.polygon([(self.S(x), self.S(y)) for x, y in pts], fill=rgb(fill, alpha))

    def sparkle(self, cx, cy, r, fill="#ffffff", alpha=255):
        """네 갈래 반짝이."""
        t = r * 0.22
        pts = [(cx, cy - r), (cx + t, cy - t), (cx + r, cy), (cx + t, cy + t),
               (cx, cy + r), (cx - t, cy + t), (cx - r, cy), (cx - t, cy - t)]
        self.polygon(pts, fill, alpha)

    def icon(self, name, cx, cy, size, color):
        f = _font("segmdl2.ttf", self.S(size))
        if f is None:
            return
        self.d.text((self.S(cx), self.S(cy)), ICON.get(name, name), font=f, fill=rgb(color), anchor="mm")

    def text(self, x, y, s, size, color, bold=False, anchor="la"):
        f = _font("malgunbd.ttf" if bold else "malgun.ttf", self.S(size))
        if f is not None:
            self.d.text((self.S(x), self.S(y)), s, font=f, fill=rgb(color), anchor=anchor)

    def emoji(self, ch, x, y, size, anchor="lm"):
        f = _font("seguiemj.ttf", self.S(size))
        if f is None:
            return
        try:
            self.d.text((self.S(x), self.S(y)), ch, font=f, embedded_color=True, anchor=anchor)
        except Exception:
            pass

    def tint_icon(self, name, cx, cy, rad, tint, square=False, size=None):
        """옅은 색 원(또는 둥근 네모) 위에 진한 색 아이콘."""
        soft, strong = TINTS[tint]
        if square:
            self.rrect(cx - rad, cy - rad, cx + rad, cy + rad, rad * 0.42, soft)
        else:
            self.circle(cx, cy, rad, soft)
        self.icon(name, cx, cy, size or rad * 0.95, strong)

    def paper(self, cx, cy, w, h, angle, title="공문"):
        """배너 오른쪽의 공문 종이 그림(살짝 기울임)."""
        from PIL import ImageDraw, ImageFilter
        S = self.S
        pw, ph = S(w), S(h)
        pad = S(24)
        sheet = self.Image.new("RGBA", (pw + pad * 2, ph + pad * 2), (0, 0, 0, 0))
        dd = ImageDraw.Draw(sheet)
        dd.rounded_rectangle([pad, pad, pad + pw, pad + ph], radius=S(10), fill=(255, 255, 255, 245))
        f = _font("malgunbd.ttf", S(h * 0.085))
        if f is not None:
            dd.text((pad + pw / 2, pad + ph * 0.15), title, font=f, fill=rgb("#5b6fae"), anchor="mm")
        for i, frac in enumerate((0.78, 0.62, 0.70, 0.5, 0.66, 0.42)):
            yy = pad + ph * (0.3 + i * 0.105)
            dd.rounded_rectangle([pad + pw * 0.14, yy, pad + pw * (0.14 + frac * 0.72), yy + S(h * 0.028)],
                                 radius=S(3), fill=rgb("#c9d6f7"))
        sheet = sheet.rotate(angle, resample=self.Image.BICUBIC, expand=True)
        sh = sheet.split()[3].point(lambda a: a * 0.35).filter(ImageFilter.GaussianBlur(S(9)))
        shadow = self.Image.new("RGBA", sheet.size, rgb("#2a3d9a", 0))
        shadow.putalpha(sh)
        x, y = S(cx) - sheet.width // 2, S(cy) - sheet.height // 2
        self.im.alpha_composite(shadow, (max(0, x + S(6)), max(0, y + S(10))))
        self.im.alpha_composite(sheet, (max(0, x), max(0, y)))

    def wave(self, x0, y1, x1, h, color, alpha=60):
        """통계 카드 오른쪽 아래의 작은 오름세 선과 옅은 면."""
        n = 7
        ys = (0.55, 0.75, 0.5, 0.62, 0.3, 0.42, 0.05)
        pts = [(x0 + (x1 - x0) * i / (n - 1), y1 - h * (1 - ys[i])) for i in range(n)]
        self.polygon(pts + [(x1, y1), (x0, y1)], color, alpha // 2)
        self.line(pts, color, 1.6, min(255, alpha * 3))

    # ---- 마무리 ----
    def finish(self):
        """바탕 + 흐린 그림자 + 모양을 합쳐 1배 크기 PhotoImage로."""
        from PIL import ImageFilter, ImageTk
        Image = self.Image
        base = Image.new("RGBA", self.im.size, rgb(self.bg))
        sh = self.sh.filter(ImageFilter.GaussianBlur(7)).resize(self.im.size, Image.BILINEAR)
        base.alpha_composite(sh)
        base.alpha_composite(self.im)
        out = base.resize((self.w, self.h), Image.LANCZOS)
        return ImageTk.PhotoImage(out)


class HitCanvas(tk.Canvas):
    """그림 위의 '누를 수 있는 영역'을 직접 관리하는 캔버스(그림 바탕 위에서는 빈 사각형이 클릭을 받지 않는다)."""

    def __init__(self, parent, **kw):
        super().__init__(parent, highlightthickness=0, bd=0, **kw)
        self._hits: list = []            # (x0, y0, x1, y1, 누를 때, 올렸을 때(bool))
        self._hover = None
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _e: self._set_hover(None))
        self.bind("<Button-1>", self._click)

    def clear_hits(self):
        self._set_hover(None)
        self._hits = []

    def add_hit(self, box, command, on_hover=None):
        self._hits.append((*box, command, on_hover))

    def _find(self, x, y):
        for h in reversed(self._hits):
            if h[0] <= x <= h[2] and h[1] <= y <= h[3]:
                return h
        return None

    def _set_hover(self, h):
        if h is self._hover:
            return
        if self._hover is not None and self._hover[5]:
            try:
                self._hover[5](False)
            except tk.TclError:
                pass
        self._hover = h
        if h is not None and h[5]:
            h[5](True)
        self.config(cursor="hand2" if h is not None else "")

    def _motion(self, e):
        self._set_hover(self._find(self.canvasx(e.x), self.canvasy(e.y)))

    def _click(self, e):
        h = self._find(self.canvasx(e.x), self.canvasy(e.y))
        if h is not None and h[4]:
            h[4]()


def keep_colors(widget, **opts):
    """sv_ttk 테마는 스타일이 바뀔 때마다(<<ThemeChanged>>) tk_setPalette로 tk 입력칸 색을 회색으로 되돌린다.
    그때마다 우리 색을 다시 입힌다."""
    widget.configure(**opts)

    def again(_e=None):
        try:
            widget.after_idle(lambda: widget.winfo_exists() and widget.configure(**opts))
        except tk.TclError:
            pass
    widget.bind("<<ThemeChanged>>", again, add="+")
    return widget


def round_rect(cv: tk.Canvas, x0, y0, x1, y1, r, **kw):
    """캔버스 둥근 사각형(부드러운 다각형)."""
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, splinesteps=24, **kw)


def ellipsize(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "…"


def read_history(logs_dir: str) -> list[dict]:
    """logs\\작성이력_년월.csv 전부를 최근 것부터."""
    rows = []
    for path in glob.glob(os.path.join(logs_dir, "작성이력_*.csv")):
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                rows += [r for r in csv.DictReader(f) if r.get("시각")]
        except (OSError, csv.Error, UnicodeDecodeError):
            continue
    rows.sort(key=lambda r: r.get("시각", ""), reverse=True)
    return rows


def is_done(row: dict) -> bool:
    return not (row.get("상태") or "").startswith("실패")
