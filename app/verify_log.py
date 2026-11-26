"""자격검증 기록: '주택전산검색 관계철' 엑셀의 주민등록 검증결과 시트 읽기·쓰기.

엑셀 파일은 담당자가 계속 손으로도 쓰는 관계철이라 서식·다른 시트를 건드리면 안 된다.
그래서 openpyxl로 다시 저장하지 않고 Excel 자체(COM)로 칸 값만 쓴다(PowerShell로 부른다 —
pywin32 없이). 그 파일이 이미 Excel에 열려 있으면 그 창에 바로 쓰고 저장한다(열린 채로 둔다).
열려 있지 않으면 보이지 않는 Excel로 열어 쓰고 저장한 뒤 닫는다.

시트 모양(3·4줄 머리글, 5줄부터 한 줄에 한 건, B열부터):
  갱신    : 입주자격검색 | 요청일 | 범정부 송신 | 총계 | 세대주 | 배우자 | 세대원 | 차수 | 조사완료일 | 갱신완료 | 소명대상/소명내용
  주택정기: 입주자격검색 | 요청일 | 총계 | 세대주 | 배우자 | 세대원 | 차수 | 조사완료일(문서통보일) | 검증완료 | 소명대상/소명내용
"""
import datetime as dt
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass

FIRST_ROW = 5           # 기록이 시작하는 줄
FIRST_COL = 2           # B열
DEFAULT_NAME = "주택전산검색 관계철.xlsx"


@dataclass(frozen=True)
class Field:
    key: str            # 칸 이름(화면에 보이는 이름)
    kind: str           # text · date · num · total · status · check · memo


@dataclass(frozen=True)
class Sheet:
    key: str            # 탭 이름
    name: str           # 엑셀 시트 이름
    fields: tuple
    status_values: tuple = ()      # 진행 상태 칸에서 고를 것(직접 적어도 된다)
    status_default: str = ""
    label_choices: tuple = ()      # 달이 아닌 탭의 '구분'(입주자격검색) 칸에서 고를 것

    @property
    def excel_fields(self) -> tuple:
        """예전 관계철 엑셀(Excel로 직접 읽는 것)에 있는 칸 — 소명안내·소명완료일은 KODAS에만 있다."""
        return tuple(f for f in self.fields if f.key not in NEW_KEYS)

    @property
    def last_col(self) -> int:
        return FIRST_COL + len(self.excel_fields) - 1


# 갱신완료(검증완료)와 기록사항 사이: 소명안내를 체크하면 소명완료일(오늘 + 소명기간)을 자동으로 넣는다
CALL = "소명안내"
CALL_DUE = "소명완료일"
CHECK_MARK = "✔"
NEW_KEYS = (CALL, CALL_DUE)
DEFAULT_CALL_DAYS = 10


def call_due(today: dt.date | None = None, days: int = DEFAULT_CALL_DAYS) -> dt.date:
    """소명안내를 체크한 날 기준 소명완료일(오늘 + 소명기간 일수)."""
    return (today or dt.date.today()) + dt.timedelta(days=int(days))


def set_call(rec: dict, on: bool, today: dt.date | None = None, days: int = DEFAULT_CALL_DAYS) -> None:
    """소명안내 체크를 켜면 소명완료일을 오늘 + 소명기간으로, 끄면 둘 다 비운다."""
    rec[CALL] = CHECK_MARK if on else ""
    rec[CALL_DUE] = call_due(today, days) if on else ""


MEMO = "자격검증 기록사항"          # 마지막 칸 제목(예전 이름: 소명대상/소명내용)
OLD_MEMO = "소명대상/소명내용"
HEAD_ROW = 3                        # 머리글 줄(칸 제목)
# 갱신계약 탭 '갱신완료'에서 고르는 차례(일 진행 순서, 2026-11-20 요청)
RENEW_STATUS = ("서류제출안내", "주민등록 검증", "범정부 자동연계", "소명안내", "소명완료", "계약안내", "계약완료")
# 명의변경·예비자정기는 승계·예비자 상태까지
OTHER_STATUS = ("주민등록 검증", "범정부 자동연계", "서류제출안내", "소명안내", "소명완료", "계약안내", "계약완료",
                "승계계약완료", "자격검증 완료")
OLD_STATUS = {"범정부자동연계": "범정부 자동연계", "주민등록검증": "주민등록 검증"}   # 예전 표기 → 지금 표기


def norm_status(v):
    """진행 상태 값의 예전 표기(띄어쓰기 없음)를 지금 목록의 표기로 맞춘다."""
    return OLD_STATUS.get(v.strip(), v) if isinstance(v, str) else v
RENEW_FIELDS = (
    Field("입주자격검색", "text"), Field("요청일", "date"), Field("범정부 송신", "date"),
    Field("총계", "total"), Field("세대주", "num"), Field("배우자", "num"), Field("세대원", "num"),
    Field("차수", "text"), Field("조사완료일", "date"), Field("갱신완료", "status"),
    Field(CALL, "check"), Field(CALL_DUE, "date"), Field(MEMO, "memo"))
RENEW = Sheet("갱신", "주민등록 검증결과(갱신)", RENEW_FIELDS,
              status_values=RENEW_STATUS, status_default="주민등록 검증")
# 예전 관계철 엑셀에서 명의변경·예비자정기를 함께 두던 시트(가져오기·예전 파일 올리기에만 쓴다)
OTHER = Sheet("명의변경·예비자정기", "주민등록 검증결과(명의변경·예비자정기)", RENEW_FIELDS,
              status_values=OTHER_STATUS, status_default="자격검증 완료")
