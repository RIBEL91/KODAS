import pytest

import roster


def _csv(tmp_path, text, enc="utf-8-sig"):
    p = tmp_path / "명단.csv"
    p.write_text(text, encoding=enc)
    return str(p)


def test_dong_ho_columns(tmp_path):
    p = _csv(tmp_path, "동,호,계약자명,비고\n101,1001,홍길동,\n102동,201호,김철수,x\n,,,\n")
    assert roster.load(p) == [roster.Person("홍길동", "101동 1001호"),
                              roster.Person("김철수", "102동 201호")]


def test_header_below_title_and_single_address(tmp_path):
    p = _csv(tmp_path, "갱신대상 명단\n\n동·호, 성 명\n101동 1001호,홍길동\n", enc="cp949")
    assert roster.load(p) == [roster.Person("홍길동", "101동 1001호")]


def test_name_only(tmp_path):
    assert roster.load(_csv(tmp_path, "이름\n홍길동\n")) == [roster.Person("홍길동", "")]


def test_errors(tmp_path):
    with pytest.raises(ValueError, match="이름 열"):
        roster.load(_csv(tmp_path, "동,호\n101,1001\n"))
    with pytest.raises(ValueError, match="xlsx"):
        roster.load(str(tmp_path / "옛날.xls"))


def test_count_upload(tmp_path):
    p = _csv(tmp_path, "가나 101동 101호 입주자귀하\n가나 101동 102호 입주자귀하\n\n,메모\n가나 102동 201호 입주자귀하\n")
    assert roster.count_upload(p) == 3
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    for i in range(25):
        wb.active.append([f"가나 101동 {i + 1}호 입주자귀하", "x"])
    x = str(tmp_path / "수신자.xlsx")
    wb.save(x)
    assert roster.count_upload(x) == 25


def test_clean_upload_copy(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    src = _csv(tmp_path, "가나 101동 101호 입주자귀하,메모\n\n가나 101동 102호 입주자귀하,x\n")
    out = roster.clean_upload_copy(src, str(tmp_path / "up"))
    ws = openpyxl.load_workbook(out).active
    assert [r[0] for r in ws.iter_rows(values_only=True)] == ["가나 101동 101호 입주자귀하", "가나 101동 102호 입주자귀하"]
    assert ws.max_column == 1
    with pytest.raises(ValueError):
        roster.clean_upload_copy(_csv(tmp_path, ",x\n"), str(tmp_path / "up2"))


def test_xlsx(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["이름", "동", "호"])
    ws.append(["홍길동", 101, 1001])
    p = str(tmp_path / "명단.xlsx")
    wb.save(p)
    assert roster.load(p) == [roster.Person("홍길동", "101동 1001호")]
