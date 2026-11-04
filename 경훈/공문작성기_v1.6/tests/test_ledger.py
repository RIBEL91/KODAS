import datetime as dt

import ledger


def _row(title, reg, enforce, regno, sender):
    return {"text": ["null", "9", "-1", "", "공개", "접수", reg, regno, title, "오영철",
                     "주거복지실/본사/본사", enforce, "임대관리관계철(1)", "관리소장", "", sender],
            "userdata": f"<userdata><CREATE_REG_DATE>{reg}</CREATE_REG_DATE><TITLE>{title}</TITLE></userdata>"}


ROWS = [
    _row("주택소유 전산검색 결과 통보(41차, ~ 26. 10. 13. 요청건)", "20261021114447", "20261020101240",
         "광주양림2관리소-1977", "주거복지실-2441"),
    _row("주택소유 전산검색 결과 통보(34차, ~ 26. 8. 25. 요청건)", "20260903132534", "20260903090901",
         "광주양림2관리소-1685", "주거복지실-2044"),
    _row("주택소유 전산검색 결과 통보(4차, ~ 2025년 하반기 예비자 정기)", "20260205101913", "20260204090457",
         "광주양림2관리소-245", "주거복지실-494"),
    _row("주택소유 전산검색 결과 통보(4차, ~ 26. 1. 27. 요청건)", "20260204092600", "20260203152912",
         "광주양림2관리소-241", "주거복지실-492"),
]


def test_pick_34():
    n = ledger.pick_notice(ROWS, 34)
    assert n.doc_number == "주거복지실-2044"
    assert n.enforce_date == dt.date(2026, 9, 3)
    assert n.request_date == dt.date(2026, 8, 25)


def test_pick_prefers_request_round_and_exact_number():
    n = ledger.pick_notice(ROWS, 4)
    assert n.doc_number == "주거복지실-492" and n.request_date == dt.date(2026, 1, 27)
    assert ledger.pick_notice(ROWS, 3) is None          # '34차'가 '3차'로 잡히면 안 된다
    assert ledger.pick_notice(ROWS, 1) is None