# 2026-11-24: 명의변경과 예비자정기를 따로 둔다. 명의변경은 요청일 옆에 명의변경 신청일
NAME_CHANGE_DATE = "명의변경 신청일"
NAME_CHANGE = Sheet("명의변경", "주민등록 검증결과(명의변경)", (
    Field("입주자격검색", "text"), Field("요청일", "date"), Field(NAME_CHANGE_DATE, "date"),
    Field("범정부 송신", "date"), Field("총계", "total"), Field("세대주", "num"), Field("배우자", "num"),
    Field("세대원", "num"), Field("차수", "text"), Field("조사완료일", "date"), Field("갱신완료", "status"),
    Field(CALL, "check"), Field(CALL_DUE, "date"), Field(MEMO, "memo")),
    status_values=OTHER_STATUS, status_default="자격검증 완료", label_choices=("명의변경",))
PRELIM = Sheet("예비자정기", "주민등록 검증결과(예비자정기)", RENEW_FIELDS,
               status_values=OTHER_STATUS, status_default="자격검증 완료",
               label_choices=("예비자정기", "상반기 예비자정기", "하반기 예비자정기"))
REGULAR = Sheet("주택정기", "주민등록 검증결과(주택정기)", (
    Field("입주자격검색", "text"), Field("요청일", "date"),
    Field("총계", "total"), Field("세대주", "num"), Field("배우자", "num"), Field("세대원", "num"),
    Field("차수", "text"), Field("조사완료일(문서통보일)", "date"), Field("검증완료", "status"),
    Field(CALL, "check"), Field(CALL_DUE, "date"), Field(MEMO, "memo")),
    status_values=("검색요청", "소명안내", "소명완료", "확정"),
    status_default="검색요청")
SHEETS = (RENEW, NAME_CHANGE, PRELIM, REGULAR)      # KODAS에 저장하는 탭
EXCEL_SHEETS = (RENEW, OTHER, REGULAR)              # 예전 관계철 엑셀의 시트(처음 가져오기)
COUNT_KEYS = ("세대주", "배우자", "세대원")
MONTH_RE = re.compile(r"(\d{2})-(\d{1,2})월")
OTHER_NAMES = ("명의변경", "예비자정기", "상반기 예비자정기", "하반기 예비자정기")


def split_key(label) -> str:
    """달이 아닌 줄을 어느 탭에 둘지: '명의변경…'이면 명의변경, 나머지는 예비자정기."""
    return NAME_CHANGE.key if str(label or "").strip().startswith("명의변경") else PRELIM.key


def distribute(data: dict, rows: list) -> None:
    """명의변경·예비자정기가 섞인 줄들을 두 탭에 나눠 붙인다."""
    for r in rows:
        data.setdefault(split_key(r.get("입주자격검색")), []).append(r)
DONE_VALUES = ("계약완료", "승계계약완료", "자격검증 완료")


def is_month(label) -> bool:
    """'26-1월'처럼 달을 적은 줄인지(갱신계약·주택정기의 달마다 기록)."""
    return bool(MONTH_RE.fullmatch(str(label or "").strip()))


def status_key(sheet: "Sheet") -> str:
    """진행 상태 칸 이름(갱신완료·검증완료)."""
    return next((f.key for f in sheet.fields if f.kind == "status"), "")


def is_done(sheet: "Sheet", rec: dict) -> bool:
    """끝난 줄(갱신완료가 계약완료 등, 주택정기 검증완료가 확정) — 화면 맨 위 접힌 묶음에 넣고
    엑셀에서도 맨 위로 옮겨 숨긴다."""
    key = status_key(sheet)
    if not key:
        return False
    v = str(rec.get(key, "")).strip()
    return v in DONE_VALUES or v.endswith("확정")


@dataclass(frozen=True)
class View:
    """화면 탭 하나."""
    key: str
    sheet: Sheet
    months: bool            # True면 입주자격검색(월)을 목록에서 고른다


VIEWS = (View("갱신계약", RENEW, True), View("주택정기", REGULAR, True),
         View("명의변경", NAME_CHANGE, False), View("예비자정기", PRELIM, False))


def month_choices(today: dt.date | None = None, current: str = "") -> list[str]:
    """고를 달: 지난해 1월부터 내년 12월까지('26-1월' 꼴). 적혀 있던 달이 범위 밖이면 그것도 넣는다."""
    y = (today or dt.date.today()).year
    out = [f"{yy % 100:02d}-{m}월" for yy in range(y - 1, y + 2) for m in range(1, 13)]
    if current and current not in out:
        out.insert(0, current)
    return out


def default_book() -> str:
    """바탕화면의 '주택전산검색 관계철.xlsx'(있으면)."""
    import paths
    if paths.was_reset():                    # 데이터 초기화 뒤에는 빈 기록으로 시작
        return ""
    p = os.path.join(os.path.expanduser("~"), "Desktop", DEFAULT_NAME)
    return p if os.path.exists(p) else ""


# ---------------- 값 바꾸기 ----------------
_EPOCH = dt.datetime(1899, 12, 30)


