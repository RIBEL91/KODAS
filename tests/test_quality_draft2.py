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
    assert res.basis.split("\n") == ["코넥스 안전점검일지 화면캡쳐", "광주양림2- 812(26.04.30) 지하저수조 청소",
                                     "광주양림2- 935(26.05.18) 수질검사"]       # 수질검사는 설명으로 찾음
    assert res.lacking == ["어린이놀이터 정기검사"]


def test_wrong_number_found_by_description_and_quarters():
    prev = ("광주양림2- 687(03.21) 1분기 재난대응훈련\n광주양림2- 1395(06.25) 2분기 재난대응훈련\n"
            "광주양림2- 2403(11.19) 4분기 재난대응훈련")
    res = _db(prev, 2025, 2026, LED)
    assert res.basis.split("\n") == ["광주양림2- 531(26.03.20) 1분기 재난대응훈련",
                                     "광주양림2- 1113(26.06.16) 2분기 재난대응훈련"]   # 1395는 번호 오기 → 설명·날짜로
    assert res.lacking == ["4분기 재난대응훈련"]


def test_number_list_without_dates():
    res = _db("광주양림2-239,1435", 2025, 2026, LED)
    assert res.basis == "광주양림2-148,355" and res.found == 2


def test_make_draft_marks_missing_in_basis():
    """작년에 있고 올해 없는 문서: 점수 불인정 사유가 아니라 평가 근거 맨 아래 '✗ …' 줄(엑셀 빨간 글씨)."""
    prev = [qe.Item(row=1, part="유지관리", area="", indicator="", no="1-4", seq=1, text="공용시설물 관리상태",
                    basis="광주양림2- 330(02.10) 어린이놀이터 정기검사\n광주양림2- 1050(05.09) 지하저수조 청소")]
    cur = [qe.Item(row=9, part="유지관리", area="", indicator="", no="1-4", seq=1, text="공용시설물 관리상태",
                   reason="점검자 메모\n작년과 비교해 없는 항목: 예전 방식")]
    out = qd.make_draft(prev, cur, 2025, 2026, LED)
    assert out and cur[0].flag
    assert cur[0].reason == "점검자 메모"                       # 예전 방식 사유는 지우고 직접 적은 것만
    assert cur[0].basis.split("\n")[-1] == "✗ 작년에 있고 올해 없음: 어린이놀이터 정기검사"
    assert cur[0].added == []                                   # 작년 근거에서 옮긴 줄은 '새로 들어간 줄'이 아님
    qd.make_draft(prev, cur, 2025, 2026, LED)                  # 다시 해도 겹치지 않음
    assert cur[0].basis.count("✗ ") == 1


def test_save_writes_red_and_yellow_lines(tmp_path):
    from openpyxl import load_workbook
    from openpyxl.cell.rich_text import CellRichText
    from test_quality_eval import _sheet
    p = str(tmp_path / "평가표.xlsx")
    _sheet(p)
    wb = load_workbook(p)                                       # 예전 방식의 노란 칸 칠 → 저장하면 지워진다
    qe._fill(wb["항목별평가표"], 8, 9, True)
    wb.save(p)
    items = qe.load(p)
    items[0].basis = "광주양림2- 812(26.04.30) 청소\n광주양림2- 37(26.01.08) 새 문서\n✗ 작년에 있고 올해 없음: 수질검사"
    items[0].added = ["광주양림2- 37(26.01.08) 새 문서"]
    qe.save(p, items)
    ws = load_workbook(p, rich_text=True)["항목별평가표"]
    v = ws["I8"].value
    assert isinstance(v, CellRichText)
    colors = {b.text.strip(): (b.font.color.rgb if b.font.color else None) for b in v}
    assert colors == {"광주양림2- 812(26.04.30) 청소": None,
                      "광주양림2- 37(26.01.08) 새 문서": qe.ADDED_COLOR,
                      "✗ 작년에 있고 올해 없음: 수질검사": qe.MISS_COLOR}
    assert ws["I8"].fill.fill_type is None and ws["J8"].value is None   # 노란 칸·사유 칸은 쓰지 않는다
    again = qe.load(p)
    assert again[0].flag and again[0].added == ["광주양림2- 37(26.01.08) 새 문서"]
    assert again[0].basis == items[0].basis


