"""품질평가 초안: 관리소마다 다른 근거 모양(연도 없는 날짜·설명·번호 목록)과 '작년과 비교해 없는 항목'."""
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


LED = {
    2025: [_doc(1050, "지하저수조 청소 결과 보고(상반기)", D(2025, 5, 9)),
           _doc(1348, "2025년 상반기 지하저수시설 수질검사 결과 홍보 실시 보고", D(2025, 6, 20)),
           _doc(330, "어린이놀이시설 정기검사 결과보고", D(2025, 2, 10)),
           _doc(1395, "2025년 6월 운영자금 배정 요청(5차)", D(2025, 6, 25)),
           _doc(1396, "2025년 2/4분기 상시 재난대응훈련 결과 보고", D(2025, 6, 26)),
           _doc(687, "2025년 1/4분기 상시 재난대응훈련 결과 보고", D(2025, 3, 21)),
           _doc(2403, "2025년 4/4분기 상시 재난대응훈련 결과 보고", D(2025, 11, 19)),
           _doc(239, "2025년 1월 관리비 등 정산 보고", D(2025, 2, 5)),
           _doc(1435, "2025년 6월 관리비 등 정산 보고", D(2025, 7, 7))],
    2026: [_doc(812, "지하저수조 청소 결과 보고(상반기)", D(2026, 4, 30)),
           _doc(935, "2026년 상반기 수질검사 실시 결과", D(2026, 5, 18)),
           _doc(531, "2026년 1/4분기 상시 재난대응훈련 결과 보고", D(2026, 3, 20)),
           _doc(1113, "2026년 2/4분기 상시 재난대응훈련 결과 보고", D(2026, 6, 16)),
           _doc(148, "2026년 1월 관리비 등 정산 보고", D(2026, 2, 4)),
           _doc(355, "2026년 2월 관리비 등 정산 보고", D(2026, 3, 5))],
}


def test_yearless_dates_with_description():
    refs = qd.parse_refs("광주양림2- 1050(05.09) 지하저수조 청소\n광주양림2_ 1050 (25.05.09) 저수조(상방기)", 2025)
    assert [(r.pre, r.presep, r.seq, r.date, r.ylen, r.desc) for r in refs] == [
        ("광주양림2", "- ", 1050, D(2025, 5, 9), 0, "지하저수조 청소"),
        ("광주양림2", "_ ", 1050, D(2025, 5, 9), 2, "저수조(상방기)")]


def test_public_facility_item_and_lacking():
    prev = ("코넥스 안전점검일지 화면캡쳐\n광주양림2- 1050(05.09) 지하저수조 청소\n"
            "광주양림2- 1348(06.20) 수질검사\n광주양림2- 330(02.10) 어린이놀이터 정기검사")
    res = _db(prev, 2025, 2026, LED, item_text="공용시설물 관리상태")
    assert res.basis.split("\n") == ["코넥스 안전점검일지 화면캡쳐", "광주양림2- 812(04.30) 지하저수조 청소",
                                     "광주양림2- 935(05.18) 수질검사"]       # 수질검사는 설명으로 찾음
    assert res.lacking == ["어린이놀이터 정기검사"]


def test_wrong_number_found_by_description_and_quarters():
    prev = ("광주양림2- 687(03.21) 1분기 재난대응훈련\n광주양림2- 1395(06.25) 2분기 재난대응훈련\n"
            "광주양림2- 2403(11.19) 4분기 재난대응훈련")
    res = _db(prev, 2025, 2026, LED)
    assert res.basis.split("\n") == ["광주양림2- 531(03.20) 1분기 재난대응훈련",
                                     "광주양림2- 1113(06.16) 2분기 재난대응훈련"]   # 1395는 번호 오기 → 설명·날짜로
    assert res.lacking == ["4분기 재난대응훈련"]


def test_number_list_without_dates():
    res = _db("광주양림2-239,1435", 2025, 2026, LED)
    assert res.basis == "광주양림2-148,355" and res.found == 2


