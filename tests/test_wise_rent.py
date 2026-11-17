import datetime as dt
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import wise_glyph  # noqa: E402
import wise_glyphs  # noqa: E402
import wise_rent  # noqa: E402
from wise_rent import Row  # noqa: E402

SHAPES = {v: k for k, v in wise_glyphs.GLYPHS.items()}


def _draw(text: str, gap_before_comma: int = 0) -> Image.Image:
    """글자 모양 표로 WISE 칸 그림을 흉내 낸다(쉼표는 앞 숫자에 붙인다)."""
    img = Image.new("RGB", (8 * len(text) + 20, 22), (250, 252, 255))
    px = img.load()
    x = 6
    for ch in text:
        size, rest = SHAPES[ch].split("@")
        w, h = map(int, size.split("x"))
        dy, bits = rest.split(":")
        if ch == ",":
            x -= 1 - gap_before_comma
        for i, b in enumerate(bits):
            if b == "1":
                px[x + i % w, 6 + int(dy) + i // w] = (51, 51, 51)
        x += w + 1
    return img


def test_glyph_table_has_all_digits():
    assert set(wise_glyphs.GLYPHS.values()) >= set("0123456789.,-")


def test_read_numbers_back():
    for text in ("100.1438", "99.8590", "96", "2026-08-01", "48,525,000", "171,240", "111,430"):
        assert wise_glyph.read(_draw(text), wise_glyphs.GLYPHS) == text


def test_read_unknown_shape_is_none():
    img = _draw("12")
    img.putpixel((2, 2), (0, 0, 0))
    img.putpixel((3, 2), (0, 0, 0))
    img.putpixel((2, 3), (0, 0, 0))
    assert wise_glyph.read(img, wise_glyphs.GLYPHS) is None


def test_empty_cell():
    assert wise_glyph.read(Image.new("RGB", (40, 20), "white"), wise_glyphs.GLYPHS) == ""


def _rows():
    return [Row(1, "100.1438", 82, "59.7600", "2026-08-01", "48,525,000", "264,020"),
            Row(2, "61.4502", 96, "36.6700", "2026-08-01", "19,980,000", "117,000"),
            Row(3, "100.1438", 82, "59.7600", "2024-08-01", "46,215,000", "251,450"),
            Row(4, "61.4502", 96, "36.6700", "2024-08-01", "19,029,000", "111,430"),
            Row(5, "61.4502", 96, "36.6700", "2028-08-01", "20,000,000", "120,000")]


def test_latest_rows_skips_future_period():
    pick = wise_rent.latest_rows(_rows(), dt.date(2026, 11, 17))
    assert [r.no for r in pick] == [1, 2]


def test_latest_rows_only_future():
    rows = [r for r in _rows() if r.start == "2028-08-01"]
    assert wise_rent.latest_rows(rows, dt.date(2026, 11, 17)) == rows


def test_to_types_uses_exclusive_area():
    pick = wise_rent.latest_rows(_rows(), dt.date(2026, 11, 17))
    assert wise_rent.to_types(pick) == [("36.67", 96, "19,980,000", "117,000", "61.45"),
                                        ("59.76", 82, "48,525,000", "264,020", "100.14")]


def test_clean_drops_border_marks():
    assert wise_rent.clean("I 광주전남지역본부") == "광주전남지역본부"
    assert wise_rent.clean("| 광주양림2") == "광주양림2"
    assert wise_rent.clean("국민임대") == "국민임대"
