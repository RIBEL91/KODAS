import datetime as dt
import os
import re

import doc_template as dtpl
import paths

D = dt.date(2026, 11, 6)   # 금요일
VALUES = {"이름": "홍길동", "주소": "101동 1001호", "관리소": "가나관리소",
          "단지명": "가나1단지", "담당자": "김담당", "전화번호": "031-000-0000", "세대수": "25",
          "문서링크": "주거복지실-2044(2026.09.03.)", "심사결과링크": "가나관리소-1700(2026. 9. 10.)",
          "소명안내링크": "가나관리소-1701(2026. 9. 10.)"}


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
    assert "가. 표" in html and "margin-left:" in html          # 들여쓰기는 왼쪽 여백(내어쓰기)으로
    assert "【문단:" in dtpl.to_html("  가. 표", hwp=True)      # 웹한글용은 문단 표식
    assert html.index("붙임") > html.index("</table>")


def test_bundled_templates_all_render():
    items, errors = dtpl.load_all(paths.template_dir())
    assert not errors
    assert len([t for t in items if t.file_name[:2].isdigit()]) == 25    # 임대 서식(오영철)
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
    assert t14.uses("심사결과링크") and t14.uses("소명안내링크")


def test_options_header_and_folder(tmp_path):
    t = dtpl.parse("제목: 가\n수신자: 내부결재\n구분: 나\n선택안: 1_가; 2_나 \n---\n본문",
                   os.path.join(tmp_path, "08_x.txt"))
    assert t.options == ["1_가", "2_나"]
    dtpl.save(t)
    assert dtpl.load(t.path).options == ["1_가", "2_나"]
    folder = paths.template_dir()
    t08 = next(x for x in dtpl.load_all(folder)[0] if x.file_name.startswith("08_"))
    opts, errors = dtpl.load_all(os.path.join(folder, dtpl.OPTION_DIR))
    assert not errors and len(t08.options) == 5 and len(opts) == 6
    t32 = next(x for x in dtpl.load_all(folder)[0] if x.file_name.startswith("32_"))
    assert sorted(t08.options + t32.options) == [x.file_name for x in opts]   # 모든 선택안이 쓰인다
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
    assert sorted(monthly) == ["05", "06", "07", "08", "14", "15", "16", "18", "24", "25", "26", "31", "32"]
    bundles = {}
    for no, x in sorted(monthly.items(), key=lambda it: it[1].sort_key):
        bundles.setdefault(x.bundle, []).append(no)
    assert bundles == {"갱신계약": ["05", "06", "08", "14", "16", "18", "24", "26", "25"], "주택소유 정기": ["31", "32"],
                       "임대조건 신고": ["15"], "예비입주자 순위안내": ["07"]}
    assert dtpl.parse(dtpl.dump(monthly["31"])).bundle == "주택소유 정기"
    others = {}
    for x in items:
        if x.cycle == "수시":
            others.setdefault(x.bundle, []).append(x.file_name[:2])
    assert others == {"예비입주자": ["01", "02", "03", "04"], "기타": ["19", "27", "28"],
                      "권리의무승계": ["21", "22", "23"], "가정어린이집": ["29", "30"]}


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
