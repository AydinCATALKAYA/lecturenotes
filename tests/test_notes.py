from pathlib import Path

import pytest

from lecturenotes import render, study
from lecturenotes.writer import _attach_transcript_errors, _normalise_plan

SEGMENTS = {
    "video": {"name": "lecture.mp4", "duration": 180.0},
    "kind": "slides",
    "slides": [
        {"no": 1, "start": 0.0, "end": 60.0, "image": None, "transcript": []},
        {"no": 2, "start": 60.0, "end": 120.0, "image": None, "transcript": []},
        {"no": 3, "start": 120.0, "end": 180.0, "image": None, "transcript": []},
    ],
}


def test_normalise_plan_covers_every_segment_once_in_order():
    plan = {"parts": [
        {"title": "B", "sections": [{"slides": [9, 10], "title": "x"}, {"slides": [1, 2, 3, 4, 5, 6, 7, 8], "title": "y"}]},
        {"title": "C", "sections": [{"slides": [12, 12, 13], "title": "dup"}, {"slides": [99], "title": "unknown"}]},
    ]}
    parts = _normalise_plan(plan, list(range(1, 15)))
    flat = [n for part in parts for sec in part["sections"] for n in sec["slides"]]
    assert flat == list(range(1, 15))
    assert all(len(sec["slides"]) <= 3 for part in parts for sec in part["sections"])


def test_transcript_errors_must_exist_in_transcript():
    by_no = {slide["no"]: slide for slide in SEGMENTS["slides"]}
    parts = [{"title": None, "sections": [{"slides": [1], "title": "a"}, {"slides": [2, 3], "title": "b"}]}]
    errors = [
        {"time": "00:30", "heard": "Bettina", "correct": "retina", "body": "Bettina → retina"},
        {"time": "02:10", "heard": "Boba", "correct": "Weber", "body": "Boba → Weber"},
        {"time": "02:20", "heard": "invented", "correct": "x", "body": "not in the transcript"},
    ]
    attached = _attach_transcript_errors(parts, errors, by_no, "the Bettina ... Boba's law")
    assert attached == 2
    assert [c["body"] for c in parts[0]["sections"][0]["callouts"]] == ["Bettina → retina"]
    assert [c["body"] for c in parts[0]["sections"][1]["callouts"]] == ["Boba → Weber"]


def test_note_context_takes_times_from_slides(tmp_path: Path):
    note = {"language": "en", "parts": [{"title": "Part", "sections": [
        {"slides": [2, 3], "title": "Middle", "content": "text", "callouts": [{"type": "extra", "body": "more"}]}]}]}
    context = render._context(tmp_path, note, SEGMENTS)
    section = context["parts"][0]["sections"][0]
    assert section["time_label"] == "01:00–03:00"
    assert section["callouts"][0]["title"] == "Additional context"


def test_note_rejects_unknown_slides(tmp_path: Path):
    note = {"parts": [{"sections": [{"slides": [7], "title": "Nope", "content": "x"}]}]}
    with pytest.raises(render.NoteError):
        render._context(tmp_path, note, SEGMENTS)


def test_study_context_splits_visible_and_folded_content(tmp_path: Path):
    doc = {"language": "en", "parts": [{"title": None, "sections": [{
        "slides": [1], "title": "Intro", "idea": "One idea.", "explain": "Short text.", "details": "Long detail text.",
        "callouts": [{"type": "key", "body": "Key"}, {"type": "correction", "body": "Fix"}],
        "checks": [{"q": "Why?", "a": "Because."}],
    }]}], "cards": [{"front": "F", "back": "B"}]}
    context = study._context(tmp_path, doc, SEGMENTS)
    section = context["parts"][0]["sections"][0]
    assert [c["type"] for c in section["key_callouts"]] == ["key"]
    assert [c["type"] for c in section["more_callouts"]] == ["correction"]
    assert context["core_words"] < context["all_words"]
    assert context["cards"] == [{"front": "F", "back": "B"}]
