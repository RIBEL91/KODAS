"""수신인 명단(엑셀·CSV) 읽기.

첫 줄(또는 위쪽 10줄 안의 머리글 줄)에서 열 이름으로 찾는다.
- 이름: 이름 / 성명 / 계약자 / 계약자명 / 세대주 / 수신인 / 수신자
- 동·호: '동'과 '호' 두 칸, 또는 '동호' / '동·호' / '주소' 한 칸
동·호는 '101동 1001호' 모양으로 합쳐 {주소}에 넣는다.
"""
import csv
import os
import re
from dataclasses import dataclass

NAME_COLS = ("이름", "성명", "계약자", "계약자명", "세대주", "수신인", "수신자")
DONG_COLS = ("동",)
HO_COLS = ("호", "호수")
ADDR_COLS = ("동호", "동·호", "동/호", "주소")
HEADER_SCAN = 10


@dataclass
class Person:
    name: str
    address: str = ""


def _norm(s) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def _cell(v) -> str:
    """엑셀 숫자 101.0 → '101'"""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip() if v is not None else ""


def _unit(v: str, suffix: str) -> str:
    return v if not v or v.endswith(suffix) else v + suffix


def _find(header: list[str], names: tuple[str, ...]) -> int | None:
    for i, h in enumerate(header):
        if h in names:
            return i
    return None


def _rows_xlsx(path: str) -> list[list]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ValueError("엑셀을 읽는 부품(openpyxl)이 없습니다. CSV로 저장해 불러오세요.") from None
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    finally:
        wb.close()


def _rows_csv(path: str) -> list[list]:
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return [row for row in csv.reader(f)]
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV 글자 인코딩을 알 수 없습니다. 엑셀(xlsx)로 저장해 불러오세요.")


def _rows_xls(path: str) -> list[list]:
    try:
        import xlrd
    except ImportError:
        raise ValueError("옛 엑셀(.xls)을 읽는 부품(xlrd)이 없습니다.") from None
    sheet = xlrd.open_workbook(path).sheet_by_index(0)
    return [sheet.row_values(i) for i in range(sheet.nrows)]


def upload_names(path: str) -> list[str]:
    """홈넷 수기입력 [업로드]용 엑셀의 수신자들: 첫 시트 첫 열에서 비어 있지 않은 칸.
    (홈넷도 sheet1의 첫 열만 읽는다)"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xls":
        rows = _rows_xls(path)
    elif ext in (".xlsx", ".xlsm"):
        rows = _rows_xlsx(path)
    elif ext == ".csv":
        rows = _rows_csv(path)
    else:
        raise ValueError(f"엑셀 파일이 아닙니다: {os.path.basename(path)}")
    return [_cell(row[0]) for row in rows if row and _cell(row[0])]


def count_upload(path: str) -> int:
    return len(upload_names(path))


def clean_upload_copy(path: str, folder: str) -> str:
    """명단만 뽑아 새 엑셀(.xlsx)로 다시 만든다.

    PC의 문서보안(DRM) 등으로 원본 파일을 홈넷 서버가 읽지 못해 '시스템 오류'가 나는 경우가 있어,
    프로그램이 새로 만든 파일을 올린다. 돌려주는 값은 새 파일 경로.
    """
    from openpyxl import Workbook
    names = upload_names(path)
    if not names:
        raise ValueError(f"수신자 엑셀의 첫 열에 명단이 없습니다: {os.path.basename(path)}")
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, "upload_recipients.xlsx")
    wb = Workbook()
    for n in names:
        wb.active.append([n])
    wb.save(out)
    return out


def load(path: str) -> list[Person]:
    """명단을 읽는다. 이름이 빈 줄은 건너뛴다."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        rows = _rows_xlsx(path)
    elif ext == ".csv":
        rows = _rows_csv(path)
    elif ext == ".xls":
        raise ValueError("옛 엑셀 형식(.xls)은 읽지 못합니다. 엑셀에서 [다른 이름으로 저장 → .xlsx]로 바꿔 주세요.")
    else:
        raise ValueError(f"엑셀(.xlsx) 또는 CSV 파일을 골라 주세요: {os.path.basename(path)}")

    for hi, row in enumerate(rows[:HEADER_SCAN]):
        header = [_norm(c) for c in row]
        ni = _find(header, NAME_COLS)
        if ni is not None:
            break
    else:
        raise ValueError("첫 줄에서 이름 열을 찾지 못했습니다. 머리글을 '이름', '동', '호'로 적어 주세요.")
    di, hoi, ai = _find(header, DONG_COLS), _find(header, HO_COLS), _find(header, ADDR_COLS)

    people = []
    for row in rows[hi + 1:]:
        get = lambda i: _cell(row[i]) if i is not None and i < len(row) else ""
        name = get(ni)
        if not name:
            continue
        if di is not None or hoi is not None:
            addr = " ".join(x for x in (_unit(get(di), "동"), _unit(get(hoi), "호")) if x)
        else:
            addr = get(ai)
        people.append(Person(name, addr))
    if not people:
        raise ValueError("명단에 이름이 한 명도 없습니다.")
    return people
