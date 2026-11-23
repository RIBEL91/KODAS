import datetime as dt
import os
import re

import pytest

import doc_template as dtpl
import paths

D = dt.date(2026, 11, 6)   # 금요일
VALUES = {"이름": "홍길동", "주소": "101동 1001호", "관리소": "가나관리소",
          "단지명": "가나1단지", "담당자": "김담당", "전화번호": "031-000-0000", "세대수": "25",
          "문서링크": "주거복지실-2044(2026.09.03.)", "심사결과링크": "가나관리소-1700(2026. 9. 10.)",
          "소명안내링크": "가나관리소-1701(2026. 9. 10.)", "중복입주링크": "주거복지실-1737(2026.07.22.)"}


def test_fmt_date():
    assert dtpl.fmt_date(D) == "2026. 11. 6.(금)"
    assert dtpl.fmt_date(D, "일") == "2026. 11. 6."
    assert dtpl.fmt_date(D, "월") == "2026년 11월"
    assert dtpl.fmt_date(D, "월만") == "11월"
    assert dtpl.fmt_date(D, "년월") == "26년 11월"
    assert dtpl.fmt_date(D, "분기") == "2026년 4분기"
    assert dtpl.fmt_date(D, "점") == "2026. 11. 6."
    assert dtpl.fmt_date(D, "점요일") == "2026. 11. 6.(금)"


def test_parse_and_fill():
    t = dtpl.parse("제목: 안내({날짜:갱신월|월} 갱신)\n수신자: {주소} {이름} 귀하\n구분: 갱신\n---\n"
                   "기한: {날짜:제출기한}까지 {단지명}\n만료 {날짜:갱신월|점}")
    assert t.date_fields() == [("갱신월", "월"), ("제출기한", "요일")]
    dates = {"갱신월": D, "제출기한": D}
    assert dtpl.fill(t.title, VALUES, dates) == "안내(2026년 11월 갱신)"
    assert dtpl.fill(t.body, VALUES, dates) == "기한: 2026. 11. 6.(금)까지 가나1단지\n만료 2026. 11. 6."
    assert dtpl.fill_receiver(t.receiver, VALUES) == "101동 1001호 홍길동 귀하"
    assert dtpl.fill_receiver(t.receiver, {**VALUES, "주소": ""}) == "홍길동 귀하"
    assert not t.internal


def test_unfilled_kept_and_reported():
    out = dtpl.fill("{이름} {날짜:기한} 0000년 담당자(OOO)", {}, {})
    assert out == "{이름} {날짜:기한} 0000년 담당자(OOO)"
    assert dtpl.leftovers(out) == ["{이름}", "{날짜:기한}", "0000", "OOO"]


def test_table_spans_and_header():
    html = dtpl.to_html("  가. 표\n| 구분 | 내용 | < |\n|---|\n| 기본 | a | b |\n| ^ | c<br>d | e |\n붙임  끝.")
    assert html.count("<table") == 1
    assert 'colspan="2"' in html and 'rowspan="2"' in html
    assert html.count("bgcolor=\"#e8e8e8\"") == 2      # 머리글 2칸(구분, 내용)
    # '  가. 표'는 빈칸 대신 내어쓰기: 첫 줄은 한글 1자(13pt)에서, 둘째 줄은 '가. ' 실제 너비만큼 더 들어가서
    first, rest = _starts(html)[0]
    assert first == pytest.approx(13, abs=0.01) and rest == pytest.approx(13 + dtpl._width_pt("가. "), abs=0.01)
    assert ">가. 표<" in html and html.index("붙임") > html.index("</table>")


def _starts(html):
    """미리보기 HTML의 문단마다 (첫 줄 시작, 둘째 줄 시작) pt."""
    out = []
    for m in re.finditer(r"margin-left:([\d.]+)pt;text-indent:(-?[\d.]+)pt;", html):
        left, ind = float(m.group(1)), float(m.group(2))
        out.append((left + ind, left))
    return out


