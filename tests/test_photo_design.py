"""내 사진 디자인: 사진에서 색 묶음을 뽑고, 저장된 색으로 디자인을 입힌다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import ui_kit  # noqa: E402


def _photo(tmp_path, color):
    from PIL import Image
    p = tmp_path / "photo.png"
    im = Image.new("RGB", (200, 120), color)
    im.paste((250, 250, 250), (0, 0, 60, 120))        # 흰 부분이 섞여도 선명한 색을 고른다
    im.save(p)
    return str(p)


def test_palette_follows_photo_color(tmp_path):
    import colorsys
    pal = ui_kit.palette_from_photo(_photo(tmp_path, (30, 160, 70)))      # 초록 사진
    assert set(pal) == set(ui_kit.DESIGNS[ui_kit.DEFAULT_DESIGN])
    r, g, b = ui_kit.rgb(pal["primary"])[:3]
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    assert 0.25 < h < 0.45 and s >= 0.5 and v <= 0.7                       # 초록, 흰 글자가 읽히는 밝기


def test_gray_photo_gives_gray_palette(tmp_path):
    pal = ui_kit.palette_from_photo(_photo(tmp_path, (120, 120, 120)))
    r, g, b = ui_kit.rgb(pal["primary"])[:3]
    assert max(r, g, b) - min(r, g, b) < 40


def test_apply_photo_design_and_fallback(tmp_path):
    photo = _photo(tmp_path, (200, 90, 30))
    pal = ui_kit.palette_from_photo(photo)
    try:
        ui_kit.apply_design(ui_kit.PHOTO_DESIGN, "", pal, photo)
        assert ui_kit.DESIGN == ui_kit.PHOTO_DESIGN
        assert ui_kit.PRIMARY == pal["primary"] and ui_kit.HERO_PHOTO == photo
        ui_kit.apply_design(ui_kit.PHOTO_DESIGN, "", None, photo)          # 색이 없으면 기본 디자인
        assert ui_kit.DESIGN == ui_kit.DEFAULT_DESIGN and ui_kit.HERO_PHOTO == ""
    finally:
        ui_kit.apply_design(ui_kit.DEFAULT_DESIGN)