def test_default_writes_doc_title():
    """기본: '번호(날짜) 공문 제목 그대로' 한 줄에 하나씩."""
    prev = "코넥스 화면캡쳐\n광주양림2- 1050(05.09) 지하저수조 청소\n광주양림2- 1348(06.20) 수질검사"
    res = qd.draft_basis(prev, 2025, 2026, LED)
    assert res.basis.split("\n") == ["코넥스 화면캡쳐",
                                     "광주양림2- 812(26.04.30) 지하저수조 청소 결과 보고(상반기)",
                                     "광주양림2- 935(26.05.18) 2026년 상반기 수질검사 실시 결과"]


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


def test_promo_docs_follow_main_doc():
    led = {2025: LED[2025],
           2026: LED[2026] + [_doc(728, "상반기 지하저수조 청소 홍보 실시 보고", D(2026, 4, 16)),
                              _doc(1900, "하반기 지하저수조 청소 홍보 실시 보고", D(2026, 10, 1)),
                              _doc(700, "탁구대회 홍보", D(2026, 4, 20))]}
    res = qd.draft_basis("광주양림2- 1050(05.09) 지하저수조 청소", 2025, 2026, led)
    assert res.basis.split("\n") == ["광주양림2- 728(26.04.16) 상반기 지하저수조 청소 홍보 실시 보고",     # 먼저 낸 것이 위로
                                     "광주양림2- 812(26.04.30) 지하저수조 청소 결과 보고(상반기)"]
    assert qd.draft_basis("광주양림2- 1050(05.09) 지하저수조 청소", 2025, 2026, led, promos=False).basis.count("\n") == 0
    assert qd.subject_core("상반기 지하저수조 청소 홍보 실시 보고") == "지하저수조청소"


def test_desc_wider_than_ref_title_adds_same_topic_docs():
    """설명('전기안전관리자')이 참고 공문 제목('…기술교육 수료 보고')보다 넓으면 그 주제의 다른 공문도 함께,
    받은 안내 공문은 빼고, 먼저 낸 것이 위로."""
    led = {2025: [_doc(343, "전기안전관리기술교육 수료 보고", D(2025, 2, 12))],
           2026: [_doc(445, "전기안전관리기술교육 수료 보고", D(2026, 3, 10)),
                  _doc(37, "전기안전관리자 선해임 변경 신고", D(2026, 1, 8)),
                  _doc(50, "전기안전관리자 기술교육 안내", D(2026, 1, 20))]}
    res = qd.draft_basis("광주양림2- 343(02.12) 전기안전관리자", 2025, 2026, led)
    assert res.basis.split("\n") == ["광주양림2- 37(26.01.08) 전기안전관리자 선해임 변경 신고",
                                     "광주양림2- 445(26.03.10) 전기안전관리기술교육 수료 보고"]
    assert "37(" not in qd.draft_basis("광주양림2- 343(02.12) 전기안전관리자", 2025, 2026, led, promos=False).basis