def test_wrapped_lines_hang_under_item_text():
    """두 줄이 넘는 항목은 둘째 줄이 항목 기호 뒤 글자에 맞춰 시작한다(표준 공문 내어쓰기)."""
    html = dtpl.to_html("1. 첫째 항목\n  가. 둘째\n    1) 셋째\n붙임  1. 서류 1부.\n      2. 서류 1부.\n"
                        "      3. 서류 1부.  끝.\n본문")
    w = dtpl._width_pt
    one, ga, sub, att1, att2, att3 = _starts(html)
    assert one == pytest.approx((0, w("1. ")), abs=0.01)                 # 1. → 둘째 줄은 '1. ' 뒤
    assert ga == pytest.approx((13, 13 + w("가. ")), abs=0.01)           # 빈칸 2개 = 한글 1자(2타)
    assert sub == pytest.approx((26, 26 + w("1) ")), abs=0.01)
    # 붙임: 2. 3.은 '붙임  ' 실제 너비에서 시작해 1.과 같은 열, 둘째 줄도 같은 열
    gap = "붙임" + " " * dtpl.ATTACH_GAP                # 붙임 뒤 간격은 빈칸 ATTACH_GAP개로 고정
    assert att1 == pytest.approx((0, w(gap + "1. ")), abs=0.01)
    assert att2[0] == pytest.approx(w(gap), abs=0.01) and att2 == pytest.approx(att3, abs=0.01)
    assert att2[1] == pytest.approx(att1[1], abs=0.01)
    last = html.split("<p ")[-1]
    assert "margin-left" not in last and "line-height:160%" in last  # 기호 없는 줄은 들여쓰지 않는다


def test_gulim_widths_are_real_font_widths():
    """빈칸·숫자·마침표는 굴림 실제 너비(한글의 절반이 아님). 붙임  1.의 열이 어긋나던 원인."""
    assert dtpl._width_pt(" ") == pytest.approx(13 * 341 / 1024, abs=0.01)
    assert dtpl._width_pt("1.") == pytest.approx(13 * (588 + 342) / 1024, abs=0.01)
    assert dtpl._width_pt("가") == 13


def test_hwp_html_uses_para_marks_not_css_margins():
    """웹한글용 HTML: 여백 CSS 없이 문단 앞 표식 【문단:왼쪽여백:내어쓰기】(HWPUNIT)만 넣는다."""
    body = ("1. 첫째\n  가. 둘째\n| 구분 | 내용 |\n|---|\n| 기본 | □ 건물등기사항증명서(건물등기부등본) 길게 길게<br>  * 미등기 |\n"
            "붙임  1. 가 1부.\n      2. 나 1부.  끝.\n본문")
    html = dtpl.to_html(body, hwp=True)
    assert "margin-left" not in html and "text-indent" not in html
    hu = lambda pt: round(pt * 100)  # noqa: E731
    w = dtpl._width_pt
    assert f"【문단:0:-{hu(dtpl._units('1. ') * 6.5)}】1. 첫째" in html
    assert f"【문단:1300:-{hu(dtpl._units('가. ') * 6.5)}】가. 둘째" in html
    assert f"【문단:550:-{hu(w('* ', 11) / 2)}】* 미등기" in html      # 표 칸(11pt)
    # 붙임: '붙임' 뒤와 2. 앞에 탭 표식(본문을 넣은 뒤 진짜 탭으로 바꾼다) → 1. 2.가 같은 탭 위치
    assert ">붙임【탭】1. 가 1부.<" in html and ">【탭】2. 나 1부. &nbsp;끝.<" in html
    assert "【문단:0:0】본문<" in html                         # 기호 없는 줄도 어절 줄 나눔용 표식
    marks = dtpl.PARA_MARK_RE.findall(html)
    assert len(marks) == 5                                     # 붙임 줄에는 문단 표식을 넣지 않는다


