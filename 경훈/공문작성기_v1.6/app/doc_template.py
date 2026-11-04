"""서식(txt) 읽기 · 빈칸 채우기 · 웹한글 본문용 HTML 만들기.

서식 파일 형식 (UTF-8):
    제목: 갱신계약 체결 안내({날짜:갱신월|월} 갱신)
    수신자: {주소} {이름} 귀하          ← '내부결재'면 수신자를 넣지 않는다
    구분: 재임대·갱신계약
    이름칸: 받는 분 이름                 ← (선택) 이름 입력칸에 보일 설명
    1안: 갱신계약 사전서류 제출 안내(내부결재)  ← (선택) 서식\\1안 폴더의 내부결재 서식을 1안으로,
                                           이 서식을 2안으로 함께 작성한다(수신자는 2안에만)
    메모: LH-WISE > … > 출력              ← (선택) 작성자에게만 보이는 메모
    분야: 시설                           ← (선택) 시작 화면 분야(임대·시설·주거복지·주택관리). 없으면 임대
    주기: 매월                           ← (선택) 목록의 '매월 작성'('매주'면 '매주 작성') 묶음에 둔다. 없으면 '수시 작성'
    입력: {숫자:전월누적=0}               ← (선택) 본문에 안 나오고 계산에만 쓰는 입력칸(여러 줄 가능)
    이월: 전월누적 <- 누적                 ← (선택) 작성을 마치면 '누적' 값을 다음 작성 때 '전월누적' 처음 값으로
    묶음: 갱신계약                        ← (선택) 서식 고르기의 펼침 묶음(갱신계약·예비입주자·기타 …)
    순서: 99                             ← (선택) 묶음 안 차례. 없으면 파일 번호 차례
    선택안: 1_가; 2_나                   ← (선택) 서식\선택안 폴더의 서식을 골라 2안·3안…으로 함께 작성
    없음표시: 소명대상 없음               ← (선택) 선택안 옆에 이 체크칸을 두고, 체크하면 선택안을 빼고
                                           1안 제목 끝 괄호 안에 ', 소명대상 없음'을 붙인다
    ---
    본문 …

빈칸
- {이름} {주소}                       : 공문마다 입력
- {관리소} {단지명} {담당자} {전화번호}  : 기본정보(처음 한 번 입력)
- {날짜:항목|형식}                     : 같은 항목은 한 번만 입력. 형식은 아래 FORMATS
- {입력:항목}                         : 글자로 직접 적는 칸(예: 날짜를 2026. 10. 25.처럼 수기로)
- {입력:항목=처음값}                   : 처음 값이 들어 있는 입력칸
- {숫자:항목} {숫자:항목=3200}          : 숫자 칸(1,234처럼 쉼표를 넣어 보여 준다)
- {금액:항목}                         : 금액 칸. 113560 → 금113,560원(금일십일만삼천오백육십원)
- {계산:이름=식}                       : 다른 칸으로 계산한 값. 예: {계산:금액=수량*단가}
                                       + - * / ( )와 내림(x,10)·반올림·올림·합, 단지기본정보는 단지:평형1
- {단지:항목}                         : 단지기본정보(파일 → 단지기본정보)의 값. 예: {단지:관리소명}
- {문서링크}                          : 자동 작성 때 홈넷 [문서링크]로 '{입력:차수}차' 결과 통보 문서를 넣는 자리
- {심사결과링크}                       : 같은 차수의 '입주자격심사 결과' 문서를 넣는 자리
- {소명안내링크}                       : 같은 갱신월의 '소명 안내' 문서를 넣는 자리
표
- '|'로 시작하는 줄이 이어지면 표. 첫 줄(또는 '|---|' 위의 줄들)이 머리글.
- 칸 안 줄바꿈은 <br>, '^'는 위 칸과 합치기, '<'는 왼쪽 칸과 합치기.
"""
import datetime as dt
import os
import re
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser

WEEKDAYS = "월화수목금토일"
DATE_RE = re.compile(r"\{날짜:([^{}|]+)(?:\|([^{}]+))?\}")
INPUT_RE = re.compile(r"\{입력:([^{}|=]+)(?:=([^{}]*))?\}")      # 수기 입력 칸: 적은 글자 그대로 들어간다
NUM_RE = re.compile(r"\{(숫자|금액):([^{}|=]+)(?:=([^{}]*))?\}")  # 숫자·금액 칸(값은 '입력:이름'에 담긴다)
CALC_RE = re.compile(r"\{계산:([^{}=]+)=([^{}]+)\}")
COMPLEX_RE = re.compile(r"\{단지:([^{}|=]+)\}")
FIELD_RE = re.compile(r"\{([^{}:|]+)\}")
COMPLEX_PREFIX = "단지:"
# 단지기본정보 값(이름 → 값). 프로그램이 시작할 때와 단지기본정보를 저장할 때 set_complex로 채운다.
COMPLEX: dict[str, str] = {}


def set_complex(values: dict) -> None:
    COMPLEX.clear()
    COMPLEX.update({str(k): str(v or "") for k, v in (values or {}).items()})
PERSON_KEYS = ("이름", "주소")
INFO_KEYS = ("관리소", "단지명", "담당자", "전화번호")
INTERNAL = "내부결재"
FIRST_DIR = "1안"      # 서식 폴더 안: 다른 서식의 1안으로만 쓰는 내부결재 서식(목록에는 안 보임)
OPTION_DIR = "선택안"   # 서식 폴더 안: 다른 서식에 2안·3안…으로 골라 붙이는 서식(목록에는 안 보임)
COLLECTED_DIR = "수집한 서식"   # 서식 폴더 안: 홈넷 대장에서 모아 자동으로 만든 서식(목록에 보임)

# 아직 고치지 않은 서식 표시(0000년, 00월, OOO, ○○ 등)를 찾는다.
# 숫자 바로 뒤의 0(10,000원·1,200세대처럼 계산·입력한 값)은 서식 표시가 아니다.
_UNFILLED_RE = re.compile(r"(?<![\d,])(?:0000|00월|00일|00세대|00차|0,000|000(?![0-9]))|OOO|ooo|○○|0\*0")


