import work_schedule as ws


def test_slots_by_kind():
    assert ws.slots(ws.new_task("a"), 2026, 11) == [("done", "")]
    assert ws.slots(ws.new_task("b", "매월"), 2026, 11) == [("2026-11", "11월")]
    assert [k for k, _ in ws.slots(ws.new_task("c", "분기별"), 2026, 11)] == [
        "2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]
    t = ws.new_task("d", "정해진 달", [11, 3, 5, 3])
    assert t["months"] == [3, 5, 11]
    assert [lab for _, lab in ws.slots(t, 2026, 1)] == ["3월", "5월", "11월"]


def test_current_slot_and_done():
    q = ws.new_task("중복입주", "분기별")
    assert ws.current_slot(q, 2026, 11) == "2026-Q4"
    m = ws.new_task("정례화", "정해진 달", [3, 5])
    assert ws.current_slot(m, 2026, 4) is None
    ws.set_done(q, "2026-Q4", True)
    assert ws.is_done(q, "2026-Q4") and not ws.is_done(q, "2027-Q4")
    ws.set_done(q, "2026-Q4", False)
    assert not ws.is_done(q, "2026-Q4")


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "store_path", lambda: str(tmp_path / "s.json"))
    assert ws.load()                       # 처음에는 기본 업무
    t = ws.new_task("새 업무", "매월")
    ws.set_done(t, "2026-11", True)
    ws.save([t])
    got = ws.load()
    assert len(got) == 1 and got[0]["title"] == "새 업무" and ws.is_done(got[0], "2026-11")


def test_render_month_tokens():
    assert ws.render("갱신세대 소명안내({월+3})", 2026, 11) == "갱신세대 소명안내(2월)"
    assert ws.render("갱신세대 소명안내({월+3})", 2026, 12) == "갱신세대 소명안내(3월)"
    assert ws.render("{월-1} 변동정보", 2027, 1) == "12월 변동정보"
    assert ws.render("({년월+6}갱신)", 2026, 11) == "(27.5월갱신)"
    assert ws.render("{연도월+2} 납부안내", 2026, 11) == "2027.1월 납부안내"
    assert ws.render("그냥 업무", 2026, 11) == "그냥 업무"


def test_all_app_modules_compile():
    """화면 모듈도 문법 오류 없이 읽히는지(테스트가 import하지 않는 창 모듈 포함)."""
    import glob
    import os
    import py_compile
    app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
    for f in glob.glob(os.path.join(app, "*.py")):
        py_compile.compile(f, doraise=True)


def test_move_within_group():
    a, b, q, c = ws.new_task("a", "매월"), ws.new_task("b"), ws.new_task("q", "분기별"), ws.new_task("c", "매월")
    tasks = [a, b, q, c]
    kinds = ("일반", "매월")
    assert ws.move(tasks, c, -1, kinds)            # 분기별 q는 건너뛰고 b와 바뀐다
    assert [t["title"] for t in tasks] == ["a", "c", "q", "b"]
    assert not ws.move(tasks, a, -1, kinds)        # 맨 위
    assert not ws.move(tasks, q, 1, ("분기별",))    # 묶음에 하나뿐


def test_history_last_month_only(tmp_path):
    import datetime as dt
    import ui_kit
    now = dt.datetime.now()
    old = (now - dt.timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")
    new = (now - dt.timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    (tmp_path / "작성이력_x.csv").write_text(f"시각,서식\n{old},옛것\n{new},새것\n", encoding="utf-8-sig")
    assert [r["서식"] for r in ui_kit.read_history(str(tmp_path))] == ["새것"]
    assert len(ui_kit.read_history(str(tmp_path), days=None)) == 2
