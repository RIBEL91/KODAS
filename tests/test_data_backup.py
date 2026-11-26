import json
import os
import zipfile

import pytest

import data_backup
import paths


def _setup(tmp_path, monkeypatch, name):
    root = tmp_path / name
    root.mkdir()
    monkeypatch.setattr(paths, "user_dir", lambda: str(root))
    monkeypatch.setattr(paths, "data_dir", lambda: str(root))
    return root


def test_export_import_roundtrip(tmp_path, monkeypatch):
    a = _setup(tmp_path, monkeypatch, "a")
    (a / "settings.json").write_text(json.dumps({"complex_info": {"관리소": "가나"}}), encoding="utf-8")
    (a / "서식").mkdir()
    (a / "서식" / "01_내 서식.txt").write_text("제목: 내것\n---\n본문", encoding="utf-8")
    (a / "logs").mkdir()
    (a / "logs" / "x.log").write_text("로그", encoding="utf-8")
    z = tmp_path / "내데이터.zip"
    assert data_backup.export_zip(str(z)) == 2
    names = zipfile.ZipFile(z).namelist()
    assert "서식/01_내 서식.txt" in names and not any(n.startswith("logs") for n in names)

    b = _setup(tmp_path, monkeypatch, "b")
    (b / "settings.json").write_text("{}", encoding="utf-8")
    (b / "서식").mkdir()
    (b / "서식" / "99_지울것.txt").write_text("x", encoding="utf-8")
    n, backup = data_backup.import_zip(str(z))
    assert n == 2 and os.path.isfile(backup)
    assert json.loads((b / "settings.json").read_text(encoding="utf-8"))["complex_info"]["관리소"] == "가나"
    assert sorted(os.listdir(b / "서식")) == ["01_내 서식.txt"]      # 서식 폴더는 통째로 바뀐다
    assert "settings.json" in zipfile.ZipFile(backup).namelist()     # 등록 전 데이터는 백업


def test_rejects_other_zip(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "a")
    z = tmp_path / "other.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("settings.json", "{}")
    with pytest.raises(data_backup.DataError):
        data_backup.check_zip(str(z))


def test_wipe_removes_everything_but_keeps_folder(tmp_path):
    import data_backup
    (tmp_path / "서식" / "임대").mkdir(parents=True)
    (tmp_path / "서식" / "임대" / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "백업").mkdir()
    (tmp_path / "백업" / "old.zip").write_bytes(b"z")
    assert data_backup.wipe(str(tmp_path)) == []
    assert tmp_path.exists() and [x.name for x in tmp_path.iterdir()] == ["초기화함.txt"]   # 초기화 표시만


def test_after_reset_nothing_comes_back(tmp_path, monkeypatch):
    """초기화 뒤: 바탕화면 관계철에서 자격검증 기록을 다시 가져오지 않고, 일정표는 기록 없이 하나만."""
    import data_backup
    import paths
    import verify_log as vl
    import work_schedule as ws
    monkeypatch.setattr(paths, "user_dir", lambda: str(tmp_path))
    monkeypatch.setattr(paths, "data_dir", lambda: str(tmp_path))
    assert not paths.was_reset()
    data_backup.wipe(str(tmp_path))
    assert paths.was_reset()
    assert vl.default_book() == ""
    assert ws.load_boards() == []
    assert ws.load(ws.merged_path(), ws.merged_defaults) == []


def test_auto_backup_monthly_and_keeps_recent(tmp_path, monkeypatch):
    import datetime as dt
    import os
    import data_backup
    import paths
    data, out = tmp_path / "data", tmp_path / "auto"
    data.mkdir(); out.mkdir()
    monkeypatch.setattr(paths, "user_dir", lambda: str(data))
    monkeypatch.setattr(paths, "data_dir", lambda: str(data))
    assert data_backup.auto_backup(str(out)) is None            # 설정 없음(처음 상태) → 만들지 않음
    (data / "settings.json").write_text("{}", encoding="utf-8")
    t0 = dt.datetime(2026, 1, 1, 9, 0)
    first = data_backup.auto_backup(str(out), now=t0)
    assert first and os.path.exists(first)
    os.utime(first, (t0.timestamp(), t0.timestamp()))
    assert data_backup.auto_backup(str(out), now=t0 + dt.timedelta(days=10)) is None   # 한 달 안 됨
    for m in range(1, 15):                                       # 매달 → 최근 12개만 남는다
        t = t0 + dt.timedelta(days=31 * m)
        p = data_backup.auto_backup(str(out), now=t)
        assert p
        os.utime(p, (t.timestamp(), t.timestamp()))
    assert len(data_backup.auto_list(str(out))) == data_backup.AUTO_KEEP
    assert data_backup.check_zip(data_backup.auto_list(str(out))[-1])["names"] == ["settings.json"]
