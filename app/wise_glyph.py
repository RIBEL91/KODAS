"""WISE 표의 숫자를 글자 모양으로 읽는다.

WISE(XPlatform) 표는 번짐 없는 작은 비트맵 글씨라 Windows OCR이 9를 3으로 자주 잘못 읽는다.
대신 칸 그림을 글자 하나씩 잘라 미리 떠 둔 모양(wise_glyphs.GLYPHS)과 똑같은지 맞춰 본다.
쉼표는 앞 숫자에 붙어 있어(빈 세로줄 없음) 한 덩어리를 여러 글자로 나눠 가며 맞춘다.
"""
from PIL import Image

INK = 185          # 세 색 중 가장 작은 값이 이보다 작으면 글씨(표 선·바탕은 이보다 밝다)
DIGIT_W = 5        # 숫자 한 자의 폭(픽셀)


class _Cell:
    def __init__(self, img: Image.Image):
        img = img.convert("RGB")
        self.w, self.h = img.size
        px = img.load()
        self.m = [[min(px[x, y]) < INK for x in range(self.w)] for y in range(self.h)]
        self.cols = [any(self.m[y][x] for y in range(self.h)) for x in range(self.w)]
        ys = [y for y in range(self.h) if any(self.m[y])]
        self.top = ys[0] if ys else 0

    def runs(self) -> list[tuple[int, int]]:
        out, x = [], 0
        while x < self.w:
            if self.cols[x]:
                s = x
                while x < self.w and self.cols[x]:
                    x += 1
                out.append((s, x))
            else:
                x += 1
        return out

    def key(self, s: int, e: int) -> str:
        """세로줄 s..e-1 조각의 모양 열쇠(위아래 빈 줄은 떼고, 글자 줄 맨 위에서 떨어진 정도를 붙인다)."""
        while s < e and not self.cols[s]:
            s += 1
        while e > s and not self.cols[e - 1]:
            e -= 1
        ys = [y for y in range(self.h) if any(self.m[y][x] for x in range(s, e))]
        if not ys:
            return ""
        y0, y1 = ys[0], ys[-1] + 1
        bits = "".join("1" if self.m[y][x] else "0" for y in range(y0, y1) for x in range(s, e))
        return f"{e - s}x{y1 - y0}@{y0 - self.top}:{bits}"


def _split(cell: _Cell, s: int, e: int, table: dict, memo: dict) -> list[str] | None:
    """덩어리 s..e를 아는 모양들로 나눈 글자들. 못 나누면 None."""
    if (s, e) in memo:
        return memo[(s, e)]
    whole = table.get(cell.key(s, e))
    res = [whole] if whole is not None else None
    if res is None:
        for cut in range(s + 1, e):
            left = table.get(cell.key(s, cut))
            if left is None:
                continue
            rest = _split(cell, cut, e, table, memo)
            if rest is not None:
                res = [left] + rest
                break
    memo[(s, e)] = res
    return res


def read(img: Image.Image, table: dict) -> str | None:
    """칸 그림의 글자. 모르는 모양이 있으면 None, 빈 칸이면 ""."""
    cell = _Cell(img)
    out = []
    for s, e in cell.runs():
        part = _split(cell, s, e, table, {})
        if part is None:
            return None
        out += part
    return "".join(out)


def learn(img: Image.Image, text: str, table: dict) -> bool:
    """값을 아는 칸 그림에서 글자 모양을 떠서 table에 넣는다.
    숫자 폭(5)보다 넓은 덩어리는 '숫자 + 쉼표'로 보고 나눈다. 글자 수가 맞을 때만 넣는다."""
    cell = _Cell(img)
    pieces = []
    for s, e in cell.runs():
        while e - s > DIGIT_W:
            pieces.append((s, s + DIGIT_W))
            s += DIGIT_W
        pieces.append((s, e))
    chars = [c for c in text if not c.isspace()]
    if len(pieces) != len(chars):
        return False
    for (s, e), c in zip(pieces, chars):
        k = cell.key(s, e)
        if k:
            table[k] = c
    return True
