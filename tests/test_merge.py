"""ai3(관리업무 월별·주별 서식)에서 가져온 칸 종류·머리말 시험."""
import datetime as dt
import os

import complex_info
import doc_template as dtpl
import paths

D = dt.date(2026, 11, 6)   # 금요일


def setup_function(_):
    dtpl.set_complex(complex_info.resolve({}))


def test_new_date_styles_keep_old_meaning():
    assert dtpl.fmt_date(D, "일") == "2026. 11. 6."             # 임대 서식 그대로
    assert dtpl.fmt_date(D, "일자") == "2026년 11월 6일"          # ai3의 '일'
    assert dtpl.fmt_date(D, "공문요일") == "2026. 11. 6.(금)"
    assert dtpl.fmt_date(D, "짧은년월") == "'26년 11월"
    assert dtpl.fmt_date(D, "점월") == "2026. 11월"


def test_amount_number_calc_complex():
    t = dtpl.parse("제목: {단지:단지명} 구입\n수신자: 내부결재\n---\n"
                   "| 수량 | 단가 | 금액 |\n|---|\n| {숫자:수량} | {숫자:단가=3200} | {계산:금액=수량*단가} |\n"
                   "합계 {금액:총액}")
    assert t.input_fields() == ["수량", "단가", "총액"]
    assert t.input_kinds() == {"수량": "숫자", "단가": "숫자", "총액": "금액"}
    assert t.input_defaults() == {"단가": "3200"}
    body = dtpl.fill(t.body, {"입력:수량": "10", "입력:단가": "3200", "입력:총액": "113560"}, {})
    assert "| 10 | 3,200 | 32,000 |" in body
    assert "금113,560원(금일십일만삼천오백육십원)" in body
    assert dtpl.fill(t.title, {}, {}) == "광주우산3 구입"
    assert not dtpl.leftovers(body)          # 32,000의 000은 빈칸 표시가 아니다


def test_input_default_used_when_no_widget():
    assert dtpl.fill("{입력:대상=301~303동}", {}, {}) == "301~303동"
    assert dtpl.fill("{입력:대상=301~303동}", {"입력:대상": "304동"}, {}) == "304동"
    assert dtpl.fill("{입력:대상=301~303동}", {"입력:대상": ""}, {}) == "{입력:대상=301~303동}"


def test_pipe_inside_date_in_table():
    rows = dtpl._split_row("| {날짜:구입일|공문} | 가 |")
    assert rows == ["{날짜:구입일|공문}", "가"]


def test_extras_carry_roundtrip_and_set_default(tmp_path):
    src = ("제목: 청구\n수신자: 내부결재\n구분: 관리비·회계\n분야: 주택관리\n주기: 매주\n"
           "입력: {숫자:전월누적=100}\n이월: 전월누적 <- 누적\n---\n"
           "청구 {숫자:청구=5}, 누적 {계산:누적=전월누적+청구}")
    t = dtpl.parse(src, os.path.join(tmp_path, "주별09_청구.txt"))
    assert (t.area, t.cycle, t.label) == ("주택관리", "매주", "09. 청구")
    assert t.input_fields() == ["청구", "전월누적"]
    assert dtpl.computed(t, {"입력:청구": "5", "입력:전월누적": "100"}) == {"누적": "105"}
    dtpl.save(t)
    back = dtpl.load(t.path)
    assert back.extras == t.extras and back.carry == [("전월누적", "누적")] and back.cycle == "매주"
    assert dtpl.set_default(back, "전월누적", "105")
    assert back.extras == ["{숫자:전월누적=105}"]


def test_month_day_style_mix():
    t = dtpl.parse("제목: {날짜:일시|짧은년월} 결과\n---\n일시: {날짜:일시|공문요일}")
    assert t.date_fields() == [("일시", "공문요일")]


def test_merged_folder_areas():
    items, errors = dtpl.load_all(paths.template_dir())
    assert not errors
    areas = {}
    for t in items:
        areas.setdefault(t.area, []).append(t)
    assert len([t for t in areas["임대"] if t.file_name[:2].isdigit()]) == 28   # 오영철 임대 서식 그대로(+33번·34번·35번)
    assert {t.cycle for t in areas["주택관리"]} == {"매월", "매주"}
    assert all(areas.get(a) for a in ("시설", "주거복지", "주택관리"))
    assert sum(len(v) for v in areas.values()) == 28 + 64
