"""'조회' 화면(본문 없는 접수 등록 문서)은 저장하지 않고, 나머지는 모두 저장하는지 — 가짜 브라우저로 시험."""
import collector

VIEW_TEXT = ("조회\n편철\t유관기관 관계철\n제목\t{t}\n생산처리과기관코드\tA355060\t생산(접수)등록번호\tA355060-002569\n"
             "등록구분\t일반문서 접수\t시행일자\t2026/10/26\n")
BASE = "https://gw.kohom.or.kr/nanum/cflow/archives/"


def doc_text(title, receiver="내부결재"):
    return f"주택관리공단\n수신자 {receiver}\n(경유)\n제 목 {title}\n\n1. 본문입니다.  끝.\n"


class _Alert:
    @property
    def alert(self):
        raise RuntimeError("no alert")


class FakeDriver:
    """창(핸들 → 주소·글자)과 [다음] 순서만 흉내 낸다. items: (종류, 제목) — doc · view(같은 창) · popup(새 창)"""

    def __init__(self, items, view_has_next=True):
        self.items, self.pos, self.view_has_next = items, 0, view_has_next
        self.win = {"MAIN": ("https://homnet.kohom.or.kr/main", "")}
        self.cur = "MAIN"
        self.closed, self.viewer = [], "V"
        self._show("V", 0)

    def _show(self, h, i):
        kind, title = self.items[i]
        if kind == "doc":
            self.win[h] = (BASE + "ledger/ledger_dochandler.jsp", doc_text(title, "OOO 귀하" if "안내" in title else "내부결재"))
        elif kind == "view":
            self.win[h] = (BASE + "dialog/ledger/view_handdocument.jsp?DOC_ID=1", VIEW_TEXT.format(t=title))
        else:                                   # popup: 문서 창은 그대로, 새 창에 '조회'
            self.win[f"P{i}"] = (BASE + "dialog/ledger/view_handdocument.jsp?DOC_ID=2", VIEW_TEXT.format(t=title))

    # --- selenium 흉내 ---
    @property
    def window_handles(self):
        return list(self.win)

    @property
    def current_window_handle(self):
        return self.cur

    @property
    def current_url(self):
        return self.win[self.cur][0]

    @property
    def switch_to(self):
        drv = self

        class S(_Alert):
            def window(self, h):
                if h not in drv.win:
                    raise RuntimeError("no window")
                drv.cur = h

            def default_content(self):
                pass
        return S()

    def execute_script(self, js, *a):
        if js == collector._JS_PAGE_TEXT:
            return self.win[self.cur][1]
        return None

    def close(self):
        self.closed.append(self.cur)
        del self.win[self.cur]

    def next(self):
        if "view_handdocument" in self.win[self.viewer][0] and not self.view_has_next:
            return False
        if self.pos + 1 >= len(self.items):
            return False
        self.pos += 1
        self._show(self.viewer, self.pos)
        return True

    def open_after(self, title):
        i = next(i for i, (_, t) in enumerate(self.items) if t == title) + 1
        if i >= len(self.items):
            raise collector.CollectError("다음 줄 없음")
        self.pos = i
        self.viewer = "V2"
        self._show("V2", i)
        return "V2"


def run(monkeypatch, tmp_path, drv, count=10):
    def read_doc(driver, log=None):
        url, text = driver.win[driver.cur]
        return {"html": "" if "view_hand" in url else "<p>x</p>", "text": text, "source": "test"}

    monkeypatch.setattr(collector, "read_doc", read_doc)
    monkeypatch.setattr(collector, "click_next", lambda d: d.next())
    monkeypatch.setattr(collector, "read_doc_info", lambda d, h, log=None:
                        {"raw": "", "binder_raw": "", "binder": "", "kind": "생산"})
    monkeypatch.setattr(collector, "password_prompt", lambda d: False)
    monkeypatch.setattr(collector, "drain_alerts", lambda *a, **k: "")
    monkeypatch.setattr(collector.time, "sleep", lambda s: None)
    monkeypatch.setattr(collector, "_close_window", lambda d, h: d.win.pop(h, None) and d.closed.append(h))
    monkeypatch.setattr(collector, "open_first_doc", lambda d, kw, log, after_title="": d.open_after(after_title))
    monkeypatch.setattr(collector, "find_viewer", lambda d: "V")
    logs = []
    res = collector.collect(drv, str(tmp_path), count, logs.append)
    return res, logs


def test_view_screens_skipped_rest_saved(monkeypatch, tmp_path):
    drv = FakeDriver([("doc", "건물명도 소송통고 안내(1차)"), ("view", "종이팩 분리배출 협조 요청"),
                      ("doc", "승강기 자체점검 결과 보고"), ("popup", "유관기관 회의 참석 요청"),
                      ("doc", "단지 대청소 실시")])
    res, logs = run(monkeypatch, tmp_path, drv)
    assert res["names"] == ["건물명도 소송통고 안내(1차)", "승강기 자체점검 결과 보고", "단지 대청소 실시"]
    assert res["views"] == 2 and res["skipped"] == 0
    assert "P3" in drv.closed                                   # 새 창으로 뜬 '조회' 창은 닫는다
    assert not any("종이팩" in f or "유관기관" in f for f in __import__("os").listdir(tmp_path))


def test_view_without_next_continues_from_list(monkeypatch, tmp_path):
    drv = FakeDriver([("doc", "첫 문서 보고"), ("view", "접수 문서 하나"), ("doc", "다음 문서 보고")],
                     view_has_next=False)
    res, logs = run(monkeypatch, tmp_path, drv)
    assert res["names"] == ["첫 문서 보고", "다음 문서 보고"] and res["views"] == 1
    assert "V" in drv.closed


def test_helpers():
    t = VIEW_TEXT.format(t="공동주택 종이팩 분리배출제 시행 준비 및 홍보 협조 요청")
    assert collector.is_view_only(t) and collector.is_view_only("", BASE + "dialog/ledger/view_handdocument.jsp")
    assert not collector.is_view_only(doc_text("보고"), BASE + "ledger/ledger_dochandler.jsp")
    assert collector.view_title(t) == "공동주택 종이팩 분리배출제 시행 준비 및 홍보 협조 요청"
    rows = [{"text": ["접수", "A 보고"]}, {"text": ["생산", "B 보고"]}, {"text": ["생산", "C"]}]
    assert collector.row_after(rows, "A  보고") == 1 and collector.row_after(rows, "C") is None
    assert collector.row_after(rows, "없음") is None