def from_excel(field: Field, v):
    """Excel Value2 → 화면에 쓸 값(날짜는 date, 숫자는 int, 나머지는 글자)."""
    if v is None:
        return ""
    if field.kind == "date" and isinstance(v, (int, float)):
        return (_EPOCH + dt.timedelta(days=float(v))).date()
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if field.kind in ("num", "total") and isinstance(v, int):
        return v
    return str(v).strip() if isinstance(v, str) else str(v)


def show(v) -> str:
    """칸 값 → 목록·입력칸에 보이는 글자."""
    if isinstance(v, dt.date):
        return f"{v.year}. {v.month}. {v.day}."
    return "" if v is None else str(v)


def parse_date(text: str, today: dt.date | None = None):
    """'2026. 11. 18.' · '2026-11-18' · '11. 18.' · '11월 18일' → date. 못 읽으면 글자 그대로."""
    s = (text or "").strip()
    if not s:
        return ""
    today = today or dt.date.today()
    m = re.fullmatch(r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*[.일]?", s)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*[.일]?", s)
        if not m:
            return s
        y, (mo, d) = today.year, map(int, m.groups())
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return s


def parse_num(text: str):
    s = str(text or "").replace(",", "").strip()
    if not s:
        return ""
    try:
        f = float(s)
    except ValueError:
        return s
    return int(f) if f.is_integer() else f


def total_of(values: dict):
    """세대주+배우자+세대원(숫자가 하나도 없으면 '')."""
    nums = [values.get(k) for k in COUNT_KEYS]
    nums = [n for n in nums if isinstance(n, (int, float))]
    return sum(nums) if nums else ""


def next_label(rows: list[dict]) -> str:
    """새 줄의 입주자격검색 칸: 마지막 'YY-M월' 다음 달(예: 26-12월 → 27-1월). 없으면 ''."""
    for r in reversed(rows):
        m = MONTH_RE.fullmatch(str(r.get("입주자격검색", "")).strip())
        if m:
            y, mo = int(m.group(1)), int(m.group(2)) + 1
            if mo > 12:
                y, mo = y + 1, 1
            return f"{y:02d}-{mo}월"
    return ""


def to_cell(field: Field, v) -> dict:
    """화면 값 → PowerShell에 넘길 칸 값 {t: 종류, v: 값}."""
    if v == "" or v is None:
        return {"t": "empty"}
    if isinstance(v, dt.date):
        return {"t": "date", "v": v.isoformat()}
    if isinstance(v, (int, float)):
        return {"t": "num", "v": v}
    return {"t": "text", "v": str(v)}