def fmt_date(d: dt.date, style: str = "") -> str:
    """2025 공문서 작성법: 연월일은 숫자 뒤에 마침표, '일' 뒤에도 마침표를 찍는다.
    형식: (기본)요일 2026. 11. 6.(금) / 일 2026. 11. 6. / 월 2026년 11월 /
    월만 11월 / 년월 26년 11월 / 년 2026년 / 분기 2026년 4분기 / 점·점요일은 일·요일과 같다(옛 서식 호환)
    관리업무(월별·주별) 서식 형식: 공문 2026. 11. 6. / 공문요일 2026. 11. 6.(금) / 일자 2026년 11월 6일 /
    일요일 2026년 11월 6일(금) / 월일 11월 6일 / 월일요일 11월 6일(금) / 년월점 2026. 11. / 점월 2026. 11월 /
    짧은월 '26. 11월 / 짧은년 '26년 / 짧은년월 '26년 11월 / 분기만 4분기"""
    wd = WEEKDAYS[d.weekday()]
    style = (style or "요일").strip()
    if style in ("요일", "점요일"):
        return f"{d.year}. {d.month}. {d.day}.({wd})"
    if style in ("일", "점"):
        return f"{d.year}. {d.month}. {d.day}."
    if style == "월":
        return f"{d.year}년 {d.month}월"
    if style == "월만":
        return f"{d.month}월"
    if style == "년월":
        return f"{d.year % 100}년 {d.month}월"
    if style == "년":
        return f"{d.year}년"
    if style == "분기":
        return f"{d.year}년 {(d.month - 1) // 3 + 1}분기"
    yy = f"{d.year % 100:02d}"
    more = {
        "공문": f"{d.year}. {d.month}. {d.day}.",
        "공문요일": f"{d.year}. {d.month}. {d.day}.({wd})",
        "일자": f"{d.year}년 {d.month}월 {d.day}일",
        "일요일": f"{d.year}년 {d.month}월 {d.day}일({wd})",
        "월일": f"{d.month}월 {d.day}일",
        "월일요일": f"{d.month}월 {d.day}일({wd})",
        "년월점": f"{d.year}. {d.month}.",
        "점월": f"{d.year}. {d.month}월",
        "짧은월": f"'{yy}. {d.month}월",
        "짧은년": f"'{yy}년",
        "짧은년월": f"'{yy}년 {d.month}월",
        "분기만": f"{(d.month - 1) // 3 + 1}분기",
    }
    if style in more:
        return more[style]
    raise ValueError(f"알 수 없는 날짜 형식입니다: {style}")


DATE_STYLES = ("요일", "일", "월", "월만", "년월", "년", "분기", "점", "점요일",
               "공문", "공문요일", "일자", "일요일", "월일", "월일요일",
               "년월점", "점월", "짧은월", "짧은년", "짧은년월", "분기만")
# 날짜 칸이 달만 고르는 칸이 되는 형식. 월·월만·년월은 칸 이름이 '…월'일 때만(임대 서식 그대로),
# 아래 형식은 이름과 상관없이 달만 고른다(관리업무 서식).
MONTH_STYLES = ("년월점", "점월", "짧은월", "짧은년", "짧은년월", "분기만")
DAY_STYLES = ("요일", "일", "점", "점요일", "공문", "공문요일", "일자", "일요일", "월일", "월일요일")

# ---------------- 금액·숫자·계산 ----------------
_DIGITS = "영일이삼사오육칠팔구"
_SMALL = ["", "십", "백", "천"]
_BIG = ["", "만", "억", "조"]


def korean_number(n: int) -> str:
    """113560 → 일십일만삼천오백육십 (공문 금액 표기)."""
    if n == 0:
        return "영"
    out, b = [], 0
    while n:
        n, chunk = divmod(n, 10000)
        if chunk:
            s = ""
            for i, ch in enumerate(f"{chunk:04d}"):
                if ch != "0":
                    s += _DIGITS[int(ch)] + _SMALL[3 - i]
            out.append(s + _BIG[b])
        b += 1
    return "".join(reversed(out))


def fmt_amount(text: str) -> str:
    digits = re.sub(r"[^\d]", "", str(text or ""))
    if not digits:
        return ""
    n = int(digits)
    return f"금{n:,}원(금{korean_number(n)}원)"


def to_number(text) -> float:
    s = re.sub(r"[^\d.\-]", "", str(text or ""))
    try:
        return float(s) if s not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def fmt_number(x: float) -> str:
    return f"{int(round(x)):,}" if abs(x - round(x)) < 1e-9 else f"{x:,.2f}"


