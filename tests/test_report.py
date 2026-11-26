import datetime as dt

from PIL import Image

import evidence_fetch as ef
import hwp_report as hr
import page_images as pi
import quality_draft as qd
import quality_eval as qe


def test_volume_of():
    assert qe.volume_of("유지관리") == 1
    assert qe.volume_of("운영관리") == 2
    assert qe.volume_of("주민참여및공동체활성화") == 3
    assert qe.volume_of("단지특성") == 3
    assert qe.volume_of("가감점") == 3
    assert qe.volume_of("임대운영") == 4
    assert qe.volume_of("본.지사업무협조도") == 4


def test_join_caps():
    assert hr._join_caps([("a", "계획 문서 - 1"), ("b", "계획 문서 - 2")]) == "계획 문서 - 1~2"
    assert hr._join_caps([("a", "공문")]) == "공문"
    assert hr._join_caps([("a", "공문"), ("b", "사진")]) == "공문 / 사진"


def test_take_unit_pairs_portraits(tmp_path):
    por = []
    for i in range(3):
        p = tmp_path / f"p{i}.png"
        Image.new("RGB", (100, 141), "white").save(p)
        por.append((str(p), f"문서 - {i + 1}"))
    land = tmp_path / "l.png"
    Image.new("RGB", (200, 100), "white").save(land)
    q = por + [(str(land), "화면")]
    work = tmp_path / "w"
    work.mkdir()
    wide = {"w": 173, "h": 111}
    pics, cols, rows = hr._take_unit(q, wide, str(work))   # 세로 쪽 2장 나란히(칸을 나눠 각각)
    assert [c for _p, c in pics] == ["문서 - 1", "문서 - 2"] and (cols, rows) == (2, 1) and len(q) == 2
    pics, cols, rows = hr._take_unit(q, wide, str(work))   # 남은 세로 1장 + 공란
    assert pics[0][1] == "문서 - 3" and pics[1][0] is None and len(q) == 1
    pics, cols, rows = hr._take_unit(q, wide, str(work))   # 가로 화면은 그대로
    assert pics == [(str(land), "화면")] and (cols, rows) == (1, 1) and not q


def test_take_unit_single_landscape_tall(tmp_path):
    land = tmp_path / "l.png"
    Image.new("RGB", (400, 30), "white").save(land)
    work = tmp_path / "w"
    work.mkdir()
    tall = {"w": 173, "h": 230}
    q = [(str(land), "화면")]
    pics, cols, rows = hr._take_unit(q, tall, str(work))   # 큰 칸에 가로 1장: 위에 넣고 아래는 공란
    assert pics == [(str(land), "화면"), (None, pi.BLANK)] and (cols, rows) == (1, 2) and not q


def test_compose_size(tmp_path):
    p = tmp_path / "a.png"
    Image.new("RGB", (100, 141), "red").save(p)
    out = pi.compose([(str(p), "x"), (None, pi.BLANK)], 2, 1, str(tmp_path / "o.png"), 173 / 111)
    w, h = Image.open(out).size
    assert abs(w / h - 173 / 111) < 0.01


def test_plan_and_find_doc():
    it = qe.Item(row=1, part="임대운영", area="", indicator="", no="1-1", seq=1, text="t",
                 basis="모집공고계획수립-104(26.01.15) 계획 수립 안내 / 화면 캡처")
    refs, years = ef.plan([it], 2026)
    assert years == {2026}
    ref = refs[id(it)][0]
    docs = {2026: [qd.Doc(seq=104, number="광주양림2관리소-104", title="계획 수립 안내", date=dt.date(2026, 1, 15)),
                   qd.Doc(seq=105, number="광주양림2관리소-105", title="다른 문서", date=dt.date(2026, 1, 15))]}
    assert ef.find_doc(docs, ref).number == "광주양림2관리소-104"


def test_custom_foldering(tmp_path):
    """내가 만든 폴더링: 번호 폴더(+ 'k.' 항목 폴더)를 찾아 증빙으로. 같은 번호는 'N권' 폴더로 가른다."""
    def mk(*parts, files=("a.pdf",)):
        d = tmp_path.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            (d / f).write_bytes(b"x")
    mk("4권 임대운영", "1-1 임대차", "1. 계약서", files=("계약.pdf", "b.jpg"))
    mk("4권 임대운영", "1-1 임대차", "2. 갱신")
    mk("1권", "1-1")                                        # 1권 1-1: 항목 폴더 없이 번호 폴더에 바로
    mk("4권 임대운영", "1-2")
    its = [qe.Item(1, "임대운영", "", "", "1-1", 1, "계약"), qe.Item(2, "임대운영", "", "", "1-1", 2, "갱신"),
           qe.Item(3, "유지관리", "", "", "1-1", 1, "시설"), qe.Item(4, "유지관리", "", "", "1-1", 2, "점검"),
           qe.Item(5, "임대운영", "", "", "1-2", 1, "입주"), qe.Item(6, "임대운영", "", "", "1-3", 1, "없음")]
    found = qe.scan_custom(str(tmp_path), its)
    assert found[(4, "1-1", 1)].endswith("1. 계약서")
    assert found[(4, "1-1", 2)].endswith("2. 갱신")
    assert found[(1, "1-1", 1)].endswith("1-1") and "1권" in found[(1, "1-1", 1)]
    assert (1, "1-1", 2) not in found                       # 번호 폴더는 첫 항목에만
    assert (4, "1-3", 1) not in found
    assert len(its[0].evidence) == 2 and len(its[4].evidence) == 1 and its[5].evidence == []
