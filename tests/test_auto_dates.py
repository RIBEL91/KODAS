import datetime as dt

import gui


def test_month_end():
    assert gui.month_end(dt.date(2027, 2, 1)) == dt.date(2027, 2, 28)
    assert gui.month_end(dt.date(2028, 2, 10)) == dt.date(2028, 2, 29)
    assert gui.month_end(dt.date(2026, 12, 31)) == dt.date(2026, 12, 31)


def test_auto_date_rule():
    today = dt.date(2026, 10, 25)
    rule = gui.auto_date_rule("만료일", {"갱신월": "월"})
    assert rule({"갱신월": dt.date(2026, 11, 1)}, today) == dt.date(2026, 11, 30)
    assert gui.auto_date_rule("만료일", {}) is None          # 갱신월이 없는 서식은 직접 입력
    assert gui.auto_date_rule("계약체결기한", {"갱신월": "월"})(
        {"갱신월": dt.date(2027, 2, 1)}, today) == dt.date(2027, 2, 28)
    assert gui.auto_date_rule("계약체결기한", {}) is None      # 재임대(04)·어린이집(30)은 직접 입력
    rule = gui.auto_date_rule("대상세대 갱신월", {"검색월": "년월"})
    assert rule({"검색월": dt.date(2026, 10, 1)}, today) == dt.date(2025, 9, 1)
    assert rule({"검색월": dt.date(2027, 1, 1)}, today) == dt.date(2025, 12, 1)
    assert gui.auto_date_rule("대상세대 갱신월", {}) is None
    rule = gui.auto_date_rule("재임대월", {"갱신월": "월"})
    assert rule({"갱신월": dt.date(2026, 11, 1)}, today) == dt.date(2026, 9, 1)
    assert rule({"갱신월": dt.date(2027, 1, 1)}, today) == dt.date(2026, 11, 1)
    assert gui.auto_date_rule("안내문시행일", {})({}, today) == today
    assert gui.auto_date_rule("제출기한", {}) is None
    assert gui.default_date("제출기한", today) == dt.date(2026, 11, 8)


def test_saved_month():
    months = {"16_갱신.txt": "2026-11", "깨짐.txt": "11월", "숫자.txt": 11}
    assert gui.saved_month(months, "16_갱신.txt") == dt.date(2026, 11, 1)
    assert gui.saved_month(months, "없음.txt") is None
    assert gui.saved_month(months, "깨짐.txt") is None
    assert gui.saved_month(months, "숫자.txt") is None
    assert gui.saved_month(None, "16_갱신.txt") is None


def test_month_field():
    assert gui.is_month_field("갱신월", "월")
    assert gui.is_month_field("갱신월", "월만")
    assert not gui.is_month_field("만료일", "일")