_FUNCS = {
    # 39.85*3200 = 127519.99999… 같은 소수 오차로 한 단위 내려가지 않게 먼저 반올림해 둔다
    "내림": lambda x, unit=1: (round(x, 6) // unit) * unit,
    "반올림": lambda x, unit=1: round(round(x, 6) / unit) * unit,
    "올림": lambda x, unit=1: -((-round(x, 6)) // unit) * unit,
    "합": lambda *xs: sum(xs),
}


def evaluate(expr: str, env: dict[str, float]) -> float:
    """계산식을 안전하게 계산한다. 칸 이름(공백·괄호가 있어도 됨), + - * / ( ), 내림·반올림·올림·합."""
    import ast
    names = sorted(env, key=len, reverse=True)
    py, local = expr, {}
    for i, n in enumerate(names):
        if n in py:
            py = py.replace(n, f" _v{i} ")
            local[f"_v{i}"] = env[n]
    py = py.replace("×", "*").replace("÷", "/").strip()
    tree = ast.parse(py, mode="eval")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in local:
                return float(local[node.id])
            raise ValueError(f"모르는 칸 이름: {node.id}")
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            ops = {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b}
            if type(node.op) in ops:
                return ops[type(node.op)]
            if isinstance(node.op, (ast.Div, ast.FloorDiv)):
                return 0.0 if b == 0 else (a / b if isinstance(node.op, ast.Div) else a // b)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
            return float(_FUNCS[node.func.id](*[ev(a) for a in node.args]))
        raise ValueError("계산식에 쓸 수 없는 글자가 있습니다")
    return ev(tree)


def compute(calcs: dict[str, str], values: dict) -> dict[str, str]:
    """계산 칸들의 값을 구한다(이름 → 쉼표 넣은 글자). 계산 칸끼리 서로 참조해도 되도록 몇 번 되풀이한다.
    입력칸 값은 values의 '입력:이름'에서, 단지기본정보는 '단지:평형1'처럼 쓴다."""
    env = {COMPLEX_PREFIX + k: to_number(v) for k, v in COMPLEX.items()}
    env.update({k[3:]: to_number(v) for k, v in values.items() if k.startswith("입력:")})
    out: dict[str, str] = {}
    for _ in range(len(calcs) + 1):
        changed = False
        for name, expr in calcs.items():
            try:
                x = evaluate(expr, env)
            except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
                s = "(계산식 오류)"
            else:
                s = fmt_number(x)
                if env.get(name) != x:
                    env[name], changed = x, True
            if out.get(name) != s:
                out[name], changed = s, True
        if not changed:
            break
    return out


def calcs_in(text: str) -> dict[str, str]:
    return {m.group(1).strip(): m.group(2).strip() for m in CALC_RE.finditer(text)}


@dataclass
class Template:
    path: str
    title: str
    receiver: str
    group: str
    body: str
    name_hint: str = ""
    first: str = ""         # 1안으로 함께 작성할 내부결재 서식 이름(서식\1안 폴더)
    memo: str = ""          # 작성자에게만 보이는 메모(공문 본문에는 들어가지 않음)
    area: str = "임대"      # 시작 화면의 분야(임대·시설·주거복지·주택관리)
    cycle: str = "수시"     # 서식 목록 묶음: 매월 작성 / 수시 작성
    options: list = field(default_factory=list)   # 골라서 2안·3안…으로 붙일 서식 이름(서식\선택안 폴더)
    none_label: str = ""    # 선택안 대상이 없을 때 체크하는 칸 이름(예: 소명대상 없음)
    bundle: str = ""        # 서식 고르기의 펼침 묶음 이름(없으면 구분으로 묶는다)
    order: int = 0          # 묶음 안 차례(0이면 파일 번호 차례)
    extras: list = field(default_factory=list)   # 본문에 안 나오고 계산에만 쓰는 입력칸(머리말 '입력:')
    carry: list = field(default_factory=list)    # 작성 후 다음 기본값으로 넘길 값 [(받을 칸, 줄 칸)]

    @property
    def _number(self) -> str:
        """파일 이름 앞 번호: '01_…' → '01', 관리업무 서식 '월별13_…' → '13'"""
        return re.sub(r"^(월별|주별|분기별|연도별|수시)", "", self.file_name.partition("_")[0])

    @property
    def sort_key(self) -> int:
        """묶음 안에서 놓이는 차례: '순서:'가 있으면 그것, 없으면 파일 번호."""
        no = self._number
        return self.order or (int(no) if no.isdigit() else 0)

    @property
    def file_name(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]

    @property
    def label(self) -> str:
        """목록 표시 이름: '01_예비입주자 …' → '01. 예비입주자 …', '월별13_저장품 구입' → '13. 저장품 구입'"""
        _, _, rest = self.file_name.partition("_")
        return f"{self._number}. {rest}" if rest else self.file_name

    def _all_text(self) -> str:
        return "\n".join((self.title, self.receiver, self.body))

    def date_fields(self) -> list[tuple[str, str]]:
        """[(항목, 대표 형식)] 처음 나온 순서. 같은 항목은 한 번만.
        달 형식으로 먼저 나왔어도 하루 날짜 형식이 함께 쓰이면 하루를 고르는 칸으로 한다."""
        seen: dict[str, str] = {}
        for m in DATE_RE.finditer(self._all_text()):
            name, style = m.group(1).strip(), (m.group(2) or "요일").strip()
            if name not in seen or (seen[name] not in DAY_STYLES and style in DAY_STYLES
                                    and seen[name] in MONTH_STYLES):
                seen[name] = style
        return list(seen.items())

    def _input_matches(self):
        text = self._all_text() + "\n" + "\n".join(self.extras)
        found = [(m.start(), m.group(1).strip(), "입력", m.group(2)) for m in INPUT_RE.finditer(text)]
        found += [(m.start(), m.group(2).strip(), m.group(1), m.group(3)) for m in NUM_RE.finditer(text)]
        return sorted(found)

    def input_fields(self) -> list[str]:
        """{입력:항목}·{숫자:항목}·{금액:항목} 칸 이름. 처음 나온 순서, 같은 항목은 한 번만."""
        return list(dict.fromkeys(name for _, name, _, _ in self._input_matches()))

    def input_kinds(self) -> dict[str, str]:
        """칸 이름 → 입력·숫자·금액"""
        out: dict[str, str] = {}
        for _, name, kind, _ in self._input_matches():
            out.setdefault(name, kind)
        return out

    def input_defaults(self) -> dict[str, str]:
        """칸 이름 → 처음 값({숫자:단가=3200}의 3200). 처음 값이 있는 칸만."""
        out: dict[str, str] = {}
        for _, name, _, default in self._input_matches():
            if default and default.strip() and name not in out:
                out[name] = default.strip()
        return out

    def uses(self, key: str) -> bool:
        return "{" + key + "}" in self._all_text()

    @property
    def internal(self) -> bool:
        return self.receiver.strip() in ("", INTERNAL)


def parse(text: str, path: str = "") -> Template:
    head, sep, body = text.replace("\r\n", "\n").partition("\n---\n")
    if not sep:
        raise ValueError(f"서식에 '---' 구분줄이 없습니다: {os.path.basename(path)}")
    meta, extras, carry = {}, [], []
    for line in head.splitlines():
        k, colon, v = line.partition(":")
        if not colon:
            continue
        k, v = k.strip(), v.strip()
        if k == "입력":             # 여러 줄 쓸 수 있다
            extras += [m.group(0) for m in re.finditer(r"\{[^{}]+\}", v)]
        elif k == "이월":
            a, arrow, b = v.partition("<-")
            if arrow:
                carry.append((a.strip(), b.strip()))
        else:
            meta[k] = v
    if not meta.get("제목"):
        raise ValueError(f"서식에 '제목:' 줄이 없습니다: {os.path.basename(path)}")
    cycle = meta.get("주기", "").strip()
    return Template(path=path, title=meta["제목"], receiver=meta.get("수신자", INTERNAL),
                    group=meta.get("구분", "기타"), body=body.strip("\n"),
                    name_hint=meta.get("이름칸", ""), first=meta.get("1안", ""),
                    memo=meta.get("메모", ""), area=meta.get("분야", "") or "임대",
                    cycle=cycle if cycle in ("매월", "매주") else "수시",
                    options=[x.strip() for x in meta.get("선택안", "").split(";") if x.strip()],
                    none_label=meta.get("없음표시", ""), bundle=meta.get("묶음", ""),
                    order=int(meta["순서"]) if meta.get("순서", "").isdigit() else 0,
                    extras=extras, carry=carry)


def load(path: str) -> Template:
    with open(path, encoding="utf-8-sig") as f:
        return parse(f.read(), path)


def load_all(folder: str) -> tuple[list[Template], list[str]]:
    """폴더의 서식을 모두 읽는다. (서식 목록, 읽지 못한 파일 설명)"""
    items, errors = [], []
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".txt") or name.startswith(("_", "~")):
            continue
        try:
            items.append(load(os.path.join(folder, name)))
        except (OSError, ValueError, UnicodeDecodeError) as ex:
            errors.append(f"{name}: {ex}")
    return items, errors


def dump(t: Template) -> str:
    head = [f"제목: {t.title}", f"수신자: {t.receiver}", f"구분: {t.group}"]
    if t.name_hint:
        head.append(f"이름칸: {t.name_hint}")
    if t.first:
        head.append(f"1안: {t.first}")
    if t.memo:
        head.append(f"메모: {t.memo}")
    if t.area != "임대":
        head.append(f"분야: {t.area}")
    if t.options:
        head.append("선택안: " + "; ".join(t.options))
    if t.none_label:
        head.append(f"없음표시: {t.none_label}")
    if t.cycle in ("매월", "매주"):
        head.append(f"주기: {t.cycle}")
    if t.bundle:
        head.append(f"묶음: {t.bundle}")
    if t.order:
        head.append(f"순서: {t.order}")
    head += [f"입력: {s}" for s in t.extras]
    head += [f"이월: {a} <- {b}" for a, b in t.carry]
    return "\n".join(head) + "\n---\n" + t.body.strip("\n") + "\n"


def save(t: Template) -> None:
    with open(t.path, "w", encoding="utf-8") as f:
        f.write(dump(t))


def set_default(t: Template, name: str, value: str) -> bool:
    """{숫자:이름=옛값}·{입력:이름=옛값}의 처음 값을 새 값으로 바꾼다(제목·본문·머리말 입력칸 모두)."""
    pat = re.compile(r"\{(숫자|입력):" + re.escape(name) + r"(?:=[^{}]*)?\}")

    def sub(m):
        return "{" + m.group(1) + ":" + name + "=" + value + "}"
    changed = False
    for attr in ("title", "body"):
        s = getattr(t, attr)
        s2 = pat.sub(sub, s)
        changed |= s2 != s
        setattr(t, attr, s2)
    extras = [pat.sub(sub, s) for s in t.extras]
    changed |= extras != t.extras
    t.extras = extras
    return changed


# ---------------- 빈칸 채우기 ----------------

def _input_value(values: dict, name: str, default) -> str:
    """입력칸 값. 화면에 그 칸이 없으면(values에 키가 없으면) 처음 값을 쓴다."""
    key = "입력:" + name
    return str(values[key] if key in values else (default or "")).strip()


def fill(text: str, values: dict, dates: dict, extras: list | None = None) -> str:
    """{날짜:…}와 {이름} 등을 채운다. 값이 없는 빈칸은 그대로 둔다(미리보기에서 보이도록).
    {계산:…}은 여기서 계산한다. extras: 계산에만 쓰는 머리말 입력칸(처음 값을 쓰려고 받는다)."""
    def date_sub(m):
        d = dates.get(m.group(1).strip())
        return fmt_date(d, m.group(2) or "") if d else m.group(0)

    def field_sub(m):
        v = str(values.get(m.group(1).strip(), "") or "").strip()
        return v if v else m.group(0)

    def input_sub(m):
        v = _input_value(values, m.group(1).strip(), m.group(2))
        return v if v else m.group(0)

    def num_sub(m):
        v = _input_value(values, m.group(2).strip(), m.group(3))
        if not v:
            return m.group(0)
        return fmt_amount(v) if m.group(1) == "금액" else fmt_number(to_number(v))

    def complex_sub(m):
        return COMPLEX.get(m.group(1).strip(), "").strip() or m.group(0)

    calcs = calcs_in(text)
    if calcs:
        results = compute(calcs, _calc_env([text] + list(extras or []), values))
        text = CALC_RE.sub(lambda m: results.get(m.group(1).strip(), m.group(0)), text)
    text = COMPLEX_RE.sub(complex_sub, NUM_RE.sub(num_sub, DATE_RE.sub(date_sub, text)))
    return FIELD_RE.sub(field_sub, INPUT_RE.sub(input_sub, text))


def _calc_env(texts: list[str], values: dict) -> dict:
    """계산에 쓸 입력칸 값: values에 없는 칸은 서식의 처음 값."""
    env = dict(values)
    for spec in texts:
        for m in INPUT_RE.finditer(spec):
            env.setdefault("입력:" + m.group(1).strip(), m.group(2) or "")
        for m in NUM_RE.finditer(spec):
            env.setdefault("입력:" + m.group(2).strip(), m.group(3) or "")
    return env


def computed(t: Template, values: dict) -> dict[str, str]:
    """서식의 계산 칸 값 전부(이월할 값을 꺼낼 때 쓴다)."""
    text = "\n".join([t.title, t.body])
    return compute(calcs_in(text), _calc_env([text] + list(t.extras), values))


def add_title_note(title: str, note: str) -> str:
    """제목 끝 괄호 안에 ', 메모'를 붙인다. 괄호가 없으면 '(메모)'를 붙인다.
    예: 주택소유 심사 결과(26년 10월 입주자정기, 40차) → …(26년 10월 입주자정기, 40차, 소명대상 없음)"""
    if title.endswith(")"):
        return f"{title[:-1]}, {note})"
    return f"{title}({note})"


def fill_receiver(text: str, values: dict) -> str:
    """수신자 줄. 주소는 선택 입력이라 비어 있으면 빼고 공백을 정리한다."""
    v = dict(values)
    if not str(v.get("주소", "") or "").strip():
        text = text.replace("{주소}", "")
    return " ".join(fill(text, v, {}).split())


def leftovers(text: str) -> list[str]:
    """채우지 않은 빈칸({…})과 서식 표시(0000, OOO …)를 중복 없이 돌려준다."""
    found = [m.group(0) for m in re.finditer(r"\{[^{}]+\}", text)]
    found += [m.group(0) for m in _UNFILLED_RE.finditer(text)]
    return list(dict.fromkeys(found))


# ---------------- 웹한글용 HTML ----------------
# LeavePromotion(draft_content.py)에서 웹한글(HwpCtrl) HTML 가져오기로 검증한 서식 규칙:
# - 상대 너비는 무시되므로 표 칸 너비를 pt로 고정한다.
# - 정렬을 안 주면 앞 문단 정렬을 이어받으므로 모든 문단·칸에 정렬을 명시한다.
# - 글꼴은 문단(p)+span(+font)에 지정해야 표 칸 안에도 적용된다.

FONT_FAMILY = "굴림"
FONT_PT = 13
TABLE_PT = 11          # 표 안 글자 크기(칸이 많은 표가 본문 폭에 들어가도록)
BODY_WIDTH_PT = 470    # A4 본문 폭 이내


def _font(pt: int) -> str:
    return f"font-family:'{FONT_FAMILY}',Gulim;font-size:{pt}pt;"


LINE_HEIGHT = "160%"
CELL_LINE_HEIGHT = "130%"


def _p(text_html: str, align: str = "justify", pt: int = FONT_PT, left: float = 0, first: float = 0,
       lh: str = LINE_HEIGHT, pre: bool = False) -> str:
    """문단 하나. left: 왼쪽 여백(pt), first: 첫 줄 들여쓰기(pt, 음수면 내어쓰기).
    pre: 빈칸을 &nbsp; 대신 그대로 살린다(브라우저 미리보기 — 굴림 &nbsp;은 빈칸보다 넓다)."""
    f = _font(pt)
    indent = f"margin-left:{left:g}pt;text-indent:{first:g}pt;" if left or first else ""
    ws = "white-space:pre-wrap;" if pre else ""
    return (f'<p align="{align}" style="text-align:{align};margin-top:0;margin-bottom:0;margin-right:0;'
            f'{indent}{ws}line-height:{lh};{f}"><span style="'
            f'{f}"><font face="{FONT_FAMILY}">{text_html}</font></span></p>')


_BLANK = _p("&nbsp;", "left")

# 항목 기호: '붙임  1.', '1.', '가.', '1)', '가)', '(1)', '(가)', '①', '㉮', '-', '*', '※', '□', '○' …
_MARK_RE = re.compile(
    r'(?:붙임 +(?:\d+\. +)?|(?:\d+\.|[가-하]\.|\d+\)|[가-하]\)|\(\d+\)|\([가-하]\)|[①-⑳]|[㉮-㉻])(?: +|$)|(?:[-*※□■○◦ㅇ•▶]|\*+)(?: +|$))')

# 굴림 글자 너비(1/1024 em). 표에 없는 글자는 한글·전각 1024, 나머지 512.
_GULIM = {' ': 341, '!': 341, '"': 384, '#': 768, '$': 612, '%': 896, '&': 704, "'": 290, '(': 384, ')': 384, '*': 512, '+': 640, ',': 342, '-': 640, '.': 342, '/': 427, '0': 588, '1': 588, '2': 588, '3': 588, '4': 588, '5': 588, '6': 588, '7': 588, '8': 588, '9': 588, ':': 342, ';': 342, '<': 640, '=': 640, '>': 640, '?': 555, '@': 1024, 'A': 661, 'B': 693, 'C': 735, 'D': 739, 'E': 640, 'F': 610, 'G': 788, 'H': 748, 'I': 276, 'J': 512, 'K': 650, 'L': 556, 'M': 832, 'N': 716, 'O': 788, 'P': 652, 'Q': 792, 'R': 682, 'S': 648, 'T': 596, 'U': 728, 'V': 614, 'W': 916, 'X': 640, 'Y': 640, 'Z': 640, '[': 512, '\\': 939, ']': 512, '^': 555, '_': 512, '`': 341, 'a': 576, 'b': 620, 'c': 586, 'd': 620, 'e': 581, 'f': 350, 'g': 620, 'h': 585, 'i': 247, 'j': 247, 'k': 512, 'l': 237, 'm': 882, 'n': 594, 'o': 620, 'p': 620, 'q': 620, 'r': 341, 's': 538, 't': 321, 'u': 584, 'v': 512, 'w': 768, 'x': 512, 'y': 512, 'z': 512, '{': 512, '|': 512, '}': 512, '~': 811, '□': 911, '■': 911, '○': 1024, '◦': 384, '●': 1024, '•': 384, '▶': 1024, '※': 1024, '·': 384, 'ㆍ': 1024, '‘': 341, '’': 341, '“': 512, '”': 512, '\xa0': 341}


def _wide(ch: str) -> bool:
    o = ord(ch)
    return (0x1100 <= o <= 0x11FF or 0x2460 <= o <= 0x24FF or 0x25A0 <= o <= 0x25FF or o == 0x203B
            or 0x2E80 <= o <= 0xA4CF or 0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFF60)


def _char_pt(ch: str, pt: float = FONT_PT) -> float:
    """굴림에서 글자 한 자의 실제 너비(pt). 빈칸은 한글의 1/3쯤, 숫자는 0.57쯤이다."""
    return pt * _GULIM.get(ch, 1024 if _wide(ch) else 512) / 1024


def _width_pt(s: str, pt: float = FONT_PT) -> float:
    return sum(_char_pt(c, pt) for c in s)


def _lead_pt(lead: str, pt: float = FONT_PT) -> float:
    """줄 앞 들여쓰기: 공문 규칙대로 빈칸 2개 = 한글 1자(2타)로 본다(실제 빈칸 너비가 아니라)."""
    return len(lead) * pt / 2


def _units(s: str) -> int:
    """고정폭으로 본 글자 칸 수(한글 2, 반각 1). 서식 txt에서 빈칸으로 맞춘 열을 찾을 때 쓴다."""
    return sum(2 if _wide(c) else 1 for c in s)


# 웹한글은 HTML의 margin/text-indent를 무시하므로, 문단 앞에 표식을 넣고 붙여 넣은 뒤 문단 모양으로 바꾼다.
PARA_MARK_RE = re.compile(r"【문단:(\d+):(-?\d+)】")


def para_mark(left_pt: float, indent_pt: float) -> str:
    """한글 문단 모양: 첫 줄은 왼쪽 여백에서, 나머지 줄은 |내어쓰기|만큼 더 들어가서 시작한다."""
    return f"【문단:{round(left_pt * 100)}:{round(indent_pt * 100)}】"


def _body_p(line: str, pt: int = FONT_PT, lh: str = LINE_HEIGHT, hwp: bool = False,
            lead_w: float | None = None) -> str:
    """본문(또는 표 칸) 한 줄. 둘째 줄부터는 항목 기호 뒤 글자에 맞춰 줄이 바뀌게(내어쓰기) 한다.
    예) '  가. 무주택 …'  → 왼쪽 여백 = '  ' (한글 1자), 첫 줄 뒤 줄은 '가. ' 실제 너비만큼 더 들어간다.
    lead_w: 들여쓰기 너비를 직접 줄 때(붙임 둘째 줄을 '붙임  ' 뒤 열에 맞출 때).
    hwp=True면 여백 대신 문단 앞에 para_mark 표식을 넣는다(웹한글용)."""
    stripped = line.lstrip(" ")
    lead = line[:len(line) - len(stripped)]
    m = _MARK_RE.match(stripped)
    head = m.group(0) if m else ""
    lead_w = _lead_pt(lead, pt) if lead_w is None else lead_w
    head_w = _width_pt(head, pt)
    if hwp:
        # 웹한글: 문단 모양은 붙여 넣은 뒤 표식으로 준다
        mark = para_mark(lead_w, -head_w) if lead_w or head_w else ""
        return _p(mark + (_line_html(stripped) or "&nbsp;"), "left", pt, lh=lh)
    return _p(escape(stripped) or "&nbsp;", "left", pt, left=lead_w + head_w, first=-head_w, lh=lh, pre=True)


def _line_html(line: str) -> str:
    """들여쓰기와 중간의 연속 공백('붙임  1.')을 &nbsp;로 바꿔 살린다."""
    stripped = line.lstrip(" ")
    inner = re.sub(r" {2,}", lambda m: " " + "&nbsp;" * (len(m.group(0)) - 1), escape(stripped))
    return "&nbsp;" * (len(line) - len(stripped)) + inner


_PIPE_OUTSIDE_RE = re.compile(r"\|(?![^{}]*\})")    # 빈칸 {날짜:일|공문} 안의 '|'는 칸 구분이 아니다


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in _PIPE_OUTSIDE_RE.split(s)]


def _is_sep(line: str) -> bool:
    return bool(re.fullmatch(r"\|\s*-{3,}\s*\|?", line.strip()))


def _table(lines: list[str], hwp: bool = False) -> str:
    header_rows = 1
    rows: list[list[str]] = []
    for ln in lines:
        if _is_sep(ln):
            header_rows = len(rows)
            continue
        rows.append(_split_row(ln))
    ncol = max(len(r) for r in rows)
    for r in rows:
        r += [""] * (ncol - len(r))

    # 칸 너비: 합치지 않은 칸 글자 수(가장 긴 줄, 상한 24) 비율로 나눈다.
    weight = [4] * ncol
    for r in rows:
        for c, cell in enumerate(r):
            if cell in ("^", "<"):
                continue
            if c + 1 >= ncol or r[c + 1] != "<":     # 합친 칸은 너비 계산에서 뺀다
                longest = max((len(x.strip()) for x in cell.split("<br>")), default=0)
                weight[c] = max(weight[c], min(longest, 24) + 2)
    total = sum(weight)
    widths = [max(28, round(BODY_WIDTH_PT * w / total)) for w in weight]

    out = [f'<table align="center" border="1" cellspacing="0" cellpadding="4" '
           f'width="{sum(widths)}pt" style="border-collapse:collapse;margin:0 auto;'
           f'width:{sum(widths)}pt;">']
    # 칸이 많은 표는 글자를 줄여 한 화면에 깔끔하게 들어가게 한다
    pt = TABLE_PT if ncol <= 6 else 9 if ncol <= 9 else 8
    f = _font(pt)
    for ri, r in enumerate(rows):
        head = ri < header_rows
        out.append("<tr>")
        for c, cell in enumerate(r):
            if cell in ("^", "<"):
                continue
            colspan = 1
            while c + colspan < ncol and r[c + colspan] == "<":
                colspan += 1
            rowspan = 1
            while ri + rowspan < len(rows) and rows[ri + rowspan][c] == "^":
                rowspan += 1
            parts = [x for x in cell.split("<br>")]
            longest = max((len(x.strip()) for x in parts), default=0)
            align = "center" if head or (longest <= 16 and len(parts) <= 3) else "left"
            w = sum(widths[c:c + colspan])
            bg = 'bgcolor="#e8e8e8" ' if head else ""
            bgs = "background:#e8e8e8;font-weight:bold;" if head else ""
            span_attr = (f' colspan="{colspan}"' if colspan > 1 else "") + \
                        (f' rowspan="{rowspan}"' if rowspan > 1 else "")
            if align == "left":
                # 왼쪽 정렬 칸: 줄마다 문단으로(항목 기호 뒤 글자에 맞춰 내어쓰기)
                body = "".join(_body_p(x, pt, CELL_LINE_HEIGHT, hwp) for x in parts)
            else:
                inner = "<br>".join(f'<span style="{f}"><font face="{FONT_FAMILY}">'
                                    f'{_line_html(x) or "&nbsp;"}</font></span>' for x in parts)
                body = f'<p align="{align}" style="text-align:{align};margin:0;{f}">{inner}</p>'
            out.append(
                f'<td{span_attr} align="{align}" valign="middle" width="{w}pt" {bg}'
                f'style="width:{w}pt;text-align:{align};vertical-align:middle;border:1px solid #000;padding:3pt 3pt;'
                f'{bgs}{f}">{body}</td>')
        out.append("</tr>")
    out.append("</table>")
    return f'<div align="center" style="text-align:center;">{"".join(out)}</div>'


ATTACH_GAP = 4         # 미리보기에서 '붙임' 뒤 빈칸 수(웹한글에서는 탭)

# 웹한글에 넣은 뒤 진짜 탭으로 바꿀 표식(붙임 1. 2. 3.을 같은 탭 위치에 맞춘다)
TAB_MARK = "【탭】"


def to_html(body: str, hwp: bool = False) -> str:
    """채운 본문 텍스트를 HTML로 바꾼다. hwp=True면 웹한글에 넣을 HTML(여백 대신 para_mark 표식)."""
    html, table = [], []
    attach = None          # 붙임 줄 뒤: (들여쓰기 칸 수, 너비) — 같은 열에서 시작하는 줄은 붙임 목록
    for line in body.split("\n") + [""]:
        if line.strip().startswith("|"):
            table.append(line)
            continue
        if table:
            html.append(_table(table, hwp))
            table = []
        # '붙임  1. …' / '      2. …' : 웹한글에서는 탭, 미리보기에서는 빈칸으로 열을 맞춘다
        m = re.match("붙임 +", line)
        if m:
            units = _units(m.group(0))
            if hwp:
                html.append(_p("붙임" + TAB_MARK + _line_html(line[m.end():]), "left"))
                attach = (units, 0)
                continue
            line = "붙임" + " " * ATTACH_GAP + line[m.end():]
            attach = (units, _width_pt("붙임" + " " * ATTACH_GAP))
        elif not line.startswith(" "):
            attach = None
        lead = len(line) - len(line.lstrip(" "))
        lead_w = attach[1] if attach and lead == attach[0] and line.strip() else None
        if hwp and lead_w is not None:
            html.append(_p(TAB_MARK + _line_html(line.strip()), "left"))
            continue
        html.append(_body_p(line, hwp=hwp, lead_w=lead_w) if line.strip() else _BLANK)
    while html and html[-1] == _BLANK:
        html.pop()
    return "".join(html)


def to_preview_text(body: str) -> str:
    """화면 미리보기용: 표 표시(| ^ < <br> |---|)를 읽기 쉬운 글로 바꾼다."""
    out = []
    for line in body.split("\n"):
        if not line.strip().startswith("|"):
            out.append(line)
            continue
        if _is_sep(line):
            continue
        cells = [("" if c in ("^", "<") else c.replace("<br>", " ")) for c in _split_row(line)]
        out.append("    ▏" + "  │  ".join(cells))
    return "\n".join(out)


def preview_html(title: str, receiver: str, body_html: str) -> str:
    """브라우저 미리보기용 전체 문서."""
    f = _font(FONT_PT)
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            f'<title>{escape(title)}</title></head>'
            f'<body style="background:#eee;margin:0;padding:24px;">'
            f'<div style="background:#fff;width:520pt;margin:0 auto;padding:40pt 36pt;'
            f'box-shadow:0 1px 4px rgba(0,0,0,.2);">'
            f'<p style="{f}margin:0 0 4pt;">수신자 : {escape(receiver)}</p>'
            f'<p style="{f}margin:0 0 4pt;">(경유)</p>'
            f'<p style="{f}margin:0 0 12pt;"><b>제&nbsp;&nbsp;목 : {escape(title)}</b></p>'
            f'{body_html}</div></body></html>')