# ---------------- Excel(COM) ----------------
_PS = r"""
param([string]$JobPath)
$ErrorActionPreference = 'Stop'
$j = Get-Content -Raw -Encoding UTF8 -LiteralPath $JobPath | ConvertFrom-Json
$res = @{ ok = $false }
$xl = $null; $wb = $null; $own = $false
$r0 = [int]$j.r0; $c0 = [int]$j.c0
function Find-Sheet([string]$name) {
  foreach ($w in $wb.Worksheets) { if ($w.Name -eq $name) { return $w } }
  return $null
}
function Last-Row($sh, [int]$c1) {
  # 숨긴 줄이 있으면 End(xlUp)이 건너뛰므로, 쓰인 범위 맨 아래부터 위로 값이 있는 줄을 찾는다
  $ur = $sh.UsedRange
  $last = $ur.Row + $ur.Rows.Count - 1
  while ($last -ge $r0) {
    if ($xl.WorksheetFunction.CountA($sh.Range($sh.Cells.Item($last, $c0), $sh.Cells.Item($last, $c1))) -gt 0) { break }
    $last--
  }
  if ($last -lt $r0) { $last = $r0 - 1 }
  return $last
}
function Is-Done($v) {
  $t = ([string]$v).Trim()
  return ($j.done_values -contains $t) -or $t.EndsWith('확정')
}
function Read-Rows($sh, [int]$c1) {
  $last = Last-Row $sh $c1
  $rows = @()
  for ($r = $r0; $r -le $last; $r++) {
    $vals = @()
    for ($c = $c0; $c -le $c1; $c++) { $vals += ,($sh.Cells.Item($r, $c).Value2) }
    $rows += ,@{ row = $r; v = $vals }
  }
  return ,$rows
}
try {
  try { $xl = [Runtime.InteropServices.Marshal]::GetActiveObject('Excel.Application') } catch { $xl = $null }
  if ($xl) { foreach ($w in $xl.Workbooks) { if ($w.FullName -ieq $j.path) { $wb = $w } } }
  if (-not $wb) {
    $xl = New-Object -ComObject Excel.Application
    $xl.Visible = $false; $xl.DisplayAlerts = $false
    $wb = $xl.Workbooks.Open($j.path); $own = $true
  }
  $res.live = -not $own
  if ($j.op -eq 'readall') {
    $out = @{}
    foreach ($s in $j.sheets) {
      $sh = Find-Sheet $s.name
      if (-not $sh) { $out[$s.key] = @{ missing = $true; rows = @() }; continue }
      $out[$s.key] = @{ missing = $false; head = [string]$sh.Cells.Item([int]$j.head_row, [int]$s.c1).Value2;
                        rows = (Read-Rows $sh ([int]$s.c1)) }
    }
    $res.sheets = $out
  }
  elseif ($j.op -eq 'split') {
    # 갱신 시트의 줄들(j.rows)을 새 시트(j.target, 없으면 갱신 시트를 본떠 만든다)로 옮긴다
    $c1 = [int]$j.c1
    $src = Find-Sheet $j.sheet
    $dst = Find-Sheet $j.target
    if (-not $dst) {
      $src.Copy([Type]::Missing, $src) | Out-Null
      $dst = $wb.Worksheets.Item($src.Index + 1)
      $dst.Name = [string]$j.target
      $last = Last-Row $dst $c1
      if ($last -ge $r0) { $dst.Range($dst.Cells.Item($r0, $c0), $dst.Cells.Item($last, $c1)).ClearContents() | Out-Null }
      $ur = $dst.UsedRange
      $dst.Range($dst.Cells.Item($r0, 1), $dst.Cells.Item([Math]::Max($r0, $ur.Row + $ur.Rows.Count), 1)).EntireRow.Hidden = $false
      $src.Activate() | Out-Null
    }
    $di = (Last-Row $dst $c1) + 1
    if ($di -lt $r0) { $di = $r0 }
    $rowsToMove = @($j.rows | ForEach-Object { [int]$_ })
    foreach ($r in $rowsToMove) {
      $src.Range($src.Cells.Item($r, $c0), $src.Cells.Item($r, $c1)).Copy($dst.Cells.Item($di, $c0)) | Out-Null
      # 갱신완료(계약완료 등) 줄은 엑셀에서처럼 숨겨 둔다
      $dst.Rows.Item($di).Hidden = [bool](Is-Done $dst.Cells.Item($di, [int]$j.status_col).Value2)
      $di++
    }
    try { $xl.CutCopyMode = 0 } catch {}
    for ($k = $rowsToMove.Count - 1; $k -ge 0; $k--) {
      # 줄 통째로 지운다(숨김 표시가 다른 줄로 밀리지 않게). 이 시트는 B~L열만 쓴다
      $src.Rows.Item([int]$rowsToMove[$k]).Delete() | Out-Null
    }
    foreach ($h in $j.heads) {
      $sh = Find-Sheet $h.name
      if ($sh) { $sh.Cells.Item([int]$j.head_row, [int]$h.c1).Value2 = [string]$h.text }
    }
    $wb.Save()
    $res.moved = $rowsToMove.Count
  }
  elseif ($j.op -eq 'write') {
    $ws = Find-Sheet $j.sheet
    if (-not $ws) { throw ("엑셀에 '" + $j.sheet + "' 시트가 없습니다.") }
    $c1 = [int]$j.c1
    $row = [int]$j.row
    if ($row -le 0) {
      $row = (Last-Row $ws $c1) + 1
      if ($row -lt $r0) { $row = $r0 }
    }
    if ($row -gt $r0 -and $ws.Cells.Item($row, $c0 + 1).NumberFormat -eq 'General' -and
        $ws.Cells.Item($row - 1, $c0 + 1).NumberFormat -ne 'General') {
      # 서식이 없는 새 줄: 바로 위 줄의 서식을 가져온다
      $ws.Range($ws.Cells.Item($row - 1, $c0), $ws.Cells.Item($row - 1, $c1)).Copy() | Out-Null
      $ws.Range($ws.Cells.Item($row, $c0), $ws.Cells.Item($row, $c1)).PasteSpecial(-4122) | Out-Null
      try { $xl.CutCopyMode = 0 } catch {}
    }
    $i = 0
    foreach ($cell in $j.cells) {
      $rg = $ws.Cells.Item($row, $c0 + $i)
      switch ($cell.t) {
        'empty' { $rg.ClearContents() | Out-Null }
        'date'  { $rg.Value2 = [double]([datetime]::ParseExact($cell.v, 'yyyy-MM-dd', $null).ToOADate()) }
        'num'   { $rg.Value2 = [double]$cell.v }
        default { $rg.Value2 = [string]$cell.v }
      }
      $i++
    }
    $res.moved_from = $row; $res.moved_to = $row
    if ($j.status_changed -and [int]$j.status_col -gt 0) {
      if (Is-Done $ws.Cells.Item($row, [int]$j.status_col).Value2) {
        # 맨 위부터 이어진 완료 줄들 바로 아래 자리
        $t = $r0
        while ($t -lt $row -and (Is-Done $ws.Cells.Item($t, [int]$j.status_col).Value2)) { $t++ }
        if ($t -lt $row) {
          $ws.Rows.Item($row).Cut() | Out-Null
          $ws.Rows.Item($t).Insert(-4121) | Out-Null
          try { $xl.CutCopyMode = 0 } catch {}
          $res.moved_to = $t
          $row = $t
        }
        $ws.Rows.Item($row).Hidden = $true
      } else {
        $ws.Rows.Item($row).Hidden = $false
      }
    }
    $wb.Save()
    $res.row = $row
  }
  $res.ok = $true
} catch {
  $res.error = $_.Exception.Message
} finally {
  if ($own) {
    try { $wb.Close($false) } catch {}
    try { $xl.Quit() } catch {}
  }
}
$res | ConvertTo-Json -Depth 8 -Compress | Out-File -Encoding utf8 -LiteralPath $j.out
"""


class ExcelError(RuntimeError):
    pass