def test_supplement_sheet_adds_docs_in_written_order():
    """올해 손으로 적은 평가표(보탤 근거): 그 문서들도 같은 모양·공문 제목으로 넣고, 순서는 적은 순서,
    올해 같은 종류가 없는 지난 문서는 그대로(연도 붙여), 줄 바뀜으로 끊긴 번호·날짜 오타도 읽는다."""
    led = {2025: [_doc(1050, "지하저수조 청소 결과 보고(상반기)", D(2025, 5, 9)),
                  _doc(330, "어린이놀이시설 정기검사 결과보고", D(2025, 2, 10))],
           2026: [_doc(812, "지하저수조 청소 결과 보고(상반기)", D(2026, 4, 30)),
                  _doc(37, "전기안전관리자 선해임 변경 신고", D(2026, 1, 8)),
                  _doc(379, "전기설비 정기검사 신청 보고", D(2026, 3, 3)),
                  _doc(1323, "2026년 소방시설물 종합점검 지적사항 보수 완료 보고", D(2026, 7, 14))]}
    prev = [qe.Item(row=1, part="유지관리", area="", indicator="", no="1-4", seq=1, text="공용시설물 관리상태",
                    basis="화면캡처\n광주양림2- 1050(05.09) 지하저수조 청소\n광주양림2- 330(02.10) 어린이놀이터 정기검사")]
    sup = [qe.Item(row=1, part="유지관리", area="", indicator="", no="1-4", seq=1, text="공용시설물 관리상태",
                   basis="코넥스 시설물 관리대장 화면캡쳐\n전기안전관리자 선.해임변경 신고(양림2-37(26.01.08))\n"
                         "지하저수조 청소결과 보고(양림2-812(26.04.30))\n전기설비 정기검사 신청보고(양림2-379(26.03.03))\n"
                         "어린이놀이시설 정기검사 결과보고(양림2-330(25.02.10))\n소방 보수 완료보고\n(양림2-1323(26..07.14))\n"
                         "임대차 신고 1033(26.69.1)")]
    cur = [qe.Item(row=9, part="유지관리", area="", indicator="", no="1-4", seq=1, text="공용시설물 관리상태")]
    (it, res), = qd.make_draft(prev, cur, 2025, 2026, led, extras=[(sup, 2026)])
    lines = it.basis.split("\n")
    assert lines == [
        "코넥스 시설물 관리대장 화면캡쳐",
        "광주양림2- 37(26.01.08) 전기안전관리자 선해임 변경 신고",
        "광주양림2- 812(26.04.30) 지하저수조 청소 결과 보고(상반기)",
        "광주양림2- 379(26.03.03) 전기설비 정기검사 신청 보고",
        "광주양림2- 330(25.02.10) 어린이놀이시설 정기검사 결과보고",
        "광주양림2- 1323(26.07.14) 2026년 소방시설물 종합점검 지적사항 보수 완료 보고",
        "✗ 올해 작성분에 있고 올해 없음: '임대차 신고 1033(26.69.1)'(날짜를 잘못 적어 읽지 못함)"]
    assert not res.lacking                          # 지난 정기검사는 손으로 적은 근거에 있으니 없는 항목 아님
    assert it.reason == ""                          # 점수 불인정 사유 칸에는 적지 않는다
    assert it.flag
    # 작년 근거(저수조 청소)에서 옮긴 줄이 아닌 것 = 새로 들어간 줄(노란 글씨)
    assert "광주양림2- 812(26.04.30) 지하저수조 청소 결과 보고(상반기)" not in it.added
    assert "광주양림2- 37(26.01.08) 전기안전관리자 선해임 변경 신고" in it.added


