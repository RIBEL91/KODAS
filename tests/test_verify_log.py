import datetime as dt

import verify_log as vl


def test_parse_date():
    t = dt.date(2026, 11, 18)
    assert vl.parse_date("2026. 11. 18.", t) == t
    assert vl.parse_date("2026-11-18", t) == t
    assert vl.parse_date("11. 18.", t) == t
    assert vl.parse_date("8월 25일", t) == dt.date(2026, 8, 25)
    assert vl.parse_date("", t) == ""
    assert vl.parse_date("미정", t) == "미정"


def test_from_excel_and_total():
    date_f, num_f = vl.Field("요청일", "date"), vl.Field("세대주", "num")
    assert vl.from_excel(date_f, 46344.0) == dt.date(2026, 11, 18)
    assert vl.from_excel(date_f, "8월 25일") == "8월 25일"
    assert vl.from_excel(num_f, 25.0) == 25
    assert vl.total_of({"세대주": 25, "배우자": 8, "세대원": 20}) == 53
    assert vl.total_of({"세대주": "", "배우자": "", "세대원": ""}) == ""


def test_next_label_and_cells():
    assert vl.next_label([{"입주자격검색": "26-11월"}, {"입주자격검색": "명의변경"}]) == "26-12월"
    assert vl.next_label([{"입주자격검색": "26-12월"}]) == "27-1월"
    assert vl.to_cell(vl.Field("요청일", "date"), dt.date(2026, 1, 2)) == {"t": "date", "v": "2026-01-02"}
    assert vl.to_cell(vl.Field("차수", "text"), "") == {"t": "empty"}
    assert [len(s.fields) for s in vl.SHEETS] == [11, 11, 10]      # B~L(갱신·명의변경), B~K(주택정기)
    assert vl.RENEW.last_col == 12 and vl.REGULAR.last_col == 11
    assert vl.RENEW.fields[-1].key == vl.REGULAR.fields[-1].key == "자격검증 기록사항"


def test_done_and_remap():
    assert vl.is_done(vl.RENEW, {"갱신완료": "계약완료"})
    assert vl.is_done(vl.OTHER, {"갱신완료": "부적격자 예비자 제외 확정"})
    assert not vl.is_done(vl.RENEW, {"갱신완료": "소명완료"})
    assert vl.is_done(vl.REGULAR, {"검증완료": "확정"})              # 주택정기는 확정이면 숨긴다
    assert not vl.is_done(vl.REGULAR, {"검증완료": "소명안내"})
    rows = [{"_row": r, "n": r} for r in range(5, 11)]
    vl.remap_rows(rows, 9, 6)                    # 9줄을 6줄 자리로 끼워 넣음
    assert [(r["_row"], r["n"]) for r in rows] == [(5, 5), (6, 9), (7, 6), (8, 7), (9, 8), (10, 10)]
    assert vl.status_col(vl.RENEW) == 11 and vl.status_col(vl.REGULAR) == 10


def test_book_split_need():
    rows = {"갱신": [{"입주자격검색": "26-1월", "_row": 5}, {"입주자격검색": "명의변경", "_row": 6}],
            "명의변경·예비자정기": [], "주택정기": []}
    b = vl.Book(rows, True, ("명의변경·예비자정기",), ())
    assert b.to_move() == [6] and b.needs_split()
    assert not vl.Book({**rows, "갱신": rows["갱신"][:1]}, True, (), ()).needs_split()


def test_fix_years():
    rec = {"입주자격검색": "26-12월", "요청일": "8월 25일", "범정부 송신": "8월 26일",
           "조사완료일": dt.date(2026, 10, 8)}
    vl.fix_years(vl.RENEW, rec)
    assert rec["요청일"] == dt.date(2026, 8, 25) and rec["범정부 송신"] == dt.date(2026, 8, 26)
    rec = {"입주자격검색": "27-1월", "요청일": "12월 20일", "조사완료일": ""}
    vl.fix_years(vl.RENEW, rec)                  # 다른 날짜가 없으면 달(27년 1월) 기준 → 지난해 12월
    assert rec["요청일"] == dt.date(2026, 12, 20)


def test_store_write_move_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(vl, "store_path", lambda: str(tmp_path / "기록.json"))
    assert not vl.store_exists() and vl.store_book().rows["갱신"] == []
    for m, st in (("26-1월", "계약완료"), ("26-2월", "소명안내"), ("26-3월", "소명안내")):
        vl.store_write(vl.RENEW, {"입주자격검색": m, "갱신완료": st, "세대주": 2, "배우자": 1}, 0)
    rows = vl.store_load()["갱신"]
    assert [r["_row"] for r in rows] == [1, 2, 3] and rows[0]["총계"] == 3
    w = vl.store_write(vl.RENEW, {**rows[2], "갱신완료": "계약완료", "요청일": dt.date(2026, 1, 5)}, 3,
                       status_changed=True)
    assert (w.moved_from, w.moved_to) == (3, 2)        # 끝난 줄 바로 아래로
    rows = vl.store_load()["갱신"]
    assert [r["입주자격검색"] for r in rows] == ["26-1월", "26-3월", "26-2월"]
    assert rows[1]["요청일"] == dt.date(2026, 1, 5)    # 날짜는 날짜로 되살린다
    vl.store_delete(vl.RENEW, 1)
    assert [(r["_row"], r["입주자격검색"]) for r in vl.store_load()["갱신"]] == [(1, "26-3월"), (2, "26-2월")]
