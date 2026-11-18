import datetime as dt

import kr_holidays as kh


def test_holidays_2026():
    h = kh.holidays(2026)
    for m, d in ((2, 16), (2, 17), (2, 18), (3, 2), (5, 25), (6, 3), (8, 17), (9, 24), (10, 5), (10, 9)):
        assert dt.date(2026, m, d) in h
    assert dt.date(2026, 11, 18) not in h


def test_substitute_once_for_overlap():
    h = kh.holidays(2025)            # 어린이날 = 부처님오신날 → 대체 5/6 하루
    assert dt.date(2025, 5, 6) in h and dt.date(2025, 5, 7) not in h
    assert dt.date(2025, 10, 8) in h  # 추석 연휴 일요일 → 대체


def test_deadline_ten_workdays():
    import gui
    assert gui.default_date("제출기한", dt.date(2026, 11, 18)) == dt.date(2026, 12, 2)
    assert gui.default_date("제출기한", dt.date(2026, 9, 18)) == dt.date(2026, 10, 7)   # 추석·개천절 대체·한글날 건너뜀
    assert gui.default_date("시행일", dt.date(2026, 9, 18)) == dt.date(2026, 9, 18)
