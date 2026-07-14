"""chaptr.web.chapters の parse / format（デスクトップ版と互換）のテスト"""

from chaptr.web import chapters as chap


def test_parse_time_str_variants():
    assert chap.parse_time_str("1:23:45.678") == ((1 * 3600 + 23 * 60 + 45) * 1000 + 678)
    assert chap.parse_time_str("1:23:45") == (1 * 3600 + 23 * 60 + 45) * 1000
    assert chap.parse_time_str("23:45") == (23 * 60 + 45) * 1000
    assert chap.parse_time_str("12:34.500") == (12 * 60 + 34) * 1000 + 500


def test_format_time_ms():
    assert chap.format_time_ms(0) == "0:00:00.000"
    assert chap.format_time_ms((1 * 3600 + 2 * 60 + 3) * 1000 + 456) == "1:02:03.456"
    assert chap.format_time_ms(-100) == "0:00:00.000"  # 負はクランプ


def test_parse_chapters_skips_comments_and_sorts():
    text = (
        "# source: big.mov\n"
        "# created: 2026-07-14T00:00:00\n"
        "0:12:34.567 Second\n"
        "\n"
        "0:00:00.000 First\n"
        "0:45:00.000 --休憩\n"
    )
    chs = chap.parse_chapters_text(text)
    assert [c.title for c in chs] == ["First", "Second", "--休憩"]
    assert chs[0].time_ms == 0
    assert chs[2].is_excluded is True


def test_format_roundtrip_matches_desktop_format():
    chs = [chap.Chapter(0, "Opening"), chap.Chapter(754500, "Next")]
    text = chap.format_chapters_text(chs, source_name="big.mov", created="2026-07-14T10:00:00")
    lines = text.strip().splitlines()
    assert lines[0] == "# source: big.mov"
    assert lines[1] == "# created: 2026-07-14T10:00:00"
    assert lines[2] == "0:00:00.000 Opening"
    assert lines[3] == "0:12:34.500 Next"
    # 往復
    assert [c.title for c in chap.parse_chapters_text(text)] == ["Opening", "Next"]


def test_format_without_header():
    text = chap.format_chapters_text([chap.Chapter(0, "X")])
    assert not text.startswith("#")
    assert text.strip() == "0:00:00.000 X"


def test_json_roundtrip():
    chs = [chap.Chapter(5000, "B"), chap.Chapter(1000, "A")]
    js = chap.chapters_to_json(chs)
    assert js[0]["title"] == "A" and js[0]["time_str"] == "0:00:01.000"
    back = chap.chapters_from_json(js)
    assert [c.title for c in back] == ["A", "B"]


def test_json_from_time_str_only():
    back = chap.chapters_from_json([{"time_str": "0:00:02.000", "title": "T"}])
    assert back[0].time_ms == 2000


def test_json_from_ignores_missing_time():
    back = chap.chapters_from_json([{"title": "no time"}, {"time_ms": 0, "title": "ok"}])
    assert [c.title for c in back] == ["ok"]
