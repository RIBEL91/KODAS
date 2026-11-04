import proofread as pr


def rules(changes):
    return {r for r, _, _ in changes}


def test_dates_times_money():
    body = ("1. 점검일: 2026.10.8 (목) 오후 2시 30분\n"
            "2. 기한: 2026-11-02, 14시 05분까지\n"
            "3. 비용: 금 1250000원\n"
            "4. 이미 맞는 날짜 2026. 10. 8.(목) 09:00  끝.")
    new, ch = pr.fix(body)
    assert "2026. 10. 8.(목) 14:30" in new
    assert "2026. 11. 2., 14:05까지" in new
    assert "금1,250,000원(금일백이십오만원)" in new
    assert new.endswith("2026. 10. 8.(목) 09:00  끝.")
    assert {"날짜 표기", "시간 표기(24시각)", "금액 쉼표", "금액 한글 병기"} <= rules(ch)


def test_won_hangul():
    assert pr.won_hangul(113560) == "일십일만삼천오백육십"
    assert pr.won_hangul(1000000) == "일백만"
    assert pr.won_hangul(120000000) == "일억이천만"


def test_item_numbers_and_spaces():
    body = ("1. 관련: 가나관리소-1234\n"
            "3.점검 결과를 보고합니다.\n"
            "  가. 일시: 2026. 10. 8.\n"
            "  다. 장소: 관리사무소\n"
            "    1) 첫째\n"
            "    3) 둘째\n"
            "4. 기타\n"
            "  가. 다시 처음\n"
            "\n"
            "붙임  1. 점검표 1부\n"
            "      3. 사진 1부")
    new, ch = pr.fix(body)
    lines = new.split("\n")
    assert lines[1] == "2. 점검 결과를 보고합니다."
    assert lines[3] == "  나. 장소: 관리사무소"
    assert lines[5] == "    2) 둘째"
    assert lines[6] == "3. 기타"
    assert lines[7] == "  가. 다시 처음"
    assert lines[9] == "붙임  1. 점검표 1부."            # 붙임 번호는 건드리지 않는다
    assert lines[10] == "      3. 사진 1부.  끝."
    assert "항목 번호 차례" in rules(ch) and "항목 기호 뒤 띄어쓰기" in rules(ch)


def test_end_mark_and_attach():
    assert pr.fix("보고합니다.")[0] == "보고합니다.  끝."
    assert pr.fix("보고합니다 끝")[0] == "보고합니다  끝."
    assert pr.fix("붙임: 명단 1부 끝.")[0] == "붙임  명단 1부.  끝."
    assert pr.fix("| 구분 | 내용 |\n| 가 | 나 |")[0].endswith("| 가 | 나 |\n끝.")
    ok = "1. 안내합니다.\n\n붙임  안내문 1부.  끝."
    assert pr.fix(ok) == (ok, [])                              # 맞는 문서는 그대로
    assert pr.fix("※ 문의: 담당자(☎ 062-000-0000)  끝.") == ("※ 문의: 담당자(☎ 062-000-0000)  끝.", [])


def test_terms_and_protected_fields():
    body = "상기 건은 익일까지 제출하며, 법 제3조에 의거하여 처리합니다. 금일십만원\n{날짜:점검일} {입력:금액}원 [문서링크: 가나관리소-2026.10]  끝."
    new, ch = pr.fix(body)
    assert new.startswith("위 건은 다음 날까지 제출하며, 법 제3조에 따라 처리합니다. 금일십만원")
    assert "{날짜:점검일} {입력:금액}원 [문서링크: 가나관리소-2026.10]" in new
    assert "행정용어 순화" in rules(ch)
    assert pr.fix("이를 상기시키기 위해 하기 쉬운 일입니다.  끝.")[1] == []   # '상기시키다'·'하기'는 그대로


def test_title():
    t, ch = pr.fix_title("2026.10.8  승강기 점검 결과 보고.")
    assert t == "2026. 10. 8. 승강기 점검 결과 보고" and ch
    assert pr.fix_title("승강기 점검 결과 보고(2026. 10.)")[1] == []
