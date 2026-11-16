import json
import os

import collector
import doc_template as dtpl

SAMPLE = """주 택 관 리 공 단
수신자 내부결재
(경유)
제 목 승강기 자체점검 결과 보고(105동 814호 민원 포함)

1. 관련: 광주우산3관리소-1234(2026. 10. 2.)
2. 2026년 10월 승강기 자체점검을 아래와 같이 실시하였기에 보고합니다.
  가. 점검일: 2026. 10. 15.(목)
  나. 점검업체: (주)한빛엘리베이터
  다. 비용: 1,250,000원
  라. 문의: 홍길동 010-1234-5678

붙임  점검표 1부.  끝.
"""


def test_safe_name_and_meta():
    used = set()
    assert collector.safe_name('보고: 결과/정리?', 1, used) == "보고 결과 정리"
    assert collector.safe_name('보고: 결과/정리?', 2, used) == "보고 결과 정리 (2)"
    assert collector.safe_name("", 7, used) == "007"
    meta = collector.extract_meta(SAMPLE)
    assert meta["internal"] and meta["title"].startswith("승강기 자체점검 결과 보고")
    assert not collector.other_receiver(meta)
    assert collector.other_receiver({"receiver": "광주광역시 북구청장", "title": "", "internal": False})


def test_parse_doc_info_binder():
    info = collector.parse_doc_info("[cabinetName] 시설관리관계철(2)\n구분 : 생산")
    assert info["binder"] == "시설관리관계철" and info["kind"] == "생산"
    info = collector.parse_doc_info("편철\n임대보증금관계철(1)\n구분 접수")
    assert info["binder"] == "임대보증금관계철" and info["kind"] == "접수"


def test_from_collected_anonymizes_and_parses(tmp_path):
    dtpl.KNOWN_INFO = {"관리소": "광주우산3관리소", "단지명": "", "담당자": "", "전화번호": ""}
    try:
        src = tmp_path / "승강기 자체점검 결과 보고.txt"
        src.write_text(SAMPLE, encoding="utf-8")
        (tmp_path / "승강기 자체점검 결과 보고.meta.json").write_text(
            json.dumps({"편철": "시설관리관계철"}, ensure_ascii=False), encoding="utf-8")
        text = dtpl.from_collected(SAMPLE, str(src), "시설")
    finally:
        dtpl.KNOWN_INFO = {}
    t = dtpl.parse(text, str(src))
    assert t.area == "시설" and t.bundle == "편철 · 시설관리관계철" and t.internal
    assert "시설관리관계철" in t.memo
    assert "{주소}" in t.title                                   # 105동 814호 → {주소}
    for gone in ("홍길동", "010-1234-5678", "1,250,000", "한빛엘리베이터", "-1234", "2026. 10. 15."):
        assert gone not in t.body, gone
    assert "{관리소}-0000" in t.body and "0,000,000원" in t.body
    assert "{날짜:" in t.body and t.body.rstrip().endswith("끝.")
    assert dict(t.date_fields())                                  # 날짜 칸이 입력칸으로 잡힌다
    assert dtpl._anonymize("연락처 062-123-4567", {}) == "연락처 {입력:연락처}"   # 이름이 아닌 말은 둔다
    assert "{입력:연락처}" in t.body and "000 {입력:연락처}" in t.body           # 문의: 홍길동 010-… → 000
    assert "연락처" in t.input_fields()                                          # 연락처 입력칸이 생긴다


PERSON = """수신자 105동 814호 홍길동 귀하
(경유)
제 목 임대차계약 갱신 안내

1. 귀 세대(105동 814호)의 계약 만료에 따라 갱신 계약을 안내합니다.
2. 대상자: 홍길동 (연락처 010-2222-3333)
3. 문의: 관리사무소 062-571-0000

붙임  갱신 안내문 1부.  끝.
"""


def test_from_collected_person_fields(tmp_path):
    """받는 분이 있는 문서: 이름·동호수·연락처가 입력칸이 되고, 관리소 번호는 {전화번호}로."""
    dtpl.KNOWN_INFO = {"관리소": "", "단지명": "", "담당자": "", "전화번호": "062-571-0000"}
    try:
        src = tmp_path / "갱신 안내.txt"
        src.write_text(PERSON, encoding="utf-8")
        t = dtpl.parse(dtpl.from_collected(PERSON, str(src), "임대"), str(src))
    finally:
        dtpl.KNOWN_INFO = {}
    assert not t.internal and t.receiver == "{주소} {이름} 귀하"
    assert t.uses("이름") and t.uses("주소") and "연락처" in t.input_fields()
    assert "대상자: {이름}" in t.body and "{전화번호}" in t.body
    for gone in ("홍길동", "105동", "010-2222-3333", "062-571-0000"):
        assert gone not in t.body + t.receiver, gone