def test_bundled_templates_all_render():
    items, errors = dtpl.load_all(paths.template_dir())
    assert not errors
    assert len([t for t in items if t.file_name[:2].isdigit()]) == 29    # 임대 서식(오영철, 36번 중복입주 결과 보고·35번 예비입주자 모집 공고·34번 갱신계약 완료 보고·33번 국민임대 계약체결 안내 포함)
    assert len([t for t in items if t.file_name.startswith(("월별", "주별"))]) == 64   # 관리업무 서식(ai3)
    import complex_info
    dtpl.set_complex(complex_info.resolve({}))
    items += dtpl.load_all(os.path.join(paths.template_dir(), dtpl.FIRST_DIR))[0]
    items += dtpl.load_all(os.path.join(paths.template_dir(), dtpl.OPTION_DIR))[0]
    for t in items:
        dates = {k: D for k, _ in t.date_fields()}
        values = {**VALUES, **{"입력:" + x: "2026. 10. 25." for x in t.input_fields()}}
        body = dtpl.fill(t.body, values, dates)
        title = dtpl.fill(t.title, values, dates)
        assert not re.search(r"\{[^{}]+\}", title + body), t.label   # 모든 빈칸이 채워짐
        assert "끝." in body, t.label
        html = dtpl.to_html(body)
        assert html.count("<table") == html.count("</table>")
        for style in re.findall(r"\{날짜:[^{}|]+\|([^{}]+)\}", t.title + t.body):
            assert style in dtpl.DATE_STYLES, (t.label, style)


def test_first_header(tmp_path):
    t = dtpl.parse("제목: 가\n수신자: {이름} 귀하\n구분: 나\n1안: 내부\n---\n본문")
    assert t.first == "내부" and not t.internal
    t.path = os.path.join(tmp_path, "05_x.txt")
    dtpl.save(t)
    assert dtpl.load(t.path).first == "내부"


def test_input_fields():
    t = dtpl.parse("제목: 가({입력:차수})\n수신자: 내부결재\n---\n통보일 {입력:통보일}, 다시 {입력:통보일}")
    assert t.input_fields() == ["차수", "통보일"]
    assert t.date_fields() == []
    out = dtpl.fill(t.body, {"입력:통보일": "2026. 10. 25."}, {})
    assert out == "통보일 2026. 10. 25., 다시 2026. 10. 25."
    assert dtpl.fill("{입력:차수}", {}, {}) == "{입력:차수}"            # 비우면 빈칸 표시가 남는다
    t08 = next(x for x in dtpl.load_all(paths.template_dir())[0] if x.file_name.startswith("08_"))
    assert t08.internal and t08.input_fields() == ["차수", "조사완료일", "자격검색요청일"]
    assert t08.uses("문서링크")
    t14 = next(x for x in dtpl.load_all(paths.template_dir())[0] if x.file_name.startswith("14_"))
    assert t14.input_fields() == ["차수"]
    assert t14.uses("심사결과링크") and not t14.uses("소명안내링크")


def test_options_header_and_folder(tmp_path):
    t = dtpl.parse("제목: 가\n수신자: 내부결재\n구분: 나\n선택안: 1_가; 2_나 \n---\n본문",
                   os.path.join(tmp_path, "08_x.txt"))
    assert t.options == ["1_가", "2_나"]
    dtpl.save(t)
    assert dtpl.load(t.path).options == ["1_가", "2_나"]
    folder = paths.template_dir()
    t08 = next(x for x in dtpl.load_all(folder)[0] if x.file_name.startswith("08_"))
    opts, errors = dtpl.load_all(os.path.join(folder, dtpl.OPTION_DIR))
    assert not errors and len(t08.options) == 5 and len(opts) == 7
    t32 = next(x for x in dtpl.load_all(folder)[0] if x.file_name.startswith("32_"))
    t36 = next(x for x in dtpl.load_all(folder)[0] if x.file_name.startswith("36_"))
    assert sorted(t08.options + t32.options + t36.options) == [x.file_name for x in opts]   # 모든 선택안이 쓰인다
    assert t32.none_label == "소명대상 없음" and t08.none_label == "소명대상 없음"
    assert dtpl.parse(dtpl.dump(t32), t32.path).none_label == "소명대상 없음"
    assert dtpl.add_title_note("주택소유 심사 결과(26년 10월 입주자정기, 40차)", "소명대상 없음") == \
        "주택소유 심사 결과(26년 10월 입주자정기, 40차, 소명대상 없음)"
    assert all(not x.internal and "끝." in x.body for x in opts)
    assert t08.cycle == "매월"
    assert [k for k, _ in t08.date_fields()] == ["갱신월"]