def test_supplement_doc_missing_this_year_goes_to_basis():
    """작성분(2026 상반기)에 있던 공문이 고른 해(2027) 대장에 없으면 평가 근거에 '✗ …' 줄로 이유와 함께."""
    led = {2026: [_doc(379, "전기설비 정기검사 신청 보고", D(2026, 3, 3)),
                  _doc(592, "전기설비 법정 정기검사 홍보 보고", D(2026, 3, 30)),
                  _doc(812, "지하저수조 청소 결과 보고(상반기)", D(2026, 4, 30))],
           2027: [_doc(800, "지하저수조 청소 결과 보고(상반기)", D(2027, 4, 29))]}
    sup = [qe.Item(row=1, part="유지관리", area="", indicator="", no="1-4", seq=1, text="공용시설물 관리상태",
                   basis="전기설비 정기검사 신청보고(양림2-379(26.03.03))\n전기설비 법정 정기검사 홍보 보고(양림2-592(26.3.30))\n"
                         "지하저수조 청소결과 보고(양림2-812(26.04.30))\n양림2-999(26.05.01)")]
    cur = [qe.Item(row=9, part="유지관리", area="", indicator="", no="1-4", seq=1, text="공용시설물 관리상태",
                   reason="직접 적은 사유")]
    (it, res), = qd.make_draft([], cur, 2026, 2027, led, extras=[(sup, 2026, "2026년 상반기")])
    assert it.basis.split("\n") == [
        "800(27.4.29) 지하저수조 청소 결과 보고(상반기)",
        "✗ 2026년 상반기 작성분에 있고 올해 없음: 전기설비 정기검사 신청 보고(2027년 대장에 같은 공문 없음)",
        "✗ 2026년 상반기 작성분에 있고 올해 없음: 전기설비 법정 정기검사 홍보 보고(2027년 대장에 같은 공문 없음)",
        "✗ 2026년 상반기 작성분에 있고 올해 없음: 양림2-999(26.05.01)(2026년 대장에서 이 번호·날짜의 공문을 찾지 못함)"]
    assert it.reason == "직접 적은 사유"
    assert it.flag
    qd.make_draft([], cur, 2026, 2027, led, extras=[(sup, 2026, "2026년 상반기")])     # 다시 해도 겹치지 않음
    assert it.basis.count("✗ ") == 3


def test_old_reason_moves_to_red_lines(tmp_path):
    """예전 방식(사유 칸 '작년과 비교해 없는 항목: …' + 노란 칸)으로 저장된 평가표를 열면 근거의 '✗' 줄로 옮긴다."""
    from openpyxl import load_workbook
    from test_quality_eval import _sheet
    p = str(tmp_path / "평가표.xlsx")
    _sheet(p)
    wb = load_workbook(p)
    ws = wb["항목별평가표"]
    ws["I8"], ws["J8"] = "광주양림2- 812(26.04.30) 청소", "메모\n작년과 비교해 없는 항목: 수질검사, 4분기 훈련"
    qe._fill(ws, 8, 9, True)
    wb.save(p)
    it = qe.load(p)[0]
    assert it.basis.split("\n") == ["광주양림2- 812(26.04.30) 청소", "✗ 작년에 있고 올해 없음: 수질검사",
                                    "✗ 작년에 있고 올해 없음: 4분기 훈련"]
    assert it.reason == "메모" and it.flag


def test_several_years_of_supplements():
    """최근 여러 해 작성분(근거 보태기 여러 개): 해마다의 근거 문서가 모두 같은 종류로 들어간다."""
    led = {2024: [_doc(500, "승강기 정기검사 결과 보고", D(2024, 5, 2))],
           2025: [_doc(600, "소방시설 종합정밀점검 결과 보고", D(2025, 6, 3))],
           2026: [_doc(700, "승강기 정기검사 결과 보고", D(2026, 5, 7)),
                  _doc(710, "소방시설 종합정밀점검 결과 보고", D(2026, 6, 9))]}
    sup24 = [qe.Item(row=1, part="유지관리", area="", indicator="", no="1-4", seq=1, text="공용시설물 관리상태",
                     basis="광주양림2- 500(24.05.02) 승강기 정기검사 결과 보고")]
    sup25 = [qe.Item(row=1, part="유지관리", area="", indicator="", no="1-4", seq=1, text="공용시설물 관리상태",
                     basis="광주양림2- 600(25.06.03) 소방시설 종합정밀점검 결과 보고")]
    cur = [qe.Item(row=9, part="유지관리", area="", indicator="", no="1-4", seq=1, text="공용시설물 관리상태")]
    (it, _res), = qd.make_draft([], cur, 2025, 2026, led, extras=[(sup25, 2025, "2025년도"), (sup24, 2024, "2024년도")])
    assert it.basis.split("\n") == ["700(26.5.7) 승강기 정기검사 결과 보고", "710(26.6.9) 소방시설 종합정밀점검 결과 보고"]
    assert not it.flag