def test_attach_names_and_masked_pdf_html():
    names = collector.attach_names("첨부 1. 점검표(105동).pdf (120KB)\n2. 사진대지.hwp\n점검표(105동).pdf")
    assert names == ["점검표(105동).pdf", "사진대지.hwp"]
    html, found = collector.masked_pdf_html("<p>수신자 105동 814호 <b>홍길동</b> 귀하</p>", "", "제목")
    assert "홍길동" not in html and "<b>000</b>" in html and "000동 000호" in html
    html, _ = collector.masked_pdf_html("", "대상자: 김영희 010-1234-5678", "제목<1>")
    assert "김영희" not in html and "000-0000-0000" in html and "제목&lt;1&gt;" in html


def test_mask_attachments_and_zip(tmp_path):
    import zipfile
    pymupdf = __import__("pytest").importorskip("pymupdf")
    got = tmp_path / "got"
    got.mkdir()
    pdf = got / "명단.pdf"
    d = pymupdf.open()
    d.new_page().insert_text((50, 72), "대상자: 홍길동 010-1234-5678", fontname="malgun",
                             fontfile=r"C:\Windows\Fonts\malgun.ttf", fontsize=11)
    d.save(str(pdf))
    d.close()
    z = got / "전체.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(pdf, "안의파일.pdf")
        zf.writestr("메모.txt", "x")
    res = collector.mask_attachments([str(pdf), str(z)], str(tmp_path / "첨부"), log=lambda m: None)
    assert res["pdf"] == 2 and res["masked"] >= 4 and res["other"] == ["메모.txt"]
    assert not pdf.exists() and not z.exists()                  # 가리기 전 원본은 남기지 않는다
    import privacy
    for f in ("명단.pdf", "안의파일.pdf"):
        text = privacy.pdf_text(str(tmp_path / "첨부" / f))
        assert "홍길동" not in text and "010-1234-5678" not in text and "000" in text


def test_import_to_templates(tmp_path):
    out, dest = tmp_path / "수집", tmp_path / "서식" / dtpl.COLLECTED_DIR
    out.mkdir()
    (out / "승강기 자체점검 결과 보고(105동 814호 민원 포함).txt").write_text(SAMPLE, encoding="utf-8")
    made = collector.import_to_templates(str(out), ["승강기 자체점검 결과 보고(105동 814호 민원 포함)"],
                                         str(dest), log=lambda m: None, area="주택관리")
    again = collector.import_to_templates(str(out), ["승강기 자체점검 결과 보고(105동 814호 민원 포함)"],
                                          str(dest), log=lambda m: None)
    assert len(made) == 1 and len(again) == 1 and made[0] != again[0]     # 덮어쓰지 않고 (2)를 붙인다
    assert "105동" not in os.path.basename(made[0])                        # 파일 이름에도 동호가 남지 않는다
    items, errors = dtpl.load_all(str(dest))
    assert not errors and len(items) == 2 and all(t.area == "주택관리" for t in items)


def test_cut_footer_sender_and_signature():
    lines = ["1. 본문입니다.", "2. 계속 안내합니다.", "", "| 주택관리공단 가나관리소장 | < |",
             "| 과장 | 홍길동 | 관리소장 | 전결 |", "| 시행 | 가나관리소-1234 | 접수 | |", "| 전화 | 062-000-0000 | 전송 | |"]
    assert dtpl._cut_footer(lines) == ["1. 본문입니다.", "2. 계속 안내합니다."]
    body = ["1. 표입니다.", "| 구분 | 내용 |", "| 시설 | 점검 |", "붙임  1부.  끝."]
    assert dtpl._cut_footer(body) == body                       # 보통 표는 그대로


def test_similar_key_ignores_dates_months_and_units():
    k = collector.similar_key
    assert k("사회복무요원 급여 지급(2025.12월분)") == k("사회복무요원 급여 지급(2025.11월분)")
    assert k("사회복무요원 직무교육 실시보고(25.12)") == k("사회복무요원 직무교육 실시보고(25.11)")
    assert k("임대(전환)보증금 수지 현황 보고(2025년11월)") == k("임대(전환)보증금 수지 현황 보고(2025년 11월)")
    assert k("계약 해지(104동 1306호)") == k("계약 해지(101동 1411호)") == k("계약 해지(OOO동 OOO호)")
    assert k("납부최고 1차") != k("납부최고 2차")
    assert k("사회복무요원 급여 지급(2025.12월분)") != k("사회복무요원 직무교육 실시보고(25.12)")


def test_mask_secure_doc_uses_ooo():
    doc = {"text": "제  목\n계약 해지(104동 1306호)\n계약자: 홍길동 연락처 010-1234-5678", "html": ""}
    out = collector._mask_secure_doc(doc)
    assert "홍길동" not in out["text"] and "1306" not in out["text"] and "5678" not in out["text"]
    assert "OOO동 OOO호" in out["text"] and "OOO-OOOO-OOOO" in out["text"]
