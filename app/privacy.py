"""대장에서 받은 문서·PDF의 개인정보(이름·동호수·연락처·주민번호)를 000으로 가린다.

- find_private(text): 글자에서 가릴 곳을 찾는다 → [(찾은 글자, 바꿀 글자, 종류)]
- mask_text / mask_html: 글자·HTML의 가릴 곳을 000으로 바꾼다
- mask_pdf: PDF의 가릴 곳을 지우고(검은 칠 대신 흰 바탕) 그 자리에 000을 쓴다. 원본 글자는 PDF에서 지워진다.
이 PC 안에서만 처리한다(어디로도 보내지 않는다).
"""
import html as _html
import os
import re

NAME_MASK = "000"
ADDR_MASK = "000동 000호"
PHONE_MASK = "000-0000-0000"
RRN_MASK = "000000-0000000"

# '성명: 홍길동'처럼 이 말 뒤에 오는 한글 2~4자는 사람 이름
NAME_LABELS = ("성명", "성 명", "이름", "이 름", "대상자", "수령인", "계약자", "세대주", "신청인", "입주자", "임차인",
               "상속인", "사망자", "참석자", "받는 분", "받는분", "민원인", "피상속인", "승계인", "보호자", "명의자")
# 이름처럼 보여도 이름이 아닌 말(귀하·님 앞, 동호 뒤, 전화번호 앞에 자주 오는 말)
NOT_NAMES = {
    "관리소장", "소장", "입주자", "입주민", "세대주", "계약자", "고객", "주민", "여러분", "회원", "선생", "담당자", "담당",
    "신청인", "임차인", "대표", "회장", "위원장", "통장", "반장", "세대", "거주", "소유", "귀하", "가구", "호실", "동대표",
    "연락처", "전화", "전화번호", "문의", "문의처", "휴대폰", "핸드폰", "대표번호", "팩스", "관리소", "관리사무소",
    "센터", "본부", "지사", "사업소", "주무", "과장", "차장", "부장", "대리", "주임", "사원", "직원", "기사", "경비",
    "미화", "상속인", "보호자", "민원인", "명의자", "승계인", "대상자", "수령인", "참석자", "성명", "이름", "입주", "퇴거",
    "갱신", "계약", "명도", "안내", "통보", "결과", "현황", "목록", "명단", "내역", "합계", "소계", "비고", "확인",
    "외", "등", "님", "씨", "부부", "가족", "본인", "배우자", "자녀", "임대인", "임대", "공단", "주택", "아파트",
    "민원", "누수", "거주자", "거주지", "관련", "처리", "방문", "점검", "공사", "보수", "수리", "교체", "하자", "소음",
    "층간", "이사", "전입", "전출", "체납", "연체", "납부", "미납", "주차", "차량", "화재", "사고", "신고", "요청",
    "접수", "조치", "완료", "예정", "대상", "세대원", "동거인", "보증금", "임대료", "관리비", "정산", "검침", "현관",
    "베란다", "욕실", "주방", "거실", "안방", "배관", "누전", "정전", "단수", "승강기", "엘리베이터", "공용", "전용",
    "고지서", "통지서", "안내문", "신청서", "확인서", "증명서", "계약서", "위임장", "서류", "제출", "기한", "기간",
    "사진", "도면", "자료", "첨부", "별첨", "붙임", "참고", "내용", "사항", "사유", "의견", "답변", "회신", "협조",
    "선정", "제외", "포함", "변경", "해지", "만료", "연장", "종료", "시작", "개시", "실시", "진행", "보고", "결재",
    "전송", "홈페이지", "누리집", "우편", "우편번호", "주소", "공개", "비공개", "부분공개", "시행", "기안자", "검토자",
    "결재권자", "협조자", "사망", "사망자", "상속", "유족", "없음", "해당", "해당없음", "미정", "미상",
}

# 성씨(앞 글자). 이름표 없이 짐작으로 찾은 이름(귀하·님 앞, 동호 뒤, 전화번호 앞)은 성씨로 시작해야 이름으로 본다
SURNAMES = set("김이박최정강조윤장임한오서신권황안송류유전홍고문양손배백허남심노하곽성차주우구민나진지엄채원천방"
               "공현함변염여추도소석선설마길연위표명기반라왕금옥육인맹제모탁국어은편용예경봉사부가복태목형피두감"
               "음빈동온호범좌팽승간상갈단견당화창")

_HANGUL_NAME = r"[가-힣]{2,4}"
_SP = r"(?:\s|&nbsp;)*"                # 빈칸(HTML의 &nbsp; 포함). \s가 \xa0도 맞춘다 — 따로 넣지 말 것