def test_make_draft_sets_reason_and_flag():
    prev = [qe.Item(row=1, part="유지관리", area="", indicator="", no="1-4", seq=1, text="공용시설물 관리상태",
                    basis="광주양림2- 330(02.10) 어린이놀이터 정기검사\n광주양림2- 1050(05.09) 지하저수조 청소")]
    cur = [qe.Item(row=9, part="유지관리", area="", indicator="", no="1-4", seq=1, text="공용시설물 관리상태",
                   reason="점검자 메모")]
    out = qd.make_draft(prev, cur, 2025, 2026, LED)
    assert out and cur[0].flag
    assert cur[0].reason == "점검자 메모\n작년과 비교해 없는 항목: 어린이놀이터 정기검사"
    qd.make_draft(prev, cur, 2025, 2026, LED)                     # 다시 해도 사유가 겹치지 않음
    assert cur[0].reason.count("작년과 비교해") == 1


def test_save_writes_reason_and_yellow(tmp_path):
    from openpyxl import load_workbook
    from test_quality_eval import _sheet
    p = str(tmp_path / "평가표.xlsx")
    _sheet(p)
    items = qe.load(p)
    items[0].reason, items[0].flag = "작년과 비교해 없는 항목: 수질검사", True
    qe.save(p, items)
    ws = load_workbook(p)["항목별평가표"]
    assert ws["J8"].value == "작년과 비교해 없는 항목: 수질검사"
    assert ws["I8"].fill.fgColor.rgb == qe.FLAG_COLOR and ws["J8"].fill.fgColor.rgb == qe.FLAG_COLOR
    again = qe.load(p)
    assert again[0].flag and again[0].reason.startswith("작년과")
    again[0].flag, again[0].reason = False, ""
    qe.save(p, again)
    ws = load_workbook(p)["항목별평가표"]
    assert ws["I8"].fill.fill_type is None and ws["J8"].value is None


def test_default_writes_doc_title():
    """기본: '번호(날짜) 공문 제목 그대로' 한 줄에 하나씩."""
    prev = "코넥스 화면캡쳐\n광주양림2- 1050(05.09) 지하저수조 청소\n광주양림2- 1348(06.20) 수질검사"
    res = qd.draft_basis(prev, 2025, 2026, LED)
    assert res.basis.split("\n") == ["코넥스 화면캡쳐",
                                     "광주양림2- 812(04.30) 지하저수조 청소 결과 보고(상반기)",
                                     "광주양림2- 935(05.18) 2026년 상반기 수질검사 실시 결과"]


def test_default_title_for_lists_and_quarters():
    assert qd.draft_basis("광주양림2-239,1435", 2025, 2026, LED).basis.split("\n") == [
        "광주양림2-148(26.02.04) 2026년 1월 관리비 등 정산 보고",
        "광주양림2-355(26.03.05) 2026년 2월 관리비 등 정산 보고"]
    res = qd.draft_basis("계약-687(25.03.21), 2403(25.11.19)", 2025, 2026, LED)
    assert res.basis.split("\n") == ["계약-531(26.03.20) 2026년 1/4분기 상시 재난대응훈련 결과 보고",
                                     "계약-1113(26.06.16) 2026년 2/4분기 상시 재난대응훈련 결과 보고"]


def test_save_tidies_basis_cells(tmp_path):
    from openpyxl import load_workbook
    from test_quality_eval import _sheet
    p = str(tmp_path / "평가표.xlsx")
    _sheet(p)
    wb = load_workbook(p)
    ws = wb["항목별평가표"]
    ws.column_dimensions["I"].width = 40
    ws["I8"].font = ws["I8"].font.copy(sz=15)
    wb.save(p)
    items = qe.load(p)
    items[0].basis = "\n".join(f"광주양림2- {800 + n}(04.30) 지하저수조 청소 결과 보고(상반기)" for n in range(12))
    qe.save(p, items)
    ws = load_workbook(p)["항목별평가표"]
    a = ws["I8"].alignment
    assert a.wrap_text and a.horizontal == "left"
    total = sum((ws.row_dimensions[r].height or ws.sheet_format.defaultRowHeight or 15) for r in (8, 9))
    assert total >= 12 * 15 * 1.3                     # 12줄(한 줄에 다 안 들어가면 더)이 다 보이는 높이
    h_before = ws.row_dimensions[8].height
    items = qe.load(p)
    items[0].basis = "짧게"
    qe.save(p, items)
    assert load_workbook(p)["항목별평가표"].row_dimensions[8].height == h_before     # 줄이지는 않음