def test_cycle_header(tmp_path):
    t = dtpl.parse("제목: 가\n수신자: 내부결재\n구분: 나\n주기: 매월\n---\n본문", os.path.join(tmp_path, "01_x.txt"))
    assert t.cycle == "매월"
    dtpl.save(t)
    assert dtpl.load(t.path).cycle == "매월"
    assert dtpl.parse("제목: 가\n---\n본문").cycle == "수시"
    items, _ = dtpl.load_all(paths.template_dir())
    monthly = {x.file_name[:2]: x for x in items if x.cycle == "매월" and x.file_name[:2].isdigit()}
    assert sorted(monthly) == ["05", "06", "07", "08", "14", "15", "16", "18", "24", "25", "26", "31", "32", "34"]
    bundles = {}
    for no, x in sorted(monthly.items(), key=lambda it: it[1].sort_key):
        bundles.setdefault(x.bundle, []).append(no)
    assert bundles == {"갱신계약": ["05", "06", "08", "14", "16", "34", "18", "24", "26", "25"], "주택소유 정기": ["31", "32"],
                       "임대조건 신고": ["15"], "예비입주자 순위안내": ["07"]}
    assert dtpl.parse(dtpl.dump(monthly["31"])).bundle == "주택소유 정기"
    others = {}
    for x in items:
        if x.cycle == "수시":
            others.setdefault(x.bundle, []).append(x.file_name[:2])
    assert others == {"예비입주자": ["01", "02", "03", "04", "33", "35"], "기타": ["19", "27", "28"],
                      "권리의무승계": ["21", "22", "23"], "가정어린이집": ["29", "30"], "중복입주": ["36"]}


def test_renewal_templates_share_first():
    """갱신계약 사전서류(영구·국민)와 갱신계약 체결안내: 1안 내부결재는 서식\\1안에 있다."""
    folder = paths.template_dir()
    items, _ = dtpl.load_all(folder)
    firsts, errors = dtpl.load_all(os.path.join(folder, dtpl.FIRST_DIR))
    assert not errors
    names = {x.file_name: x for x in firsts}
    renewal = [x for x in items if x.first]
    assert sorted(x.file_name[:2] for x in renewal) == ["05", "06", "16", "21"]   # 21: 권리의무승계 검색 결과 + 소명 안내
    assert not any(x.file_name.startswith("20_") for x in items)
    assert not any(x.file_name.startswith("17_") for x in items)
    assert not {"09", "10", "11", "12", "13"} & {x.file_name[:2] for x in items}
    for x in renewal:
        assert x.first in names and names[x.first].internal and not x.internal
    assert not any("내부결재" in x.file_name and "갱신계약 사전서류" in x.file_name for x in items)


def test_save_roundtrip(tmp_path):
    p = os.path.join(tmp_path, "01_테스트.txt")
    t = dtpl.parse("제목: 가\n수신자: 내부결재\n구분: 나\n---\n본문", p)
    dtpl.save(t)
    t2 = dtpl.load(p)
    assert (t2.title, t2.receiver, t2.group, t2.body, t2.internal) == ("가", "내부결재", "나", "본문", True)
    assert t2.label == "01. 테스트"