_RRN_RE = re.compile(r"(?<![\d-])\d{6}\s*-\s*[1-4]\d{6}(?!\d)")
_ADDR_RE = re.compile(r"(?<!\d)\d{1,4}" + _SP + r"동" + _SP + r"\d{1,4}" + _SP + r"호")
_ADDR_DASH_RE = re.compile(r"((?:동\s*[·.,/]?\s*호(?:수)?|주\s*소)\s*[:：]?\s*)(\d{1,4}\s*-\s*\d{1,4})(?![\d-])")
_MOBILE_RE = re.compile(r"(?<![\d-])01[016789](?:\s*[-.)]\s*|\s?)\d{3,4}(?:\s*[-.]\s*|\s?)\d{4}(?!\d)")
_PHONE_RE = re.compile(r"(?<![\d-])0\d{1,2}\s*[-)]\s*\d{3,4}\s*-\s*\d{4}(?!\d)")
_LABEL_NAME_RE = re.compile(r"(?:" + "|".join(re.escape(x) for x in NAME_LABELS) + r")\s*[:：]\s*(" + _HANGUL_NAME
                            + r")(?![가-힣])")
_HONOR_RE = re.compile(r"(?<![가-힣])(" + _HANGUL_NAME + r")" + _SP + r"(?:귀하|님)(?![가-힣])")
_AFTER_ADDR_RE = re.compile(r"\d{1,4}" + _SP + r"동" + _SP + r"\d{1,4}" + _SP + r"호" + _SP + r"(?:[(\[]" + _SP + r")?"
                            + r"(" + _HANGUL_NAME + r")(?![가-힣])")
_BEFORE_PHONE_RE = re.compile(r"(?<![가-힣])(" + _HANGUL_NAME + r")" + _SP + r"(?:[(\[]" + _SP + r")?"
                              + r"(?=01[016789]|0\d{1,2}\s*[-)])")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _name_ok(name: str, guess: bool = False) -> bool:
    """사람 이름으로 볼 만한지. guess: 이름표('성명:' 등) 없이 짐작한 것 — 성씨로 시작해야 한다."""
    if name in NOT_NAMES or len(name) < 2:
        return False
    if re.search(r"(관리|사무|센터|본부|지사|공단|주택|아파트|단지|세대|민원|처리|관련)", name):
        return False
    return not guess or (name[0] in SURNAMES and name[1:] not in NOT_NAMES)


def find_private(text: str, extra=(), keep_phones=()) -> list[tuple[str, str, str]]:
    """가릴 곳 [(찾은 글자, 바꿀 글자, 종류)]. 종류: 이름·동호수·연락처·주민번호.

    extra: 사용자가 직접 넣은 '꼭 가릴 글자'(이름·동호수·연락처 등). 문서 어디에 있든 가린다.
    keep_phones: 가리지 않을 전화번호(관리소 대표번호 등).
    """
    text = text or ""
    keep = {_digits(p) for p in keep_phones if _digits(p)}
    out: list[tuple[str, str, str]] = []
    seen = set()

    def add(s: str, repl: str, kind: str):
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            out.append((s, repl, kind))

    for m in _RRN_RE.finditer(text):
        add(m.group(0), RRN_MASK, "주민번호")
    names = []
    for rx, guess in ((_LABEL_NAME_RE, False), (_HONOR_RE, True), (_AFTER_ADDR_RE, True), (_BEFORE_PHONE_RE, True)):
        for m in rx.finditer(text):
            if _name_ok(m.group(1), guess):
                names.append(m.group(1))
    for m in _ADDR_RE.finditer(text):
        add(m.group(0), ADDR_MASK, "동호수")
    for m in _ADDR_DASH_RE.finditer(text):
        add(m.group(2), "000-000", "동호수")
    for rx in (_MOBILE_RE, _PHONE_RE):
        for m in rx.finditer(text):
            if _digits(m.group(0)) not in keep:
                add(m.group(0), PHONE_MASK, "연락처")
    for n in names:                       # 한 번 이름으로 찾은 글자는 문서 어디에 있든 가린다(표·서명란 등)
        add(n, NAME_MASK, "이름")
    for w in extra:
        w = (w or "").strip()
        if not w:
            continue
        if _ADDR_RE.fullmatch(w):
            add(w, ADDR_MASK, "동호수")
        elif _MOBILE_RE.fullmatch(w) or _PHONE_RE.fullmatch(w):
            add(w, PHONE_MASK, "연락처")
        else:
            add(w, NAME_MASK, "이름")
    # 긴 글자부터 바꿔야 '홍길동'보다 '105동 814호 홍길동'이 먼저 맞는다
    out.sort(key=lambda x: -len(x[0]))
    return out


def _flex(s: str) -> str:
    """찾은 글자를 빈칸·&nbsp;가 달라도 맞도록 정규식으로."""
    parts = [re.escape(p) for p in re.split(r"\s+", s) if p]
    return _SP.join(parts)


def mask_text(text: str, extra=(), keep_phones=(), found=None) -> tuple[str, list]:
    """글자의 가릴 곳을 000으로 바꾼다. (바뀐 글자, 가린 목록)"""
    found = find_private(text, extra, keep_phones) if found is None else found
    for s, repl, _kind in found:
        if _name_like(s):
            text = re.sub(r"(?<![가-힣])" + _flex(s) + r"(?![가-힣])", repl, text)
        else:
            text = re.sub(_flex(s), repl, text)
    return text, found


