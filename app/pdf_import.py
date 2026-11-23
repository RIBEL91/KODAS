"""[나의 공문 업로드]: 사용자가 고른 공문 PDF를 읽어 서식(.txt)으로 만든다.

- PDF 글자를 줄 단위로 다시 맞춘다(한글 프로그램에서 PDF로 바꾸면 숫자·괄호가 따로 떨어져 나온다 → 글자 상자
  위치로 같은 줄을 묶고 왼쪽부터 잇는다). 겹쳐 두 번 찍힌 글자(굵게 흉내)는 하나만 둔다.
- 서식 만들기는 대장 문서 받기와 같은 doc_template.from_collected를 쓴다(제목·수신자 읽기, 결재란·시행 줄 빼기,
  이름·동호수·연락처 → 입력칸, 날짜 → 날짜 칸, 관리소·단지명·담당자·전화번호 → {…}).
- 서식 폴더의 '수집한 서식' 아래에 두고, 서식 고르기에서는 'PDF로 넣은 서식' 묶음으로 보인다.
"""
from __future__ import annotations

import os
import re

BUNDLE = "PDF로 넣은 서식"


class PdfImportError(Exception):
    pass


def page_chars(page) -> list:
    """쪽의 글자 하나하나 [(x0, y0, x1, y1, 글자)] — 낱말 단위보다 정확하다(괄호·작은 글씨 차례가 맞는다)."""
    out = []
    for blk in page.get_text("rawdict")["blocks"]:
        for line in blk.get("lines", []):
            for span in line["spans"]:
                for c in span["chars"]:
                    if c["c"].strip():
                        out.append((*c["bbox"], c["c"]))
    return out


def join_words(words: list) -> list[str]:
    """글자(또는 낱말) 상자 [(x0, y0, x1, y1, 글자, …)]를 줄 글자 목록으로. 띄어쓰기는 상자 사이 틈으로 정한다."""
    seen, ws = set(), []
    for w in words:
        key = (w[4], round(w[0]), round(w[1]))
        if key in seen:                          # 같은 자리에 두 번 찍힌 글자
            continue
        seen.add(key)
        ws.append(w)
    ws.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows: list[dict] = []
    for w in ws:
        cy, h = (w[1] + w[3]) / 2, max(1.0, w[3] - w[1])
        if rows and abs(rows[-1]["cy"] - cy) < max(2.5, h * 0.35):
            rows[-1]["w"].append(w)
        else:
            rows.append({"cy": cy, "w": [w]})
    out = []
    for r in rows:
        r["w"].sort(key=lambda w: w[0])
        s, prev = "", None
        for w in r["w"]:
            if prev is not None:
                gap, h = w[0] - prev[2], max(1.0, w[3] - w[1])
                if gap > h * 2:
                    s += "   "
                elif gap > h * 0.15:
                    s += " "
            s += w[4]
            prev = w
        out.append(s)
    return out


def pdf_lines(path: str, passwords=()) -> list[str]:
    import pymupdf
    try:
        doc = pymupdf.open(path)
    except Exception as ex:
        raise PdfImportError(f"PDF를 열지 못했습니다({ex})")
    try:
        if doc.needs_pass and not any(doc.authenticate(p) for p in passwords if p):
            raise PdfImportError("암호가 걸린 PDF입니다")
        lines = []
        for page in doc:
            lines += join_words(page_chars(page))
            lines.append("")
    finally:
        doc.close()
    if not any(l.strip() for l in lines):
        raise PdfImportError("글자가 없는 PDF입니다(스캔한 그림 PDF는 읽지 못합니다)")
    return lines


def to_template_text(path: str, area: str | None = None, passwords=()) -> str:
    """PDF 한 개 → 서식 파일 글자. area가 없으면 제목으로 분야를 정한다."""
    import binder_rules
    import doc_template
    text = "\n".join(pdf_lines(path, passwords))
    title, _recv, _i = doc_template.split_header(text.split("\n"))
    if not title:
        raise PdfImportError("공문 제목(제목 줄)을 찾지 못했습니다")
    area = area or binder_rules.area_for("", title)
    out = doc_template.from_collected(text, path, area)
    out = re.sub(r"(?m)^묶음:.*$", "묶음: " + BUNDLE, out, count=1)
    out = re.sub(r"(?m)^메모:.*$", "메모: PDF로 넣은 공문으로 만든 서식 — 쓰기 전에 남은 개인정보가 없는지 확인하세요. "
                 "원본: " + os.path.basename(path).replace("\\", "/"), out, count=1)
    doc_template.parse(out, path)                     # 서식으로 읽히는지 확인
    return out


def import_pdfs(files: list[str], dest: str, log=print, passwords=()) -> tuple[list[str], list[tuple[str, str]]]:
    """PDF들을 서식으로 만들어 dest에 둔다. (만든 서식 경로들, [(PDF 이름, 못 넣은 까닭)])."""
    import collector
    import doc_template
    os.makedirs(dest, exist_ok=True)
    made, failed = [], []
    for f in files:
        name = os.path.basename(f)
        try:
            text = to_template_text(f, passwords=passwords)
        except PdfImportError as ex:
            failed.append((name, str(ex)))
            log(f"  ✗ {name}: {ex}")
            continue
        except Exception as ex:                       # 예상 못 한 PDF 모양
            failed.append((name, f"읽지 못했습니다({ex})"))
            log(f"  ✗ {name}: {ex}")
            continue
        title = doc_template.parse(text, f).title
        base = collector.safe_name(re.sub(r"\{[^{}]*\}", "○", title), 0, set()) or os.path.splitext(name)[0]
        path, k = os.path.join(dest, base + ".txt"), 2
        while os.path.exists(path):
            path = os.path.join(dest, f"{base} ({k}).txt")
            k += 1
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        made.append(path)
        log(f"  ✓ {name} → 서식 '{os.path.basename(path)}'")
    return made, failed