def test_rent_type_shows_only_matching_clause():
    t = "조건 {유형:영구임대=제10조|국민임대·공공임대·행복주택=제9조}에 따라"
    assert dtpl.fill(t, {"임대유형": "영구임대"}, {}) == "조건 제10조에 따라"
    for v in ("국민임대", "공공임대", "행복주택", "국민"):       # 국민: 예전에 저장한 값
        assert dtpl.fill(t, {"임대유형": v}, {}) == "조건 제9조에 따라"
    all_clauses = "조건 제10조(영구임대), 제9조(국민임대·공공임대·행복주택)에 따라"
    assert dtpl.fill(t, {}, {}) == all_clauses
    assert dtpl.fill(t, {"임대유형": "도시공사"}, {}) == all_clauses


def test_hwp_html_marks_each_table_once_with_font_size():
    body = "1. 표\n| 가 | 나 |\n| 1 | 2 |\n\n2. 둘째\n| 다 | 라 |\n| 3 | 4 |"
    html = dtpl.to_html(body, hwp=True)
    marks = dtpl.TABLE_MARK_RE.findall(html)
    assert [m[0] for m in marks] == ["1", "2"]
    assert all(int(pt) == dtpl.TABLE_PT for _, pt in marks)
    assert not dtpl.TABLE_MARK_RE.search(dtpl.to_html(body))     # 미리보기에는 표식이 없다


def test_choice_field_repeats_rows():
    t = dtpl.parse("제목: 계약체결 안내({선택:형별=36|46|51|59}형)\n수신자: 내부결재\n---\n"
                   "| 형별 | 동호 |\n| {선택값:형별} |  |\n  끝.")
    assert t.input_fields() == ["형별"] and t.input_kinds() == {"형별": "선택"}
    assert t.input_options() == {"형별": ["36", "46", "51", "59"]}
    v = {"입력:형별": "36, 51"}
    assert dtpl.fill(t.title, v, {}) == "계약체결 안내(36, 51형)"
    assert dtpl.fill(t.body, v, {}) == "| 형별 | 동호 |\n| 36 |  |\n| 51 |  |\n  끝."
    assert dtpl.fill(t.title, {}, {}) == "계약체결 안내({형별}형)"      # 안 고르면 빈칸 표시


def test_choice_from_complex_types():
    """{선택:형별=단지:평형|형}: 고를 것은 단지기본정보 평형, 넣는 모양은 형·면적·형별."""
    old = dict(dtpl.COMPLEX)
    try:
        dtpl.set_complex({"평형1": "46.89", "평형2": "51.93", "평형3": "", "관리소명": "광주양림2관리소"})
        t = dtpl.parse("제목: 모집 공고({선택:형별=단지:평형|형}㎡)\n수신자: 내부결재\n---\n"
                       "가. 모집형: {선택:형별=단지:평형|형별}\n| {선택값:형별|형} | {선택값:형별} |")
        assert t.input_options() == {"형별": ["46.89", "51.93"]} and t.input_kinds() == {"형별": "선택"}
        v = {"입력:형별": "51.93"}
        assert dtpl.fill(t.title, v, {}) == "모집 공고(51㎡)"
        assert dtpl.fill(t.body, v, {}).split("\n") == ["가. 모집형: 51형(전용면적 51.93㎡)", "| 51 | 51.93 |"]
        v = {"입력:형별": "46.89, 51.93"}
        assert dtpl.fill(t.title, v, {}) == "모집 공고(46, 51㎡)"
        assert dtpl.choice_label("51.93", "형") == "51형(51.93㎡)" and dtpl.choice_label("36", "형") == "36형"
    finally:
        dtpl.set_complex(old)


def test_recruit_notice_template():
    """35번 국민임대 예비입주자 모집 공고: 형별은 단지기본정보 평형에서 고른다."""
    t = next(x for x in dtpl.load_all(paths.template_dir())[0] if x.file_name.startswith("35_"))
    assert "{선택:형별=단지:평형|형}" in t.title and t.input_kinds()["형별"] == "선택"
    assert {"모집계획 문서번호", "모집인원", "기존인원"} <= set(t.input_fields())


