import os

import pytest

import privacy

DOC = """수신자 105동 814호 홍길동 귀하
제 목 임대차계약 갱신 안내(105동 814호)

1. 귀 세대의 계약 만료(2026. 12. 31.)에 따라 갱신 계약을 안내합니다.
2. 대상자: 김영희 (연락처 010-1234-5678)
3. 동호수: 106-1203, 주민등록번호 800101-1234567
4. 문의: 관리사무소 062-571-0000, 담당자 이순신 010 9876 5432
  - 관리소장님께 보고, 입주자 귀하, 세대주 님

| 동호 | 성명 | 비고 |
| 105동 814호 | 홍길동 | 갱신 |
"""


def test_find_private_kinds():
    found = privacy.find_private(DOC, keep_phones=("062-571-0000",))
    got = {s: kind for s, _, kind in found}
    assert got["105동 814호"] == "동호수"
    assert got["홍길동"] == "이름" and got["김영희"] == "이름" and got["이순신"] == "이름"
    assert got["010-1234-5678"] == "연락처" and got["010 9876 5432"] == "연락처"
    assert got["106-1203"] == "동호수" and got["800101-1234567"] == "주민번호"
    assert "062-571-0000" not in got                       # 관리소 대표번호는 남긴다
    for word in ("관리소장", "입주자", "세대주", "담당자"):  # 호칭·직함은 이름이 아니다
        assert word not in got


def test_mask_text_and_extra():
    out, found = privacy.mask_text(DOC, extra=("갱신",), keep_phones=("062-571-0000",))
    for gone in ("홍길동", "김영희", "이순신", "105동 814호", "010-1234-5678", "800101-1234567", "106-1203"):
        assert gone not in out, gone
    assert "000동 000호 000 귀하" in out and "대상자: 000" in out
    assert "000-0000-0000" in out and "000000-0000000" in out
    assert "062-571-0000" in out and "관리소장님" in out
    assert "| 000동 000호 | 000 | 000 |" in out                # 직접 넣은 글자('갱신')도 가린다


def test_mask_html_keeps_tags():
    html = ('<p style="x">수신자 105동&nbsp;814호 <b>홍길동</b> 귀하</p>'
            '<td>성명: 김영희</td><td>010-1234-5678</td>')
    out, found = privacy.mask_html(html)
    assert '<p style="x">' in out and "<b>000</b>" in out
    assert "홍길동" not in out and "김영희" not in out and "010-1234-5678" not in out
    assert "814호" not in out


def _make_pdf(path, lines):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    font = r"C:\Windows\Fonts\malgun.ttf"
    y = 72
    for line in lines:
        page.insert_text((60, y), line, fontname="malgun", fontfile=font, fontsize=11)
        y += 20
    doc.save(path)
    doc.close()


def test_mask_pdf(tmp_path):
    src, dst = str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")
    _make_pdf(src, ["수신자 105동 814호 홍길동 귀하", "대상자: 김영희 010-1234-5678",
                    "관리사무소 062-571-0000", "표: 홍길동 갱신 완료"])
    res = privacy.mask_pdf(src, dst, keep_phones=("062-571-0000",))
    text = privacy.pdf_text(dst)
    for gone in ("홍길동", "김영희", "814호", "010-1234-5678"):
        assert gone not in text, gone
    assert "062-571-0000" in text and "000" in text
    assert res["masked"] >= 5 and res["scanned"] == 0 and res["kinds"]["이름"] >= 3
    assert os.path.getsize(dst) > 0


def test_mask_pdf_known_and_scanned(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    src, dst = str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")
    _make_pdf(src, ["참석: 박민수, 최지우"])
    # 본문에서 이미 찾은 이름(박민수)은 첨부 PDF에서도 가린다
    res = privacy.mask_pdf(src, dst, known=[("박민수", "000", "이름")], extra=("최지우",))
    text = privacy.pdf_text(dst)
    assert "박민수" not in text and "최지우" not in text and res["masked"] == 2
    empty = str(tmp_path / "scan.pdf")
    d = pymupdf.open()
    d.new_page()
    d.save(empty)
    d.close()
    assert privacy.mask_pdf(empty, str(tmp_path / "scan2.pdf"))["scanned"] == 1


def test_no_false_names():
    for text, want in (("105동 814호 민원 처리", "000동 000호 민원 처리"),
                       ("105동 814호 누수 관련", "000동 000호 누수 관련"),
                       ("101동 202호 거주자", "000동 000호 거주자"),
                       ("101동 202호 세대 방문", "000동 000호 세대 방문"),
                       ("101동 202호(홍길동)", "000동 000호(000)"),
                       ("고객님 안녕하세요", "고객님 안녕하세요"),
                       ("점검 결과 010-1111-2222", "점검 결과 000-0000-0000")):
        assert privacy.mask_text(text)[0] == want, text


def test_locked_and_scanned_attachments(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    import collector
    got = tmp_path / "got"
    got.mkdir()
    d = pymupdf.open()
    d.new_page().insert_text((50, 72), "대상자: 홍길동", fontname="malgun",
                             fontfile=r"C:\Windows\Fonts\malgun.ttf", fontsize=11)
    d.save(str(got / "잠김.pdf"), encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y")
    d.close()
    d = pymupdf.open()
    d.new_page()
    d.save(str(got / "스캔.pdf"))
    d.close()
    res = collector.mask_attachments([str(got / "잠김.pdf"), str(got / "스캔.pdf")], str(tmp_path / "첨부"),
                                     log=lambda m: None)
    names = sorted(os.listdir(tmp_path / "첨부"))
    assert names == ["스캔 (스캔본·가리지 못함).pdf", "잠김 (암호·가리지 못함).pdf"]
    assert res["locked"] == ["잠김 (암호·가리지 못함).pdf"] and res["scanned"] == ["스캔 (스캔본·가리지 못함).pdf"]
    assert not os.listdir(got)
