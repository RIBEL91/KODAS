r"""시작 화면 그림(assets/splash.png)을 만든다 — 은색 테두리 흰 카드 + 광택 + 가운데 로고·안내 + 진행 칸.

가운데 KODAS(가장 크게), 위에 공단 상징+'주택관리공단 광주전남지사', 오른쪽 안내 — 글자는 모두 Noto Sans KR. 진행 칸은 회색 틀만 그리고, 색 채우기(파랑→초록)는
KODAS.spec의 SPLASH_BLOCKS_TCL이 움직이며 칠한다(칸 자리 BLOCKS와 맞출 것).
PyInstaller 시작 화면(Windows)은 자홍색만 투명하게 바꾸므로 모서리는 보이기/숨기기로 깎는다.

    .venv\Scripts\python.exe tools\make_splash.py
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(HERE, "..", "assets", "splash.png")
LOGO = os.path.join(HERE, "kohom_logo.png")      # 주택관리공단 로고(185×47)
EMBLEM = (5, 0, 50, 47)                           # 로고 속 둥근 상징 자리(글자 부분은 쓰지 않는다)
FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
W, H, R, RIM = 540, 156, 12, 5
BLOCKS = dict(n=15, x=56, y=118, w=25, h=10, gap=4)      # 진행 칸(Tcl과 같게)
SS = 3


def font(weight, size):
    """로고 글씨와 비슷한 굵은 고딕(Noto Sans KR, 굵기 Bold·Medium). 없으면 맑은 고딕."""
    try:
        f = ImageFont.truetype(os.path.join(FONTS, "NotoSansKR-VF.ttf"), size * SS)
        f.set_variation_by_name(weight)
        return f
    except (OSError, ValueError):
        return ImageFont.truetype(os.path.join(FONTS, "malgunbd.ttf"), size * SS)


def main():
    w, h = W * SS, H * SS
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 은색 두꺼운 테두리(위는 밝게, 아래는 어둡게) + 흰 안쪽
    rim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    for y in range(h):
        t = y / h
        c = int(214 - 34 * t)
        rd.line([(0, y), (w, y)], fill=(c, c, c + 2, 255))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], R * SS, fill=255)
    img.paste(rim, (0, 0), mask)
    inner = [RIM * SS, RIM * SS, w - RIM * SS - 1, h - RIM * SS - 1]
    d.rounded_rectangle(inner, (R - 3) * SS, fill=(255, 255, 255, 255))

    # 안쪽 장식: 로고 뒤 옅은 회색 빛 + 대각선 광택 띠
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([int(w * 0.10), int(h * 0.05), int(w * 0.90), int(h * 0.80)], fill=(150, 152, 160, 55))
    glow = glow.filter(ImageFilter.GaussianBlur(26 * SS))
    for x0, ww, a in ((0.30, 0.10, 45), (0.44, 0.04, 60), (0.70, 0.07, 40)):
        gd2 = ImageDraw.Draw(glow)
        X = int(w * x0)
        gd2.polygon([(X, RIM * SS), (X + int(w * ww), RIM * SS), (X + int(w * ww) - int(h * 0.9), h - RIM * SS),
                     (X - int(h * 0.9), h - RIM * SS)], fill=(255, 255, 255, a))
    imask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(imask).rounded_rectangle(inner, (R - 3) * SS, fill=255)
    img.paste(Image.alpha_composite(img, glow), (0, 0), imask)
    # 테두리 광택(위쪽 가는 흰 줄)
    d.rounded_rectangle([SS, SS, w - SS - 1, h - SS - 1], R * SS, outline=(245, 245, 248, 255), width=SS)

    # 글자는 모두 같은 글씨체(Noto Sans KR). 로고 그림에서는 둥근 상징(엠블럼)만 떼어 쓰고
    # '주택관리공단 광주전남지사'는 글자로 쓴다(로고 그림 속 글씨체와 섞이지 않게).
    logo = Image.open(LOGO).convert("RGBA").crop(EMBLEM)
    lp = logo.load()
    for y in range(logo.height):                 # 흰 바탕 걷어 내기(흰색에서 풀어 내기)
        for x in range(logo.width):
            r, g, bb, _ = lp[x, y]
            a = max(255 - r, 255 - g, 255 - bb)
            if a == 0:
                lp[x, y] = (0, 0, 0, 0)
                continue
            lp[x, y] = (*[255 - (255 - c) * 255 // a for c in (r, g, bb)], a)
    eh = 22 * SS                                  # 상징 높이
    logo = logo.resize((int(logo.width * eh / logo.height), eh), Image.LANCZOS)

    d = ImageDraw.Draw(img)
    f_org = font("Bold", 13)
    f_kodas = font("Black", 44)
    f_sub = font("Medium", 12)
    f_t1, f_t2 = font("Bold", 17), font("Medium", 13)
    org = "주택관리공단 광주전남지사"
    kodas_w = d.textlength("KODAS", font=f_kodas)
    left_w = max(logo.width + 8 * SS + d.textlength(org, font=f_org),
                 kodas_w + 10 * SS + d.textlength("공문 자동작성 시스템", font=f_sub))
    right_w = max(d.textlength("처리중입니다.", font=f_t1), d.textlength("잠시만 기다려주세요.", font=f_t2))
    gap = 22 * SS
    x0 = int((w - (left_w + gap * 2 + right_w)) / 2)          # 왼쪽 묶음 + 세로줄 + 오른쪽 안내를 가운데로

    # 윗줄: 상징 + 주택관리공단 광주전남지사
    oy = 18 * SS
    img.alpha_composite(logo, (x0, oy))
    d = ImageDraw.Draw(img)
    d.text((x0 + logo.width + 8 * SS, oy + eh // 2), org, font=f_org, fill=(64, 68, 76, 255), anchor="lm")
    # 가운데: KODAS(가장 크게, 파란 그라데이션) + 공문 자동작성 시스템
    base = 92 * SS
    txt = Image.new("L", (w, h), 0)
    ImageDraw.Draw(txt).text((x0 - 2 * SS, base), "KODAS", font=f_kodas, fill=255, anchor="ls")
    grad = Image.new("RGBA", (w, h))
    gp = ImageDraw.Draw(grad)
    for x in range(w):                           # 파랑 → 남보라
        t = min(1.0, max(0.0, (x - x0) / max(1, kodas_w)))
        gp.line([(x, 0), (x, h)], fill=(int(28 + 64 * t), int(84 - 30 * t), int(196 + 20 * t), 255))
    shadow = Image.new("RGBA", (w, h), (20, 40, 110, 0))
    shadow.putalpha(txt.point(lambda v: v * 40 // 255).filter(ImageFilter.GaussianBlur(3 * SS)))
    img.alpha_composite(shadow, (0, 2 * SS))
    img.paste(grad, (0, 0), txt)
    d = ImageDraw.Draw(img)
    d.text((x0 + kodas_w + 10 * SS, base - 3 * SS), "공문 자동작성 시스템", font=f_sub,
           fill=(96, 100, 110, 255), anchor="ls")

    # 세로줄 + 오른쪽 안내
    vx = int(x0 + left_w + gap)
    d.line([(vx, 24 * SS), (vx, 92 * SS)], fill=(200, 200, 204, 255), width=SS)
    tx = vx + gap
    d.text((tx, 56 * SS), "처리중입니다.", font=f_t1, fill=(52, 54, 60, 255), anchor="ls")
    d.text((tx, 80 * SS), "잠시만 기다려주세요.", font=f_t2, fill=(80, 82, 88, 255), anchor="ls")

    # 진행 칸 틀(회색)
    b = BLOCKS
    for i in range(b["n"]):
        x = (b["x"] + i * (b["w"] + b["gap"])) * SS
        d.rectangle([x, b["y"] * SS, x + b["w"] * SS - 1, (b["y"] + b["h"]) * SS - 1],
                    fill=(214, 214, 216, 255), outline=(180, 180, 184, 255), width=SS)

    # 개발자(작고 연하게, 오른쪽 아래)
    d.text((w - 16 * SS, 143 * SS), "Developers: 최문원 · 오영철 · 이동욱 · 김경훈", font=font("Regular", 8),
           fill=(150, 152, 158, 255), anchor="rm")

    out = img.resize((W, H), Image.LANCZOS)
    px = out.load()
    for y in range(H):                       # 모서리 반투명 → 보이기/숨기기(자홍 테두리가 안 생기게)
        for x in range(W):
            r, g, bb, a = px[x, y]
            px[x, y] = (r, g, bb, 255) if a >= 128 else (0, 0, 0, 0)
    out.save(DST)
    print("저장:", os.path.abspath(DST), out.size)


if __name__ == "__main__":
    main()