def _name_like(s: str) -> bool:
    return bool(re.fullmatch(r"[가-힣]{2,4}", s))


_TAG_RE = re.compile(r"(<[^>]*>)")


def mask_html(html: str, extra=(), keep_phones=(), found=None) -> tuple[str, list]:
    """HTML의 글자 부분(태그 밖)만 가린다. 태그·스타일은 그대로 둔다."""
    parts = _TAG_RE.split(html or "")
    plain = " ".join(_html.unescape(p) for p in parts[::2])
    found = find_private(plain, extra, keep_phones) if found is None else found
    for i in range(0, len(parts), 2):
        if parts[i].strip():
            masked, _ = mask_text(_html.unescape(parts[i]), found=found)
            if masked != _html.unescape(parts[i]):
                parts[i] = _html.escape(masked, quote=False)
    return "".join(parts), found


def pdf_text(path: str) -> str:
    import pymupdf as fitz
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


class PdfLocked(Exception):
    """암호가 걸려 열 수 없는 PDF(읽을 수 없으니 가릴 수도 없다)."""


def mask_pdf(src: str, dst: str, extra=(), keep_phones=(), known=()) -> dict:
    """PDF의 가릴 곳을 지우고 000을 쓴다.

    known: 같은 문서 본문에서 이미 찾은 가릴 곳(find_private 결과) — 첨부 PDF에도 같이 적용한다.
    돌려주는 값: {'masked': 가린 곳 수, 'kinds': {종류: 수}, 'scanned': 글자 없는 쪽 수, 'pages': 쪽 수}
    """
    import pymupdf as fitz
    doc = fitz.open(src)
    try:
        if doc.needs_pass:
            raise PdfLocked("암호가 걸린 PDF")
        text = "\n".join(page.get_text() for page in doc)
        found = find_private(text, extra, keep_phones)
        have = {s for s, _, _ in found}
        found += [x for x in known if x[0] not in have and x[0] in re.sub(r"\s+", " ", text)]
        masked, kinds, scanned = 0, {}, 0
        for page in doc:
            ptext = page.get_text()
            if not ptext.strip():
                scanned += 1               # 스캔(그림)만 있는 쪽: 글자를 찾을 수 없다
                continue
            hits = []
            for s, repl, kind in found:           # 긴 글자부터: '105동 814호 홍길동' 안의 '홍길동'은 한 번만
                if _name_like(s):
                    # 이름은 앞뒤가 한글이 아닐 때만(예: '김철수'를 '김철수동'에서 가리지 않게)
                    if not re.search(r"(?<![가-힣])" + re.escape(s) + r"(?![가-힣])", ptext):
                        continue
                for rect in page.search_for(s):
                    if not any(_inside(rect, h[0]) for h in hits):
                        hits.append((rect, repl, kind))
            for rect, _repl, kind in hits:
                # 상자를 조금 줄여 옆 글자('귀하'의 '귀' 등)까지 지우지 않게 한다
                dx, dy = min(1.2, rect.width * 0.04), rect.height * 0.22
                page.add_redact_annot(fitz.Rect(rect.x0 + dx, rect.y0 + dy, rect.x1 - dx, rect.y1 - dy),
                                      fill=False)   # 흰 칠은 옆 글자까지 덮어 쓰지 않는다
                kinds[kind] = kinds.get(kind, 0) + 1
            if hits:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
                for rect, repl, _kind in hits:    # 지운 자리에 000을 쓴다(한글 글꼴로)
                    _write(page, rect, repl)
                masked += len(hits)
        doc.save(dst, garbage=3, deflate=True)
        return {"masked": masked, "kinds": kinds, "scanned": scanned, "pages": len(doc)}
    finally:
        doc.close()


def _inside(a, b) -> bool:
    """a 상자가 b 상자 안에 (거의) 들어가는지."""
    return a.x0 >= b.x0 - 0.5 and a.x1 <= b.x1 + 0.5 and a.y0 >= b.y0 - 0.5 and a.y1 <= b.y1 + 0.5


_KO_FONT = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "malgun.ttf")


def _write(page, rect, text: str) -> None:
    """지운 상자 자리에 글자를 쓴다. 맑은 고딕이 없으면 영문 글꼴로 숫자만 쓴다."""
    size = max(5.0, min(14.0, rect.height * 0.72))
    base = (rect.x0, rect.y1 - rect.height * 0.24)
    if os.path.isfile(_KO_FONT):
        page.insert_text(base, text, fontname="kodasko", fontfile=_KO_FONT, fontsize=size)
    else:
        page.insert_text(base, re.sub(r"[^\x20-\x7e]", "", text), fontname="helv", fontsize=size)


def summary(kinds: dict) -> str:
    return ", ".join(f"{k} {v}곳" for k, v in kinds.items()) or "가릴 곳 없음"
