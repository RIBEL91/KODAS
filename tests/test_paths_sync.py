"""exe 하나로 옮겨 쓰기: 번들 기본 서식을 사용자 서식 폴더에 맞추는 규칙."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import paths  # noqa: E402


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _r(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_sync_rules(tmp_path):
    src, dst = str(tmp_path / "bundle"), str(tmp_path / "user")
    _w(os.path.join(src, "01_a.txt"), "a1")
    _w(os.path.join(src, "02_b.txt"), "b1")
    _w(os.path.join(src, "1안", "c.txt"), "c1")
    paths.sync_templates(src, dst)                                  # 처음: 모두 꺼냄
    assert _r(os.path.join(dst, "01_a.txt")) == "a1"
    assert _r(os.path.join(dst, "1안", "c.txt")) == "c1"

    _w(os.path.join(dst, "02_b.txt"), "내가 고침")                   # 사용자가 고친 서식
    os.remove(os.path.join(dst, "1안", "c.txt"))                    # 사용자가 지운 서식
    _w(os.path.join(dst, "99_mine.txt"), "직접 만듦")
    _w(os.path.join(src, "01_a.txt"), "a2")                          # 새 버전: 안 고친 서식 내용 바뀜
    _w(os.path.join(src, "02_b.txt"), "b2")
    _w(os.path.join(src, "1안", "c.txt"), "c2")
    _w(os.path.join(src, "03_new.txt"), "new")                       # 새 버전에 추가된 서식
    paths.sync_templates(src, dst)
    assert _r(os.path.join(dst, "01_a.txt")) == "a2"
    assert _r(os.path.join(dst, "02_b.txt")) == "내가 고침"
    assert not os.path.exists(os.path.join(dst, "1안", "c.txt"))
    assert _r(os.path.join(dst, "03_new.txt")) == "new"
    assert _r(os.path.join(dst, "99_mine.txt")) == "직접 만듦"


def test_existing_edited_folder_is_kept(tmp_path):
    """예전 exe 옆 서식 폴더를 옮겨 온 경우: 다른 내용은 사용자가 고친 것으로 보고 둔다."""
    src, dst = str(tmp_path / "bundle"), str(tmp_path / "user")
    _w(os.path.join(src, "01_a.txt"), "a1")
    _w(os.path.join(dst, "01_a.txt"), "예전에 고친 것")
    paths.sync_templates(src, dst)
    assert _r(os.path.join(dst, "01_a.txt")) == "예전에 고친 것"
    _w(os.path.join(src, "01_a.txt"), "a2")
    paths.sync_templates(src, dst)
    assert _r(os.path.join(dst, "01_a.txt")) == "예전에 고친 것"
