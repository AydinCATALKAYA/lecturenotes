from pathlib import Path

from lecturenotes import transcript
from lecturenotes.render import _md
from lecturenotes.util import clock, slugify


def test_clock_floors_and_adds_hours():
    assert clock(0) == "00:00"
    assert clock(59.9) == "00:59"
    assert clock(3725) == "1:02:05"


def test_slugify_transliterates_turkish():
    assert slugify("İnsan Bilgisayar Etkileşimi – Ders 5") == "insan-bilgisayar-etkilesimi-ders-5"
    assert slugify("???") == "video"


def test_parse_srt(tmp_path: Path):
    path = tmp_path / "t.srt"
    path.write_text("1\n00:00:01,500 --> 00:00:04,000\nHello <i>there</i>\n\n2\n00:01:00,000 --> 00:01:02,250\nBye\n",
                    encoding="utf-8")
    segments = transcript.from_file(path)["segments"]
    assert segments == [{"start": 1.5, "end": 4.0, "text": "Hello there"},
                        {"start": 60.0, "end": 62.25, "text": "Bye"}]


def test_parse_timestamped_lines_joins_continuations(tmp_path: Path):
    path = tmp_path / "t.txt"
    path.write_text("[0:05] first line\ncontinued here\n[1:02:03] later\n", encoding="utf-8")
    segments = transcript.from_file(path)["segments"]
    assert segments[0] == {"start": 5.0, "end": 3723.0, "text": "first line continued here"}
    assert segments[1]["start"] == 3723.0 and segments[1]["text"] == "later"


def test_save_writes_srt_and_txt(tmp_path: Path):
    doc = {"source": "file", "segments": [{"start": 61.2, "end": 63.0, "text": "Hi"}]}
    transcript.save(doc, tmp_path)
    assert (tmp_path / "transcript.txt").read_text(encoding="utf-8") == "[01:01] Hi\n"
    assert "00:01:01,200 --> 00:01:03,000" in (tmp_path / "transcript.srt").read_text(encoding="utf-8")


def test_markdown_terms_and_tables():
    html = str(_md("Synapse ((synapse))\n\n| a | b |\n| --- | --- |\n| 1 | 2 |"))
    assert '<span class="term">synapse</span>' in html
    assert '<div class="table-wrap"><table>' in html
    assert str(_md("just **bold**", inline=True)) == "just <strong>bold</strong>"
