"""품질평가 초안: 전년도 근거의 문서번호 → 전년 대장 제목 → 올해 대장 같은 종류 문서."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import quality_draft as qd  # noqa: E402
import quality_eval as qe  # noqa: E402

D = dt.date


def _db(*a, **k):
    """예전 모양(설명 유지) 시험: 공문 제목을 붙이지 않는다."""
    k.setdefault("with_title", False)
    return qd.draft_basis(*a, **k)


def _doc(seq, title, d):
    return qd.Doc(seq=seq, number=f"광주양림2관리소-{seq}", title=title, date=d)


LEDGERS = {
    2025: [_doc(120, "2025년 1월 주택소유 정기검색 의뢰", D(2025, 1, 13)),
           _doc(393, "2025년 2월 주택소유 정기검색 의뢰", D(2025, 2, 17)),
           _doc(1936, "임대주택 계약체결 안내(101동 1203호)", D(2025, 9, 15)),
           _doc(173, "2025년 공공임대 예비입주자 모집공고 계획 수립", D(2025, 1, 21))],
    2026: [_doc(110, "2026년 1월 주택소유 정기검색 의뢰", D(2026, 1, 12)),
           _doc(402, "2026년 2월 주택소유 정기검색 의뢰", D(2026, 2, 16)),
           _doc(127, "갱신계약 체결 안내(3월 만기)", D(2026, 1, 19)),
           _doc(2001, "임대주택 계약체결 안내(102동 304호)", D(2026, 9, 3)),
           _doc(2100, "임대주택 계약체결 안내(103동 1101호)", D(2026, 10, 7))],
    2027: [_doc(130, "갱신계약 체결 안내(3월 만기)", D(2027, 1, 18))],
}


def test_parse_refs_shapes():
    refs = qd.parse_refs("1월-120(25.01.13), 2월-393(25.02.17)\n계약안내-1936(25.09.15)\n127(26.1.19.) 3월\n264 (26.2.9.)")
    assert [(r.seq, r.date, r.mon, r.pre, r.suf) for r in refs] == [
        (120, D(2025, 1, 13), "1", "", ""), (393, D(2025, 2, 17), "2", "", ""),
        (1936, D(2025, 9, 15), "", "계약안내", ""), (127, D(2026, 1, 19), "", "", "3"), (264, D(2026, 2, 9), "", "", "")]
    assert refs[0].pad and refs[3].dot and refs[4].space


def test_monthly_series_and_prefix():
    res = _db("1월-120(25.01.13), 2월-393(25.02.17)", 2025, 2026, LEDGERS)
    assert res.basis == "1월-110(26.01.12), 2월-402(26.02.16)" and res.found == 2


def test_next_year_offset_and_suffix():
    res = _db("127(26.1.19.) 3월", 2025, 2026, LEDGERS, follow_offset=True)   # 다음 해 문서 → 다음 해
    assert res.basis == "130(27.1.18.) 3월"


def test_keeps_text_and_marks_missing():
    prev = "해약처리현황 화면 캡처\n계약안내-1936(25.09.15)\n모집공고계획수립-173(25.01.21)\n999(25.3.3.)"
    res = _db(prev, 2025, 2026, LEDGERS)
    lines = res.basis.split("\n")
    assert lines[0] == "해약처리현황 화면 캡처"
    assert lines[1] == "계약안내-2001(26.09.03), 2100(26.10.07)"     # 원래처럼 '계약안내-'는 맨 앞에만
    assert lines[2] == "999(25.3.3.)(확인 필요)" and len(lines) == 3   # 일부라도 찾았으면 '없음' 줄은 안 씀
    assert len(res.missing) == 2


def test_round_and_similar_titles():
    led = {2025: [_doc(120, "입주자격심사 결과(2025년 1월 정기, 1차)", D(2025, 1, 13))],
           2026: [_doc(110, "입주자격심사 결과(2026년 1월 정기, 2차)", D(2026, 1, 12)),
                  _doc(150, "입주자격심사 결과 통보(2026년 2월 정기 7차)", D(2026, 2, 12)),
                  _doc(170, "관리비 부과 내역", D(2026, 2, 13))]}
    res = _db("1월-120(25.01.13)", 2025, 2026, led)
    assert res.basis == "1월-110(26.01.12)"                         # 차수는 달라도 같은 종류
    led[2026] = led[2026][1:]
    res = _db("1월-120(25.01.13)", 2025, 2026, led)      # 열쇠가 같은 게 없으면 비슷한 제목
    assert res.basis == "2월-150(26.02.12)"


def test_nothing_found_note():
    res = _db("모집공고계획수립-173(25.01.21)\n화면 캡처", 2025, 2026, LEDGERS)
    assert res.basis == "화면 캡처\n※ 2026년 대장에서 확인 필요: 2025년 공공임대 예비입주자 모집공고 계획 수립"


def test_plain_text_carried():
    res = _db("11월 말 기준 적정", 2025, 2026, LEDGERS)
    assert res.basis == "11월 말 기준 적정" and res.carried


def test_parse_ledger_rows():
    rows = [{"text": ["생산", "20260112093000", "광주양림2관리소-110", "2026년 1월 주택소유 정기검색 의뢰", "오영철",
                      "20260112093500", "주택소유검색"], "userdata": "<CREATE_REG_DATE>20260112093000</CREATE_REG_DATE>"},
            {"text": ["접수", "20260903132534", "광주양림2관리소-1685", "주택소유 전산검색 결과 통보(34차)", "담당",
                      "주거복지실", "20260903090901", "", "", "", "주거복지실-2044"], "userdata": ""}]
    docs = qd.parse_ledger_rows(rows)
    assert [(d.seq, d.title, d.date) for d in docs] == [
        (110, "2026년 1월 주택소유 정기검색 의뢰", D(2026, 1, 12)), (1685, "주택소유 전산검색 결과 통보(34차)", D(2026, 9, 3))]
    assert qd.docs_from_json(qd.docs_to_json(docs))[0].key == docs[0].key


def test_make_draft_matches_items():
    prev = [qe.Item(row=10, part="임대운영", area="", indicator="", no="1-3", seq=4, text="주택소유정기검색 의뢰 여부",
                    basis="1월-120(25.01.13)"),
            qe.Item(row=12, part="임대운영", area="", indicator="", no="1-5", seq=1, text="미반환임대보증금 관리",
                    basis="11월 말 기준 적정")]
    cur = [qe.Item(row=30, part="임대운영", area="", indicator="", no="1-3", seq=4, text="주택소유정기검색 의뢰 여부"),
           qe.Item(row=32, part="임대운영", area="", indicator="", no="1-5", seq=1, text="미반환임대보증금 관리"),
           qe.Item(row=40, part="유지관리", area="", indicator="", no="1-1", seq=1, text="다른 항목")]
    out = qd.make_draft(prev, cur, 2025, 2026, LEDGERS, with_title=False)
    assert [it.row for it, _r in out] == [30, 32]
    assert cur[0].basis == "1월-110(26.01.12), 2월-402(26.02.16)"
    assert cur[1].basis == "11월 말 기준 적정" and cur[2].basis == ""
    assert qd.needed_years(prev, 2025, 2026) == ({2025}, {2026})


def test_month_label_keeps_gap():
    led = {2025: [_doc(54, "임대차계약 변경신고", D(2025, 1, 7))],
           2026: [_doc(60, "임대차계약 변경신고", D(2026, 1, 8)), _doc(300, "임대차계약 변경신고", D(2026, 12, 3))]}
    res = _db("2월-54(25.01.07)", 2025, 2026, led)
    assert res.basis == "2월-60(26.01.08), 1월-300(26.12.03)"


def test_current_year_only():
    """기본: 참고 근거가 어느 해 문서든 새 문서는 당해년도 대장에서."""
    res = _db("127(26.1.19.) 3월", 2026, 2026, LEDGERS)
    assert res.basis == "127(26.1.19.) 3월"
    assert qd.needed_years([qe.Item(row=1, part="임대운영", area="", indicator="", no="1-1", seq=1, text="x",
                                    basis="1월-120(25.01.13) 264 (26.2.9.)")], 2026, 2026) == ({2025, 2026}, {2026})


def test_save_as_keeps_source(tmp_path):
    from test_quality_eval import _sheet
    src, dst = str(tmp_path / "양식.xlsx"), str(tmp_path / "완성본.xlsx")
    _sheet(src)
    items = qe.load(src)
    items[3].basis = "1월-110(26.01.12)"
    qe.save_as(src, dst, items, "광주양림2")
    assert qe.load(dst)[3].basis == "1월-110(26.01.12)"
    assert qe.load(src)[3].basis == "모집공고계획수립-173"


def test_renamed_docs_found_by_item_name():
    led = {2025: [_doc(120, "입주자격심사 결과(2025년 1월 정기, 1차)", D(2025, 1, 13))],
           2026: [_doc(13, "입주자 주택소유 정기검색 의뢰(26년 1월)", D(2026, 1, 6)),
                  _doc(122, "입주자 주택소유 정기검색 의뢰(26년 5월 갱신)", D(2026, 1, 19)),
                  _doc(228, "입주자 주택소유 정기검색 의뢰(26년 2월)", D(2026, 2, 2))]}
    res = _db("1월-120(25.01.13)", 2025, 2026, led, item_text="주택소유정기검색 의뢰 여부")
    assert res.basis == "1월-13(26.01.06), 2월-228(26.02.02)"


def test_existing_current_year_ref_kept_verbatim():
    res = _db("127(26.1.19.) 3월", 2026, 2026,
                         {2026: [_doc(127, "2026년 9월 갱신계약 안내", D(2026, 1, 19))]})
    assert res.basis == "127(26.1.19.) 3월"                       # 제목의 '9월'에 끌려가지 않음


def test_cached_ledgers(tmp_path):
    import json
    today = dt.date.today()
    docs = qd.docs_to_json(LEDGERS[2025])
    (tmp_path / f"{today.year - 1}.json").write_text(json.dumps({"v": qd.CACHE_V, "date": "2000-01-01", "docs": docs}), "utf-8")
    assert qd.cached_ledgers([today.year - 1, today.year], str(tmp_path)) is None     # 올해 목록 없음
    (tmp_path / f"{today.year}.json").write_text(json.dumps({"v": qd.CACHE_V, "date": "2000-01-01", "docs": docs}), "utf-8")
    assert qd.cached_ledgers([today.year], str(tmp_path)) is None                     # 올해 목록은 오늘 것만
    (tmp_path / f"{today.year}.json").write_text(json.dumps({"v": qd.CACHE_V, "date": today.isoformat(), "docs": docs}), "utf-8")
    got = qd.cached_ledgers([today.year - 1, today.year], str(tmp_path))
    assert set(got) == {today.year - 1, today.year} and len(got[today.year]) == len(docs)


def test_internal_numbers_keeps_only_internal():
    D = qd.Doc
    led = {2026: [D(126, "광주양림2관리소-126", "3월 갱신", dt.date(2026, 1, 19), to=""),
                  D(127, "광주양림2관리소-127", "3월 갱신", dt.date(2026, 1, 19), to="201동 904호 입주자귀하")]}
    got = qd.internal_numbers("3월-126(26.01.19) 2026년 3월 안내문\n3월-127(26.01.19) 2026년 3월 안내문\n해약처리현황 화면 캡처",
                              led, 2026)
    assert got == "3월-126(26.01.19) 3월 갱신\n해약처리현황 화면 캡처"


def test_old_cache_kept_for_past_year(tmp_path):
    import json
    today = dt.date.today()
    docs = qd.docs_to_json(LEDGERS[2025])
    (tmp_path / f"{today.year - 1}.json").write_text(json.dumps({"date": "2000-01-01", "docs": docs}), "utf-8")
    assert qd.cached_ledgers([today.year - 1], str(tmp_path)) is not None    # 지난해는 한 번 읽은 목록을 계속 쓴다
    (tmp_path / f"{today.year}.json").write_text(json.dumps({"date": today.isoformat(), "docs": docs}), "utf-8")
    assert qd.cached_ledgers([today.year], str(tmp_path)) is None            # 올해 예전 목록(수신자 없음)은 다시


def test_incremental_current_year(tmp_path, monkeypatch):
    import json
    today = dt.date.today()
    old = [qd.Doc(10, "광주양림2관리소-10", "옛 문서", dt.date(today.year, 1, 2), to="")]
    (tmp_path / f"{today.year}.json").write_text(
        json.dumps({"v": qd.CACHE_V, "date": "2000-01-01", "docs": qd.docs_to_json(old)}), "utf-8")
    rows = [{"text": ["생산", "20990101000000", "광주양림2관리소-11", "새 문서", "담당", ""]},
            {"text": ["생산", "20990101000000", "광주양림2관리소-10", "옛 문서", "담당", ""]}]
    monkeypatch.setattr(qd, "_new_rows", lambda *a, **k: rows)
    got, _ = qd.load_ledgers(None, [today.year], str(tmp_path), lambda m: None)
    assert [d.number for d in got[today.year]] == ["광주양림2관리소-11", "광주양림2관리소-10"]
    saved = json.loads((tmp_path / f"{today.year}.json").read_text("utf-8"))
    assert saved["date"] == today.isoformat() and len(saved["docs"]) == 2
