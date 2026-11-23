import pdf_import as pi
import work_schedule as ws


def test_join_chars_orders_by_position_and_spaces():
    # '명도(주택)' 의 괄호가 뒤섞여 들어와도 x 위치대로 잇고, 두 번 찍힌 글자는 하나만
    chars = [(30, 100, 40, 112, "("), (10, 100, 20, 112, "명"), (20, 100, 30, 112, "도"),
             (40, 100, 50, 112, "주"), (50, 100, 60, 112, "택"), (60, 100, 70, 112, ")"),
             (10, 100, 20, 112, "명"),
             (10, 130, 20, 142, "끝"), (25, 130, 30, 142, ".")]
    assert pi.join_words(chars) == ["명도(주택)", "끝 ."]


def test_mydocs_store_starts_empty(tmp_path):
    p = str(tmp_path / "my.json")
    assert ws.load(p) == []
    t = ws.new_task("08. 입주자격심사 결과", "매월")
    t["tpl"] = "08_입주자격심사.txt"
    ws.save([t], p)
    got = ws.load(p)
    assert got[0]["tpl"] == "08_입주자격심사.txt"


def test_migrate_copies_old_data_once(tmp_path):
    import json
    import paths
    old, new = tmp_path / "old", tmp_path / "new"
    (old / "서식").mkdir(parents=True)
    (old / "서식" / "a.txt").write_text("x", encoding="utf-8")
    (old / "browser").mkdir()
    (old / "settings.json").write_text(json.dumps({"design": {"photo": str(old / "design_photo.jpg")}},
                                                  ensure_ascii=False), encoding="utf-8")
    assert paths.migrate(str(old), str(new))
    assert (new / "서식" / "a.txt").exists() and not (new / "browser").exists()
    got = json.loads((new / "settings.json").read_text(encoding="utf-8"))
    assert got["design"]["photo"] == str(new / "design_photo.jpg")
    assert not paths.migrate(str(old), str(new))          # 두 번째는 하지 않는다