def _run(job: dict, timeout: int = 90) -> dict:
    tmp = tempfile.mkdtemp(prefix="kodas_verify_")
    script, job_path, out = (os.path.join(tmp, n) for n in ("job.ps1", "job.json", "out.json"))
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(_PS)
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump({**job, "out": out}, f, ensure_ascii=False)
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-File", script, job_path], capture_output=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not os.path.exists(out):
            raise ExcelError("엑셀을 열지 못했습니다.")
        with open(out, encoding="utf-8-sig") as f:
            res = json.load(f)
    except subprocess.TimeoutExpired:
        raise ExcelError("엑셀이 응답하지 않습니다. 엑셀에서 칸을 고치는 중이면 Enter나 Esc를 누르고 다시 해 주세요.")
    finally:
        for p in (script, job_path, out):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass
    if not res.get("ok"):
        msg = res.get("error") or "알 수 없는 오류"
        if "0x800AC472" in msg or "거부" in msg or "rejected" in msg.lower():
            msg = "엑셀이 바쁩니다. 엑셀에서 칸을 고치는 중이면 Enter나 Esc를 누르고 다시 해 주세요."
        raise ExcelError(msg)
    return res


def status_col(sheet: Sheet) -> int:
    """진행 상태 칸(갱신완료·검증완료)의 엑셀 열 번호(끝난 줄 옮기기·숨기기에 쓴다). 없으면 0."""
    return next((FIRST_COL + i for i, f in enumerate(sheet.fields) if f.kind == "status"), 0)


def _job(path: str, sheet: Sheet, op: str, **kw) -> dict:
    return {"path": os.path.abspath(path), "sheet": sheet.name, "op": op,
            "r0": FIRST_ROW, "c0": FIRST_COL, "c1": sheet.last_col,
            "status_col": status_col(sheet), "done_values": list(DONE_VALUES), **kw}


_MD_RE = re.compile(r"(\d{1,2})\s*(?:월|[.\-/])\s*(\d{1,2})\s*(?:일|\.)?")


def fix_years(sheet: Sheet, rec: dict) -> None:
    """'8월 25일'처럼 연도 없이 글자로 적힌 날짜 칸을 날짜로 바꾼다(화면에 연월일로 보이고,
    그 줄을 다시 저장하면 엑셀에도 날짜로 들어간다). 연도는 같은 줄의 다른 날짜(조사완료일 등)보다
    늦지 않게, 그런 날짜가 없으면 입주자격검색 달('26-12월')을 기준으로 정한다."""
    dates = [rec[f.key] for f in sheet.fields if f.kind == "date" and isinstance(rec.get(f.key), dt.date)]
    ref = max(dates) if dates else None
    if ref is None:
        m = MONTH_RE.fullmatch(str(rec.get("입주자격검색", "")).strip())
        if m:
            ref = dt.date(2000 + int(m.group(1)), int(m.group(2)), 1)
    for f in sheet.fields:
        v = rec.get(f.key)
        if f.kind != "date" or not isinstance(v, str):
            continue
        m = _MD_RE.fullmatch(v.strip())
        if not m or ref is None:
            continue
        mo, d = int(m.group(1)), int(m.group(2))
        for y in (ref.year, ref.year - 1):
            try:
                cand = dt.date(y, mo, d)
            except ValueError:
                break
            if cand <= ref + dt.timedelta(days=31):
                rec[f.key] = cand
                break


def _rows(sheet: Sheet, res: dict) -> list[dict]:
    rows = []
    for item in res.get("rows") or []:
        vals = item.get("v") or []
        if not isinstance(vals, list):
            vals = [vals]
        rec = {f.key: from_excel(f, vals[i] if i < len(vals) else None) for i, f in enumerate(sheet.excel_fields)}
        fix_years(sheet, rec)
        if any(v != "" for v in rec.values()):
            rec["_row"] = int(item["row"])
            rows.append(rec)
    return rows


@dataclass
class Book:
    """관계철을 한 번에 읽은 것."""
    rows: dict              # 시트 key → 기록들
    live: bool              # 엑셀에 열려 있던 파일인지
    missing: tuple          # 엑셀에 없는 시트 key들
    old_heads: tuple        # 마지막 칸 제목이 아직 '자격검증 기록사항'이 아닌 시트 key들

    def to_move(self) -> list[int]:
        """갱신 시트에 남아 있는 명의변경·예비자정기 등(달이 아닌) 줄 번호."""
        return [r["_row"] for r in self.rows.get(RENEW.key, []) if not is_month(r.get("입주자격검색"))]

    def needs_split(self) -> bool:
        return OTHER.key in self.missing or bool(self.to_move()) or bool(self.old_heads)


def read_all(path: str) -> Book:
    """세 시트를 한 번에 읽는다(명의변경·예비자정기 시트는 없을 수 있다)."""
    job = {"path": os.path.abspath(path), "op": "readall", "r0": FIRST_ROW, "c0": FIRST_COL,
           "head_row": HEAD_ROW,
           "sheets": [{"key": s.key, "name": s.name, "c1": s.last_col} for s in EXCEL_SHEETS]}
    res = _run(job)
    got = res.get("sheets") or {}
    rows, missing, old = {}, [], []
    for s in EXCEL_SHEETS:
        item = got.get(s.key) or {"missing": True}
        if item.get("missing"):
            missing.append(s.key)
            rows[s.key] = []
            continue
        rows[s.key] = _rows(s, item)
        if str(item.get("head") or "").strip() != MEMO:
            old.append(s.key)
    if RENEW.key in missing or REGULAR.key in missing:
        names = [s.name for s in EXCEL_SHEETS if s.key in missing and s is not OTHER]
        raise ExcelError("관계철에 다음 시트가 없습니다: " + ", ".join(names))
    return Book(rows, bool(res.get("live")), tuple(missing), tuple(old))


