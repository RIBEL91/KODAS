import csv
import json

import binder_rules
import collector
import doc_template as dtpl

# 홈넷 [문서정보] 창(편철.png)의 글자 모양
DOC_INFO = """문서정보
기본정보
제목\t대한결핵협회 예방 교육 실시(외부기관 )
기안자\t권창호/5급대우/광주쌍촌관리소\t기안부서\t광주쌍촌관리소
문서번호\t광주쌍촌관리소-3527\t기안일자\t2025.12.31.
문서상태\t내부완료\t보안문서\t비설정
보안등급\t3등급[전체열람]\t비공개등급\t공개
편철\t교육훈련관계철(1)
평가구분\t없음
수신자\t
키워드\t
"""

EDU = """수신자 내부결재
(경유)
제 목 대한결핵협회 예방 교육 실시(외부기관)

1. 직원 결핵 예방 교육을 아래와 같이 실시하고자 합니다.
  가. 일시: 2025. 12. 31.(수) 14:00
  나. 장소: 관리사무소 회의실

붙임  교육자료 1부.  끝.
"""

LEASE = """수신자 105동 814호 홍길동 귀하
(경유)
제 목 임대차계약 갱신 안내

1. 귀 세대의 계약 만료에 따라 갱신 계약을 안내합니다.

붙임  갱신 안내문 1부.  끝.
"""


def test_parse_doc_info_from_screen():
    info = collector.parse_doc_info(DOC_INFO)
    assert info["binder_raw"] == "교육훈련관계철(1)" and info["binder"] == "교육훈련관계철"
    assert info["doc_no"] == "광주쌍촌관리소-3527" and info["date"] == "2025.12.31."


def test_area_rules():
    assert binder_rules.area_for("교육훈련관계철(1)") == "주택관리"
    assert binder_rules.area_for("임대보증금관계철") == "임대"
    assert binder_rules.area_for("시설관리관계철") == "시설"
    assert binder_rules.area_for("승강기관리철") == "시설"
    assert binder_rules.area_for("주거복지관계철") == "주거복지"
    assert binder_rules.area_for("경비용역계약철") == "주택관리"         # '계약'이 있어도 용역은 주택관리
    assert binder_rules.area_for("", "입주민 간담회 실시 안내") == "주거복지"   # 편철 없으면 제목으로
    assert binder_rules.area_for("", "알 수 없는 제목", "시설") == "시설"


def test_binder_filter():
    assert binder_rules.matches("교육훈련관계철", [])
    assert binder_rules.matches("교육훈련관계철(1)", ["교육 훈련", "시설"])
    assert not binder_rules.matches("임대보증금관계철", ["교육훈련"])
    assert not binder_rules.matches("", ["교육훈련"])


def _collected(out, name, text, binder):
    (out / f"{name}.txt").write_text(text, encoding="utf-8")
    meta = {"제목": name, "편철": binder, "편철원문": f"{binder}(1)" if binder else "",
            "문서번호": "광주쌍촌관리소-1", "기안일자": "2025.12.31.",
            "분야": binder_rules.area_for(binder, name)}
    (out / f"{name}.meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (out / "PDF").mkdir(exist_ok=True)
    (out / "PDF" / f"{name}.pdf").write_bytes(b"%PDF-1.4 test")


def test_auto_area_and_binder_folders(tmp_path):
    out, dest = tmp_path / "수집", tmp_path / "서식" / dtpl.COLLECTED_DIR
    out.mkdir()
    _collected(out, "대한결핵협회 예방 교육 실시", EDU, "교육훈련관계철")
    _collected(out, "임대차계약 갱신 안내", LEASE, "임대보증금관계철")
    _collected(out, "편철 없는 입주민 간담회 안내", EDU.replace("결핵", "간담회"), "")
    names = ["대한결핵협회 예방 교육 실시", "임대차계약 갱신 안내", "편철 없는 입주민 간담회 안내"]

    groups = collector.organize_by_binder(str(out), names, log=lambda m: None)
    assert set(groups) == {"교육훈련관계철", "임대보증금관계철", collector.NO_BINDER}
    assert (out / "편철별" / "교육훈련관계철" / "대한결핵협회 예방 교육 실시.pdf").is_file()
    assert (out / "편철별" / "임대보증금관계철" / "임대차계약 갱신 안내.pdf").is_file()
    assert not list((out / "편철별").rglob("*.txt"))          # 가리지 않은 원문은 편철별 폴더에 넣지 않는다
    with open(out / "편철별_목록.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert [r["편철"] for r in rows] == ["교육훈련관계철", "임대보증금관계철", collector.NO_BINDER]
    assert rows[0]["문서번호"] == "광주쌍촌관리소-1" and rows[0]["분야"] == "주택관리"

    made = collector.import_to_templates(str(out), names, str(dest), log=lambda m: None, area=binder_rules.AUTO)
    items, errors = dtpl.load_all(str(dest))
    assert not errors and len(made) == 3
    got = {t.bundle: t.area for t in items}
    assert got["편철 · 교육훈련관계철"] == "주택관리"
    assert got["편철 · 임대보증금관계철"] == "임대"
    assert got["수집한 서식"] == "주거복지"                      # 편철이 없으면 제목(간담회)으로 분야
    lease = next(t for t in items if t.area == "임대")
    assert "홍길동" not in lease.body + lease.receiver and lease.uses("이름")