def test_duplicate_occupancy_quarter():
    """36번 중복입주 결과 보고: 분기를 고르면 제목·본문에 들어가고 {중복입주링크} 자리가 있다."""
    import datetime as dt
    t = next(x for x in dtpl.load_all(paths.template_dir())[0] if x.file_name.startswith("36_"))
    assert t.input_kinds().get("분기") == "선택" and t.input_options()["분기"] == ["1", "2", "3", "4"]
    assert t.uses("중복입주링크")
    v = {"입력:연도": "2026", "입력:분기": "2", "중복입주링크": "주거복지실-1737(2026.07.22.)"}
    title = dtpl.fill(t.title, v, {})
    assert dtpl.add_title_note(title, t.none_label) == "2026년 2분기 임대주택 중복입주 결과 보고(소명대상 없음)"
    assert t.options == ["7_중복입주에 따른 소명 안내(분기 정기)"]
    opt = next(x for x in dtpl.load_all(os.path.join(paths.template_dir(), dtpl.OPTION_DIR))[0]
               if x.file_name == t.options[0])
    assert not opt.internal and "{이름}" in opt.receiver
    letter = dtpl.fill(opt.body, {**VALUES, **v}, {"제출기한": dt.date(2026, 12, 2)})
    assert "2026년 2분기 중복입주 검색 결과" in letter and "{" not in letter
    body = dtpl.fill(t.body, v, {"등본요청월": dt.date(2026, 7, 1)})
    assert "1. 주거복지실-1737(2026.07.22.)호 관련 내용입니다." in body
    assert "2026년 2분기 중복입주결과내역" in body and "2026년 7월 등본요청내역" in body


def test_record_token():
    """{기록:총계=0}: 자격검증 기록 값이 있으면 그 값, 없으면 = 뒤 값."""
    assert dtpl.fill("| {기록:총계=0} | {기록:세대주=0} |", {"기록:총계": "69"}, {}) == "| 69 | 0 |"
    t = next(x for x in dtpl.load_all(paths.template_dir())[0] if x.file_name.startswith("08_"))
    assert "{기록:총계=0}" in t.body and dtpl.RECORD_PREFIX in t._all_text()


def test_important_dates_red():
    """기한·기간·까지 등이 있는 줄의 날짜, '~' 기간은 빨간 글씨. 그 밖의 날짜는 그대로."""
    import doc_template as dt_
    red = 'color="#FF0000"'
    h = dt_.to_html("  나. 제출기한: 2026. 11. 30.(월)까지")
    assert red in h and "2026.11.30.(월)까지</span></font>" in h
    assert red not in dt_.to_html("  가. 제출서류: 2026. 11. 1.(안내문 시행일) 이후 발급분")
    assert red in dt_.to_html("접수: 2026. 11. 1. ~ 2026. 11. 30.")
    assert red in dt_.to_html("  나. 제출기한: 2026. 11. 30.(월)까지", hwp=True)
    t = dt_.to_html("| 구분 | 납부기한 |\n| 1회 | 2026.8.25 |\n| 비고 | 2026.9.1 |")
    assert t.count(red) == 2


def test_internal_no_red():
    """내부결재(emph=False)는 빨간 글씨 없이."""
    import doc_template as dt_
    h = dt_.to_html("  나. 제출기한: 2026. 11. 30.(월)까지", hwp=True, emph=False)
    assert "FF0000" not in h and "2026.11.30.(월)까지" in h


def test_dates_kept_on_one_line():
    """본문 날짜는 띄어쓰기 없이 붙여 줄이 나뉘지 않게(2026. 11. 12. → 2026.11.12.)."""
    import doc_template as dt_
    h = dt_.to_html("1. 주거복지실-2404(2026.10.14.) 호와 범정부 자동연계 조사완료일(2026. 11. 12.) 건 관련입니다.", hwp=True)
    assert "(2026.11.12.)" in h and "2026. 11." not in h
    assert dt_.keep_dates_together("1. 2. 3.") == "1. 2. 3."
    assert dt_.keep_dates_together("2026. 11. 까지") == "2026.11. 까지"
