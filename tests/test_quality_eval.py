"""품질평가 평가표: 항목 읽기, 점수·근거 저장(수식·다른 칸 유지), 증빙 폴더."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import quality_eval as qe  # noqa: E402


def _sheet(path):
    from openpyxl import Workbook
    wb = Workbook()
    s = wb.active
    s.title = "총괄표"
    s["F13"] = "=SUM(항목별평가표!G8:G11)"
    ws = wb.create_sheet("항목별평가표")
    ws["A3"] = "○ 단지명 :  "
    ws["F7"] = "=SUM(F8:F20)"
    rows = [
        (8, "유지\n관리\n(27)", "시설물\n관리", "입·퇴거", "1-1", "◦ 입·퇴거시 서류 작성 유무", 2, "• 체크 서류"),
        (9, None, None, None, None, "[평가기준]\n - 입주시(1)", None, None),
        (10, None, None, "수선유지", "1-3", "◦ 수선유지대장", 1, ""),
        (12, None, None, None, None, "◦ COTIS 입력", 2, ""),
        (14, "임대운영\n(18)", None, "예비입주자", "1-1", "◦ 예비입주자 모집인원 산정", 1, ""),
        (16, None, None, None, None, "◦ 예비입주자 주택소유 정기 검색", 2, ""),
        (18, "가감점", None, None, "６-1", "◦ 6-1-1. [운영관리] 표창", 1, ""),
    ]
    for r, a, b, c, d, e, f, h in rows:
        for col, v in zip("ABCDEFH", (a, b, c, d, e, f, h)):
            if v is not None:
                ws[f"{col}{r}"] = v
    ws.merge_cells("G8:G9")
    ws.merge_cells("I8:I9")
    ws.merge_cells("D14:D17")
    ws["I14"] = "모집공고계획수립-173"
    wb.save(path)


def test_load_items(tmp_path):
    p = str(tmp_path / "평가표.xlsx")
    _sheet(p)
    items = qe.load(p)
    assert [(i.part, i.no, i.seq) for i in items] == [
        ("유지관리", "1-1", 1), ("유지관리", "1-3", 1), ("유지관리", "1-3", 2),
        ("임대운영", "1-1", 1), ("임대운영", "1-1", 2), ("가감점", "6-1", 1)]
    assert items[0].criteria.startswith("- 입주시") and items[0].max_score == 2
    assert items[3].basis == "모집공고계획수립-173"


def test_save_keeps_formulas(tmp_path):
    from openpyxl import load_workbook
    p = str(tmp_path / "평가표.xlsx")
    _sheet(p)
    items = qe.load(p)
    items[0].score, items[0].basis = 2, "점검대장 사진"
    items[4].score = 1.5
    bak = qe.save(p, items, "광주양림2", str(tmp_path / "bak"))
    assert os.path.isfile(bak)
    wb = load_workbook(p)
    ws = wb["항목별평가표"]
    assert ws["G8"].value == 2 and ws["I8"].value == "점검대장 사진" and ws["G16"].value == 1.5
    assert ws["F7"].value == "=SUM(F8:F20)" and wb["총괄표"]["F13"].value.startswith("=SUM(")
    assert ws["A3"].value == "○ 단지명 : 광주양림2"
    assert qe.complex_name(p) == "광주양림2"
    assert [i.score for i in qe.load(p)][:1] == [2]


def test_evidence_folders(tmp_path):
    p = str(tmp_path / "평가표.xlsx")
    _sheet(p)
    items = qe.load(p)
    root = qe.evidence_root(p)
    os.makedirs(os.path.join(root, "1-1", "2. 예비입주자 정기검색", "예비자 없음"))     # 양식에 있던 폴더(이름 다름)
    made = qe.make_folders(root, items)
    assert made == len(items) - 1
    rent1 = items[3]
    d = qe.item_dir(root, rent1)
    assert d == os.path.join(root, "1-1", "1. 예비입주자 모집인원 산정")              # 4권 범위는 폴더링 바로 아래
    assert qe.item_dir(root, items[0]).startswith(os.path.join(root, "유지관리", "1-1"))
    with open(os.path.join(d, "1.jpg"), "wb") as f:
        f.write(b"x")
    qe.scan_evidence(root, items)
    assert len(rent1.evidence) == 1
    assert items[4].evidence == [] and items[4].notes == ["예비자 없음"]


def test_find_sheets(tmp_path):
    d = tmp_path / "품질평가" / "2026"
    d.mkdir(parents=True)
    (d / "2026년도 서비스 품질평가 평가표(광주).xlsx").write_bytes(b"")
    (d / "다른 파일.xlsx").write_bytes(b"")
    found = qe.find_sheets([str(tmp_path)], 2026)
    assert len(found) == 1 and found[0].endswith("평가표(광주).xlsx")
