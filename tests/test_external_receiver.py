import pytest

import doc_template as dtpl
import homnet_draft as hd

ROWS = [
    ["a", "남구", ["남구", ""]],
    ["b", "남구시설공단", ["남구시설공단", ""]],
    ["c", "북구", ["북구", ""]],
]


def test_target_drops_region():
    assert hd.external_target("전남광주통합특별시남구") == "남구"
    assert hd.external_target("전남광주통합특별시 남구") == "남구"
    assert hd.external_target("남구") == "남구"
    assert hd.external_target("전남광주통합특별시") == "전남광주통합특별시"


def test_pick_exact_not_longer_name():
    assert hd.pick_external_row("남구", ROWS)[0] == "a"
    assert hd.pick_external_row("남구 시설공단", ROWS)[0] == "b"


def test_pick_refuses_duplicates():
    with pytest.raises(hd.DraftError, match="2곳"):
        hd.pick_external_row("남구", ROWS + [["d", "남구", ["남구", ""]]])


def test_pick_refuses_partial_match():
    with pytest.raises(hd.DraftError, match="비슷한 기관: 남구시설공단"):
        hd.pick_external_row("시설공단", ROWS)


def test_pick_no_result():
    with pytest.raises(hd.DraftError, match="찾지 못했습니다"):
        hd.pick_external_row("없는기관", [])


def test_template_header_round_trip():
    text = "제목: 안내\n수신자: {이름}\n구분: 기타\n수신자찾기: 외부유통문서\n---\n본문"
    t = dtpl.parse(text)
    assert t.external_receiver
    assert dtpl.parse(dtpl.dump(t)).external_receiver
    assert not dtpl.parse("제목: 안내\n수신자: {이름}\n---\n본문").external_receiver
