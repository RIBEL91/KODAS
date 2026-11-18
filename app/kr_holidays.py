"""우리나라 공휴일 — 제출기한 같은 날짜를 근무일로 셀 때 쓴다(인터넷 없이).

- 해마다 같은 날: 신정, 삼일절, 어린이날, 현충일, 광복절, 개천절, 한글날, 성탄절
- 음력 공휴일(설날·추석 앞뒤 하루씩, 부처님오신날): 아래 표(2025~2030)
- 대체공휴일: 설날·추석은 일요일이나 다른 공휴일과 겹치면, 삼일절·어린이날·광복절·개천절·한글날·
  부처님오신날·성탄절은 토·일요일이나 다른 공휴일과 겹치면 다음 근무일
- 선거일·임시공휴일: EXTRA
표에 없는 해는 해마다 같은 날만 센다. 새 해가 오면 LUNAR에 그 해를 더한다.
"""
import datetime as dt
from functools import lru_cache

D = dt.date
# 연도 → (설날, 부처님오신날, 추석) — 양력 날짜
LUNAR = {
    2025: (D(2025, 1, 29), D(2025, 5, 5), D(2025, 10, 6)),
    2026: (D(2026, 2, 17), D(2026, 5, 24), D(2026, 9, 25)),
    2027: (D(2027, 2, 7), D(2027, 5, 13), D(2027, 9, 15)),
    2028: (D(2028, 1, 27), D(2028, 5, 2), D(2028, 10, 3)),
    2029: (D(2029, 2, 13), D(2029, 5, 20), D(2029, 9, 22)),
    2030: (D(2030, 2, 3), D(2030, 5, 9), D(2030, 9, 12)),
}
# 선거일·임시공휴일
EXTRA = {D(2025, 1, 27), D(2025, 6, 3), D(2026, 6, 3), D(2028, 4, 12)}
FIXED = ((1, 1), (3, 1), (5, 5), (6, 6), (8, 15), (10, 3), (10, 9), (12, 25))
SUBSTITUTE_FIXED = ((3, 1), (5, 5), (8, 15), (10, 3), (10, 9), (12, 25))   # 현충일·신정은 대체 없음


@lru_cache(maxsize=None)
def holidays(year: int) -> frozenset:
    days = {D(year, m, d) for m, d in FIXED} | {x for x in EXTRA if x.year == year}
    lunar = LUNAR.get(year)
    subs = []
    if lunar:
        seol, buddha, chuseok = lunar
        for center in (seol, chuseok):
            three = [center + dt.timedelta(days=k) for k in (-1, 0, 1)]
            # 일요일이거나 다른 공휴일과 겹친 날 수만큼 대체
            subs.append((three, sum(1 for x in three if x.weekday() == 6 or x in days)))
            days |= set(three)
        clash = buddha in days
        days.add(buddha)
        subs.append(([buddha], 1 if clash or buddha.weekday() >= 5 else 0))
    for m, d in SUBSTITUTE_FIXED:
        x = D(year, m, d)
        if x.weekday() >= 5:        # 음력 공휴일과 겹친 것은 위 음력 쪽에서 한 번만 센다
            subs.append(([x], 1))
    for span, n in subs:
        nxt = max(span)
        while n > 0:
            nxt += dt.timedelta(days=1)
            if nxt.weekday() < 5 and nxt not in days:
                days.add(nxt)
                n -= 1
    return frozenset(days)


def is_workday(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def add_workdays(start: dt.date, n: int) -> dt.date:
    """start 다음 날부터 근무일(토·일·공휴일 빼고)을 n일 센 날."""
    d = start
    while n > 0:
        d += dt.timedelta(days=1)
        if is_workday(d):
            n -= 1
    return d
