import doc_template as dtpl
import paths
import similar


def _all():
    items, _ = dtpl.load_all(paths.template_dir())
    return list(enumerate(items))


def test_title_match_ranks_first():
    found = similar.search(_all(), "승강기")
    assert found, "승강기 서식이 있어야 한다"
    assert all("승강기" in r[1].label for r in found[:2])
    assert found[0][3] == "제목"


def test_fuzzy_without_spaces():
    # 띄어쓰기·낱말이 달라도 비슷한 서식을 찾는다
    labels = [r[1].label for r in similar.search(_all(), "승강기점검")]
    assert any("승강기 자체점검" in x for x in labels)


def test_body_match_and_snippet():
    found = similar.search(_all(), "소명")
    assert found
    assert any(r[4] for r in found)          # 본문 미리보기 한 줄
    assert "{" not in "".join(r[4] for r in found)   # 빈칸 표시는 ○○로 바뀐다


def test_multi_word_and_empty():
    assert similar.search(_all(), "") == []
    many = similar.search(_all(), "관리비 공개")
    assert many and "관리비" in many[0][1].label


def test_clean_line():
    assert similar.clean_line("| {이름} 귀하 | {날짜:기한} |") == "○○ 귀하 ○○"