def read(path: str, sheet: Sheet) -> tuple[list[dict], bool]:
    """(그 시트 기록들, 엑셀에 열려 있는지)."""
    b = read_all(path)
    return b.rows[sheet.key], b.live


def backup(path: str) -> str:
    """고치기 전 관계철을 사용자 폴더(공문작성기/백업/자격검증)에 복사해 둔다."""
    import shutil
    import paths
    folder = paths.sub_dir("백업", "자격검증")
    stem, ext = os.path.splitext(os.path.basename(path))
    dst = os.path.join(folder, f"{stem}_{dt.datetime.now():%Y%m%d_%H%M%S}{ext}")
    shutil.copy2(path, dst)
    return dst


def split_other(path: str, book: Book) -> int:
    """갱신 시트의 명의변경·예비자정기 줄을 새 시트로 옮기고, 마지막 칸 제목을 '자격검증 기록사항'으로.
    옮긴 줄 수를 돌려준다. 먼저 backup()을 해 둔다."""
    heads = [{"name": s.name, "c1": s.last_col, "text": MEMO} for s in EXCEL_SHEETS
             if s.key in book.old_heads or (s is OTHER and OTHER.key in book.missing)]
    job = {"path": os.path.abspath(path), "op": "split", "r0": FIRST_ROW, "c0": FIRST_COL,
           "c1": RENEW.last_col, "head_row": HEAD_ROW, "sheet": RENEW.name, "target": OTHER.name,
           "rows": book.to_move(), "heads": heads,
           "status_col": status_col(RENEW), "done_values": list(DONE_VALUES)}
    return int(_run(job, timeout=180).get("moved") or 0)


@dataclass
class Written:
    row: int            # 다 쓴 뒤 그 줄의 엑셀 줄 번호
    moved_from: int     # 완료 줄을 맨 위로 옮겼으면 옮기기 전 줄(안 옮겼으면 row와 같다)
    moved_to: int


def write(path: str, sheet: Sheet, values: dict, row: int = 0, status_changed: bool = False) -> Written:
    """한 줄을 쓴다(row=0이면 마지막 기록 다음 줄에 새로).
    status_changed이고 갱신완료가 끝난 상태(계약완료 등)면 그 줄을 맨 위 완료 줄들 바로 아래로 옮겨 숨긴다
    (담당자가 엑셀에서 하던 대로). 완료가 아니게 바뀌면 숨김을 푼다."""
    values = dict(values)
    values["총계"] = total_of(values) if any(values.get(k) not in ("", None) for k in COUNT_KEYS)         else values.get("총계", "")
    cells = [to_cell(f, values.get(f.key, "")) for f in sheet.fields]
    res = _run(_job(path, sheet, "write", row=int(row or 0), cells=cells, status_changed=bool(status_changed)))
    r = int(res.get("row") or 0)
    return Written(r, int(res.get("moved_from") or r), int(res.get("moved_to") or r))


def remap_rows(rows: list[dict], moved_from: int, moved_to: int) -> None:
    """엑셀에서 moved_from 줄을 moved_to 자리로 옮긴(끼워 넣은) 뒤의 줄 번호로 기록들의 _row를 고친다."""
    if moved_to >= moved_from:
        return
    for r in rows:
        if r["_row"] == moved_from:
            r["_row"] = moved_to
        elif moved_to <= r["_row"] < moved_from:
            r["_row"] += 1
    rows.sort(key=lambda r: r["_row"])


# ---------------- KODAS 안에 따로 두는 기록(관계철 엑셀과 연결하지 않음) ----------------
# 기록은 사용자 폴더의 자격검증기록.json에 둔다. 처음 한 번만 관계철 엑셀이 있으면 그 내용을 가져와 시작한다.
STORE_NAME = "자격검증기록.json"
_DATE_TAG = "날짜:"


def store_path() -> str:
    import paths
    return os.path.join(paths.data_dir(), STORE_NAME)


def _enc(v):
    return _DATE_TAG + v.isoformat() if isinstance(v, dt.date) else v


def _dec(v):
    if isinstance(v, str) and v.startswith(_DATE_TAG):
        try:
            return dt.date.fromisoformat(v[len(_DATE_TAG):])
        except ValueError:
            return v
    return v


def _renumber(rows: list[dict]) -> list[dict]:
    """기록 차례대로 줄 번호를 1부터 다시 매긴다."""
    for i, r in enumerate(rows, 1):
        r["_row"] = i
    return rows


def store_load() -> dict:
    """{시트 key: [기록 …]} (파일이 없으면 빈 기록)."""
    try:
        with open(store_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = {}
    if OTHER.key in raw:          # 예전 '명의변경·예비자정기' 탭 → 명의변경 / 예비자정기로 나눈다
        mixed = [r for r in raw.pop(OTHER.key) or [] if isinstance(r, dict)]
        distribute(raw, mixed)
    out = {}
    for s in SHEETS:
        rows = [{k: _dec(v) for k, v in r.items()} for r in raw.get(s.key, []) if isinstance(r, dict)]
        key = status_key(s)
        for r in rows:            # 예전 이름으로 저장된 칸
            if OLD_MEMO in r and MEMO not in r:
                r[MEMO] = r.pop(OLD_MEMO)
            if key in r:
                r[key] = norm_status(r[key])
        out[s.key] = _renumber(rows)
    return out


def store_save(data: dict) -> None:
    path = store_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: [{kk: _enc(vv) for kk, vv in r.items() if kk != "_row"} for r in rows]
                   for k, rows in data.items()}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def store_exists() -> bool:
    return os.path.exists(store_path())