# ---------------- 홈넷 대장에서 모은 문서 → 서식 ----------------
# 수집 도구(collector)가 저장한 {제목}.txt(+같은 이름의 .html)를 서식으로 바꾼다.
# 이름·주소·날짜·금액·전화번호 등은 빈칸({…})이나 0000 같은 자리표시로 바꾼다.

KNOWN_INFO: dict = {}          # 기본정보(관리소·단지명·담당자·전화번호). GUI가 채워 준다 → 해당 글자를 {…}로 바꾼다.


class _Html2Lines(HTMLParser):
    """웹한글이 내보낸 HTML을 줄 목록으로. 표는 서식의 '|' 표 문법으로 바꾼다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.cur: list[str] = []
        self.skip = 0
        self.depth = 0
        self.rows: list[list[dict]] = []
        self.row: list[dict] | None = None
        self.cell: dict | None = None

    def _flush(self):
        text = "".join(self.cur).replace("\xa0", " ")
        self.cur = []
        text = re.sub(r"[ \t]*\n[ \t]*", " ", text).rstrip()
        self.lines.append(text)

    def _put(self, s: str):
        if self.cell is not None:
            self.cell["parts"].append(s)
        else:
            self.cur.append(s)

    def _flush_before_block(self):
        """문단·표가 시작되기 전 남은 글자를 내보낸다. HTML 줄바꿈 공백뿐이면 빈 줄로 만들지 않고 버린다
        (진짜 빈 문단은 &nbsp;로 들어온다)."""
        raw = "".join(self.cur)
        if raw.strip(" \t\r\n"):
            self._flush()
        else:
            self.cur = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("style", "script", "head", "title"):
            self.skip += 1
        elif tag == "table":
            self.depth += 1
            if self.depth == 1:
                if self.cur:
                    self._flush_before_block()
                self.rows = []
        elif tag == "tr" and self.depth == 1:
            self.row = []
        elif tag in ("td", "th") and self.depth == 1:
            def num(k):
                try:
                    return max(1, int(re.sub(r"\D", "", a.get(k) or "1") or 1))
                except ValueError:
                    return 1
            self.cell = {"parts": [], "rs": num("rowspan"), "cs": num("colspan"), "th": tag == "th"}
        elif tag == "br":
            self._put("\n") if self.cell is not None else self._flush()
        elif tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            if self.cell is not None:
                if self.cell["parts"] and self.cell["parts"][-1] != "\n":
                    self.cell["parts"].append("\n")
            elif self.cur:
                self._flush_before_block()

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head", "title"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th") and self.depth == 1 and self.cell is not None:
            if self.row is not None:
                self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.depth == 1 and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "table":
            if self.depth == 1:
                self.lines += _table_lines(self.rows)
                self.rows = []
            self.depth = max(0, self.depth - 1)
        elif tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6") and self.cell is None:
            self._flush()

    def handle_data(self, data):
        if not self.skip:
            self._put(data)

    def result(self) -> list[str]:
        if self.cur:
            self._flush()
        return self.lines


def _cell_text(cell: dict) -> str:
    text = "".join(cell["parts"]).replace("\xa0", " ")
    parts = [re.sub(r"[ \t]*\r?\n[ \t]*", " ", p).strip() for p in text.split("\n")]
    out = "<br>".join(p for p in parts if p)
    return out.replace("|", "/")


def _table_lines(rows: list[list[dict]]) -> list[str]:
    """표를 서식의 '|' 문법으로: 위 칸과 합치기 '^', 왼쪽 칸과 합치기 '<'."""
    if not rows:
        return []
    occupied: dict = {}
    grid: list[list[str]] = []
    for r, row in enumerate(rows):
        out, c = [], 0
        for cell in row:
            while (r, c) in occupied:
                out.append("^")
                c += 1
            out.append(_cell_text(cell))
            out += ["<"] * (cell["cs"] - 1)
            for rr in range(r + 1, r + cell["rs"]):
                for kk in range(cell["cs"]):
                    occupied[(rr, c + kk)] = True
            c += cell["cs"]
        while (r, c) in occupied:
            out.append("^")
            c += 1
        grid.append(out)
    width = max(len(g) for g in grid)
    lines = ["| " + " | ".join(g + [""] * (width - len(g))) + " |" for g in grid]
    header = 0
    for row in rows:                       # <th>로만 된 맨 위 줄들이 머리글
        if row and all(c["th"] for c in row):
            header += 1
        else:
            break
    if header > 1:
        lines.insert(header, "|---|")
    return [""] + lines + [""]


def html_to_lines(html: str) -> list[str]:
    p = _Html2Lines()
    p.feed(html)
    p.close()
    return p.result()


def _norm(s: str) -> str:
    return re.sub(r"[\s|]+", "", s or "")


_PHONE_LABELS = {"연락처", "전화", "전화번호", "문의", "문의처", "담당", "담당자", "휴대폰", "핸드폰", "대표번호", "팩스"}


def _anonymize(text: str, dates: dict) -> str:
    """사람·건물·돈·날짜 같은 개별 정보를 빈칸·자리표시로 바꾼다. dates는 날짜 칸 이름표를 문서 전체에서 공유."""
    for key in ("관리소", "단지명", "담당자", "전화번호"):
        val = (KNOWN_INFO.get(key) or "").strip()
        if len(val) >= 2:
            text = text.replace(val, "{" + key + "}")
    text = re.sub(r"(?<![\d-])\d{6}-[1-4]\d{6}(?!\d)", "000000-0000000", text)          # 주민등록번호
    text = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "○○○@○○○", text)                     # 전자우편
    # 받는 분 이름·동호수·연락처는 입력칸으로: {이름} · {주소}(동·호) · {입력:연락처}
    import privacy
    labels = "|".join(re.escape(x).replace(r"\ ", r"\s*") for x in privacy.NAME_LABELS)
    text = re.sub(r"((?:" + labels + r")\s*[:：]\s*)([가-힣]{2,4})(?![가-힣])",           # '성명: 홍길동'
                  lambda m: m.group(1) + "{이름}" if privacy._name_ok(m.group(2)) else m.group(0), text)
    text = re.sub(r"(\d{1,4}\s*동\s*\d{1,4}\s*호\s*)([가-힣]{2,4})(?![가-힣])",          # '105동 814호 홍길동'
                  lambda m: m.group(1) + "{이름}" if privacy._name_ok(m.group(2), True) else m.group(0), text)
    text = re.sub(r"(?<![가-힣{])([가-힣]{2,4})(\s*(?:귀하|님)(?![가-힣]))",                  # '홍길동 귀하'
                  lambda m: "{이름}" + m.group(2) if privacy._name_ok(m.group(1), True) else m.group(0), text)
    text = re.sub(r"(?<![\d-])01[016789][-. ]?\d{3,4}[-. ]?\d{4}(?!\d)", "{입력:연락처}", text)  # 휴대전화
    text = re.sub(r"(?<![\d-])0\d{1,2}-\d{3,4}-\d{4}(?!\d)", "{입력:연락처}", text)     # 전화번호(관리소 번호는 위에서)
    text = re.sub(r"(?<![가-힣{])([가-힣]{2,4})(\s*(?:\(\s*)?\{(?:전화번호|입력:연락처)\})",  # '홍길동 010-…'의 이름
                  lambda m: "000" + m.group(2) if privacy._name_ok(m.group(1), True) else m.group(0), text)
    text = re.sub(r"(\{관리소\}-|[가-힣]+(?:관리소|지사|본부|사업소|실|부|처|센터)-)\d{3,5}", r"\g<1>0000", text)  # 문서번호
    text = re.sub(r"\d{1,4}\s*동\s*\d{1,4}\s*호", "{주소}", text)                       # 동·호
    text = re.sub(r"((?:동\s*[·.,/]?\s*호(?:수)?)\s*[:：]\s*)\d{1,4}\s*-\s*\d{1,4}(?![\d-])",  # '동호수: 105-814'
                  r"\g<1>{주소}", text)

    def date_field(label_prefix, key, style):
        label = dates.setdefault(key, f"{label_prefix}{sum(1 for k in dates if k[0] == key[0]) + 1}")
        return "{날짜:" + label + "|" + style + "}"

    def dotted(m):
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dt.date(y, mo, d)
        except ValueError:
            return m.group(0)
        return date_field("날짜", ("d", y, mo, d), "요일" if m.group(4) else "일")

    def korean(m):
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dt.date(y, mo, d)
        except ValueError:
            return m.group(0)
        return date_field("날짜", ("d", y, mo, d), "요일" if m.group(4) else "일")

    def ym(m):
        y, mo = int(m.group(1)), int(m.group(2))
        if not 1 <= mo <= 12:
            return m.group(0)
        return date_field("해당월", ("m", y, mo), "월")

    wd = r"(\([월화수목금토일]\))?"
    text = re.sub(r"(?<![\d.])(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\.?" + wd, dotted, text)
    text = re.sub(r"(?<![\d.])(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일" + wd, korean, text)
    text = re.sub(r"(?<![\d.])(\d{4})\s*년\s*(\d{1,2})\s*월(?!\s*\d)(?![가-힣]*일)", ym, text)
    text = re.sub(r"(?<![\d.])((?:19|20)\d{2})\s*\.\s*(\d{1,2})(?:\s*월|\.)?(?![\d.]|\s*\d)", ym, text)   # 2026. 10. · 2025.12 · 2026.10월
    text = re.sub(r"\d{1,3}(?:,\d{3})+", lambda m: re.sub(r"\d", "0", m.group(0)), text)   # 금액 → 0,000,000
    text = re.sub(r"\(주\)\s*[가-힣A-Za-z0-9&]+", "(주)○○○", text)                       # 업체명
    text = re.sub(r"주식회사\s*[가-힣A-Za-z0-9&]+", "주식회사 ○○○", text)
    return text


_RE_TITLE = re.compile(r"^\s*제\s*목\s*[:：]?\s*(.*)$")
_RE_RECV = re.compile(r"^\s*수\s*신\s*자?\s*[:：]?\s*(.*)$")


def _value_at(lines: list[str], i: int, rest: str) -> tuple[str, int]:
    """'제 목 …'처럼 같은 줄에 값이 있으면 그것을, '제 목' 글자만 있으면 다음 빈 줄이 아닌 줄을 값으로."""
    rest = rest.strip()
    if rest:
        return rest, i
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    return (lines[j].strip(), j) if j < len(lines) else ("", i)


def split_header(lines: list[str]) -> tuple[str, str, int | None]:
    """수집한 글의 머리에서 (제목, 수신자, 제목 값이 있는 줄 번호)를 읽는다. 못 찾으면 줄 번호 None."""
    head = lines[:60]
    t_label = next((i for i, l in enumerate(head) if re.match(r"^\s*제\s*목(?:\s|[:：]|$)", l)), None)
    if t_label is None:
        return "", "", None
    title, t_idx = _value_at(lines, t_label, _RE_TITLE.match(lines[t_label]).group(1))
    receiver = ""
    for i, l in enumerate(lines[:t_label]):
        if not re.match(r"^\s*수\s*신(?:\s|[:：]|자|$)", l):
            continue
        value, _ = _value_at(lines, i, _RE_RECV.match(l).group(1))
        if value and not re.match(r"^\(?\s*경\s*유|^참\s*조|^제\s*목", value) and i + 1 <= t_label:
            receiver = value
        break
    return title, receiver, t_idx


_NAME_HEAD_RE = re.compile(r"^(성\s*명|이\s*름|대상자|수령인|계약자|세대주|신청인|입주자|참석자|받는\s*분)")


# 본문 뒤 홈넷 서식 부분: 발신명의(…관리소장), 결재란(기안자·검토자), 시행·접수·우·전화 줄. 서식 본문에서는 뺀다
_SENDER_RE = re.compile(r"주택관리공단\s*\S*\s*(?:관리소장|사업소장|지사장|본부장|센터장|사장)\s*$|"
                        r"^\S*(?:관리소장|사업소장|지사장|본부장|센터장)\s*$")
_FOOTER_WORDS = ("시행", "접수", "기안자", "검토자", "결재권자", "협조자", "전결", "대결")


def _cut_footer(lines: list[str]) -> list[str]:
    """본문 아래 발신명의·결재란·시행 줄부터 끝까지 뺀다(표로 들어온 경우 그 표 처음부터)."""
    for i, line in enumerate(lines):
        if i == 0:
            continue
        if line.strip().startswith("|"):
            cells = [c for c in _split_row(line) if c not in ("", "^", "<")]
        else:
            cells = [line.strip()] if line.strip() else []
        sender = any(_SENDER_RE.search(c) for c in cells)
        footer = sum(1 for c in cells if c in _FOOTER_WORDS) >= 1 and line.strip().startswith("|")
        if sender or footer:
            j = i
            if line.strip().startswith("|"):          # 그 표의 첫 줄부터
                while j > 0 and lines[j - 1].strip().startswith("|"):
                    j -= 1
            out = lines[:j]
            while out and not out[-1].strip():
                out.pop()
            return out
    return lines


def _hide_names_in_tables(lines: list[str]) -> list[str]:
    """표에서 머리글이 성명·이름·대상자 … 인 열의 사람 이름(한글 2~4자)을 000으로 바꾼다."""
    out = list(lines)
    i = 0
    while i < len(out):
        if not out[i].strip().startswith("|"):
            i += 1
            continue
        j = i
        while j < len(out) and out[j].strip().startswith("|"):
            j += 1
        rows = [_split_row(l) for l in out[i:j]]
        cols = [c for c, h in enumerate(rows[0]) if _NAME_HEAD_RE.match(h.replace("<br>", ""))]
        if cols:
            for r in range(1, len(rows)):
                if _is_sep(out[i + r]):
                    continue
                for c in cols:
                    if c < len(rows[r]) and re.fullmatch(r"[가-힣]{2,4}", rows[r][c].strip()):
                        rows[r][c] = "000"
                out[i + r] = "| " + " | ".join(rows[r]) + " |"
        i = j
    return out


def from_collected(text: str, path: str = "", area: str = "주택관리") -> str:
    """수집한 문서(글자 + 같은 이름의 .html)를 서식 파일 글자('제목:… --- 본문')로 바꾼다.
    area: 서식이 놓일 분야(임대·시설·주거복지·주택관리). 서식 고르기의 '기타 공문 → 수집한 서식' 묶음에 보인다."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    lines = [re.sub(r"^\t+", lambda m: "  " * len(m.group(0)), l.rstrip()).replace("\t", "  ")
             for l in text.split("\n")]
    stem = os.path.splitext(os.path.basename(path))[0] if path else "수집한 서식"
    title, receiver, t_idx = split_header(lines)
    title = title or stem
    receiver = receiver or INTERNAL
    body = lines[t_idx + 1:] if t_idx is not None else lines

    html_path = os.path.splitext(path)[0] + ".html" if path else ""
    if html_path and os.path.isfile(html_path):      # 표 모양을 살리려면 HTML이 낫다
        try:
            with open(html_path, encoding="utf-8-sig") as f:
                hl = html_to_lines(f.read())
            key = _norm(title)[:24]
            pos = next((i for i, l in enumerate(hl) if key and key in _norm(l)), None)
            if pos is not None:
                body = hl[pos + 1:]
        except (OSError, UnicodeDecodeError):
            pass

    while body and not body[0].strip():
        body.pop(0)
    last = max((i for i, l in enumerate(body) if re.search(r"끝\.\s*$", l)), default=None)
    if last is not None:                               # '끝.' 뒤에는 안내문구(「…」·※)만 남긴다
        keep = []
        for l in body[last + 1:]:
            if not l.strip() or l.lstrip().startswith(("「", "※", "*")):
                keep.append(l)
            else:
                break
        body = body[:last + 1] + keep
    while body and not body[-1].strip():
        body.pop()
    body = ["—" if l.strip() == "---" else l for l in body]
    # 양쪽 정렬 때문에 생긴 긴 공백은 하나로(줄 앞 들여쓰기와 '붙임  '·'  끝.'의 두 칸은 그대로)
    body = [re.match(r"^\s*", l).group(0) + re.sub(r"(?<=\S) {3,}(?=\S)", " ", l.lstrip()) for l in body]
    body = _cut_footer(body)
    body = _hide_names_in_tables(body)
    in_attach = False                                   # 붙임 아래 둘째 항목은 첫 항목 숫자에 맞춰 6칸
    for i, l in enumerate(body):
        if re.match(r"^\s*붙\s*임", l):
            in_attach = True
        elif not l.strip():
            in_attach = False
        elif in_attach and re.match(r"^\s*\d+\.\s", l):
            body[i] = "      " + l.strip()
    out: list[str] = []
    for l in body:                                      # 연속 빈 줄은 하나로
        if l == "" and out and out[-1] == "":
            continue
        out.append(l)
    body = out

    dates: dict = {}
    title = _anonymize(title, dates).replace("\n", " ")
    body_text = _anonymize("\n".join(body), dates)
    group = "수집한 서식" if receiver == INTERNAL else "수집한 서식(수신자 있음)"
    if receiver != INTERNAL:
        receiver = _anonymize(receiver, dates)
    binder = ""
    meta_path = os.path.splitext(path)[0] + ".meta.json" if path else ""
    if meta_path and os.path.isfile(meta_path):         # 수집할 때 함께 저장한 편철
        try:
            import json
            with open(meta_path, encoding="utf-8-sig") as f:
                binder = str(json.load(f).get("편철", "") or "").strip()
        except (OSError, ValueError):
            binder = ""
    memo = "홈넷 대장에서 모은 문서로 만든 서식 — 쓰기 전에 남은 개인정보가 없는지 확인하세요."
    if binder:
        memo += f" 원본 편철: {binder}"
    head = (f"제목: {title}\n수신자: {receiver}\n구분: {group}\n분야: {area or '주택관리'}\n"
            f"묶음: {group}\n메모: {memo}\n")
    return f"{head}---\n{body_text}\n"
