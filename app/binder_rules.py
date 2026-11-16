"""편철(기록물철) 이름으로 서식 분야를 정한다.

홈넷 [문서정보]의 편철 예: '교육훈련관계철(1)' → 기록물철 '교육훈련관계철' → 분야 '주택관리'.
편철을 못 읽었으면 문서 제목의 낱말로 정하고, 그래도 모르면 기본 분야를 쓴다.
규칙은 위에서부터 먼저 맞는 것을 쓴다(더 좁은 말을 위에 둔다).
"""
import re

AUTO = "자동(편철)"
AREAS = ("임대", "시설", "주거복지", "주택관리")

# (분야, 낱말들) — 편철 이름이나 제목에 낱말이 들어 있으면 그 분야
RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("주택관리", ("용역", "회계", "관리비", "교육훈련")),        # '용역계약'이 임대로 가지 않도록 먼저
    ("주거복지", ("주거복지", "복지", "마이홈", "공동체", "돌봄", "간담회", "협의체", "클린데이", "나누리",
              "주거행복", "시니어", "이웃", "안부", "폭염", "건강체조", "체조교실")),
    ("임대", ("임대", "보증금", "임차", "계약", "입주자격", "입주자", "예비입주", "재임대", "갱신", "명도",
            "승계", "주택소유", "소명", "어린이집", "분양", "퇴거", "해지")),
    ("시설", ("시설", "승강기", "안전", "소방", "전기", "기계", "설비", "보수", "공사", "수선", "조경",
            "전지", "제초", "당직", "에너지", "난방", "급탕", "보일러", "재활용", "폐기물", "환경정비", "점검")),
    ("주택관리", ("관리비", "회계", "예산", "결산", "출납", "예금", "자금", "부금", "징수", "정산", "잡수입",
              "교육", "훈련", "인사", "복무", "근무", "청렴", "갑질", "민원", "용역", "경비", "청소",
              "서무", "문서", "보고", "공개", "소식지", "회보", "저장품", "물품", "보험")),
)


def clean(binder: str) -> str:
    """'교육훈련관계철(1)' → '교육훈련관계철' (뒤의 (숫자)는 권호)."""
    return re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", (binder or "").strip())


def _match(text: str) -> str:
    t = re.sub(r"\s+", "", text or "")
    if not t:
        return ""
    for area, words in RULES:
        if any(w in t for w in words):
            return area
    return ""


def area_for(binder: str, title: str = "", default: str = "주택관리") -> str:
    """편철 → 분야. 편철로 모르면 제목으로, 그래도 모르면 default."""
    return _match(clean(binder)) or _match(title) or (default if default in AREAS else "주택관리")


def matches(binder: str, wanted) -> bool:
    """편철이 고른 편철 낱말(여러 개) 중 하나를 품는지. wanted가 비면 모두 True."""
    words = [re.sub(r"\s+", "", w) for w in (wanted or ()) if w and w.strip()]
    if not words:
        return True
    b = re.sub(r"\s+", "", clean(binder))
    return bool(b) and any(w in b for w in words)