def store_import_excel(path: str) -> int:
    """처음 한 번: 관계철 엑셀의 기록을 가져와 따로 저장한다(엑셀은 읽기만). 가져온 줄 수."""
    book = read_all(path)
    data = {s.key: [] for s in SHEETS}
    clean = {s.key: [{k: v for k, v in r.items() if k != "_row"} for r in book.rows.get(s.key, [])]
             for s in EXCEL_SHEETS}
    data[RENEW.key] = [r for r in clean[RENEW.key] if is_month(r.get("입주자격검색"))]
    data[REGULAR.key] = clean[REGULAR.key]
    # 명의변경·예비자정기 시트 줄과 갱신 시트에 섞여 있던 달 아닌 줄은 명의변경 / 예비자정기로
    distribute(data, clean[OTHER.key] + [r for r in clean[RENEW.key] if not is_month(r.get("입주자격검색"))])
    for k in data:
        _renumber(data[k])
    store_save(data)
    return sum(len(v) for v in data.values())


def store_book() -> Book:
    """화면·공문 작성에 쓰는 기록(따로 저장한 것)."""
    return Book(store_load(), False, (), ())


def store_write(sheet: Sheet, values: dict, row: int, status_changed: bool = False) -> Written:
    """한 줄을 저장한다(row가 없는 번호면 맨 아래 새 줄). 끝난 줄(계약완료·확정 등)로 바뀌면
    맨 위 끝난 줄들 바로 아래로 옮긴다(화면에서는 접힌 묶음 안에 숨는다)."""
    data = store_load()
    rows = data[sheet.key]
    values = {k: v for k, v in values.items() if k != "_row"}
    values["총계"] = total_of(values) if any(values.get(k) not in ("", None) for k in COUNT_KEYS) \
        else values.get("총계", "")
    rec = next((r for r in rows if r["_row"] == row), None)
    if rec is None:
        rec = {"_row": len(rows) + 1}
        rows.append(rec)
    rec.update(values)
    src = rows.index(rec)
    dst = src
    if status_changed and is_done(sheet, rec):
        dst = 0
        while dst < src and is_done(sheet, rows[dst]):
            dst += 1
        if dst < src:
            rows.insert(dst, rows.pop(src))
    _renumber(rows)
    store_save(data)
    return Written(dst + 1, src + 1, dst + 1)


def store_delete(sheet: Sheet, row: int) -> None:
    data = store_load()
    data[sheet.key] = _renumber([r for r in data[sheet.key] if r["_row"] != row])
    store_save(data)


# ---------------- 엑셀로 받기 · 엑셀 올려 적용 ----------------
# 받은 파일은 관계철과 같은 모양(시트 이름·3줄 머리글·5줄부터 B열부터)이라, 그대로 고쳐서 다시 올리면 된다.
DATE_FMT = "yyyy. m. d."


def store_export_xlsx(path: str) -> int:
    """지금 기록(세 시트)을 엑셀 파일로 쓴다. 쓴 줄 수."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    data = store_load()
    wb = Workbook()
    wb.remove(wb.active)
    thin = Side(style="thin", color="A0A8B8")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="DCE6F5")
    widths = {"text": 14, "date": 13, "num": 8, "total": 8, "status": 15, "check": 9, "memo": 50}
    n = 0
    for s in SHEETS:
        ws = wb.create_sheet(s.name[:31])
        ws.cell(1, FIRST_COL, s.name).font = Font(bold=True, size=13)
        ws.cell(2, FIRST_COL, "※ 5줄부터 한 줄에 한 건. 칸 제목(3줄)과 시트 이름은 바꾸지 마세요 — "
                "고친 뒤 KODAS [엑셀 올려 적용]으로 다시 올리면 됩니다.").font = Font(size=9, color="777777")
        for i, f in enumerate(s.fields):
            c = FIRST_COL + i
            ws.merge_cells(start_row=HEAD_ROW, start_column=c, end_row=HEAD_ROW + 1, end_column=c)
            h = ws.cell(HEAD_ROW, c, f.key)
            h.font, h.fill, h.border = Font(bold=True), head_fill, box
            h.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            ws.cell(HEAD_ROW + 1, c).border = box
            ws.column_dimensions[get_column_letter(c)].width = widths[f.kind]
        ws.column_dimensions["A"].width = 2
        for j, rec in enumerate(data.get(s.key, [])):
            r = FIRST_ROW + j
            for i, f in enumerate(s.fields):
                v = rec.get(f.key, "")
                cell = ws.cell(r, FIRST_COL + i, None if v == "" else v)
                cell.border = box
                if isinstance(v, dt.date):
                    cell.number_format = DATE_FMT
                cell.alignment = Alignment(horizontal="left" if f.kind == "memo" else "center",
                                           vertical="center", wrap_text=f.kind == "memo")
            n += 1
        ws.freeze_panes = ws.cell(FIRST_ROW, FIRST_COL)
    wb.save(path)
    return n


def _from_xlsx(field: Field, v):
    """openpyxl 칸 값 → 기록 값."""
    if v is None:
        return ""
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if field.kind == "date" and isinstance(v, (int, float)) and 20000 < v < 80000:
        return (_EPOCH + dt.timedelta(days=float(v))).date()
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if field.kind == "date" and s:
        return parse_date(s)
    if field.kind in ("num", "total") and s:
        return parse_num(s)
    if field.kind == "status":
        return norm_status(s)
    return s


def _find_ws(wb, s: Sheet):
    for ws in wb.worksheets:
        if ws.title.strip() in (s.name[:31], s.name, s.key):
            return ws
    return None


def _head_cols(ws, s: Sheet) -> dict:
    """칸 제목(3·4줄)으로 칸 자리를 찾는다(예전에 받은 파일은 소명안내·소명완료일 칸이 없다).
    제목으로 못 찾는 칸은 예전 차례대로 둔다."""
    names = {}
    for c in range(FIRST_COL, (ws.max_column or FIRST_COL) + 1):
        for r in (HEAD_ROW, HEAD_ROW + 1):
            t = re.sub(r"\s+", "", str(ws.cell(r, c).value or ""))
            if t and t not in names:
                names[t] = c
    names.setdefault(re.sub(r"\s+", "", MEMO), names.get(re.sub(r"\s+", "", OLD_MEMO)))
    cols = {}
    for f in s.fields:
        c = names.get(re.sub(r"\s+", "", f.key))
        if c:
            cols[f.key] = c
    if len(cols) < 3:                # 제목이 거의 없으면 예전 차례(소명 칸 없이)
        cols = {f.key: FIRST_COL + i for i, f in enumerate(s.excel_fields)}
    return cols


def read_xlsx(path: str) -> dict:
    """[엑셀로 받기]와 같은 양식의 파일을 읽는다 → {시트 key: [기록 …]} (파일에 있는 시트만)."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(path, data_only=True)
    except Exception as ex:
        raise ExcelError(f"엑셀 파일을 열지 못했습니다: {ex}")
    out = {}
    for s in SHEETS:
        ws = _find_ws(wb, s)
        if ws is None:
            continue
        heads = [str(ws.cell(r, FIRST_COL).value or "").strip() for r in (HEAD_ROW, HEAD_ROW + 1)]
        if "입주자격검색" not in heads:
            raise ExcelError(f"'{ws.title}' 시트의 3줄 B칸이 '입주자격검색'이 아닙니다. "
                             "[엑셀로 받기]로 받은 양식에 고쳐서 올려 주세요.")
        cols = _head_cols(ws, s)
        rows = []
        for r in range(FIRST_ROW, ws.max_row + 1):
            rec = {f.key: (_from_xlsx(f, ws.cell(r, cols[f.key]).value) if f.key in cols else "")
                   for f in s.fields}
            if all(v == "" for v in rec.values()):
                continue
            fix_years(s, rec)
            if any(rec.get(k) not in ("", None) for k in COUNT_KEYS):
                rec["총계"] = total_of(rec)
            rows.append(rec)
        out[s.key] = rows
    if NAME_CHANGE.key not in out and PRELIM.key not in out:   # 예전에 받은 파일(명의변경·예비자정기 한 시트)
        ws = _find_ws(wb, OTHER)
        if ws is not None:
            cols = _head_cols(ws, OTHER)
            mixed = []
            for r in range(FIRST_ROW, ws.max_row + 1):
                rec = {f.key: (_from_xlsx(f, ws.cell(r, cols[f.key]).value) if f.key in cols else "")
                       for f in OTHER.fields}
                if all(v == "" for v in rec.values()):
                    continue
                fix_years(OTHER, rec)
                if any(rec.get(k) not in ("", None) for k in COUNT_KEYS):
                    rec["총계"] = total_of(rec)
                mixed.append(rec)
            split = {NAME_CHANGE.key: [], PRELIM.key: []}
            distribute(split, mixed)
            out.update(split)
    if not out:
        raise ExcelError("자격검증 기록 시트가 없습니다. 시트 이름이 다음 중 하나여야 합니다:\n"
                         + "\n".join(s.name for s in SHEETS))
    return out


def backup_store() -> str:
    """지금 기록(자격검증기록.json)을 백업 폴더에 복사해 둔다(없으면 '')."""
    import shutil
    import paths
    src = store_path()
    if not os.path.exists(src):
        return ""
    dst = os.path.join(paths.sub_dir("백업", "자격검증"), f"자격검증기록_{dt.datetime.now():%Y%m%d_%H%M%S}.json")
    shutil.copy2(src, dst)
    return dst


def store_import_xlsx(path: str) -> dict:
    """올린 엑셀로 기록을 바꾼다(파일에 있는 시트만 통째로 바꾸고, 없는 시트는 그대로). 먼저 백업.
    돌려주는 것: {시트 key: 줄 수}."""
    got = read_xlsx(path)
    backup_store()
    data = store_load()
    for key, rows in got.items():
        data[key] = _renumber(rows)
    if RENEW.key in got:     # 갱신 시트에 명의변경·예비자정기 줄이 섞여 왔으면 나눈다
        other = [r for r in data[RENEW.key] if not is_month(r.get("입주자격검색"))]
        if other:
            data[RENEW.key] = _renumber([r for r in data[RENEW.key] if is_month(r.get("입주자격검색"))])
            moved = {NAME_CHANGE.key: [], PRELIM.key: []}
            distribute(moved, other)
            for k, rs in moved.items():
                if rs:
                    data[k] = _renumber(data[k] + rs)
                    got.setdefault(k, rs)
    store_save(data)
    return {k: len(data[k]) for k in got}
